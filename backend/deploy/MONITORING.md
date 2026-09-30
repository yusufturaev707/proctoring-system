# Monitoring — yuklama testi va imtihon kuni

SLO chegaralari: CPU < 70%, RAM < 80%, **swap = 0** (swap — SLO buzilishi),
xatolar < 0.1%, p95 (client API) < 500 ms.

| Nima | Buyruq | Chegara |
|---|---|---|
| CPU/RAM/swap | `htop`, `vmstat 5` (`si/so` = 0) | CPU < 70%, RAM < 80% |
| Disk | `iostat -x 5` (`%util`, `w_await`) | `%util` < 70%; skrinshot ~46 yozuv/s x 2 fsync |
| Ulanishlar | `ss -s`, `ss -ltn 'sport = :8002'` (Recv-Q = gunicorn backlog) | Recv-Q ~ 0 |
| nginx | `curl -s 127.0.0.1/nginx_status` | 429/502 o'smasin (access log) |
| PgBouncer | `psql -p 6432 pgbouncer -c 'SHOW POOLS'`, `SHOW STATS` | `cl_waiting` = 0 |
| PostgreSQL | `pg_stat_activity` (state, wait_event), `pg_stat_statements` (`shared_preload_libraries`), bloklar: `SELECT * FROM pg_locks WHERE NOT granted` | uzoq `idle in transaction` yo'q |
| Redis | `redis-cli INFO memory` (`used_memory` < maxmemory 70%), `XINFO GROUPS proctoring:events` (`lag`, `pending`), `XLEN proctoring:events:dead` | lag < 10 000, dead o'smaydi |
| Celery | `redis-cli -n 3 LLEN ingest`, `celery -A config inspect active` | navbat ~0; `flush_session_state` < 5 s |

O'lchangan bazaviy qiymatlar (L2, dev Windows, perf DB 300k sessiya / 7 mln hodisa):
flush_event_buffer ~7000 hodisa/s, flush_session_state 5000 sessiya 2.0 s,
Redis 684 B/sessiya + ~190 B/hodisa (oqim `EVENT_STREAM_MAXLEN` 500k -> ~95 MB).

Ixtiyoriy: Prometheus + node_exporter, postgres_exporter, redis_exporter,
Grafana (yoki netdata) — yuqoridagi ko'rsatkichlarning o'zi.
