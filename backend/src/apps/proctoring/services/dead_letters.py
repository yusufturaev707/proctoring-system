"""
`:dead` oqimlari bilan ishlash: sababni tasniflash, qayta yozish, tozalash.

Yozuv `:dead` ga ikki bosqichli yozishning oxirgi qatlamidan tushadi
(`stream.write_with_fallback`): batch ham, qator-ma-qator yozish ham
yiqilgan. Ma'lumot yo'qolmagan, lekin DB'da ham yo'q — panelda hodisa
ko'rinmaydi va xavf ballida qatnashmagan.

Tuzatish tartibi har doim bir xil:

1. `stats` — nima sababdan (tasnif SQLSTATE va cheklov nomi bo'yicha,
   eski yozuvlarda — matn bo'yicha);
2. sababni bartaraf etish (partitsiya yaratish, baza qaytishi...);
3. `replay` — yozuv asosiy oqimga QAYTADAN qo'yiladi va odatdagi ingest
   yo'li (Celery flush) uni yozadi. Yana yiqilsa — yangi sabab bilan
   yana `:dead` ga tushadi (endi kodi bilan), ya'ni hech narsa yo'qolmaydi;
4. qayta yozib bo'lmaydiganlar (sessiyasi yo'q) — `purge`, avval faylga
   zaxira qilinadi.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

from django.conf import settings

from apps.common.redis_client import get_redis
from apps.proctoring.services.stream import dead_letter_key

STREAMS = {
    "events": "EVENT_STREAM_KEY",
    "screenshots": "SCREENSHOT_STREAM_KEY",
}


@dataclass(frozen=True)
class Category:
    key: str
    title: str
    action: str
    replayable: bool


CATEGORIES = {
    item.key: item
    for item in (
        Category(
            "session_missing",
            "Sessiya bazada yo'q",
            "Hodisa o'chirilgan (yoki hech qachon bo'lmagan) sessiyaga tegishli — qayta yozib "
            "bo'lmaydi. Kim sessiyani o'chirganini tekshiring (smoke_test, qo'lda DELETE, "
            "boshqa bazaga ulangan worker), keyin `purge` (zaxira faylga yoziladi).",
            False,
        ),
        Category(
            "no_partition",
            "Hodisa sanasi uchun partitsiya yo'q",
            "`python manage.py setup_partitions --apply --days 30`, keyin `replay`. "
            "Beat'dagi `rotate-event-partitions` ishlayotganini tekshiring.",
            True,
        ),
        Category(
            "db_unavailable",
            "Baza vaqtincha ishlamagan",
            "Baza qaytgan bo'lsa — `replay`.",
            True,
        ),
        Category(
            "invalid_data",
            "Ma'lumot noto'g'ri (uzun satr, noto'g'ri tur)",
            "Client yuborgan qiymat model cheklovidan o'tmagan — namunani ko'rib, "
            "client/serializer'ni tuzating; yozuvning o'zi qayta yozilmaydi.",
            False,
        ),
        Category(
            "parse",
            "Yozuvni o'qib bo'lmadi",
            "Oqimdagi maydonlar buzilgan — qayta yozib bo'lmaydi; namunani ko'rib `purge`.",
            False,
        ),
        Category(
            "other",
            "Boshqa / aniqlanmagan",
            "`replay --category other` — yana yiqilsa, yozuv SQLSTATE kodi bilan qaytadi "
            "va keyingi `stats` uni aniq tasniflaydi.",
            True,
        ),
    )
}

_DB_DOWN_RE = re.compile(
    r"could not connect|server closed the connection|connection (refused|timed out)|"
    r"terminating connection|OperationalError|InterfaceError",
    re.IGNORECASE,
)


def classify(entry: dict) -> str:
    """SQLSTATE/cheklov bo'yicha; ular yo'q eski yozuvlarda — matn bo'yicha."""
    reason = entry.get("reason") or ""
    code = entry.get("code") or ""
    constraint = (entry.get("constraint") or "").lower()
    if reason.startswith("parse:"):
        return "parse"
    if code == "23503" or "_fk" in reason.lower() or "foreign key" in reason.lower():
        if "session" in constraint or "session" in reason.lower():
            return "session_missing"
    # "Qatorga partitsiya topilmadi" ham 23514 (check_violation), lekin
    # cheklov nomisiz — model `CheckConstraint` larida nom bor.
    if (code == "23514" and not constraint) or "no partition of relation" in reason.lower():
        return "no_partition"
    if code.startswith(("08", "57")) or _DB_DOWN_RE.search(reason):
        return "db_unavailable"
    if code.startswith("22") or "value too long" in reason.lower() or "invalid input" in reason.lower():
        return "invalid_data"
    return "other"


def stream_key(name: str) -> str:
    if name not in STREAMS:
        raise ValueError(f"Noma'lum oqim: {name} ({', '.join(STREAMS)})")
    return settings.PROCTORING[STREAMS[name]]


def entry_time(entry_id: str) -> datetime:
    return datetime.fromtimestamp(int(entry_id.split("-", 1)[0]) / 1000, tz=dt_timezone.utc)


def read(name: str, *, limit: int | None = None) -> list[tuple[str, dict]]:
    """`:dead` yozuvlari (eskisidan boshlab)."""
    key = dead_letter_key(stream_key(name))
    return get_redis().xrange(key, count=limit) if limit else get_redis().xrange(key)


def payload_of(entry: dict) -> dict | None:
    """Asl oqim maydonlari; 8000 belgida kesilgan bo'lsa — `None`."""
    try:
        fields = json.loads(entry.get("payload") or "")
    except ValueError:
        return None
    return fields if isinstance(fields, dict) else None


def stats(name: str) -> dict:
    entries = read(name)
    groups: dict[str, dict] = {}
    for entry_id, entry in entries:
        category = classify(entry)
        group = groups.setdefault(category, {
            "count": 0, "first": entry_id, "last": entry_id, "sample": entry.get("reason", ""),
            "codes": Counter(), "sessions": set(),
        })
        group["count"] += 1
        group["last"] = entry_id
        if entry.get("code"):
            group["codes"][entry["code"]] += 1
        fields = payload_of(entry) or {}
        if fields.get("session_id"):
            group["sessions"].add(str(fields["session_id"]))
    return {"total": len(entries), "groups": groups}


def _existing_sessions(session_ids: set[str]) -> set[str]:
    from apps.proctoring.models import ExamSession

    numeric = [int(value) for value in session_ids if str(value).isdigit()]
    return {str(pk) for pk in ExamSession.objects.filter(pk__in=numeric).values_list("pk", flat=True)}


def _as_stream_fields(fields: dict) -> dict[str, str]:
    """XADD faqat tekis satrlarni qabul qiladi (tezkor yo'l yozuvida dict bo'lishi mumkin)."""
    result = {}
    for key, value in fields.items():
        if value is None:
            result[key] = ""
        elif isinstance(value, (dict, list)):
            result[key] = json.dumps(value, ensure_ascii=False)
        else:
            result[key] = str(value)
    return result


def replay(name: str, *, categories: set[str] | None = None, dry_run: bool = False, limit: int | None = None) -> dict:
    """
    Yozuvlarni asosiy oqimga qaytaradi; muvaffaqiyatli `XADD` dan KEYIN
    `:dead` dan o'chiradi (oraliqda yiqilsa — dublikat, yo'qotish emas;
    `client_event_id` va `ignore_conflicts` takrorni to'sadi).

    `categories` berilmasa — faqat qayta yozish ma'noli bo'lganlar.
    Sessiyasi bazada yo'q yozuv HECH QACHON qaytarilmaydi: u yana `:dead`
    ga tushib, aylanib yurardi.
    """
    wanted = categories or {key for key, item in CATEGORIES.items() if item.replayable}
    source = stream_key(name)
    dead_key = dead_letter_key(source)
    candidates = []
    skipped = Counter()
    for entry_id, entry in read(name, limit=limit):
        category = classify(entry)
        if category not in wanted:
            skipped[category] += 1
            continue
        fields = payload_of(entry)
        if fields is None:
            skipped["truncated"] += 1
            continue
        candidates.append((entry_id, fields))

    existing = _existing_sessions({str(f.get("session_id")) for _, f in candidates if f.get("session_id")})
    client = get_redis()
    replayed = 0
    for entry_id, fields in candidates:
        session_id = str(fields.get("session_id") or "")
        if session_id and session_id not in existing:
            skipped["session_missing"] += 1
            continue
        if not dry_run:
            client.xadd(
                source,
                _as_stream_fields(fields),
                maxlen=settings.PROCTORING["EVENT_STREAM_MAXLEN"],
                approximate=True,
            )
            client.xdel(dead_key, entry_id)
        replayed += 1
    return {"replayed": replayed, "skipped": dict(skipped), "dry_run": dry_run}


def backup_dir() -> Path:
    # `var/` — production'da servis yozishi mumkin bo'lgan katalog
    # (systemd `ReadWritePaths`), repoga kirmaydi.
    return Path(settings.BASE_DIR).resolve().parent / "var" / "dead_letters"


def purge(name: str, *, categories: set[str], output: Path | None = None) -> dict:
    """
    Tanlangan turkumdagi yozuvlarni JSONL faylga yozadi, KEYIN o'chiradi.

    Fayl yozilmasa hech narsa o'chirilmaydi.
    """
    if not categories:
        raise ValueError("Kamida bitta turkum (--category) kerak")
    selected = [(entry_id, entry) for entry_id, entry in read(name) if classify(entry) in categories]
    if not selected:
        return {"deleted": 0, "file": None}
    if output is None:
        stamp = datetime.now(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = backup_dir() / f"{name}_{stamp}.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for entry_id, entry in selected:
            handle.write(json.dumps({"id": entry_id, "category": classify(entry), **entry}, ensure_ascii=False) + "\n")
    get_redis().xdel(dead_letter_key(stream_key(name)), *[entry_id for entry_id, _ in selected])
    return {"deleted": len(selected), "file": str(output)}
