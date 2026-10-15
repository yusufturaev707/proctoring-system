"""
Monitoring'ning Redis bilan ishlashi: uzilishga chidamli yozish va
hisoblagichlardan tezlik (`/s`) chiqarish.

Kalitlar `sysmon:` prefiksi bilan holat Redis'ida (`REDIS_STATE_URL`) —
`noeviction` siyosati ostida, shuning uchun HAR KALITDA muddat bor.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time

from apps.common.redis_client import get_redis

logger = logging.getLogger(__name__)

PREFIX = "sysmon"

#: Redis yiqilganda yozishni shuncha soniya urinmaymiz.
#:
#: Sabab: middleware har 5 s da (har worker'da) yozadi va Redis
#: ulanishining `socket_connect_timeout` i 2 s. Uzilishda har urinish
#: aynan shu so'rovni 2 s ga ushlab turardi — monitoring kuzatayotgan
#: narsasini sekinlashtirmasligi kerak. Statistika yo'qoladi, xolos.
_BREAKER_SECONDS = 30.0
_breaker_lock = threading.Lock()
_breaker_until = 0.0


def hostname() -> str:
    return socket.gethostname()


def key(*parts) -> str:
    return ":".join((PREFIX, *(str(part) for part in parts)))


def client_or_none():
    """Redis klienti yoki — yaqinda xato bo'lgan bo'lsa — `None`."""
    if time.monotonic() < _breaker_until:
        return None
    return get_redis()


def trip(exc: Exception) -> None:
    """Xatodan keyin yozishni vaqtincha to'xtatadi (bir marta log)."""
    global _breaker_until
    with _breaker_lock:
        first = time.monotonic() >= _breaker_until
        _breaker_until = time.monotonic() + _BREAKER_SECONDS
    if first:
        logger.warning("Monitoring: Redis'ga yozib bo'lmadi (%s) — %ss to'xtatildi", exc, _BREAKER_SECONDS)


# --------------------------------------------------------------------------
# Hisoblagich -> tezlik
# --------------------------------------------------------------------------
#: Bundan qisqa oraliqda tezlik hisoblanmaydi: 0.2 s lik farq shovqin
#: (ikki administrator bir vaqtda yangilasa) va avvalgi natija beriladi.
MIN_WINDOW_S = 1.5
#: Bundan eski namuna bilan farq "o'rtacha" bo'lib qoladi — tashlanadi.
MAX_WINDOW_S = 300.0


def compute_rates(tracker: str, counters: dict[str, float], *, now: float | None = None) -> tuple[dict, float]:
    """
    `counters` (o'sib boruvchi qiymatlar) bo'yicha sekundiga tezlik.

    Oldingi namuna Redis'da (`tracker` + xost), ya'ni gunicorn'ning BARCHA
    worker'lari bitta qatorni bo'lishadi: CPU foizi "shu worker oxirgi
    marta qachon so'radi" ga bog'liq bo'lmaydi. Ikki mustaqil kuzatuvchi
    bor — `live` (panel) va `history` (Celery, 30 s): panel ochiq tursa
    ham tarix nuqtalari 30 soniyalik o'rtacha bo'lib qoladi.

    Qaytaradi: `(tezliklar, oyna_soniya)`; birinchi namunada `({}, 0)`.
    Hisoblagich kamaygan kalit (jarayon qayta ishga tushdi) tashlanadi.
    """
    now = time.time() if now is None else now
    client = client_or_none()
    if client is None:
        return {}, 0.0
    redis_key = key("rate", tracker, hostname())
    try:
        raw = client.get(redis_key)
        previous = json.loads(raw) if raw else None
        if previous:
            age = now - float(previous["ts"])
            if 0 <= age < MIN_WINDOW_S:
                return previous.get("rates") or {}, float(previous.get("window") or 0)
            if age <= MAX_WINDOW_S:
                rates = _rates(previous.get("counters") or {}, counters, age)
                client.set(
                    redis_key,
                    json.dumps({"ts": now, "counters": counters, "rates": rates, "window": age}),
                    ex=int(MAX_WINDOW_S * 2),
                )
                return rates, age
        client.set(
            redis_key,
            json.dumps({"ts": now, "counters": counters, "rates": {}, "window": 0}),
            ex=int(MAX_WINDOW_S * 2),
        )
    except Exception as exc:  # noqa: BLE001 — monitoring hech qachon yiqitmaydi
        trip(exc)
    return {}, 0.0


def _rates(previous: dict, current: dict, window: float) -> dict[str, float]:
    if window <= 0:
        return {}
    rates = {}
    for name, value in current.items():
        before = previous.get(name)
        if before is None or value is None:
            continue
        delta = value - before
        if delta < 0:
            continue
        rates[name] = delta / window
    return rates
