"""
"Bu jarayon ASLIDA kim?" — nomga tayanmaydigan identifikatsiya.

Butun tozalash qatlami shu modul ustida turadi va sabab bitta: FAYL
NOMI HIMOYA EMAS. `AnyDesk.exe` ni `svchost_helper.exe` deb qayta
nomlash bir soniyalik ish va nom bo'yicha qidiradigan har qanday
ro'yxat shu bilan bekor bo'ladi. Shuning uchun bu yerda faylning
O'ZIDAN, uni qayta nomlash o'zgartirmaydigan uchta manbadan o'qiymiz:

  1. PE RESURSI (`VS_VERSION_INFO`) — `OriginalFilename`, `ProductName`,
     `CompanyName`, `FileDescription`, `InternalName`. Kompilyatsiya
     paytida yoziladi; faylni qayta nomlash unga tegmaydi. Eng arzon
     (~0.3 ms) va eng foydali belgi.
  2. AUTHENTICODE IMZOSI — sertifikat egasining nomi. Qayta nomlash
     imzoni buzmaydi, resursni tahrirlash esa BUZADI: ya'ni resursni
     tozalagan odam imzoni ham yo'qotadi va "imzosiz + masofaviy
     boshqaruv porti" degan alohida belgiga tushadi.
  3. Diskdagi YO'L — faqat kontekst uchun (`C:\\Windows` ichidagi
     binarni imzo bo'yicha tekshirishning ma'nosi yo'q).

IMZO TEKSHIRILMAYDI, FAQAT O'QILADI va bu ataylab. Bizning savolimiz
"bu imzo ishonchlimi?" emas, "bu faylni kim imzolagan deb da'vo
qilinyapti?". O'zini "AnyDesk Software GmbH" deb imzolagan soxta
sertifikat ham bizga KERAKLI javobni beradi — biz uni baribir
tutamiz. Zanjirni tekshirish (`WinVerifyTrust`) har fayl uchun
CRL/OCSP so'rovi degani: tarmoqqa bog'liq, sekin va imtihon
mashinasida ko'pincha timeout bilan tugaydi.

`pywin32` ATAYLAB ishlatilmaydi — `app_closer.py` dagi bilan bir xil
sabab: PyInstaller bundle'iga sezilarli hajm qo'shadi, bizga esa
bor-yo'g'i bir nechta funksiya kerak.

QIMMAT QISM KECHIKTIRILADI. Imzoni o'qish ~2-10 ms va uni 300 ta
jarayon uchun har skanerda bajarish imtihon davomidagi tsiklni
o'ldirardi. Shuning uchun `identity()` standart holatda FAQAT resursni
o'qiydi; imzo `with_signature=True` bilan va faqat arzon belgilar
javob bermagan fayllar uchun so'raladi (`threat_scanner` shunday
chaqiradi).
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

#: Resurs va imzo keshi: `(yo'l, mtime, hajm) -> BinaryIdentity`.
#
# Kalitga mtime va hajm KIRADI: dastur yangilanishi mumkin va eski
# keshdagi javob o'shanda yolg'on bo'lib qolardi.
_CACHE: dict = {}

#: Keshning yuqori chegarasi. Imtihon mashinasida noyob binarlar soni
#: yuzdan oshmaydi; chegara faqat cheksiz o'sishdan himoya.
_CACHE_LIMIT = 1024


@dataclass
class BinaryIdentity:
    """Bitta `.exe` faylning o'zi haqida aytgani."""

    path: str = ""
    #: Diskdagi haqiqiy nom (qayta nomlangan bo'lishi MUMKIN).
    filename: str = ""
    #: PE resursidan — qayta nomlash TEGMAYDI.
    original_filename: str = ""
    product: str = ""
    company: str = ""
    description: str = ""
    internal_name: str = ""
    #: Sertifikat egasi. Bo'sh: imzosiz, yoki hali so'ralmagan.
    signer: str = ""
    #: Imzo o'qishga URINILDIMI (bo'sh `signer` ikki ma'noli).
    signature_checked: bool = False

    @property
    def haystack(self) -> str:
        """
        Qism satr bo'yicha qidiriladigan barcha matnlar — bitta satrda.

        Fayl nomi bu yerga KIRMAYDI: u qoidalarda alohida (`names`)
        va ataylab eng oxirgi o'rinda turadi.
        """
        return " | ".join(
            part
            for part in (
                self.original_filename,
                self.product,
                self.company,
                self.description,
                self.internal_name,
                self.signer,
            )
            if part
        ).lower()

    def summary(self) -> str:
        """Jurnal uchun qisqa satr — operator nimani ko'rganini tushunsin."""
        bits = [self.filename or "?"]
        if self.original_filename and self.original_filename.lower() != self.filename.lower():
            # AYNAN SHU HOLAT eng qiziq: fayl qayta nomlangan.
            bits.append("orig={}".format(self.original_filename))
        if self.product:
            bits.append("product={}".format(self.product))
        if self.signer:
            bits.append("signer={}".format(self.signer))
        return " ".join(bits)


# --------------------------------------------------------------------------
# PE resursi
# --------------------------------------------------------------------------
def _version_strings(path: str) -> dict:
    """
    `VS_VERSION_INFO` dagi satrlar. Xato TASHLAMAYDI — bo'sh lug'at qaytadi.

    Resursi yo'q fayl (Go/Rust bilan yig'ilgan portativ binar) normal
    hol: o'shanda qoida boshqa belgilarga tushadi.
    """
    if sys.platform != "win32" or not path:
        return {}

    import ctypes
    from ctypes import wintypes

    try:
        version = ctypes.WinDLL("version", use_last_error=True)
    except OSError:
        return {}

    version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    version.GetFileVersionInfoW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID
    ]
    version.GetFileVersionInfoW.restype = wintypes.BOOL
    version.VerQueryValueW.argtypes = [
        wintypes.LPVOID, wintypes.LPCWSTR,
        ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.UINT),
    ]
    version.VerQueryValueW.restype = wintypes.BOOL

    handle = wintypes.DWORD(0)
    size = version.GetFileVersionInfoSizeW(path, ctypes.byref(handle))
    if not size:
        return {}

    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(path, 0, size, buffer):
        return {}

    # TIL VA KOD SAHIFASI FAYLDAN OLINADI, qadab qo'yilmaydi. Ko'p
    # dasturlar `040904b2` (US English / Unicode) ishlatadi, lekin
    # rus yoki xitoy lokalizatsiyasidagi binar boshqa juftlik beradi
    # va qadab qo'yilgan qiymat bilan resurs BO'SH ko'rinardi.
    pointer = wintypes.LPVOID()
    length = wintypes.UINT()
    translations = []
    if version.VerQueryValueW(
        buffer, "\\VarFileInfo\\Translation", ctypes.byref(pointer), ctypes.byref(length)
    ) and length.value >= 4:
        count = length.value // 4
        words = ctypes.cast(pointer, ctypes.POINTER(wintypes.WORD * (count * 2))).contents
        translations = [(words[index * 2], words[index * 2 + 1]) for index in range(count)]
    if not translations:
        translations = [(0x0409, 0x04B2), (0x0000, 0x04B0)]

    wanted = (
        "OriginalFilename", "ProductName", "CompanyName",
        "FileDescription", "InternalName",
    )
    result: dict = {}
    for lang, codepage in translations:
        for name in wanted:
            if result.get(name):
                continue
            query = "\\StringFileInfo\\{:04x}{:04x}\\{}".format(lang, codepage, name)
            value = wintypes.LPVOID()
            chars = wintypes.UINT()
            if not version.VerQueryValueW(
                buffer, query, ctypes.byref(value), ctypes.byref(chars)
            ):
                continue
            if not chars.value:
                continue
            text = ctypes.wstring_at(value, chars.value).strip("\x00 \t")
            if text:
                result[name] = text
        if len(result) == len(wanted):
            break
    return result


# --------------------------------------------------------------------------
# Authenticode
# --------------------------------------------------------------------------
_CERT_QUERY_OBJECT_FILE = 0x00000001
#: `CERT_QUERY_CONTENT_FLAG_PKCS7_SIGNED_EMBED` — PE ichiga joylashgan imzo.
_CERT_QUERY_CONTENT_FLAG_PKCS7_SIGNED_EMBED = 1 << 10
_CERT_QUERY_FORMAT_FLAG_BINARY = 1 << 1
_CMSG_SIGNER_INFO_PARAM = 6
#: `CERT_COMPARE_SUBJECT_CERT << CERT_COMPARE_SHIFT`
_CERT_FIND_SUBJECT_CERT = 11 << 16
_CERT_NAME_SIMPLE_DISPLAY_TYPE = 4
_ENCODING = 0x00000001 | 0x00010000  # X509_ASN | PKCS_7_ASN


def _crypt_structs():
    """
    `crypt32` uchun struktura ta'riflari.

    `CERT_INFO` TO'LIQ tavsiflanishi SHART, garchi bizga faqat ikkita
    maydon (`Issuer`, `SerialNumber`) kerak bo'lsa ham: `crypt32` uni
    bizning xotiramizdan o'qiydi va maydon SURILMALARI aniq mos
    kelishi kerak. Qisqartirilgan struktura jimgina noto'g'ri
    sertifikat qaytarardi yoki jarayonni qulatardi.
    """
    import ctypes
    from ctypes import wintypes

    class CRYPT_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    class CRYPT_ALGORITHM_IDENTIFIER(ctypes.Structure):
        _fields_ = [("pszObjId", ctypes.c_char_p), ("Parameters", CRYPT_BLOB)]

    class CRYPT_BIT_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
            ("cUnusedBits", wintypes.DWORD),
        ]

    class CERT_PUBLIC_KEY_INFO(ctypes.Structure):
        _fields_ = [("Algorithm", CRYPT_ALGORITHM_IDENTIFIER), ("PublicKey", CRYPT_BIT_BLOB)]

    class CRYPT_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("cAttr", wintypes.DWORD), ("rgAttr", ctypes.c_void_p)]

    class CMSG_SIGNER_INFO(ctypes.Structure):
        _fields_ = [
            ("dwVersion", wintypes.DWORD),
            ("Issuer", CRYPT_BLOB),
            ("SerialNumber", CRYPT_BLOB),
            ("HashAlgorithm", CRYPT_ALGORITHM_IDENTIFIER),
            ("HashEncryptionAlgorithm", CRYPT_ALGORITHM_IDENTIFIER),
            ("EncryptedHash", CRYPT_BLOB),
            ("AuthAttrs", CRYPT_ATTRIBUTES),
            ("UnauthAttrs", CRYPT_ATTRIBUTES),
        ]

    class CERT_INFO(ctypes.Structure):
        _fields_ = [
            ("dwVersion", wintypes.DWORD),
            ("SerialNumber", CRYPT_BLOB),
            ("SignatureAlgorithm", CRYPT_ALGORITHM_IDENTIFIER),
            ("Issuer", CRYPT_BLOB),
            ("NotBefore", wintypes.FILETIME),
            ("NotAfter", wintypes.FILETIME),
            ("Subject", CRYPT_BLOB),
            ("SubjectPublicKeyInfo", CERT_PUBLIC_KEY_INFO),
            ("IssuerUniqueId", CRYPT_BIT_BLOB),
            ("SubjectUniqueId", CRYPT_BIT_BLOB),
            ("cExtension", wintypes.DWORD),
            ("rgExtension", ctypes.c_void_p),
        ]

    return CMSG_SIGNER_INFO, CERT_INFO


def signer_name(path: str) -> str:
    """
    Faylni imzolagan tashkilot nomi. Imzosiz bo'lsa — bo'sh satr.

    Zanjir TEKSHIRILMAYDI (modul docstring'iga qarang): bizga "kim
    imzolagan" kerak, "ishonchlimi" emas.

    FAQAT PE ICHIGA JOYLASHGAN (embedded) IMZO o'qiladi. Windows
    tizim binarlari KATALOG bilan imzolanadi (`.cat` fayllari) va bu
    funksiya ular uchun bo'sh satr qaytaradi. Bu bizga xalaqit
    bermaydi va ataylab shunday qoldirilgan: nishonlarimiz —
    uchinchi tomon o'rnatuvchilari (AnyDesk, TeamViewer, RustDesk,
    VirtualBox) va ularning hammasi embedded imzo ishlatadi. Katalog
    imzosini o'qish `WinVerifyTrust` + katalog bazasini talab
    qiladi: sezilarli sekinroq va faqat Microsoft binarlarini
    tasdiqlash uchun foydali bo'lardi.
    """
    if sys.platform != "win32" or not path or not os.path.isfile(path):
        return ""

    import ctypes
    from ctypes import wintypes

    try:
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    except OSError:
        return ""

    CMSG_SIGNER_INFO, CERT_INFO = _crypt_structs()

    crypt32.CryptQueryObject.restype = wintypes.BOOL
    crypt32.CryptMsgGetParam.restype = wintypes.BOOL
    crypt32.CertFindCertificateInStore.restype = ctypes.c_void_p
    crypt32.CertGetNameStringW.restype = wintypes.DWORD
    crypt32.CertFreeCertificateContext.restype = wintypes.BOOL
    crypt32.CertCloseStore.restype = wintypes.BOOL
    crypt32.CryptMsgClose.restype = wintypes.BOOL

    store = ctypes.c_void_p()
    message = ctypes.c_void_p()
    encoding = wintypes.DWORD()
    content = wintypes.DWORD()
    form = wintypes.DWORD()

    ok = crypt32.CryptQueryObject(
        _CERT_QUERY_OBJECT_FILE,
        ctypes.c_wchar_p(path),
        _CERT_QUERY_CONTENT_FLAG_PKCS7_SIGNED_EMBED,
        _CERT_QUERY_FORMAT_FLAG_BINARY,
        0,
        ctypes.byref(encoding),
        ctypes.byref(content),
        ctypes.byref(form),
        ctypes.byref(store),
        ctypes.byref(message),
        None,
    )
    if not ok:
        # Imzosiz fayl — KUTILGAN holat, xato emas.
        return ""

    certificate = None
    try:
        size = wintypes.DWORD()
        if not crypt32.CryptMsgGetParam(
            message, _CMSG_SIGNER_INFO_PARAM, 0, None, ctypes.byref(size)
        ):
            return ""
        blob = ctypes.create_string_buffer(size.value)
        if not crypt32.CryptMsgGetParam(
            message, _CMSG_SIGNER_INFO_PARAM, 0, blob, ctypes.byref(size)
        ):
            return ""

        signer = ctypes.cast(blob, ctypes.POINTER(CMSG_SIGNER_INFO)).contents
        # Imzolovchini sertifikatlar ombordan `Issuer` + `SerialNumber`
        # juftligi bo'yicha topamiz — PKCS#7 da imzo aynan shu juftlik
        # orqali sertifikatga bog'lanadi.
        wanted = CERT_INFO()
        wanted.Issuer = signer.Issuer
        wanted.SerialNumber = signer.SerialNumber

        certificate = crypt32.CertFindCertificateInStore(
            store, _ENCODING, 0, _CERT_FIND_SUBJECT_CERT, ctypes.byref(wanted), None
        )
        if not certificate:
            return ""

        length = crypt32.CertGetNameStringW(
            ctypes.c_void_p(certificate), _CERT_NAME_SIMPLE_DISPLAY_TYPE, 0, None, None, 0
        )
        if length <= 1:
            return ""
        name = ctypes.create_unicode_buffer(length)
        crypt32.CertGetNameStringW(
            ctypes.c_void_p(certificate), _CERT_NAME_SIMPLE_DISPLAY_TYPE, 0, None, name, length
        )
        return (name.value or "").strip()
    except Exception:
        log.debug("Imzoni o'qib bo'lmadi: %s", path, exc_info=True)
        return ""
    finally:
        # Tartib muhim: avval sertifikat, keyin ombor va xabar.
        try:
            if certificate:
                crypt32.CertFreeCertificateContext(ctypes.c_void_p(certificate))
            if store:
                crypt32.CertCloseStore(store, 0)
            if message:
                crypt32.CryptMsgClose(message)
        except Exception:
            log.debug("crypt32 deskriptorlarini yopishda xato", exc_info=True)


def _strip_mui(value: str) -> str:
    """
    `NOTEPAD.EXE.MUI` -> `NOTEPAD.EXE`.

    Windows LOKALIZATSIYALANGAN tizim binarlarining satr resurslarini
    yonidagi `.mui` yo'ldosh faylida saqlaydi va `GetFileVersionInfoW`
    o'sha faylga JIMGINA yo'naltiriladi. Natijada `mstsc.exe` uchun
    `OriginalFilename` qiymati `mstsc.exe.mui` bo'lib chiqadi.

    Buni tuzatmaslik ikkita jimgina xatoga olib kelardi: tizim
    katalogidagi nishon (`mstsc.exe`) qoidaga hech qachon mos
    kelmasdi, va har bir tizim binari "qayta nomlangan" deb
    ko'rinardi (diskdagi nom `.mui` bilan tugamaydi).

    Uchinchi tomon dasturlari (AnyDesk, TeamViewer) MUI ishlatmaydi —
    ularda bu funksiya hech narsani o'zgartirmaydi.
    """
    text = (value or "").strip()
    return text[:-4] if text.lower().endswith(".mui") else text


# --------------------------------------------------------------------------
def identity(path: str, *, with_signature: bool = False) -> BinaryIdentity:
    """
    Fayl haqidagi to'plangan ma'lumot (keshlanadi).

    `with_signature=False` (standart) — faqat PE resursi, ~0.3 ms.
    `with_signature=True` — imzo ham, ~2-10 ms. Skaner uni faqat arzon
    belgilar hech narsa aytmagan fayllar uchun so'raydi.
    """
    if not path:
        return BinaryIdentity()

    try:
        stat = os.stat(path)
        key = (path.lower(), int(stat.st_mtime), stat.st_size)
    except OSError:
        # Fayl o'chirilgan yoki o'qib bo'lmaydi — keshsiz, nomdan
        # tashqari hech narsasiz qaytamiz.
        return BinaryIdentity(path=path, filename=os.path.basename(path))

    cached = _CACHE.get(key)
    if cached is not None and (cached.signature_checked or not with_signature):
        return cached

    if cached is not None:
        info = cached
    else:
        strings = _version_strings(path)
        info = BinaryIdentity(
            path=path,
            filename=os.path.basename(path),
            original_filename=_strip_mui(strings.get("OriginalFilename", "")),
            product=strings.get("ProductName", ""),
            company=strings.get("CompanyName", ""),
            description=strings.get("FileDescription", ""),
            internal_name=strings.get("InternalName", ""),
        )

    if with_signature and not info.signature_checked:
        info.signer = signer_name(path)
        info.signature_checked = True

    if len(_CACHE) >= _CACHE_LIMIT:
        _CACHE.clear()
    _CACHE[key] = info
    return info


# --------------------------------------------------------------------------
# Muhit haqidagi savollar
# --------------------------------------------------------------------------
def is_elevated() -> bool:
    """
    Dastur administrator huquqi bilan ishlayaptimi.

    Xizmatlarni to'xtatish va boshqa hisob jarayonlarini o'ldirish
    AYNAN shunga bog'liq. Huquq yo'qligi nosozlik EMAS — hisobotda
    "to'xtatib bo'lmadi" deb qoladi va operator ko'radi.
    """
    if sys.platform != "win32":
        return False
    import ctypes

    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        log.debug("Huquq darajasini aniqlab bo'lmadi", exc_info=True)
        return False


def in_remote_session() -> bool:
    """
    Dastur MASOFAVIY seansda ishlayaptimi (RDP, Terminal Services).

    Bu jarayon qidiruvidan MUSTAQIL va undan kuchliroq belgi: bu yerda
    "masofaviy boshqaruv dasturi o'rnatilgan" emas, "mashinani HOZIR
    kimdir masofadan boshqaryapti" degan javob olinadi. `mstsc.exe`
    ni qayta nomlash ham, uni butunlay boshqa client bilan
    almashtirish ham bu bayroqqa ta'sir qilmaydi — uni Windows
    seansning o'zi haqida aytadi.
    """
    if sys.platform != "win32":
        return False
    import ctypes

    try:
        # SM_REMOTESESSION
        return bool(ctypes.windll.user32.GetSystemMetrics(0x1000))
    except Exception:
        log.debug("Seans turini aniqlab bo'lmadi", exc_info=True)
        return False


#: BIOS satrlarida uchraydigan virtualizatsiya belgilari.
_VM_MARKERS = (
    "vmware", "virtualbox", "innotek", "qemu", "bochs", "xen",
    "parallels", "kvm", "virtual machine", "hyper-v", "bhyve",
)

#: Qisqa belgilar FAQAT butun so'z sifatida: satr 7 maydondan yig'iladi
#: va substring "xen"/"kvm" boshqa so'z ichida tasodifan uchrashi mumkin -
#: haqiqiy mashinada soxta "virtual mashina" to'sig'i butun imtihonni
#: to'xtatardi.
_VM_WORD_MARKERS = frozenset({"xen", "kvm", "qemu", "bochs", "bhyve"})

#: O'qiladigan BIOS maydonlari (`HKLM\HARDWARE\DESCRIPTION\System\BIOS`).
#: Ilgari to'rttasi o'qilardi; Hyper-V belgisi ("Hyper-V UEFI Release
#: v4.1") esa aynan `BIOSVersion` da, ba'zi gipervizorlar faqat
#: `SystemFamily` / `BaseBoardProduct` ni to'ldiradi.
_VM_BIOS_FIELDS = (
    "SystemManufacturer", "SystemProductName", "SystemFamily",
    "BIOSVendor", "BIOSVersion", "BaseBoardManufacturer", "BaseBoardProduct",
)


def detect_vm_marker(values) -> str:
    """
    BIOS satrlaridan virtualizatsiya belgisi (sof funksiya, testda).

    `values` - `{maydon: qiymat}`. Qaytadi: `"hyper-v (BIOSVersion)"`
    ko'rinishidagi satr yoki bo'sh. Maydon nomi dalil uchun: operator
    "nega VM deyapti?" deb so'raganda javob shu yerda.
    """
    import re

    for field_name in _VM_BIOS_FIELDS:
        text = str((values or {}).get(field_name) or "").lower()
        if not text:
            continue
        for marker in _VM_MARKERS:
            if marker in _VM_WORD_MARKERS:
                found = re.search(r"(?<![a-z0-9]){}(?![a-z0-9])".format(re.escape(marker)), text)
            else:
                found = marker in text
            if found:
                return "{} ({})".format(marker, field_name)
    return ""


def host_virtualization() -> str:
    """
    Mashinaning O'ZI virtual bo'lsa — belgining nomi, aks holda bo'sh satr.

    `threat_rules` dagi qoidalar "mashinada virtual mashina ISHLAYAPTI"
    holatini tutadi; bu esa teskarisini — "client virtual mashinaning
    ICHIDA ishlayapti". Ikkalasi butunlay boshqa hujum: ikkinchisida
    talabgor butun imtihon muhitini bir oynaga qamab, yonida haqiqiy
    ish stolini ochiq qoldiradi va bizning kiosk rejimimiz unga
    umuman ta'sir qilmaydi.

    Manba — registrdagi BIOS satrlari. WMI ATAYLAB ishlatilmaydi: u
    COM'ni ko'taradi, sekin (~200 ms) va xizmat o'chirilgan
    mashinalarda umuman javob bermaydi.
    """
    if sys.platform != "win32":
        return ""
    try:
        import winreg
    except ImportError:
        return ""

    values = {}
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS"
        ) as key:
            for name in _VM_BIOS_FIELDS:
                try:
                    values[name] = str(winreg.QueryValueEx(key, name)[0] or "")
                except OSError:
                    continue
    except OSError:
        log.debug("BIOS registrini o'qib bo'lmadi", exc_info=True)
        return ""
    return detect_vm_marker(values)


# --------------------------------------------------------------------------
# Boshqa (begona) RDP seanslari - Terminal Services API
# --------------------------------------------------------------------------
#
# `in_remote_session()` faqat O'Z seansimizni so'raydi. U yetmaydigan
# holat: mashinada BIR VAQTDA ikkinchi seans (Windows Server, RDPWrap
# patch'i) - yordamchi alohida RDP seansdan `mstsc /shadow` bilan
# talabgorning konsol seansini ko'radi va boshqaradi. Talabgor seansi
# o'shanda ham "lokal" va `SM_REMOTESESSION` jim. `WTSEnumerateSessions`
# esa Task Manager "Users" tab'i va `query session` ko'radigan ro'yxatni
# beradi - administrator huquqi shart emas, ~1 ms.

_WTS_CURRENT_SERVER = None
_WTS_ACTIVE = 0
_WTS_SHADOW = 3
_WTS_USER_NAME = 5
_WTS_DOMAIN_NAME = 7
_WTS_CLIENT_NAME = 10
_WTS_CLIENT_ADDRESS = 14
_WTS_CLIENT_PROTOCOL = 16
_PROTOCOL_RDP = 2


@dataclass
class RdpSession:
    """Mashinadagi begona faol RDP seansi."""

    session_id: int
    user: str = ""
    client_name: str = ""
    client_address: str = ""

    def describe(self) -> str:
        who = self.user or "noma'lum foydalanuvchi"
        source = " ".join(part for part in (self.client_name, self.client_address) if part)
        return "seans #{} - {}{}".format(
            self.session_id, who, " ({})".format(source) if source else ""
        )


def _wts_api():
    """`wtsapi32` funksiyalari - `argtypes` bilan (`CLAUDE.md`: ctypes tuzog'i)."""
    import ctypes
    from ctypes import wintypes

    class _SessionInfo(ctypes.Structure):
        _fields_ = [
            ("SessionId", wintypes.DWORD),
            ("pWinStationName", wintypes.LPWSTR),
            ("State", ctypes.c_int),
        ]

    wts = ctypes.WinDLL("wtsapi32", use_last_error=True)
    wts.WTSEnumerateSessionsW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_SessionInfo)), ctypes.POINTER(wintypes.DWORD),
    ]
    wts.WTSEnumerateSessionsW.restype = wintypes.BOOL
    wts.WTSQuerySessionInformationW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.c_int,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD),
    ]
    wts.WTSQuerySessionInformationW.restype = wintypes.BOOL
    wts.WTSFreeMemory.argtypes = [ctypes.c_void_p]
    wts.WTSFreeMemory.restype = None
    wts.WTSLogoffSession.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL]
    wts.WTSLogoffSession.restype = wintypes.BOOL
    return wts, _SessionInfo


def _own_session_id() -> int:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel32.ProcessIdToSessionId.restype = wintypes.BOOL
    session = wintypes.DWORD(0)
    if not kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session)):
        return -1
    return int(session.value)


def _query(wts, session_id: int, info_class: int):
    """Xom bufer (`bytes`) yoki `None`. Xotira HAR DOIM bo'shatiladi."""
    import ctypes
    from ctypes import wintypes

    buffer = ctypes.c_void_p()
    size = wintypes.DWORD(0)
    if not wts.WTSQuerySessionInformationW(
        _WTS_CURRENT_SERVER, session_id, info_class, ctypes.byref(buffer), ctypes.byref(size)
    ):
        return None
    try:
        if not buffer.value or not size.value:
            return b""
        return ctypes.string_at(buffer.value, size.value)
    finally:
        wts.WTSFreeMemory(buffer)


def _text(raw) -> str:
    if not raw:
        return ""
    return raw.decode("utf-16-le", errors="replace").split("\x00", 1)[0].strip()


def _client_ip(raw) -> str:
    """`WTS_CLIENT_ADDRESS`: DWORD oila + 20 bayt; IPv4 manzil 2..6 da."""
    if not raw or len(raw) < 10:
        return ""
    family = int.from_bytes(raw[0:4], "little")
    if family == 2:  # AF_INET
        return ".".join(str(byte) for byte in raw[6:10])
    return ""


def foreign_rdp_sessions() -> list:
    """
    Mashinadagi BOSHQA faol RDP seanslari (o'zimiznikidan tashqari).

    Faqat protokoli RDP (2) va holati faol/soya bo'lgan seanslar:
    konsol (0) - jismonan o'tirgan odam, uzilgan (`Disconnected`) seans
    - hozir hech kim ulanmagan. O'z seansimiz bu yerga KIRMAYDI: u
    masofaviy bo'lsa `in_remote_session()` aytadi va uni uzish
    talabgorning o'zini chiqarib yuborish bo'lardi.

    Xato (API yo'q, huquq) - bo'sh ro'yxat: aniqlash imtihonning sharti
    emas, u qo'shimcha qatlam.
    """
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    try:
        wts, session_info = _wts_api()
    except OSError:
        log.debug("wtsapi32 yuklanmadi", exc_info=True)
        return []

    own = _own_session_id()
    entries = ctypes.POINTER(session_info)()
    count = wintypes.DWORD(0)
    if not wts.WTSEnumerateSessionsW(
        _WTS_CURRENT_SERVER, 0, 1, ctypes.byref(entries), ctypes.byref(count)
    ):
        log.debug("WTSEnumerateSessions xatosi: %s", ctypes.get_last_error())
        return []

    sessions = []
    try:
        for index in range(count.value):
            entry = entries[index]
            session_id = int(entry.SessionId)
            if session_id in (0, own) or entry.State not in (_WTS_ACTIVE, _WTS_SHADOW):
                continue
            protocol = _query(wts, session_id, _WTS_CLIENT_PROTOCOL)
            if not protocol or int.from_bytes(protocol[:2], "little") != _PROTOCOL_RDP:
                continue
            user = _text(_query(wts, session_id, _WTS_USER_NAME))
            domain = _text(_query(wts, session_id, _WTS_DOMAIN_NAME))
            sessions.append(
                RdpSession(
                    session_id=session_id,
                    user="{}\\{}".format(domain, user) if domain and user else user,
                    client_name=_text(_query(wts, session_id, _WTS_CLIENT_NAME)),
                    client_address=_client_ip(_query(wts, session_id, _WTS_CLIENT_ADDRESS)),
                )
            )
    finally:
        wts.WTSFreeMemory(entries)
    return sessions


def logoff_session(session_id: int) -> tuple:
    """
    Seansni YAKUNLAYDI (logoff). Qaytadi: `(muvaffaqiyat, sabab)`.

    `WTSDisconnectSession` EMAS: uzilgan seans tirik qoladi va yordamchi
    bir soniyada qayta ulanadi. Logoff administrator huquqini talab
    qiladi (boshqa foydalanuvchining seansi) - huquq yetmasa sabab
    qaytadi va skaner imtihonni to'sadi.

    O'z seansimizni HECH QACHON yakunlamaydi (himoya chaqiruvchi xatosiga
    qarshi ham).
    """
    if sys.platform != "win32":
        return False, "faqat Windows"
    import ctypes

    if session_id in (0, _own_session_id()):
        return False, "o'z seansimiz yoki xizmat seansi"
    try:
        wts, _ = _wts_api()
    except OSError as exc:
        return False, str(exc)[:120]
    if wts.WTSLogoffSession(_WTS_CURRENT_SERVER, int(session_id), False):
        return True, ""
    error = ctypes.get_last_error()
    if error == 5:  # ERROR_ACCESS_DENIED
        return False, "huquq yetmadi (administrator kerak)"
    return False, "WTSLogoffSession xatosi {}".format(error)
