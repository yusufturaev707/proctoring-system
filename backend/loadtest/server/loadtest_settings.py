"""
LOKAL yuklama sinovi uchun sozlama — dev muhitidan TO'LIQ ajratilgan.

NIMA UCHUN ALOHIDA MODUL (`.env` emas): `config/settings/base.py` Redis
bazalarini `REDIS_URL` dan o'zi yasaydi (`/1` kesh, `/2` holat, `/5`
channel layer). `REDIS_URL` ni o'zgartirish bilan bazani tanlab bo'lmaydi —
dasturchining dev ma'lumoti (`sess:*`, oqimlar) bilan aralashib ketardi.
Bu yerda har bir URL qo'lda, alohida bazalarga qo'yiladi:

    6  — kesh (throttle hisoblagichlari ham shu yerda)
    7  — sessiya holati, event/skrinshot oqimlari (REDIS_STATE_URL)
    8  — Celery broker
    9  — Celery natijalari
    10 — Channels (WebSocket) layer

Baza — `proctoring_loadtest` (dev bazasi `.env` dagi `POSTGRES_DB`).
Skrinshot ildizi — `backend/loadtest/results/storage/` (dev fayllariga
tegilmaydi).

Ishlatish (PowerShell, `backend/` dan):

    $env:PYTHONPATH = "loadtest\\server"
    $env:DJANGO_SETTINGS_MODULE = "loadtest_settings"
    .venv\\Scripts\\python.exe manage.py migrate

`config/env.py` `.env` ni `override=False` bilan yuklaydi, ya'ni jarayon
muhitidagi `DJANGO_SETTINGS_MODULE` `.env` dagidan USTUN.

PRODUCTION/STAGING UCHUN EMAS: staging'da `config.settings.production`
ishlatiladi (README.md, "Staging").
"""

import os
from pathlib import Path

from config.settings.local import *  # noqa: F401,F403
from config.settings.local import (  # noqa: F401
    CACHES,
    CHANNEL_LAYERS,
    DATABASES,
    PROCTORING,
    REDIS_URL,
    REST_FRAMEWORK,
    SCREENSHOT_STORAGE,
    env_bool,
    env_int,
)
from config.settings.base import _channel_layer_host

_LT_ROOT = Path(__file__).resolve().parent.parent  # backend/loadtest

# DEBUG=False: `connection.queries` xotirada yig'ilmaydi va javob
# vaqti production'dagiga yaqinroq bo'ladi.
DEBUG = env_bool("LT_DEBUG", False)
ALLOWED_HOSTS = ["*"]

DATABASES["default"]["NAME"] = os.getenv("LT_POSTGRES_DB", "proctoring_loadtest")
DATABASES["default"]["CONN_MAX_AGE"] = env_int("LT_CONN_MAX_AGE", 60)

_redis = os.getenv("LT_REDIS_URL", REDIS_URL).rstrip("/")
CACHES["default"]["LOCATION"] = f"{_redis}/6"
REDIS_STATE_URL = f"{_redis}/7"
CELERY_BROKER_URL = f"{_redis}/8"
CELERY_RESULT_BACKEND = f"{_redis}/9"
# Celery `CELERY_BROKER_URL` MUHIT O'ZGARUVCHISINI sozlamadan USTUN qo'yadi,
# `.env` esa (`config/env.py`) uni `os.environ` ga yuklab qo'ygan
# (dev'da `/0`). Qayta yozilmasa sinov vazifalari DEV brokeriga ketadi.
os.environ["CELERY_BROKER_URL"] = CELERY_BROKER_URL
os.environ["CELERY_RESULT_BACKEND"] = CELERY_RESULT_BACKEND
CHANNEL_LAYERS["default"]["CONFIG"]["hosts"] = [_channel_layer_host(f"{_redis}/10")]

SCREENSHOT_STORAGE["ROOT"] = Path(
    os.getenv("LT_SCREENSHOT_ROOT", str(_LT_ROOT / "results" / "storage"))
)
SCREENSHOT_STORAGE["SERVE_DIRECTLY"] = True

# Tashqi platforma — lokal stub (`loadtest/server/stub_platform.py`).
# `site_url` imtihon yozuvida (`seed_loadtest --platform-url`), MOCK o'chiq:
# stub haqiqiy HTTP yo'lini (pool, timeout, circuit breaker) ishlatadi.
EXTERNAL_PLATFORM["MOCK"] = env_bool("LT_PLATFORM_MOCK", False)  # noqa: F405
# ntest (natija yuborish, `report_session_result`) ham STUB'ga. MAJBURIY:
# `base.py` da `BASE_API_URL` bo'sh bo'lsa standart qiymat PRODUCTION
# domeni (`https://ntest.uzbmb.uz`) — sinov yakunlari u yerga ketardi.
EXTERNAL_PLATFORM["BASE_URL"] = os.getenv("LT_NTEST_URL", "http://127.0.0.1:8099")  # noqa: F405
EXTERNAL_PLATFORM["API_KEY"] = "loadtest"  # noqa: F405

# Throttling: standart holatda YOQIQ va production qiymatlari bilan —
# yuklama sinovi aynan shu chegaralarni ham tekshiradi. Lokal
# mashinada hamma so'rov 127.0.0.1 dan keladi, shuning uchun
# `TRUSTED_PROXY_COUNT=1` va Locust har "bino" uchun `X-Real-IP`
# yuboradi (staging'dagi nginx `realip` sxemasining taqlidi; README).
if env_bool("LT_THROTTLING", True):
    REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {
        "pinfl_lookup": "10/hour",
        "pinfl_lookup_operator": "1500/hour",
        "pinfl_lookup_device": "120/hour",
        "face_verify": "40/min",
        "session_start": "10/hour",
        "exit_verify": "300/hour",
        "exit_verify_device": "10/hour",
        "client_ingest": "600/min",
        "staff_login": "60/min",
        "staff_login_device": "10/min",
        "device_register": "20/hour",
        "preflight": "30/min",
        "access_attempt": "30/min",
        "user": "1000/min",
        "anon": "60/min",
    }
TRUSTED_PROXY_COUNT = env_int("LT_TRUSTED_PROXY_COUNT", 1)

# Staging/production'dagi kabi: manba manzili "bino NAT IP" si
# (X-Real-IP), xususiy manzil sifatida o'tkazilmaydi.
PROCTORING["ALLOW_PRIVATE_SOURCE_IP"] = env_bool("LT_ALLOW_PRIVATE_SOURCE_IP", False)
PROCTORING["REQUIRE_DEVICE_ID"] = True
PROCTORING["REQUIRE_COMPUTER_BOOKING"] = True
PROCTORING["REQUIRE_EXAM_SCHEDULE"] = True
PROCTORING["REQUIRE_MACHINE_MATCH"] = True
PROCTORING["REQUIRE_IDENTITY_CONFIRMATION"] = True
# Kamera tekshiruvi oqimda bor (client uni har doim yuboradi).
PROCTORING["REQUIRE_CAMERA_CHECK"] = True

# Konsolga har so'rov yozilmasin — lokal o'lchovni buzadi.
LOGGING["root"]["level"] = os.getenv("LT_LOG_LEVEL", "WARNING")  # noqa: F405
LOGGING["loggers"]["apps"]["level"] = os.getenv("LT_LOG_LEVEL", "WARNING")  # noqa: F405

# Kamera zondlash lokal sinovda kerak emas (kamera yo'q).
CAMERA_PROBE_ENABLED = False

# Kirish urinishlari jurnali dev jurnaliga (`backend/logs/`) aralashmasin.
LOGGING["handlers"]["client_access"]["filename"] = str(  # noqa: F405
    _LT_ROOT / "results" / "client_access.log"
)
