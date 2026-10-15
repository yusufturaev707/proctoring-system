"""
Ogohlantirish chegaralari — BITTA joyda.

Qiymatlar `deploy/MONITORING.md` dagi SLO'dan (CPU < 70%, RAM < 80%,
swap = 0, xato < 0.1%, p95 < 500 ms, Redis < maxmemory 70%, oqim lag
< 10 000). Panel ranglari ham shu jadvaldan (`status` javobidagi
`thresholds`) — sahifa va `problems` ro'yxati bir-biriga zid
gapirmasligi uchun.

Har kalit: `(ogohlantirish, kritik)`; qiymat shu chegaradan KATTA yoki
TENG bo'lsa holat o'zgaradi.
"""

THRESHOLDS: dict[str, tuple[float, float]] = {
    "cpu_pct": (70, 90),
    # Bitta yadro 100% — GIL'li Python jarayoni (gunicorn worker, uvicorn)
    # shu yadroda tiqilib qolgan bo'lishi mumkin, umumiy CPU esa 30%.
    "core_max_pct": (95, 100),
    "load_per_core": (1.0, 2.0),
    # ESXi: boshqa VM'lar shu xostdagi fizik yadroni egallagan vaqt.
    # Bir necha foiz ham kechikishda seziladi; VM ichidan tuzatib bo'lmaydi.
    "steal_pct": (5, 10),
    "iowait_pct": (15, 30),
    "memory_pct": (80, 92),
    # Swap'ga tushish — SLO buzilishi (MONITORING.md): kechikish keskin oshadi.
    "swap_used_pct": (1, 25),
    "disk_pct": (80, 90),
    "inode_pct": (80, 90),
    "disk_util_pct": (70, 90),
    "disk_await_ms": (20, 100),
    "fd_pct": (70, 90),
    "http_5xx_pct": (0.1, 1.0),
    "http_p95_ms": (500, 2000),
    "redis_memory_pct": (70, 85),
    # Redis asosiy oqimi bitta yadroda ishlaydi — 100% uning shifti.
    "redis_cpu_pct": (70, 90),
    "stream_lag": (10_000, 50_000),
    "pg_connections_pct": (80, 90),
    "pg_idle_in_tx_s": (60, 300),
    "pg_long_query_s": (30, 120),
    "pg_cache_hit_pct": (99, 95),  # TESKARI: past bo'lsa yomon (`_below`)
    # gunicorn qabul navbati: worker'lar ulgurmayapti.
    "listen_backlog": (10, 200),
    "celery_queue": (100, 1000),
    "disk_days_left": (30, 7),  # TESKARI
    "pressure_some_pct": (20, 50),
}

#: Kichik qiymat yomon bo'lgan kalitlar.
LOWER_IS_WORSE = frozenset({"pg_cache_hit_pct", "disk_days_left"})


def level(key: str, value) -> str:
    """`ok` / `warning` / `critical`; qiymat yo'q bo'lsa `unknown`."""
    if value is None:
        return "unknown"
    warn, crit = THRESHOLDS[key]
    if key in LOWER_IS_WORSE:
        if value <= crit:
            return "critical"
        if value <= warn:
            return "warning"
        return "ok"
    if value >= crit:
        return "critical"
    if value >= warn:
        return "warning"
    return "ok"


def as_payload() -> dict:
    return {
        key: {"warning": warn, "critical": crit, "lower_is_worse": key in LOWER_IS_WORSE}
        for key, (warn, crit) in THRESHOLDS.items()
    }
