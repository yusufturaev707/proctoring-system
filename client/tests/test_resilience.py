"""
Global himoya qatlamining sof mantig'i (C1): log niqobi, xato cheklovi,
holat fayli, watchdog qarori, tizim hodisalari tasnifi, self-check.

GUI ochilmaydi, jarayon o'ldirilmaydi - faqat qaror qiluvchi funksiyalar.
"""

from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import crash_guard, self_check, state_store, system_events, watchdog  # noqa: E402
from core.log_redaction import redact  # noqa: E402


class RedactionTests(unittest.TestCase):
    def test_jwt_and_bearer(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.abcdefghijk"
        text = redact("Authorization: Bearer {} token={}".format(jwt, jwt))
        self.assertNotIn(jwt, text)
        self.assertNotIn("eyJzdWIi", text)

    def test_key_values(self):
        text = redact('{"password": "Sirli123", "proctoring_session_token": "abcDEF123456"}')
        self.assertNotIn("Sirli123", text)
        self.assertNotIn("abcDEF123456", text)
        self.assertIn("password", text)

    def test_test_link_and_query_token(self):
        text = redact("test_link=https://test.uz/login?token=QWERTY12345 ok")
        self.assertNotIn("QWERTY12345", text)

    def test_pinfl_masked(self):
        text = redact("JSHSHIR 32701234560024 topildi")
        self.assertNotIn("32701234560024", text)
        self.assertIn("3270******0024", text)

    def test_pinfl_in_archive_path(self):
        # `local_archive` papka nomi: <sessiya>_<jshshir>_<mac> (C3 topilmasi).
        text = redact(r"Arxiv: D:\Arxiv\SAT\2026-09-30\a1b2c3_32701234560024_aabbccddeeff\screen.mp4")
        self.assertNotIn("32701234560024", text)
        self.assertIn("_3270******0024_", text)

    def test_ordinary_numbers_untouched(self):
        line = "port=8050 pid=12345 vaqt 1700000000.123 kod 0xC0000409"
        self.assertEqual(redact(line), line)

    def test_embedding_vector(self):
        vector = ", ".join("0.{:04d}".format(i) for i in range(40))
        self.assertNotIn("0.0020", redact("emb [{}]".format(vector)))

    def test_data_uri(self):
        text = redact("rasm data:image/jpeg;base64," + "A" * 200)
        self.assertNotIn("AAAAAAAAAAAAAAAA", text)


class ErrorThrottleTests(unittest.TestCase):
    def test_same_signature_limited(self):
        throttle = crash_guard.ErrorThrottle(repeat_s=60, global_gap_s=5)
        self.assertEqual(throttle.record("A", 0.0), (1, True))
        self.assertEqual(throttle.record("A", 1.0), (2, False))
        self.assertEqual(throttle.record("A", 30.0), (3, False))
        self.assertEqual(throttle.record("A", 61.0), (4, True))

    def test_global_gap(self):
        throttle = crash_guard.ErrorThrottle(repeat_s=60, global_gap_s=5)
        self.assertTrue(throttle.record("A", 0.0)[1])
        self.assertFalse(throttle.record("B", 2.0)[1])
        self.assertTrue(throttle.record("B", 6.0)[1])

    def test_signature(self):
        try:
            raise ValueError("x")
        except ValueError:
            exc_type, _value, tb = sys.exc_info()
        self.assertTrue(crash_guard.signature_of(exc_type, tb).startswith("ValueError (test_resilience.py:"))

    def test_hook_never_raises(self):
        # Ilgak ichida log yiqilsa ham istisno chiqmasligi kerak.
        with mock.patch("logging.Logger.error", side_effect=RuntimeError("log")):
            crash_guard._excepthook(ValueError, ValueError("x"), None)


class StateStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_rejects_secrets(self):
        store = state_store.StateStore(self.path)
        store.update(stage="exam", token="SECRET", pinfl="32701234560024", exam_id=5)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["stage"], "exam")
        self.assertEqual(data["exam_id"], 5)
        self.assertNotIn("token", data)
        self.assertNotIn("pinfl", data)

    def test_crash_detection_and_clean_exit(self):
        first = state_store.StateStore(self.path)
        self.assertEqual(first.begin(pid=100, app_version="1"), {})
        first.update(stage="exam", exam_id=7, session_public_id="abc")
        # Toza chiqishsiz yangi jarayon - oldingisi "yiqilgan".
        second = state_store.StateStore(self.path)
        crash = second.begin(pid=200, app_version="1", restart_count=1)
        self.assertEqual(crash["pid"], 100)
        self.assertTrue(state_store.had_open_session(crash))
        second.mark_clean_exit("parol bilan chiqish")
        third = state_store.StateStore(self.path)
        self.assertEqual(third.begin(pid=300, app_version="1"), {})

    def test_disk_full_does_not_raise(self):
        store = state_store.StateStore(self.path)
        with mock.patch.object(state_store, "atomic_write_json",
                               side_effect=OSError(errno.ENOSPC, "No space left")):
            self.assertFalse(store.update(stage="login"))
        self.assertEqual(store.data["stage"], "login")  # xotirada qoldi
        self.assertTrue(store.update(stage="exam_select"))

    def test_atomic_write_leaves_no_tmp_on_error(self):
        with mock.patch("os.replace", side_effect=OSError("band")):
            with self.assertRaises(OSError):
                state_store.atomic_write_json(self.path, {"a": 1})
        self.assertEqual([p for p in Path(self.tmp.name).iterdir()], [])

    def test_broken_json_is_empty(self):
        self.path.write_text("{yarim", encoding="utf-8")
        self.assertEqual(state_store.read_json(self.path), {})


class WatchdogLogicTests(unittest.TestCase):
    def test_restart_limit(self):
        policy = watchdog.RestartPolicy(max_restarts=3, window_s=300)
        for t in (0, 10, 20):
            self.assertTrue(policy.allow(t))
            policy.record(t)
        self.assertFalse(policy.allow(30))
        self.assertTrue(policy.allow(301))  # birinchisi oynadan chiqdi

    def test_exit_reason(self):
        self.assertEqual(watchdog.exit_reason(1, clean_marker=False, shutting_down=False), "")
        self.assertEqual(watchdog.exit_reason(0xC0000005, clean_marker=False, shutting_down=False), "")
        self.assertTrue(watchdog.exit_reason(0, clean_marker=False, shutting_down=False))
        self.assertTrue(watchdog.exit_reason(0xC0000005, clean_marker=True, shutting_down=False))
        self.assertTrue(watchdog.exit_reason(1, clean_marker=False, shutting_down=True))
        self.assertTrue(watchdog.exit_reason(-1073741510, clean_marker=False, shutting_down=False))

    def test_parse_and_strip(self):
        argv = ["x.exe", "--watchdog-pid", "55", "--restart-count", "2", "--foo"]
        self.assertEqual(watchdog.parse_args(argv),
                         {"pid": 0, "restart_count": 2, "watchdog_pid": 55})
        self.assertEqual(watchdog.strip_own_flags(argv), ["x.exe", "--foo"])

    def test_bad_args(self):
        self.assertEqual(watchdog.parse_args(["--pid", "abc"])["pid"], 0)


class SystemEventsTests(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(system_events.classify_message(0x0218, 0x12), "resume")
        self.assertEqual(system_events.classify_message(0x0218, 0x07), "resume")
        self.assertEqual(system_events.classify_message(0x0218, 0x04), "suspend")
        self.assertEqual(system_events.classify_message(0x0218, 0x0A), "")
        self.assertEqual(system_events.classify_message(0x007E, 0), "display")
        self.assertEqual(system_events.classify_message(0x02E0, 0), "display")
        self.assertEqual(system_events.classify_message(0x0010, 0), "")


class SelfCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "models" / "buffalo_l").mkdir(parents=True)
        self.model = self.root / "models" / "buffalo_l" / "det_10g.onnx"
        self.model.write_bytes(b"model-bytes")

    def tearDown(self):
        self.tmp.cleanup()

    def _manifest(self, **override):
        meta = {"size": len(b"model-bytes"), "sha256": self_check.sha256_of(self.model)}
        meta.update(override)
        return {"models/buffalo_l/det_10g.onnx": meta}

    def test_sizes_ok_and_hash_cached(self):
        problems, entries = self_check.check_model_sizes(self._manifest(), self.root)
        self.assertEqual(problems, [])
        hp, cache, hashed = self_check.verify_hashes(entries, {})
        self.assertEqual((hp, hashed), ([], 1))
        hasher = mock.Mock(side_effect=AssertionError("qayta xeshlanmasligi kerak"))
        hp, _cache, hashed = self_check.verify_hashes(entries, cache, hasher=hasher)
        self.assertEqual((hp, hashed), ([], 0))

    def test_size_mismatch_and_missing(self):
        manifest = self._manifest(size=999)
        manifest["models/yolo/x.onnx"] = {"size": 1, "sha256": "00"}
        problems, _ = self_check.check_model_sizes(manifest, self.root)
        codes = sorted(p.code for p in problems)
        self.assertEqual(codes, ["model_missing", "model_size"])

    def test_hash_mismatch(self):
        _, entries = self_check.check_model_sizes(self._manifest(sha256="ab" * 32), self.root)
        problems, cache, _ = self_check.verify_hashes(entries, {})
        self.assertEqual([p.code for p in problems], ["model_hash"])
        self.assertFalse(cache["models/buffalo_l/det_10g.onnx"]["ok"])

    def test_manifest_loading(self):
        self.assertIsNone(self_check.load_manifest([self.root / "none.json"]))
        broken = self.root / "m.json"
        broken.write_text("{", encoding="utf-8")
        self.assertEqual(self_check.load_manifest([broken]), {})
        good = self.root / "g.json"
        good.write_text(json.dumps({"files": self._manifest()}), encoding="utf-8")
        self.assertIn("models/buffalo_l/det_10g.onnx", self_check.load_manifest([good]))

    def test_required_models_dev(self):
        problems = self_check.check_required_models(self.root)
        self.assertEqual([p.code for p in problems], ["model_missing"])  # w600k yo'q

    def test_config(self):
        problems = self_check.check_config(frozen=True, env_file=None,
                                           api_base_url="http://127.0.0.1:8000/api/v1")
        self.assertEqual(sorted(p.code for p in problems), ["api_url_local", "env_missing"])
        self.assertEqual(self_check.check_config(
            frozen=False, env_file=None, api_base_url="http://127.0.0.1:8000"), [])

    def test_network_and_cameras(self):
        problems = self_check.check_network("https://api.example.uz/api/v1",
                                            probe=lambda host, port: host == "api.example.uz")
        self.assertEqual([p.code for p in problems], ["internet_unreachable"])
        self.assertEqual([p.code for p in self_check.check_cameras(lambda: [])], ["camera_none"])
        self.assertEqual(self_check.check_cameras(lambda: ["cam"]), [])
        self.assertEqual(self_check.check_cameras(mock.Mock(side_effect=OSError)), [])

    def test_writable_and_bundle(self):
        self.assertEqual(self_check.check_writable(self.root, "x"), [])
        problems = self_check.check_bundle_files(self.root, ("yoq.dll",))
        self.assertEqual([p.code for p in problems], ["bundle_files"])


@unittest.skipUnless(sys.platform == "win32", "Windows mutex")
class SingleInstanceTests(unittest.TestCase):
    def test_second_process_is_rejected(self):
        from core import single_instance

        name = "Local\\ProctoringClient.Test.{}".format(os.getpid())
        self.assertTrue(single_instance.acquire(name))
        code = (
            "import sys; sys.path.insert(0, r'{}');"
            "from core import single_instance as s;"
            "sys.exit(0 if s.acquire(r'{}') else 7)"
        ).format(ROOT, name)
        result = subprocess.run([sys.executable, "-c", code], timeout=60)
        self.assertEqual(result.returncode, 7)


if __name__ == "__main__":
    unittest.main()
