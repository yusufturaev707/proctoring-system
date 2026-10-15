"""
Muammolar ro'yxati: SLO chegaralari va "nima qilish kerak" qoidalari.

Kirish — tayyor snapshot lug'ati, ya'ni qoidalar haqiqiy servissiz
tekshiriladi.
"""

from django.test import SimpleTestCase

from apps.monitoring.services import _overall, problems
from apps.monitoring.thresholds import level


def codes(snapshot):
    return {item["code"]: item["severity"] for item in problems(snapshot)}


class ThresholdTests(SimpleTestCase):
    def test_higher_is_worse(self):
        self.assertEqual(level("cpu_pct", 50), "ok")
        self.assertEqual(level("cpu_pct", 70), "warning")
        self.assertEqual(level("cpu_pct", 95), "critical")
        self.assertEqual(level("cpu_pct", None), "unknown")

    def test_lower_is_worse(self):
        self.assertEqual(level("disk_days_left", 90), "ok")
        self.assertEqual(level("disk_days_left", 20), "warning")
        self.assertEqual(level("disk_days_left", 3), "critical")


class ProblemRuleTests(SimpleTestCase):
    def test_healthy_snapshot_has_no_problems(self):
        snapshot = {
            "cpu": {"percent": 20, "breakdown": {"steal": 0, "iowait": 1}, "load": [1, 1, 1], "load_per_core": 0.1},
            "memory": {"percent": 40, "swap_total": 0},
            "redis": {"maxmemory_policy": "noeviction", "maxmemory": 1 << 30, "memory_percent": 10, "rates": {}},
        }
        self.assertEqual(problems(snapshot), [])
        self.assertEqual(_overall([]), "ok")

    def test_esxi_steal_is_reported(self):
        found = codes({"cpu": {"percent": 40, "breakdown": {"steal": 12}}})
        self.assertEqual(found["cpu_steal"], "critical")

    def test_single_core_saturation_with_idle_total(self):
        found = codes({"cpu": {"percent": 30, "cores": [100, 5, 3, 2], "breakdown": {}}})
        self.assertEqual(found["core_saturated"], "warning")

    def test_swap_in_is_critical(self):
        found = codes({"memory": {"percent": 70, "swap_in_bps": 4096, "swap_total": 1}})
        self.assertEqual(found["swap_in"], "critical")

    def test_redis_eviction_policy_is_critical(self):
        """`allkeys-lru` sessiya tokenlarini o'chiradi (CLAUDE.md)."""
        found = codes({"redis": {"maxmemory_policy": "allkeys-lru", "maxmemory": 1, "rates": {}}})
        self.assertEqual(found["redis_policy"], "critical")

    def test_stale_ingest_task_is_critical_other_is_warning(self):
        found = codes({"celery": {"tracking": True, "queues": [], "tasks": [
            {"name": "flush-event-buffer", "queue": "ingest", "health": "stale", "last_run_age_s": 600},
            {"name": "probe-cameras", "queue": "maintenance", "health": "stale", "last_run_age_s": 600},
        ]}})
        self.assertEqual(found["stale_flush-event-buffer"], "critical")
        self.assertEqual(found["stale_probe-cameras"], "warning")

    def test_failed_required_unit_is_critical(self):
        found = codes({"services": {"units": [
            {"unit": "proctoring-api.service", "label": "HTTP API", "required": True,
             "load_state": "loaded", "active_state": "failed", "sub_state": "failed", "restarts": 0},
            {"unit": "pgbouncer.service", "label": "PgBouncer", "required": False,
             "load_state": "loaded", "active_state": "active", "sub_state": "running", "restarts": 3},
        ]}})
        self.assertEqual(found["unit_down"], "critical")
        self.assertEqual(found["unit_restarted"], "warning")

    def test_http_errors_need_enough_requests(self):
        """10 so'rovdan 1 tasi 5xx — statistika emas, tasodif."""
        few = codes({"requests": {"5m": {"count": 10, "error_pct": 10.0, "p95_ms": 50}}})
        many = codes({"requests": {"5m": {"count": 1000, "error_pct": 2.0, "p95_ms": 50}}})
        self.assertNotIn("http_5xx", few)
        self.assertEqual(many["http_5xx"], "critical")

    def test_disk_forecast(self):
        found = codes({"disks": {"mounts": [{
            "mount": "/srv", "percent": 50, "free": 10 << 30, "contains": ["screenshots"],
            "days_left": 5, "growth_per_day": 2 << 30,
        }]}})
        self.assertEqual(found["disk_forecast"], "critical")

    def test_critical_sorted_first(self):
        items = problems({
            "memory": {"percent": 85, "swap_total": 0},
            "errors": {"postgres": "OperationalError"},
        })
        self.assertEqual(items[0]["severity"], "critical")
        self.assertEqual(_overall(items), "critical")
