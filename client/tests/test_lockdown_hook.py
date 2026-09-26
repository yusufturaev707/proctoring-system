"""
Klaviatura qulfi: siyosat (`lockdown`) va xom hook mexanizmi (`keyboard_hook`).

Qo'riqlanadigan shartnoma (`services/lockdown.py` docstring'i):

  1. modifikatorlar (Alt, Ctrl, Shift) hech qachon ushlanmaydi va qayta
     yuborilmaydi - ular OS'ga o'z tartibida yetadi (Alt+Shift til
     almashtirishi ishlaydi);
  2. bloklangan kombinatsiyaning ASOSIY tugmasi yutiladi, ortiqcha
     modifikator bilan ham (Alt+Shift+Space, Ctrl+Alt+Space = AltGr);
  3. yutilgan tugma o'z UP'igacha yutiladi - OS'ga DOWN'siz UP yetmaydi;
  4. modifikator holati OS'dan o'qiladi: hook ko'rmagan UP (Ctrl+Alt+Del,
     Win+L, UAC) bloklashni buzmaydi va oddiy tugmani yutmaydi;
  5. INJEKT qilingan hodisa ham tekshiriladi (masofaviy boshqaruv);
  6. yopishgan modifikator (apparat / yo'qolgan UP) mantiqan qo'yib
     yuboriladi, auto-repeat'lari jismoniy UP gacha yutiladi;
  7. Windows olib tashlagan hook aniqlanadi va qayta o'rnatiladi;
  8. kiosk oynasida Windows System Menu yo'q va ramka saqlanadi;
  9. hook ALOHIDA jarayonda: bloklaydi, o'lsa qayta ko'tariladi, client
     o'lsa o'zi ham yopiladi (egasiz qulf qolmaydi); ishga tushmasa -
     client ichidagi zaxira hook.

Ilgari (`keyboard.add_hotkey(suppress=True)`) 1, 2, 4, 5 va 7 buzilgan
edi: Alt+Shift OS'ga `shift↓ shift↑ alt↓ alt↑` bo'lib yetardi,
`alt+shift+space` Space'ni Alt bosilgan oynaga o'tkazardi, eskirgan
jadvaldan keyin aniq Alt+Space ham o'tib, oyna tepasida System Menu
ochilardi (o'lchangan: Qt oynasi `WindowSystemMenuHint` bilan aynan
Alt+Space'da menyu ochadi).
"""

import ctypes
import os
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from services import keyboard_hook as kh  # noqa: E402
from services import keyboard_hook_process as khp  # noqa: E402
from services import lockdown as ld  # noqa: E402

# Nom -> (hodisa VK'si, GetAsyncKeyState ko'radigan VK'lar).
KEYS = {
    "alt": (0xA4, (0xA4, 0x12)),
    "ralt": (0xA5, (0xA5, 0x12)),
    "shift": (0xA0, (0xA0, 0x10)),
    "ctrl": (0xA2, (0xA2, 0x11)),
    "win": (0x5B, (0x5B,)),
    "space": (0x20, ()),
    "tab": (0x09, ()),
    "f4": (0x73, ()),
    "i": (0x49, ()),
    "a": (0x41, ()),
    "del": (0x2E, ()),
    "prtsc": (0x2C, ()),
    "num*": (0x6A, ()),
}
DEFAULT = [k.strip() for k in (
    "alt+tab,alt+shift+tab,alt+esc,win,ctrl+esc,alt+f4,alt+space,"
    "print screen,ctrl+shift+esc,f12,ctrl+shift+i"
).split(",")]


class LockdownPolicyTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.os_down = set()      # OS'dagi mantiqiy holat (VK)
        self.delivered = []       # OS'ga yetganlar
        self.notified = []
        self.issues = []
        self.released = []
        self.policy = ld.KeyPolicy(
            key_is_down=lambda vk: vk in self.os_down,
            clock=lambda: self.now,
            on_blocked=self.notified.append,
            on_issue=lambda reason, key: self.issues.append((reason, key)),
        )
        self.policy.release_key = self._release
        self.assertEqual(len(self.policy.set_codes(DEFAULT)), len(DEFAULT))

    def _release(self, vk):
        self.released.append(vk)
        for event_vk, vks in KEYS.values():
            if event_vk == vk:
                self.os_down.difference_update(vks)

    def press(self, *steps, injected=False):
        """`d:alt`, `u:alt`; `lost:ctrl` - UP OS'ga yetdi, hook'ga YO'Q."""
        for step in steps:
            kind, name = step.split(":")
            vk, vks = KEYS[name]
            if kind == "lost":
                self.os_down.difference_update(vks)
                continue
            down = kind == "d"
            if self.policy.on_key(vk, down, injected):
                self.delivered.append(name + ("↓" if down else "↑"))
                (self.os_down.update if down else self.os_down.difference_update)(vks)

    # 1. Modifikatorlar -------------------------------------------------
    def test_alt_shift_language_switch_reaches_os_together(self):
        self.press("d:alt", "d:shift", "u:shift", "u:alt")
        self.assertEqual(self.delivered, ["alt↓", "shift↓", "shift↑", "alt↑"])

    def test_shift_letter_untouched(self):
        self.press("d:shift", "d:a", "u:a", "u:shift")
        self.assertEqual(self.delivered, ["shift↓", "a↓", "a↑", "shift↑"])

    # 2. Bloklash ------------------------------------------------------
    def test_alt_space_blocked(self):
        self.press("d:alt", "d:space", "u:space", "u:alt")
        self.assertEqual(self.delivered, ["alt↓", "alt↑"])
        self.assertEqual(self.notified, ["alt+space"])

    def test_extra_modifiers_do_not_unblock(self):
        for extra in ("shift", "ctrl", "ralt"):  # Alt+Shift+Space, AltGr+Space
            self.delivered.clear()
            self.press("d:alt", "d:" + extra, "d:space", "u:space", "u:" + extra, "u:alt")
            self.assertNotIn("space↓", self.delivered, extra)

    def test_alt_tab_blocked_even_when_alt_released_first(self):
        self.press("d:alt", "d:tab", "u:alt", "u:tab")
        self.assertEqual(self.delivered, ["alt↓", "alt↑"])

    def test_swallowed_key_repeat_stays_swallowed_and_counted_once(self):
        self.press("d:alt", "d:tab", "d:tab", "d:tab", "u:alt", "d:tab", "u:tab")
        self.assertEqual(self.delivered, ["alt↓", "alt↑"])
        self.assertEqual(self.notified, ["alt+tab"])

    def test_most_specific_combo_reported(self):
        self.press("d:alt", "d:shift", "d:tab", "u:tab", "u:shift", "u:alt")
        self.assertEqual(self.notified, ["alt+shift+tab"])

    def test_ctrl_shift_i_alt_f4_and_win_blocked(self):
        self.press("d:ctrl", "d:shift", "d:i", "u:i", "u:shift", "u:ctrl",
                   "d:alt", "d:f4", "u:f4", "u:alt", "d:win", "u:win")
        for key in ("i↓", "f4↓", "win↓", "win↑"):
            self.assertNotIn(key, self.delivered)

    def test_print_screen_blocked_but_numpad_star_passes(self):
        self.press("d:prtsc", "u:prtsc", "d:num*", "u:num*")
        self.assertEqual(self.delivered, ["num*↓", "num*↑"])

    # 3-5. Oddiy tugmalar, eskirgan holat, injeksiya -------------------
    def test_plain_space_passes(self):
        self.press("d:space", "u:space", "d:alt", "d:tab", "u:tab", "u:alt", "d:space", "u:space")
        self.assertEqual(self.delivered, ["space↓", "space↑", "alt↓", "alt↑", "space↓", "space↑"])

    def test_lost_key_up_does_not_break_blocking(self):
        # Ctrl+Alt+Del: xavfsiz ish stoli UP'larni hook'dan yashiradi.
        self.press("d:ctrl", "d:alt", "d:del", "lost:del", "lost:alt", "lost:ctrl")
        self.delivered.clear()
        self.press("d:alt", "d:space", "u:space", "u:alt")
        self.assertEqual(self.delivered, ["alt↓", "alt↑"])
        self.press("d:space", "u:space")
        self.assertEqual(self.delivered[-2:], ["space↓", "space↑"])

    def test_injected_combo_is_blocked_too(self):
        self.press("d:alt", "d:tab", "u:tab", "u:alt", injected=True)
        self.assertEqual(self.delivered, ["alt↓", "alt↑"])

    def test_codes_swap(self):
        self.policy.set_codes(["alt+tab"])
        self.press("d:alt", "d:space", "u:space", "u:alt")
        self.assertIn("space↓", self.delivered)

    def test_reset_passes_everything(self):
        self.policy.reset()
        self.press("d:alt", "d:space", "u:space", "u:alt")
        self.assertEqual(self.delivered, ["alt↓", "space↓", "space↑", "alt↑"])

    # 6. Yopishgan modifikator -----------------------------------------
    def test_stuck_alt_released_and_typing_works(self):
        self.press("d:alt")
        self.now += 21
        self.policy.tick()
        self.assertEqual(self.released, [0xA4])
        self.assertEqual(self.issues, [("stuck_key", "alt")])
        self.assertNotIn(0x12, self.os_down)
        # Apparat hali ham auto-repeat beradi - yutiladi, Alt qaytmaydi.
        self.press("d:alt", "d:space", "u:space")
        self.assertEqual(self.delivered[-2:], ["space↓", "space↑"])
        # Jismoniy UP - yutiladi (OS'da allaqachon qo'yilgan), holat tozalanadi.
        self.press("u:alt")
        self.assertNotIn("alt↑", self.delivered)
        self.press("d:alt", "u:alt")
        self.assertEqual(self.delivered[-2:], ["alt↓", "alt↑"])

    def test_lost_up_is_not_treated_as_stuck(self):
        self.press("d:alt", "lost:alt")
        self.now += 60
        self.policy.tick()
        self.assertEqual(self.released, [])
        self.assertEqual(self.issues, [])
        self.press("d:alt", "u:alt")
        self.assertEqual(self.delivered[-2:], ["alt↓", "alt↑"])

    def test_shift_has_longer_threshold(self):
        self.press("d:shift")
        self.now += 30
        self.policy.tick()
        self.assertEqual(self.released, [])
        self.now += 31
        self.policy.tick()
        self.assertEqual(self.released, [0xA0])



class _FakeEngine:
    instances = []

    def __init__(self, *, on_blocked=None, on_issue=None, ok=True):
        self.ok = ok
        self.running = False
        self.codes = []
        _FakeEngine.instances.append(self)

    def start(self, codes):
        self.codes = list(codes)
        self.running = self.ok
        return self.ok

    def update(self, codes):
        self.codes = list(codes)

    def stop(self):
        self.running = False


class _FakeHook:
    def __init__(self, handler, *, on_tick=None, on_health=None):
        self.on_health = on_health
        self.running = False

    def start(self):
        self.running = True
        return True

    def stop(self):
        self.running = False

    def release_key(self, vk):
        return True


class LockdownEngineTests(unittest.TestCase):
    def setUp(self):
        _FakeEngine.instances.clear()
        for patch in (
            mock.patch.object(ld._Lockdown, "_disable_accessibility", lambda self: None),
            mock.patch.object(ld._Lockdown, "_restore_accessibility", lambda self: None),
            mock.patch.object(ld._Lockdown, "_register_cleanup", lambda self: None),
            mock.patch.object(ld, "_KEYBOARD_AVAILABLE", True),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def test_policy_swap_keeps_single_engine(self):
        lock = ld._Lockdown(process_factory=_FakeEngine, hook_factory=_FakeHook)
        lock.apply(DEFAULT)
        lock.apply(["alt+tab", "nosuch+key"])
        self.assertEqual(len(_FakeEngine.instances), 1)
        self.assertEqual(_FakeEngine.instances[0].codes, ["alt+tab"])
        self.assertEqual(lock.blocked_keys, ["alt+tab"])
        lock.release()
        self.assertFalse(_FakeEngine.instances[0].running)

    def test_falls_back_to_in_process_hook(self):
        issues = []
        lock = ld._Lockdown(
            process_factory=lambda **kw: _FakeEngine(ok=False, **kw), hook_factory=_FakeHook,
        )
        lock.set_issue_observer(lambda reason, key: issues.append(reason))
        self.assertEqual(lock.apply(["alt+tab"]), ["alt+tab"])
        self.assertIsInstance(lock._engine, ld._LocalEngine)
        lock._engine._hook.on_health("restored")
        self.assertEqual(issues, ["hook_restored"])
        lock.release()

    def test_empty_list_stops_engine(self):
        lock = ld._Lockdown(process_factory=_FakeEngine, hook_factory=_FakeHook)
        lock.apply(["alt+tab"])
        self.assertEqual(lock.apply([]), [])
        self.assertIsNone(lock._engine)


class ParseComboTests(unittest.TestCase):
    def test_main_key_and_modifiers(self):
        combo = ld._parse_combo("alt+shift+tab")
        self.assertEqual(combo.vks, {0x09})
        self.assertEqual(len(combo.required), 2)

    def test_modifier_only_code_blocks_the_key_itself(self):
        combo = ld._parse_combo("win")
        self.assertEqual(combo.vks, {0x5B, 0x5C})
        self.assertEqual(combo.required, ())

    def test_names(self):
        self.assertEqual(ld._key_vks("print screen"), (0x2C,))
        self.assertEqual(ld._key_vks("f12"), (0x7B,))
        self.assertEqual(ld._key_vks("i"), (0x49,))
        self.assertEqual(ld._key_vks("num 5"), (0x65,))
        self.assertEqual(ld._parse_combo(ld._normalize("PrintScreen")).vks, {0x2C})

    def test_invalid_rejected(self):
        for code in ("tab+space", "ctrl+nosuchkey", "alt+alt"):
            with self.assertRaises(ValueError, msg=code):
                ld._parse_combo(code)


@unittest.skipUnless(sys.platform == "win32", "Windows kerak")
class RealHookTests(unittest.TestCase):
    """
    Haqiqiy `WH_KEYBOARD_LL`. Faqat TAYINLANMAGAN VK'lar injekt qilinadi
    va hook ularni yutadi - ochiq oynaga hech narsa yetmaydi. Kiritish
    bloklangan bo'lsa (qulflangan ish stoli) test o'tkazib yuboriladi.
    """

    PROBE_VK = 0xE9

    def setUp(self):
        self.seen = []
        self.health = []

        def handler(vk, down, injected):
            if vk == self.PROBE_VK:
                self.seen.append((down, injected))
                return False
            return True

        self.hook = kh.KeyboardHook(handler, on_health=self.health.append)
        self.assertTrue(self.hook.start())
        self.addCleanup(self.hook.stop)
        if self.hook.probe() is None:
            self.skipTest("SendInput rad etildi (ish stoli qulflangan?)")

    def test_probe_and_injected_key_path(self):
        self.assertTrue(self.hook.probe())
        done = threading.Event()
        for flags in (0, kh._KEYEVENTF_KEYUP):
            item = kh._INPUT(type=kh._INPUT_KEYBOARD)
            item.u.ki = kh._KEYBDINPUT(self.PROBE_VK, 0, flags, 0, 0)
            kh._user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(kh._INPUT))
        done.wait(0.3)
        self.assertEqual(self.seen, [(True, True), (False, True)])

    def test_hook_removed_by_windows_is_restored(self):
        # Windows `LowLevelHooksTimeout` da qiladigan ish: hook jimgina o'chadi.
        ctypes.WinDLL("user32").UnhookWindowsHookEx(ctypes.c_void_p(self.hook._hhook))
        self.assertFalse(self.hook.probe())
        self.hook._check_health()
        self.assertEqual(self.health, ["restored"])
        self.assertEqual(self.hook.reinstalls, 1)
        self.assertTrue(self.hook.probe())


class IdleProbeTests(unittest.TestCase):
    """Bo'sh mashinada canary YUBORILMAYDI - bo'sh turish taymeri buzilmasin."""

    def setUp(self):
        self.hook = kh.KeyboardHook(lambda *a: True)
        self.now = 1_000_000
        self.last = self.now
        patches = [
            mock.patch.object(kh, "_tick_count", lambda: self.now),
            mock.patch.object(kh, "_last_input_tick", lambda: self.last),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_own_canary_does_not_count_as_activity(self):
        self.assertTrue(self.hook._user_active())
        # Faqat canary'lar: har biri "oxirgi kiritish" ni yangilaydi.
        for _ in range(20):
            self.now += 5_000
            self.last = self.now
            self.hook._probe_input_tick = self.last
            active = self.hook._user_active()
        self.assertFalse(active)

    def test_real_input_resumes_probing_and_tick_wraps(self):
        self.now = 0xFFFFFFF0
        self.last = self.now
        self.hook._user_active()
        self.now = (self.now + 30_000) & 0xFFFFFFFF   # GetTickCount aylanib o'tdi
        self.assertTrue(self.hook._user_active())
        self.now += 61_000
        self.assertFalse(self.hook._user_active())
        self.last = self.now                           # talabgor tugma bosdi
        self.assertTrue(self.hook._user_active())


def _send_f24() -> bool:
    ok = True
    for flags in (0, kh._KEYEVENTF_KEYUP):
        item = kh._INPUT(type=kh._INPUT_KEYBOARD)
        item.u.ki = kh._KEYBDINPUT(0x87, 0, flags, 0, 0)  # F24 - ish joyi klaviaturasida yo'q
        ok = kh._user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(kh._INPUT)) == 1 and ok
    return ok


def _wait(predicate, timeout=5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


@unittest.skipUnless(sys.platform == "win32", "Windows kerak")
class HookProcessTests(unittest.TestCase):
    """Haqiqiy qulf jarayoni (`main.py --keyboard-hook`)."""

    def setUp(self):
        self.blocked = []
        self.issues = []
        self.proc = khp.HookProcess(
            on_blocked=self.blocked.append,
            on_issue=lambda reason, key: self.issues.append(reason),
        )
        self.proc.RESTART_BACKOFF_S = (0.2,)
        self.assertTrue(self.proc.start(["f24"]))
        self.addCleanup(self.proc.stop)

    def test_blocks_in_child_and_restarts_after_crash(self):
        if not _send_f24():
            self.skipTest("SendInput rad etildi (ish stoli qulflangan?)")
        self.assertTrue(_wait(lambda: self.blocked == ["f24"]), self.blocked)
        first_pid = self.proc.pid
        subprocess.run(["taskkill", "/F", "/PID", str(first_pid)], capture_output=True)
        self.assertTrue(_wait(lambda: self.issues == ["hook_lost", "hook_restored"]), self.issues)
        self.assertNotEqual(self.proc.pid, first_pid)
        _send_f24()
        self.assertTrue(_wait(lambda: self.blocked == ["f24", "f24"]), self.blocked)

    def test_stop_ends_child(self):
        child = self.proc._proc
        self.proc.stop()
        self.assertEqual(child.wait(timeout=3), 0)


@unittest.skipUnless(sys.platform == "win32", "Windows kerak")
class OrphanChildTests(unittest.TestCase):
    def test_child_exits_when_client_is_killed(self):
        import psutil

        code = (
            "import sys, time; sys.path.insert(0, r'{root}');"
            "from services.keyboard_hook_process import HookProcess;"
            "p = HookProcess(); assert p.start(['f24']); print(p.pid, flush=True); time.sleep(60)"
        ).format(root=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        parent = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        try:
            child_pid = int(parent.stdout.readline())
            self.assertTrue(psutil.pid_exists(child_pid))
        finally:
            parent.kill()  # TerminateProcess - hech qanday tozalash ishlamaydi
            parent.wait()
            parent.stdout.close()
        self.assertTrue(_wait(lambda: not psutil.pid_exists(child_pid)), "qulf jarayoni egasiz qoldi")


class SystemMenuGuardTests(unittest.TestCase):
    def test_messages(self):
        self.assertTrue(ld.is_system_menu_message(0x0104, 0x20))      # WM_SYSKEYDOWN Space
        self.assertTrue(ld.is_system_menu_message(0x0106, 0x20))      # WM_SYSCHAR ' '
        self.assertTrue(ld.is_system_menu_message(0x0112, 0xF100))    # SC_KEYMENU
        self.assertTrue(ld.is_system_menu_message(0x0112, 0xF093))    # SC_MOUSEMENU | pastki bitlar
        self.assertFalse(ld.is_system_menu_message(0x0112, 0xF060))   # SC_CLOSE - tegilmaydi
        self.assertFalse(ld.is_system_menu_message(0x0100, 0x20))     # oddiy Space
        self.assertFalse(ld.is_system_menu_message(0x0104, 0x09))     # Alt+Tab - hook'ning ishi

    def test_kiosk_flags_keep_frameless_and_drop_system_menu(self):
        try:
            from PyQt6.QtCore import Qt
            from PyQt6.QtWidgets import QApplication, QMainWindow
        except Exception:  # pragma: no cover
            self.skipTest("PyQt6 yo'q")
        app = QApplication.instance() or QApplication([])  # noqa: F841
        window = QMainWindow()
        window.setWindowFlags(ld.kiosk_window_flags(
            window.windowFlags()
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        ))
        flags = window.windowFlags()
        # Qt `adjustFlags` Min/Max bayrog'i qolsa ramkani QAYTARARDI.
        self.assertTrue(flags & Qt.WindowType.FramelessWindowHint)
        self.assertTrue(flags & Qt.WindowType.WindowStaysOnTopHint)
        self.assertFalse(flags & Qt.WindowType.WindowSystemMenuHint)


if __name__ == "__main__":
    unittest.main()
