"""
Ochiq endpointlar chegarasi: ma'lum qurilma — o'z byudjeti, qolgani — IP.

Server internetda turganda butun bino bitta NAT manzili bilan keladi.
Faqat IP bo'yicha chegara imtihon boshida binoning ko'p qismini 429
bilan to'xtatardi; header'ning o'ziga ishonish esa har so'rovda yangi
ID yuborib chegarani chetlab o'tish yo'li bo'lardi.
"""

from django.core.cache import cache
from django.test import RequestFactory, TestCase

from apps.common.throttling import (
    AccessAttemptThrottle,
    DeviceRegisterThrottle,
    PreflightThrottle,
    device_or_ip_ident,
)
from apps.proctoring.tests import factories

BUILDING_IP = "8.8.8.8"


class _TwoPerMinute(PreflightThrottle):
    # Test sozlamalarida throttling o'chiq — chegara shu yerda beriladi.
    THROTTLE_RATES = {"preflight": "2/min"}


class DeviceOrIpIdentTests(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

    def request(self, device_id=None):
        headers = {"REMOTE_ADDR": BUILDING_IP}
        if device_id is not None:
            headers["HTTP_X_DEVICE_ID"] = device_id
        return self.factory.post("/api/v1/client/preflight/", **headers)

    def test_known_devices_behind_one_ip_get_separate_keys(self):
        first, second = factories.make_device(), factories.make_device()

        keys = {device_or_ip_ident(self.request(d.device_id)) for d in (first, second)}

        self.assertEqual(keys, {f"dev:{first.pk}:{BUILDING_IP}", f"dev:{second.pk}:{BUILDING_IP}"})

    def test_pending_device_is_known(self):
        """Tasdiq kutayotgan mashina ham ishga tushishda preflight qiladi."""
        device = factories.make_device(status="pending")
        self.assertEqual(
            device_or_ip_ident(self.request(device.device_id)), f"dev:{device.pk}:{BUILDING_IP}"
        )

    def test_unknown_missing_or_oversized_id_falls_back_to_ip(self):
        for device_id in (None, "", "dev_not_registered", "x" * 500):
            with self.subTest(device_id=device_id and device_id[:20]):
                self.assertEqual(device_or_ip_ident(self.request(device_id)), f"ip:{BUILDING_IP}")

    def test_all_open_endpoints_use_the_same_key(self):
        device = factories.make_device()
        request = self.request(device.device_id)
        for throttle in (PreflightThrottle(), AccessAttemptThrottle(), DeviceRegisterThrottle()):
            with self.subTest(throttle=type(throttle).__name__):
                self.assertIn(f"dev:{device.pk}:", throttle.get_cache_key(request, None))

    def test_building_is_not_throttled_as_one_client(self):
        """Uchta ro'yxatdagi mashina — har biri o'z chegarasigacha o'tadi."""
        devices = [factories.make_device() for _ in range(3)]
        for device in devices:
            for _ in range(2):
                self.assertTrue(_TwoPerMinute().allow_request(self.request(device.device_id), None))
        self.assertFalse(_TwoPerMinute().allow_request(self.request(devices[0].device_id), None))

    def test_rotating_fake_ids_stay_on_ip_budget(self):
        """Header soxtalashtirilsa — chegara avvalgidek IP bo'yicha."""
        allowed = [
            _TwoPerMinute().allow_request(self.request(f"fake_{i}"), None) for i in range(5)
        ]
        self.assertEqual(allowed, [True, True, False, False, False])
