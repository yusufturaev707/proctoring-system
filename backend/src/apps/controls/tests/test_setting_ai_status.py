"""
Sozlama profilidagi AI kuzatuv holati (`SettingSerializer.ai_proctoring`).

YOLO kaliti profilda (`Setting.is_enable_detect`), AI kuzatuvning bosh
kaliti esa ALOHIDA modelda (`ProctoringPolicy.is_enabled`). Obyekt
aniqlash faqat ikkalasi ham yoqilganda ishlaydi va ilgari panelning
profil sahifasida buni aytadigan hech narsa yo'q edi: administrator
YOLO ni yoqib, siyosat yaratmagan edi - client esa jimgina AI siz
ishlayverdi. Testlar ikkita narsani qo'riqlaydi:

  1. holat CLIENT'ga ketadigan qiymat bilan AYNAN bir xil formuladan
     chiqadi (panel boshqa narsani va'da qilmasligi kerak);
  2. panel yuboradigan yoqish so'rovi (`{setting, is_enabled}`)
     siyosatni haqiqatan yaratadi va client konfiguratsiyasi o'zgaradi.
"""

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.controls import services
from apps.controls.models import ProctoringPolicy
from apps.proctoring.tests import factories


class SettingAiStatusTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient()
        self.staff = factories.make_user(
            permissions=[
                "controls.manage", "controls.view",
                "controls.proctoring_manage", "controls.proctoring_view",
            ],
            is_staff=True,
        )
        self.client.force_authenticate(self.staff)
        self.setting = factories.make_setting(is_enable_detect=True)
        self.url = reverse("setting-detail", args=[self.setting.pk])

    def _status(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["data"]["ai_proctoring"]

    def test_detect_on_without_policy_reports_ai_off(self):
        """Aynan topilgan holat: YOLO yoqilgan, siyosat yo'q -> AI o'chiq."""
        status = self._status()
        self.assertEqual(
            status, {"policy_id": None, "enabled": False, "objects": False, "evidence": False}
        )
        # Client ham xuddi shuni oladi - panel va client bir xil gapiradi.
        proctoring = services.get_client_config(None)["proctoring"]
        self.assertFalse(proctoring["enabled"])

    def test_disabled_policy_is_reported_with_its_id(self):
        policy = ProctoringPolicy.objects.create(setting=self.setting, is_enabled=False)
        status = self._status()
        self.assertEqual(status["policy_id"], policy.pk)
        self.assertFalse(status["enabled"])

    def test_objects_follow_client_formula(self):
        """`objects` = siyosat yoqilgan VA siyosat moduli VA profil kaliti."""
        ProctoringPolicy.objects.create(
            setting=self.setting, is_enabled=True, enable_objects=True
        )
        self.assertTrue(self._status()["objects"])

        self.setting.is_enable_detect = False
        self.setting.save(update_fields=["is_enable_detect"])
        self.assertFalse(self._status()["objects"])

    def test_panel_enable_request_creates_policy(self):
        """
        Panel tugmasi yuboradigan so'rov - faqat `setting` va `is_enabled`.

        Qolgan maydonlar standart qiymatlarni olishi kerak: aks holda
        "yoqish" tugmasi validatsiya xatosi bilan qaytardi.
        """
        response = self.client.post(
            reverse("proctoring-policy-list"),
            {"setting": self.setting.pk, "is_enabled": True},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)

        status = self._status()
        self.assertTrue(status["enabled"])
        self.assertTrue(status["evidence"])
        self.assertEqual(status["objects"], status["enabled"] and self.setting.is_enable_detect)

    def test_list_endpoint_has_no_extra_queries_per_profile(self):
        """`proctoring` `select_related` da - profil soni so'rovlarni ko'paytirmaydi."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        ProctoringPolicy.objects.create(setting=self.setting, is_enabled=True)
        self.client.get(reverse("setting-list"))  # ruxsat keshini isitish
        with CaptureQueriesContext(connection) as before:
            self.client.get(reverse("setting-list"))
        for _ in range(3):
            ProctoringPolicy.objects.create(setting=factories.make_setting(), is_enabled=True)
        with CaptureQueriesContext(connection) as after:
            self.client.get(reverse("setting-list"))
        self.assertEqual(len(before), len(after), "har bir profil qo'shimcha so'rov beryapti")
