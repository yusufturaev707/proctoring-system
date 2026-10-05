"""
Ochiq endpointlar chegarasi: ma'lum qurilma — o'z byudjeti, qolgani — IP.

Server internetda turganda butun bino bitta NAT manzili bilan keladi.
Faqat IP bo'yicha chegara imtihon boshida binoning ko'p qismini 429
bilan to'xtatardi; header'ning o'ziga ishonish esa har so'rovda yangi
ID yuborib chegarani chetlab o'tish yo'li bo'lardi.
"""

import json

from django.core.cache import cache
from django.test import RequestFactory, TestCase
from rest_framework.parsers import JSONParser
from rest_framework.request import Request

from apps.common.throttling import (
    AccessAttemptThrottle,
    DeviceRegisterThrottle,
    ExitVerifyDeviceThrottle,
    ExitVerifyThrottle,
    PinflLookupDeviceThrottle,
    PinflLookupOperatorThrottle,
    PreflightThrottle,
    StaffLoginDeviceThrottle,
    StaffLoginThrottle,
    device_or_ip_ident,
    device_user_ident,
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


# --------------------------------------------------------------------------
# Operator hisobi REGIONGA bitta: mashina bo'yicha qat'iy + hisob bo'yicha keng
# --------------------------------------------------------------------------
class _PinflDeviceTwoPerHour(PinflLookupDeviceThrottle):
    THROTTLE_RATES = {"pinfl_lookup_device": "2/hour"}


class _PinflAccountFivePerHour(PinflLookupOperatorThrottle):
    THROTTLE_RATES = {"pinfl_lookup_operator": "5/hour"}


class _LoginDeviceTwoPerMinute(StaffLoginDeviceThrottle):
    THROTTLE_RATES = {"staff_login_device": "2/min"}


class DeviceUserIdentTests(TestCase):
    """Bitta region hisobi bilan ishlaydigan bino — har mashinaga o'z byudjeti."""

    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.user = factories.make_user()

    def request(self, device_id=None, *, user="default", device=None):
        headers = {"REMOTE_ADDR": BUILDING_IP}
        if device_id is not None:
            headers["HTTP_X_DEVICE_ID"] = device_id
        request = self.factory.post("/api/v1/client/candidate/lookup/", **headers)
        if user is not None:
            request.user = self.user if user == "default" else user
        if device is not None:
            request.device = device
        return request

    def test_region_account_gets_separate_key_per_machine(self):
        first, second = factories.make_device(), factories.make_device()

        keys = {device_user_ident(self.request(d.device_id)) for d in (first, second)}

        self.assertEqual(
            keys, {f"dev:{first.pk}:user:{self.user.pk}", f"dev:{second.pk}:user:{self.user.pk}"}
        )

    def test_resolved_device_is_used_without_extra_query(self):
        """`DeviceResolution` qurilmani topgan bo'lsa — bazaga qayta borilmaydi."""
        device = factories.make_device()
        request = self.request(device=device)

        with self.assertNumQueries(0):
            key = device_user_ident(request)

        self.assertEqual(key, f"dev:{device.pk}:user:{self.user.pk}")

    def test_unknown_or_missing_device_falls_back_to_account_and_ip(self):
        """Soxta ID yangi byudjet bermaydi — hisob + bino IP'si."""
        for device_id in (None, "", "dev_not_registered"):
            with self.subTest(device_id=device_id):
                self.assertEqual(
                    device_user_ident(self.request(device_id)),
                    f"user:{self.user.pk}:ip:{BUILDING_IP}",
                )

    def test_anonymous_request_uses_device_or_ip(self):
        device = factories.make_device()
        self.assertEqual(
            device_user_ident(self.request(device.device_id, user=None)),
            f"dev:{device.pk}:{BUILDING_IP}",
        )
        self.assertEqual(device_user_ident(self.request("fake", user=None)), f"ip:{BUILDING_IP}")

    def test_device_scopes_use_device_key(self):
        device = factories.make_device()
        request = self.request(device.device_id)
        for throttle in (PinflLookupDeviceThrottle(), ExitVerifyDeviceThrottle()):
            with self.subTest(throttle=type(throttle).__name__):
                self.assertIn(
                    f"dev:{device.pk}:user:{self.user.pk}", throttle.get_cache_key(request, None)
                )

    def test_account_scopes_keep_account_key(self):
        """Keng chegara hisob bo'yicha qoladi: o'g'irlangan hisob ko'p mashinadan ham to'xtaydi."""
        device = factories.make_device()
        request = self.request(device.device_id)
        for throttle in (PinflLookupOperatorThrottle(), ExitVerifyThrottle()):
            with self.subTest(throttle=type(throttle).__name__):
                self.assertTrue(throttle.get_cache_key(request, None).endswith(f"user:{self.user.pk}"))

    def test_one_machine_does_not_exhaust_the_building(self):
        devices = [factories.make_device() for _ in range(2)]
        for _ in range(2):
            self.assertTrue(_PinflDeviceTwoPerHour().allow_request(self.request(devices[0].device_id), None))

        self.assertFalse(_PinflDeviceTwoPerHour().allow_request(self.request(devices[0].device_id), None))
        self.assertTrue(_PinflDeviceTwoPerHour().allow_request(self.request(devices[1].device_id), None))

    def test_account_cap_still_applies_across_machines(self):
        devices = [factories.make_device() for _ in range(6)]
        allowed = [
            _PinflAccountFivePerHour().allow_request(self.request(d.device_id), None) for d in devices
        ]
        self.assertEqual(allowed, [True] * 5 + [False])


class StaffLoginThrottleTests(TestCase):
    """Login'da xodim hali yo'q — kalit qurilma (yoki bino IP) + kiritilgan login."""

    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

    def request(self, device_id=None, username="region_01"):
        headers = {"REMOTE_ADDR": BUILDING_IP}
        if device_id is not None:
            headers["HTTP_X_DEVICE_ID"] = device_id
        django_request = self.factory.post(
            "/api/v1/auth/login/",
            data=json.dumps({"username": username, "password": "x"}),
            content_type="application/json",
            **headers,
        )
        return Request(django_request, parsers=[JSONParser()])

    def test_device_key_per_machine_and_ip_key_for_unknown(self):
        device = factories.make_device()
        throttle = StaffLoginDeviceThrottle()

        self.assertIn(
            f"dev:{device.pk}:{BUILDING_IP}:region_01",
            throttle.get_cache_key(self.request(device.device_id), None),
        )
        self.assertIn(
            f"ip:{BUILDING_IP}:region_01", throttle.get_cache_key(self.request("fake"), None)
        )

    def test_building_key_is_unchanged(self):
        self.assertIn(
            f"{BUILDING_IP}:region_01", StaffLoginThrottle().get_cache_key(self.request(), None)
        )

    def test_shared_account_logs_in_on_many_machines(self):
        devices = [factories.make_device() for _ in range(3)]
        for device in devices:
            for _ in range(2):
                self.assertTrue(
                    _LoginDeviceTwoPerMinute().allow_request(self.request(device.device_id), None)
                )
        self.assertFalse(
            _LoginDeviceTwoPerMinute().allow_request(self.request(devices[0].device_id), None)
        )


class ThrottleWiringTests(TestCase):
    """Uchala yuzada ikki qavat ham ulangan bo'lishi shart."""

    def test_views_use_device_and_account_layers(self):
        from apps.proctoring.api.v1.client_views import CandidateLookupView, ExitVerifyView
        from apps.users.api.v1.views import LoginView

        cases = (
            (LoginView, StaffLoginDeviceThrottle, StaffLoginThrottle),
            (CandidateLookupView, PinflLookupDeviceThrottle, PinflLookupOperatorThrottle),
            (ExitVerifyView, ExitVerifyDeviceThrottle, ExitVerifyThrottle),
        )
        for view, device_layer, account_layer in cases:
            with self.subTest(view=view.__name__):
                self.assertIn(device_layer, view.throttle_classes)
                self.assertIn(account_layer, view.throttle_classes)
