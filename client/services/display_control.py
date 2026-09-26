"""
Ortiqcha monitorlarni o'chirish — imtihon BITTA ekranda o'tadi.

NIMA UCHUN KERAK. Ikkinchi monitor kiosk rejimining butun mantig'ini
bekor qiladi: bizning oynamiz birinchi ekranda to'liq ochiladi,
talabgor esa yonidagi ekranda ochiq qolgan hujjatni, messenjerni
yoki masofadan ulangan odamning kursorini ko'rib turadi. Skrinshot
ham faqat ASOSIY ekranni oladi (`services/screen_capture.py`), ya'ni
bayonnomada bu umuman iz qoldirmaydi.

`DeviceWatcher` ikkinchi monitorni allaqachon ANIQLAYDI va
`multi_monitor` hodisasini yozadi — lekin u hodisa, ya'ni proktor
ekranidagi qator. Qator paydo bo'lguncha talabgor uni allaqachon
ishlatgan bo'ladi. Shuning uchun bu modul ikkinchi qadamni bajaradi:
monitor ISH STOLIDAN UZILADI (kengaytirilgan ish stoli qismi
bo'lishdan to'xtaydi) va Windows unga umuman chizmaydi.

QANDAY UZILADI. `ChangeDisplaySettingsEx` ga NOL o'lchamli
`DEVMODE` beriladi — bu monitorni uzishning hujjatlashtirilgan
yo'li. `SetDisplayConfig(SDC_TOPOLOGY_INTERNAL)` qisqaroq bo'lardi,
lekin u faqat noutbukda ishlaydi ("ichki panel"), imtihon
mashinalari esa odatda statsionar kompyuter — u yerda "ichki
panel" tushunchasi yo'q va chaqiruv xato qaytaradi.

ADMINISTRATOR HUQUQI KERAK EMAS: ekran konfiguratsiyasi joriy
seans (interaktiv foydalanuvchi) doirasida o'zgaradi.

ASOSIY MONITORGA TEGILMAYDI va bu yagona istisno emas: oynani
umuman ko'rsatadigan ekran qolishi kerak. Ko'zgu drayverlari
(mirroring driver — ba'zi masofaviy boshqaruv dasturlari shunday
qurilma yaratadi) ham chetlab o'tiladi: ular ish stolining
kengaytmasi emas va ularni uzish drayverni qulatishi mumkin.
Masofaviy boshqaruvning o'zi bilan `threat_scanner` shug'ullanadi.

CHIQISHDA QAYTARILADI (`restore`). Uzish `CDS_UPDATEREGISTRY`
bilan bajariladi, ya'ni u qayta yuklashdan keyin ham saqlanadi —
dastur monitorni o'chirib, uni o'z holicha qoldirsa, mashina
imtihondan keyin ham bitta ekranda qolardi va buni operator
tuzatishi kerak bo'lardi. Shuning uchun asl `DEVMODE` xotirada
saqlanadi va yopilishda qaytariladi.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import POINTER, byref, wintypes
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"

# --- DISPLAY_DEVICE.StateFlags ---
_ATTACHED_TO_DESKTOP = 0x00000001
_MIRRORING_DRIVER = 0x00000008
_PRIMARY_DEVICE = 0x00000004

# --- EnumDisplaySettingsEx ---
_ENUM_CURRENT_SETTINGS = -1

# --- DEVMODE.dmFields ---
_DM_POSITION = 0x00000020
_DM_BITSPERPEL = 0x00040000
_DM_PELSWIDTH = 0x00080000
_DM_PELSHEIGHT = 0x00100000
_DM_DISPLAYFREQUENCY = 0x00400000
#: QAYTARISHDA beriladigan maydonlar — qiymatlar haqiqiy.
_DM_RESTORE_FIELDS = (
    _DM_POSITION | _DM_BITSPERPEL | _DM_PELSWIDTH | _DM_PELSHEIGHT
    | _DM_DISPLAYFREQUENCY
)

#: UZISHDA beriladigan maydonlar — qiymatlar NOL.
#:
#: `DM_BITSPERPEL` VA `DM_DISPLAYFREQUENCY` BU YERDA BO'LMASLIGI
#: KERAK va bu shu mashinada o'lchab aniqlandi: ular bilan drayver
#: `DISP_CHANGE_BADMODE` (-2) qaytaradi — nol rang chuqurligi va nol
#: chastota u uchun yaroqsiz GRAFIK REJIM, holbuki biz rejim
#: so'ramayapmiz, ekranni ish stolidan uzayapmiz. Faqat joylashuv va
#: nol o'lcham qolganda chaqiruv muvaffaqiyatli bo'ladi.
_DM_DETACH_FIELDS = _DM_POSITION | _DM_PELSWIDTH | _DM_PELSHEIGHT

# --- ChangeDisplaySettingsEx ---
_CDS_UPDATEREGISTRY = 0x00000001
_CDS_NORESET = 0x10000000
_DISP_CHANGE_SUCCESSFUL = 0

#: `ChangeDisplaySettingsEx` xato kodlari — log uchun.
_DISP_CHANGE = {
    0: "ok",
    -1: "restart kerak",
    -2: "drayver rad etdi",
    -3: "yozib bo'lmadi",
    -4: "tizim xatosi",
    -5: "noto'g'ri rejim",
    -6: "qo'llab-quvvatlanmaydi",
}


class _POINTL(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _DEVMODE_DISPLAY(ctypes.Structure):
    """`DEVMODE` union'ining EKRAN varianti (printer varianti kerak emas)."""

    _fields_ = [
        ("dmPosition", _POINTL),
        ("dmDisplayOrientation", wintypes.DWORD),
        ("dmDisplayFixedOutput", wintypes.DWORD),
    ]


class DEVMODEW(ctypes.Structure):
    """
    `DEVMODEW` — ekran rejimi.

    Union'lar ATAYLAB bitta variant bilan yozilgan: printerga oid
    maydonlar bir xil o'lchamni egallaydi (8 ta `short` = 16 bayt)
    va bizga kerak emas. Tuzilmaning UMUMIY o'lchami muhim —
    `dmSize` shundan olinadi va Windows aynan shu qiymatga qarab
    maydonlarni o'qiydi.
    """

    _fields_ = [
        ("dmDeviceName", wintypes.WCHAR * 32),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("dmDisplay", _DEVMODE_DISPLAY),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", wintypes.WCHAR * 32),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD),
        ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD),
        ("dmICMIntent", wintypes.DWORD),
        ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD),
        ("dmReserved1", wintypes.DWORD),
        ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD),
        ("dmPanningHeight", wintypes.DWORD),
    ]


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]


@dataclass
class Display:
    """Bitta ekran — ro'yxat va log uchun."""

    name: str                     # `\\.\DISPLAY2`
    label: str                    # adapter nomi
    is_primary: bool = False
    width: int = 0
    height: int = 0

    def describe(self) -> str:
        return "{} ({}x{}, {})".format(
            self.label or self.name, self.width, self.height, self.name
        )


@dataclass
class DisplayReport:
    """Nima o'chirildi va nima qoldi."""

    #: O'chirilgan ekranlar.
    disabled: list = field(default_factory=list)
    #: Topildi, lekin o'chirib bo'lmadi (drayver rad etdi).
    failed: list = field(default_factory=list)
    #: Asosiy ekran — hech qachon tegilmaydi.
    primary: str = ""
    #: Umuman tekshirildimi (Windows emas / bayroq o'chirilgan).
    checked: bool = True

    @property
    def changed(self) -> bool:
        return bool(self.disabled)

    def summary(self) -> str:
        if not self.checked:
            return "tekshirilmadi"
        if not self.disabled and not self.failed:
            return "bitta ekran"
        parts = []
        if self.disabled:
            parts.append("{} ta o'chirildi".format(len(self.disabled)))
        if self.failed:
            parts.append("{} tasi o'chmadi".format(len(self.failed)))
        return ", ".join(parts)


if _IS_WINDOWS:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)

    # `argtypes` MAJBURIY: usiz ctypes ko'rsatkichni 32-bitli `int`
    # deb uzatadi va 64-bitli Windows'da chaqiruv jimgina buziladi
    # (loyihada bu xato `threat_scanner._stop_service` da uchragan).
    _user32.EnumDisplayDevicesW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, POINTER(DISPLAY_DEVICEW), wintypes.DWORD
    ]
    _user32.EnumDisplayDevicesW.restype = wintypes.BOOL
    _user32.EnumDisplaySettingsExW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, POINTER(DEVMODEW), wintypes.DWORD
    ]
    _user32.EnumDisplaySettingsExW.restype = wintypes.BOOL
    _user32.ChangeDisplaySettingsExW.argtypes = [
        wintypes.LPCWSTR, POINTER(DEVMODEW), wintypes.HWND,
        wintypes.DWORD, ctypes.c_void_p,
    ]
    _user32.ChangeDisplaySettingsExW.restype = ctypes.c_long
else:  # pragma: no cover - loyiha Windows uchun
    _user32 = None


#: O'chirilgan ekranlarning ASL rejimi: nom -> `DEVMODEW`.
#
# Modul darajasida, chunki o'chirish `main()` da (Qt'dan oldin), qaytarish
# esa dastur yopilishida bajariladi - ikkalasi orasida umumiy obyekt yo'q.
_saved: dict = {}


# --------------------------------------------------------------------------
def list_displays() -> list[Display]:
    """
    Ish stoliga ulangan ekranlar.

    Ko'zgu drayverlari ro'yxatga KIRMAYDI: ular ish stolining
    kengaytmasi emas, mavjud ekranning nusxasi.
    """
    if not _IS_WINDOWS:
        return []

    found: list[Display] = []
    index = 0
    while True:
        device = DISPLAY_DEVICEW()
        device.cb = ctypes.sizeof(DISPLAY_DEVICEW)
        if not _user32.EnumDisplayDevicesW(None, index, byref(device), 0):
            break
        index += 1

        flags = device.StateFlags
        if not flags & _ATTACHED_TO_DESKTOP:
            continue
        if flags & _MIRRORING_DRIVER:
            continue

        mode = _current_mode(device.DeviceName)
        found.append(
            Display(
                name=device.DeviceName,
                label=device.DeviceString,
                is_primary=bool(flags & _PRIMARY_DEVICE),
                width=int(mode.dmPelsWidth) if mode else 0,
                height=int(mode.dmPelsHeight) if mode else 0,
            )
        )
    return found


def disable_secondary() -> DisplayReport:
    """
    Asosiy bo'lmagan barcha ekranlarni ish stolidan uzadi.

    QT'DAN OLDIN chaqiriladi: `QApplication` ekranlar ro'yxatini
    ishga tushishda o'qiydi va oynani joylashtirishda undan
    foydalanadi. Keyin o'chirilsa, Qt oynani endi mavjud bo'lmagan
    ekranga qo'ygan bo'lishi mumkin va u ko'rinmay qoladi.

    XATO DASTURNI TO'XTATMAYDI: bu tozalash bosqichi, imtihonning
    sharti emas. O'chirilmagan monitor `DeviceWatcher` orqali
    baribir hodisa sifatida qayd etiladi va proktor uni ko'radi.
    """
    report = DisplayReport()
    if not _IS_WINDOWS:
        report.checked = False
        return report

    displays = list_displays()
    primary = next((item for item in displays if item.is_primary), None)
    report.primary = primary.name if primary else ""

    extra = [item for item in displays if not item.is_primary]
    if not extra:
        return report

    applied = False
    for display in extra:
        # ASL REJIM AVVAL SAQLANADI. `CDS_UPDATEREGISTRY` registrdagi
        # yozuvni ham o'zgartiradi, ya'ni uzgandan keyin "avval qanday
        # edi?" degan savolga javob beradigan manba qolmaydi.
        mode = _current_mode(display.name)
        result = _detach(display.name)
        if result != _DISP_CHANGE_SUCCESSFUL:
            log.warning(
                "Monitorni o'chirib bo'lmadi: %s — %s",
                display.describe(), _DISP_CHANGE.get(result, result),
            )
            report.failed.append(display)
            continue
        if mode is not None:
            _saved[display.name] = mode
        report.disabled.append(display)
        applied = True

    if applied:
        # `CDS_NORESET` bilan yuborilgan o'zgarishlar BIRGA qo'llanadi:
        # har bir monitorni alohida qo'llash ekranning bir necha marta
        # qorayib-yonishiga olib kelardi.
        _apply()
    return report


def restore() -> None:
    """
    O'chirilgan ekranlarni qaytaradi — dastur yopilishida.

    Uzish registrda saqlanadi, ya'ni qaytarmaslik monitorni
    imtihondan KEYIN ham o'chirilgan holda qoldirardi va operator
    uni Windows sozlamalaridan qo'lda qaytarishga majbur bo'lardi.
    """
    if not _IS_WINDOWS or not _saved:
        return

    restored = []
    for name, mode in list(_saved.items()):
        mode.dmFields = _DM_RESTORE_FIELDS
        result = _user32.ChangeDisplaySettingsExW(
            name, byref(mode), None, _CDS_UPDATEREGISTRY | _CDS_NORESET, None
        )
        if result != _DISP_CHANGE_SUCCESSFUL:
            log.warning(
                "Monitorni qaytarib bo'lmadi: %s — %s",
                name, _DISP_CHANGE.get(result, result),
            )
            continue
        restored.append(name)
    _saved.clear()

    if restored:
        _apply()
        log.info("Monitorlar qaytarildi: %s", ", ".join(restored))


# --------------------------------------------------------------------------
def _current_mode(name: str):
    mode = DEVMODEW()
    mode.dmSize = ctypes.sizeof(DEVMODEW)
    if not _user32.EnumDisplaySettingsExW(name, _ENUM_CURRENT_SETTINGS, byref(mode), 0):
        return None
    return mode


def _detach(name: str) -> int:
    """
    Ekranni ish stolidan uzadi.

    NOL O'LCHAM — uzishning hujjatlashtirilgan yo'li: `dmFields` da
    o'lcham va joylashuv bayroqlari bor, qiymatlar esa nol. Buni
    "rezolyutsiyani 0 ga qo'yish" deb o'qish mumkin emas — Windows
    aynan shu kombinatsiyani "bu ekran endi ish stolining qismi
    emas" deb tushunadi.

    Maydonlar ro'yxati `_DM_DETACH_FIELDS` da va u qaytarishnikidan
    FARQ QILADI — sabab o'sha izohda.
    """
    mode = DEVMODEW()
    mode.dmSize = ctypes.sizeof(DEVMODEW)
    mode.dmFields = _DM_DETACH_FIELDS
    return _user32.ChangeDisplaySettingsExW(
        name, byref(mode), None, _CDS_UPDATEREGISTRY | _CDS_NORESET, None
    )


def _apply() -> int:
    """To'plangan o'zgarishlarni qo'llaydi (`NULL, NULL`)."""
    result = _user32.ChangeDisplaySettingsExW(None, None, None, 0, None)
    if result != _DISP_CHANGE_SUCCESSFUL:
        log.warning(
            "Ekran konfiguratsiyasi qo'llanmadi: %s",
            _DISP_CHANGE.get(result, result),
        )
    return result
