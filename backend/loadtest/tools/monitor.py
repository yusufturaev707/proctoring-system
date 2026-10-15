"""
Yuklama sinovi paytida stend resurslarini yozib boradi (CSV, har N soniyada).

Ikki qism, chunki bog'liqliklar ikki venv'da:

    # jarayonlar (psutil — loadtest venv'ida bor)
    loadtest\\.venv\\Scripts\\python tools\\monitor.py proc --out results\\run\\proc.csv
    # baza va Redis (psycopg2/redis — backend venv'ida bor)
    .venv\\Scripts\\python loadtest\\tools\\monitor.py data --out loadtest\\results\\run\\data.csv

NIMA UCHUN JARAYON GURUHLARI: stend, Postgres, Redis (Docker VM) va Locust
BITTA mashinada — "server sekin" mi yoki "generator CPU'ni yeb qo'ydi" mi,
faqat guruhlar bo'yicha CPU ajratilganda ko'rinadi. Guruh — `local_stack.ps1`
yozgan `pids.txt` dagi ("nom pid") ildiz jarayon va uning BARCHA avlodlari (uvicorn
ishchilari `multiprocessing` orqali tug'iladi, buyruq satrida port yo'q).
"""

from __future__ import annotations

import argparse
import csv
import os
import time
from pathlib import Path

_LT = Path(__file__).resolve().parent.parent  # backend/loadtest


def _groups(extra_pid_files: list[str]) -> dict[str, set[int]]:
    import psutil

    groups: dict[str, set[int]] = {}
    pid_file = _LT / "results" / "local_stack" / "pids.txt"
    lines = pid_file.read_text().splitlines() if pid_file.exists() else []
    for line in lines:
        # "http3 1234" -> guruh "http" (alohida HTTP jarayonlari bitta guruh).
        name, _, pid = line.strip().rpartition(" ")
        if pid.isdigit():
            groups.setdefault(name.rstrip("0123456789") or "?", set()).update(_tree(int(pid)))
    for path in extra_pid_files:
        for pid in Path(path).read_text().split():
            groups.setdefault("locust", set()).update(_tree(int(pid)))
    for proc in psutil.process_iter(["name"]):
        name = (proc.info["name"] or "").lower()
        if name == "postgres.exe":
            groups.setdefault("postgres", set()).add(proc.pid)
        elif name.startswith("vmmem"):
            # Docker Desktop (WSL2) VM — Redis konteyneri shu ichida.
            groups.setdefault("docker_vm", set()).add(proc.pid)
    return groups


def _tree(pid: int) -> set[int]:
    import psutil

    try:
        root = psutil.Process(pid)
        return {root.pid, *(c.pid for c in root.children(recursive=True))}
    except psutil.Error:
        return set()


def run_proc(out: Path, interval: float, extra: list[str]) -> None:
    import psutil

    cores = psutil.cpu_count() or 1
    cache: dict[int, psutil.Process] = {}
    fields = None
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = None
        psutil.cpu_percent(None)
        while True:
            groups = _groups(extra)  # uvicorn ishchisi qayta tug'ilsa ham ko'rinadi
            for pids in groups.values():
                for pid in pids:
                    if pid not in cache:
                        try:
                            cache[pid] = psutil.Process(pid)
                            cache[pid].cpu_percent(None)
                        except psutil.Error:
                            pass
            time.sleep(interval)
            vm = psutil.virtual_memory()
            row = {
                "ts": round(time.time(), 1),
                "cpu_total_pct": psutil.cpu_percent(None),
                "ram_used_gb": round((vm.total - vm.available) / 2**30, 2),
            }
            for name in sorted(groups):
                cpu = rss = 0.0
                alive = 0
                for pid in groups[name]:
                    proc = cache.get(pid)
                    if proc is None:
                        continue
                    try:
                        cpu += proc.cpu_percent(None)
                        rss += proc.memory_info().rss
                        alive += 1
                    except psutil.Error:
                        cache.pop(pid, None)
                # Bitta yadro = 100% (psutil jarayon CPU'si) -> mashinaning foizi.
                row[f"{name}_cpu_pct"] = round(cpu / cores, 1)
                row[f"{name}_rss_mb"] = round(rss / 2**20)
                row[f"{name}_procs"] = alive
            if fields is None or set(row) - set(fields):
                fields = list(dict.fromkeys([*(fields or []), *row]))
                writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
            writer.writerow(row)
            fh.flush()


def run_data(out: Path, interval: float, db: str) -> None:
    import psycopg2
    import redis

    from dotenv import dotenv_values

    env = dotenv_values(_LT.parent / ".env")
    conn = psycopg2.connect(
        host=env.get("POSTGRES_HOST", "127.0.0.1"), port=env.get("POSTGRES_PORT", "5432"),
        user=env.get("POSTGRES_USER", "postgres"), password=env.get("POSTGRES_PASSWORD", ""),
        dbname=db,
    )
    conn.autocommit = True
    base = (os.getenv("LT_REDIS_URL") or env.get("REDIS_URL") or "redis://127.0.0.1:6379").rstrip("/")
    state = redis.Redis.from_url(f"{base}/7")
    broker = redis.Redis.from_url(f"{base}/8")
    fields = None
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = None
        while True:
            row = {"ts": round(time.time(), 1)}
            cur = conn.cursor()
            cur.execute(
                "select count(*), count(*) filter (where datname=%s), "
                "count(*) filter (where datname=%s and state='active'), "
                "count(*) filter (where datname=%s and wait_event_type='Lock') "
                "from pg_stat_activity", (db, db, db),
            )
            row["pg_conn_total"], row["pg_conn_lt"], row["pg_active_lt"], row["pg_lock_wait_lt"] = cur.fetchone()
            cur.execute("show max_connections")
            row["pg_max_conn"] = int(cur.fetchone()[0])
            cur.execute("select status, count(*) from exam_session group by status")
            for status, n in cur.fetchall():
                row[f"sess_{status}"] = n
            cur.execute("select count(*) from proctoring_event")
            row["events_db"] = cur.fetchone()[0]
            cur.execute("select count(*) from proctoring_screenshot")
            row["screenshots_db"] = cur.fetchone()[0]
            cur.execute(
                "select xact_commit, xact_rollback, deadlocks, temp_bytes "
                "from pg_stat_database where datname=%s", (db,),
            )
            row["pg_commit"], row["pg_rollback"], row["pg_deadlocks"], row["pg_temp_bytes"] = cur.fetchone()
            cur.close()
            for key, short in (("proctoring:events", "ev"), ("proctoring:screenshots", "shot")):
                try:
                    row[f"{short}_xlen"] = state.xlen(key)
                    groups = state.xinfo_groups(key)
                    row[f"{short}_lag"] = sum(int(g.get("lag") or 0) for g in groups)
                    row[f"{short}_pending"] = sum(int(g.get("pending") or 0) for g in groups)
                    row[f"{short}_dead"] = state.xlen(f"{key}:dead")
                except redis.RedisError:
                    pass
            info = state.info()
            row["redis_clients"] = info.get("connected_clients")
            row["redis_mem_mb"] = round(info.get("used_memory", 0) / 2**20, 1)
            row["redis_ops"] = info.get("instantaneous_ops_per_sec")
            for queue in ("ingest", "maintenance", "default"):
                row[f"celery_q_{queue}"] = broker.llen(queue)
            if fields is None or set(row) - set(fields):
                fields = list(dict.fromkeys([*(fields or []), *row]))
                writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
            writer.writerow(row)
            fh.flush()
            time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("part", choices=["proc", "data"])
    parser.add_argument("--out", required=True)
    parser.add_argument("--interval", type=float, default=10.0)
    parser.add_argument("--db", default="proctoring_loadtest")
    parser.add_argument("--locust-pids", nargs="*", default=[],
                        help="Locust jarayonlari PID fayllari (CPU guruhi uchun)")
    args = parser.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.part == "proc":
        run_proc(out, args.interval, args.locust_pids)
    else:
        run_data(out, args.interval, args.db)


if __name__ == "__main__":
    main()
