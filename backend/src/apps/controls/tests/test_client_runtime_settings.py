"""
Client sozlamalarining panel qatlami (`CLAUDE.md`: "Client sozlamalari:
.env va panel").

Client serverdan kelgan qiymatni `.env` dagi zaxiradan USTUN qo'yadi
(`client/services/runtime_settings.py`). Shuning uchun uch narsa
qo'riqlanadi:

  1. `_serialize` va `_default_config` BIR XIL kalitlarni beradi. Ular
     ajralib ketsa, sozlamasi yo'q tizimda (yoki aksincha) kalit
     yo'qoladi va client jimgina `.env` zaxirasiga tushadi - bitta
     bino ikki xil qoida bilan ishlaydi va buni hech kim sezmaydi;
  2. `_default_config` dagi qiymatlar MODEL STANDARTLARI bilan bir
     xil - "profil yo'q" va "yangi profil" bir xil xulq berishi kerak;
  3. panel API chegaralarni qo'llaydi (heartbeat `HEARTBEAT_TIMEOUT`
     ning yarmi, sanoq, foizlar) va o'zgarish kesh orqali clientga
     yetadi.
"""

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.controls import services
from apps.controls.models import Setting
from apps.devices.services import PRESENCE_PING_INTERVAL, PRESENCE_TTL
from apps.proctoring.tests import factories

#: Clientga ketadigan kalit -> `Setting` maydoni (panel qatlamiga
#: ko'chirilgan va shu vazifada ulangan sozlamalar).
RUNTIME_FIELDS = {
    ("face", "guide_seconds"): "faceid_guide_seconds",
    ("face", "match_streak"): "faceid_match_streak",
    ("face", "fail_streak"): "faceid_fail_streak",
    ("face", "fail_min_seconds"): "faceid_fail_min_seconds",
    ("face", "interval"): "faceid_interval",
    ("capture", "screen_record"): "is_screen_record",
    ("capture", "record_fps"): "screen_record_fps",
    ("capture", "record_width"): "screen_record_width",
    ("capture", "record_pip_percent"): "screen_record_pip_percent",
    ("capture", "upload"): "is_screenshot_upload",
    ("capture", "camera_overlay"): "is_screenshot_camera_overlay",
    ("capture", "camera_overlay_percent"): "screenshot_pip_percent",
    ("rdp", "block_exam"): "is_threat_block_exam",
    ("network", "heartbeat_interval"): "heartbeat_interval",
    ("network", "event_batch_interval"): "event_batch_interval",
    ("network", "offline_buffer_size"): "offline_buffer_size",
}


def _shape(value):
    """Lug'at tuzilmasi (kalitlar daraxti); ro'yxat va qiymatlar - barg."""
    if isinstance(value, dict):
        return {key: _shape(item) for key, item in value.items()}
    return None


def _at(config: dict, path: tuple):
    for key in path:
        config = config[key]
    return config


class ConfigShapeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_serialize_and_default_have_same_keys(self):
        serialized = services._serialize(factories.make_setting())
        with self.assertLogs("apps.controls.services", level="WARNING"):
            default = services._default_config()
        self.assertEqual(_shape(serialized), _shape(default))

    def test_default_config_matches_model_defaults(self):
        with self.assertLogs("apps.controls.services", level="WARNING"):
            default = services._default_config()
        for path, field in RUNTIME_FIELDS.items():
            with self.subTest(key=".".join(path)):
                model_default = Setting._meta.get_field(field).default
                self.assertEqual(_at(default, path), model_default)

    def test_serialize_carries_profile_values(self):
        setting = factories.make_setting(
            faceid_guide_seconds=0,
            faceid_match_streak=5,
            faceid_fail_streak=20,
            faceid_fail_min_seconds=12,
            is_screen_record=False,
            screen_record_fps=3,
            screen_record_width=1280,
            screen_record_pip_percent=20,
            is_screenshot_upload=False,
            is_screenshot_camera_overlay=False,
            screenshot_pip_percent=25,
            is_threat_block_exam=False,
            heartbeat_interval=20,
            event_batch_interval=10,
            offline_buffer_size=2000,
        )
        config = services._serialize(setting)
        for path, field in RUNTIME_FIELDS.items():
            with self.subTest(key=".".join(path)):
                self.assertEqual(_at(config, path), getattr(setting, field))

    def test_presence_interval_comes_from_server_constant(self):
        config = services._serialize(factories.make_setting())
        self.assertEqual(config["network"]["presence_interval"], PRESENCE_PING_INTERVAL)
        # Bitta kechikkan signal mashinani "offline" qilmasligi kerak.
        self.assertGreaterEqual(PRESENCE_TTL, 2 * PRESENCE_PING_INTERVAL)

    def test_empty_hotkeys_mean_not_configured(self):
        """Bo'sh ro'yxat clientda `.env` standartini qoldiradi - kalit baribir bor."""
        config = services._serialize(factories.make_setting())
        self.assertEqual(config["hotkeys"], [])


class SettingApiValidationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient()
        self.staff = factories.make_user(
            permissions=["controls.manage", "controls.view"], is_staff=True
        )
        self.client.force_authenticate(self.staff)
        self.setting = factories.make_setting(is_active=True)
        self.url = reverse("setting-detail", args=[self.setting.pk])

    def _patch(self, **data):
        return self.client.patch(self.url, data, format="json")

    def test_heartbeat_limited_by_timeout(self):
        limit = settings.PROCTORING["HEARTBEAT_TIMEOUT"] // 2
        self.assertEqual(self._patch(heartbeat_interval=limit + 1).status_code, 400)
        self.assertEqual(self._patch(heartbeat_interval=limit).status_code, 200)

    @override_settings(PROCTORING={**settings.PROCTORING, "HEARTBEAT_TIMEOUT": 200})
    def test_heartbeat_limit_follows_setting(self):
        self.assertEqual(self._patch(heartbeat_interval=90).status_code, 200)

    def test_out_of_range_values_rejected(self):
        for field, value in (
            ("faceid_guide_seconds", 31),
            ("faceid_match_streak", 0),
            ("faceid_fail_min_seconds", 0),
            ("screen_record_fps", 0),
            ("screen_record_width", 320),
            ("screen_record_pip_percent", 50),
            ("screenshot_pip_percent", 2),
            ("event_batch_interval", 0),
        ):
            with self.subTest(field=field):
                response = self._patch(**{field: value})
                self.assertEqual(response.status_code, 400, response.content)

    def test_change_reaches_client_config(self):
        """Saqlash keshni tozalaydi - client keyingi so'rovda yangi qiymatni oladi."""
        self.assertEqual(services.get_client_config()["face"]["guide_seconds"], 5)
        response = self._patch(faceid_guide_seconds=0, is_threat_block_exam=False)
        self.assertEqual(response.status_code, 200, response.content)

        config = services.get_client_config()
        self.assertEqual(config["face"]["guide_seconds"], 0)
        self.assertFalse(config["rdp"]["block_exam"])
