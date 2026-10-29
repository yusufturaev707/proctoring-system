"""
Console HTTP client: token, login himoyasi, qayta urinish, sahifalash.

Login bloki eng muhim qoida: Console 15 daqiqada 5 noto'g'ri paroldan keyin
hisobni bloklaydi — har 15 s dagi holat so'rovi parolni qayta sinasa, hisob
o'zimiz tufayli qulflanardi.
"""

from unittest import mock

import requests
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.conf import settings

from apps.bba import client as bba_client
from apps.bba.client import (
    BbaAuthError,
    BbaClient,
    BbaForbidden,
    BbaNotConfigured,
    BbaRateLimited,
    BbaRejected,
    BbaUnavailable,
)
from apps.bba.tests.fakes import FakeResponse, FakeSession, login_ok


def enabled(**overrides):
    return override_settings(BBA_CONSOLE={**settings.BBA_CONSOLE, "ENABLED": True, **overrides})


@enabled()
class ClientTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        sleep = mock.patch("apps.bba.client.time.sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    def client_with(self, *responses):
        session = FakeSession(*responses)
        return BbaClient(session=session), session

    def test_token_is_reused_between_requests(self):
        client, session = self.client_with(login_ok(), FakeResponse(200, []), FakeResponse(200, []))
        client.regions()
        client.rooms()
        self.assertEqual([c["method"] for c in session.calls], ["POST", "GET", "GET"])
        self.assertEqual(session.calls[1]["headers"]["Authorization"], "Bearer tok-1")
        # Boshqa thread/jarayon ham shu tokenni oladi (umumiy kesh).
        other, other_session = self.client_with(FakeResponse(200, []))
        other.regions()
        self.assertEqual(len(other_session.calls), 1)

    def test_expired_token_relogins_once(self):
        client, session = self.client_with(
            login_ok("old"), FakeResponse(401), login_ok("new"), FakeResponse(200, [{"ID": "x"}])
        )
        self.assertEqual(client.regions(), [{"ID": "x"}])
        self.assertEqual(session.calls[-1]["headers"]["Authorization"], "Bearer new")

    def test_wrong_password_is_remembered(self):
        client, session = self.client_with(FakeResponse(401, text="invalid credentials"))
        with self.assertRaises(BbaAuthError):
            client.regions()
        # Ikkinchi chaqiruv Console'ga UMUMAN bormaydi.
        with self.assertRaises(BbaAuthError):
            client.regions()
        self.assertEqual(len(session.calls), 1)
        bba_client.clear_login_block()
        self.assertIsNone(bba_client.login_block_reason())

    def test_password_change_required_blocks_login(self):
        client, _ = self.client_with(
            FakeResponse(200, {"token": "t", "must_change_password": True})
        )
        with self.assertRaises(BbaAuthError):
            client.regions()
        self.assertIsNone(cache.get(bba_client.TOKEN_KEY))

    def test_post_is_never_retried(self):
        """Javobi yo'qolgan job Console'da yaratilgan bo'lishi mumkin — qayta yuborilmaydi."""
        client, session = self.client_with(login_ok(), FakeResponse(502))
        with self.assertRaises(BbaUnavailable):
            client.create_job("dev-1", {"type": "shutdown_computer", "params": {}, "confirm": True})
        self.assertEqual(len(session.calls), 2)

    def test_get_retries_transient_errors(self):
        client, session = self.client_with(
            login_ok(), FakeResponse(503),
            requests.ConnectionError("reset"), FakeResponse(200, []),
        )
        self.assertEqual(client.rooms(), [])
        self.assertEqual(len(session.calls), 4)

    def test_error_mapping(self):
        cases = [
            (FakeResponse(403, text="forbidden"), BbaForbidden),
            (FakeResponse(429, text="slow down", headers={"Retry-After": "45"}), BbaRateLimited),
            (FakeResponse(400, {"error": "params.features must not be empty"}), BbaRejected),
        ]
        for response, expected in cases:
            with self.subTest(expected=expected.__name__):
                cache.clear()
                client, _ = self.client_with(login_ok(), response)
                with self.assertRaises(expected) as ctx:
                    client.post("/devices/x/jobs", {})
                if expected is BbaRateLimited:
                    self.assertEqual(ctx.exception.retry_after, 45)
                if expected is BbaRejected:
                    self.assertIn("features must not be empty", str(ctx.exception))

    def test_password_change_on_request_is_auth_error(self):
        client, _ = self.client_with(login_ok(), FakeResponse(403, text="password change required"))
        with self.assertRaises(BbaAuthError):
            client.regions()

    def test_pagination_reads_every_page_with_limit_500(self):
        page1 = {"devices": [{"ID": str(i)} for i in range(500)], "total": 501}
        page2 = {"devices": [{"ID": "500"}], "total": 501}
        client, session = self.client_with(login_ok(), FakeResponse(200, page1), FakeResponse(200, page2))
        self.assertEqual(len(list(client.iter_devices())), 501)
        self.assertEqual(session.calls[1]["params"], {"limit": 500, "offset": 0})
        self.assertEqual(session.calls[2]["params"], {"limit": 500, "offset": 500})

    def test_ids_are_quoted_in_paths(self):
        client = BbaClient(session=FakeSession())
        self.assertEqual(client.path("inventory", id="a/../b"), "/devices/a%2F..%2Fb/inventory")

    def test_no_redirects_and_ca_verification(self):
        client, session = self.client_with(login_ok(), FakeResponse(200, []))
        client.regions()
        self.assertFalse(session.calls[0]["allow_redirects"])
        self.assertTrue(session.calls[0]["verify"])

    @enabled(CA_FILE="certs/missing-bba-ca.pem")
    def test_missing_ca_file_is_configuration_error(self):
        client, _ = self.client_with(login_ok())
        with self.assertRaises(BbaNotConfigured):
            client.regions()

    @enabled(PASSWORD="")
    def test_not_configured(self):
        client, session = self.client_with()
        with self.assertRaises(BbaNotConfigured):
            client.regions()
        self.assertEqual(session.calls, [])
