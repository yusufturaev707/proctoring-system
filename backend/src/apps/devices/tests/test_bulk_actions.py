"""
Ommaviy amallar: kompyuterlarni o'chirish, qurilmalarni tasdiqlash
(`BulkSelectionMixin`).
"""

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.devices.models import Computer, DeviceToken
from apps.proctoring.models import ExamSession
from apps.proctoring.tests import factories
from apps.proctoring.tests.test_client_api import bearer


class BulkActionTests(TestCase):
    def setUp(self):
        self.region = factories.make_region()
        self.zone = factories.make_zone(region=self.region)
        self.user = factories.make_user(permissions=["devices.view", "devices.manage"])
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=bearer(self.user))

    def test_bulk_delete_by_ids_skips_computer_in_exam(self):
        free, busy, kept = (factories.make_computer(zone=self.zone) for _ in range(3))
        factories.make_session(computer=busy, status=ExamSession.Status.IN_PROGRESS)
        response = self.client.post(
            reverse("computer-bulk-delete"), {"ids": [free.id, busy.id]}, format="json"
        )
        self.assertEqual(response.json()["data"], {"deleted": 1, "skipped_in_exam": 1})
        self.assertEqual(
            set(Computer.objects.filter(deleted_at__isnull=True).values_list("id", flat=True)),
            {busy.id, kept.id},
        )

    def test_bulk_delete_all_respects_filter(self):
        other_zone = factories.make_zone(region=self.region)
        factories.make_computer(zone=self.zone)
        outside = factories.make_computer(zone=other_zone)
        url = reverse("computer-bulk-delete") + f"?zone={self.zone.id}"
        self.assertEqual(self.client.post(url, {"all": True}, format="json").json()["data"]["deleted"], 1)
        self.assertEqual(list(Computer.objects.filter(deleted_at__isnull=True)), [outside])

    def test_region_admin_cannot_touch_other_region(self):
        foreign = factories.make_computer(zone=factories.make_zone(region=factories.make_region()))
        user = factories.make_user(permissions=["devices.view", "devices.manage"], region=self.region)
        self.client.credentials(HTTP_AUTHORIZATION=bearer(user))
        data = self.client.post(reverse("computer-bulk-delete"), {"ids": [foreign.id]}, format="json")
        self.assertEqual(data.json()["data"]["deleted"], 0)
        foreign.refresh_from_db()
        self.assertIsNone(foreign.deleted_at)

    def test_empty_selection_is_rejected(self):
        response = self.client.post(reverse("computer-bulk-delete"), {"ids": []}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_bulk_approve_only_pending(self):
        pending = [
            factories.make_device(computer=factories.make_computer(zone=self.zone), status=DeviceToken.Status.PENDING)
            for _ in range(2)
        ]
        revoked = factories.make_device(
            computer=factories.make_computer(zone=self.zone), status=DeviceToken.Status.REVOKED,
        )
        response = self.client.post(reverse("device-token-bulk-approve"), {"all": True}, format="json")
        self.assertEqual(response.json()["data"], {"approved": 2, "skipped": 1})
        for device in pending:
            device.refresh_from_db()
            self.assertEqual(device.status, DeviceToken.Status.ACTIVE)
        revoked.refresh_from_db()
        self.assertEqual(revoked.status, DeviceToken.Status.REVOKED)

    def test_view_only_user_cannot_bulk(self):
        user = factories.make_user(permissions=["devices.view"])
        self.client.credentials(HTTP_AUTHORIZATION=bearer(user))
        response = self.client.post(reverse("device-token-bulk-approve"), {"all": True}, format="json")
        self.assertEqual(response.status_code, 403)
