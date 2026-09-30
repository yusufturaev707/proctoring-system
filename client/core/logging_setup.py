"""
Log sozlamasi.

Frozen rejimda konsol yo'q (`console=False`), ya'ni traceback hech qayerda
ko'rinmaydi. Shuning uchun barcha xatolar faylga yoziladi va
`sys.excepthook` ham shu yerga ulanadi — aks holda dastur "sababsiz"
yopilgandek tuyuladi. Ilgaklarning o'zi `core/crash_guard.py` da.

Asosiy log JOYIDA qoldi (`%APPDATA%\\ProctoringClient\\proctoring-client.log`):
uning manzili o'rnatuvchi hujjatida yozilgan va qo'llab-quvvatlash
xodimlari uni shu yerdan oladi. Yangi fayllar (native crash, watchdog)
`%LOCALAPPDATA%\\ProctoringClient\\logs` da (`bundle_paths.logs_root`).
"""

from __future__ import annotations

import logging
import sys
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

from core.bundle_paths import writable_root
from core.log_redaction import RedactingFormatter

_LOG_NAME = "proctoring-client.log"
_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def _file_handler(log_file: Path) -> "logging.Handler | None":
    """
    Aylanuvchi fayl handler'i - ochilmasa `None`, XATO KO'TARMAYDI.

    Ilgari bu yerdagi `OSError` (disk to'la, profil katalogi faqat
    o'qish uchun, antivirus faylni qulflagan) dasturni oyna ochilmasdan
    yiqitardi - modul importida, ya'ni hech qanday xabar ko'rsatib
    bo'lmaydigan joyda.
    """
    try:
        # Rotatsiya: imtihon kuni client 8+ soat ishlaydi va hodisa log'i
        # tez o'sadi. Cheklovsiz fayl diskni to'ldirishi mumkin.
        #
        # `delay=True` EMAS: fayl ochilishi SHU YERDA tekshirilishi kerak,
        # aks holda xato birinchi yozuvda - istalgan joyda chiqardi.
        return RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
    except OSError:
        return None


def setup_logging(level: int = logging.INFO) -> "logging.Logger":
    log_file = writable_root() / _LOG_NAME
    handlers: list[logging.Handler] = []
    fallback_note = ""
    handler = _file_handler(log_file)
    if handler is None:
        # Zaxira: %TEMP%. Log umuman bo'lmasa, imtihon kuni nima
        # bo'lganini tiklab bo'lmaydi.
        fallback = Path(tempfile.gettempdir()) / _LOG_NAME
        handler = _file_handler(fallback)
        fallback_note = " (asosiy joyga yozib bo'lmadi: {})".format(log_file)
        log_file = fallback
    if handler is not None:
        handlers.append(handler)
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))
    if not handlers:
        handlers.append(logging.NullHandler())

    # Maxfiy qiymatlar (token, parol, JSHSHIR) HAR handler'da
    # niqoblanadi - `core/log_redaction.py`.
    formatter = RedactingFormatter(_FORMAT)
    for item in handlers:
        item.setFormatter(formatter)

    logging.basicConfig(level=level, handlers=handlers, force=True)
    # Log yozuvidagi xato (disk to'la, rotatsiyada fayl band) dasturni
    # to'xtatmasligi kerak: `handleError` stderr'ga yozishga urinadi,
    # frozen rejimda esa u yo'q.
    logging.raiseExceptions = False

    from core import crash_guard

    crash_guard.install_python_hooks()

    log = logging.getLogger("client")
    log.info("=== Proctoring client ishga tushdi — log: %s%s", log_file, fallback_note)
    return log
