"""
Duplicate (klon) rejimidagi ikkinchi monitor (`services/display_control.py`).

Noutbukda amalda topilgan xato: duplicate rejimida ikkala monitor BITTA
displey manbasidan tasvir oladi - `EnumDisplayDevices` va Qt bitta ekran
ko'radi, ya'ni ikkinchi monitor na o'chirilardi, na `multi_monitor`
hodisasi chiqardi (extend rejimida ishlardi).

Testlar Windows API'siz: tanlov va qayta indekslash sof funksiyalar,
kuzatuvchi esa `active_monitor_count` / `disable_clones` almashtirilib
sinaladi.
"""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from services import display_control as dc  # noqa: E402

_INTERNAL = 0x80000000
_HDMI = 5
_DP = 10


def _target(source: int, target: int, output: int = _HDMI, adapter=(1, 0)) -> dc.DisplayTarget:
    return dc.DisplayTarget(adapter=adapter, source_id=source, target_id=target, output_technology=output)


class PlanTests(unittest.TestCase):
    def test_laptop_clone_keeps_internal_panel(self):
        # Ichki panel ro'yxatda ikkinchi bo'lsa ham u qoladi.
        targets = [_target(0, 10, _HDMI), _target(0, 11, _INTERNAL)]
        self.assertEqual(dc.plan_clone_reduction(targets), [0])

    def test_embedded_displayport_is_internal(self):
        targets = [_target(0, 10, _HDMI), _target(0, 11, 11)]
        self.assertEqual(dc.plan_clone_reduction(targets), [0])

    def test_desktop_clone_keeps_first(self):
        targets = [_target(0, 10, _DP), _target(0, 11, _HDMI)]
        self.assertEqual(dc.plan_clone_reduction(targets), [1])

    def test_extend_is_not_touched(self):
        # Turli manbalar - extend; uning o'z yo'li bor (`disable_secondary`).
        targets = [_target(0, 10), _target(1, 11)]
        self.assertEqual(dc.plan_clone_reduction(targets), [])

    def test_same_source_id_on_other_adapter_is_not_clone(self):
        targets = [_target(0, 10, adapter=(1, 0)), _target(0, 11, adapter=(2, 0))]
        self.assertEqual(dc.plan_clone_reduction(targets), [])

    def test_clone_pair_next_to_extended_screen(self):
        targets = [_target(0, 10, _INTERNAL), _target(1, 12), _target(0, 11, _HDMI)]
        self.assertEqual(dc.plan_clone_reduction(targets), [2])

    def test_single_monitor(self):
        self.assertEqual(dc.plan_clone_reduction([_target(0, 10)]), [])
        self.assertEqual(dc.plan_clone_reduction([]), [])


class CompactTests(unittest.TestCase):
    def _config(self):
        # Klon: bitta manba rejimi (0), ikki monitor rejimi (1, 2).
        modes = (dc.DISPLAYCONFIG_MODE_INFO * 3)()
        for index, (kind, ident) in enumerate([(1, 100), (2, 10), (2, 11)]):
            modes[index].infoType = kind
            modes[index].id = ident
        paths = (dc.DISPLAYCONFIG_PATH_INFO * 2)()
        for index, (target, target_mode) in enumerate([(10, 1), (11, 2)]):
            paths[index].sourceInfo.id = 0
            paths[index].sourceInfo.modeInfoIdx = 0
            paths[index].targetInfo.id = target
            paths[index].targetInfo.modeInfoIdx = target_mode
            paths[index].flags = 1
        return paths, modes

    def test_keeps_only_used_modes_and_reindexes(self):
        paths, modes = self._config()
        new_paths, new_modes, count = dc.compact_config(paths, modes, [1])
        self.assertEqual(len(new_paths), 1)
        self.assertEqual(count, 2)
        path = new_paths[0]
        self.assertEqual(path.targetInfo.id, 11)
        self.assertEqual(path.flags, 1)
        self.assertEqual(new_modes[path.sourceInfo.modeInfoIdx].id, 100)
        self.assertEqual(new_modes[path.targetInfo.modeInfoIdx].id, 11)

    def test_invalid_index_stays_invalid(self):
        paths, modes = self._config()
        paths[0].targetInfo.modeInfoIdx = 0xFFFFFFFF
        new_paths, _modes, count = dc.compact_config(paths, modes, [0])
        self.assertEqual(new_paths[0].targetInfo.modeInfoIdx, 0xFFFFFFFF)
        self.assertEqual(count, 1)

    def test_struct_sizes_match_windows_sdk(self):
        import ctypes

        self.assertEqual(ctypes.sizeof(dc.DISPLAYCONFIG_PATH_INFO), 72)
        self.assertEqual(ctypes.sizeof(dc.DISPLAYCONFIG_MODE_INFO), 64)
        self.assertEqual(ctypes.sizeof(dc._TARGET_DEVICE_NAME), 420)


class WatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from services.device_watch import DeviceWatcher

        self.watcher = DeviceWatcher()
        self.watcher._active = True
        self.events = []
        self.watcher.detected.connect(lambda kind, sev, payload: self.events.append(payload))

    def _check(self, physical, *, disabled=True, enabled=True):
        report = dc.DisplayReport()
        if disabled:
            report.disabled.append(dc.Display(name="target #11", label="HP (duplicate)"))
        with mock.patch.object(dc, "active_monitor_count", return_value=physical), \
                mock.patch.object(dc, "disable_clones", return_value=report) as disable, \
                mock.patch("config.DISABLE_EXTRA_MONITORS", enabled), \
                mock.patch.object(self.app, "screens", return_value=[self.app.primaryScreen()]):
            self.watcher._check_monitors("changed")
        return disable

    def test_duplicate_detected_and_disabled(self):
        disable = self._check(2)
        disable.assert_called_once()
        self.assertEqual(len(self.events), 1)
        payload = self.events[0]
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["mode"], "duplicate")
        self.assertTrue(payload["disabled"])

    def test_not_repeated_while_count_unchanged(self):
        self._check(2)
        self._check(2)
        self.assertEqual(len(self.events), 1)

    def test_reported_again_after_returning(self):
        self._check(2)
        self._check(1)
        self._check(2)
        self.assertEqual(len(self.events), 2)

    def test_disabling_switched_off_still_reports(self):
        disable = self._check(2, enabled=False)
        disable.assert_not_called()
        self.assertFalse(self.events[0]["disabled"])

    def test_single_monitor_is_silent(self):
        disable = self._check(1)
        disable.assert_not_called()
        self.assertEqual(self.events, [])

    def test_api_failure_falls_back_to_qt(self):
        disable = self._check(None)
        disable.assert_not_called()
        self.assertEqual(self.events, [])


if __name__ == "__main__":
    unittest.main()
