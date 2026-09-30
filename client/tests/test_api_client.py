"""
`ApiClient` — nosoz server qarshisida (fault injection, GUI'siz).

Lokal HTTP server 500/502 (nginx HTML), 429 + Retry-After, JSON bo'lmagan
va bo'sh tana, sekin javob qaytaradi. Qo'riqlanadigan qoidalar:

  * hech bir holat istisnosiz (`ClientError` dan boshqa) tugamaydi;
  * idempotent so'rov qisqa uzilishda takrorlanadi, idempotent bo'lmagan
    POST javobdan KEYINGI xatoda takrorlanmaydi (`face/verify/`,
    `session/finish/`);
  * `Retry-After` dan oldin shu yo'lga so'rov umuman ketmaydi;
  * refresh paytidagi tarmoq xatosi "sessiya muddati tugadi" EMAS.
"""

import json
import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

from core.errors import ClientError, NetworkError
from services import api_client as ac


def _envelope(data):
    return json.dumps({"success": True, "data": data, "error": None}).encode()


class _Handler(BaseHTTPRequestHandler):
    hits: dict = {}
    flaky_left: dict = {}

    def log_message(self, *args):  # jim
        pass

    def _send(self, status, body=b"", content_type="application/json", headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _route(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        path = self.path.split("?")[0]
        _Handler.hits[path] = _Handler.hits.get(path, 0) + 1
        if path == "/ok":
            return self._send(200, _envelope({"x": 1}))
        if path.startswith("/flaky"):
            left = _Handler.flaky_left.get(path, 2)
            if left > 0:
                _Handler.flaky_left[path] = left - 1
                return self._send(502, b"<html>502 Bad Gateway</html>", "text/html")
            return self._send(200, _envelope({"ok": True}))
        if path == "/html502":
            return self._send(502, b"<html><body>nginx</body></html>", "text/html")
        if path == "/html500":
            return self._send(500, b"<html>Server Error</html>", "text/html")
        if path == "/presign503":
            body = json.dumps({"success": False, "data": None,
                               "error": {"code": "", "message": "storage off"}}).encode()
            return self._send(503, body)
        if path == "/r429":
            body = json.dumps({"success": False,
                               "error": {"code": "throttled", "message": "slow down"}}).encode()
            return self._send(429, body, headers={"Retry-After": "30"})
        if path == "/badjson":
            return self._send(200, b"<html>captive portal</html>", "text/html")
        if path == "/empty":
            return self._send(200, b"")
        if path == "/errstr":
            return self._send(400, json.dumps({"success": False, "error": "matn"}).encode())
        if path == "/errlist":
            body = json.dumps({"success": False, "error": {
                "code": "validation_error", "message": "bad", "details": ["a", "b"]}}).encode()
            return self._send(400, body)
        if path == "/slow":
            time.sleep(1.5)
            return self._send(200, _envelope({}))
        if path == "/needauth":
            return self._send(401, json.dumps({"success": False, "error": {
                "code": "token_not_valid", "message": "expired"}}).encode())
        if path == "/auth/refresh/":
            mode = _Handler.flaky_left.get("refresh_mode", "502")
            if mode == "502":
                return self._send(502, b"<html>bad gateway</html>", "text/html")
            return self._send(401, json.dumps({"success": False, "error": {
                "code": "token_not_valid", "message": "refresh expired"}}).encode())
        return self._send(404, b"{}")

    do_GET = _route
    do_POST = _route


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ApiClientFaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = "http://127.0.0.1:{}".format(cls.server.server_address[1])
        cls._orig = (ac._INLINE_BASE_S, ac._INLINE_CAP_S)
        # Testda kutish qisqa - mantiq o'sha.
        ac._INLINE_BASE_S, ac._INLINE_CAP_S = 0.01, 0.05

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        ac._INLINE_BASE_S, ac._INLINE_CAP_S = cls._orig

    def setUp(self):
        _Handler.hits.clear()
        _Handler.flaky_left.clear()
        # Singleton'ni chetlab: har test o'z mijozi bilan.
        self.api = ac.ApiClient.__new__(ac.ApiClient)
        ac.ApiClient.__init__(self.api)
        self.api._client.close()
        self.api._client = httpx.Client(
            base_url=self.base, timeout=httpx.Timeout(1.0, connect=1.0)
        )
        self.expired = []
        self.api.set_auth_expired_handler(lambda: self.expired.append(True))

    def tearDown(self):
        self.api.close()

    def hits(self, path):
        return _Handler.hits.get(path, 0)

    # --- konvert ------------------------------------------------------
    def test_ok_envelope(self):
        self.assertEqual(self.api.get("/ok"), {"x": 1})

    def test_empty_body_is_none(self):
        self.assertIsNone(self.api.get("/empty"))

    def test_html_on_200_is_invalid_response(self):
        with self.assertRaises(ClientError) as ctx:
            self.api.get("/badjson")
        self.assertEqual(ctx.exception.code, "invalid_response")

    def test_nginx_502_html_is_readable_error(self):
        with self.assertRaises(ClientError) as ctx:
            self.api.get("/html502", retries=0)
        self.assertEqual(ctx.exception.code, "server_unavailable")
        self.assertEqual(ctx.exception.status, 502)
        self.assertIn("502", ctx.exception.message)

    def test_500_not_retried(self):
        with self.assertRaises(ClientError) as ctx:
            self.api.get("/html500")
        self.assertEqual(ctx.exception.code, "server_error")
        self.assertEqual(self.hits("/html500"), 1)

    def test_error_as_string_and_details_list(self):
        with self.assertRaises(ClientError) as ctx:
            self.api.post("/errstr")
        self.assertEqual(ctx.exception.message, "matn")
        self.assertEqual(ctx.exception.details, {})
        with self.assertRaises(ClientError) as ctx:
            self.api.post("/errlist")
        self.assertEqual(ctx.exception.details, {"items": ["a", "b"]})
        self.assertEqual(self.hits("/errlist"), 1)  # 4xx takrorlanmaydi

    def test_backend_503_keeps_status_for_presign_fallback(self):
        with self.assertRaises(ClientError) as ctx:
            self.api.post("/presign503", retries=0)
        self.assertEqual(ctx.exception.status, 503)

    # --- takror -------------------------------------------------------
    def test_get_retries_through_short_outage(self):
        self.assertEqual(self.api.get("/flaky_get"), {"ok": True})
        self.assertEqual(self.hits("/flaky_get"), 3)

    def test_unsafe_post_not_retried_after_response(self):
        with self.assertRaises(ClientError):
            self.api.post("/flaky_post")
        self.assertEqual(self.hits("/flaky_post"), 1)

    def test_idempotent_post_retried(self):
        self.assertEqual(self.api.post("/flaky_idem", idempotent=True), {"ok": True})
        self.assertEqual(self.hits("/flaky_idem"), 3)

    def test_read_timeout_unsafe_post_single_attempt(self):
        with self.assertRaises(NetworkError) as ctx:
            self.api.post("/slow")
        self.assertEqual(ctx.exception.code, "network")
        self.assertEqual(self.hits("/slow"), 1)

    def test_explicit_timeout_disables_retries(self):
        with self.assertRaises(NetworkError):
            self.api.get("/slow", timeout=0.3)
        self.assertEqual(self.hits("/slow"), 1)

    def test_connection_refused_is_network_error(self):
        self.api._client.close()
        self.api._client = httpx.Client(
            base_url="http://127.0.0.1:{}".format(_free_port()), timeout=1.0
        )
        started = time.monotonic()
        with self.assertRaises(NetworkError) as ctx:
            self.api.post("/ok")
        self.assertEqual(ctx.exception.code, "network")
        self.assertLess(time.monotonic() - started, 5)

    # --- Retry-After --------------------------------------------------
    def test_retry_after_gate_blocks_next_request_locally(self):
        with self.assertRaises(ClientError) as ctx:
            self.api.post("/r429")
        self.assertEqual(ctx.exception.code, "throttled")
        self.assertAlmostEqual(ctx.exception.retry_after, 30, delta=1)
        with self.assertRaises(ClientError) as ctx:
            self.api.post("/r429")
        self.assertEqual(ctx.exception.code, "throttled")
        self.assertEqual(self.hits("/r429"), 1)  # ikkinchisi serverga bormadi
        self.assertEqual(self.api.get("/ok"), {"x": 1})  # boshqa yo'l ochiq

    # --- refresh ------------------------------------------------------
    def test_refresh_network_failure_is_not_auth_expired(self):
        self.api.set_tokens("old-access", "refresh-token")
        with self.assertRaises(NetworkError):
            self.api.get("/needauth")
        self.assertEqual(self.expired, [])

    def test_refresh_rejected_is_auth_expired(self):
        _Handler.flaky_left["refresh_mode"] = "401"
        self.api.set_tokens("old-access", "refresh-token")
        with self.assertRaises(ClientError) as ctx:
            self.api.get("/needauth")
        self.assertEqual(ctx.exception.status, 401)
        self.assertEqual(self.expired, [True])


if __name__ == "__main__":
    unittest.main()
