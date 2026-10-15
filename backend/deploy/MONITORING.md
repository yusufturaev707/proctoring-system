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

## Panel: «Server holati» (`/system`)

Yuqoridagi buyruqlarning asosiylari panelda bitta sahifada (`apps/monitoring`,
ruxsat `system.view`, faqat respublika darajasi): CPU (yadrolar, iowait,
**steal** — ESXi xosti band), RAM/swap, PSI, disklar (inode, `%util`,
`await`, to'lish prognozi), portlar navbati (`ss -ltn` Recv-Q), systemd
servislari (holat, `NRestarts`, CPU, xotira), PostgreSQL, Redis, ingest
oqimlari, Celery davriy vazifalari va HTTP so'rovlar (p50/p95/p99, 5xx,
marshrutlar). Muammolar yuqoridagi SLO chegaralari bilan
(`apps/monitoring/thresholds.py`) — sabab va "nima qilish kerak" bilan.

* Tarix (24 soat, 30 s) — `monitoring.sample_system` (beat + maintenance).
* nginx ko'rsatkichlari — `SYSTEM_MONITOR_NGINX_STATUS_URL` va
  `nginx.conf.example` oxiridagi lokal `8081` bloki.
* Bitta node uchun mo'ljallangan: xost ko'rsatkichlari so'rovni bajargan
  serverniki. Bir nechta node — Prometheus + node_exporter.

