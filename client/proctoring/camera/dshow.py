"""
DirectShow video qurilmalari ro'yxati — OpenCV INDEKSI bilan bir xil
tartibda.

NIMA UCHUN KERAK. Ilgari nom Windows PnP ro'yxatidan (`Get-PnpDevice
-Class Camera`) olinar va OpenCV indeksiga TARTIB bo'yicha
juftlanardi. Ikkala ro'yxat ham "kameralar" haqida, lekin ular BIR
XIL EMAS va tartiblari ham bir xil emas:

  * PnP ro'yxati qurilma instansiyalari bo'yicha tuziladi va
    OpenCV'ning `CAP_DSHOW` sanog'iga hech qanday aloqasi yo'q;
  * virtual kamera (OBS, ManyCam) PnP qurilmasi EMAS — u
    ro'yxatdan umuman tushib qoladi, DirectShow'da esa bor va
    OpenCV unga indeks beradi;
  * o'chirilgan yoki band qurilma ikkala ro'yxatda boshqacha
    ko'rinadi.

Natija ekranda shunday chiqardi: mashinada ikkita veb-kamera bor
("Logi C270" va "GRANDSTREAM GUV3100"), operator birinchi kartada
"Logi C270" nomini ko'rib unga "Yuz tekshiruvi" ni beradi — aslida
esa o'sha kartaning ostida boshqa qurilmaning indeksi turibdi.
Tanlov ishlaydi, lekin NOM YOLG'ON, ya'ni tanlovning yagona
mo'ljali ishonchsiz. `discovery._apply_names` bu xavfni sonlar mos
kelmaganda nomni umuman bermaslik bilan yumshatardi — lekin sonlar
TASODIFAN mos kelganda (aynan ikkita kamerali mashinada odatiy hol)
xato nom baribir ekranga chiqardi.

Yechim: qurilmalarni OpenCV'ning O'ZI ishlatadigan manbadan sanash.
`CAP_DSHOW` backend'i DirectShow'ning tizim qurilma sanagichidan
(`CLSID_SystemDeviceEnum` + `CLSID_VideoInputDeviceCategory`)
foydalanadi va indeksni AYNAN shu ro'yxatdagi tartib bo'yicha
beradi. Shu ro'yxatni o'zimiz o'qisak, nom va indeks o'rtasidagi
bog'liqlik taxmin emas, FAKT bo'ladi.

YANGI BOG'LIQLIK YO'Q. `pygrabber` xuddi shu ishni qiladi, lekin u
`comtypes` ni tortib keladi va ikkalasi ham PyInstaller bundle'ida
qo'shimcha muammo (`comtypes` ish vaqtida kod generatsiya qiladi).
Bu yerda COM chaqiruvlari `ctypes` bilan qo'lda yozilgan — kerakli
uchta interfeysdan atigi to'rtta metod ishlatiladi.

`DevicePath` ham o'qiladi: u qurilmaning BARQAROR identifikatori
(USB VID/PID + instansiya) va indeksdan farqli ravishda boshqa
kamera ulanganda siljimaydi — operator tanlovi shunga bog'lanadi.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import POINTER, byref, c_void_p
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    _ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    _oleaut32 = ctypes.WinDLL("oleaut32", use_last_error=True)
else:  # pragma: no cover - loyiha Windows uchun
    _ole32 = _oleaut32 = None


@dataclass(frozen=True)
class DshowDevice:
    """DirectShow ro'yxatidagi bitta qurilma."""

    #: OpenCV `VideoCapture(index, CAP_DSHOW)` uchun indeks.
    index: int
    name: str = ""
    #: `\\?\usb#vid_046d&pid_0825...` — qurilmaning barqaror kaliti.
    #: Virtual kameralarda bo'sh bo'lishi mumkin: ular fizik qurilma
    #: emas, registrda ro'yxatdan o'tgan filtr.
    device_path: str = ""


# --------------------------------------------------------------------------
# COM qobig'i
# --------------------------------------------------------------------------
class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _VARIANT(ctypes.Structure):
    """
    `VARIANT` ning bizga yetarli qismi.

    To'liq tuzilma union'lar bilan o'nlab maydondan iborat, bizga esa
    faqat `vt` (tur) va birinchi ko'rsatkich (BSTR) kerak. Ikkita
    ko'rsatkichli "quyruq" union'ning to'liq o'lchamini qoplaydi
    (x64 da 16 bayt, x86 da 8) — `VariantClear` tuzilmani o'zining
    haqiqiy o'lchamida kutadi va kichikroq bufer stekni buzardi.
    """

    _fields_ = [
        ("vt", ctypes.c_ushort),
        ("reserved1", ctypes.c_ushort),
        ("reserved2", ctypes.c_ushort),
        ("reserved3", ctypes.c_ushort),
        ("value", c_void_p),
        ("tail", c_void_p),
    ]


_VT_BSTR = 8
_S_OK = 0
_CLSCTX_INPROC_SERVER = 1
_COINIT_APARTMENTTHREADED = 0x2

#: COM shu thread'da allaqachon ishga tushirilgan (`S_FALSE`).
#:
#: Boshqa qiymat — odatda `RPC_E_CHANGED_MODE`: jarayonda COM
#: boshqa rejimda ishga tushirilgan. Ikkalasi ham xato emas, lekin
#: farqi bor: birinchisida `CoUninitialize` biznikidir, ikkinchisida
#: yo'q (pastdagi `own_com` ga qarang).
_S_FALSE = 1


def _guid(text: str) -> _GUID:
    value = _GUID()
    if _ole32 is not None:
        _ole32.CLSIDFromString(text, byref(value))
    return value


def _vcall(pointer: c_void_p, index: int, *argtypes):
    """
    COM interfeysining `index` - metodini chaqiradigan funksiya.

    `restype` HAR DOIM `c_long` (HRESULT) va ATAYLAB `ctypes.HRESULT`
    EMAS: ikkinchisi muvaffaqiyatsiz kodda istisno tashlaydi, bizda
    esa "muvaffaqiyatsiz" odatiy javob (ro'yxat tugadi, xususiyat
    yo'q). `argtypes` ham majburiy — usiz ctypes ko'rsatkichlarni
    32-bitli `int` deb uzatadi va chaqiruv 64-bitli tizimda
    `OverflowError` bilan yiqiladi.
    """
    vtable = ctypes.cast(pointer, POINTER(POINTER(c_void_p)))[0]
    prototype = ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, *argtypes)
    return prototype(vtable[index])


def _release(pointer: c_void_p) -> None:
    if pointer:
        _vcall(pointer, 2)(pointer)


def _read_string(property_bag: c_void_p, key: str) -> str:
    """`IPropertyBag::Read` — satr xususiyati (bo'lmasa bo'sh satr)."""
    variant = _VARIANT()
    _oleaut32.VariantInit(byref(variant))
    read = _vcall(property_bag, 3, ctypes.c_wchar_p, POINTER(_VARIANT), c_void_p)
    try:
        if read(property_bag, key, byref(variant), None) != _S_OK:
            return ""
        if variant.vt != _VT_BSTR or not variant.value:
            return ""
        return ctypes.cast(c_void_p(variant.value), ctypes.c_wchar_p).value or ""
    finally:
        _oleaut32.VariantClear(byref(variant))


def _setup_prototypes() -> None:
    """
    `argtypes` / `restype` — MAJBURIY, ixtiyoriy emas.

    Loyihada bu xato allaqachon uchragan (`threat_scanner._stop_service`,
    `CLAUDE.md` tuzoqlari): usiz ctypes ko'rsatkichni C `int` deb
    uzatadi va 64-bitli tizimda chaqiruv jimgina buziladi.
    """
    _ole32.CLSIDFromString.argtypes = [ctypes.c_wchar_p, POINTER(_GUID)]
    _ole32.CLSIDFromString.restype = ctypes.c_long
    _ole32.CoInitializeEx.argtypes = [c_void_p, ctypes.c_ulong]
    _ole32.CoInitializeEx.restype = ctypes.c_long
    _ole32.CoUninitialize.argtypes = []
    _ole32.CoUninitialize.restype = None
    _ole32.CoCreateInstance.argtypes = [
        POINTER(_GUID), c_void_p, ctypes.c_ulong, POINTER(_GUID), POINTER(c_void_p)
    ]
    _ole32.CoCreateInstance.restype = ctypes.c_long
    _oleaut32.VariantInit.argtypes = [POINTER(_VARIANT)]
    _oleaut32.VariantInit.restype = None
    _oleaut32.VariantClear.argtypes = [POINTER(_VARIANT)]
    _oleaut32.VariantClear.restype = ctypes.c_long


if _IS_WINDOWS:
    _setup_prototypes()
    _CLSID_SystemDeviceEnum = _guid("{62BE5D10-60EB-11d0-BD3B-00A0C911CE86}")
    _IID_ICreateDevEnum = _guid("{29840822-5B84-11D0-BD3B-00A0C911CE86}")
    _CLSID_VideoInputDeviceCategory = _guid("{860BB310-5D01-11d0-BD3B-00A0C911CE86}")
    _IID_IPropertyBag = _guid("{55272A00-42CB-11CE-8135-00AA004BB851}")


# --------------------------------------------------------------------------
def enumerate_devices() -> list[DshowDevice]:
    """
    DirectShow video kirish qurilmalari — OpenCV tartibida.

    Bo'sh ro'yxat IKKI ma'noni bildiradi: qurilma yo'q yoki COM
    chaqiruvi ishlamadi. Ikkalasida ham chaqiruvchi eski yo'lga
    (PnP nomlari) tushadi, shuning uchun ularni ajratishning
    ma'nosi yo'q — sabab log'da qoladi. Farq kerak bo'lsa —
    `enumerate_devices_strict`.
    """
    if not _IS_WINDOWS:
        return []
    try:
        return _enumerate() or []
    except Exception:
        log.warning("DirectShow qurilmalarini sanab bo'lmadi", exc_info=True)
        return []


def enumerate_devices_strict() -> Optional[list[DshowDevice]]:
    """
    `enumerate_devices` ning ANIQ shakli: `None` — sanab bo'lmadi,
    `[]` — kamera haqiqatan yo'q (kategoriya bo'sh).

    "Kamera uzildimi" savoli uchun (`WebcamSource.is_present`): COM
    xatosini "uzildi" deb o'qish ishlab turgan kamerani har tekshiruvda
    yopib-ochardi.
    """
    if not _IS_WINDOWS:
        return None
    try:
        return _enumerate()
    except Exception:
        log.debug("DirectShow qurilmalarini sanab bo'lmadi", exc_info=True)
        return None


def _enumerate() -> Optional[list[DshowDevice]]:
    initialized = _ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    # `RPC_E_CHANGED_MODE` — jarayonda COM boshqa rejimda ishga
    # tushirilgan (Qt buni qiladi). Bu XATO EMAS: sanash baribir
    # ishlaydi, faqat `CoUninitialize` chaqirilmasligi kerak —
    # aks holda biz ochmagan apartamentni yopib qo'yardik.
    own_com = initialized in (_S_OK, _S_FALSE)
    try:
        device_enum = c_void_p()
        if _ole32.CoCreateInstance(
            byref(_CLSID_SystemDeviceEnum), None, _CLSCTX_INPROC_SERVER,
            byref(_IID_ICreateDevEnum), byref(device_enum),
        ) != _S_OK or not device_enum:
            return None
        try:
            return _enumerate_category(device_enum)
        finally:
            _release(device_enum)
    finally:
        if own_com:
            _ole32.CoUninitialize()


def _enumerate_category(device_enum: c_void_p) -> Optional[list[DshowDevice]]:
    moniker_enum = c_void_p()
    create = _vcall(
        device_enum, 3, POINTER(_GUID), POINTER(c_void_p), ctypes.c_ulong
    )
    # `S_FALSE` — kategoriya bo'sh (kamera umuman yo'q) va
    # ko'rsatkich `NULL` bo'lib qoladi. Boshqa kod - xato (`None`).
    result = create(
        device_enum, byref(_CLSID_VideoInputDeviceCategory), byref(moniker_enum), 0
    )
    if result == _S_FALSE:
        return []
    if result != _S_OK or not moniker_enum:
        return None

    devices: list[DshowDevice] = []
    try:
        next_moniker = _vcall(
            moniker_enum, 3, ctypes.c_ulong, POINTER(c_void_p), POINTER(ctypes.c_ulong)
        )
        index = 0
        while True:
            moniker = c_void_p()
            fetched = ctypes.c_ulong(0)
            if next_moniker(moniker_enum, 1, byref(moniker), byref(fetched)) != _S_OK:
                break
            if not moniker:
                break
            try:
                devices.append(_read_device(moniker, index))
            finally:
                _release(moniker)
            index += 1
    finally:
        _release(moniker_enum)
    return devices


def _read_device(moniker: c_void_p, index: int) -> DshowDevice:
    """`IMoniker::BindToStorage` -> `IPropertyBag` -> nom va yo'l."""
    property_bag = c_void_p()
    # 9 - `IMoniker` vtable'idagi `BindToStorage`: IUnknown (3) +
    # IPersist (1) + IPersistStream (4) + BindToObject (1).
    bind = _vcall(moniker, 9, c_void_p, c_void_p, POINTER(_GUID), POINTER(c_void_p))
    if bind(moniker, None, None, byref(_IID_IPropertyBag), byref(property_bag)) != _S_OK:
        return DshowDevice(index=index)
    try:
        return DshowDevice(
            index=index,
            name=_read_string(property_bag, "FriendlyName"),
            device_path=_read_string(property_bag, "DevicePath"),
        )
    finally:
        _release(property_bag)
