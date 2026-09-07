"""
Kiosk rejimi: tezkor tugmalarni bloklash va tizim yorliqlarini o'chirish.

OS darajasidagi barcha aralashuv SHU FAYLDA. Sabab oddiy: bu modul
foydalanuvchi mashinasining GLOBAL holatini o'zgartiradi (klaviatura
hook'i, registry kalitlari) va "kim nimani o'zgartirdi, kim qaytardi"
degan savolga bitta joydan javob berilishi kerak.

Ikki qatlam, ikkalasi ham alohida ishlaydi:

  1. `keyboard` hook'lari - Alt+Tab, Win, PrintScreen kabi
     kombinatsiyalarni bosilishidan OLDIN yutadi;
  2. Windows Accessibility yorliqlari - Shift x5 (Sticky Keys),
     Shift 8s (Filter Keys), NumLock 5s (Toggle Keys). Bularni
     `keyboard` ushlay olmaydi: ular OS ichida, hook zanjiridan
     oldinroq ishlaydi va ekranga MODAL oyna chiqaradi - to'liq
     ekran rejimi shu zahoti buziladi.

QAT'IY QOIDA: registry o'zgarishi dastur bilan birga o'lmaydi. Hook
jarayon tugashi bilan OS tomonidan olib tashlanadi, registry esa
QOLADI - talaba mashinasida Sticky Keys butunlay o'chgan holda. Shu
sababli tiklash uch joyga qo'yilgan: oddiy chiqish, `atexit` va
tutilmagan istisno. Referens loyihada faqat birinchisi bor edi.
"""

from __future__ import annotations

import atexit
import logging
import sys
import threading
from typing import Optional

log = logging.getLogger(__name__)

try:
    import keyboard  # type: ignore

    _KEYBOARD_AVAILABLE = True
except Exception:  # ImportError va Linux'dagi ruxsat xatolari
    keyboard = None  # type: ignore
    _KEYBOARD_AVAILABLE = False


#: Panelda yozilgan kod -> `keyboard` kutubxonasi tushunadigan nom.
#:
#: Kerak, chunki panelga kodni ODAM kiritadi va u tabiiy ravishda
#: "printscreen" deb yozadi; kutubxona esa faqat "print screen" ni
#: biladi va aks holda JIMGINA bloklamay qo'yadi. Nomlash farqi
#: tufayli ekran nusxasi ochiq qolishi mumkin emas.
_KEY_ALIASES = {
    "printscreen": "print screen",
    "prtsc": "print screen",
    "prt sc": "print screen",
    "prtscr": "print screen",
    "prnt scrn": "print screen",
    "escape": "esc",
    "windows": "win",
    "meta": "win",
    "super": "win",
    "cmd": "win",
    "del": "delete",
    "ins": "insert",
    "pgup": "page up",
    "pgdn": "page down",
    "return": "enter",
    "capslock": "caps lock",
    "numlock": "num lock",
    "scrolllock": "scroll lock",
}


#: HECH QACHON bloklanmaydigan kombinatsiya.
#:
#: Ctrl+Q - dasturdan chiqishning yagona yo'li (login sahifasidan
#: boshlab). Uni panelga "bloklanadigan tugmalar" ro'yxatiga qo'shish
#: mumkin va shunda mashina o'zini qulflab qo'yardi: chiqish dialogini
#: ochib bo'lmaydi, Alt+F4 allaqachon bloklangan, `closeEvent` esa
#: parolsiz yopilishni rad etadi. Bu xatoni administrator o'zi ham
#: sezmasligi mumkin, shuning uchun qoida KODDA.
_NEVER_BLOCKED = frozenset({"ctrl+q"})


def _normalize(code: str) -> str:
    """`Ctrl + Shift+I` -> `ctrl+shift+i`, alias'lar bilan."""
    parts = [part.strip().lower() for part in str(code or "").split("+")]
    parts = [_KEY_ALIASES.get(part, part) for part in parts if part]
    return "+".join(parts)


class _Lockdown:
    """
    Qulflash holati - yagona nusxa (`lockdown`).

    Holatni saqlash SHART: siyosat ikki marta keladi (preflight va
    handshake) va ikkinchisi birinchisini ALMASHTIRISHI kerak, ustiga
    qo'shmasligi. Aks holda bino sozlamasidan o'chirilgan tugma
    bloklangan holda qolardi.
    """

    def __init__(self) -> None:
        self._handles: list = []
        self._active_keys: list[str] = []
        self._accessibility_saved: dict = {}
        self._lock = threading.RLock()
        self._cleanup_registered = False
        #: Bloklangan bosish haqida xabar qiluvchi (ixtiyoriy).
        self._observer: Optional[callable] = None

    def set_observer(self, observer: Optional[callable]) -> None:
        """
        Bloklangan tugma bosilganda chaqiriladigan funksiya.

        Nima uchun kerak: bloklashning O'ZI hodisa emas, lekin talabgor
        Alt+Tab ni QAYTA-QAYTA bosayotgani - eng aniq niyat belgisi.
        Usiz proktor faqat natijani (hech narsa bo'lmagan ekranni)
        ko'radi va urinishlarni umuman bilmaydi.

        DIQQAT: `keyboard` kutubxonasining hook thread'idan chaqiriladi,
        UI thread'idan EMAS. Observer thread-safe bo'lishi shart
        (Qt signalini emit qilish - shunday).
        """
        self._observer = observer

    def _notify(self, code: str) -> None:
        if self._observer is None:
            return
        try:
            self._observer(code)
        except Exception:
            # Observer xatosi bloklashni buzmasligi kerak: hook
            # ichidagi istisno `keyboard` kutubxonasini yiqitadi va
            # o'sha zahoti BARCHA tugmalar ochilib qoladi.
            log.debug("Qulflash observer xatosi", exc_info=True)

    # ------------------------------------------------------------------
    @property
    def is_available(self) -> bool:
        """`keyboard` moduli ishlayaptimi (Windows'da odatda ha)."""
        return _KEYBOARD_AVAILABLE

    @property
    def blocked_keys(self) -> list[str]:
        return list(self._active_keys)

    # ------------------------------------------------------------------
    def apply(self, keys: Optional[list] = None) -> list[str]:
        """
        Berilgan ro'yxatni qo'llaydi va HAQIQATDA bloklanganini qaytaradi.

        Idempotent: har chaqiruvda avvalgi hook'lar bo'shatiladi.
        Xato bo'lgan bitta kod butun ro'yxatni yiqitmaydi - u
        o'tkazib yuboriladi va log'da qoladi, chunki panelga qo'lda
        kiritilgan "ctrl+shft+i" kabi xato yozuv tufayli qolgan
        tugmalar ochiq qolishi mumkin emas.
        """
        with self._lock:
            self._register_cleanup()
            self._unhook_all()
            self._disable_accessibility()

            if not keys:
                log.info("Qulflash: bloklanadigan tugmalar ro'yxati bo'sh")
                return []
            if not _KEYBOARD_AVAILABLE:
                log.warning(
                    "Qulflash ISHLAMAYDI: `keyboard` moduli yo'q. "
                    "Tugmalar bloklanmaydi: %s", keys
                )
                return []

            blocked, failed = [], []
            for raw in keys:
                code = _normalize(raw)
                if not code:
                    continue
                if code in _NEVER_BLOCKED:
                    log.warning(
                        "'%s' bloklanmaydi: u dasturdan chiqishning yagona "
                        "yo'li. Ro'yxatdan olib tashlang.", code
                    )
                    continue
                try:
                    # Kombinatsiya va yakka tugma ATAYLAB har xil
                    # ishlanadi. `block_key("alt")` butun Alt tugmasini
                    # o'ldiradi - u bilan birga Alt+Shift (til
                    # almashtirish) ham yo'qoladi. `add_hotkey(...,
                    # suppress=True)` esa faqat aynan shu kombinatsiyani
                    # yutadi. Referens loyihada faqat birinchisi bor edi
                    # va ro'yxati ['alt','tab',...] shaklida yozilgan.
                    if "+" in code:
                        handle = keyboard.add_hotkey(
                            code,
                            lambda c=code: self._notify(c),
                            suppress=True,
                            trigger_on_release=False,
                        )
                    else:
                        # `block_key` o'rniga `hook_key`: ikkalasi ham
                        # bir xil bloklaydi (`block_key` shunchaki
                        # `hook_key(..., lambda e: False, suppress=True)`),
                        # lekin `hook_key` bosilganini XABAR QILISH
                        # imkonini beradi. `False` qaytarish - hodisani
                        # yutish; boshqa qiymat tugmani o'tkazib
                        # yuborardi.
                        handle = keyboard.hook_key(
                            code, self._make_blocker(code), suppress=True
                        )
                except Exception as exc:
                    failed.append("{} ({})".format(code, str(exc)[:60]))
                    continue
                self._handles.append((code, handle))
                blocked.append(code)

            self._active_keys = blocked
            log.info("Qulflash: %s ta tugma bloklandi: %s", len(blocked), blocked)
            if failed:
                log.warning("Qulflash: bloklanmagan tugmalar: %s", failed)
            return blocked

    def release(self) -> None:
        """Hamma narsani asl holiga qaytaradi. Qayta chaqirish xavfsiz."""
        with self._lock:
            self._unhook_all()
            self._restore_accessibility()

    # ------------------------------------------------------------------
    def _make_blocker(self, code: str):
        """
        Yakka tugma uchun hook: xabar qiladi va hodisani YUTADI.

        Faqat bosilishda (`down`) xabar beriladi: har bosish `down` va
        `up` juftligini beradi va ikkalasini ham hisoblash urinishlar
        sonini ikki barobar ko'rsatardi.
        """

        def handler(event) -> bool:
            if getattr(event, "event_type", None) == "down":
                self._notify(code)
            return False

        return handler

    def _unhook_all(self) -> None:
        for code, handle in self._handles:
            try:
                if "+" in code:
                    keyboard.remove_hotkey(handle)
                else:
                    # `hook_key` va `block_key` bir xil handle beradi;
                    # `unblock_key` ham aslida `unhook` ning taxallusi.
                    keyboard.unhook(handle)
            except Exception as exc:
                log.debug("Hook bo'shatilmadi (%s): %s", code, exc)
        self._handles.clear()
        self._active_keys = []

    def _register_cleanup(self) -> None:
        """
        Tiklashni dasturning HAR QANDAY tugashiga bog'laydi.

        `atexit` oddiy chiqishni va `sys.exit()` ni qamrab oladi;
        `excepthook` esa tutilmagan istisnoni. Ikkalasi ham bo'lmasa,
        yiqilgan dastur talaba mashinasida Sticky Keys'ni butunlay
        o'chirilgan holda qoldirardi.
        """
        if self._cleanup_registered:
            return
        atexit.register(self.release)

        previous_hook = sys.excepthook

        def _hook(exc_type, exc_value, traceback):
            try:
                self.release()
            finally:
                previous_hook(exc_type, exc_value, traceback)

        sys.excepthook = _hook
        self._cleanup_registered = True

    # ------------------------------------------------------------------
    # Windows Accessibility (Sticky / Filter / Toggle Keys)
    # ------------------------------------------------------------------
    #: (registry yo'li, qiymat nomi, "o'chirilgan" bayroqlari)
    _ACCESSIBILITY_KEYS = (
        (r"Control Panel\Accessibility\StickyKeys", "Flags", "506"),
        (r"Control Panel\Accessibility\FilterKeys", "Flags", "506"),
        (r"Control Panel\Accessibility\ToggleKeys", "Flags", "506"),
    )

    def _disable_accessibility(self) -> None:
        if sys.platform != "win32" or self._accessibility_saved:
            return
        try:
            import winreg
        except ImportError:
            return

        for path, name, disabled in self._ACCESSIBILITY_KEYS:
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, path, 0,
                    winreg.KEY_READ | winreg.KEY_WRITE,
                ) as key:
                    try:
                        original, _ = winreg.QueryValueEx(key, name)
                    except FileNotFoundError:
                        original = None
                    self._accessibility_saved[path] = original
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, disabled)
            except OSError as exc:
                log.debug("Accessibility o'chirilmadi (%s): %s", path, exc)

        self._apply_accessibility_now(enabled=False)
        log.info("Windows yordamchi yorliqlari o'chirildi (Sticky/Filter/Toggle)")

    def _restore_accessibility(self) -> None:
        if sys.platform != "win32" or not self._accessibility_saved:
            return
        try:
            import winreg
        except ImportError:
            return

        for path, name, _ in self._ACCESSIBILITY_KEYS:
            original = self._accessibility_saved.get(path)
            if original is None:
                continue
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_WRITE
                ) as key:
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, original)
            except OSError as exc:
                log.debug("Accessibility tiklanmadi (%s): %s", path, exc)

        self._accessibility_saved.clear()
        self._apply_accessibility_now(enabled=True)
        log.info("Windows yordamchi yorliqlari tiklandi")

    @staticmethod
    def _apply_accessibility_now(*, enabled: bool) -> None:
        """
        O'zgarishni JORIY sessiyaga darhol qo'llaydi.

        Registry yozuvining o'zi yetarli emas: u qayta kirilgunga
        (logoff/logon) qadar kuchga kirmaydi. `SystemParametersInfo`
        esa o'sha zahoti ishlaydi.
        """
        try:
            import ctypes

            # SKF_STICKYKEYSON=1 | SKF_AVAILABLE=2 | SKF_HOTKEYACTIVE=4
            flags = 0x02 | 0x04 if enabled else 0x00

            class _Sticky(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwFlags", ctypes.c_uint)]

            class _Filter(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_uint), ("dwFlags", ctypes.c_uint),
                    ("iWaitMSec", ctypes.c_uint), ("iDelayMSec", ctypes.c_uint),
                    ("iRepeatMSec", ctypes.c_uint), ("iBounceMSec", ctypes.c_uint),
                ]

            user32 = ctypes.windll.user32
            sticky = _Sticky(ctypes.sizeof(_Sticky), flags)
            user32.SystemParametersInfoW(0x003B, ctypes.sizeof(sticky), ctypes.byref(sticky), 0)

            filters = _Filter(ctypes.sizeof(_Filter), flags, 0, 0, 0, 0)
            user32.SystemParametersInfoW(0x003A, ctypes.sizeof(filters), ctypes.byref(filters), 0)

            toggle = _Sticky(ctypes.sizeof(_Sticky), flags)
            user32.SystemParametersInfoW(0x0035, ctypes.sizeof(toggle), ctypes.byref(toggle), 0)
        except Exception as exc:
            log.debug("SystemParametersInfo xatosi: %s", exc)


#: Yagona nusxa - OS holati global, demak uni boshqaruvchi ham bitta.
lockdown = _Lockdown()
