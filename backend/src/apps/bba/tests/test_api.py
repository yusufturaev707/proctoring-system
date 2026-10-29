"""
Panel API: ruxsatlar, viloyat chegarasi, Console xatolarining javobi va WebSocket.
"""

import uuid
from unittest import mock

from asgiref.sync import sync_to_async
from django.core.cache import cache
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from apps.bba.client import BbaForbidden
from apps.bba.consumers import BbaConsumer
from apps.bba.models import BbaDevice, BbaJob, BbaRegion
from apps.bba.services import bba_group
from apps.bba.tests.fakes import SNAPSHOT, FakeConsole
from apps.common.tests.ws import WebsocketCommunicator
from apps.proctoring.consumers import CLOSE_FORBIDDEN
from apps.proctoring.tests import factories
from apps.proctoring.tests.test_client_api import bearer
from apps.proctoring.tests.test_consumers import access_token

BASE = "/api/v1/bba"


def make_device(bba_region=None, **kwargs) -> BbaDevice:
    return BbaDevice.objects.create(
        console_id=uuid.uuid4(), bba_region=bba_region,
        **{"hostname_code": f"BBA-{uuid.uuid4().hex[:6]}", "status": "online", **kwargs},
    )


class BbaApiTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.console = FakeConsole()
        patcher = mock.patch("apps.bba.services.get_client", return_value=self.console)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.region = factories.make_region()
        self.other_region = factories.make_region()
        self.bba_region = BbaRegion.objects.create(console_id=uuid.uuid4(), name="Toshkent", region=self.region)
        self.foreign_bba_region = BbaRegion.objects.create(
            console_id=uuid.uuid4(), name="Samarqand", region=self.other_region
        )
        self.unmapped = BbaRegion.objects.create(console_id=uuid.uuid4(), name="Bog'lanmagan")
        self.own = make_device(self.bba_region, macs=["30:C5:99:18:53:A1"])
        self.foreign = make_device(self.foreign_bba_region)
        self.loose = make_device(self.unmapped)
        self.client = APIClient()

    def as_user(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=bearer(user))
        return self.client


class AccessTests(BbaApiTestCase):
    def test_view_permission_required(self):
        user = factories.make_user(permissions=["dashboard.view"])
        self.assertEqual(self.as_user(user).get(f"{BASE}/devices/").status_code, 403)
        self.assertEqual(self.as_user(user).get(f"{BASE}/overview/").status_code, 403)

    def test_republic_user_sees_everything(self):
        user = factories.make_user(permissions=["bba.view"])
        response = self.as_user(user).get(f"{BASE}/devices/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["count"], 3)
        overview = self.as_user(user).get(f"{BASE}/overview/").json()["data"]
        self.assertEqual((overview["total"], overview["unmapped_regions"]), (3, 1))

    def test_region_user_sees_only_mapped_region(self):
        user = factories.make_user(permissions=["bba.view"], region=self.region)
        client = self.as_user(user)
        ids = [row["id"] for row in client.get(f"{BASE}/devices/").json()["data"]["results"]]
        self.assertEqual(ids, [self.own.pk])
        self.assertEqual(client.get(f"{BASE}/devices/{self.foreign.pk}/").status_code, 404)
        regions = client.get(f"{BASE}/regions/").json()["data"]
        self.assertEqual([row["id"] for row in regions], [self.bba_region.pk])
        self.assertNotIn("unmapped_regions", client.get(f"{BASE}/overview/").json()["data"])

    def test_region_mapping_is_republic_only(self):
        region_admin = factories.make_user(permissions=["bba.view", "bba.manage"], region=self.region)
        response = self.as_user(region_admin).patch(
            f"{BASE}/regions/{self.bba_region.pk}/", {"region": None}, format="json"
        )
        self.assertEqual(response.status_code, 403)
        admin = factories.make_user(permissions=["bba.view", "bba.manage"])
        response = self.as_user(admin).patch(
            f"{BASE}/regions/{self.unmapped.pk}/", {"region": self.region.pk, "name": "x"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.unmapped.refresh_from_db()
        self.assertEqual((self.unmapped.region, self.unmapped.name), (self.region, "Bog'lanmagan"))

    def test_send_job_needs_jobs_permission(self):
        viewer = factories.make_user(permissions=["bba.view", "bba.manage"])
        url = f"{BASE}/devices/{self.own.pk}/send-job/"
        payload = {"job_type": "collect_inventory", "params": {}}
        self.assertEqual(self.as_user(viewer).post(url, payload, format="json").status_code, 403)
        operator = factories.make_user(permissions=["bba.view", "bba.jobs"])
        response = self.as_user(operator).post(url, payload, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["jobs"][0]["issued_by_username"], operator.username)

    def test_region_user_cannot_send_job_to_foreign_device(self):
        operator = factories.make_user(permissions=["bba.view", "bba.jobs"], region=self.region)
        response = self.as_user(operator).post(
            f"{BASE}/devices/bulk-send-job/",
            {"ids": [self.own.pk, self.foreign.pk], "job_type": "collect_inventory"}, format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual([cid for cid, _ in [self.console.created_jobs[0]]], [str(self.own.console_id)])
        self.assertEqual(list(BbaJob.objects.values_list("device_id", flat=True)), [self.own.pk])

    def test_dangerous_job_without_confirm_is_400(self):
        operator = factories.make_user(permissions=["bba.view", "bba.jobs"])
        response = self.as_user(operator).post(
            f"{BASE}/devices/{self.own.pk}/send-job/", {"job_type": "shutdown_computer"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.console.created_jobs, [])

    def test_console_refusal_is_explained(self):
        operator = factories.make_user(permissions=["bba.view", "bba.jobs"])
        self.console.error = BbaForbidden("BBA Console ruxsat bermadi: forbidden")
        response = self.as_user(operator).post(
            f"{BASE}/devices/{self.own.pk}/send-job/", {"job_type": "collect_inventory"}, format="json"
        )
        self.assertEqual(response.status_code, 403)
        error = response.json()["error"]
        self.assertEqual(error["code"], "bba_forbidden")
        self.assertIn("ruxsat bermadi", error["message"])

    def test_import_needs_devices_manage_too(self):
        self.own.system_uuid = "124023EC-FFF9-9177-3E7D-30C5991853A1"
        self.own.primary_mac = "30:C5:99:18:53:A1"
        self.own.save()
        zone = factories.make_zone(region=self.region)
        url = f"{BASE}/devices/{self.own.pk}/import/"
        only_bba = factories.make_user(permissions=["bba.view", "bba.manage"])
        self.assertEqual(self.as_user(only_bba).post(url, {"zone": zone.pk}, format="json").status_code, 403)
        admin = factories.make_user(permissions=["bba.view", "bba.manage", "devices.manage"])
        response = self.as_user(admin).post(url, {"zone": zone.pk}, format="json")
        self.assertEqual(response.status_code, 201)
        detail = self.as_user(admin).get(f"{BASE}/devices/{self.own.pk}/").json()["data"]
        self.assertEqual(detail["computer_detail"]["id"], response.json()["data"]["computer"])

    def test_filters(self):
        user = factories.make_user(permissions=["bba.view"])
        client = self.as_user(user)

        def ids(query):
            return [row["id"] for row in client.get(f"{BASE}/devices/?{query}").json()["data"]["results"]]

        self.assertEqual(ids("mac=30-c5-99-18-53-a1"), [self.own.pk])
        self.assertEqual(ids("mac=zz"), [])
        self.foreign.status = "offline_graceful"
        self.foreign.save()
        self.assertEqual(ids("status=offline_graceful"), [self.foreign.pk])
        self.assertEqual(len(ids("linked=false")), 3)
        self.assertEqual(ids("linked=true"), [])

    def test_detail_returns_inventory_and_refresh(self):
        self.console.inventories[str(self.own.console_id)] = {"snapshot": SNAPSHOT}
        user = factories.make_user(permissions=["bba.view"])
        client = self.as_user(user)
        self.assertIsNone(client.get(f"{BASE}/devices/{self.own.pk}/").json()["data"]["inventory"])
        data = client.post(f"{BASE}/devices/{self.own.pk}/refresh-inventory/").json()["data"]
        self.assertEqual(data["inventory"]["OSVersion"], SNAPSHOT["OSVersion"])
        self.assertEqual(data["system_uuid"], "124023EC-FFF9-9177-3E7D-30C5991853A1")
        # List javobida og'ir JSON yo'q.
        row = client.get(f"{BASE}/devices/").json()["data"]["results"][0]
        self.assertNotIn("inventory", row)

    def test_tree_groups_by_region_and_room_with_counts(self):
        from apps.bba.models import BbaRoom

        room = BbaRoom.objects.create(console_id=uuid.uuid4(), name="Class-110", bba_region=self.bba_region)
        self.own.room = room
        self.own.save()
        make_device(self.bba_region, room=room, status="offline_unexpected")
        make_device(self.bba_region, status="offline_graceful")  # xonasiz
        make_device(self.bba_region, room=room, is_visible=False)  # Console'da ko'rinmaydi
        user = factories.make_user(permissions=["bba.view"])
        regions = self.as_user(user).get(f"{BASE}/devices/tree/").json()["data"]["regions"]
        own = next(item for item in regions if item["id"] == self.bba_region.pk)
        self.assertEqual((own["total"], own["region_name"]), (3, self.region.name))
        self.assertEqual([r["name"] for r in own["rooms"]], ["Class-110", "Xonaga biriktirilmagan"])
        class_room = own["rooms"][0]
        self.assertEqual(class_room["total"], 2)
        self.assertEqual(
            (class_room["by_status"]["online"], class_room["by_status"]["offline_unexpected"]), (1, 1)
        )

    def test_tree_and_by_room_respect_region_scope(self):
        user = factories.make_user(permissions=["bba.view"], region=self.region)
        client = self.as_user(user)
        regions = client.get(f"{BASE}/devices/tree/").json()["data"]["regions"]
        self.assertEqual([item["id"] for item in regions], [self.bba_region.pk])
        rows = client.get(f"{BASE}/devices/by-room/?bba_region={self.foreign_bba_region.pk}").json()["data"]
        self.assertEqual(rows["results"], [])
        rows = client.get(f"{BASE}/devices/by-room/?bba_region={self.bba_region.pk}").json()["data"]
        self.assertEqual([row["id"] for row in rows["results"]], [self.own.pk])
        self.assertEqual(rows["results"][0]["region_name"], self.region.name)

    def test_by_room_needs_region_and_supports_unassigned(self):
        orphan = make_device(None)
        user = factories.make_user(permissions=["bba.view"])
        client = self.as_user(user)
        self.assertEqual(client.get(f"{BASE}/devices/by-room/").status_code, 400)
        rows = client.get(f"{BASE}/devices/by-room/?bba_region=none").json()["data"]["results"]
        self.assertEqual([row["id"] for row in rows], [orphan.pk])

    def test_job_types_catalog(self):
        user = factories.make_user(permissions=["bba.view"])
        data = self.as_user(user).get(f"{BASE}/job-types/").json()["data"]
        codes = {item["code"]: item for item in data["types"]}
        self.assertTrue(codes["shutdown_computer"]["dangerous"])
        self.assertEqual(codes["lock_system"]["params"], "features")


class BbaConsumerTests(TransactionTestCase):
    def setUp(self):
        self.region = factories.make_region()

    async def connect(self, user):
        communicator = WebsocketCommunicator(
            BbaConsumer.as_asgi(), f"/ws/bba/?token={await sync_to_async(access_token)(user)}"
        )
        return communicator, await communicator.connect()

    async def test_requires_bba_view(self):
        user = await sync_to_async(factories.make_user)(permissions=["sessions.view"])
        _, (connected, code) = await self.connect(user)
        self.assertFalse(connected)
        self.assertEqual(code, CLOSE_FORBIDDEN)

    async def test_region_user_joins_only_own_group_and_gets_updates(self):
        from channels.layers import get_channel_layer

        user = await sync_to_async(factories.make_user)(permissions=["bba.view"], region=self.region)
        communicator, (connected, _) = await self.connect(user)
        self.assertTrue(connected)
        message = await communicator.receive_json_from()
        self.assertEqual(message["groups"], [bba_group(self.region.pk)])

        await get_channel_layer().group_send(bba_group(self.region.pk), {
            "type": "bba.update", "kind": "status", "payload": [{"id": 1, "status": "online"}],
        })
        message = await communicator.receive_json_from()
        self.assertEqual(message, {"type": "status", "payload": [{"id": 1, "status": "online"}]})
        await communicator.disconnect()

    async def test_republic_user_joins_all(self):
        user = await sync_to_async(factories.make_user)(permissions=["bba.view"])
        communicator, (connected, _) = await self.connect(user)
        self.assertTrue(connected)
        self.assertEqual((await communicator.receive_json_from())["groups"], ["bba.all"])
        await communicator.disconnect()
