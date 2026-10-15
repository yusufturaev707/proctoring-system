"""
Xost yig'uvchilari: systemd chiqishini o'qish, portlar navbati, CPU
foizlari va tezlik hisoblash. Linux manbalari soxtalashtiriladi — testlar
Windows dev mashinasida ham ishlaydi.
"""

from unittest import mock

from django.test import SimpleTestCase, override_settings

from apps.common.tests.utils import RedisStateMixin
from apps.monitoring import host, store

SYSTEMCTL_SHOW = """Id=proctoring-api.service
LoadState=loaded
ActiveState=active
SubState=running
MainPID=1234
NRestarts=2
Result=success
ActiveEnterTimestampMonotonic=1000000
MemoryCurrent=104857600
CPUUsageNSec=5000000000
TasksCurrent=81

Id=proctoring-ws.service
LoadState=loaded
ActiveState=failed
SubState=failed
MainPID=0
NRestarts=0
Result=exit-code
ActiveEnterTimestampMonotonic=0
MemoryCurrent=[not set]
CPUUsageNSec=18446744073709551615
TasksCurrent=[not set]

Id=pgbouncer.service
LoadState=not-found
ActiveState=inactive
SubState=dead
"""


class SystemdParseTests(SimpleTestCase):
    def test_parses_units_and_skips_missing_optional(self):
        specs = [
            ("proctoring-api.service", "HTTP API", "app", True),
            ("proctoring-ws.service", "WebSocket", "app", True),
            ("pgbouncer.service", "PgBouncer", "infra", False),
        ]
        with mock.patch.object(host, "IS_LINUX", True), \
                mock.patch.object(host.shutil, "which", return_value="/bin/systemctl"), \
                mock.patch.object(host, "_unit_specs", return_value=specs), \
                mock.patch.object(host, "_run", return_value=SYSTEMCTL_SHOW):
            data, counters = host.services()

        units = {unit["unit"]: unit for unit in data["units"]}
        self.assertNotIn("pgbouncer.service", units)  # ixtiyoriy va o'rnatilmagan
        api = units["proctoring-api.service"]
        self.assertEqual(api["restarts"], 2)
        self.assertEqual(api["memory"], 104857600)
        self.assertEqual(counters["svc.proctoring-api.service.cpu_ns"], 5e9)
        ws = units["proctoring-ws.service"]
        self.assertEqual(ws["active_state"], "failed")
        self.assertIsNone(ws["memory"])
        self.assertIsNone(ws["uptime_s"])
        self.assertNotIn("svc.proctoring-ws.service.cpu_ns", counters)  # UINT64_MAX = qiymat yo'q

    def test_glob_resolves_postgres_cluster(self):
        listing = "postgresql@15-main.service loaded active running PostgreSQL Cluster 15-main\n"
        with mock.patch.object(host, "_run", return_value=listing):
            resolved = host._resolve_units([("postgresql@*.service", "PostgreSQL", "infra", True)])
        self.assertEqual(resolved, [("postgresql@15-main.service", "PostgreSQL 15-main", "infra", True)])

    def test_no_systemd_on_dev(self):
        with mock.patch.object(host, "IS_LINUX", False):
            data, counters = host.services()
        self.assertEqual(data, {"available": False, "units": []})


class SocketTests(SimpleTestCase):
    @override_settings(SYSTEM_MONITOR={"PORTS": ["api:8002", "ws:8003"]})
    def test_backlog_and_established_from_proc(self):
        rows = [
            (8002, "0A", 7),   # LISTEN, 7 ta accept() kutmoqda
            (8002, "0A", 0),   # IPv6 LISTEN
            (8003, "0A", 0),
            (8003, "01", 0), (8003, "01", 0), (8003, "01", 0),
            (8002, "06", 0),   # TIME_WAIT — sanalmaydi
            (5555, "01", 0),   # kuzatilmaydigan port
        ]
        with mock.patch.object(host, "_proc_net_tcp", return_value=rows):
            data = host.sockets()
        ports = {port["name"]: port for port in data["ports"]}
        self.assertEqual(ports["api"]["backlog"], 7)
        self.assertEqual(ports["api"]["established"], 0)
        self.assertEqual(ports["ws"]["established"], 3)


class CpuRateTests(SimpleTestCase):
    def test_percentages_from_counter_deltas(self):
        rates = {
            "cpu.user": 2.0, "cpu.system": 1.0, "cpu.idle": 5.0, "cpu.iowait": 1.0, "cpu.steal": 1.0,
            "core.0.total": 1.0, "core.0.idle": 0.0,
            "core.1.total": 1.0, "core.1.idle": 1.0,
        }
        data = host.cpu_from_rates({"load": [2.0, 1.0, 1.0]}, rates)
        self.assertEqual(data["percent"], 40.0)  # 100 − idle 50 − iowait 10
        self.assertEqual(data["breakdown"]["steal"], 10.0)
        self.assertEqual(data["cores"], [100.0, 0.0])

    def test_first_sample_has_no_percent(self):
        self.assertIsNone(host.cpu_from_rates({"load": [0, 0, 0]}, {})["percent"])


class MountTests(SimpleTestCase):
    def test_longest_prefix_wins(self):
        import os
        import tempfile

        root = tempfile.mkdtemp()
        nested = os.path.join(root, "storage")
        os.makedirs(nested, exist_ok=True)
        mounts = [os.path.dirname(root) or root, root]
        self.assertEqual(host._mount_for(os.path.join(nested, "yo'q", "fayl"), mounts), root)


@override_settings(SYSTEM_MONITOR={"ENABLED": True})
class RateTrackerTests(RedisStateMixin, SimpleTestCase):
    def test_rates_between_samples(self):
        self.assertEqual(store.compute_rates("t", {"a": 10.0}, now=1000.0), ({}, 0.0))
        rates, window = store.compute_rates("t", {"a": 40.0}, now=1010.0)
        self.assertEqual(window, 10.0)
        self.assertEqual(rates, {"a": 3.0})

    def test_too_close_reuses_previous_result(self):
        store.compute_rates("t", {"a": 0.0}, now=1000.0)
        store.compute_rates("t", {"a": 100.0}, now=1010.0)
        rates, window = store.compute_rates("t", {"a": 999.0}, now=1010.5)
        self.assertEqual(rates, {"a": 10.0})

    def test_counter_reset_is_skipped(self):
        """Servis qayta ishga tushdi — hisoblagich noldan; manfiy tezlik yo'q."""
        store.compute_rates("t", {"a": 500.0, "b": 1.0}, now=1000.0)
        rates, _ = store.compute_rates("t", {"a": 5.0, "b": 11.0}, now=1010.0)
        self.assertEqual(rates, {"b": 1.0})
