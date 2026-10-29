"""
Sinxronizatsiya, bog'lash, import va job — Console `FakeConsole` bilan.
"""

import uuid
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from apps.bba import services
from apps.bba.models import BbaDevice, BbaJob, BbaRegion, BbaRoom
from apps.bba.tests.fakes import SNAPSHOT, FakeConsole, console_device
from apps.devices.models import Computer
from apps.proctoring.models import AuditLog
from apps.proctoring.tests import factories

UUID = "124023EC-FFF9-9177-3E7D-30C5991853A1"


def new_id() -> str:
    return str(uuid.uuid4())


def fake_request(user):
    request = APIRequestFactory().post("/")
    request.user = user
    return request


class ServiceTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.console = FakeConsole()
        patcher = mock.patch("apps.bba.services.get_client", return_value=self.console)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.sent = []
        broadcast = mock.patch(
            "apps.bba.services.broadcast", side_effect=lambda kind, rows: self.sent.append((kind, rows))
        )
        broadcast.start()
        self.addCleanup(broadcast.stop)

    def sync(self):
        services.sync_tree(self.console)
        return services.sync_devices(self.console)


class SyncTests(ServiceTestCase):
    def test_tree_and_devices_are_created(self):
        a, b = new_id(), new_id()
        self.console.devices = [console_device(a), console_device(b, status="offline_graceful", code="BBA-110-4")]
        result = self.sync()
        self.assertEqual(result["created"], 2)
        region = BbaRegion.objects.get()
        room = BbaRoom.objects.get()
        self.assertEqual(room.bba_region, region)
        device = BbaDevice.objects.get(console_id=b)
        self.assertEqual((device.room, device.bba_region, device.status), (room, region, "offline_graceful"))
        self.assertIsNotNone(device.status_changed_at)

    def test_only_changes_are_written_and_broadcast(self):
        a, b = new_id(), new_id()
        self.console.devices = [console_device(a), console_device(b)]
        self.sync()
        self.sent.clear()

        result = services.sync_devices(self.console)
        self.assertEqual((result["updated"], result["status_changed"]), (0, 0))
        self.assertEqual(self.sent, [])

        self.console.devices[0]["Status"] = "offline_unexpected"
        result = services.sync_devices(self.console)
        self.assertEqual(result["status_changed"], 1)
        kind, rows = self.sent[-1]
        device = BbaDevice.objects.get(console_id=a)
        self.assertEqual(kind, "status")
        self.assertEqual([(r["id"], r["status"]) for r in rows], [(device.pk, "offline_unexpected")])

    def test_missing_device_is_hidden_not_deleted(self):
        a, b = new_id(), new_id()
        self.console.devices = [console_device(a), console_device(b)]
        self.sync()
        self.console.devices = self.console.devices[:1]
        result = services.sync_devices(self.console)
        self.assertEqual(result["missing"], 1)
        hidden = BbaDevice.objects.get(console_id=b)
        self.assertFalse(hidden.is_visible)
        self.assertIsNotNone(hidden.missing_since)
        # Qaytsa — yana ko'rinadi.
        self.console.devices.append(console_device(b))
        services.sync_devices(self.console)
        hidden.refresh_from_db()
        self.assertTrue(hidden.is_visible)
        self.assertIsNone(hidden.missing_since)

    def test_unknown_room_triggers_tree_sync(self):
        services.sync_tree(self.console)
        room_id = new_id()
        self.console.rooms_data.append({"ID": room_id, "RegionID": self.console.regions_data[0]["ID"],
                                        "Name": "Class-111"})
        self.console.devices = [console_device(new_id(), room=room_id)]
        services.sync_devices(self.console)
        self.assertEqual(BbaDevice.objects.get().room.name, "Class-111")

    def test_poll_records_state_and_errors(self):
        from apps.bba.client import BbaUnavailable

        with self.settings(BBA_CONSOLE={**self.settings_dict(), "ENABLED": True}):
            self.console.devices = [console_device(new_id())]
            self.assertEqual(services.poll()["total"], 1)
            self.assertTrue(services.state()["ok"])
            self.console.error = BbaUnavailable("Console javob bermayapti")
            self.assertIn("error", services.poll())
            state = services.state()
            self.assertFalse(state["ok"])
            self.assertEqual(state["error_code"], "bba_unavailable")
            self.assertIn("last_success_at", state)

    def settings_dict(self):
        from django.conf import settings

        return settings.BBA_CONSOLE


class LinkAndInventoryTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.console_id = new_id()
        self.console.devices = [console_device(self.console_id)]
        self.console.inventories[self.console_id] = {"snapshot": SNAPSHOT, "changes": ["cpu"]}
        self.sync()
        self.device = BbaDevice.objects.get()

    def test_inventory_stores_ids_and_links_by_pair(self):
        # UUID bir xil, MAC boshqa — boshqa mashina (bir partiyadagi plata).
        stranger = factories.make_computer(machine_uuid=UUID, mac_address="AA:AA:AA:AA:AA:01")
        own = factories.make_computer(machine_uuid=UUID, mac_address="C4:62:37:01:DE:1A")
        device = services.fetch_inventory(self.device, self.console)
        self.assertEqual(device.system_uuid, UUID)
        self.assertEqual(device.primary_mac, "30:C5:99:18:53:A1")
        self.assertEqual(device.computer_id, own.pk)
        self.assertNotEqual(device.computer_id, stranger.pk)
        self.assertEqual(device.inventory["Hostname"], "BBA-110-3")

    def test_no_link_when_only_uuid_matches(self):
        factories.make_computer(machine_uuid=UUID, mac_address="AA:AA:AA:AA:AA:02")
        factories.make_computer(machine_uuid=UUID, mac_address="AA:AA:AA:AA:AA:03")
        self.assertIsNone(services.fetch_inventory(self.device, self.console).computer_id)

    def test_deleted_computer_unlinks(self):
        computer = factories.make_computer(machine_uuid=UUID, mac_address="30:C5:99:18:53:A1")
        services.fetch_inventory(self.device, self.console)
        computer.delete()
        services.link_computers()
        self.device.refresh_from_db()
        self.assertIsNone(self.device.computer_id)

    def test_null_snapshot_is_not_an_error(self):
        self.console.inventories.clear()
        device = services.fetch_inventory(self.device, self.console)
        self.assertIsNone(device.inventory)
        self.assertEqual(device.inventory_error, "")
        self.assertIsNotNone(device.inventory_fetched_at)

    def test_sync_inventories_takes_never_fetched_first(self):
        stats = services.sync_inventories(self.console)
        self.assertEqual(stats["fetched"], 1)
        # Yangisi — 6 soat ichida qayta so'ralmaydi.
        self.assertEqual(services.sync_inventories(self.console)["fetched"], 0)


class ImportTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.console_id = new_id()
        self.console.devices = [console_device(self.console_id)]
        self.console.inventories[self.console_id] = {"snapshot": SNAPSHOT}
        self.sync()
        self.device = services.fetch_inventory(BbaDevice.objects.get(), self.console)
        self.zone = factories.make_zone()
        self.admin = factories.make_user(permissions=["*"])

    def test_import_creates_computer_with_console_name(self):
        computer = services.import_computer(
            self.device, zone_id=self.zone.pk, request=fake_request(self.admin), number=7
        )
        self.assertEqual(
            (computer.machine_uuid, computer.mac_address, computer.inventory_code, computer.number),
            (UUID, "30:C5:99:18:53:A1", "BBA-110-3", 7),
        )
        self.device.refresh_from_db()
        self.assertEqual(self.device.computer, computer)
        self.assertTrue(AuditLog.objects.filter(action="bba_import_computer").exists())
        with self.assertRaises(services.BbaAlreadyLinked):
            services.import_computer(self.device, zone_id=self.zone.pk, request=fake_request(self.admin))

    def test_chosen_mac_must_be_physical(self):
        with self.assertRaises(serializers.ValidationError):
            services.import_computer(
                self.device, zone_id=self.zone.pk, request=fake_request(self.admin),
                mac_address="00-15-5D-01-02-03",
            )
        computer = services.import_computer(
            self.device, zone_id=self.zone.pk, request=fake_request(self.admin),
            mac_address="c4:62:37:01:de:1a",
        )
        self.assertEqual(computer.mac_address, "C4:62:37:01:DE:1A")

    def test_taken_name_falls_back_to_auto_code(self):
        factories.make_computer(inventory_code="BBA-110-3")
        computer = services.import_computer(self.device, zone_id=self.zone.pk, request=fake_request(self.admin))
        self.assertTrue(computer.inventory_code.startswith("AUTO-124023EC"))

    def test_region_admin_cannot_import_into_foreign_zone(self):
        region_admin = factories.make_user(permissions=["devices.manage"], region=factories.make_region())
        with self.assertRaises(serializers.ValidationError):
            services.import_computer(self.device, zone_id=self.zone.pk, request=fake_request(region_admin))
        self.assertFalse(Computer.objects.filter(machine_uuid=UUID).exists())

    def test_bulk_import_reports_each_device(self):
        other = BbaDevice.objects.create(console_id=new_id(), hostname_code="BBA-110-9")
        results = services.bulk_import([self.device, other], zone_id=self.zone.pk,
                                       request=fake_request(self.admin))
        self.assertEqual([row["status"] for row in results], ["created", "error"])
        self.assertIn("System UUID", results[1]["message"])


class JobTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.ids = [new_id(), new_id()]
        self.console.devices = [console_device(cid, code=f"BBA-{i}") for i, cid in enumerate(self.ids)]
        self.sync()
        self.devices = list(BbaDevice.objects.order_by("hostname_code"))
        self.admin = factories.make_user(permissions=["*"])

    def test_single_job_records_who_sent_it(self):
        [job] = services.dispatch_job(
            self.devices[:1], job_type="restart_computer", params={"ignored": 1}, confirm=True,
            request=fake_request(self.admin),
        )
        self.assertEqual((job.console_job_id, job.status, job.issued_by), ("job-1", "sent", self.admin))
        console_id, body = self.console.created_jobs[0]
        self.assertEqual(console_id, self.ids[0])
        self.assertEqual(body, {"type": "restart_computer", "params": {}, "confirm": True})
        self.assertTrue(AuditLog.objects.filter(action="bba_job", meta__type="restart_computer").exists())

    def test_dangerous_job_needs_confirmation(self):
        with self.assertRaises(serializers.ValidationError):
            services.dispatch_job(self.devices[:1], job_type="shutdown_computer", params={},
                                  confirm=False, request=fake_request(self.admin))
        self.assertEqual(self.console.created_jobs, [])

    def test_params_are_validated(self):
        cases = [
            ("lock_system", {"features": []}),
            ("lock_system", {"features": ["keyboard"]}),
            ("run_script", {"script_type": "bash", "script_content": "ls"}),
            ("run_script", {"script_content": "   "}),
            ("manage_startup_app", {"action": "enable", "name": "X"}),
        ]
        for job_type, params in cases:
            with self.subTest(job_type=job_type, params=params):
                with self.assertRaises(serializers.ValidationError):
                    services.dispatch_job(self.devices[:1], job_type=job_type, params=params,
                                          confirm=True, request=fake_request(self.admin))

    def test_bulk_job_maps_results_per_device(self):
        self.console.bulk_response = {
            "bulk_operation_id": "bulk-7",
            "jobs": [
                {"device_id": self.ids[1], "status": "error", "error": "device offline"},
                {"device_id": self.ids[0], "job_id": "job-a", "status": "sent"},
            ],
        }
        jobs = services.dispatch_job(self.devices, job_type="collect_inventory", params={},
                                     confirm=False, request=fake_request(self.admin))
        by_device = {job.device_id: job for job in jobs}
        first, second = by_device[self.devices[0].pk], by_device[self.devices[1].pk]
        self.assertEqual((first.console_job_id, first.status, first.bulk_operation_id), ("job-a", "sent", "bulk-7"))
        self.assertEqual((second.status, second.error), ("error", "device offline"))
        self.assertIsNone(second.sent_at)

    def test_refresh_updates_status_and_result(self):
        [job] = services.dispatch_job(self.devices[:1], job_type="collect_inventory", params={},
                                      confirm=False, request=fake_request(self.admin))
        self.console.jobs_data = [{
            "JobID": "job-1", "DeviceID": self.ids[0], "Status": "done",
            "Result": {"stdout": "ok", "exit_code": 0}, "CompletedAt": "2026-10-06T14:10:08+05:00",
        }]
        self.assertEqual(services.refresh_jobs(self.console), 1)
        job.refresh_from_db()
        self.assertEqual((job.status, job.result["stdout"]), ("done", "ok"))
        self.assertIsNotNone(job.completed_at)
        self.assertEqual(self.sent[-1][0], "job")
        self.assertFalse(services.pending_jobs().exists())

    def test_bulk_job_without_ids_is_found_by_operation(self):
        self.console.bulk_response = {"bulk_operation_id": "bulk-9", "jobs": []}
        services.dispatch_job(self.devices, job_type="collect_inventory", params={},
                              confirm=False, request=fake_request(self.admin))
        self.console.jobs_data = [
            {"JobID": f"j-{i}", "BulkOperationID": "bulk-9", "DeviceID": cid, "Status": "running"}
            for i, cid in enumerate(self.ids)
        ]
        self.assertEqual(services.refresh_jobs(self.console), 2)
        self.assertEqual(
            sorted(BbaJob.objects.values_list("console_job_id", "status")),
            [("j-0", "running"), ("j-1", "running")],
        )
