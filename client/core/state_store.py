"""
Ish holati fayli: `%LOCALAPPDATA%\\ProctoringClient\\state.json`.

Kutilmagan yopilishdan keyin "qayerda edik?" degan savolga javob. FAQAT
MAXFIY BO'LMAGAN qiymatlar - `ALLOWED_KEYS` oq ro'yxati. JWT, sessiya
tokeni, JSHSHIR, talabgor ismi, `test_link` HECH QACHON yozilmaydi:
fayl diskda shifrsiz yotadi va talabgor ham o'qiy oladi. Ro'yxatdan
tashqari kalit JIMGINA emas, WARNING bilan tashlanadi - dasturchi xatosi
darhol ko'rinsin.

YOZISH ATOMIK: vaqtinchalik fayl + `fsync` + `os.replace`. Quvvat
uzilganda ham fayl yo eski, yo yangi holatda qoladi - yarim yozilgan
JSON "oldingi sessiya" haqida yolg'on gapirardi.

DISK TO'LA (`ENOSPC`) yoki ruxsat yo'q - XATO KO'TARILMAYDI: holat
xotirada qoladi, log'ga BIR MARTA yoziladi. Holat fayli - qulaylik,
imtihonning sharti emas.

Faylga ikki jarayon tegadi: UI yozadi, watchdog faqat O'QIYDI (toza
chiqish belgisi). Atomik almashtirish tufayli o'quvchi hech qachon
yarim faylni ko'rmaydi.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

STATE_FILE_NAME = "state.json"
SCHEMA_VERSION = 1

#: Ruxsat etilgan kalitlar va ularning ma'nosi.
ALLOWED_KEYS = {
    "schema": "fayl sxemasi versiyasi",
    "app_version": "dastur versiyasi",
    "pid": "joriy UI jarayoni",
    "started_at": "jarayon boshlangan vaqt (unix)",
    "updated_at": "oxirgi yozuv (unix)",
    "stage": "oqim bosqichi (preflight/login/exam_select/candidate/faceid/exam)",
    "exam_id": "tanlangan imtihon id",
    "exam_name": "imtihon nomi (maxfiy emas, ekranda ko'rinadi)",
    "schedule_id": "test sessiyasi (ExamSchedule) id",
    "session_public_id": "ochiq ExamSession public_id",
    "session_started_at": "imtihon oynasi ochilgan vaqt (unix)",
    "clean_exit": "toza chiqish belgisi (parol bilan / OS seansi)",
    "exit_reason": "chiqish sababi (qisqa matn)",
    "restart_count": "watchdog qayta ishga tushirgan marta",
    "restarted_at": "oxirgi qayta ishga tushirish (unix)",
    "previous_crash": "oldingi jarayon kutilmaganda tugagan: {pid, stage, at}",
}

#: Oqim bosqichlari - `stage` qiymatlari.
STAGE_EXAM = "exam"
STAGES_WITH_SESSION = ("faceid", "exam")


def default_path() -> Path:
    from core.bundle_paths import local_state_root

    return local_state_root() / STATE_FILE_NAME


def atomic_write_json(path: Path, data: dict) -> None:
    """Vaqtinchalik fayl + fsync + `os.replace`. Xato KO'TARADI (chaqiruvchi ushlaydi)."""
    path = Path(path)
    payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path: Path) -> dict:
    """Buzilgan/yo'q fayl - bo'sh lug'at (xato emas)."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def sanitize(fields: dict) -> dict:
    """Oq ro'yxatdan tashqari kalitlarni tashlaydi."""
    clean = {}
    for key, value in fields.items():
        if key not in ALLOWED_KEYS:
            log.warning("state.json: ruxsat etilmagan kalit tashlandi: %s", key)
            continue
        clean[key] = value
    return clean


class StateStore:
    """UI jarayonining holat fayli. Thread-safe (qulf bilan)."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path) if path is not None else default_path()
        self._lock = threading.Lock()
        self._data: dict = {}
        self._write_failed_logged = False
        #: Ishga tushishdagi OLDINGI holat (o'zgartirilmaydi).
        self.previous: dict = read_json(self._path)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def data(self) -> dict:
        with self._lock:
            return dict(self._data)

    # ------------------------------------------------------------------
    def begin(self, *, pid: int, app_version: str, restart_count: int = 0,
              now: Optional[float] = None) -> dict:
        """
        Yangi jarayon: oldingi holatni baholaydi va yangisini boshlaydi.

        Qaytaradi: oldingi jarayon KUTILMAGANDA tugagan bo'lsa uning
        qisqa ma'lumoti (`previous_crash`), aks holda bo'sh lug'at.
        """
        now = time.time() if now is None else now
        crash = previous_crash_info(self.previous)
        fields: dict[str, Any] = {
            "schema": SCHEMA_VERSION,
            "app_version": app_version,
            "pid": int(pid),
            "started_at": now,
            "stage": "preflight",
            "clean_exit": False,
            "restart_count": int(restart_count or 0),
        }
        if restart_count:
            fields["restarted_at"] = now
        if crash:
            fields["previous_crash"] = crash
        with self._lock:
            self._data = {}
        self.update(**fields)
        return crash

    def update(self, **fields) -> bool:
        """Maydonlarni yangilaydi va ATOMIK yozadi. `False` - diskka yozilmadi."""
        clean = sanitize(fields)
        with self._lock:
            for key, value in clean.items():
                if value is None:
                    self._data.pop(key, None)
                else:
                    self._data[key] = value
            self._data["updated_at"] = time.time()
            snapshot = dict(self._data)
        try:
            atomic_write_json(self._path, snapshot)
            self._write_failed_logged = False
            return True
        except OSError as exc:
            # ENOSPC, EACCES, antivirus qulfi - dastur ishlashda davom etadi.
            if not self._write_failed_logged:
                log.error("Holat fayli yozilmadi (%s): %s", self._path, exc)
                self._write_failed_logged = True
            return False
        except Exception:  # noqa: BLE001
            if not self._write_failed_logged:
                log.exception("Holat fayli yozilmadi: %s", self._path)
                self._write_failed_logged = True
            return False

    def mark_clean_exit(self, reason: str) -> bool:
        return self.update(clean_exit=True, exit_reason=(reason or "")[:120], stage="exited")


def previous_crash_info(previous: dict) -> dict:
    """
    Oldingi holat "kutilmagan yopilish"mi.

    Belgisi: fayl bor, `pid` bor va `clean_exit` rost EMAS. Sessiya
    ma'lumoti (bor bo'lsa) qaytariladi - login'dan keyin "oldingi
    sessiya ochiq qolgan" xabari shundan quriladi.
    """
    if not previous or not previous.get("pid") or previous.get("clean_exit"):
        return {}
    info = {
        "pid": previous.get("pid"),
        "stage": previous.get("stage") or "",
        "at": previous.get("updated_at") or previous.get("started_at"),
    }
    for key in ("exam_id", "exam_name", "schedule_id", "session_public_id",
                "session_started_at"):
        if previous.get(key) not in (None, ""):
            info[key] = previous[key]
    return info


def had_open_session(crash: dict) -> bool:
    """Yiqilgan jarayonda serverda OCHIQ qolgan sessiya bo'lganmi."""
    return bool(
        crash
        and crash.get("session_public_id")
        and crash.get("stage") in STAGES_WITH_SESSION
    )
