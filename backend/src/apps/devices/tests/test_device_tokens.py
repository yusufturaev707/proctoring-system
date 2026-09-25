"""
Qurilma tokenlari — panel amallari.

Uchta shartnoma:

  * holat FAQAT `approve/` va `revoke/` orqali o'zgaradi — `PATCH`
    tasdiqlashni ham, blok sababini ham, ularning auditini ham
    chetlab o'ta olmaydi;
  * `PATCH` bilan yagona o'zgaradigan narsa — `computer` (obraz
    ko'chirilgan mashinani qayta biriktirish) va u viloyat doirasidan
    chiqa olmaydi;
  * bloklangan qurilma blokdan CHIQARILADI va eski blok izi tozalanadi.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.devices.models import DeviceToken
from apps.proctoring.models import AuditLog
from apps.proctoring.tests import factories

BASE = "/api/v1/device-tokens/"


class DeviceTokenAdminTests(TestCase):
    def setUp(self):
        self.region = factories.make_region()
        self.zone = factories.make_zone(region=self.region)
        self.computer = factories.make_computer(zone=self.zone)
        self.other_computer = factories.make_computer(zone=self.zone)
        self.device = factories.make_device(
            computer=self.computer, status=DeviceToken.Status.PENDING,
            app_version="1.0.0", hardware_fingerprint="fp-original",
        )
        self.admin = factories.make_user(
            permissions=["devices.manage", "devices.view"], region=self.region
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def _url(self, suffix=""):
        return f"{BASE}{self.device.pk}/{suffix}"

    def test_patch_cannot_change_status_or_client_reported_fields(self):
        response = self.client.patch(
            self._url(),
            {"status": "active", "app_version": "9.9.9", "hardware_fingerprint": "fake"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, DeviceToken.Status.PENDING)
        self.assertEqual(self.device.app_version, "1.0.0")
        self.assertEqual(self.device.hardware_fingerprint, "fp-original")

    def test_patch_rebinds_computer_and_is_audited(self):
        response = self.client.patch(
            self._url(), {"computer": self.other_computer.pk}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.device.refresh_from_db()
        self.assertEqual(self.device.computer_id, self.other_computer.pk)
        log = AuditLog.objects.filter(object_id=str(self.device.pk)).latest("id")
        self.assertEqual(log.meta.get("action"), "rebind")
        self.assertEqual(log.meta.get("computer_from"), self.computer.pk)

    def test_rebind_to_foreign_region_is_rejected(self):
        foreign = factories.make_computer(zone=factories.make_zone())
        response = self.client.patch(self._url(), {"computer": foreign.pk}, format="json")
        self.assertEqual(response.status_code, 400)
        self.device.refresh_from_db()
        self.assertEqual(self.device.computer_id, self.computer.pk)

    def test_rebind_to_written_off_computer_is_rejected(self):
        # `SoftDeleteModel.delete()` — hisobdan chiqarish (`deleted_at`).
        self.other_computer.delete()
        response = self.client.patch(
            self._url(), {"computer": self.other_computer.pk}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_revoke_requires_reason(self):
        response = self.client.post(self._url("revoke/"), {"reason": "  "}, format="json")
        self.assertEqual(response.status_code, 400)
        self.device.refresh_from_db()
        self.assertNotEqual(self.device.status, DeviceToken.Status.REVOKED)

    def test_unblock_clears_revoke_trace(self):
        self.client.post(self._url("revoke/"), {"reason": "Obraz ko'chirilgan"}, format="json")
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, DeviceToken.Status.REVOKED)

        response = self.client.post(self._url("approve/"))
        self.assertEqual(response.status_code, 200)
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, DeviceToken.Status.ACTIVE)
        self.assertIsNone(self.device.revoked_at)
        self.assertEqual(self.device.revoke_reason, "")
        log = AuditLog.objects.filter(object_id=str(self.device.pk)).latest("id")
        self.assertEqual(log.meta.get("action"), "unblock")

    def test_approve_active_device_is_idempotent(self):
        self.client.post(self._url("approve/"))
        before = AuditLog.objects.count()
        response = self.client.post(self._url("approve/"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(AuditLog.objects.count(), before)

    def test_stats_counts_by_status_within_region(self):
        factories.make_device(computer=self.other_computer, status=DeviceToken.Status.ACTIVE)
        factories.make_device(computer=self.other_computer, status=DeviceToken.Status.REVOKED)
        # Boshqa viloyatdagi qurilma sanalmaydi.
        factories.make_device(status=DeviceToken.Status.PENDING)

        response = self.client.get(f"{BASE}stats/")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(
            (data["pending"], data["active"], data["revoked"], data["total"]), (1, 1, 1, 3)
        )
