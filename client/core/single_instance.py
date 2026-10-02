"""
Bitta nusxa: Windows nomli mutex.

FAQAT ASOSIY UI rejimi egallaydi - `--keyboard-hook` va `--watchdog`
jarayonlari bu yerga kelmaydi (`main.py` ularni undan OLDIN ajratadi).

NIMA UCHUN KERAK. Ikkinchi nusxa (operator ikki marta bosdi, avtostart +
qo'lda ishga tushirish, watchdog qayta ko'targan paytda eski nusxa hali
yopilmagan) `main()` dagi tozalash bosqichlarini ham bajarardi:
`app_closer` BIRINCHI nusxaning oynasini "begona dastur" deb yopishi,
ikkala nusxa bitta kamera va bitta lokal port (8050) uchun kurashishi
mumkin edi.

`Local\\` - SEANS bo'yicha. Operator va talabgor boshqa-boshqa Windows
hisobida bo'lsa, har seans o'z client'iga ega bo'la oladi (tezkor
foydalanuvchi almashtirish); bitta seans ichida esa faqat bitta.

`ERROR_ACCESS_DENIED` ham "band" deb hisoblanadi: yuqori huquqli
(Task Scheduler, `RunLevel Highest`) nusxa yaratgan mutexni oddiy
huquqli ikkinchi nusxa ocha olmaydi - bu aynan "boshqa nusxa ishlayapti"
degani.

Deskriptor JARAYON OXIRIGACHA ochiq turadi (modul o'zgaruvchisi) va
meros qilinmaydi (`bInheritHandle=False`) - klaviatura qulfi va watchdog
bolalari uni ushlab qolmaydi, ya'ni UI o'lsa mutex darhol bo'shaydi va
qayta ishga tushirilgan nusxa uni egallay oladi.
"""

from __future__ import annotations

import logging
import sys

log = logging.getLogger(__name__)

MUTEX_NAME = "Local\\ProctoringClient.SingleInstance"

_ERROR_ALREADY_EXISTS = 183
_ERROR_ACCESS_DENIED = 5

_handle = None


def acquire(name: str = MUTEX_NAME) -> bool:
    """
    `True` - biz yagona nusxamiz (yoki tekshirib bo'lmadi).

    Tekshiruvning o'zi ishlamasa (`kernel32` yo'q, kutilmagan xato)
    `True` qaytadi: bitta nusxa - qulaylik, uning nosozligi dasturni
    ishga tushirmaslik uchun sabab emas.
    """
    global _handle
    if _handle is not None:
        return True
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel32.CreateMutexW
        create.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        create.restype = wintypes.HANDLE
        close = kernel32.CloseHandle
        close.argtypes = (wintypes.HANDLE,)
        close.restype = wintypes.BOOL

        handle = create(None, False, name)
        error = ctypes.get_last_error()
        if not handle:
            if error == _ERROR_ACCESS_DENIED:
                return False
            log.warning("Mutex yaratilmadi (xato %s) - tekshiruvsiz davom etamiz", error)
            return True
        if error == _ERROR_ALREADY_EXISTS:
            close(handle)
            return False
        _handle = handle
        return True
    except Exception:  # noqa: BLE001
        log.warning("Bitta nusxa tekshiruvi ishlamadi", exc_info=True)
        return True


#: Ikkinchi nusxalarning "kuting" xabari bir vaqtda BITTA bo'lsin.
NOTICE_MUTEX_NAME = "Local\\ProctoringClient.StartingNotice"

#: Xabar o'zi yopiladi (ms): ikkinchi nusxa baribir chiqib ketadi va
#: ekranda egasiz oyna qolmasligi kerak.
NOTICE_TIMEOUT_MS = 4000

STARTING_TEXT = (
    "Dastur allaqachon ishga tushmoqda.\n\n"
    "Iltimos, kuting — oyna bir necha soniyada ochiladi. "
    "Belgini qayta bosish shart emas."
)

_SW_RESTORE = 9
_MB_ICONINFORMATION = 0x40
_MB_SETFOREGROUND = 0x10000
_MB_TOPMOST = 0x40000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def notify_running(app_name: str) -> str:
    """
    Ikkinchi nusxa: foydalanuvchiga JAVOB beradi, keyin chiqib ketadi.

    NIMA UCHUN. Birinchi nusxa oynani bir necha soniyadan keyin ko'rsatadi
    (monitorlar, boshqa dasturlarni yopish, tahdid skaneri, og'ir
    modullar). Ikkinchi nusxa JIMGINA yopilganda xodim "ochilmadi" deb
    belgini qayta-qayta bosardi. Endi:

      * birinchi nusxaning oynasi BOR - u oldinga chiqariladi
        (`"activated"`);
      * hali yo'q (yuklanmoqda) - "kuting" xabari, o'zi yopiladi
        (`"notice"`). O'nta bosish - bitta xabar (`NOTICE_MUTEX_NAME`);
      * boshqa hollarda - hech narsa (`"none"`).

    XATO YUTILADI: bu qulaylik, ikkinchi nusxa baribir yopiladi.
    """
    if sys.platform != "win32":
        return "none"
    try:
        hwnd = _find_main_window(app_name)
        if hwnd:
            _activate(hwnd)
            return "activated"
        return "notice" if _show_starting_notice(app_name) else "none"
    except Exception:  # noqa: BLE001
        log.debug("Ikkinchi nusxa xabari ko'rsatilmadi", exc_info=True)
        return "none"


def _user32():
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.EnumWindows.argtypes = (ctypes.c_void_p, wintypes.LPARAM)
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.IsIconic.argtypes = (wintypes.HWND,)
    user32.IsIconic.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    user32.SetForegroundWindow.restype = wintypes.BOOL
    return user32


def _process_image(pid: int) -> str:
    """Jarayonning exe fayl nomi (kichik harf) yoki bo'sh satr."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
    )
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return buffer.value.replace("/", "\\").rsplit("\\", 1)[-1].lower()
    finally:
        kernel32.CloseHandle(handle)


def _find_main_window(app_name: str) -> int:
    """
    Birinchi nusxaning ko'rinadigan asosiy oynasi (HWND) yoki 0.

    Sarlavha BILAN BIRGA jarayon exe'si ham solishtiriladi: sarlavha
    ("ProctoringClient") boshqa dasturda ham bo'lishi mumkin va begona
    oynani oldinga chiqarish chalg'itardi.
    """
    import ctypes
    import os
    from ctypes import wintypes

    user32 = _user32()
    own_pid = os.getpid()
    own_image = os.path.basename(sys.executable).lower()
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, 256)
        if title.value != app_name:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value and pid.value != own_pid and _process_image(pid.value) == own_image:
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(callback, 0)
    return found[0] if found else 0


def _activate(hwnd: int) -> None:
    user32 = _user32()
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, _SW_RESTORE)
    # Ikkinchi nusxa foydalanuvchi bosgani uchun HOZIR oldingi planda -
    # Windows unga boshqa oynani oldinga chiqarishga ruxsat beradi.
    user32.SetForegroundWindow(hwnd)


def _show_starting_notice(app_name: str) -> bool:
    """
    "Kuting" xabari, o'zi yopiladi. `False` - boshqa nusxa allaqachon
    ko'rsatib turibdi (yoki Windows funksiyasi yo'q).

    `MessageBoxTimeoutW` - hujjatlanmagan, lekin XP'dan beri user32 da
    bor. Yo'q bo'lsa xabar KO'RSATILMAYDI: oddiy `MessageBoxW` o'zi
    yopilmaydi va ekranda egasiz modal qoldirardi.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    show = getattr(user32, "MessageBoxTimeoutW", None)
    if show is None:
        return False
    show.argtypes = (
        wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT, wintypes.WORD,
        wintypes.DWORD,
    )
    show.restype = ctypes.c_int

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    notice = kernel32.CreateMutexW(None, False, NOTICE_MUTEX_NAME)
    already = ctypes.get_last_error() == _ERROR_ALREADY_EXISTS
    try:
        if not notice or already:
            return False
        show(
            None, STARTING_TEXT, app_name,
            _MB_ICONINFORMATION | _MB_TOPMOST | _MB_SETFOREGROUND, 0, NOTICE_TIMEOUT_MS,
        )
        return True
    finally:
        if notice:
            kernel32.CloseHandle(notice)
