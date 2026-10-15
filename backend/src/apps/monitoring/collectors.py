"""
Infratuzilma yig'uvchilari: PostgreSQL, Redis (+ ingest oqimlari),
nginx va imtihon jarayoni.

Xavfsizlik: SQL so'rov MATNI, ulanish satrlari, buyruq qatorlari va
muhit o'zgaruvchilari QAYTARILMAYDI — so'rov matnida JSHSHIR yoki
token bo'lishi mumkin, panel esa ularni ko'rsatish joyi emas. Faqat
sonlar, holatlar va davomiyliklar.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import time
from urllib.parse import urlsplit

from django.conf import settings
from django.db import connections, transaction

from apps.common.redis_client import get_redis

logger = logging.getLogger(__name__)

#: Monitoring so'rovi hech qachon bazani band qilmasin.
_PG_STATEMENT_TIMEOUT = "3s"


# --------------------------------------------------------------------------
# PostgreSQL
# --------------------------------------------------------------------------
def postgres() -> tuple[dict, dict]:
    connection = connections["default"]
    data: dict = {}
    counters: dict[str, float] = {}
    with transaction.atomic(using="default"), connection.cursor() as cursor:
        cursor.execute(f"SET LOCAL statement_timeout = '{_PG_STATEMENT_TIMEOUT}'")
        cursor.execute(
            """
            SELECT current_setting('server_version'),
                   extract(epoch FROM now() - pg_postmaster_start_time())::bigint,
                   current_setting('max_connections')::int,
                   pg_database_size(current_database()),
                   current_database()
            """
        )
        version, uptime, max_connections, size, name = cursor.fetchone()
        data.update({
            "version": version,
            "uptime_s": int(uptime),
            "database": name,
            "size": int(size),
            "max_connections": int(max_connections),
        })

        # Barcha bazalar bo'yicha: `max_connections` — server chegarasi.
        cursor.execute(
            """
            SELECT coalesce(state, 'other'),
                   (wait_event_type = 'Lock') AS lock_wait,
                   count(*),
                   max(extract(epoch FROM now() - xact_start))
                       FILTER (WHERE state LIKE 'idle in transaction%'),
                   max(extract(epoch FROM now() - query_start))
                       FILTER (WHERE state = 'active')
            FROM pg_stat_activity
            WHERE backend_type = 'client backend' AND pid <> pg_backend_pid()
            GROUP BY 1, 2
            """
        )
        by_state: dict[str, int] = {}
        lock_waiting = 0
        idle_tx_max = 0.0
        active_max = 0.0
        for state, lock_wait, count, idle_tx, active in cursor.fetchall():
            by_state[state] = by_state.get(state, 0) + int(count)
            if lock_wait:
                lock_waiting += int(count)
            idle_tx_max = max(idle_tx_max, float(idle_tx or 0))
            active_max = max(active_max, float(active or 0))
        total = sum(by_state.values()) + 1  # + shu monitoring ulanishi
        data["connections"] = {
            "total": total,
            "percent": round(total / max_connections * 100, 1) if max_connections else None,
            "active": by_state.get("active", 0),
            "idle": by_state.get("idle", 0),
            "idle_in_transaction": sum(
                count for state, count in by_state.items() if state.startswith("idle in transaction")
            ),
            "lock_waiting": lock_waiting,
            "longest_query_s": round(active_max, 1),
            "longest_idle_tx_s": round(idle_tx_max, 1),
        }

        cursor.execute(
            """
            SELECT xact_commit, xact_rollback, blks_read, blks_hit, deadlocks,
                   temp_bytes, tup_inserted, tup_updated, tup_deleted
            FROM pg_stat_database WHERE datname = current_database()
            """
        )
        row = cursor.fetchone()
        if row:
            names = (
                "xact_commit", "xact_rollback", "blks_read", "blks_hit", "deadlocks",
                "temp_bytes", "tup_inserted", "tup_updated", "tup_deleted",
            )
            for field, value in zip(names, row):
                counters[f"pg.{field}"] = float(value or 0)
            data["deadlocks_total"] = int(row[4] or 0)

    data["tables"] = _pg_tables(connection)
    data["data_directory"] = _pg_data_directory(connection)
    return data, counters


def _pg_tables(connection) -> list[dict]:
    """
    Eng katta jadvallar. Partitsiyalar ota jadval nomi bilan yig'iladi
    (`proctoring_event` — kunlik partitsiyalar). `dead_tuples` — tez-tez
    yangilanadigan `exam_session` da autovacuum ulguryaptimi.
    """
    try:
        with transaction.atomic(using="default"), connection.cursor() as cursor:
            cursor.execute(f"SET LOCAL statement_timeout = '{_PG_STATEMENT_TIMEOUT}'")
            cursor.execute(
                """
                SELECT coalesce(parent.relname, c.relname) AS name,
                       sum(pg_total_relation_size(c.oid))::bigint,
                       sum(greatest(c.reltuples, 0))::bigint,
                       sum(coalesce(s.n_dead_tup, 0))::bigint,
                       count(*)
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                LEFT JOIN pg_inherits i ON i.inhrelid = c.oid
                LEFT JOIN pg_class parent ON parent.oid = i.inhparent
                LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
                WHERE n.nspname = 'public' AND c.relkind = 'r'
                GROUP BY 1
                ORDER BY 2 DESC
                LIMIT 8
                """
            )
            return [
                {
                    "name": name,
                    "size": int(size),
                    "rows": int(rows),
                    "dead_rows": int(dead),
                    "partitions": int(parts) if parts > 1 else 0,
                }
                for name, size, rows, dead, parts in cursor.fetchall()
            ]
    except Exception as exc:  # noqa: BLE001
        logger.debug("Monitoring: jadval o'lchamlari o'qilmadi: %s", exc)
        return []


def _pg_data_directory(connection) -> str | None:
    """`pg_read_all_settings` huquqi bo'lmasa — `None` (disk kartasida ko'rinmaydi)."""
    try:
        with transaction.atomic(using="default"), connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('data_directory')")
            return cursor.fetchone()[0]
    except Exception:  # noqa: BLE001
        return None


def postgres_from_rates(data: dict, rates: dict) -> dict:
    hits = rates.get("pg.blks_hit")
    reads = rates.get("pg.blks_read")
    cache_hit = None
    if hits is not None and reads is not None and hits + reads > 0:
        cache_hit = round(hits / (hits + reads) * 100, 2)
    data["rates"] = {
        "commits_per_s": _round(rates.get("pg.xact_commit")),
        "rollbacks_per_s": _round(rates.get("pg.xact_rollback")),
        "inserts_per_s": _round(rates.get("pg.tup_inserted")),
        "updates_per_s": _round(rates.get("pg.tup_updated")),
        "deletes_per_s": _round(rates.get("pg.tup_deleted")),
        "temp_bytes_per_s": _round(rates.get("pg.temp_bytes")),
        "deadlocks_per_s": _round(rates.get("pg.deadlocks"), 4),
        # Diskdan emas, xotiradan o'qilgan bloklar ulushi: < 99% — RAM
        # (`shared_buffers`) yetmayapti yoki indeks yo'q so'rov bor.
        "cache_hit_pct": cache_hit,
    }
    return data


def _round(value, digits: int = 1):
    return None if value is None else round(value, digits)


# --------------------------------------------------------------------------
# Redis
# --------------------------------------------------------------------------
def redis_info() -> tuple[dict, dict]:
    client = get_redis()
    info = client.info()
    maxmemory = int(info.get("maxmemory") or 0)
    used = int(info.get("used_memory") or 0)
    keyspace = {
        name: int(value.get("keys", 0))
        for name, value in info.items()
        if re.fullmatch(r"db\d+", str(name)) and isinstance(value, dict)
    }
    data = {
        "version": info.get("redis_version"),
        "uptime_s": int(info.get("uptime_in_seconds") or 0),
        "clients": int(info.get("connected_clients") or 0),
        "blocked_clients": int(info.get("blocked_clients") or 0),
        "maxclients": int(info.get("maxclients") or 0),
        "used_memory": used,
        "used_memory_rss": int(info.get("used_memory_rss") or 0),
        "used_memory_peak": int(info.get("used_memory_peak") or 0),
        "maxmemory": maxmemory,
        "memory_percent": round(used / maxmemory * 100, 1) if maxmemory else None,
        "maxmemory_policy": info.get("maxmemory_policy"),
        "fragmentation": info.get("mem_fragmentation_ratio"),
        "ops_per_s": int(info.get("instantaneous_ops_per_sec") or 0),
        "evicted_keys": int(info.get("evicted_keys") or 0),
        "rejected_connections": int(info.get("rejected_connections") or 0),
        "rdb_last_bgsave_status": info.get("rdb_last_bgsave_status"),
        "rdb_changes_since_last_save": int(info.get("rdb_changes_since_last_save") or 0),
        "rdb_last_save_age_s": (
            int(time.time() - int(info["rdb_last_save_time"])) if info.get("rdb_last_save_time") else None
        ),
        "aof_enabled": bool(int(info.get("aof_enabled") or 0)),
        "aof_last_write_status": info.get("aof_last_write_status"),
        "keyspace": keyspace,
    }
    counters = {
        "redis.cpu": float(info.get("used_cpu_sys") or 0) + float(info.get("used_cpu_user") or 0),
        "redis.commands": float(info.get("total_commands_processed") or 0),
        "redis.hits": float(info.get("keyspace_hits") or 0),
        "redis.misses": float(info.get("keyspace_misses") or 0),
        "redis.net_in": float(info.get("total_net_input_bytes") or 0),
        "redis.net_out": float(info.get("total_net_output_bytes") or 0),
    }
    return data, counters


def redis_from_rates(data: dict, rates: dict) -> dict:
    cpu = rates.get("redis.cpu")
    hits, misses = rates.get("redis.hits"), rates.get("redis.misses")
    data["rates"] = {
        # Redis buyruqlarni BITTA yadroda bajaradi: 100% — uning shifti,
        # server CPU'si bo'sh tursa ham.
        "cpu_pct": None if cpu is None else round(cpu * 100, 1),
        "commands_per_s": _round(rates.get("redis.commands")),
        "hit_pct": (
            round(hits / (hits + misses) * 100, 1)
            if hits is not None and misses is not None and hits + misses > 0 else None
        ),
        "net_in_bps": _round(rates.get("redis.net_in"), 0),
        "net_out_bps": _round(rates.get("redis.net_out"), 0),
    }
    return data


def streams() -> tuple[dict, dict]:
    """
    Ikki bosqichli yozish oqimlari: kirish tezligi, `lag` (hali o'qilmagan),
    `pending` (o'qilgan, lekin DB'ga yozilmagan), `dead` (yozib bo'lmagan).
    """
    from apps.proctoring.services.stream import CONSUMER_GROUP, dead_letter_key

    client = get_redis()
    conf = settings.PROCTORING
    names = {"events": conf["EVENT_STREAM_KEY"], "screenshots": conf["SCREENSHOT_STREAM_KEY"]}
    result, counters = [], {}
    for label, stream in names.items():
        entry = {"name": label, "key": stream, "length": 0, "lag": None, "pending": 0, "dead": 0, "consumers": 0}
        try:
            info = client.xinfo_stream(stream)
            entry["length"] = int(info.get("length") or 0)
            added = info.get("entries-added")
            if added is not None:
                counters[f"stream.{label}.added"] = float(added)
        except Exception:  # noqa: BLE001 — oqim hali yaratilmagan
            pass
        try:
            for group in client.xinfo_groups(stream):
                if group.get("name") == CONSUMER_GROUP:
                    entry["lag"] = group.get("lag")
                    entry["pending"] = int(group.get("pending") or 0)
                    entry["consumers"] = int(group.get("consumers") or 0)
        except Exception:  # noqa: BLE001
            pass
        try:
            entry["dead"] = int(client.xlen(dead_letter_key(stream)))
        except Exception:  # noqa: BLE001
            pass
        result.append(entry)
    return {"streams": result}, counters


def streams_from_rates(data: dict, rates: dict) -> dict:
    for entry in data.get("streams", []):
        rate = rates.get(f"stream.{entry['name']}.added")
        entry["in_per_s"] = None if rate is None else round(rate, 1)
    return data


# --------------------------------------------------------------------------
# nginx (`stub_status`)
# --------------------------------------------------------------------------
_NGINX_RE = re.compile(
    r"Active connections:\s*(\d+).*?(\d+)\s+(\d+)\s+(\d+).*?"
    r"Reading:\s*(\d+)\s*Writing:\s*(\d+)\s*Waiting:\s*(\d+)",
    re.S,
)


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _fetch_status(url: str):
    """
    `stub_status` sahifasi yoki xato kodi (`(response, None)` / `(None, kod)`).

    LOOPBACK MANZILDA SERTIFIKAT TEKSHIRILMAYDI. Sabab: `nginx_status`
    odatda asosiy HTTPS server blokida (`allow 127.0.0.1`), 80-port esa
    hammasini HTTPS'ga yo'naltiradi — backend uni faqat
    `https://127.0.0.1/nginx_status` bilan o'qiy oladi, sertifikat esa
    domenga berilgan va IP bilan HECH QACHON tekshiruvdan o'tmaydi.
    Domen orqali so'rasa — manba manzil 127.0.0.1 bo'lmaydi va nginx
    `deny all` beradi. Loopback trafigi mashinadan chiqmaydi, ya'ni TLS
    tekshiruvi himoya qiladigan "tarmoqdagi oraliq odam" bu yerda yo'q.
    Boshqa manzillarda tekshiruv yoqiq qoladi.

    Yo'naltirishga ergashilmaydi: `http://` → `https://domen` ga o'tib,
    tashqi manzilga so'rov yuborilmasin; o'rniga aniq maslahat beriladi.
    """
    import warnings

    import requests
    from urllib3.exceptions import InsecureRequestWarning

    loopback = _is_loopback(urlsplit(url).hostname or "")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", InsecureRequestWarning)
            response = requests.get(url, timeout=1.0, verify=not loopback, allow_redirects=False)
    except requests.exceptions.SSLError:
        return None, "tls"
    except requests.exceptions.Timeout:
        return None, "timeout"
    except requests.exceptions.RequestException:
        return None, "unreachable"
    if response.is_redirect or response.is_permanent_redirect:
        return None, "redirect"
    if response.status_code == 403:
        return None, "forbidden"
    if response.status_code == 404:
        return None, "not_found"
    if response.status_code >= 400:
        return None, f"http_{response.status_code}"
    return response, None


def nginx() -> tuple[dict, dict]:
    url = settings.SYSTEM_MONITOR.get("NGINX_STATUS_URL") or ""
    if not url:
        return {"available": False, "configured": False}, {}
    response, error = _fetch_status(url)
    if error:
        return {"available": False, "configured": True, "error": error, "url": url}, {}
    match = _NGINX_RE.search(response.text)
    if not match:
        return {"available": False, "configured": True, "error": "parse", "url": url}, {}
    active, accepts, handled, requests_total, reading, writing, waiting = (int(v) for v in match.groups())
    data = {
        "available": True,
        "configured": True,
        "active": active,
        "reading": reading,
        "writing": writing,
        "waiting": waiting,
        # accepts − handled > 0: `worker_connections` chegarasiga yetilgan.
        "dropped_total": max(0, accepts - handled),
    }
    counters = {"nginx.accepts": float(accepts), "nginx.requests": float(requests_total)}
    return data, counters


def nginx_from_rates(data: dict, rates: dict) -> dict:
    if data.get("available"):
        data["requests_per_s"] = _round(rates.get("nginx.requests"))
        data["accepts_per_s"] = _round(rates.get("nginx.accepts"))
    return data


# --------------------------------------------------------------------------
# Imtihon jarayoni
# --------------------------------------------------------------------------
def exam_process() -> dict:
    """
    Hozir nima bo'lyapti: ochiq sessiyalar holati, aloqasi uzilganlar,
    onlayn kompyuterlar. Faqat indeksli ustunlar (`status`,
    `last_heartbeat_at`) — 300k sessiyali bazada ham millisoniyalar.
    """
    from datetime import timedelta

    from django.db.models import Count
    from django.utils import timezone

    from apps.devices.models import Computer
    from apps.proctoring.models import ExamSession

    open_statuses = [
        status for status in ExamSession.Status.values
        if status not in ExamSession.TERMINAL_STATUSES
    ]
    by_status = dict(
        ExamSession.objects.filter(status__in=open_statuses)
        .values("status")
        .annotate(n=Count("id"))
        .values_list("status", "n")
    )
    timeout = int(settings.PROCTORING.get("HEARTBEAT_TIMEOUT", 90))
    # `last_heartbeat_at` ni ingest ishchisi ~10 s kechikish bilan yozadi
    # (write-behind) — chegara shunga zaxira bilan.
    silent = ExamSession.objects.filter(
        status=ExamSession.Status.IN_PROGRESS,
        last_heartbeat_at__lt=timezone.now() - timedelta(seconds=timeout),
    ).count()
    computers = dict(
        Computer.objects.filter(deleted_at__isnull=True)
        .values("status")
        .annotate(n=Count("id"))
        .values_list("status", "n")
    )
    return {
        "sessions": {
            "by_status": by_status,
            "open": sum(by_status.values()),
            "in_progress": by_status.get(ExamSession.Status.IN_PROGRESS, 0),
            "silent": silent,
            "heartbeat_timeout_s": timeout,
        },
        "computers": {
            "online": computers.get(Computer.Status.ONLINE, 0),
            "in_exam": computers.get(Computer.Status.IN_EXAM, 0),
            "offline": computers.get(Computer.Status.OFFLINE, 0),
            "blocked": computers.get(Computer.Status.BLOCKED, 0),
            "total": sum(computers.values()),
        },
    }
