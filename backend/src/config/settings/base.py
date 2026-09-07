"""
Base settings — barcha muhitlar uchun umumiy.

Qoida: bu yerda hech qanday sir hardcode qilinmaydi. Barchasi `.env` orqali.
Majburiy sirlar `production.py` da ishga tushishda tekshiriladi.
"""

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

# src/config/settings/base.py -> src/
BASE_DIR = Path(__file__).resolve().parent.parent.parent
# backend/  (.env shu yerda)
ROOT_DIR = BASE_DIR.parent

load_dotenv(ROOT_DIR / ".env")


# --------------------------------------------------------------------------
# env helper'lar
# --------------------------------------------------------------------------
def env(key: str, default=None):
    value = os.getenv(key)
    return default if value in (None, "") else value


def env_bool(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw in (None, ""):
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(key: str, default: int) -> int:
    try:
        return int(env(key, default))
    except (TypeError, ValueError):
        return default


def env_float(key: str, default: float) -> float:
    try:
        return float(env(key, default))
    except (TypeError, ValueError):
        return default


def env_list(key: str, default=None) -> list[str]:
    raw = env(key)
    if not raw:
        return list(default or [])
    return [item.strip() for item in raw.split(",") if item.strip()]


# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------
SECRET_KEY = env("SECRET_KEY", "insecure-dev-key-change-me")
DEBUG = env_bool("DEBUG", False)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", ["localhost", "127.0.0.1"])

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
AUTH_USER_MODEL = "users.User"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Desktop client bitta so'rovda event batch yuboradi.
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 2000


# --------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "corsheaders",
    "drf_spectacular",
    "channels",
]

LOCAL_APPS = [
    "apps.common",
    "apps.users",
    "apps.regions",
    "apps.devices",
    "apps.controls",
    "apps.exams",
    "apps.proctoring",
    "apps.integrations",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.common.middleware.RequestIDMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
# CONN_MAX_AGE:
#   PgBouncer `transaction` rejimi bilan  -> 0  (pooling'ni bouncer qiladi)
#   To'g'ridan-to'g'ri Postgres'ga        -> 60 (ulanishni qayta ishlatish)
DB_CONN_MAX_AGE = env_int("DB_CONN_MAX_AGE", 60)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "proctoring"),
        "USER": env("POSTGRES_USER", "postgres"),
        "PASSWORD": env("POSTGRES_PASSWORD", "postgres"),
        "HOST": env("POSTGRES_HOST", "127.0.0.1"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": DB_CONN_MAX_AGE,
        "CONN_HEALTH_CHECKS": DB_CONN_MAX_AGE > 0,
        "OPTIONS": {
            "connect_timeout": 5,
            # Bitta og'ir query butun pool'ni band qilib qo'ymasligi uchun.
            "options": (
                "-c statement_timeout=15000 "
                "-c idle_in_transaction_session_timeout=30000"
            ),
        },
    }
}

# Read replica (ixtiyoriy) — dashboard/hisobot query'lari shu yerga ketadi.
REPLICA_HOST = env("REPLICA_POSTGRES_HOST")
if REPLICA_HOST:
    DATABASES["replica"] = {
        **DATABASES["default"],
        "HOST": REPLICA_HOST,
        "PORT": env("REPLICA_POSTGRES_PORT", env("POSTGRES_PORT", "5432")),
        "TEST": {"MIRROR": "default"},
    }
    DATABASE_ROUTERS = ["apps.common.db_router.ReadReplicaRouter"]


# --------------------------------------------------------------------------
# Cache / Redis
# --------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL", "redis://127.0.0.1:6379")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"{REDIS_URL}/1",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "CONNECTION_POOL_KWARGS": {
                "max_connections": env_int("REDIS_MAX_CONNECTIONS", 200),
                "retry_on_timeout": True,
            },
            "SOCKET_CONNECT_TIMEOUT": 2,
            "SOCKET_TIMEOUT": 2,
            # Redis tushsa tizim to'liq o'lmasin — degradatsiya qilsin.
            "IGNORE_EXCEPTIONS": True,
        },
        "KEY_PREFIX": "pcache",
    },
}
DJANGO_REDIS_IGNORE_EXCEPTIONS = True

# Sessiya holati / event buffer uchun xom Redis (alohida DB).
REDIS_STATE_URL = f"{REDIS_URL}/2"

# Admin sessiyalari DB'da emas, cache'da.
SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"


# --------------------------------------------------------------------------
# Celery
# --------------------------------------------------------------------------
# Nechta ISHONCHLI proksi oldinda turadi.
#
# `0` (standart) - Django to'g'ridan-to'g'ri ochiq: `X-Real-IP` va
# `X-Forwarded-For` header'lari e'tiborsiz qoldiriladi, chunki ularni
# istalgan client yozib yuborishi mumkin va IP allowlist'i ma'nosiz
# bo'lib qolardi.
#
# nginx ortida `1` qo'ying (`deploy/nginx.conf.example` ga qarang).
TRUSTED_PROXY_COUNT = env_int("TRUSTED_PROXY_COUNT", 0)

CELERY_BROKER_URL = env("CELERY_BROKER_URL", f"{REDIS_URL}/3")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", f"{REDIS_URL}/4")
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = "Asia/Tashkent"
CELERY_ENABLE_UTC = True
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_RESULT_EXPIRES = 3600
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_ROUTES = {
    "proctoring.flush_event_buffer": {"queue": "ingest"},
    "proctoring.flush_screenshot_buffer": {"queue": "ingest"},
    "proctoring.flush_session_state": {"queue": "ingest"},
    "proctoring.close_stale_sessions": {"queue": "maintenance"},
    "proctoring.rotate_event_partitions": {"queue": "maintenance"},
    "proctoring.purge_expired_screenshots": {"queue": "maintenance"},
    "devices.*": {"queue": "maintenance"},
}


# --------------------------------------------------------------------------
# Channels (WebSocket)
# --------------------------------------------------------------------------
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            # `socket_timeout` MAJBURIY va u channels_redis'ning
            # `brpop_timeout` (5s) dan katta bo'lishi SHART.
            #
            # redis-py 8 da `DEFAULT_SOCKET_TIMEOUT = 5` paydo bo'ldi. U
            # channels_redis'ning BZPOPMIN kutish vaqti bilan aynan teng,
            # natijada har bir bo'sh kutish klientda TimeoutError beradi va
            # WebSocket consumer'i o'sha zahoti yiqiladi.
            "hosts": [{"address": f"{REDIS_URL}/5", "socket_timeout": 30}],
            "capacity": 2000,
            "expiry": 20,
        },
    }
}


# --------------------------------------------------------------------------
# REST Framework
# --------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.DefaultPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
        "rest_framework.filters.SearchFilter",
    ),
    "DEFAULT_RENDERER_CLASSES": ("apps.common.renderers.ApiJSONRenderer",),
    "EXCEPTION_HANDLER": "apps.common.exceptions.api_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_RATES": {
        # Talabgor JSHSHIR qidiruvi — brute-force'ga qarshi eng muhim chegara
        "pinfl_lookup": env("THROTTLE_PINFL_LOOKUP", "10/hour"),
        "pinfl_lookup_operator": env("THROTTLE_PINFL_OPERATOR", "300/hour"),
        "face_verify": env("THROTTLE_FACE_VERIFY", "40/min"),
        "session_start": env("THROTTLE_SESSION_START", "10/hour"),
        "exit_verify": env("THROTTLE_EXIT_VERIFY", "10/hour"),
        "client_ingest": env("THROTTLE_CLIENT_INGEST", "600/min"),
        "staff_login": env("THROTTLE_STAFF_LOGIN", "10/min"),
        "device_register": env("THROTTLE_DEVICE_REGISTER", "20/hour"),
        "preflight": env("THROTTLE_PREFLIGHT", "30/min"),
        "access_attempt": env("THROTTLE_ACCESS_ATTEMPT", "30/min"),
        "user": env("THROTTLE_USER", "1000/min"),
        "anon": env("THROTTLE_ANON", "60/min"),
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env_int("JWT_ACCESS_MINUTES", 30)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env_int("JWT_REFRESH_DAYS", 7)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    # Har login'da users jadvaliga UPDATE — yuqori yuklamada keraksiz yozish.
    "UPDATE_LAST_LOGIN": False,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": env("JWT_SIGNING_KEY", SECRET_KEY),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "TOKEN_TYPE_CLAIM": "token_type",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Proctoring System API",
    "DESCRIPTION": "Onlayn imtihon proktorlik tizimi — admin va desktop client API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": "/api/v1",
}


# --------------------------------------------------------------------------
# CORS
# --------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", ["http://localhost:5173"])
CORS_ALLOW_CREDENTIALS = False
CORS_ALLOW_HEADERS = [
    "accept", "authorization", "content-type", "origin", "user-agent",
    "x-requested-with", "x-device-id", "x-proctoring-session", "x-request-id",
]


# --------------------------------------------------------------------------
# Auth / Password
# --------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# --------------------------------------------------------------------------
# i18n / Static
# --------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = ROOT_DIR / "static"
MEDIA_URL = "media/"
MEDIA_ROOT = ROOT_DIR / "media"


# --------------------------------------------------------------------------
# Domen sozlamalari
# --------------------------------------------------------------------------
# Token hash va maydon shifrlash kalitlari. Production'da MAJBURIY.
# TOKEN_HASH_KEY o'zgarsa — barcha faol sessiya tokenlari bekor bo'ladi.
TOKEN_HASH_KEY = env("TOKEN_HASH_KEY", "dev-token-hash-key-change-me")
FIELD_ENCRYPTION_KEY = env("FIELD_ENCRYPTION_KEY", "dev-field-encryption-key-change!")

PROCTORING = {
    # --- Sessiya ---
    "SESSION_TOKEN_TTL": env_int("SESSION_TOKEN_TTL", 5 * 60 * 60),
    "PENDING_SESSION_TTL": env_int("PENDING_SESSION_TTL", 5 * 60),
    "HEARTBEAT_TIMEOUT": env_int("HEARTBEAT_TIMEOUT", 90),
    "STALE_SESSION_AFTER": env_int("STALE_SESSION_AFTER", 15 * 60),

    # --- Tashqi platforma sessiyasi ---
    # Token WebView'ga qanday uzatiladi: `post` — form body'da,
    # `cookie` — `QWebEngineProfile.cookieStore()` orqali.
    # URL'ga HECH QACHON qo'yilmaydi: u brauzer tarixi, `Referer`
    # header'i va nginx access log orqali sizib chiqadi.
    "EXTERNAL_TOKEN_DELIVERY": env("EXTERNAL_TOKEN_DELIVERY", "post"),

    # --- Operator tasdig'i ---
    # `true` (standart): operator hujjat bo'yicha shaxsni tasdiqlamaguncha
    # imtihon ochilmaydi. Buni o'chirish tizimning shaxsni aniqlash
    # kafolatini BUTUNLAY yo'q qiladi — FaceID uni bera olmaydi, chunki
    # etalon shu sessiyaning o'zida olinadi.
    "REQUIRE_IDENTITY_CONFIRMATION": env_bool("REQUIRE_IDENTITY_CONFIRMATION", True),

    # --- Imtihon jadvali (kirish oynasi) ---
    # `true` bo'lsa, jadvali yo'q imtihonga kirish umuman mumkin emas.
    # Standart `false`: jadval tuzilmagan bo'lsa tekshiruv o'chirilgan
    # hisoblanadi (dastlabki o'rnatish bosqichi bloklanmasligi uchun).
    # Production'da `true` qo'yish tavsiya etiladi.
    "REQUIRE_EXAM_SCHEDULE": env_bool("REQUIRE_EXAM_SCHEDULE", False),

    # --- Ruxsat etilgan tashqi IP'lar ---
    # `AllowedPublicIp` da FAOL yozuv qolmaganda nima bo'ladi:
    #
    #   true (standart) — HECH KIM kira olmaydi. "Ro'yxat bo'sh" degani
    #     "ruxsat cheklovi yo'q" emas, "hali hech kimga ruxsat
    #     berilmagan" degani. Proktorlikda xavfsiz talqin shu.
    #   false — tekshiruv o'chirilgan hisoblanadi va hamma kiraveradi.
    #
    # Bu FAQAT desktop client'ga tegishli: admin panel bu ro'yxatdan
    # umuman o'tmaydi, ya'ni `true` bo'lganda ham administrator panelga
    # kirib birinchi IP'ni kirita oladi — tizim o'zini qulflab qo'ymaydi.
    "REQUIRE_ALLOWED_IP": env_bool("REQUIRE_ALLOWED_IP", True),

    # --- Server imtihon tarmog'ining ICHIDAMI ---
    #
    # `AllowedPublicIp` — bu binolarning TASHQI (NAT) manzillari
    # ro'yxati. U faqat server clientlarni internet orqali ko'rganda
    # ma'noga ega:
    #
    #   A) server internetda (nginx ortida) — client NAT orqali keladi,
    #      server binoning tashqi manzilini ko'radi, ro'yxat ishlaydi;
    #   B) server BINO ICHIDA (yoki dev'da o'sha mashinada) — client
    #      unga LAN manzili bilan yetib boradi va server uning tashqi
    #      manzilini printsipial ravishda KO'RA OLMAYDI.
    #
    # B holatida ommaviy manzillar ro'yxati xususiy manzilga hech qachon
    # mos kelmaydi, ya'ni `check_source_ip` HAMMANI rad etadi. Har bir
    # ish stantsiyasining 192.168.x.x manzilini ro'yxatga kiritish esa
    # yechim emas (`network_preflight` docstring'i buni tushuntiradi).
    #
    # Shuning uchun qaror TAXMIN QILINMAYDI, u sozlamada aytiladi:
    #
    #   true  — xususiy (LAN/loopback) manba manzili tekshiruvdan
    #           o'tadi. Bu B holati: LAN'ning O'ZI perimetr, unga
    #           kirish uchun binoga jismonan kirish kerak.
    #   false — (standart) faqat ro'yxatdagi manzil o'tadi. Bu A holati.
    #
    # DIQQAT: `true` IP tekshiruvini LAN uchun o'chiradi, boshqa
    # qatlamlarni emas — qurilma baribir ro'yxatdan o'tgan va
    # tasdiqlangan bo'lishi, xodim JWT'si va ochiq imtihon oynasi
    # bo'lishi shart. Ommaviy manzildan kelgan so'rov esa avvalgidek
    # ro'yxat bo'yicha tekshiriladi.
    "ALLOW_PRIVATE_SOURCE_IP": env_bool("ALLOW_PRIVATE_SOURCE_IP", False),

    # --- Qurilma identifikatori ---
    # `X-Device-ID` kredensial EMAS — u sessiya qaysi kompyuterda va qaysi
    # binoda o'tayotganini belgilaydi. Usiz sessiyaning zonasi bo'lmaydi,
    # ya'ni dashboard va viloyat bo'yicha ajratish ishlamaydi. Faqat lokal
    # ishlab chiqishda (Postman/curl) o'chiriladi.
    "REQUIRE_DEVICE_ID": env_bool("REQUIRE_DEVICE_ID", True),

    # --- Avtomatik inventarizatsiya ---
    # `true` bo'lsa, ro'yxatda yo'q kompyuter avtomatik yaratiladi -
    # LEKIN faqat binoning tashqi IP'si `AllowedPublicIp` da qayd
    # etilgan bo'lsa. 500 mashinani qo'lda kiritish yukini olib
    # tashlaydi; qurilma baribir `PENDING` bo'lib qoladi va admin
    # tasdig'ini kutadi.
    #
    # Standart `false`: bu inventarizatsiya intizomini yumshatadi va
    # har bir muassasa buni o'zi hal qilishi kerak.
    "AUTO_REGISTER_COMPUTERS": env_bool("AUTO_REGISTER_COMPUTERS", False),

    # --- Buffer / batch (performance) ---
    "EVENT_STREAM_KEY": "proctoring:events",
    "SCREENSHOT_STREAM_KEY": "proctoring:screenshots",
    "EVENT_BATCH_SIZE": env_int("EVENT_BATCH_SIZE", 2000),
    "EVENT_STREAM_MAXLEN": env_int("EVENT_STREAM_MAXLEN", 500_000),

    # Yiqilgan worker'dan qolgan yozuvni shuncha vaqtdan keyin boshqa
    # worker qaytarib oladi. Flush intervalidan (5s) ANCHA katta bo'lishi
    # kerak — aks holda ishlab turgan worker'ning yozuvlari tortib olinadi
    # va bitta hodisa ikki marta yoziladi.
    "STREAM_RECLAIM_IDLE_MS": env_int("STREAM_RECLAIM_IDLE_MS", 60_000),
    # Yozib bo'lmagan yozuvlar shu oqimga ko'chiriladi (`<stream>:dead`).
    "STREAM_DEAD_LETTER_MAXLEN": env_int("STREAM_DEAD_LETTER_MAXLEN", 10_000),

    # --- Client vaqtiga ishonch chegarasi ---
    # `occurred_at` kunlik partitsiyani tanlaydi, shuning uchun u
    # cheklanmasa soati adashgan bitta mashina butun batchni yiqitadi.
    "EVENT_MAX_FUTURE_SKEW": env_int("EVENT_MAX_FUTURE_SKEW", 300),      # 5 daqiqa
    "EVENT_MAX_BACKFILL": env_int("EVENT_MAX_BACKFILL", 24 * 60 * 60),   # 1 kun

    # --- FaceID ---
    "FACE_EMBEDDING_DIM": env_int("FACE_EMBEDDING_DIM", 512),
    "FACE_RANDOM_AUDIT_RATE": env_float("FACE_RANDOM_AUDIT_RATE", 0.05),

    # --- Realtime ---
    "MONITOR_MIN_SEVERITY": env_int("MONITOR_MIN_SEVERITY", 2),
}

# Object storage — skrinshotlar DB'da EMAS, shu yerda.
STORAGE = {
    "ENABLED": env_bool("S3_ENABLED", False),
    "ENDPOINT_URL": env("S3_ENDPOINT_URL", "http://127.0.0.1:9000"),
    "ACCESS_KEY": env("S3_ACCESS_KEY", "minioadmin"),
    "SECRET_KEY": env("S3_SECRET_KEY", "minioadmin"),
    "BUCKET": env("S3_BUCKET", "proctoring"),
    "REGION": env("S3_REGION", "us-east-1"),
    "PRESIGN_TTL": env_int("S3_PRESIGN_TTL", 300),
}

# --------------------------------------------------------------------------
# Skrinshot storage (fayl tizimi)
#
# S3 yo'lidan (`STORAGE`) ALOHIDA va undan farqli: bu yerda binary Django
# orqali o'tadi. Bu ataylab qilingan kelishuv — obyekt storage'i yo'q
# o'rnatishlar uchun. Yuklama chegarasi: taxminan bitta bino (~500 client),
# undan yuqorisida presigned URL yo'liga qaytish kerak.
#
# Baytlarni QAYTARISHDA esa Django ishtirok etmaydi: ruxsat tekshirilib,
# `X-Accel-Redirect` beriladi va faylni nginx o'zi o'qiydi.
# --------------------------------------------------------------------------
SCREENSHOT_STORAGE = {
    "BACKEND": env(
        "SCREENSHOT_STORAGE_BACKEND",
        "apps.common.screenshot_storage.FilesystemScreenshotStorage",
    ),
    # Fayllar ildizi. Bu katalog nginx uchun ham o'qiladigan bo'lishi kerak.
    "ROOT": Path(env("SCREENSHOT_ROOT", str(ROOT_DIR / "storage" / "screenshots"))),

    # nginx'dagi `internal` location — tashqi dunyo bu manzilga to'g'ridan
    # to'g'ri kira olmaydi, unga faqat `X-Accel-Redirect` orqali tushiladi.
    "INTERNAL_LOCATION": env("SCREENSHOT_INTERNAL_LOCATION", "/protected-screenshots"),

    # `true` bo'lsa faylni Django o'zi beradi (nginx yo'q dev muhitida).
    # Production'da HECH QACHON `true` qilmang.
    "SERVE_DIRECTLY": env_bool("SCREENSHOT_SERVE_DIRECTLY", False),

    "MAX_BYTES": env_int("SCREENSHOT_MAX_BYTES", 5 * 1024 * 1024),
    # Dekompressiya bombasiga qarshi: 100 MP dan katta rasm 4K skrinshot
    # emas, hujum. Pillow uni ochishda RAM'ni yeb qo'yadi.
    "MAX_PIXELS": env_int("SCREENSHOT_MAX_PIXELS", 100_000_000),
    # Faqat shu formatlar. Baytlardan aniqlanadi, kengaytmadan emas.
    "ALLOWED_FORMATS": {
        "JPEG": ("image/jpeg", "jpg"),
        "PNG": ("image/png", "png"),
        "WEBP": ("image/webp", "webp"),
    },

    "RETENTION_DAYS": env_int("SCREENSHOT_RETENTION_DAYS", 90),

    # Fayl va katalog huquqlari: nginx guruh orqali o'qiydi, dunyo uchun
    # yopiq. Skrinshot — talabgorning ekrani, ya'ni shaxsiy ma'lumot.
    "DIR_MODE": 0o750,
    "FILE_MODE": 0o640,
}

# Tashqi test platformasi (ntest)
EXTERNAL_PLATFORM = {
    "BASE_URL": env("BASE_API_URL", "https://ntest.uzbmb.uz"),
    "API_KEY": env("BASE_API_KEY", ""),
    "CONNECT_TIMEOUT": env_float("BASE_CONNECT_TIMEOUT", 2.0),
    "READ_TIMEOUT": env_float("BASE_TIMEOUT", 5.0),
    "MAX_RETRIES": env_int("BASE_MAX_RETRIES", 2),
    "POOL_SIZE": env_int("BASE_POOL_SIZE", 100),
    # Talabgor javobi jonli sessiya tokeni va test statusini olib keladi,
    # shuning uchun kesh qisqa: u faqat takroriy bosishni yutadi.
    "CACHE_TTL": env_int("BASE_CACHE_TTL", 60),
    # Circuit breaker
    "CB_FAIL_THRESHOLD": env_int("BASE_CB_FAIL_THRESHOLD", 10),
    "CB_WINDOW": env_int("BASE_CB_WINDOW", 60),
    "CB_RESET_TIMEOUT": env_int("BASE_CB_RESET_TIMEOUT", 30),
    # Test/dev uchun: tashqi API o'rniga soxta javob qaytarish
    "MOCK": env_bool("BASE_API_MOCK", False),
}


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
LOG_LEVEL = env("LOG_LEVEL", "INFO")

# Client kirish urinishlari uchun ALOHIDA fayl.
#
# Nega alohida: uni tizim administratori "falon kompyuter nega kira
# olmayapti?" degan aniq savol bilan ochadi. Umumiy log'da bu yozuvlar
# har bir HTTP so'rovi qatori orasida yo'qolib ketardi, `grep` esa
# imtihon kunidagi yuz megabaytli fayl bo'ylab ishlashi kerak bo'lardi.
# Nisbiy yo'l ROOT_DIR ga nisbatan hisoblanadi, joriy papkaga EMAS:
# HTTP, WebSocket va Celery jarayonlari har xil papkadan ishga
# tushiriladi va aks holda jurnal uch xil joyga bo'linib ketardi.
CLIENT_ACCESS_LOG = Path(env("CLIENT_ACCESS_LOG", "logs/client_access.log"))
if not CLIENT_ACCESS_LOG.is_absolute():
    CLIENT_ACCESS_LOG = ROOT_DIR / CLIENT_ACCESS_LOG
CLIENT_ACCESS_LOG.parent.mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_id": {"()": "apps.common.logging.RequestIDFilter"}},
    "formatters": {
        "verbose": {
            "format": "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s",
        },
        # Jurnal odam tomonidan o'qiladi va `grep` bilan filtrlanadi,
        # shuning uchun format qat'iy va bir xil: sana, daraja, matn.
        "access": {"format": "%(asctime)s %(levelname)-7s %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
            "filters": ["request_id"],
        },
        "client_access": {
            # Rotatsiya MAJBURIY: 10 000 client kuniga bir necha marta
            # ishga tushadi va cheklovsiz fayl diskni to'ldiradi.
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(CLIENT_ACCESS_LOG),
            "maxBytes": env_int("CLIENT_ACCESS_LOG_MAX_BYTES", 20 * 1024 * 1024),
            "backupCount": env_int("CLIENT_ACCESS_LOG_BACKUPS", 10),
            "encoding": "utf-8",
            "formatter": "access",
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.db.backends": {"level": "WARNING", "propagate": True},
        "apps": {"level": LOG_LEVEL, "propagate": True},
        # `propagate: False` — yozuv konsolga TUSHMAYDI. Aks holda u ikki
        # joyda bo'lardi va alohida fayl ajratishning ma'nosi qolmasdi.
        "client_access": {
            "handlers": ["client_access"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
