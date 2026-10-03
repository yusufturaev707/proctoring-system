"""
Administrator huquqi: oddiy ishga tushirilgan nusxa o'zini avtostart
vazifasi orqali QAYTA ochadi.

NIMA UCHUN KERAK. Tozalash (`services/threat_scanner.py`) SYSTEM nomidan
ishlaydigan masofaviy boshqaruv xizmatlarini (`chromoting`, AnyDesk
xizmati) faqat administrator huquqida to'xtata oladi. O'rnatuvchi
administrator bo'lgani yetmaydi: huquq har JARAYONGA alohida beriladi va
yorliq, "o'rnatishdan keyin ishga tushirish" belgisi yoki `.exe` ni ikki
marta bosish dasturni foydalanuvchining CHEKLANGAN tokeni bilan ochadi.

NIMA UCHUN VAZIFA, MANIFEST EMAS. `uac_admin=True` (requireAdministrator)
har ishga tushishda UAC oynasini chiqarardi va kioskni to'xtatardi,
oddiy hisobda esa administrator parolini so'rardi. O'rnatuvchi yaratgan
`ProctoringClient` vazifasi `RunLevel Highest` bilan (`installer/
autostart.ps1`) administrator hisobida UAC'siz to'liq token beradi -
`schtasks /Run` uni istalgan payt ishga tushiradi.

QACHON QAYTA OCHILADI - hammasi bajarilishi shart (`should_relaunch`):

  * frozen (o'rnatilgan) dastur - dev'da vazifa boshqa `.exe` ni ochardi;
  * buyruq qatorida argument yo'q - watchdog qayta ko'targan nusxa
    (`--restart-count` ...) o'z bayroqlarini yo'qotmasligi kerak;
  * token CHEKLANGAN (`TokenElevationTypeLimited`) - ya'ni foydalanuvchi
    administrator, lekin UAC tokeni bo'lingan. Oddiy hisobda (`Default`)
    vazifa ham oddiy huquq beradi: qayta ochish hech narsa bermas edi va
    cheksiz tsikl xavfini tug'dirardi. Vazifa ochgan nusxa `Full` -
    u qayta ochmaydi, tsikl shu yerda uziladi;
  * vazifa mavjud va AYNAN SHU `.exe` ni ochadi - build mashinasidagi
    `dist\\` nusxasi o'rnatilgan dasturni ochib yubormasligi kerak.

YIQILISH XAVFSIZ: har qanday xato yoki vazifa ochilmasa (15 s ichida
yangi nusxa mutex'ni egallamasa) dastur oddiy huquqda DAVOM ETADI -
self-check `not_elevated` ni ko'rsatadi, tahdid skaneri esa yopib
bo'lmaganini to'siq qiladi. Dastur hech qachon "ochilmay" qolmasligi kerak.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import time

log = logging.getLogger(__name__)

TASK_NAME = "ProctoringClient"

#: Vazifa ochgan nusxa mutex'ni egallashini kutish (s). Onedir'da
#: `main()` gacha ~1-3 s; sekin HDD'li mashinaga zaxira bilan.
WAIT_SECONDS = 15.0
_POLL_SECONDS = 0.2

# TOKEN_ELEVATION_TYPE
ELEVATION_DEFAULT = 1
ELEVATION_FULL = 2
ELEVATION_LIMITED = 3

_TOKEN_QUERY = 0x0008
_TOKEN_ELEVATION_TYPE_CLASS = 18
_CREATE_NO_WINDOW = 0x08000000
_SCHTASKS_TIMEOUT = 10

_COMMAND_RE = re.compile(r"<Command>\s*(.*?)\s*</Command>", re.IGNORECASE | re.DOTALL)


def should_relaunch(*, frozen: bool, argv: list, elevation_type: int, task_command: str, exe: str) -> bool:
    """Sof qaror (testlanadi) - shartlar modul docstring'ida."""
    if not frozen or len(argv) > 1:
        return False
    if elevation_type != ELEVATION_LIMITED:
        return False
    if not task_command or not exe:
        return False
    return _same_path(task_command, exe)


def _same_path(left: str, right: str) -> bool:
    def norm(path: str) -> str:
        path = os.path.expandvars(path.strip().strip('"'))
        return os.path.normcase(os.path.abspath(path))

    return norm(left) == norm(right)


def elevation_type() -> int:
    """Joriy jarayon tokenining turi; aniqlab bo'lmasa `0`."""
    if sys.platform != "win32":
        return 0
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        advapi32.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
        advapi32.OpenProcessToken.restype = wintypes.BOOL
        advapi32.GetTokenInformation.argtypes = (
            wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
        )
        advapi32.GetTokenInformation.restype = wintypes.BOOL

        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)):
            return 0
        try:
            value = wintypes.DWORD()
            size = wintypes.DWORD()
            if not advapi32.GetTokenInformation(
                token, _TOKEN_ELEVATION_TYPE_CLASS, ctypes.byref(value), ctypes.sizeof(value), ctypes.byref(size)
            ):
                return 0
            return int(value.value)
        finally:
            kernel32.CloseHandle(token)
    except Exception:  # noqa: BLE001
        log.debug("Token turini aniqlab bo'lmadi", exc_info=True)
        return 0


def _schtasks(*args: str) -> subprocess.CompletedProcess:
    # CREATE_NO_WINDOW: GUI dasturdan chaqirilgan konsol utilitasi
    # aks holda qora oynani miltillatardi.
    return subprocess.run(
        [os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "schtasks.exe"), *args],
        capture_output=True,
        timeout=_SCHTASKS_TIMEOUT,
        creationflags=_CREATE_NO_WINDOW,
    )


def _decode(data: bytes) -> str:
    # `/XML` chiqishi konsol kodlashida yoki UTF-16 da kelishi mumkin.
    if data[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" in data[:200]:
        return data.decode("utf-16", errors="replace")
    return data.decode("mbcs" if sys.platform == "win32" else "utf-8", errors="replace")


def _output_text(result) -> str:
    parts = [chunk for chunk in (result.stderr, result.stdout) if isinstance(chunk, bytes)]
    return _decode(b"".join(parts)).strip()[:200]


def task_command(name: str = TASK_NAME) -> str:
    """Vazifa ochadigan `.exe`; vazifa yo'q yoki o'qib bo'lmasa - bo'sh satr."""
    try:
        result = _schtasks("/Query", "/TN", name, "/XML")
    except Exception:  # noqa: BLE001
        log.debug("Vazifa so'rovi ishlamadi", exc_info=True)
        return ""
    if result.returncode != 0:
        return ""
    match = _COMMAND_RE.search(_decode(result.stdout))
    return match.group(1) if match else ""


def relaunch_via_task(release_mutex, mutex_held, reacquire_mutex) -> bool:
    """
    `True` - administrator nusxasi ishga tushdi, bu nusxa CHIQISHI kerak.

    Chaqiruvchi mutex'ni allaqachon egallagan (`main()` ning birinchi
    qadami - boshqa nusxa ishlayotgan bo'lsa bu yerga kelinmaydi). Tartib:
    mutex bo'shatiladi -> `schtasks /Run` -> yangi nusxa mutex'ni
    egallashi kutiladi. `Local\\` mutex SEANS bo'yicha, ya'ni "egallandi"
    yangi nusxa AYNAN SHU seansda ochilganini ham tasdiqlaydi (vazifa
    guruhga biriktirilgan). Kutish tugasa mutex qaytarib olinadi va
    `False` - oddiy huquqda davom etiladi.
    """
    exe = sys.executable
    try:
        level = elevation_type()
        command = task_command() if level == ELEVATION_LIMITED else ""
        if not should_relaunch(
            frozen=bool(getattr(sys, "frozen", False)),
            argv=list(sys.argv),
            elevation_type=level,
            task_command=command,
            exe=exe,
        ):
            if level == ELEVATION_LIMITED:
                log.info("Administrator huquqisiz ishga tushdi; vazifa orqali qayta ochilmaydi (vazifa: %s)",
                         command or "yo'q")
            return False

        release_mutex()
        result = _schtasks("/Run", "/TN", TASK_NAME)
        if result.returncode != 0:
            # Sabab matni MAJBURIY: kod 1 "Access is denied" (vazifaga
            # GRGX ruxsati yo'q - eski o'rnatuvchi, `autostart.ps1`) ham,
            # boshqa xato ham bo'lishi mumkin.
            log.warning(
                "Vazifa ishga tushmadi (kod %s: %s) - oddiy huquqda davom etamiz",
                result.returncode,
                _output_text(result) or "-",
            )
            return _resume(reacquire_mutex)

        deadline = time.monotonic() + WAIT_SECONDS
        while time.monotonic() < deadline:
            if mutex_held():
                log.info("Administrator huquqi bilan qayta ochildi (vazifa %s) - bu nusxa yopiladi", TASK_NAME)
                return True
            time.sleep(_POLL_SECONDS)

        log.warning("Vazifa %.0f s ichida dasturni ochmadi - oddiy huquqda davom etamiz", WAIT_SECONDS)
        return _resume(reacquire_mutex)
    except Exception:  # noqa: BLE001
        log.warning("Administrator huquqi bilan qayta ochib bo'lmadi", exc_info=True)
        return _resume(reacquire_mutex)


def _resume(reacquire_mutex) -> bool:
    """
    Mutex'ni qaytarib oladi. Olib bo'lmasa - kechikib ochilgan yangi
    nusxa uni egallagan: o'sha ishlaydi, bu nusxa chiqadi (`True`).
    """
    try:
        return not reacquire_mutex()
    except Exception:  # noqa: BLE001
        log.debug("Mutex qaytarib olinmadi", exc_info=True)
        return False
