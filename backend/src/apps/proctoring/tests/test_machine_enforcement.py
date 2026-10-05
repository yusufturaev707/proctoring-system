"""
Mashina tekshiruvi SERVERDA (`REQUIRE_MACHINE_MATCH=true`).

Ilgari natija faqat handshake javobidagi bayroq edi (`machine.allowed`) va
to'siqni client UI qo'yardi: bayroqni e'tiborsiz qoldirgan client JSHSHIR
qidirib, imtihon ochardi. Endi `candidate/lookup/` o'zi rad etadi — tashqi
platformaga so'rovdan OLDIN. `face/verify/` shu challenge bilan bog'langan
(`_require_pending_device`), ya'ni alohida tekshiruv kerak emas.
"""

from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.common.exceptions import CandidateNotFound
from apps.controls.models import AllowedPublicIp
from apps.proctoring.models import AuditLog
from apps.proctoring.tests import factories
from apps.proctoring.tests.test_client_api import bearer

PINFL = "30000000000001"
#: Shu mashinaning Wi-Fi adapteri — yozuvda yo'q MAC.
WIFI_MAC = "02:11:22:33:44:55"


class LookupMachineEnforcementTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient()
        self.zone = factories.make_zone()
        self.computer = factories.make_computer(zone=self.zone)
        self.device = factories.make_device(computer=self.computer)
        self.exam = factories.make_exam()
        factories.make_schedule(exam=self.exam, zone=self.zone)
        AllowedPublicIp.objects.create(ip_address="8.8.8.8", zone=self.zone)
        self.operator = factories.make_user(permissions=["client.operate"])

    def _lookup(self, *, uuid=None, mac=None):
        payload = {"pinfl": PINFL, "exam_id": self.exam.pk}
        if uuid is not None:
            payload["machine_uuid"] = uuid
        if mac is not None:
            payload["mac_address"] = mac
        # Platformaga yetib borganini `check` ko'rsatadi; javobi esa
        # "topilmadi" — muvaffaqiyat yo'li Redis talab qilmasin.
        with patch(
            "apps.integrations.exam_site.check_candidate", side_effect=CandidateNotFound()
        ) as check:
            response = self.client.post(
                reverse("client-candidate-lookup"),
                payload,
                format="json",
                HTTP_AUTHORIZATION=bearer(self.operator),
                HTTP_X_DEVICE_ID=self.device.device_id,
                REMOTE_ADDR="8.8.8.8",
            )
        return response, check

    def assertRefused(self, response, check, status):
        self.assertEqual(response.status_code, 409, response.content)
        error = response.json()["error"]
        self.assertEqual(error["code"], "machine_not_verified")
        self.assertEqual(error["details"]["status"], status)
        check.assert_not_called()
        return error

    def test_matching_pair_reaches_platform(self):
        response, check = self._lookup(
            uuid=self.computer.machine_uuid, mac=self.computer.mac_address
        )

        check.assert_called_once()
        self.assertEqual(response.json()["error"]["code"], "candidate_not_found")

    def test_same_uuid_other_mac_is_refused_before_platform(self):
        """Wi-Fi'ga o'tgan mashina: UUID o'sha, MAC boshqa."""
        response, check = self._lookup(uuid=self.computer.machine_uuid, mac=WIFI_MAC)

        error = self.assertRefused(response, check, "not_found")
        self.assertEqual(error["details"]["mac_address"], WIFI_MAC.upper())
        self.assertEqual(error["details"]["expected_mac"], self.computer.mac_address)
        # Xabar handshake bilan bir xil — operator nima qilishni ko'radi.
        self.assertIn("Wi-Fi", error["message"])

    def test_missing_identity_is_refused(self):
        """Maydonlarni bo'sh yuborish tekshiruvni chetlab o'tmaydi."""
        response, check = self._lookup()

        self.assertRefused(response, check, "unknown")

    def test_other_registered_machine_is_mismatch(self):
        """Qurilma boshqa kompyuterga biriktirilgan (obraz ko'chirilgan)."""
        other = factories.make_computer(zone=self.zone)

        response, check = self._lookup(uuid=other.machine_uuid, mac=other.mac_address)

        self.assertRefused(response, check, "mismatch")

    def test_flag_off_does_not_block(self):
        with patch.dict(settings.PROCTORING, {"REQUIRE_MACHINE_MATCH": False}):
            response, check = self._lookup(uuid=self.computer.machine_uuid, mac=WIFI_MAC)

        check.assert_called_once()
        self.assertEqual(response.json()["error"]["code"], "candidate_not_found")

    def test_uuid_binding_is_audited(self):
        """UUID'siz eski yozuv MAC bo'yicha bog'lanadi — handshake'dagi kabi auditda."""
        legacy = factories.make_computer(zone=self.zone, machine_uuid=None)
        self.device.computer = legacy
        self.device.save(update_fields=["computer"])
        uuid = factories.machine_uuid_for(990001)

        response, check = self._lookup(uuid=uuid, mac=legacy.mac_address)

        check.assert_called_once()
        legacy.refresh_from_db()
        self.assertEqual(legacy.machine_uuid, uuid)
        audit = AuditLog.objects.get(object_type="Computer", object_id=str(legacy.pk))
        self.assertEqual(audit.meta["machine_uuid_bound"], uuid)
        self.assertEqual(audit.actor, self.operator)
