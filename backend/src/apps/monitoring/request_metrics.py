"""
HTTP so'rovlar statistikasi: soni, javob vaqti (gistogramma), status
kodlari — umumiy va marshrut bo'yicha.

Qanday yig'iladi
================
Har so'rov jarayon ichidagi hisoblagichga qo'shiladi (lock ostida, Redis
chaqiruvisiz) va ~5 s da bir marta bitta pipeline bilan Redis'ga
yoziladi (`HINCRBY`). 800 so'rov/s da har so'rovga Redis yozuvi
qo'shimcha ~800 buyruq/s bo'lardi; bu yerda — worker boshiga 0.2/s.

Redis'da daqiqalik chelaklar (barcha API node'lari bitta yig'indida):

* `sysmon:req:{daqiqa}` — umumiy: `n`, `us` (jami mikrosoniya), `c2..c5`
  (status sinflari), `s429`, `s503`, `h0..h10` (javob vaqti
  gistogrammasi). 26 soat turadi (24 soatlik grafik).
* `sysmon:reqr:{daqiqa}` — marshrut bo'yicha (`{marshrut}|n` va h.k.).
  2 soat turadi: marshrutlar ko'p, ular faqat oxirgi soat jadvaliga kerak.

Marshrut — URL NAQSHI (`GET sessions/{pk}/`), haqiqiy manzil emas: aks
holda har sessiya id'si alohida qator bo'lib, Redis'ni to'ldirardi.

Yo'qotish: jarayon o'ldirilsa oxirgi ≤5 s statistikasi yo'qoladi —
bu monitoring, buxgalteriya emas.
"""

from __future__ import annotations

import bisect
import functools
import re
import threading
import time
from collections import Counter

from apps.monitoring import store

#: Javob vaqti chegaralari (ms); oxirgi chelak — undan kattasi.
BUCKETS_MS = (10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)
#: Marshrut gistogrammasi qo'polroq — maydonlar soni marshrutlar × chelak.
ROUTE_BUCKETS_MS = (50, 100, 250, 500, 1000, 2500)

FLUSH_INTERVAL_S = 5.0
#: Bir daqiqada bitta jarayondagi turli marshrutlar chegarasi. Kutilmagan
#: naqsh (masalan skaner botlari) Redis'ni to'ldirmasin.
MAX_ROUTES_PER_MINUTE = 400
OTHER_ROUTE = "(boshqa)"
NOT_FOUND_ROUTE = "(topilmadi)"

TOTALS_TTL_S = 26 * 3600
ROUTES_TTL_S = 2 * 3600


def totals_key(minute: int) -> str:
    return store.key("req", minute)


def routes_key(minute: int) -> str:
    return store.key("reqr", minute)


# --------------------------------------------------------------------------
# Marshrut nomi
# --------------------------------------------------------------------------
_NAMED_GROUP_RE = re.compile(r"\(\?P<(\w+)>[^)]*\)")
_CONVERTER_RE = re.compile(r"<(?:\w+:)?(\w+)>")


@functools.lru_cache(maxsize=2048)
def clean_route(route: str) -> str:
    """
    `api/v1/^sessions/(?P<pk>[^/.]+)/$` -> `sessions/{pk}/`.

    `resolver_match.route` include'lar bo'yicha bo'laklarni yopishtiradi,
    DRF router esa regex beradi — ikkalasi bir xil ko'rinishga keltiriladi.
    """
    cleaned = _NAMED_GROUP_RE.sub(r"{\1}", route)
    cleaned = _CONVERTER_RE.sub(r"{\1}", cleaned)
    cleaned = cleaned.replace("^", "").replace("$", "").replace("\\", "")
    if cleaned.startswith("api/v1/"):
        cleaned = cleaned[len("api/v1/"):]
    return cleaned or "/"


def route_label(request, status_code: int) -> str:
    match = getattr(request, "resolver_match", None)
    if match is None or not getattr(match, "route", None):
        return NOT_FOUND_ROUTE if status_code == 404 else OTHER_ROUTE
    return f"{request.method} {clean_route(match.route)}"


# --------------------------------------------------------------------------
# Jarayon ichidagi yig'uvchi
# --------------------------------------------------------------------------
class _Aggregator:
    def __init__(self):
        self._lock = threading.Lock()
        self._pending: dict[int, tuple[Counter, Counter]] = {}
        self._last_flush = time.monotonic()

    def record(self, route: str, status: int, duration_ms: float) -> None:
        minute = int(time.time() // 60)
        status_class = f"c{min(5, max(1, status // 100))}"
        bucket = bisect.bisect_left(BUCKETS_MS, duration_ms)
        route_bucket = bisect.bisect_left(ROUTE_BUCKETS_MS, duration_ms)
        micros = int(duration_ms * 1000)
        with self._lock:
            totals, routes = self._pending.setdefault(minute, (Counter(), Counter()))
            totals["n"] += 1
            totals["us"] += micros
            totals[status_class] += 1
            totals[f"h{bucket}"] += 1
            if status in (429, 503):
                totals[f"s{status}"] += 1

            if f"{route}|n" not in routes and len(routes) >= MAX_ROUTES_PER_MINUTE * 4:
                route = OTHER_ROUTE
            routes[f"{route}|n"] += 1
            routes[f"{route}|us"] += micros
            routes[f"{route}|h{route_bucket}"] += 1
            if status >= 500:
                routes[f"{route}|e5"] += 1
            elif status >= 400:
                routes[f"{route}|e4"] += 1

            due = time.monotonic() - self._last_flush >= FLUSH_INTERVAL_S
            if due:
                pending, self._pending = self._pending, {}
                self._last_flush = time.monotonic()
        if due:
            self._write(pending)

    def flush(self) -> None:
        with self._lock:
            pending, self._pending = self._pending, {}
            self._last_flush = time.monotonic()
        self._write(pending)

    @staticmethod
    def _write(pending: dict[int, tuple[Counter, Counter]]) -> None:
        if not pending:
            return
        client = store.client_or_none()
        if client is None:
            return
        try:
            pipe = client.pipeline(transaction=False)
            for minute, (totals, routes) in pending.items():
                for field, value in totals.items():
                    pipe.hincrby(totals_key(minute), field, value)
                pipe.expire(totals_key(minute), TOTALS_TTL_S)
                for field, value in routes.items():
                    pipe.hincrby(routes_key(minute), field, value)
                pipe.expire(routes_key(minute), ROUTES_TTL_S)
            pipe.execute()
        except Exception as exc:  # noqa: BLE001 — so'rovni hech qachon yiqitmaydi
            store.trip(exc)


aggregator = _Aggregator()


# --------------------------------------------------------------------------
# O'qish
# --------------------------------------------------------------------------
def _percentile(histogram: list[int], bounds: tuple[int, ...], fraction: float) -> float | None:
    """Gistogrammadan taxminiy persentil (chelak ichida chiziqli)."""
    total = sum(histogram)
    if total <= 0:
        return None
    target = total * fraction
    running = 0
    for index, count in enumerate(histogram):
        if count <= 0:
            continue
        if running + count >= target:
            lower = bounds[index - 1] if index > 0 else 0
            # Oxirgi chelak yuqori chegarasiz — pastki chegara beriladi
            # ("≥ 10 s"), uydirma son emas.
            if index >= len(bounds):
                return float(bounds[-1])
            upper = bounds[index]
            share = (target - running) / count
            return round(lower + (upper - lower) * share, 1)
        running += count
    return float(bounds[-1])


def summarize(totals: Counter, seconds: float) -> dict:
    count = int(totals.get("n", 0))
    histogram = [int(totals.get(f"h{i}", 0)) for i in range(len(BUCKETS_MS) + 1)]
    server_errors = int(totals.get("c5", 0))
    return {
        "count": count,
        "rps": round(count / seconds, 2) if seconds > 0 else 0,
        "avg_ms": round(totals.get("us", 0) / count / 1000, 1) if count else None,
        "p50_ms": _percentile(histogram, BUCKETS_MS, 0.50),
        "p95_ms": _percentile(histogram, BUCKETS_MS, 0.95),
        "p99_ms": _percentile(histogram, BUCKETS_MS, 0.99),
        "status": {
            "2xx": int(totals.get("c2", 0)),
            "3xx": int(totals.get("c3", 0)),
            "4xx": int(totals.get("c4", 0)),
            "5xx": server_errors,
            "429": int(totals.get("s429", 0)),
            "503": int(totals.get("s503", 0)),
        },
        "error_pct": round(server_errors / count * 100, 3) if count else 0.0,
        "histogram": [
            {"le_ms": BUCKETS_MS[i] if i < len(BUCKETS_MS) else None, "count": histogram[i]}
            for i in range(len(histogram))
        ],
    }


def _window(minutes: int, now: float | None = None) -> tuple[list[int], float]:
    """Oxirgi `minutes` daqiqa chelaklari va ular qamragan soniya (joriy qisman)."""
    now = time.time() if now is None else now
    current = int(now // 60)
    buckets = list(range(current - minutes + 1, current + 1))
    seconds = (minutes - 1) * 60 + (now - current * 60)
    return buckets, max(seconds, 1.0)


def _read_hashes(keys: list[str]) -> list[dict]:
    client = store.client_or_none()
    if client is None:
        return [{} for _ in keys]
    try:
        pipe = client.pipeline(transaction=False)
        for name in keys:
            pipe.hgetall(name)
        return pipe.execute()
    except Exception as exc:  # noqa: BLE001
        store.trip(exc)
        return [{} for _ in keys]


def windows(spans=(1, 5, 60), *, now: float | None = None) -> dict:
    """Oxirgi 1/5/60 daqiqa umumiy ko'rsatkichlari — bitta pipeline."""
    longest = max(spans)
    buckets, _ = _window(longest, now)
    rows = _read_hashes([totals_key(minute) for minute in buckets])
    result = {}
    for span in spans:
        span_buckets, seconds = _window(span, now)
        merged: Counter = Counter()
        for minute, row in zip(buckets, rows):
            if minute in span_buckets:
                merged.update({field: int(value) for field, value in row.items()})
        result[f"{span}m"] = summarize(merged, seconds)
    return result


def routes(minutes: int, *, now: float | None = None, limit: int = 60) -> dict:
    """Marshrutlar jadvali: soni, o'rtacha va p95, 4xx/5xx."""
    minutes = max(1, min(minutes, 120))
    buckets, seconds = _window(minutes, now)
    rows = _read_hashes([routes_key(minute) for minute in buckets])
    merged: Counter = Counter()
    for row in rows:
        merged.update({field: int(value) for field, value in row.items()})

    by_route: dict[str, Counter] = {}
    for field, value in merged.items():
        route, _, metric = field.rpartition("|")
        by_route.setdefault(route, Counter())[metric] += value

    items = []
    for route, values in by_route.items():
        count = values.get("n", 0)
        if not count:
            continue
        histogram = [values.get(f"h{i}", 0) for i in range(len(ROUTE_BUCKETS_MS) + 1)]
        method, _, path = route.partition(" ")
        items.append({
            "route": route,
            "method": method if path else "",
            "path": path or route,
            "count": count,
            "rps": round(count / seconds, 3),
            "avg_ms": round(values.get("us", 0) / count / 1000, 1),
            "p95_ms": _percentile(histogram, ROUTE_BUCKETS_MS, 0.95),
            "errors_4xx": values.get("e4", 0),
            "errors_5xx": values.get("e5", 0),
            # Umumiy vaqt ulushi: "server vaqtini nima yeyapti" — soni
            # ko'p, lekin tez marshrut va kam, lekin sekin marshrut bir
            # jadvalda solishtiriladi.
            "time_s": round(values.get("us", 0) / 1_000_000, 1),
        })
    total_time = sum(item["time_s"] for item in items) or 1
    for item in items:
        item["time_share_pct"] = round(item["time_s"] / total_time * 100, 1)
    items.sort(key=lambda item: item["time_s"], reverse=True)
    return {"minutes": minutes, "seconds": round(seconds), "routes": items[:limit], "total_routes": len(items)}


def series(minutes: int, step: int, *, now: float | None = None) -> list[dict]:
    """Grafik uchun: har `step` daqiqada rps, p95, xato foizi."""
    buckets, _ = _window(minutes, now)
    rows = _read_hashes([totals_key(minute) for minute in buckets])
    points = []
    for start in range(0, len(buckets), step):
        chunk_minutes = buckets[start:start + step]
        merged: Counter = Counter()
        for row in rows[start:start + step]:
            merged.update({field: int(value) for field, value in row.items()})
        seconds = len(chunk_minutes) * 60
        if chunk_minutes and chunk_minutes[-1] == buckets[-1]:
            now_ts = time.time() if now is None else now
            seconds = (len(chunk_minutes) - 1) * 60 + (now_ts - buckets[-1] * 60)
        summary = summarize(merged, max(seconds, 1.0))
        points.append({
            "t": chunk_minutes[0] * 60,
            "rps": summary["rps"],
            "p95_ms": summary["p95_ms"],
            "avg_ms": summary["avg_ms"],
            "error_pct": summary["error_pct"],
            "c4": summary["status"]["4xx"],
            "c5": summary["status"]["5xx"],
            "s429": summary["status"]["429"],
        })
    return points
