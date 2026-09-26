"""
Tezkor tugmalar: `.env` standarti va server ro'yxati.

Qoida (`services/lockdown.py:resolve_hotkeys`): dastur ishga tushishi
bilan `.env` dagi `BLOCKED_HOTKEYS` qo'llanadi, server ro'yxati kelsa
uni ALMASHTIRADI, server BO'SH ro'yxat bersa standart QOLADI -
"administrator sozlamagan" hech qachon "hech narsa bloklanmasin"
degani emas.
"""

import os
import unittest
from unittest import mock

import config
from services.lockdown import _NEVER_BLOCKED, _normalize, resolve_hotkeys

DEFAULT = ["alt+tab", "win", "alt+f4"]


class ResolveHotkeysTests(unittest.TestCase):
    def test_server_list_replaces_default(self):
        """Almashtiradi, ustiga qo'shmaydi: profildan olingan tugma ochiladi."""
        self.assertEqual(resolve_hotkeys(["ctrl+c"], DEFAULT), ["ctrl+c"])

    def test_empty_server_list_keeps_default(self):
        self.assertEqual(resolve_hotkeys([], DEFAULT), DEFAULT)

    def test_missing_server_list_keeps_default(self):
        """Eski server yoki preflight javob bermadi."""
        self.assertEqual(resolve_hotkeys(None, DEFAULT), DEFAULT)

    def test_both_empty(self):
        self.assertEqual(resolve_hotkeys([], []), [])
        self.assertEqual(resolve_hotkeys(None, None), [])

    def test_blank_codes_dropped(self):
        self.assertEqual(resolve_hotkeys(["", "  ", "win"], DEFAULT), ["win"])

    def test_result_is_a_copy(self):
        server = ["win"]
        result = resolve_hotkeys(server, DEFAULT)
        result.append("alt+tab")
        self.assertEqual(server, ["win"])


class EnvDefaultTests(unittest.TestCase):
    def _parse(self, raw=None):
        env = dict(os.environ)
        env.pop("BLOCKED_HOTKEYS", None)
        if raw is not None:
            env["BLOCKED_HOTKEYS"] = raw
        with mock.patch.dict(os.environ, env, clear=True):
            return config._env_list("BLOCKED_HOTKEYS", config.DEFAULT_BLOCKED_HOTKEYS)

    def test_default_set_is_safe(self):
        """Standartda chiqish (`ctrl+q`) ham, til almashtirish ham yo'q."""
        codes = [_normalize(code) for code in self._parse()]
        self.assertIn("alt+tab", codes)
        self.assertIn("win", codes)
        for code in codes:
            self.assertNotIn(code, _NEVER_BLOCKED)
        self.assertNotIn("alt+shift", codes)
        self.assertNotIn("ctrl+c", codes)

    def test_env_value_parsed(self):
        self.assertEqual(self._parse(" Alt+Tab , ,WIN "), ["alt+tab", "win"])

    def test_empty_env_value_means_no_default(self):
        """Bo'sh qiymat - mashina darajasidagi ochiq qaror (qulf standartsiz)."""
        self.assertEqual(self._parse(""), [])


if __name__ == "__main__":
    unittest.main()
