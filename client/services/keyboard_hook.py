"""
Xom `WH_KEYBOARD_LL` hook - MEXANIZM (nima yutilishini `lockdown.py` hal qiladi).

Nima uchun `keyboard` kutubxonasi EMAS. Uchta narsa uning ichida yopiq edi
va uchalasi ham kiosk'ning teshigi bo'lib chiqdi:

  * **Windows hook'ni jimgina olib tashlaydi.** Callback
    `LowLevelHooksTimeout` (~300 ms - 1 s) ichida qaytmasa, Windows 7+
    uni OGOHLANTIRISHSIZ o'chiradi. Python'da bu real: callback GIL'ni
    kutadi, GIL esa AI/kodlash thread'larida band bo'lishi mumkin.
    Kutubxonada hook'ni tekshirish ham, qayta o'rnatish ham yo'q edi -
    Alt+Tab imtihon oxirigacha ochiq qolardi va buni hech kim bilmasdi.
  * **Injekt qilingan Alt'li hodisalarni ko'rmasdi** (`fake_alt`:
    INJECTED|ALTDOWN - "ikkinchi Alt" xatosini aylanib o'tish). Ya'ni
    boshqa dastur yuborgan Alt+Tab to'g'ridan-to'g'ri o'tardi.
  * `dwExtraInfo` berilmasdi - o'z injeksiyamizni begonasidan ajratib
    bo'lmasdi.

TIRIKLIK TEKSHIRUVI (canary). Har `PROBE_INTERVAL_S` da belgili sun'iy
KEYUP (`_CANARY_VK`, tayinlanmagan kod) yuboriladi; hook uni TANIYDI va
YUTADI - oynaga hech narsa yetmaydi. O'lchangan: aylanish ~0.1 ms. Javob
kelmasa hook o'z thread'ida QAYTA o'rnatiladi: avval yangisi, keyin
eskisi olinadi - oraliqda qulfsiz lahza yo'q. Hook o'lik bo'lsa canary
oynaga yetadi, lekin u tayinlanmagan tugmaning KEYUP'i - ekranda hech
narsa bermaydi.

`SendInput` 0 qaytarsa (kiritish bloklangan: UIPI, boshqa ish stoli)
bu hook'ning aybi emas - tekshiruv o'tkazib yuboriladi.

BO'SH MASHINADA TEKSHIRILMAYDI (`IDLE_SKIP_S`). Injekt qilingan hodisa
Windows'ning bo'sh turish taymerini nolga qaytaradi: har 5 soniyadagi
canary ekran saqlagichni, monitor uyqusini va "harakatsizlikda
qulflash" siyosatini BUTUNLAY o'chirib qo'yardi - kechasi bo'sh turgan
xonada ham. Shuning uchun faqat HAQIQIY kiritishdan (`GetLastInputInfo`,
o'z canary'imiz hisobga olinmaydi) keyingi daqiqada tekshiriladi;
faollik qaytgan zahoti - keyingi tick'da darhol.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
from ctypes import wintypes
from typing import Callable, Optional

log = logging.getLogger(__name__)

_WH_KEYBOARD_LL = 13
_HC_ACTION = 0
_WM_KEYUP = 0x0101
_WM_SYSKEYUP = 0x0105
_WM_QUIT = 0x0012
_WM_APP_REINSTALL = 0x8000 + 1
_PM_NOREMOVE = 0x0000
_LLKHF_INJECTED = 0x10
_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002
_THREAD_PRIORITY_HIGHEST = 2

#: Tayinlanmagan virtual-key: haqiqiy klaviatura uni hech qachon bermaydi.
_CANARY_VK = 0xE8
#: `dwExtraInfo` belgilari. Ikkalasi ham handler'ga BORMAYDI:
#: canary - yutiladi, `_TAG_OWN` - o'zgarishsiz o'tkaziladi (masalan
#: yopishgan tugmani mantiqan qo'yib yuborish - uni "foydalanuvchi
#: qo'yib yubordi" deb o'qish holatni buzardi).
_TAG_CANARY = 0x4C4B5031
_TAG_OWN = 0x4C4B5030

#: `handler(vk, down, injected) -> bool`: True - o'tkazish, False - yutish.
KeyHandler = Callable[[int, bool, bool], bool]

if sys.platform == "win32":
    _LRESULT = ctypes.c_ssize_t
    _HOOKPROC = ctypes.WINFUNCTYPE(_LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

    class _KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", wintypes.DWORD),
            ("scanCode", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class _INPUTUNION(ctypes.Union):
        # MOUSEINPUT eng katta a'zo (x64 da 32 bayt) - `INPUT` o'lchami
        # to'g'ri bo'lmasa `SendInput` hech narsa yubormaydi.
        _fields_ = [("ki", _KEYBDINPUT), ("pad", ctypes.c_byte * 32)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    # `argtypes` SHART (CLAUDE.md "Tuzoqlar"): usiz 64-bit deskriptor
    # C `int` ga sig'maydi va chaqiruv `OverflowError` bilan yiqiladi.
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _user32.SetWindowsHookExW.argtypes = [ctypes.c_int, _HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
    _user32.SetWindowsHookExW.restype = ctypes.c_void_p
    _user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
    _user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    _user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    _user32.CallNextHookEx.restype = _LRESULT
    _user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    _user32.GetMessageW.restype = wintypes.BOOL
    _user32.PeekMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT,
    ]
    _user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.PostThreadMessageW.restype = wintypes.BOOL
    _user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
    _user32.SendInput.restype = wintypes.UINT
    _kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    _kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    _kernel32.GetCurrentThread.restype = wintypes.HANDLE
    _kernel32.SetThreadPriority.argtypes = [wintypes.HANDLE, ctypes.c_int]
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    _kernel32.GetTickCount.restype = wintypes.DWORD

    class _LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    _user32.GetLastInputInfo.argtypes = [ctypes.POINTER(_LASTINPUTINFO)]
    _user32.GetLastInputInfo.restype = wintypes.BOOL


def _tick_count() -> int:
    return int(_kernel32.GetTickCount())


def _last_input_tick() -> Optional[int]:
    """Oxirgi kiritish (sichqoncha ham) - `GetTickCount` shkalasida."""
    info = _LASTINPUTINFO(ctypes.sizeof(_LASTINPUTINFO), 0)
    if not _user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    return int(info.dwTime)


def _send_key_up(vk: int, tag: int) -> bool:
    """Belgili KEYUP yuboradi. False - kiritish bloklangan."""
    item = _INPUT(type=_INPUT_KEYBOARD)
    item.u.ki = _KEYBDINPUT(vk, 0, _KEYEVENTF_KEYUP, 0, tag)
    return _user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(_INPUT)) == 1


class KeyboardHook:
    """
    Bitta global klaviatura hook'i: o'z thread'i, xabar sikli, nazoratchi.

    `on_tick` - nazoratchi thread'idan har `TICK_S` da (`lockdown`
    yopishgan tugmani shu yerda tekshiradi). `on_health(state)` -
    `"lost"` / `"restored"`: hook o'lgani va tiklangani.
    """

    PROBE_INTERVAL_S = 5.0
    PROBE_TIMEOUT_S = 1.0
    TICK_S = 1.0
    IDLE_SKIP_S = 60.0

    def __init__(
        self,
        handler: KeyHandler,
        *,
        on_tick: Optional[Callable[[], None]] = None,
        on_health: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._handler = handler
        self._on_tick = on_tick
        self._on_health = on_health
        self._hhook = None
        self._thread_id = 0
        self._thread: Optional[threading.Thread] = None
        self._watchdog: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._installed = threading.Event()
        self._canary = threading.Event()
        self._stop = threading.Event()
        #: Qachondan beri tekshiruv o'tmayapti (None - joyida).
        self._lost_since: Optional[float] = None
        #: Nechta marta qayta o'rnatildi - diagnostika.
        self.reinstalls = 0
        #: Canary'dan keyingi `GetLastInputInfo` qiymati (o'z izimiz) va
        #: oxirgi HAQIQIY kiritish - ikkalasi `GetTickCount` shkalasida.
        self._probe_input_tick: Optional[int] = None
        self._last_real_input: Optional[int] = None
        # Callback obyektiga havola SHART: GC yig'ib olsa Windows
        # bo'shatilgan xotirani chaqirib jarayonni qulatadi.
        self._proc = _HOOKPROC(self._hook_proc) if sys.platform == "win32" else None

    # ------------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        """Hook va nazoratchini ishga tushiradi. Idempotent."""
        if sys.platform != "win32":
            return False
        if self.running:
            return True
        self._stop.clear()
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="keyboard-hook", daemon=True)
        self._thread.start()
        if not self._ready.wait(2.0) or not self._hhook:
            log.error("Klaviatura hook'i o'rnatilmadi (SetWindowsHookEx)")
            self.stop()
            return False
        self._watchdog = threading.Thread(target=self._watch, name="keyboard-hook-watch", daemon=True)
        self._watchdog.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread_id:
            _user32.PostThreadMessageW(self._thread_id, _WM_QUIT, 0, 0)
        for thread in (self._thread, self._watchdog):
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=2.0)
        self._thread = self._watchdog = None
        self._thread_id = 0

    def release_key(self, vk: int) -> bool:
        """
        Tugmani OS'da MANTIQAN qo'yib yuboradi (belgili KEYUP).

        Handler'ga bormaydi: bu foydalanuvchining harakati emas.
        """
        if sys.platform != "win32":
            return False
        return _send_key_up(vk, _TAG_OWN)

    def probe(self) -> Optional[bool]:
        """
        Hook tirikmi: canary yuboriladi va qaytishi kutiladi.

        None - tekshirib bo'lmadi (`SendInput` rad etdi), hook'ning aybi emas.
        """
        self._canary.clear()
        if not _send_key_up(_CANARY_VK, _TAG_CANARY):
            return None
        self._probe_input_tick = _last_input_tick()
        return self._canary.wait(self.PROBE_TIMEOUT_S)

    def _user_active(self) -> bool:
        """Oxirgi `IDLE_SKIP_S` ichida HAQIQIY kiritish bo'lganmi."""
        last = _last_input_tick()
        if last is None:
            return True
        if last != self._probe_input_tick or self._last_real_input is None:
            # Canary'dan keyin boshqa kiritish bo'lgan (yoki birinchi o'lchov).
            self._last_real_input = last
        idle_ms = (_tick_count() - self._last_real_input) & 0xFFFFFFFF
        return idle_ms < self.IDLE_SKIP_S * 1000

    # ------------------------------------------------------------------
    def _hook_proc(self, n_code, w_param, l_param):
        try:
            if n_code == _HC_ACTION:
                info = ctypes.cast(l_param, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
                tag = info.dwExtraInfo
                if tag == _TAG_CANARY:
                    self._canary.set()
                    return 1
                if tag != _TAG_OWN:
                    down = w_param not in (_WM_KEYUP, _WM_SYSKEYUP)
                    injected = bool(info.flags & _LLKHF_INJECTED)
                    if not self._handler(int(info.vkCode), down, injected):
                        return 1
        except Exception:
            # Hook ichidagi istisno tugmani O'TKAZADI: yiqilgan tekshiruv
            # butun klaviaturani o'ldirmasligi kerak.
            log.debug("Klaviatura hook'i xatosi", exc_info=True)
        return _user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _install(self) -> bool:
        """Yangi hook - keyin eskisi olinadi (oraliqda qulfsiz lahza yo'q)."""
        handle = _user32.SetWindowsHookExW(
            _WH_KEYBOARD_LL, self._proc, _kernel32.GetModuleHandleW(None), 0
        )
        if not handle:
            log.error("SetWindowsHookEx xatosi: %s", ctypes.get_last_error())
            return False
        old, self._hhook = self._hhook, handle
        if old:
            _user32.UnhookWindowsHookEx(old)
        return True

    def _run(self) -> None:
        # LL hook'ni O'RNATGAN thread xabar siklini aylantirishi shart -
        # Windows callback'ni shu thread orqali chaqiradi.
        self._thread_id = _kernel32.GetCurrentThreadId()
        # GIL bo'shashi bilan birinchi bo'lib navbat olsin (timeout xavfi).
        _kernel32.SetThreadPriority(_kernel32.GetCurrentThread(), _THREAD_PRIORITY_HIGHEST)
        msg = wintypes.MSG()
        # Navbat `PostThreadMessage` dan OLDIN yaratilishi kerak.
        _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, _PM_NOREMOVE)
        self._install()
        self._ready.set()
        try:
            while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == _WM_APP_REINSTALL:
                    self._install()
                    self._installed.set()
        finally:
            if self._hhook:
                _user32.UnhookWindowsHookEx(self._hhook)
            self._hhook = None

    def _reinstall(self) -> None:
        self._installed.clear()
        _user32.PostThreadMessageW(self._thread_id, _WM_APP_REINSTALL, 0, 0)
        self._installed.wait(1.0)
        self.reinstalls += 1

    def _watch(self) -> None:
        next_probe = time.monotonic() + self.PROBE_INTERVAL_S
        while not self._stop.wait(self.TICK_S):
            if self._on_tick is not None:
                try:
                    self._on_tick()
                except Exception:
                    log.debug("Hook nazoratchisi (tick) xatosi", exc_info=True)
            if not self._user_active():
                # Bo'sh mashina: tekshiruv to'xtaydi (bo'sh turish
                # taymeri buzilmasin), faollik qaytishi bilan - darhol.
                next_probe = 0.0
                continue
            if time.monotonic() < next_probe:
                continue
            next_probe = time.monotonic() + self.PROBE_INTERVAL_S
            self._check_health()

    def _check_health(self) -> None:
        alive = self.probe()
        if alive is None:
            return
        if not alive:
            self._reinstall()
            alive = bool(self.probe())
            if alive:
                log.error(
                    "Klaviatura hook'i javob bermadi (Windows olib tashlagan) - "
                    "qayta o'rnatildi (%s-marta)", self.reinstalls,
                )
                self._emit("restored")
                self._lost_since = None
                return
            if self._lost_since is None:
                self._lost_since = time.monotonic()
                log.error("Klaviatura hook'i ishlamayapti va qayta o'rnatilmadi")
                self._emit("lost")
            return
        if self._lost_since is not None:
            log.warning(
                "Klaviatura hook'i %.0f s dan keyin tiklandi",
                time.monotonic() - self._lost_since,
            )
            self._lost_since = None
            self._emit("restored")

    def _emit(self, state: str) -> None:
        if self._on_health is None:
            return
        try:
            self._on_health(state)
        except Exception:
            log.debug("Hook holati observer'i xatosi", exc_info=True)
