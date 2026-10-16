"""
Celery sog'lig'i: navbatlar uzunligi va davriy vazifalar oxirgi marta
QACHON bajarilgani.

`celery inspect ping` ishlatilmaydi: u broadcast va javobni ~1 s kutadi,
ishchi band bo'lsa (ingest flush) javob bermay "o'lik" ko'rinadi. Eng
aniq belgi — vazifaning o'zi: `flush_event_buffer` har 5 s da bajarilib
tursa, beat ham, ingest ishchisi ham, ularning Redis/DB ulanishi ham
ishlayapti. Signal har vazifa yakunida bitta `HSET` yozadi.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta

import redis
from django.conf import settings

from apps.monitoring import store

logger = logging.getLogger(__name__)

LAST_RUN_KEY = store.key("celery", "last")
FAILURES_KEY = "sysmon:celery:fail:{hour}"
_FAILURES_TTL_S = 26 * 3600

_starts: dict[str, float] = {}
_starts_lock = threading.Lock()
_connected = False


def _enabled() -> bool:
    return bool(settings.SYSTEM_MONITOR.get("ENABLED", True))


def _on_prerun(task_id=None, **_kwargs):
    if task_id and _enabled():
        with _starts_lock:
            _starts[task_id] = time.monotonic()


def _on_postrun(task_id=None, task=None, state=None, **_kwargs):
    if not _enabled() or task is None:
        return
    with _starts_lock:
        started = _starts.pop(task_id, None)
    client = store.client_or_none()
    if client is None:
        return
    payload = {
        "ts": time.time(),
        "state": state or "",
        "runtime_s": None if started is None else round(time.monotonic() - started, 3),
    }
    try:
        pipe = client.pipeline(transaction=False)
        pipe.hset(LAST_RUN_KEY, task.name, json.dumps(payload))
        if state not in ("SUCCESS", None):
            hour_key = FAILURES_KEY.format(hour=int(time.time() // 3600))
            pipe.hincrby(hour_key, task.name, 1)
            pipe.expire(hour_key, _FAILURES_TTL_S)
        pipe.execute()
    except Exception as exc:  # noqa: BLE001 — vazifani hech qachon yiqitmaydi
        store.trip(exc)


def connect_signals() -> None:
    global _connected
    if _connected:
        return
    from celery.signals import task_postrun, task_prerun

    task_prerun.connect(_on_prerun, weak=False)
    task_postrun.connect(_on_postrun, weak=False)
    _connected = True


# --------------------------------------------------------------------------
# O'qish
# --------------------------------------------------------------------------
_broker_client: redis.Redis | None = None


def _broker() -> redis.Redis | None:
    global _broker_client
    url = settings.CELERY_BROKER_URL or ""
    if not url.startswith(("redis://", "rediss://")):
        return None
    if _broker_client is None:
        _broker_client = redis.Redis.from_url(
            url, socket_connect_timeout=1, socket_timeout=1, decode_responses=True,
        )
    return _broker_client


def queues() -> dict:
    """Broker navbatlari uzunligi (`LLEN`)."""
    names = ["ingest", "maintenance", settings.CELERY_TASK_DEFAULT_QUEUE]
    client = _broker()
    if client is None:
        return {"available": False, "queues": []}
    try:
        pipe = client.pipeline(transaction=False)
        for name in names:
            pipe.llen(name)
        lengths = pipe.execute()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Monitoring: broker o'qilmadi: %s", exc)
        return {"available": False, "queues": []}
    return {
        "available": True,
        "queues": [{"name": name, "length": int(length)} for name, length in zip(names, lengths)],
    }


def _describe(schedule) -> tuple[str, float | None]:
    """(matn, oraliq_soniya) — crontab uchun oraliq `None`."""
    if isinstance(schedule, (int, float)):
        return f"har {int(schedule)} s", float(schedule)
    if isinstance(schedule, timedelta):
        return f"har {int(schedule.total_seconds())} s", schedule.total_seconds()
    run_every = getattr(schedule, "run_every", None)
    if isinstance(run_every, timedelta) and not hasattr(schedule, "minute"):
        return f"har {int(run_every.total_seconds())} s", run_every.total_seconds()
    minute = getattr(schedule, "_orig_minute", "*")
    hour = getattr(schedule, "_orig_hour", "*")
    if hour == "*":
        return f"har soat :{str(minute).zfill(2)}", None
    return f"har kuni {str(hour).zfill(2)}:{str(minute).zfill(2)}", None


def periodic_tasks(*, now: float | None = None) -> dict:
    """
    Beat jadvalidagi har vazifa: oxirgi bajarilish, davomiyligi, holati.

    `stale` — oraliqli vazifa `max(3 × oraliq, oraliq + 30 s)` dan beri
    bajarilmagan. crontab vazifasi kuniga bir marta — kechikishi
    `celery` dagi `remaining_estimate` bo'yicha (o'tkazib yuborilgan).
    """
    from config.celery import app

    now = time.time() if now is None else now
    client = store.client_or_none()
    records: dict[str, str] = {}
    failures: dict[str, int] = {}
    if client is not None:
        try:
            pipe = client.pipeline(transaction=False)
            pipe.hgetall(LAST_RUN_KEY)
            current_hour = int(now // 3600)
            for hour in range(current_hour - 23, current_hour + 1):
                pipe.hgetall(FAILURES_KEY.format(hour=hour))
            results = pipe.execute()
            records = results[0] or {}
            for row in results[1:]:
                for name, count in (row or {}).items():
                    failures[name] = failures.get(name, 0) + int(count)
        except Exception as exc:  # noqa: BLE001
            store.trip(exc)

    tasks = []
    for entry_name, entry in sorted(app.conf.beat_schedule.items()):
        task_name = entry["task"]
        text, interval = _describe(entry["schedule"])
        record = None
        if records.get(task_name):
            try:
                record = json.loads(records[task_name])
            except ValueError:
                record = None
        last_ts = record["ts"] if record else None
        age = None if last_ts is None else max(0.0, now - float(last_ts))
        if record is None:
            health = "never"
        elif interval is not None:
            health = "stale" if age > max(3 * interval, interval + 30) else "ok"
        else:
            health = "ok"
            try:
                schedule = entry["schedule"]
                # Vaqt jadval zonasida (Asia/Tashkent) berilishi SHART: crontab
                # `last_run_at.hour` ni o'z soati bilan solishtiradi, UTC'dagi
                # 23:00 (= 04:00 Toshkent) "bugun 04:00 hali bo'lmagan" deb
                # o'qilib, har bajarilgan kunlik vazifa "o'tkazib yuborilgan" chiqardi.
                last_dt = datetime.fromtimestamp(float(last_ts), tz=getattr(schedule, "tz", None) or app.timezone)
                # `remaining_estimate` haqiqiy soatga nisbatan — `now` (testda
                # surilgan) bilan solishtirish uchun mutlaq vaqtga aylantiriladi.
                next_due = time.time() + schedule.remaining_estimate(last_dt).total_seconds()
                # Keyingi ishga tushish vaqti o'tib, 10 daqiqadan ko'p bo'lsa — o'tkazib yuborilgan.
                if now - next_due > 600:
                    health = "stale"
            except Exception:  # noqa: BLE001
                pass
        if record and record.get("state") not in ("SUCCESS", "", None) and health == "ok":
            health = "failed"
        tasks.append({
            "name": entry_name,
            "task": task_name,
            "queue": (entry.get("options") or {}).get("queue") or "",
            "schedule": text,
            "interval_s": interval,
            "last_run_age_s": None if age is None else round(age, 1),
            "last_state": record.get("state") if record else None,
            "last_runtime_s": record.get("runtime_s") if record else None,
            "failures_24h": failures.get(task_name, 0),
            "health": health,
        })
    return {"tasks": tasks, "tracking": bool(records)}
