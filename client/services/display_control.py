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

DUPLICATE (KLON) REJIMI — ALOHIDA YO'L. `EnumDisplayDevices` displey
MANBALARINI (`DISPLAYn`) sanaydi, monitorlarni emas. Duplicate
rejimida ikkala monitor BITTA manbadan tasvir oladi: ro'yxatda bitta
yozuv, Qt'da ham bitta ekran — ikkinchi monitor (proyektor, yondagi
odamga qaragan ekran) imtihon sahifasini to'liq ko'rsatib turardi va
na o'chirilardi, na `multi_monitor` hodisasi chiqardi (noutbukda
amalda shunday bo'ldi; extend rejimida esa ishlardi). Shuning uchun
fizik monitorlar `QueryDisplayConfig` ning FAOL YO'LLARI (manba ->
monitor) bo'yicha sanaladi (`active_targets`), bitta manbadagi
ortiqcha yo'l esa `SetDisplayConfig` bilan o'chiriladi
(`disable_clones`). Qoladigan monitor — noutbukning ichki paneli,
bo'lmasa ro'yxatdagi birinchisi (`plan_clone_reduction`). Asl
konfiguratsiya xotirada saqlanadi va `restore` uni qaytaradi.
`SDC_TOPOLOGY_INTERNAL` ishlatilmadi — sababi yuqorida.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import POINTER, byref, wintypes
from dataclasses import dataclass, field
from typing import Optional

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


# --- QueryDisplayConfig / SetDisplayConfig (duplicate rejimi) ---
_QDC_ONLY_ACTIVE_PATHS = 0x00000002
_SDC_USE_SUPPLIED_DISPLAY_CONFIG = 0x00000020
_SDC_APPLY = 0x00000080
_SDC_SAVE_TO_DATABASE = 0x00000200
_SDC_ALLOW_CHANGES = 0x00000400
#: `SAVE_TO_DATABASE` — `CDS_UPDATEREGISTRY` bilan bir xil sabab: saqlanmagan
#: o'zgarishni Windows monitor qayta ulanganda yoki uyqudan keyin bekor
#: qilib, nusxani imtihon o'rtasida qaytarardi.
_SDC_FLAGS = (
    _SDC_APPLY | _SDC_USE_SUPPLIED_DISPLAY_CONFIG | _SDC_SAVE_TO_DATABASE | _SDC_ALLOW_CHANGES
)
_ERROR_SUCCESS = 0
_ERROR_INSUFFICIENT_BUFFER = 122
_MODE_IDX_INVALID = 0xFFFFFFFF
_MODE_INFO_TYPE_SOURCE = 1
_DEVICE_INFO_GET_TARGET_NAME = 2
#: Noutbukning ichki paneli: `INTERNAL`, `DISPLAYPORT_EMBEDDED`, `UDI_EMBEDDED`.
_INTERNAL_OUTPUTS = frozenset({0x80000000, 11, 13})


class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", ctypes.c_long)]


class _PATH_SOURCE_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", _LUID),
        ("id", ctypes.c_uint32),
        ("modeInfoIdx", ctypes.c_uint32),
        ("statusFlags", ctypes.c_uint32),
    ]


class _RATIONAL(ctypes.Structure):
    _fields_ = [("Numerator", ctypes.c_uint32), ("Denominator", ctypes.c_uint32)]


class _PATH_TARGET_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", _LUID),
        ("id", ctypes.c_uint32),
        ("modeInfoIdx", ctypes.c_uint32),
        ("outputTechnology", ctypes.c_uint32),
        ("rotation", ctypes.c_uint32),
        ("scaling", ctypes.c_uint32),
        ("refreshRate", _RATIONAL),
        ("scanLineOrdering", ctypes.c_uint32),
        ("targetAvailable", wintypes.BOOL),
        ("statusFlags", ctypes.c_uint32),
    ]


class DISPLAYCONFIG_PATH_INFO(ctypes.Structure):
    _fields_ = [
        ("sourceInfo", _PATH_SOURCE_INFO),
        ("targetInfo", _PATH_TARGET_INFO),
        ("flags", ctypes.c_uint32),
    ]


class DISPLAYCONFIG_MODE_INFO(ctypes.Structure):
    """
    Rejim yozuvi. Union (manba/monitor/tasvir rejimi) XOM BAYT sifatida:
    yozuvlar o'zgartirilmasdan qayta uzatiladi, o'qiladigani esa faqat
    manba o'lchami (`_source_size`). Union'ning eng katta varianti
    (`DISPLAYCONFIG_TARGET_MODE`) 48 bayt, tuzilma jami 64 bayt.
    """

    _fields_ = [
        ("infoType", ctypes.c_uint32),
        ("id", ctypes.c_uint32),
        ("adapterId", _LUID),
        ("mode", ctypes.c_uint32 * 12),
    ]


class _DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("size", ctypes.c_uint32),
        ("adapterId", _LUID),
        ("id", ctypes.c_uint32),
    ]


class _TARGET_DEVICE_NAME(ctypes.Structure):
    _fields_ = [
        ("header", _DEVICE_INFO_HEADER),
        ("flags", ctypes.c_uint32),
        ("outputTechnology", ctypes.c_uint32),
        ("edidManufactureId", ctypes.c_uint16),
        ("edidProductCodeId", ctypes.c_uint16),
        ("connectorInstance", ctypes.c_uint32),
        ("monitorFriendlyDeviceName", wintypes.WCHAR * 64),
        ("monitorDevicePath", wintypes.WCHAR * 128),
    ]


@dataclass
class DisplayTarget:
    """Bitta FAOL yo'l: manba (`source`) -> fizik monitor (`target`)."""

    adapter: tuple                # (LowPart, HighPart) — manba LUID'i
    source_id: int
    target_id: int
    output_technology: int
    name: str = ""                # EDID'dagi monitor nomi
    width: int = 0                # manba o'lchami (nusxada ikkalasida bir xil)
    height: int = 0

    @property
    def internal(self) -> bool:
        return self.output_technology in _INTERNAL_OUTPUTS

    @property
    def source_key(self) -> tuple:
        return (self.adapter, self.source_id)

    def as_display(self) -> "Display":
        return Display(
            name="target #{}".format(self.target_id),
            label="{} (duplicate)".format(self.name or "monitor"),
            width=self.width,
            height=self.height,
        )


def plan_clone_reduction(targets: list) -> list:
    """
    O'chiriladigan yo'llarning INDEKSLARI (sof funksiya, testlanadi).

    Bitta manbaga ulangan har guruhda BITTA monitor qoladi: noutbukning
    ichki paneli (talabgor aynan uning oldida o'tiradi), u bo'lmasa —
    ro'yxatdagi birinchisi. Turli manbalar (extend) bu yerda
    tegilmaydi — ular `disable_secondary` ning o'z yo'li.
    """
    groups: dict = {}
    for index, target in enumerate(targets):
        groups.setdefault(target.source_key, []).append(index)
    drop: list = []
    for indexes in groups.values():
        if len(indexes) < 2:
            continue
        keep = next((i for i in indexes if targets[i].internal), indexes[0])
        drop.extend(i for i in indexes if i != keep)
    return sorted(drop)


def compact_config(paths, modes, keep: list):
    """
    Faqat `keep` yo'llari va ular ishlatadigan rejimlar — qayta indekslangan.

    `SetDisplayConfig(SDC_USE_SUPPLIED_DISPLAY_CONFIG)` ga berilmagan yo'l
    faolsizlantiriladi. Rejimlar ham qisqartiriladi: ishlatilmaydigan
    (o'chirilgan monitorniki) rejim qolsa ba'zi drayverlar
    `ERROR_INVALID_PARAMETER` qaytaradi.
    """
    new_modes: list = []
    remap: dict = {}

    def take(index: int) -> int:
        if index == _MODE_IDX_INVALID or index >= len(modes):
            return _MODE_IDX_INVALID
        if index not in remap:
            remap[index] = len(new_modes)
            new_modes.append(modes[index])
        return remap[index]

    new_paths = (DISPLAYCONFIG_PATH_INFO * len(keep))()
    for slot, index in enumerate(keep):
        ctypes.memmove(byref(new_paths[slot]), byref(paths[index]), ctypes.sizeof(DISPLAYCONFIG_PATH_INFO))
        new_paths[slot].sourceInfo.modeInfoIdx = take(paths[index].sourceInfo.modeInfoIdx)
        new_paths[slot].targetInfo.modeInfoIdx = take(paths[index].targetInfo.modeInfoIdx)
    mode_array = (DISPLAYCONFIG_MODE_INFO * max(1, len(new_modes)))()
    for slot, mode in enumerate(new_modes):
        ctypes.memmove(byref(mode_array[slot]), byref(mode), ctypes.sizeof(DISPLAYCONFIG_MODE_INFO))
    return new_paths, mode_array, len(new_modes)


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
    _user32.GetDisplayConfigBufferSizes.argtypes = [
        ctypes.c_uint32, POINTER(ctypes.c_uint32), POINTER(ctypes.c_uint32)
    ]
    _user32.GetDisplayConfigBufferSizes.restype = ctypes.c_long
    _user32.QueryDisplayConfig.argtypes = [
        ctypes.c_uint32,
        POINTER(ctypes.c_uint32), POINTER(DISPLAYCONFIG_PATH_INFO),
        POINTER(ctypes.c_uint32), POINTER(DISPLAYCONFIG_MODE_INFO),
        ctypes.c_void_p,
    ]
    _user32.QueryDisplayConfig.restype = ctypes.c_long
    _user32.SetDisplayConfig.argtypes = [
        ctypes.c_uint32, POINTER(DISPLAYCONFIG_PATH_INFO),
        ctypes.c_uint32, POINTER(DISPLAYCONFIG_MODE_INFO),
        ctypes.c_uint32,
    ]
    _user32.SetDisplayConfig.restype = ctypes.c_long
    _user32.DisplayConfigGetDeviceInfo.argtypes = [POINTER(_DEVICE_INFO_HEADER)]
    _user32.DisplayConfigGetDeviceInfo.restype = ctypes.c_long
else:  # pragma: no cover - loyiha Windows uchun
    _user32 = None


#: O'chirilgan ekranlarning ASL rejimi: nom -> `DEVMODEW`.
#
# Modul darajasida, chunki o'chirish `main()` da (Qt'dan oldin), qaytarish
# esa dastur yopilishida bajariladi - ikkalasi orasida umumiy obyekt yo'q.
_saved: dict = {}

#: Duplicate o'chirilishidan OLDINGI faol konfiguratsiya: (yo'llar, rejimlar).
#: Faqat BIRINCHI o'chirishda yoziladi — imtihon davomidagi takroriy
#: o'chirish asl holatni "allaqachon qisqartirilgan" bilan almashtirmasin.
_saved_topology = None


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

    # `extra` bo'sh bo'lsa ham QAYTILMAYDI: duplicate rejimida ikkala
    # monitor bitta manbada va `EnumDisplayDevices` faqat asosiysini
    # ko'radi — ortiqcha monitor faqat pastdagi `disable_clones` da topiladi.
    extra = [item for item in displays if not item.is_primary]

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

    # Extend uzilgandan KEYIN: endi faqat asosiy manba qolgan va uning
    # nusxalari (duplicate) shu yerda ko'rinadi.
    clones = disable_clones()
    report.disabled.extend(clones.disabled)
    report.failed.extend(clones.failed)
    return report


def active_targets() -> Optional[list]:
    """
    Hozir tasvir ko'rsatayotgan FIZIK monitorlar (`DisplayTarget`).

    `None` — aniqlab bo'lmadi (Windows emas yoki API xatosi);
    chaqiruvchi Qt'ning ekranlar soniga qaytadi.
    """
    config = _query_active()
    return None if config is None else _targets_of(config)


def _targets_of(config) -> list:
    paths, count, modes = config
    targets = []
    for index in range(count):
        path = paths[index]
        width, height = _source_size(modes, path.sourceInfo.modeInfoIdx)
        targets.append(DisplayTarget(
            adapter=(path.sourceInfo.adapterId.LowPart, path.sourceInfo.adapterId.HighPart),
            source_id=int(path.sourceInfo.id),
            target_id=int(path.targetInfo.id),
            output_technology=int(path.targetInfo.outputTechnology),
            name=_target_name(path),
            width=width,
            height=height,
        ))
    return targets


def active_monitor_count() -> Optional[int]:
    """Fizik monitorlar soni (duplicate'dagilar ham) yoki `None`."""
    targets = active_targets()
    return None if targets is None else len(targets)


def disable_clones() -> DisplayReport:
    """
    Duplicate rejimidagi ortiqcha monitorlarni o'chiradi.

    Imtihon DAVOMIDA ham xavfsiz (`DeviceWatcher`): manba o'zgarmaydi,
    ya'ni oynamiz turgan ekran va Qt'ning ekranlar ro'yxati joyida
    qoladi — extend'dagi uzishdan farqi shu.
    """
    global _saved_topology
    report = DisplayReport()
    config = _query_active()
    if config is None:
        report.checked = False
        return report
    # Yo'llar va monitorlar BITTA so'rovdan: indekslar mos kelishi shart.
    paths, count, modes = config
    targets = _targets_of(config)
    drop = plan_clone_reduction(targets)
    if not drop:
        return report

    keep = [index for index in range(count) if index not in drop]
    new_paths, new_modes, mode_count = compact_config(paths, modes, keep)
    original = (paths, count, modes)
    result = _user32.SetDisplayConfig(len(keep), new_paths, mode_count, new_modes, _SDC_FLAGS)
    dropped = [targets[index].as_display() for index in drop]
    if result != _ERROR_SUCCESS:
        log.warning("Duplicate monitorni o'chirib bo'lmadi (SetDisplayConfig %s): %s",
                    result, ", ".join(item.describe() for item in dropped))
        report.failed.extend(dropped)
        return report
    if _saved_topology is None:
        _saved_topology = original
    report.disabled.extend(dropped)
    return report


def restore() -> None:
    """
    O'chirilgan ekranlarni qaytaradi — dastur yopilishida.

    Uzish registrda saqlanadi, ya'ni qaytarmaslik monitorni
    imtihondan KEYIN ham o'chirilgan holda qoldirardi va operator
    uni Windows sozlamalaridan qo'lda qaytarishga majbur bo'lardi.

    Tartib uzishning teskarisi: avval duplicate (asosiy manba
    konfiguratsiyasi), keyin extend'dagi uzilgan manbalar.
    """
    if not _IS_WINDOWS:
        return
    _restore_topology()
    if not _saved:
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


def _restore_topology() -> None:
    global _saved_topology
    if _saved_topology is None:
        return
    paths, count, modes = _saved_topology
    _saved_topology = None
    result = _user32.SetDisplayConfig(count, paths, len(modes), modes, _SDC_FLAGS)
    if result != _ERROR_SUCCESS:
        # Odatda sabab — monitor imtihon davomida uzilgan: qaytariladigan
        # narsa yo'q, Windows qolganini o'zi joylashtiradi.
        log.warning("Duplicate monitor qaytarilmadi (SetDisplayConfig %s)", result)
        return
    log.info("Duplicate monitor(lar) qaytarildi")


def _query_active():
    """`(yo'llar, yo'llar soni, rejimlar)` yoki `None`."""
    if not _IS_WINDOWS:
        return None
    for _attempt in range(3):
        path_count = ctypes.c_uint32()
        mode_count = ctypes.c_uint32()
        if _user32.GetDisplayConfigBufferSizes(
            _QDC_ONLY_ACTIVE_PATHS, byref(path_count), byref(mode_count)
        ) != _ERROR_SUCCESS:
            return None
        paths = (DISPLAYCONFIG_PATH_INFO * max(1, path_count.value))()
        modes = (DISPLAYCONFIG_MODE_INFO * max(1, mode_count.value))()
        result = _user32.QueryDisplayConfig(
            _QDC_ONLY_ACTIVE_PATHS, byref(path_count), paths, byref(mode_count), modes, None
        )
        if result == _ERROR_INSUFFICIENT_BUFFER:
            # So'rovlar orasida monitor ulandi/uzildi - qaytadan o'lchaymiz.
            continue
        if result != _ERROR_SUCCESS:
            log.debug("QueryDisplayConfig xatosi: %s", result)
            return None
        # Rejimlar AYNAN qaytgan soncha: `len(modes)` keyin to'g'ridan-
        # to'g'ri `SetDisplayConfig` ga soni sifatida uzatiladi (`restore`).
        exact = (DISPLAYCONFIG_MODE_INFO * mode_count.value)()
        ctypes.memmove(exact, modes, ctypes.sizeof(DISPLAYCONFIG_MODE_INFO) * mode_count.value)
        return paths, int(path_count.value), exact
    return None


def _source_size(modes, index: int) -> tuple:
    if index == _MODE_IDX_INVALID or index >= len(modes):
        return 0, 0
    mode = modes[index]
    if mode.infoType != _MODE_INFO_TYPE_SOURCE:
        return 0, 0
    # DISPLAYCONFIG_SOURCE_MODE: width, height, pixelFormat, position.
    return int(mode.mode[0]), int(mode.mode[1])


def _target_name(path) -> str:
    info = _TARGET_DEVICE_NAME()
    info.header.type = _DEVICE_INFO_GET_TARGET_NAME
    info.header.size = ctypes.sizeof(_TARGET_DEVICE_NAME)
    info.header.adapterId = path.targetInfo.adapterId
    info.header.id = path.targetInfo.id
    try:
        if _user32.DisplayConfigGetDeviceInfo(byref(info.header)) != _ERROR_SUCCESS:
            return ""
    except OSError:
        return ""
    return info.monitorFriendlyDeviceName or ""


def _apply() -> int:
    """To'plangan o'zgarishlarni qo'llaydi (`NULL, NULL`)."""
    result = _user32.ChangeDisplaySettingsExW(None, None, None, 0, None)
    if result != _DISP_CHANGE_SUCCESSFUL:
        log.warning(
            "Ekran konfiguratsiyasi qo'llanmadi: %s",
            _DISP_CHANGE.get(result, result),
        )
    return result
