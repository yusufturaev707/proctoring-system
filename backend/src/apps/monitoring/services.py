"""
Server holati: bo'limlarni yig'ish, muammolarni aniqlash, tarix.

Har bo'lim MUSTAQIL: PostgreSQL ishlamasa ham CPU, disk va servislar
ko'rinadi (aynan shu paytda ular eng kerak). Bo'lim xatosi `errors` ga
tushadi va `problems` ro'yxatida aytiladi — 500 qaytarilmaydi.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.monitoring import celery_health, collectors, host, request_metrics, store
from apps.monitoring.thresholds import as_payload, level

logger = logging.getLogger(__name__)

HISTORY_KEY = "sysmon:hist:{host}"
#: 24 soat × 30 s.
HISTORY_POINTS = 2880
HISTORY_INTERVAL_S = 30
DISK_DAILY_KEY = "sysmon:diskday:{host}"
DISK_DAILY_KEEP_DAYS = 35
STORAGE_USAGE_KEY = store.key("storage")
STORAGE_USAGE_EVERY_S = 3600


def _guarded(errors: dict, name: str, fn, default):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — bitta bo'lim sahifani yiqitmaydi
        logger.warning("Monitoring: %s bo'limi o'qilmadi: %s", name, exc)
        errors[name] = f"{type(exc).__name__}: {str(exc)[:200]}"
        return default


# --------------------------------------------------------------------------
# Jonli holat
# --------------------------------------------------------------------------
def system_status(*, use_cache: bool = True) -> dict:
    ttl = int(settings.SYSTEM_MONITOR.get("CACHE_SECONDS") or 0)
    cache_key = f"sysmon:status:{store.hostname()}"
    if use_cache and ttl > 0:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
    snapshot = build_status()
    if ttl > 0:
        cache.set(cache_key, snapshot, ttl)
    return snapshot


def build_status() -> dict:
    started = time.perf_counter()
    errors: dict[str, str] = {}
    counters: dict[str, float] = {}

    def collect(name, fn, default):
        result = _guarded(errors, name, fn, default)
        if isinstance(result, tuple):
            data, extra = result
            counters.update(extra)
            return data
        return result

    platform = collect("platform", host.platform_info, {})
    cpu = collect("cpu", host.cpu, {})
    memory = collect("memory", host.memory, {})
    postgres = collect("postgres", collectors.postgres, None)
    paths = host.data_paths({"postgres": (postgres or {}).get("data_directory")})
    disks = collect("disks", lambda: host.disks(paths), {"mounts": [], "devices": []})
    network = collect("network", host.network, {"interfaces": []})
    services = collect("services", host.services, {"available": False, "units": []})
    redis = collect("redis", collectors.redis_info, None)
    streams = collect("streams", collectors.streams, {"streams": []})
    nginx = collect("nginx", collectors.nginx, {"available": False})
    sockets = _guarded(errors, "sockets", host.sockets, {"available": False, "ports": []})
    limits = _guarded(errors, "limits", host.kernel_limits, {})
    pressure = _guarded(errors, "pressure", host.pressure, None)
    process = _guarded(errors, "process", collectors.exam_process, None)
    celery = {
        **_guarded(errors, "celery_queues", celery_health.queues, {"available": False, "queues": []}),
        **_guarded(errors, "celery_tasks", celery_health.periodic_tasks, {"tasks": [], "tracking": False}),
    }
    requests = _guarded(errors, "requests", request_metrics.windows, {})

    rates, window = store.compute_rates("live", counters)

    disks = host.disks_from_rates(disks, rates)
    for mount in disks["mounts"]:
        mount.update(_forecast(mount))
    snapshot = {
        "generated_at": timezone.now().isoformat(),
        "window_s": round(window, 1),
        "host": platform,
        "cpu": host.cpu_from_rates(cpu, rates),
        "memory": {
            **memory,
            "swap_in_bps": _round(rates.get("swap.sin")),
            "swap_out_bps": _round(rates.get("swap.sout")),
        },
        "pressure": pressure,
        "limits": limits,
        "disks": disks,
        "network": host.network_from_rates(network, rates),
        "sockets": sockets,
        "services": host.services_from_rates(services, rates),
        "postgres": collectors.postgres_from_rates(postgres, rates) if postgres else None,
        "redis": collectors.redis_from_rates(redis, rates) if redis else None,
        "streams": collectors.streams_from_rates(streams, rates),
        "nginx": collectors.nginx_from_rates(nginx, rates),
        "celery": celery,
        "requests": requests,
        "process": process,
        "storage": storage_usage_cached(),
        "history": _history_meta(),
        "errors": errors,
        "thresholds": as_payload(),
    }
    snapshot["problems"] = problems(snapshot)
    snapshot["overall"] = _overall(snapshot["problems"])
    snapshot["collect_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return snapshot


def _round(value, digits: int = 0):
    return None if value is None else round(value, digits)


def _overall(items: list[dict]) -> str:
    severities = {item["severity"] for item in items}
    if "critical" in severities:
        return "critical"
    if "warning" in severities:
        return "warning"
    return "ok"


# --------------------------------------------------------------------------
# Muammolar — "nima bo'ldi" + "nima qilish kerak"
# --------------------------------------------------------------------------
def _fmt_bytes(value: float | None) -> str:
    if value is None:
        return "—"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TB"


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = int(seconds)
    if seconds < 90:
        return f"{seconds} s"
    if seconds < 5400:
        return f"{seconds // 60} daqiqa"
    if seconds < 172800:
        return f"{seconds // 3600} soat"
    return f"{seconds // 86400} kun"


def problems(snapshot: dict) -> list[dict]:  # noqa: C901 — qoidalar ro'yxati, ataylab tekis
    items: list[dict] = []

    def add(severity, section, code, title, hint=""):
        if severity in ("warning", "critical"):
            items.append({"severity": severity, "section": section, "code": code, "title": title, "hint": hint})

    errors = snapshot.get("errors") or {}
    if "postgres" in errors:
        add("critical", "postgres", "postgres_unreachable", "PostgreSQL'ga ulanib bo'lmadi",
            "`systemctl status postgresql@*` va PgBouncer'ni tekshiring; imtihon yozuvlari to'xtagan bo'lishi mumkin.")
    if "redis" in errors:
        add("critical", "redis", "redis_unreachable", "Redis'ga ulanib bo'lmadi",
            "`systemctl status redis-server`. Imtihon zaxira yo'lda (DB) davom etadi, lekin sekinroq.")
    for name in sorted(set(errors) - {"postgres", "redis"}):
        add("warning", name, f"collector_{name}", f"«{name}» bo'limi o'qilmadi", errors[name])

    # --- CPU ---
    cpu = snapshot.get("cpu") or {}
    percent = cpu.get("percent")
    add(level("cpu_pct", percent), "cpu", "cpu_high", f"CPU yuklamasi {percent}%",
        "Qaysi servis ko'p olayotganini «Servislar» jadvalidan ko'ring. Doimiy bo'lsa VM'ga vCPU qo'shing.")
    cores = cpu.get("cores") or []
    if cores and percent is not None and percent < 70 and level("core_max_pct", max(cores)) != "ok":
        add("warning", "cpu", "core_saturated", f"Bitta yadro to'liq band ({max(cores)}%)",
            "Bitta jarayon (gunicorn worker, uvicorn yoki Redis) bitta yadroda tiqilgan — "
            "umumiy CPU bo'sh bo'lsa ham u sekinlashadi.")
    breakdown = cpu.get("breakdown") or {}
    steal = breakdown.get("steal")
    add(level("steal_pct", steal), "cpu", "cpu_steal", f"ESXi xosti band: steal {steal}%",
        "VM fizik yadroni kutyapti. VM ichidan tuzatilmaydi: ESXi'da xostdagi boshqa VM'lar yuklamasini, "
        "vCPU sonini (ortiqcha vCPU ham zarar) va CPU reservation'ni tekshiring.")
    iowait = breakdown.get("iowait")
    add(level("iowait_pct", iowait), "cpu", "cpu_iowait", f"Disk kutish (iowait) {iowait}%",
        "Jarayonlar diskni kutyapti — «Disklar» bo'limida qaysi qurilma band; ESXi datastore yuklamasini tekshiring.")
    per_core = cpu.get("load_per_core")
    load = (cpu.get("load") or [None])[0]
    add(level("load_per_core", per_core), "cpu", "load_high",
        f"Yuklama (load average) {load} — yadroga {per_core}",
        "Bajarilishni kutayotgan jarayonlar yadrolardan ko'p: CPU yoki disk yetmayapti.")

    # --- Xotira ---
    memory = snapshot.get("memory") or {}
    add(level("memory_pct", memory.get("percent")), "memory", "memory_high",
        f"Xotira {memory.get('percent')}% band",
        "Eng ko'p xotira olgan servisni «Servislar» jadvalidan toping; VM'ga RAM qo'shing yoki worker sonini kamaytiring.")
    if (memory.get("swap_in_bps") or 0) > 0:
        add("critical", "memory", "swap_in", f"Swap'dan o'qilyapti ({_fmt_bytes(memory.get('swap_in_bps'))}/s)",
            "RAM yetmayapti — kechikish keskin oshadi (SLO: swap = 0). Darhol xotira bo'shating yoki RAM qo'shing.")
    elif memory.get("swap_total"):
        add(level("swap_used_pct", memory.get("swap_percent")), "memory", "swap_used",
            f"Swap ishlatilgan: {_fmt_bytes(memory.get('swap_used'))}",
            "Ilgari xotira yetmagan. Hozir swap'dan o'qilmayapti, lekin RAM zaxirasi kam.")

    pressure = snapshot.get("pressure") or {}
    for resource, label in (("cpu", "CPU"), ("memory", "xotira"), ("io", "disk")):
        some = ((pressure.get(resource) or {}).get("some") or {}).get("avg60")
        add(level("pressure_some_pct", some), "pressure", f"pressure_{resource}",
            f"{label} yetishmovchiligi: jarayonlar vaqtning {some}% ida kutdi (PSI)",
            "PSI — haqiqiy kechikish o'lchovi: foiz past bo'lsa ham resurs to'yingan.")

    limits = snapshot.get("limits") or {}
    add(level("fd_pct", limits.get("files_percent")), "limits", "fd_high",
        f"Ochiq fayllar chegarasi {limits.get('files_percent')}%", "`fs.file-max` (sysctl) ni oshiring.")

    # --- Disklar ---
    disks = snapshot.get("disks") or {}
    for mount in disks.get("mounts", []):
        name = mount["mount"]
        contains = ", ".join(mount.get("contains") or [])
        suffix = f" ({contains})" if contains else ""
        add(level("disk_pct", mount.get("percent")), "disks", "disk_full",
            f"{name}{suffix} — {mount.get('percent')}% to'lgan, {_fmt_bytes(mount.get('free'))} bo'sh",
            "Diskni kengaytiring (ESXi'da VMDK + `growpart`/`resize2fs`) yoki saqlash muddatini qisqartiring.")
        add(level("inode_pct", mount.get("inodes_percent")), "disks", "inodes_full",
            f"{name} — inode'lar {mount.get('inodes_percent')}% band",
            "Juda ko'p mayda fayl (skrinshotlar): bo'sh joy bo'lsa ham yangi fayl yozilmaydi.")
        days = mount.get("days_left")
        if days is not None:
            add(level("disk_days_left", days), "disks", "disk_forecast",
                f"{name}{suffix} ~{days} kunda to'ladi (kuniga +{_fmt_bytes(mount.get('growth_per_day'))})",
                "Diskni oldindan kengaytiring: to'lsa skrinshot va hodisalar yozilmaydi.")
    for device in disks.get("io", []):
        add(level("disk_util_pct", device.get("util_pct")), "disks", "disk_busy",
            f"{device['device']} disk {device.get('util_pct')}% band",
            "Disk to'yingan. ESXi datastore'ni (boshqa VM'lar, snapshot'lar) tekshiring.")
        if (device.get("read_iops") or 0) + (device.get("write_iops") or 0) >= 5:
            add(level("disk_await_ms", device.get("await_ms")), "disks", "disk_slow",
                f"{device['device']} javob vaqti {device.get('await_ms')} ms",
                "Disk sekin javob beryapti — datastore kechikishini (ESXi `DAVG`/`KAVG`) tekshiring.")

    for nic in (snapshot.get("network") or {}).get("interfaces", []):
        if (nic.get("errors_per_s") or 0) > 0:
            add("warning", "network", "nic_errors", f"{nic['name']}: paket xatolari/tashlanishlari",
                "Tarmoq kartasi yoki vSwitch muammosi; VMXNET3 drayverini tekshiring.")

    sockets = snapshot.get("sockets") or {}
    for port in sockets.get("ports", []):
        if port["name"] in ("api", "ws"):
            add(level("listen_backlog", port.get("backlog")), "sockets", f"backlog_{port['name']}",
                f"{port['name'].upper()} qabul navbatida {port.get('backlog')} ulanish kutyapti",
                "Worker'lar ulgurmayapti — GUNICORN_WORKERS/threads yoki CPU yetmayapti.")

    # --- Servislar ---
    services = snapshot.get("services") or {}
    for unit in services.get("units", []):
        label = unit["label"]
        if unit["load_state"] == "not-found":
            add("critical", "services", "unit_missing", f"{label}: servis topilmadi ({unit['unit']})",
                "Servis o'rnatilmagan yoki nomi boshqa (`SYSTEM_MONITOR_UNITS`).")
        elif unit["active_state"] != "active":
            add("critical" if unit["required"] else "warning", "services", "unit_down",
                f"{label}: {unit['active_state']} ({unit['sub_state']})",
                f"`journalctl -u {unit['unit']} -n 100` — xato sababini ko'ring, keyin `systemctl restart {unit['unit']}`.")
        elif unit.get("restarts"):
            add("warning", "services", "unit_restarted", f"{label}: {unit['restarts']} marta qayta ishga tushgan",
                f"Servis yiqilib turibdi — `journalctl -u {unit['unit']}` dagi xatolarni ko'ring.")

    platform = snapshot.get("host") or {}
    virt = platform.get("virtualization") or {}
    if virt.get("type") == "vmware" and virt.get("vmware_tools") is False:
        add("warning", "host", "vmware_tools", "VMware Tools ishlamayapti",
            "`apt install open-vm-tools` — xostdan to'g'ri o'chirish, vaqt sinxronizatsiyasi va xotira boshqaruvi uchun.")
    time_sync = platform.get("time_sync") or {}
    if time_sync.get("synced") is False:
        add("warning", "host", "ntp", "Server soati sinxron emas (NTP)",
            "Heartbeat va sessiya muddatlari soatga tayanadi: `systemctl status systemd-timesyncd` (yoki chrony).")

    # --- PostgreSQL ---
    postgres = snapshot.get("postgres") or {}
    if postgres:
        conn = postgres.get("connections") or {}
        add(level("pg_connections_pct", conn.get("percent")), "postgres", "pg_connections",
            f"PostgreSQL ulanishlari {conn.get('total')}/{postgres.get('max_connections')}",
            "PgBouncer pool'i yoki `max_connections`; ulanishlar oqib ketayotgan bo'lishi mumkin.")
        add(level("pg_idle_in_tx_s", conn.get("longest_idle_tx_s")), "postgres", "pg_idle_tx",
            f"Ochiq qolgan tranzaksiya: {_fmt_duration(conn.get('longest_idle_tx_s'))}",
            "Tranzaksiya ochiq turib qatorlarni qulflaydi va VACUUM'ni to'sadi.")
        add(level("pg_long_query_s", conn.get("longest_query_s")), "postgres", "pg_long_query",
            f"Uzoq so'rov: {_fmt_duration(conn.get('longest_query_s'))}",
            "`pg_stat_activity` dan so'rovni toping (statement_timeout 15 s).")
        if conn.get("lock_waiting"):
            add("warning", "postgres", "pg_locks", f"{conn['lock_waiting']} ta so'rov qulfni kutyapti",
                "`SELECT * FROM pg_locks WHERE NOT granted` — kim kimni to'sayotganini ko'ring.")
        pg_rates = postgres.get("rates") or {}
        if (pg_rates.get("commits_per_s") or 0) >= 5:
            add(level("pg_cache_hit_pct", pg_rates.get("cache_hit_pct")), "postgres", "pg_cache",
                f"Kesh samaradorligi {pg_rates.get('cache_hit_pct')}%",
                "Ma'lumot diskdan o'qilyapti: `shared_buffers` ni oshiring yoki indekssiz so'rovni toping.")
        if (pg_rates.get("deadlocks_per_s") or 0) > 0:
            add("warning", "postgres", "pg_deadlocks", "Deadlock'lar paydo bo'lyapti", "PostgreSQL log'ida `deadlock detected`.")

    # --- Redis ---
    redis = snapshot.get("redis") or {}
    if redis:
        if redis.get("maxmemory_policy") and redis["maxmemory_policy"] != "noeviction":
            add("critical", "redis", "redis_policy", f"Redis siyosati: {redis['maxmemory_policy']}",
                "`maxmemory-policy noeviction` bo'lishi SHART — aks holda sessiya tokenlari o'chiriladi.")
        if not redis.get("maxmemory"):
            add("warning", "redis", "redis_no_limit", "Redis xotira chegarasi (maxmemory) o'rnatilmagan",
                "Redis butun RAM'ni egallab, PostgreSQL'ni siqib chiqarishi mumkin.")
        add(level("redis_memory_pct", redis.get("memory_percent")), "redis", "redis_memory",
            f"Redis xotirasi {redis.get('memory_percent')}%",
            "Oqim (`EVENT_STREAM_MAXLEN`) yoki ingest orqada qolgan — `lag` ni tekshiring.")
        add(level("redis_cpu_pct", (redis.get("rates") or {}).get("cpu_pct")), "redis", "redis_cpu",
            f"Redis yadrosi {(redis.get('rates') or {}).get('cpu_pct')}% band",
            "Redis bitta yadroda ishlaydi — bu uning shifti.")
        if redis.get("rejected_connections"):
            add("warning", "redis", "redis_rejected", f"Redis {redis['rejected_connections']} ulanishni rad etgan",
                "`maxclients` chegarasi.")
        if redis.get("rdb_last_bgsave_status") not in (None, "ok"):
            add("warning", "redis", "redis_bgsave", "Redis diskka saqlay olmadi (BGSAVE)", "Disk joyi va huquqlar.")

    for stream in (snapshot.get("streams") or {}).get("streams", []):
        add(level("stream_lag", stream.get("lag")), "streams", f"lag_{stream['name']}",
            f"«{stream['name']}» oqimi orqada: {stream.get('lag')} yozuv",
            "Ingest ishchisi ulgurmayapti — «Celery» bo'limidagi flush vaqtini tekshiring.")
        if stream.get("dead"):
            add("warning", "streams", f"dead_{stream['name']}",
                f"«{stream['name']}»: {stream['dead']} ta yozuv DB'ga yozilmadi (:dead)",
                "Dalil yo'qolmagan — `:dead` oqimida turibdi. Sababini log'dan aniqlang.")

    # --- Celery ---
    celery = snapshot.get("celery") or {}
    for queue in celery.get("queues", []):
        add(level("celery_queue", queue.get("length")), "celery", f"queue_{queue['name']}",
            f"Celery «{queue['name']}» navbatida {queue['length']} vazifa",
            "Ishchi to'xtagan yoki ulgurmayapti — servis holatini tekshiring.")
    for task in celery.get("tasks", []):
        if task["health"] == "stale":
            critical = task["queue"] == "ingest"
            add("critical" if critical else "warning", "celery", f"stale_{task['name']}",
                f"«{task['name']}» {_fmt_duration(task.get('last_run_age_s'))} dan beri bajarilmagan",
                "beat yoki shu navbat ishchisi ishlamayapti." + (
                    " Hodisalar DB'ga yozilmayapti!" if critical else ""
                ))
        elif task["health"] == "failed":
            add("warning", "celery", f"failed_{task['name']}", f"«{task['name']}» xato bilan tugadi",
                "Celery ishchisi log'ini ko'ring.")
    if celery.get("tasks") and not celery.get("tracking"):
        add("warning", "celery", "celery_untracked", "Celery vazifalari kuzatilmayapti",
            "Ishchilar yangi kod bilan qayta ishga tushirilmagan yoki ishlamayapti.")

    # --- HTTP ---
    window = (snapshot.get("requests") or {}).get("5m") or {}
    if window.get("count", 0) >= 50:
        add(level("http_5xx_pct", window.get("error_pct")), "requests", "http_5xx",
            f"Server xatolari (5xx): {window.get('error_pct')}% (5 daqiqa)",
            "«So'rovlar» jadvalidan qaysi marshrut xato berayotganini toping; journalctl -u proctoring-api.")
        add(level("http_p95_ms", window.get("p95_ms")), "requests", "http_slow",
            f"Javob vaqti p95 = {window.get('p95_ms')} ms (5 daqiqa)",
            "SLO < 500 ms. CPU, PostgreSQL va eng sekin marshrutlarni tekshiring.")

    process = snapshot.get("process") or {}
    silent = (process.get("sessions") or {}).get("silent") or 0
    if silent:
        add("warning", "process", "sessions_silent", f"{silent} ta sessiyadan signal kelmayapti",
            "Client'lar tarmoqdan uzilgan yoki ingest ishchisi `last_heartbeat_at` ni yozmayapti.")

    history = snapshot.get("history") or {}
    if history.get("age_s") is not None and history["age_s"] > HISTORY_INTERVAL_S * 4:
        add("warning", "history", "history_stale",
            f"Grafik tarixi {_fmt_duration(history['age_s'])} dan beri yozilmagan",
            "`proctoring-celery-beat` va `proctoring-celery-maintenance` servislarini tekshiring.")

    order = {"critical": 0, "warning": 1}
    items.sort(key=lambda item: order[item["severity"]])
    return items


# --------------------------------------------------------------------------
# Tarix (Celery, 30 s)
# --------------------------------------------------------------------------
def sample_history() -> dict:
    """Bitta tarix nuqtasi + kunlik disk o'lchovi + (soatiga) storage hajmi."""
    errors: dict[str, str] = {}
    counters: dict[str, float] = {}

    def collect(name, fn, default):
        result = _guarded(errors, name, fn, default)
        if isinstance(result, tuple):
            data, extra = result
            counters.update(extra)
            return data
        return result

    cpu = collect("cpu", host.cpu, {})
    memory = collect("memory", host.memory, {})
    postgres = collect("postgres", collectors.postgres, None)
    paths = host.data_paths({"postgres": (postgres or {}).get("data_directory")})
    disks = collect("disks", lambda: host.disks(paths), {"mounts": [], "devices": []})
    network = collect("network", host.network, {"interfaces": []})
    redis = collect("redis", collectors.redis_info, None)
    streams = collect("streams", collectors.streams, {"streams": []})
    sockets = _guarded(errors, "sockets", host.sockets, {"ports": []})
    process = _guarded(errors, "process", collectors.exam_process, None)

    rates, window = store.compute_rates("history", counters)
    cpu = host.cpu_from_rates(cpu, rates)
    disk_io = host.disks_from_rates(disks, rates)["io"]
    nics = host.network_from_rates(network, rates)["interfaces"]
    redis = collectors.redis_from_rates(redis, rates) if redis else {}
    events_stream = next(
        (s for s in streams.get("streams", []) if s["name"] == "events"), {}
    )
    ports = {port["name"]: port for port in sockets.get("ports", [])}
    pg_rates = collectors.postgres_from_rates(postgres, rates)["rates"] if postgres else {}

    point = {
        "t": int(time.time()),
        "cpu": cpu.get("percent"),
        "user": (cpu.get("breakdown") or {}).get("user"),
        "system": (cpu.get("breakdown") or {}).get("system"),
        "iowait": (cpu.get("breakdown") or {}).get("iowait"),
        "steal": (cpu.get("breakdown") or {}).get("steal"),
        "load1": (cpu.get("load") or [None])[0],
        "mem": memory.get("percent"),
        "swap": memory.get("swap_percent"),
        "disk_r": sum(d["read_bps"] for d in disk_io) if disk_io else None,
        "disk_w": sum(d["write_bps"] for d in disk_io) if disk_io else None,
        "disk_util": max((d["util_pct"] or 0) for d in disk_io) if disk_io else None,
        "disk_await": max(d["await_ms"] for d in disk_io) if disk_io else None,
        "net_rx": sum(n["rx_bps"] or 0 for n in nics) if nics else None,
        "net_tx": sum(n["tx_bps"] or 0 for n in nics) if nics else None,
        "redis_mem": redis.get("used_memory"),
        "redis_cpu": (redis.get("rates") or {}).get("cpu_pct"),
        "lag": events_stream.get("lag"),
        "pg_conn": ((postgres or {}).get("connections") or {}).get("total"),
        "pg_tps": pg_rates.get("commits_per_s"),
        "ws": (ports.get("ws") or {}).get("established"),
        "backlog": (ports.get("api") or {}).get("backlog"),
        "sessions": ((process or {}).get("sessions") or {}).get("in_progress"),
    }
    # Birinchi namunada tezliklar yo'q — CPU `None`; nuqta baribir yoziladi
    # (xotira, ulanishlar bor), grafik bo'shliqni o'zi chizadi.
    client = store.client_or_none()
    if client is not None:
        try:
            history_key = HISTORY_KEY.format(host=store.hostname())
            pipe = client.pipeline(transaction=False)
            pipe.lpush(history_key, json.dumps(point, separators=(",", ":")))
            pipe.ltrim(history_key, 0, HISTORY_POINTS - 1)
            pipe.expire(history_key, 2 * 86400)
            pipe.execute()
            _record_disk_daily(client, disks.get("mounts", []))
        except Exception as exc:  # noqa: BLE001
            store.trip(exc)
    _refresh_storage_usage()
    return {"point": point, "window_s": round(window, 1), "errors": errors}


def _history_meta() -> dict:
    client = store.client_or_none()
    if client is None:
        return {"age_s": None, "points": 0}
    try:
        history_key = HISTORY_KEY.format(host=store.hostname())
        latest = client.lindex(history_key, 0)
        count = client.llen(history_key)
    except Exception as exc:  # noqa: BLE001
        store.trip(exc)
        return {"age_s": None, "points": 0}
    age = None
    if latest:
        try:
            age = max(0, int(time.time() - json.loads(latest)["t"]))
        except (ValueError, KeyError):
            age = None
    return {"age_s": age, "points": int(count or 0), "interval_s": HISTORY_INTERVAL_S}


RANGES = {"1h": 3600, "6h": 6 * 3600, "24h": 86400}


def history(range_name: str) -> dict:
    seconds = RANGES.get(range_name, 3600)
    now = time.time()
    points: list[dict] = []
    client = store.client_or_none()
    if client is not None:
        try:
            raw = client.lrange(HISTORY_KEY.format(host=store.hostname()), 0, seconds // HISTORY_INTERVAL_S + 2)
            for item in reversed(raw):
                try:
                    point = json.loads(item)
                except ValueError:
                    continue
                if point.get("t", 0) >= now - seconds:
                    points.append(point)
        except Exception as exc:  # noqa: BLE001
            store.trip(exc)
    # ~360 nuqtadan ko'p chizish brauzerda behuda: o'rtacha bilan siqiladi.
    step = max(1, -(-len(points) // 360))
    host_points = _downsample(points, step)
    request_step = {"1h": 1, "6h": 2, "24h": 5}.get(range_name, 1)
    return {
        "range": range_name if range_name in RANGES else "1h",
        "host": host_points,
        "requests": request_metrics.series(seconds // 60, request_step),
        "interval_s": HISTORY_INTERVAL_S * step,
    }


def _downsample(points: list[dict], step: int) -> list[dict]:
    if step <= 1:
        return points
    result = []
    for start in range(0, len(points), step):
        chunk = points[start:start + step]
        merged = {"t": chunk[0]["t"]}
        for field in chunk[0]:
            if field == "t":
                continue
            values = [p.get(field) for p in chunk if isinstance(p.get(field), (int, float))]
            if not values:
                merged[field] = None
            elif field in ("cpu", "steal", "iowait", "disk_util", "disk_await", "backlog", "lag"):
                # Cho'qqilar yo'qolmasin: siqilgan grafikda ham eng yomoni.
                merged[field] = max(values)
            else:
                merged[field] = round(sum(values) / len(values), 2)
        result.append(merged)
    return result


# --------------------------------------------------------------------------
# Disk to'lish prognozi
# --------------------------------------------------------------------------
def _record_disk_daily(client, mounts: list[dict]) -> None:
    """Har kun uchun mount'dagi band joy (kunning oxirgi o'lchovi)."""
    if not mounts:
        return
    disk_key = DISK_DAILY_KEY.format(host=store.hostname())
    today = timezone.localdate()
    oldest = (today - timedelta(days=DISK_DAILY_KEEP_DAYS)).isoformat()
    pipe = client.pipeline(transaction=False)
    for mount in mounts:
        pipe.hset(disk_key, f"{today.isoformat()}|{mount['mount']}", int(mount["used"]))
    pipe.expire(disk_key, (DISK_DAILY_KEEP_DAYS + 5) * 86400)
    pipe.execute()
    stale = [field for field in client.hkeys(disk_key) if field.split("|", 1)[0] < oldest]
    if stale:
        client.hdel(disk_key, *stale)


_forecast_cache: dict[str, tuple[float, dict]] = {}


def _daily_usage() -> dict[str, dict[str, int]]:
    """{mount: {sana: band_bayt}} — jarayon ichida 5 daqiqa keshlanadi."""
    hit = _forecast_cache.get("daily")
    if hit and time.monotonic() - hit[0] < 300:
        return hit[1]
    result: dict[str, dict[str, int]] = {}
    client = store.client_or_none()
    if client is not None:
        try:
            for field, value in (client.hgetall(DISK_DAILY_KEY.format(host=store.hostname())) or {}).items():
                day, _, mount = field.partition("|")
                result.setdefault(mount, {})[day] = int(value)
        except Exception as exc:  # noqa: BLE001
            store.trip(exc)
    _forecast_cache["daily"] = (time.monotonic(), result)
    return result


def _forecast(mount: dict) -> dict:
    """
    Kunlik o'sish (oxirgi ≤14 kun) va necha kunda to'lishi.

    Kamida bir kunlik tarix kerak; o'sish yo'q yoki manfiy (tozalash
    vazifasi ishlagan) bo'lsa — prognoz yo'q.
    """
    days = _daily_usage().get(mount["mount"]) or {}
    today = timezone.localdate()
    start = (today - timedelta(days=14)).isoformat()
    candidates = sorted(day for day in days if start <= day < today.isoformat())
    if not candidates:
        return {"growth_per_day": None, "days_left": None}
    first_day = candidates[0]
    span = (today - date.fromisoformat(first_day)).days
    if span <= 0:
        return {"growth_per_day": None, "days_left": None}
    growth = (mount["used"] - days[first_day]) / span
    if growth <= 0:
        return {"growth_per_day": round(growth), "days_left": None}
    return {"growth_per_day": round(growth), "days_left": int(mount["free"] / growth)}


# --------------------------------------------------------------------------
# Rasmlar qancha joy egallaydi (soatiga bir marta)
# --------------------------------------------------------------------------
def storage_usage_cached() -> dict | None:
    client = store.client_or_none()
    if client is None:
        return None
    try:
        raw = client.get(STORAGE_USAGE_KEY)
    except Exception as exc:  # noqa: BLE001
        store.trip(exc)
        return None
    return json.loads(raw) if raw else None


def _refresh_storage_usage(*, force: bool = False) -> None:
    """
    Skrinshot, dalil va FaceID kadrlari soni/hajmi — bazadagi `file_size`
    bo'yicha (diskni aylanib chiqish millionlab fayl uchun soatlab ketardi).

    `SUM` katta jadvalda seq scan — shuning uchun so'rov yo'lida emas,
    Celery'da va soatiga bir marta.
    """
    current = storage_usage_cached()
    if not force and current and time.time() - current.get("computed_at", 0) < STORAGE_USAGE_EVERY_S:
        return
    from django.db import connections, transaction
    from django.db.models import Count, Q, Sum

    from apps.proctoring.models import (
        EvidenceArtifact, FaceVerificationLog, ProctoringScreenshot, ScreenshotMeta,
    )

    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        with transaction.atomic(using="default"):
            with connections["default"].cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = '60s'")
            shots = ProctoringScreenshot.objects.aggregate(
                count=Count("id"), bytes=Sum("file_size"),
                today_count=Count("id", filter=Q(captured_at__gte=start)),
                today_bytes=Sum("file_size", filter=Q(captured_at__gte=start)),
            )
            s3_shots = ScreenshotMeta.objects.aggregate(count=Count("id"), bytes=Sum("size_bytes"))
            evidence = EvidenceArtifact.objects.exclude(file_path="").aggregate(
                count=Count("id"), bytes=Sum("size_bytes"),
            )
            faces = FaceVerificationLog.objects.exclude(image_path="").count()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Monitoring: storage hajmi hisoblanmadi: %s", exc)
        return
    payload = {
        "computed_at": time.time(),
        "screenshots": {key: int(value or 0) for key, value in shots.items()},
        "s3_screenshots": {key: int(value or 0) for key, value in s3_shots.items()},
        "evidence": {key: int(value or 0) for key, value in evidence.items()},
        "face_images": {"count": int(faces)},
        "root": str(settings.SCREENSHOT_STORAGE["ROOT"]),
    }
    client = store.client_or_none()
    if client is None:
        return
    try:
        client.set(STORAGE_USAGE_KEY, json.dumps(payload), ex=STORAGE_USAGE_EVERY_S * 3)
    except Exception as exc:  # noqa: BLE001
        store.trip(exc)
