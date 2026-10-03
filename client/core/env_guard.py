"""
O'rnatilgan dasturda jarayon muhiti (environment) — ISHONCHSIZ manba.

NIMA UCHUN. Client Task Scheduler orqali foydalanuvchi nomidan
(administrator hisobida — yuqori huquq bilan) ishga tushadi va
foydalanuvchining SHAXSIY muhit o'zgaruvchilarini (`HKCU\\Environment`)
meros qilib oladi. Ularni istalgan talabgor `setx` bilan yoza oladi —
administrator huquqisiz va bir marta yozilsa keyingi har kirishda
amal qiladi. Ilgari bu uch yo'l bilan kiosk himoyasini ochardi:

  * `setx KIOSK_MODE 0` — `.env` da yozilmagan har kalit muhitdan
    o'qilardi (`override=True` faqat faylda BOR kalitlarga ta'sir qiladi);
  * `setx PROCTORING_ENV_FILE ...` — administrator faylini butunlay
    o'zinikiga almashtirardi;
  * kutubxonalarning o'z o'zgaruvchilari: `QTWEBENGINE_CHROMIUM_FLAGS`
    (`--ignore-certificate-errors`, `--proxy-server`),
    `QTWEBENGINE_REMOTE_DEBUGGING=0.0.0.0:9222` (tarmoqdagi sherik test
    sahifasini DevTools orqali boshqaradi), `SSL_CERT_FILE` (httpx o'z
    CA ro'yxati sifatida o'qiydi — API trafigini MITM qilish).

QOIDA (faqat frozen; dev'da muhit odatdagidek ishlaydi):

  * sozlama (`config`) faqat ADMINISTRATOR FAYLIDAN (`.env`) va kod
    standartidan — `config_source`;
  * kutubxonalar o'qiydigan xavfli o'zgaruvchilar Qt/httpx yuklanishidan
    OLDIN o'chiriladi — `sanitize_process_env`. `.env` da yozilgani esa
    keyin `load_dotenv` bilan QAYTA qo'yiladi: administrator ataylab
    bergan qiymat (masalan korporativ CA) ishlayveradi;
  * `PROCTORING_ENV_FILE` faqat MASHINA darajasida (HKLM, administrator)
    berilgan bo'lsa — `machine_env`;
  * tizim yo'llari (`ProgramData`, `SystemRoot`...) Windows API'dan
    olingan HAQIQIY qiymatga qaytariladi: foydalanuvchi o'zgaruvchisi
    shu nomdagi tizim o'zgaruvchisini soyalaydi, `setx ProgramData ...`
    esa `.env` qidiriladigan katalogni (`bundle_paths.machine_config_root`)
    talabgorning papkasiga burardi, `setx SystemRoot ...` — tahdid
    skaneri "tizim fayli" deb imzosini o'qimaydigan joyni.

Modul hech narsa import qilmaydi (`winreg` dan tashqari, dangasa):
u `main.py` ning eng boshida, log va Qt'dan oldin chaqiriladi.
"""

from __future__ import annotations

import os
import sys
from typing import Mapping, MutableMapping, Optional

#: Shu prefiksli hamma o'zgaruvchi o'chiriladi. Qt va Chromium ularni
#: hujjatlashtirilgan sozlama sifatida o'qiydi; client ularning
#: birortasini ham ishlatmaydi (`QT_PLUGIN_PATH` va `QML2_IMPORT_PATH`
#: ni PyInstaller runtime hook'i baribir qayta yozadi). `CUDA_PATH*` —
#: `cuda_runtime` u yerdagi DLL'larni YUKLAYDI (begona kod client
#: jarayonida); o'rnatilgan dastur CUDA'ni o'z `_internal/cuda` sidan oladi.
UNTRUSTED_PREFIXES = ("QTWEBENGINE", "QT_QPA_", "CUDA_PATH")

#: Aniq nomlar. `INSIGHTFACE_ROOT` — model qayerdan yuklanishi
#: (`main.py` uni o'chirilgandan keyin bundle'ga qaratadi).
UNTRUSTED_NAMES = frozenset({
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "INSIGHTFACE_ROOT",
})

_MACHINE_ENV_KEY = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def is_untrusted(name: str) -> bool:
    upper = name.upper()
    return upper in UNTRUSTED_NAMES or upper.startswith(UNTRUSTED_PREFIXES)


def sanitize_process_env(
    environ: Optional[MutableMapping[str, str]] = None,
    *,
    frozen: Optional[bool] = None,
    system_dirs: Optional[Mapping[str, str]] = None,
) -> list[str]:
    """
    Xavfli o'zgaruvchilarni o'chiradi, tizim yo'llarini tiklaydi va
    o'zgargan NOMLARNI qaytaradi.

    Qiymatlar qaytarilmaydi va log'ga yozilmaydi: ularda yo'l yoki
    manzil bo'lishi mumkin, chaqiruvchiga esa "nima e'tiborsiz qoldi"
    degan savolga javob kifoya. Dev rejimda hech narsa qilinmaydi.
    `system_dirs` — testlar uchun (standart: `trusted_system_dirs()`).
    """
    if environ is None:
        environ = os.environ
    if not (_frozen() if frozen is None else frozen):
        return []
    changed = [name for name in list(environ) if is_untrusted(name)]
    for name in changed:
        environ.pop(name, None)

    # `os.environ` Windows'da nom registriga befarq, oddiy lug'at emas.
    current = {name.upper(): name for name in environ}
    trusted = trusted_system_dirs() if system_dirs is None else system_dirs
    for name, value in trusted.items():
        existing = current.get(name.upper())
        if existing is not None and os.path.normcase(environ[existing]) == os.path.normcase(value):
            continue
        if existing is not None:
            environ.pop(existing, None)
            changed.append(name)
        environ[name] = value
    return sorted(set(changed))


def trusted_system_dirs() -> dict:
    """
    Tizim kataloglari — muhitdan EMAS, Windows API'dan.

    `GetSystemWindowsDirectoryW` va `SHGetKnownFolderPath` qiymati
    foydalanuvchi o'zgaruvchilariga bog'liq emas. Aniqlab bo'lmagani
    lug'atga kirmaydi (va muhitdagi qiymat o'z holicha qoladi): buzilgan
    API'da ishga tushishni to'xtatish tozalashdan ko'ra yomonroq.
    """
    if sys.platform != "win32":
        return {}
    import ctypes
    import uuid
    from ctypes import wintypes

    result: dict = {}
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetSystemWindowsDirectoryW.argtypes = [wintypes.LPWSTR, wintypes.UINT]
        kernel32.GetSystemWindowsDirectoryW.restype = wintypes.UINT
        buffer = ctypes.create_unicode_buffer(wintypes.MAX_PATH + 1)
        length = kernel32.GetSystemWindowsDirectoryW(buffer, len(buffer))
        if 0 < length < len(buffer):
            result["SystemRoot"] = buffer.value
            result["windir"] = buffer.value
    except (OSError, AttributeError):
        pass

    try:
        class _GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8),
            ]

        folder = _GUID.from_buffer_copy(
            uuid.UUID("62AB5D82-FDC1-4DC3-A9DD-070D1D495D97").bytes_le  # FOLDERID_ProgramData
        )
        shell32 = ctypes.WinDLL("shell32")
        ole32 = ctypes.WinDLL("ole32")
        shell32.SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(_GUID), wintypes.DWORD, wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        shell32.SHGetKnownFolderPath.restype = ctypes.c_long
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        ole32.CoTaskMemFree.restype = None
        path = ctypes.c_wchar_p()
        if shell32.SHGetKnownFolderPath(ctypes.byref(folder), 0, None, ctypes.byref(path)) == 0:
            try:
                if path.value:
                    result["ProgramData"] = path.value
                    result["ALLUSERSPROFILE"] = path.value
            finally:
                ole32.CoTaskMemFree(ctypes.cast(path, ctypes.c_void_p))
    except (OSError, AttributeError, ValueError):
        pass
    return result


def config_source(
    file_values: Mapping[str, Optional[str]],
    environ: Mapping[str, str],
    *,
    frozen: bool,
) -> Mapping[str, str]:
    """
    `config` sozlamalarini qayerdan o'qishi.

    Frozen — FAQAT fayl (qiymatsiz kalit, `KEY` yolg'iz, tashlanadi).
    Dev — jarayon muhiti (unga `.env` `override=False` bilan yuklangan:
    terminaldagi `set X=...` fayldan ustun).
    """
    if frozen:
        return {key: value for key, value in file_values.items() if value is not None}
    return environ


def machine_env(name: str) -> Optional[str]:
    """
    MASHINA darajasidagi muhit o'zgaruvchisi (HKLM) yoki `None`.

    U yerga faqat administrator yoza oladi. Foydalanuvchi darajasidagi
    (`HKCU\\Environment`) shu nomli qiymat ATAYLAB qaralmaydi.

    `REG_EXPAND_SZ` da faqat `%ProgramData%` ochiladi va u ham
    `trusted_system_dirs` dan: `os.path.expandvars` foydalanuvchi
    o'zgaruvchilarini qo'yib, administrator yozgan yo'lni yana
    talabgor boshqaradigan joyga burardi. Boshqa `%...%` qolsa — `None`.
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _MACHINE_ENV_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    if not isinstance(value, str):
        return None
    return expand_machine_value(value, trusted_system_dirs())


def expand_machine_value(value: str, system_dirs: Mapping[str, str]) -> Optional[str]:
    """`%ProgramData%` ni ishonchli qiymat bilan ochadi; boshqa `%...%` — `None`."""
    value = (value or "").strip()
    program_data = system_dirs.get("ProgramData")
    if program_data:
        lower = value.lower()
        token = "%programdata%"
        while token in lower:
            index = lower.index(token)
            value = value[:index] + program_data + value[index + len(token):]
            lower = value.lower()
    if "%" in value:
        return None
    return value or None
