"""
Test platformasiga kamera va mikrofon ruxsati (`Setting.is_platform_camera`,
`is_platform_microphone`).

Client buni FAQAT `exam/access/` dagi `webview_policy` dan o'qiydi; kalit
unutilsa paneldagi kalit hech narsani o'zgartirmasdi. Standart — RAD (yangi
profil ham, profilsiz tizim ham). Ikki kalit MUSTAQIL: speaking uchun kamera,
FaceID uchun mikrofon berilmaydi.
"""

from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient

from apps.controls import services as controls_services
from apps.proctoring.services import session as session_service
from apps.proctoring.tests import factories
from apps.proctoring.tests.test_client_api import bearer
from apps.proctoring.tests.test_session import SessionFlowTestCase


class PlatformCameraPolicyTests(SessionFlowTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)

    def _policy(self):
        session = self._make_session()
        session_service.confirm_identity(
            session, actor=self.operator, document_type="passport", document_number="A1"
        )
        token = session_service.issue_session_token(session)
        operator = factories.make_user(permissions=["client.operate"])
        response = APIClient().post(
            reverse("client-exam-access"),
            {},
            format="json",
            HTTP_AUTHORIZATION=bearer(operator),
            HTTP_X_DEVICE_ID=self.device.device_id,
            HTTP_X_PROCTORING_SESSION=token,
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["data"]["webview_policy"]

    def _use_profile(self, **flags):
        self.exam.setting = factories.make_setting(**flags)
        self.exam.save(update_fields=["setting"])

    def test_denied_by_default(self):
        policy = self._policy()
        self.assertIs(policy["allow_camera"], False)
        self.assertIs(policy["allow_microphone"], False)
        # Naushnik afzal — standart (naushnik yo'q bo'lsa standart mikrofon).
        self.assertEqual(policy["microphone_source"], "headset_preferred")

    def test_camera_only(self):
        self._use_profile(is_platform_camera=True)
        policy = self._policy()
        self.assertIs(policy["allow_camera"], True)
        self.assertIs(policy["allow_microphone"], False)

    def test_microphone_only(self):
        """Speaking: mikrofon kerak, kamera emas."""
        self._use_profile(is_platform_microphone=True)
        policy = self._policy()
        self.assertIs(policy["allow_camera"], False)
        self.assertIs(policy["allow_microphone"], True)

    def test_headset_only_reaches_client(self):
        self._use_profile(is_platform_microphone=True, platform_microphone_source="headset_only")
        self.assertEqual(self._policy()["microphone_source"], "headset_only")

    def test_default_config_denies_both(self):
        with self.assertLogs("apps.controls.services", level="WARNING"):
            webview = controls_services._default_config()["webview"]
        self.assertEqual(
            webview,
            {"camera": False, "microphone": False, "microphone_source": "headset_preferred"},
        )
