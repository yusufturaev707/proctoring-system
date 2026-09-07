"""
PyInstaller bundle uchun xavfsiz fayl yo'llari.

Frozen (.exe) rejimda asset'lar boshqa katalogda yotadi:
  --onedir  : sys._MEIPASS = <exe>/_internal/
  --onefile : sys._MEIPASS = %TEMP%/_MEIxxxx/  (har ishga tushishda yangi)

Shuning uchun O'QISH (`resource_root`) va YOZISH (`writable_root`)
kataloglari ATAYLAB ajratilgan: onefile rejimda resource katalogi
vaqtinchalik va unga yozilgan narsa dastur yopilishi bilan yo'qoladi.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "ProctoringClient"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """Read-only asset'lar (InsightFace modellari, ikonkalar) ildizi."""
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        return Path(meipass) if meipass else Path(sys.executable).parent
    # Dev rejim: core/ ning ota katalogi = client ildizi
    return Path(__file__).resolve().parent.parent


def resource_path(relative: str | Path = "") -> Path:
    return resource_root() / relative


def writable_root() -> Path:
    """
    Log, kesh va qurilma identifikatori saqlanadigan katalog.

    %APPDATA%/ProctoringClient — frozen va dev rejimda BIR XIL. Bu muhim:
    dev rejimda yaratilgan `device_id` .exe ga o'tganda ham topiladi,
    ya'ni qurilma qayta ro'yxatdan o'tishi shart emas.
    """
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    root = Path(base) / APP_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root
