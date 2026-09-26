"""
Lokal xizmat (`services/local_service.py`) - test platformasi bilan shartnoma.

Qo'riqlanadigan narsalar:

  1. `device_info` shakli AYNAN platforma kutgandek (kalitlar, `number`
     satr, MAC kichik harf) - shartnoma buzilsa platforma jimgina
     bo'sh qiymat ko'rsatadi;
  2. begona Origin va loopback bo'lmagan Host rad etiladi, CORS/PNA
     preflight'iga to'g'ri javob beriladi;
  3. imtihon ochiq bo'lmasa skrinshot buyrug'i 409 (202 emas) -
     platforma "kadr olindi" deb o'ylamasligi kerak;
  4. SMBIOS UUID bayt tartibi `wmic` bilan bir xil.
"""

import json
import socket
import unittest
import urllib.error
import urllib.request

from PyQt6.QtCore import Qt

from services import local_service as ls
from services.system_info import parse_smbios_uuid


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class RulesTests(unittest.TestCase):
    def test_payload_shape(self):
        payload = ls.device_payload(
            machine_uuid="4C4C4544-0038-4A10-805A-C7C04F400000",
            ip="192.168.0.194", mac="2C-F0-5D-77-BB-EB", number=13,
        )
        self.assertEqual(payload, {
            "machine_uuid": "4C4C4544-0038-4A10-805A-C7C04F400000",
            "ip": "192.168.0.194", "mac": "2c:f0:5d:77:bb:eb", "number": "13",
        })

    def test_unknown_values_are_null(self):
        payload = ls.device_payload(machine_uuid="", ip="", mac="", number=None)
        self.assertEqual(set(payload.values()), {None})

    def test_origin_rules(self):
        allowed = ls.origin_allowed
        # Origin'siz (brauzer emas) - o'tadi.
        self.assertTrue(allowed("", extra=[], exam_domains=None))
        # Imtihon yo'q - faqat `.env` ro'yxati.
        self.assertFalse(allowed("https://test.uz", extra=[], exam_domains=None))
        self.assertTrue(allowed("https://test.uz", extra=["https://test.uz"], exam_domains=None))
        self.assertTrue(allowed("http://evil.uz", extra=["*"], exam_domains=None))
        # Imtihon: domen va subdomen, WebView allowlist'i bilan bir xil.
        self.assertTrue(allowed("https://test.uz", extra=[], exam_domains=["test.uz"]))
        self.assertTrue(allowed("https://app.test.uz:8443", extra=[], exam_domains=["test.uz"]))
        self.assertFalse(allowed("https://eviltest.uz", extra=[], exam_domains=["test.uz"]))
        # Serverda cheklov yo'q - WebView ham to'smaydi.
        self.assertTrue(allowed("https://any.uz", extra=[], exam_domains=[]))

    def test_host_rules(self):
        self.assertTrue(ls.host_allowed("localhost:8050", 8050))
        self.assertTrue(ls.host_allowed("127.0.0.1:8050", 8050))
        self.assertTrue(ls.host_allowed("[::1]:8050", 8050))
        self.assertFalse(ls.host_allowed("evil.uz:8050", 8050))
        self.assertFalse(ls.host_allowed("localhost:9999", 8050))


class PayloadTests(unittest.TestCase):
    def test_accepts_strings_numbers_form_and_query(self):
        parse = ls.parse_capture_payload
        self.assertEqual(parse(b'{"q_id": "1", "q_n": "3"}', "application/json"), {"q_id": "1", "q_n": 3})
        self.assertEqual(parse(b'{"q_id": 17, "q_n": 3.0}'), {"q_id": "17", "q_n": 3})
        self.assertEqual(parse(b"q_id=a-b_1&q_n=12", "application/x-www-form-urlencoded"), {"q_id": "a-b_1", "q_n": 12})
        self.assertEqual(parse(b"", "", "q_id=9&q_n=4"), {"q_id": "9", "q_n": 4})
        self.assertEqual(parse(b'{"q_id": "5"}'), {"q_id": "5"})
        self.assertEqual(parse(b""), {})
        self.assertEqual(parse(b"{}"), {})

    def test_rejects_unsafe_or_broken_values(self):
        for body in (
            b'{"q_id": "a/b"}', b'{"q_id": "a b"}', b'{"q_id": true}', b'{"q_id": "' + b"x" * 65 + b'"}',
            b'{"q_id": "1", "q_n": 0}', b'{"q_id": "1", "q_n": "3a"}', b'{"q_id": "1", "q_n": 2.5}',
            b'{"q_id": "1", "q_n": true}', b"[1, 2]", b'{"q_n": "3"}',
        ):
            with self.subTest(body=body):
                with self.assertRaises(ls.PayloadError):
                    ls.parse_capture_payload(body, "application/json")


class MachineUuidTests(unittest.TestCase):
    def test_normalize(self):
        from services.system_info import normalize_machine_uuid as norm

        self.assertEqual(
            norm("{c7b0b7bd-c0c0-d71d-abd3-2cf05d77bbeb}"), "C7B0B7BD-C0C0-D71D-ABD3-2CF05D77BBEB"
        )
        for bad in (
            "", None, "xyz", "C7B0B7BD-C0C0-D71D-ABD3-2CF05D77BBE",
            "00000000-0000-0000-0000-000000000000", "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF",
            "03000200-0400-0500-0006-000700080009", "11111111-1111-1111-1111-111111111111",
        ):
            with self.subTest(bad=bad):
                self.assertEqual(norm(bad), "")

    def test_chain_falls_back_and_never_empty(self):
        from unittest import mock

        from services import system_info as si

        with mock.patch.object(si, "_uuid_cache", None),                 mock.patch.object(si, "_uuid_from_smbios", return_value="03000200-0400-0500-0006-000700080009"),                 mock.patch.object(si, "_uuid_from_registry", side_effect=OSError("denied")),                 mock.patch.object(si, "_uuid_from_cim", return_value="{4c4c4544-0038-4a10-805a-c7c04f400000}"):
            self.assertEqual(si.machine_uuid(), "4C4C4544-0038-4A10-805A-C7C04F400000")
            self.assertEqual(si.machine_uuid_source(), "cim")
        with mock.patch.object(si, "_uuid_cache", None),                 mock.patch.object(si, "_uuid_from_smbios", return_value=""),                 mock.patch.object(si, "_uuid_from_registry", return_value=""),                 mock.patch.object(si, "_uuid_from_cim", return_value=""),                 mock.patch.object(si, "_uuid_from_wmic", return_value=""),                 mock.patch.object(si, "machine_identity", return_value={"mac": "AA:BB:CC:DD:EE:FF"}):
            value = si.machine_uuid()
            self.assertEqual(si.normalize_machine_uuid(value), value)
            self.assertTrue(si.machine_uuid_source().startswith("derived"))


class QuestionArchiveTests(unittest.TestCase):
    """Savol kadri: nomda q_n va q_id, qayta belgilashda ALMASHADI."""

    def setUp(self):
        import tempfile
        from unittest import mock

        from services import local_archive

        self.archive = local_archive
        self.folder = tempfile.mkdtemp()
        for patcher in (
            mock.patch.object(local_archive, "LOCAL_ARCHIVE_ENABLED", True),
            mock.patch.object(local_archive, "session_folder", return_value=self.folder),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def save(self, data, q_id, q_n, hour, minute, second):
        from datetime import datetime

        return self.archive.save_question_shot(
            data, question_id=q_id, question_number=q_n,
            captured_at=datetime(2026, 9, 25, hour, minute, second),
            exam_type="t", exam="e", session_id="s", pinfl="p", mac="m",
        )

    def test_reanswer_replaces_file_with_new_time(self):
        import os

        self.save(b"first", "1", 3, 14, 5, 33)
        self.save(b"other", "12", 4, 14, 6, 0)   # "1" ning prefiksi - tegilmaydi
        path = self.save(b"second", "1", 3, 14, 9, 2)
        names = sorted(os.listdir(self.folder))
        self.assertEqual(names, ["q003_id1_14-09-02.jpg", "q004_id12_14-06-00.jpg"])
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), b"second")

    def test_same_second_overwrites_and_no_temp_left(self):
        import os

        self.save(b"a", "Q_7", None, 9, 0, 0)
        self.save(b"b", "Q_7", None, 9, 0, 0)
        self.assertEqual(os.listdir(self.folder), ["idQ_7_09-00-00.jpg"])


class SmbiosTests(unittest.TestCase):
    @staticmethod
    def _table(uuid_bytes: bytes, major=3, minor=4) -> bytes:
        # 0-tur (BIOS) + satr, keyin 1-tur (System) + satrlar, oxiri 127.
        bios = bytes([0, 4, 0, 0]) + b"Vendor\x00\x00"
        system = bytes([1, 0x1B, 1, 0]) + bytes(4) + uuid_bytes + bytes(3) + b"\x00\x00"
        end = bytes([127, 4, 2, 0]) + b"\x00\x00"
        table = bios + system + end
        return bytes([0, major, minor, 0]) + len(table).to_bytes(4, "little") + table

    def test_modern_little_endian_matches_wmic(self):
        raw = bytes.fromhex("4445 4C4C 3800 104A 805A C7C04F400000".replace(" ", ""))
        self.assertEqual(
            parse_smbios_uuid(self._table(raw)), "4C4C4544-0038-4A10-805A-C7C04F400000"
        )

    def test_legacy_big_endian(self):
        raw = bytes.fromhex("4C4C454400384A10805AC7C04F400000")
        self.assertEqual(
            parse_smbios_uuid(self._table(raw, major=2, minor=4)),
            "4C4C4544-0038-4A10-805A-C7C04F400000",
        )

    def test_unset_uuid_is_empty(self):
        self.assertEqual(parse_smbios_uuid(self._table(b"\xff" * 16)), "")
        self.assertEqual(parse_smbios_uuid(b"\x00"), "")


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.port = _free_port()
        self.captures = 0
        self.service = ls.LocalDeviceService(
            lambda: ls.device_payload(machine_uuid="U", ip="10.0.0.5", mac="AA:BB:CC:DD:EE:FF", number=7),
            port=self.port,
        )
        # DIRECT: testda Qt hodisa sikli yo'q. Ilovada ulanish navbatli -
        # kadr UI thread'ida olinadi (`ExamWebViewPage`).
        self.service.capture_requested.connect(
            self._on_capture, Qt.ConnectionType.DirectConnection
        )
        self.assertTrue(self.service.start())

    def tearDown(self):
        self.service.stop()

    def _on_capture(self, question):
        self.captures += 1
        self.last_question = question

    def call(self, method, path, origin=None, body=b"{}"):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method)
        if origin:
            request.add_header("Origin", origin)
        if method == "POST":
            request.data = body
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read()

    def test_device_info(self):
        status, _, body = self.call("GET", "/api/device_info")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {
            "machine_uuid": "U", "ip": "10.0.0.5", "mac": "aa:bb:cc:dd:ee:ff", "number": "7",
        })

    def test_capture_requires_active_exam(self):
        status, _, body = self.call("POST", "/api/capture_screen")
        self.assertEqual((status, json.loads(body)["error"]), (409, "no_active_exam"))
        self.service.set_capture_target(True, ["test.uz"])
        status, headers, _ = self.call("POST", "/api/capture_screen", origin="https://test.uz")
        self.assertEqual(status, 202)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "https://test.uz")
        self.assertEqual(self.captures, 1)

    def test_foreign_origin_rejected(self):
        self.service.set_capture_target(True, ["test.uz"])
        status, _, _ = self.call("POST", "/api/capture_screen", origin="https://evil.uz")
        self.assertEqual(status, 403)
        self.assertEqual(self.captures, 0)

    def test_preflight_allows_private_network(self):
        self.service.set_capture_target(True, ["test.uz"])
        status, headers, _ = self.call("OPTIONS", "/api/capture_screen", origin="https://test.uz")
        self.assertEqual(status, 204)
        self.assertEqual(headers.get("Access-Control-Allow-Private-Network"), "true")
        self.assertIn("POST", headers.get("Access-Control-Allow-Methods", ""))

    def test_capture_with_question(self):
        self.service.set_capture_target(True, [])
        status, _, body = self.call(
            "POST", "/api/capture_screen", body=b'{"q_id": "1", "q_n": "3"}'
        )
        self.assertEqual(status, 202)
        self.assertEqual(json.loads(body)["q_n"], 3)
        self.assertEqual(self.last_question, {"q_id": "1", "q_n": 3})

    def test_invalid_payload_is_400_and_not_captured(self):
        self.service.set_capture_target(True, [])
        for body, code in (
            (b'{"q_id": "../x"}', "invalid_q_id"),
            (b'{"q_id": "1", "q_n": "-2"}', "invalid_q_n"),
            (b'{"q_n": 3}', "q_id_required"),
            (b"{not json", "invalid_json"),
        ):
            with self.subTest(body=body):
                status, _, raw = self.call("POST", "/api/capture_screen", body=body)
                self.assertEqual((status, json.loads(raw)["error"]), (400, code))
        self.assertEqual(self.captures, 0)

    def test_rate_limit(self):
        self.service.set_capture_target(True, [])
        statuses = [self.service.request_capture({}) for _ in range(ls._MAX_CAPTURES_PER_SECOND + 3)]
        self.assertEqual(statuses.count("accepted"), ls._MAX_CAPTURES_PER_SECOND)
        self.assertEqual(statuses[-1], "throttled")

    def test_unknown_path(self):
        self.assertEqual(self.call("GET", "/api/other")[0], 404)
