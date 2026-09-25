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

## Birinchi o'rnatish (bitta server, Ubuntu)

Katalog tartibi — nginx va systemd fayllari shunga yozilgan:

```
/srv/proctoring/               repo ildizi (git clone)
    backend/.env               deploy/env.production.example dan
    backend/.venv/             deploy.sh yaratadi
    frontend/dist/             deploy.sh build qiladi (nginx root)
    storage/screenshots/       SCREENSHOT_ROOT = nginx `alias`
```

```bash
# 1. Tizim paketlari va foydalanuvchi
sudo apt install -y python3.12-venv postgresql redis-server nginx nodejs npm
sudo useradd --system --home /srv/proctoring --shell /bin/bash proctoring
sudo git clone <repo> /srv/proctoring && sudo chown -R proctoring: /srv/proctoring

# 2. PostgreSQL va Redis (quyidagi "Infratuzilma" — `noeviction` MAJBURIY)
sudo -u postgres createuser proctoring -P
sudo -u postgres createdb -O proctoring proctoring

# 3. .env — sirlarni yaratib to'ldiring (fayl ichida buyruqlar bor)
sudo -u proctoring cp backend/deploy/env.production.example backend/.env
sudo -u proctoring nano backend/.env

# 4. systemd — unit'lar va deploy uchun cheklangan sudo
sudo cp backend/deploy/systemd/* /etc/systemd/system/
echo 'proctoring ALL=(root) NOPASSWD: /usr/bin/systemctl restart proctoring-*'   | sudo tee /etc/sudoers.d/proctoring
sudo systemctl daemon-reload && sudo systemctl enable proctoring.target

# 5. nginx — domen, sertifikat va yo'llarni moslang
sudo cp backend/deploy/proxy_common.conf /etc/nginx/proxy_common.conf
sudo cp backend/deploy/nginx.conf.example /etc/nginx/sites-available/proctoring
sudo ln -s /etc/nginx/sites-available/proctoring /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# 6. Deploy (paketlar, check --deploy, migrate, seed, partitsiyalar, build)
sudo -u proctoring bash backend/deploy/deploy.sh --first-install
sudo -u proctoring backend/.venv/bin/python backend/manage.py createsuperuser
```

Keyingi yangilanishlar: `git pull` → `sudo -u proctoring bash backend/deploy/deploy.sh`.
Skript bo'sh sir yoki `check --deploy` ogohlantirishida TO'XTAYDI; frontend
atomik almashtiriladi (oldingisi `frontend/dist.old`).

**Uchta qoidani buzmang:**

* **`FIELD_ENCRYPTION_KEY` va `TOKEN_HASH_KEY` — bir marta.** Birinchisi
  o'zgarsa kamera parollari va imtihon platformasi sarlavhasi o'qilmay
  qoladi, ikkinchisi barcha faol sessiyalarni bekor qiladi.
* **`requirements.txt` — UTF-8.** Windows PowerShell 5.1 da
  `pip freeze > requirements.txt` UTF-16 yozadi va Linux'dagi pip uni
  `\x00D\x00j...` deb o'qib yiqiladi.
* **gunicorn faqat `127.0.0.1` da** (`GUNICORN_BIND`). Tarmoqqa ochiq API
  nginx rate limit'ini chetlab o'tadi, `TRUSTED_PROXY_COUNT=1` da esa
  soxta `X-Forwarded-For` bilan IP ro'yxatini aldaydi.

FaceID integratsiyasi yoqilsa (`FACEID_API_KEY`), panelda `faceid` xodimini
yarating: respublika darajasidagi rol, faqat `bookings.view` +
`bookings.manage` (Administrator emas — kalit o'g'irlansa zarar cheklangan).

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
