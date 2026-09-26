"""
Klaviatura tili — Windows API orqali (`user32`, `kernel32`).

NIMA UCHUN BU KERAK. Kiosk rejimida vazifalar paneli yashiringan
va til almashtirish tugmalari (`alt+shift`, `win+space`) server
bergan ro'yxat bo'yicha BLOKLANGAN bo'lishi mumkin
(`services/lockdown.py`). O'shanda talabgor ham, operator ham
tilni umuman almashtira olmaydi: JSHSHIR raqam bo'lgani uchun
muammo bo'lmaydi, lekin hujjat raqami, izoh va tashqi
platformadagi javob maydonlari lotin/kirill/rus tilini talab
qiladi. Dastur ichidagi almashtirgich bu bo'shliqni yopadi.

QANDAY ALMASHTIRILADI. `ActivateKeyboardLayout` faqat CHAQIRUVCHI
thread'ga ta'sir qiladi va u Qt oynasining kirish tilini
o'zgartirmaydi. To'g'ri yo'l - oynaga `WM_INPUTLANGCHANGEREQUEST`
xabarini yuborish: Windows tilni o'sha oyna uchun almashtiradi va
tildagi indikatorni ham yangilaydi.

Modul HECH QANDAY UI ni bilmaydi va hech narsani keshlamaydi:
foydalanuvchi tilni tizim vositalari bilan ham o'zgartirishi
mumkin, ya'ni joriy qiymat har safar OS'dan so'raladi.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from dataclasses import dataclass

log = logging.getLogger(__name__)

#: `WM_INPUTLANGCHANGEREQUEST` — oynaga "tilni almashtir" xabari.
_WM_INPUTLANGCHANGEREQUEST = 0x0050

#: Til kodi: `en`, `ru`, `uz`.
_LOCALE_SISO639LANGNAME = 0x59
#: To'liq nom: "Uzbek (Cyrillic, Uzbekistan)".
_LOCALE_SLOCALIZEDDISPLAYNAME = 0x02
#: BCP-47 nomi: `uz-Cyrl-UZ`. Yozuvni ajratish uchun kerak.
_LOCALE_SNAME = 0x5C

#: Yozuv belgisi -> qisqartma qo'shimchasi.
#:
#: O'zbek tili ikki yozuvda va ikkalasi ham bitta `uz` kodini
#: beradi. Ular bir vaqtda o'rnatilgan bo'lsa (O'zbekistonda odatiy
#: hol), ikkita bir xil "UZ" tugmasi paydo bo'lardi va operator
#: qaysi biri lotin ekanini faqat bosib ko'rib bilardi.
_SCRIPT_SUFFIX = {"Cyrl": "К", "Latn": "L"}


@dataclass(frozen=True)
class Layout:
    """Bitta klaviatura tili."""

    hkl: int
    #: Tugmada ko'rinadigan qisqartma: `UZ`, `RU`, `EN`.
    code: str
    #: Tooltip uchun to'liq nom.
    name: str


def is_supported() -> bool:
    return sys.platform == "win32"


def available() -> list:
    """
    O'rnatilgan klaviatura tillari.

    Ro'yxat OS'dan olinadi va dasturda qat'iy yozilmaydi: qaysi
    tillar borligini administrator mashinani sozlashda hal qiladi,
    dastur esa borini ko'rsatadi.
    """
    if not is_supported():
        return []
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        count = user32.GetKeyboardLayoutList(0, None)
        if count <= 0:
            return []
        buffer = (wintypes.HKL * count)()
        user32.GetKeyboardLayoutList(count, buffer)
    except OSError:
        log.debug("Klaviatura tillari o'qilmadi", exc_info=True)
        return []

    layouts = []
    seen_codes: dict = {}
    for handle in buffer:
        hkl = int(handle) & 0xFFFFFFFF
        langid = hkl & 0xFFFF
        code = (_locale_info(langid, _LOCALE_SISO639LANGNAME) or "??").upper()
        name = _locale_info(langid, _LOCALE_SLOCALIZEDDISPLAYNAME) or code
        layouts.append(Layout(hkl=hkl, code=code, name=name))
        seen_codes[code] = seen_codes.get(code, 0) + 1

    # Takrorlangan kodlarga yozuv qo'shimchasi qo'shiladi.
    result = []
    for layout in layouts:
        if seen_codes.get(layout.code, 0) > 1:
            script = _script_of(layout.hkl & 0xFFFF)
            if script:
                layout = Layout(
                    hkl=layout.hkl,
                    code="{}·{}".format(layout.code, script),
                    name=layout.name,
                )
        result.append(layout)
    return result


def current_hkl(hwnd: int = 0) -> int:
    """
    Oyna uchun joriy klaviatura tili.

    `hwnd` berilmasa old plandagi oyna olinadi. Qiymat
    KESHLANMAYDI: til tizim vositalari bilan ham o'zgarishi
    mumkin va eskirgan kesh tugmalarni noto'g'ri belgilardi.
    """
    if not is_supported():
        return 0
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        window = hwnd or user32.GetForegroundWindow()
        thread_id = user32.GetWindowThreadProcessId(wintypes.HWND(window), None)
        return int(user32.GetKeyboardLayout(thread_id)) & 0xFFFFFFFF
    except OSError:
        log.debug("Joriy klaviatura tili o'qilmadi", exc_info=True)
        return 0


def activate(hkl: int, hwnd: int) -> bool:
    """
    Tilni almashtiradi.

    `PostMessage` ASINXRON: xabar navbatga tushadi va Windows uni
    o'z tartibida qayta ishlaydi. Sinxron `SendMessage` UI
    thread'ini oynaning javobiga bog'lab qo'yardi - QtWebEngine
    ochiq bo'lganda bu sezilarli kechikish beradi.

    Qo'shimcha `ActivateKeyboardLayout` zaxira sifatida: u
    chaqiruvchi thread uchun tilni darhol o'rnatadi va xabar
    biror sababga ko'ra yo'qolsa ham kiritish to'g'ri tilda
    ketadi.
    """
    if not is_supported() or not hkl or not hwnd:
        return False
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.PostMessageW(
            wintypes.HWND(hwnd),
            _WM_INPUTLANGCHANGEREQUEST,
            wintypes.WPARAM(0),
            wintypes.LPARAM(hkl),
        )
        user32.ActivateKeyboardLayout(wintypes.HKL(hkl), 0)
        return True
    except OSError:
        log.warning("Klaviatura tilini almashtirib bo'lmadi", exc_info=True)
        return False


# --------------------------------------------------------------------------
def _locale_info(langid: int, kind: int) -> str:
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        buffer = ctypes.create_unicode_buffer(128)
        if kernel32.GetLocaleInfoW(langid, kind, buffer, 128):
            return buffer.value.strip()
    except OSError:
        log.debug("GetLocaleInfoW xatosi", exc_info=True)
    return ""


def _script_of(langid: int) -> str:
    """`uz-Cyrl-UZ` -> `К`. Yozuv ko'rsatilmagan bo'lsa bo'sh satr."""
    name = _locale_info(langid, _LOCALE_SNAME)
    for script, suffix in _SCRIPT_SUFFIX.items():
        if script in name:
            return suffix
    return ""
