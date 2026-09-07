# Deploy

Tizim **to'rt xil process** dan iborat. Ularni bitta process'ga birlashtirmang —
har birining yuklama profili boshqacha.

| Process | Buyruq | Nima qiladi | Nechta kerak (10k talaba) |
|---|---|---|---|
| **HTTP API** | `gunicorn config.wsgi:application -c deploy/gunicorn.conf.py` | REST API, admin | 4–8 instansiya |
| **WebSocket** | `uvicorn config.asgi:application --host 0.0.0.0 --port 8001` | Realtime | 2–4 instansiya |
| **Celery worker** | `celery -A config worker -Q ingest -c 4` | Buffer → PostgreSQL | 2–4 (ingest), 1 (maintenance) |
| **Celery beat** | `celery -A config beat` | Periodik vazifalar | **Aynan 1 ta** |

> `celery beat` bir nechta ishga tushirilsa, har bir vazifa bir necha marta
> bajariladi. Bu ingest buffer'ida ma'lumot dublikatiga olib keladi.

## Ishga tushirish tartibi

```bash
# 1. Sxema
python manage.py migrate

# 2. Partitsiyalash (yuqori yuklamada MAJBURIY)
python manage.py setup_partitions --apply --days 30

# 3. Boshlang'ich ma'lumot
python manage.py seed_base_data
python manage.py createsuperuser

# 4. Statik fayllar
python manage.py collectstatic --noinput
```

## Celery navbatlari

```bash
# Ingest — eng yuqori ustuvorlik, alohida worker'lar
celery -A config worker -Q ingest -c 4 --max-tasks-per-child=1000

# Texnik xizmat — sekin vazifalar asosiy oqimga xalaqit bermasin
celery -A config worker -Q maintenance,default -c 2

# Rejalashtiruvchi — FAQAT BITTA
celery -A config beat --scheduler celery.beat:PersistentScheduler
```

## Infratuzilma

### PgBouncer (majburiy, 1000+ rps da)

```ini
[databases]
proctoring = host=127.0.0.1 port=5432 dbname=proctoring

[pgbouncer]
pool_mode = transaction
max_client_conn = 3000
default_pool_size = 40
reserve_pool_size = 10
server_idle_timeout = 60
```

`.env` da `USE_PGBOUNCER=true` qo'ying — `CONN_MAX_AGE` avtomatik 0 bo'ladi.
Aks holda prepared statement konfliktlari chiqadi.

### PostgreSQL sozlamalari

```ini
max_connections = 200          # PgBouncer ortida ko'p kerak emas
shared_buffers = 8GB           # RAM ning ~25%
effective_cache_size = 24GB    # RAM ning ~75%
work_mem = 32MB
maintenance_work_mem = 2GB
wal_buffers = 64MB
checkpoint_completion_target = 0.9
max_wal_size = 8GB
random_page_cost = 1.1         # SSD uchun

# Ingest jadvallarida autovacuum tez-tez ishlashi kerak
autovacuum_vacuum_scale_factor = 0.02
autovacuum_analyze_scale_factor = 0.01
autovacuum_max_workers = 6
```

### Redis

```ini
maxmemory 8gb
maxmemory-policy noeviction    # MUHIM: sessiya holati eviction'ga tushmasin
appendonly yes
appendfsync everysec
```

> `allkeys-lru` **ishlatmang**. Redis to'lganda faol sessiya tokenlari
> o'chib ketishi mumkin va imtihon o'rtasida barcha talabgorlar chiqib qoladi.

### MinIO / S3

Bucket lifecycle qoidasi (90 kundan keyin arxivga):

```json
{
  "Rules": [{
    "ID": "proctoring-retention",
    "Status": "Enabled",
    "Expiration": { "Days": 90 }
  }]
}
```

## Monitoring

Kuzatilishi shart bo'lgan ko'rsatkichlar:

| Ko'rsatkich | Sog'lom qiymat | Nima anglatadi |
|---|---|---|
| `XLEN proctoring:events` | < 50 000 | Celery buffer'ni yetkazyaptimi |
| Circuit breaker holati | `closed` | Tashqi platforma sog'ligi |
| `/readyz/` | 200 | DB + Redis mavjudligi |
| PgBouncer `cl_waiting` | 0 | Ulanish pool'i yetarlimi |
| `flush_event_buffer` davomiyligi | < 3s | Batch yozish tezligi |

Agar `XLEN` o'sib borsa — ingest worker'lar soni yetarli emas.
