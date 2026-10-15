"""
Server holati API'si: kim ko'radi va javob shakli.

Server ma'lumoti viloyatga bo'linmaydi — viloyat administratori
`system.view` bo'lsa ham ko'rmaydi (`RepublicLevelOnly`).
"""

from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from apps.monitoring import services
from apps.proctoring.tests import factories
from apps.proctoring.tests.test_client_api import bearer

URLS = ("/api/v1/system/status/", "/api/v1/system/history/", "/api/v1/system/requests/")


class SystemAccessTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient()

    def get(self, user, url):
        self.client.credentials(HTTP_AUTHORIZATION=bearer(user))
        return self.client.get(url)

    def test_republic_admin_sees_status(self):
        user = factories.make_user(permissions=["system.view"])
        with mock.patch.object(services, "system_status", return_value={"overall": "ok"}):
            response = self.get(user, URLS[0])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"], {"overall": "ok"})

    def test_without_permission_forbidden(self):
        user = factories.make_user(permissions=["dashboard.view"])
        for url in URLS:
            with self.subTest(url=url):
                self.assertEqual(self.get(user, url).status_code, 403)

    def test_region_admin_forbidden_even_with_permission(self):
        region = factories.make_region()
        user = factories.make_user(permissions=["system.view"], region=region)
        for url in URLS:
            with self.subTest(url=url):
                response = self.get(user, url)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()["error"]["code"], "republic_level_only")

    def test_client_operator_forbidden(self):
        user = factories.make_user(permissions=["client.operate", "system.view"], panel_access=False)
        self.assertEqual(self.get(user, URLS[0]).status_code, 403)

    def test_status_survives_broken_sections(self):
        """Bitta bo'lim yiqilsa ham javob 200 — xato `errors` va `problems` da."""
        user = factories.make_user(permissions=["*"])
        with mock.patch("apps.monitoring.collectors.redis_info", side_effect=ConnectionError("down")), \
                mock.patch("apps.monitoring.host.services", return_value=({"available": False, "units": []}, {})):
            response = self.get(user, URLS[0])
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertIn("redis", data["errors"])
        self.assertEqual(data["overall"], "critical")
        self.assertIn("redis_unreachable", [item["code"] for item in data["problems"]])
        # Qolgan bo'limlar baribir bor.
        self.assertIn("memory", data)
        self.assertIsNotNone(data["postgres"])
        self.assertIn("warning", data["thresholds"]["cpu_pct"])

    def test_history_rejects_unknown_range(self):
        user = factories.make_user(permissions=["system.view"])
        response = self.get(user, "/api/v1/system/history/?range=999d")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["range"], "1h")
