"""
Log sozlamasi.

Frozen rejimda konsol yo'q (`console=False`), ya'ni traceback hech qayerda
ko'rinmaydi. Shuning uchun barcha xatolar faylga yoziladi va
`sys.excepthook` ham shu yerga ulanadi — aks holda dastur "sababsiz"
yopilgandek tuyuladi.
"""

from __future__ import annotations

import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler

from core.bundle_paths import writable_root

_LOG_NAME = "proctoring-client.log"


def setup_logging(level: int = logging.INFO) -> "logging.Logger":
    log_file = writable_root() / _LOG_NAME
    handlers: list[logging.Handler] = [
        # Rotatsiya: imtihon kuni client 8+ soat ishlaydi va hodisa log'i
        # tez o'sadi. Cheklovsiz fayl diskni to'ldirishi mumkin.
        RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"),
    ]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )

    def _excepthook(exc_type, exc_value, exc_tb):
        logging.error(
            "Qo'lga olinmagan xato:\n%s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )

    sys.excepthook = _excepthook
    log = logging.getLogger("client")
    log.info("=== Proctoring client ishga tushdi — log: %s", log_file)
    return log
