"""
nginx `stub_status`: asosiy HTTPS blokidagi `location = /nginx_status`
(`allow 127.0.0.1`) backend'dan `https://127.0.0.1/...` bilan o'qiladi —
sertifikat domenga berilgan, shuning uchun loopback'da tekshirilmaydi.
"""

from unittest import mock

import requests
from django.test import SimpleTestCase, override_settings

from apps.monitoring import collectors

STUB_STATUS = """Active connections: 291
server accepts handled requests
 16630948 16630946 31070465
Reading: 6 Writing: 179 Waiting: 106
"""


def _response(status=200, text=STUB_STATUS, redirect=False):
    response = mock.Mock(status_code=status, text=text)
    response.is_redirect = redirect
    response.is_permanent_redirect = redirect
    return response


class NginxStatusTests(SimpleTestCase):
    def fetch(self, url, **response_kwargs):
        with override_settings(SYSTEM_MONITOR={"NGINX_STATUS_URL": url}), \
                mock.patch("requests.get", return_value=_response(**response_kwargs)) as get:
            data, counters = collectors.nginx()
        return data, counters, get

    def test_loopback_https_skips_certificate_check(self):
        data, counters, get = self.fetch("https://127.0.0.1/nginx_status")
        self.assertFalse(get.call_args.kwargs["verify"])
        self.assertFalse(get.call_args.kwargs["allow_redirects"])
        self.assertTrue(data["available"])
        self.assertEqual(data["active"], 291)
        self.assertEqual(data["dropped_total"], 2)
        self.assertEqual(counters["nginx.requests"], 31070465.0)

    def test_host_header_selects_server_block(self):
        with override_settings(SYSTEM_MONITOR={
            "NGINX_STATUS_URL": "https://127.0.0.1/nginx_status", "NGINX_STATUS_HOST": "proctoring.example.uz",
        }), mock.patch("requests.get", return_value=_response()) as get:
            data, _counters = collectors.nginx()
        self.assertEqual(get.call_args.kwargs["headers"], {"Host": "proctoring.example.uz"})
        self.assertTrue(data["available"])

    def test_remote_host_keeps_certificate_check(self):
        _data, _counters, get = self.fetch("https://monitor.example.uz/nginx_status")
        self.assertTrue(get.call_args.kwargs["verify"])

    def test_http_redirect_is_explained(self):
        """80-port HTTPS'ga yo'naltiradi — ergashilmaydi, sababi aytiladi."""
        data, _counters, _get = self.fetch("http://127.0.0.1/nginx_status", status=301, redirect=True)
        self.assertEqual(data["error"], "redirect")

    def test_denied(self):
        data, _counters, _get = self.fetch("https://127.0.0.1/nginx_status", status=403)
        self.assertEqual(data["error"], "forbidden")

    def test_not_configured(self):
        with override_settings(SYSTEM_MONITOR={"NGINX_STATUS_URL": ""}):
            data, _counters = collectors.nginx()
        self.assertEqual(data, {"available": False, "configured": False})

    def test_connection_error(self):
        with override_settings(SYSTEM_MONITOR={"NGINX_STATUS_URL": "https://127.0.0.1/nginx_status"}), \
                mock.patch("requests.get", side_effect=requests.exceptions.ConnectionError("refused")):
            data, _counters = collectors.nginx()
        self.assertEqual(data["error"], "unreachable")
