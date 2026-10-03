"""
O'rnatilgan dasturda jarayon muhiti ishonchsiz (`core/env_guard.py`).

Qo'riqlanadigan hujum: talabgor administrator huquqisiz `setx` bilan
foydalanuvchi o'zgaruvchisini yozadi va keyingi kirishda kiosk
himoyasi o'chadi:

  * `KIOSK_MODE=0` / `SCREENSHOT_ENABLED=0` - `.env` da yozilmagan kalit;
  * `PROCTORING_ENV_FILE` - administrator faylini almashtirish;
  * `ProgramData` - `.env` qidiriladigan katalogni burish;
  * `QTWEBENGINE_REMOTE_DEBUGGING`, `QTWEBENGINE_CHROMIUM_FLAGS`,
    `SSL_CERT_FILE` - Chromium/httpx'ni o'zgartirish.

Dev rejim (frozen emas) o'zgarmaydi - u yerda muhit qulaylik.
"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from core import bundle_paths, env_guard

CLIENT_DIR = Path(__file__).resolve().parent.parent

TRUSTED = {
    "SystemRoot": r"C:\Windows",
    "windir": r"C:\Windows",
    "ProgramData": r"C:\ProgramData",
    "ALLUSERSPROFILE": r"C:\ProgramData",
}


class SanitizeTests(unittest.TestCase):
    def test_dev_mode_untouched(self):
        env = {"QTWEBENGINE_REMOTE_DEBUGGING": "9222", "ProgramData": r"C:\Users\x"}
        self.assertEqual(env_guard.sanitize_process_env(env, frozen=False), [])
        self.assertEqual(env["QTWEBENGINE_REMOTE_DEBUGGING"], "9222")
        self.assertEqual(env["ProgramData"], r"C:\Users\x")

    def test_frozen_removes_untrusted(self):
        env = {
            "QTWEBENGINE_CHROMIUM_FLAGS": "--ignore-certificate-errors",
            "QTWEBENGINE_REMOTE_DEBUGGING": "0.0.0.0:9222",
            "QTWEBENGINEPROCESS_PATH": r"C:\Users\x\evil.exe",
            "QT_QPA_PLATFORM": "offscreen",
            "SSL_CERT_FILE": r"C:\Users\x\ca.pem",
            "SSL_CERT_DIR": r"C:\Users\x",
            "CUDA_PATH_V12_4": r"C:\Users\x\cuda",
            "INSIGHTFACE_ROOT": r"C:\Users\x\models",
            # Qolishi kerak: tizim/qonuniy qiymatlar.
            "PATH": r"C:\Windows\System32",
            "HTTPS_PROXY": "http://proxy:3128",
            "QT_PLUGIN_PATH": r"C:\app\_internal\PyQt6\Qt6\plugins",
            **TRUSTED,
        }
        removed = env_guard.sanitize_process_env(env, frozen=True, system_dirs=TRUSTED)
        for name in (
            "QTWEBENGINE_CHROMIUM_FLAGS", "QTWEBENGINE_REMOTE_DEBUGGING",
            "QTWEBENGINEPROCESS_PATH", "QT_QPA_PLATFORM", "SSL_CERT_FILE",
            "SSL_CERT_DIR", "CUDA_PATH_V12_4", "INSIGHTFACE_ROOT",
        ):
            with self.subTest(name=name):
                self.assertNotIn(name, env)
                self.assertIn(name, removed)
        for name in ("PATH", "HTTPS_PROXY", "QT_PLUGIN_PATH", "ProgramData", "SystemRoot"):
            with self.subTest(kept=name):
                self.assertIn(name, env)
        self.assertNotIn("ProgramData", removed)

    def test_frozen_restores_spoofed_system_dirs(self):
        # Windows'da `os.environ` kalitlari katta harfda - registrga befarq.
        env = {"PROGRAMDATA": r"C:\Users\student\fake", "SYSTEMROOT": r"C:\Users\student\win"}
        changed = env_guard.sanitize_process_env(env, frozen=True, system_dirs=TRUSTED)
        self.assertEqual(env["ProgramData"], r"C:\ProgramData")
        self.assertEqual(env["SystemRoot"], r"C:\Windows")
        self.assertNotIn("PROGRAMDATA", env)
        self.assertIn("ProgramData", changed)
        self.assertIn("SystemRoot", changed)

    def test_same_value_different_case_is_not_reported(self):
        env = {"PROGRAMDATA": r"c:\programdata"}
        changed = env_guard.sanitize_process_env(
            env, frozen=True, system_dirs={"ProgramData": r"C:\ProgramData"}
        )
        self.assertEqual(changed, [])

    @unittest.skipUnless(sys.platform == "win32", "Windows API")
    def test_trusted_dirs_from_windows_api(self):
        dirs = env_guard.trusted_system_dirs()
        self.assertTrue(os.path.isdir(dirs["SystemRoot"]))
        self.assertTrue(os.path.isdir(dirs["ProgramData"]))


class ConfigSourceTests(unittest.TestCase):
    def test_frozen_reads_only_file(self):
        source = env_guard.config_source(
            {"API_BASE_URL": "https://x/api/v1", "EMPTY": None},
            {"KIOSK_MODE": "0", "API_BASE_URL": "http://evil"},
            frozen=True,
        )
        self.assertEqual(source, {"API_BASE_URL": "https://x/api/v1"})

    def test_dev_reads_environment(self):
        environ = {"KIOSK_MODE": "0"}
        self.assertIs(env_guard.config_source({}, environ, frozen=False), environ)


class MachineValueTests(unittest.TestCase):
    def test_program_data_expanded_from_trusted(self):
        self.assertEqual(
            env_guard.expand_machine_value(r"%ProgramData%\Pc\.env", TRUSTED),
            r"C:\ProgramData\Pc\.env",
        )

    def test_other_variables_rejected(self):
        # `%USERPROFILE%` ni foydalanuvchi boshqaradi - qabul qilinmaydi.
        self.assertIsNone(env_guard.expand_machine_value(r"%USERPROFILE%\x.env", TRUSTED))

    def test_plain_value(self):
        self.assertEqual(env_guard.expand_machine_value(r"  D:\cfg\.env ", TRUSTED), r"D:\cfg\.env")
        self.assertIsNone(env_guard.expand_machine_value("   ", TRUSTED))


class ExplicitEnvFileTests(unittest.TestCase):
    def test_frozen_ignores_user_level_variable(self):
        with mock.patch.dict(os.environ, {"PROCTORING_ENV_FILE": r"C:\Users\x\my.env"}), \
                mock.patch.object(bundle_paths, "is_frozen", return_value=True), \
                mock.patch.object(env_guard, "machine_env", return_value=None):
            self.assertEqual(bundle_paths.explicit_env_file(), "")

    def test_frozen_honours_machine_level_variable(self):
        with mock.patch.object(bundle_paths, "is_frozen", return_value=True), \
                mock.patch.object(env_guard, "machine_env", return_value=r"D:\cfg\.env"):
            self.assertEqual(bundle_paths.explicit_env_file(), r"D:\cfg\.env")

    def test_dev_uses_process_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = str(Path(tmp) / "dev.env")
            with mock.patch.dict(os.environ, {"PROCTORING_ENV_FILE": target}), \
                    mock.patch.object(bundle_paths, "is_frozen", return_value=False):
                self.assertEqual(bundle_paths.explicit_env_file(), target)


# `config` qiymatlari IMPORT paytida hisoblanadi - frozen rejim alohida
# jarayonda taqlid qilinadi (bu jarayondagi `config` ga tegmaslik uchun).
_PROBE = textwrap.dedent(
    """
    import json, sys
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    sys.frozen = sys.argv[3] == "1"
    import core.bundle_paths as bp
    bp.env_file_path = lambda: Path(sys.argv[2])
    import config
    print(json.dumps({
        "API_BASE_URL": config.API_BASE_URL,
        "KIOSK_MODE": config.KIOSK_MODE,
        "FULLSCREEN": config.FULLSCREEN,
        "SCREENSHOT_ENABLED": config.SCREENSHOT_ENABLED,
        "CLOSE_OTHER_APPS": config.CLOSE_OTHER_APPS,
        "LOCAL_SERVICE_ALLOWED_ORIGINS": config.LOCAL_SERVICE_ALLOWED_ORIGINS,
    }))
    """
)


class FrozenConfigTests(unittest.TestCase):
    def _probe(self, frozen: bool) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "API_BASE_URL=https://exam.example.uz/api/v1\nCLOSE_OTHER_APPS=false\n",
                encoding="utf-8",
            )
            env = dict(os.environ)
            env.update({
                # Talabgor `setx` bilan yozgan qiymatlar.
                "KIOSK_MODE": "0",
                "FULLSCREEN": "0",
                "SCREENSHOT_ENABLED": "0",
                "LOCAL_SERVICE_ALLOWED_ORIGINS": "*",
                "API_BASE_URL": "http://evil.local/api/v1",
                "CLOSE_OTHER_APPS": "true",
            })
            result = subprocess.run(
                [sys.executable, "-c", _PROBE, str(CLIENT_DIR), str(env_file), "1" if frozen else "0"],
                capture_output=True, text=True, env=env, cwd=str(CLIENT_DIR), timeout=60,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_frozen_ignores_user_environment(self):
        values = self._probe(frozen=True)
        self.assertTrue(values["KIOSK_MODE"])
        self.assertTrue(values["FULLSCREEN"])
        self.assertTrue(values["SCREENSHOT_ENABLED"])
        self.assertEqual(values["LOCAL_SERVICE_ALLOWED_ORIGINS"], [])
        # Fayldagi qiymat - muhitdagidan ustun.
        self.assertEqual(values["API_BASE_URL"], "https://exam.example.uz/api/v1")
        self.assertFalse(values["CLOSE_OTHER_APPS"])

    def test_dev_environment_still_overrides(self):
        values = self._probe(frozen=False)
        self.assertFalse(values["KIOSK_MODE"])
        self.assertEqual(values["API_BASE_URL"], "http://evil.local/api/v1")


if __name__ == "__main__":
    unittest.main()
