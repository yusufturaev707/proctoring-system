"""
`client_ip` — proksi header'lariga ishonish qoidasi.

Bu loyihadagi eng nozik nuqtalardan biri: `client_ip` natijasi IP
allowlist qaroriga ham, throttling kalitiga ham kiradi. Agar u
client yozgan header'ga ishonsa, uydan turib
`X-Forwarded-For: <ruxsat etilgan IP>` yuborish bilan ikkala himoya
ham chetlab o'tiladi.

Shuning uchun bu yerdagi testlarning yarmi HUJUM stsenariysi.
"""

from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.common.throttling import client_ip


class ClientIpTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request(self, remote_addr="203.0.113.9", **headers):
        return self.factory.post("/", REMOTE_ADDR=remote_addr, **headers)

    # --- Proksisiz (standart) --------------------------------------
    @override_settings(TRUSTED_PROXY_COUNT=0)
    def test_without_proxy_uses_remote_addr(self):
        request = self._request(remote_addr="198.51.100.7")
        self.assertEqual(client_ip(request), "198.51.100.7")

    @override_settings(TRUSTED_PROXY_COUNT=0)
    def test_without_proxy_ignores_forwarded_headers(self):
        """
        HUJUM: client o'zi ruxsat etilgan IP'ni yozib yuboradi.

        `TRUSTED_PROXY_COUNT=0` da header'lar butunlay e'tiborsiz
        qoldirilishi SHART — aks holda allowlist ma'nosini yo'qotadi.
        """
        request = self._request(
            remote_addr="198.51.100.7",
            HTTP_X_FORWARDED_FOR="10.0.0.1, 8.8.8.8",
            HTTP_X_REAL_IP="10.0.0.1",
        )
        self.assertEqual(client_ip(request), "198.51.100.7")

    # --- Bitta ishonchli proksi (nginx) ----------------------------
    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_prefers_x_real_ip(self):
        """nginx `X-Real-IP` ni `$remote_addr` dan qayta yozadi."""
        request = self._request(
            remote_addr="127.0.0.1",
            HTTP_X_REAL_IP="203.0.113.44",
            HTTP_X_FORWARDED_FOR="1.2.3.4",
        )
        self.assertEqual(client_ip(request), "203.0.113.44")

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_falls_back_to_rightmost_forwarded_entry(self):
        """
        `X-Real-IP` bo'lmasa — XFF zanjirining O'NGDAN 1-elementi.

        Chapdagi qiymatni olish klassik xato: zanjirning chap qismini
        client o'zi to'ldirib yuborishi mumkin.
        """
        request = self._request(
            remote_addr="127.0.0.1",
            HTTP_X_FORWARDED_FOR="10.0.0.1, 203.0.113.44",
        )
        self.assertEqual(client_ip(request), "203.0.113.44")

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_spoofed_left_entry_is_not_used(self):
        """HUJUM: zanjir boshiga soxta manzil qo'shish."""
        request = self._request(
            remote_addr="127.0.0.1",
            HTTP_X_FORWARDED_FOR="203.0.113.99, 198.51.100.7",
        )
        self.assertNotEqual(client_ip(request), "203.0.113.99")
        self.assertEqual(client_ip(request), "198.51.100.7")

    @override_settings(TRUSTED_PROXY_COUNT=2)
    def test_two_proxies_take_second_from_right(self):
        request = self._request(
            remote_addr="127.0.0.1",
            HTTP_X_FORWARDED_FOR="1.1.1.1, 203.0.113.44, 10.0.0.5",
        )
        self.assertEqual(client_ip(request), "203.0.113.44")

    @override_settings(TRUSTED_PROXY_COUNT=2)
    def test_short_chain_falls_back_to_remote_addr(self):
        """
        Zanjir kutilganidan qisqa — konfiguratsiya noto'g'ri.

        Bunday holatda taxmin qilish emas, `REMOTE_ADDR` ga qaytish
        kerak: taxmin allowlist qarorini soxta qiymatga asoslardi.
        """
        request = self._request(
            remote_addr="198.51.100.7", HTTP_X_FORWARDED_FOR="203.0.113.44"
        )
        self.assertEqual(client_ip(request), "198.51.100.7")

    # --- Buzilgan konfiguratsiya -----------------------------------
    @override_settings(TRUSTED_PROXY_COUNT="notanumber")
    def test_invalid_setting_falls_back_to_zero(self):
        """
        `.env` da xato qiymat bo'lsa - eng XAVFSIZ holatga tushamiz.

        `0` = header'larga umuman ishonmaslik.
        """
        request = self._request(
            remote_addr="198.51.100.7", HTTP_X_REAL_IP="203.0.113.44"
        )
        self.assertEqual(client_ip(request), "198.51.100.7")

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_blank_real_ip_is_skipped(self):
        request = self._request(
            remote_addr="127.0.0.1",
            HTTP_X_REAL_IP="   ",
            HTTP_X_FORWARDED_FOR="203.0.113.44",
        )
        self.assertEqual(client_ip(request), "203.0.113.44")

    @override_settings(TRUSTED_PROXY_COUNT=0)
    def test_missing_remote_addr(self):
        request = self.factory.post("/")
        request.META.pop("REMOTE_ADDR", None)
        self.assertEqual(client_ip(request), "0.0.0.0")
