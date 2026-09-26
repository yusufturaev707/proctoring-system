"""
Server boshqaradigan sozlamalar: server USTUN, `.env` ZAXIRA.

`services/runtime_settings.get` - ikki qatlamning yagona o'qish
nuqtasi. Testlar uch narsani qo'riqlaydi:

  1. server qiymati `.env` dan ustun va client birligiga o'giriladi
     (soniya -> ms, foiz -> ulush) - birlik xatosi taymerni 1000
     barobar tez yoki sekin qilib qo'yardi;
  2. kalit yo'q / `None` / buzilgan qiymat - zaxira, istisno EMAS;
  3. chegara: eski server yoki qo'lda tahrirlangan baza `0` yuborsa,
     `QTimer.setInterval(0)` clientni band qilib qo'ymasligi kerak.

Zaxira qiymatlar `config` modulidan DINAMIK o'qiladi: dev mashinasidagi
`.env` ularni o'zgartirgan bo'lishi mumkin va test bunga bog'liq
bo'lmasligi kerak.
"""

import unittest

import config
from services import runtime_settings as rs


class FallbackTests(unittest.TestCase):
    def test_every_spec_has_env_fallback(self):
        """Jadvaldagi har bir zaxira nomi `config.py` da bor."""
        for key, spec in rs.SPECS.items():
            with self.subTest(key=key):
                self.assertTrue(hasattr(config, spec.env), spec.env)

    def test_missing_config_uses_env(self):
        self.assertEqual(rs.get(None, "face.guide_seconds"), rs.fallback("face.guide_seconds"))
        self.assertEqual(rs.get({}, "rdp.block_exam"), bool(config.THREAT_BLOCK_EXAM))
        self.assertEqual(
            rs.get({"face": {}}, "face.match_streak"), rs.fallback("face.match_streak")
        )

    def test_none_and_garbage_use_fallback(self):
        for raw in (None, "abc", [], {}, float("nan")):
            with self.subTest(raw=raw):
                self.assertEqual(
                    rs.get({"face": {"fail_streak": raw}}, "face.fail_streak"),
                    rs.fallback("face.fail_streak"),
                )

    def test_explicit_default_overrides_env(self):
        self.assertEqual(rs.get({}, "face.guide_seconds", default=7), 7)

    def test_bool_is_not_a_number(self):
        """`True` sonli kalitda - buzilgan ma'lumot, 1 emas."""
        self.assertEqual(
            rs.get({"face": {"match_streak": True}}, "face.match_streak"),
            rs.fallback("face.match_streak"),
        )


class ServerValueTests(unittest.TestCase):
    def test_server_value_wins(self):
        config_ = {"face": {"guide_seconds": 0, "match_streak": 7, "fail_min_seconds": 12}}
        self.assertEqual(rs.get(config_, "face.guide_seconds"), 0)
        self.assertEqual(rs.get(config_, "face.match_streak"), 7)
        self.assertEqual(rs.get(config_, "face.fail_min_seconds"), 12.0)

    def test_seconds_to_milliseconds(self):
        config_ = {
            "face": {"interval": 10},
            "network": {
                "heartbeat_interval": 20,
                "event_batch_interval": 5,
                "presence_interval": 45,
            },
        }
        self.assertEqual(rs.get(config_, "face.interval"), 10_000)
        self.assertEqual(rs.get(config_, "network.heartbeat_interval"), 20_000)
        self.assertEqual(rs.get(config_, "network.event_batch_interval"), 5_000)
        self.assertEqual(rs.get(config_, "network.presence_interval"), 45_000)

    def test_fractional_seconds_not_truncated(self):
        self.assertEqual(rs.get({"face": {"interval": 2.5}}, "face.interval"), 2_500)

    def test_percent_to_ratio(self):
        config_ = {"capture": {"record_pip_percent": 12, "camera_overlay_percent": 16}}
        self.assertAlmostEqual(rs.get(config_, "capture.record_pip_percent"), 0.12)
        self.assertAlmostEqual(rs.get(config_, "capture.camera_overlay_percent"), 0.16)

    def test_bool_values(self):
        for raw, expected in ((False, False), (True, True), ("false", False),
                              ("1", True), (0, False)):
            with self.subTest(raw=raw):
                self.assertIs(
                    rs.get({"capture": {"screen_record": raw}}, "capture.screen_record"),
                    expected,
                )

    def test_clamped_to_safe_range(self):
        self.assertEqual(
            rs.get({"network": {"heartbeat_interval": 0}}, "network.heartbeat_interval"),
            5_000,
        )
        self.assertEqual(rs.get({"face": {"guide_seconds": 999}}, "face.guide_seconds"), 30)
        self.assertEqual(rs.get({"face": {"interval": 0}}, "face.interval"), 1_000)
        self.assertAlmostEqual(
            rs.get({"capture": {"record_pip_percent": 90}}, "capture.record_pip_percent"),
            0.30,
        )

    def test_types(self):
        config_ = {"capture": {"record_width": "1280", "record_fps": "5"}}
        self.assertIsInstance(rs.get(config_, "capture.record_width"), int)
        self.assertIsInstance(rs.get(config_, "capture.record_fps"), float)
        self.assertEqual(rs.get(config_, "capture.record_width"), 1280)


if __name__ == "__main__":
    unittest.main()
