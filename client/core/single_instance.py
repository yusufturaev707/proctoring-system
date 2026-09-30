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
