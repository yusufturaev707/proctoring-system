"""
Production sozlamalari.

Ishga tushishda majburiy sirlar tekshiriladi — noto'g'ri konfiguratsiya bilan
server jim ishlab ketmasligi kerak.
"""

import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import DB_CONN_MAX_AGE, env, env_bool, env_int, env_list

DEBUG = False

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS")
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("ALLOWED_HOSTS production'da bo'sh bo'lishi mumkin emas")


# --------------------------------------------------------------------------
# Majburiy sirlar
# --------------------------------------------------------------------------
_INSECURE_DEFAULTS = {
    "SECRET_KEY": "insecure-dev-key-change-me",
    "TOKEN_HASH_KEY": "dev-token-hash-key-change-me",
    "FIELD_ENCRYPTION_KEY": "dev-field-encryption-key-change!",
}

for _name, _bad_default in _INSECURE_DEFAULTS.items():
    _value = globals().get(_name)
    if not _value or _value == _bad_default:
        raise ImproperlyConfigured(
            f"{_name} production'da .env orqali berilishi shart "
            f"(hozir yo'q yoki dev-qiymatda)"
        )

if len(SECRET_KEY) < 50:  # noqa: F405
    raise ImproperlyConfigured("SECRET_KEY kamida 50 belgidan iborat bo'lishi kerak")

# FaceID kaliti butun respublika bo'yicha bron qila oladi — qisqa kalit
# production'da qabul qilinmaydi (bo'sh = integratsiya o'chiq, bu ruxsat).
_faceid_key = FACEID_INTEGRATION["API_KEY"]  # noqa: F405
if _faceid_key and len(_faceid_key) < 32:
    raise ImproperlyConfigured("FACEID_API_KEY kamida 32 belgidan iborat bo'lishi kerak")


# --------------------------------------------------------------------------
# HTTPS / Xavfsizlik header'lari
# --------------------------------------------------------------------------
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 31_536_000)  # 1 yil
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"
SESSION_COOKIE_AGE = 8 * 60 * 60

CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Strict"
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", [])
# Bo'sh = hech qaysi begona origin. `base.py` standarti (`localhost:5173`)
# dev uchun; production'da panel va API bitta domenda (nginx).
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", [])

X_FRAME_OPTIONS = "DENY"

# Admin panelni standart bo'lmagan yo'lga ko'chirish (bot skanerlariga qarshi).
ADMIN_URL = env("ADMIN_URL", "admin/")

# --------------------------------------------------------------------------
# Xususiy manba manzillariga ruxsat
#
# Bu QONUNIY o'rnatish profili (server bino ichida turadi va clientlarni
# LAN manzili bilan ko'radi), lekin u IP tekshiruvini o'sha tarmoq uchun
# o'chiradi. Ishga tushishni TO'XTATMAYDI — aks holda topologiya B dagi
# muassasa umuman ishga tushira olmasdi — lekin jimgina ham o'tmaydi:
# uni yoqqan odam ham, keyin log o'qigan odam ham bilishi kerak.
# --------------------------------------------------------------------------
if PROCTORING["ALLOW_PRIVATE_SOURCE_IP"]:  # noqa: F405
    import logging

    logging.getLogger("django").warning(
        "ALLOW_PRIVATE_SOURCE_IP=true — LAN/loopback manzillari `AllowedPublicIp` "
        "ro'yxatidan o'tkazib yuboriladi. Bu faqat server imtihon tarmog'ining "
        "ICHIDA turgan o'rnatish uchun to'g'ri. Server internetda (nginx ortida) "
        "bo'lsa, uni `false` qiling."
    )


# --------------------------------------------------------------------------
# Performance
# --------------------------------------------------------------------------
# PgBouncer transaction mode'da CONN_MAX_AGE=0 bo'lishi SHART, aks holda
# prepared statement konfliktlari chiqadi.
if env_bool("USE_PGBOUNCER", False):
    DATABASES["default"]["CONN_MAX_AGE"] = 0  # noqa: F405
    DATABASES["default"]["CONN_HEALTH_CHECKS"] = False  # noqa: F405
    DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True  # noqa: F405
else:
    DATABASES["default"]["CONN_MAX_AGE"] = DB_CONN_MAX_AGE  # noqa: F405

# Template'larni har so'rovda qayta parse qilmaslik.
TEMPLATES[0]["APP_DIRS"] = False  # noqa: F405
TEMPLATES[0]["OPTIONS"]["loaders"] = [  # noqa: F405
    (
        "django.template.loaders.cached.Loader",
        [
            "django.template.loaders.filesystem.Loader",
            "django.template.loaders.app_directories.Loader",
        ],
    )
]

# `STORAGES`, `STATICFILES_STORAGE` EMAS: ikkinchisi Django 5.1 da olib
# tashlangan va 6.x da JIMGINA e'tiborsiz qoladi — production oddiy
# `StaticFilesStorage` bilan ishlab, keshni bekor qiladigan xeshli nomlar
# yo'qolardi (brauzer yangi deploydan keyin eski JS/CSS ni ko'rsatardi).
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage",
    },
}

# API hujjati (`/api/schema/`) production'da o'chiq (`config/urls.py`), lekin
# drf-spectacular har `check` da sxemani yig'adi va o'nlab hujjat
# ogohlantirishlari `check --deploy` dagi haqiqiy xavfsizlik xabarlarini
# ko'mib yuborardi. `ENABLE_API_DOCS=true` bo'lsa ular yana ko'rinadi.
ENABLE_API_DOCS = env_bool("ENABLE_API_DOCS", False)
if not ENABLE_API_DOCS:
    SILENCED_SYSTEM_CHECKS = [
        *globals().get("SILENCED_SYSTEM_CHECKS", []),
        "drf_spectacular.W001",
        "drf_spectacular.W002",
    ]

# --------------------------------------------------------------------------
# Skrinshot storage
#
# Ikki yo'ldan KAMIDA BITTASI yoqilgan bo'lishi shart. Ikkalasi ham
# o'chirilgan bo'lsa, client skrinshot yuborolmaydi va imtihonning
# vizual dalili umuman yig'ilmaydi — buni ishga tushgandan keyin emas,
# hoziroq bilish kerak.
# --------------------------------------------------------------------------
_FILESYSTEM_SCREENSHOTS = env_bool("SCREENSHOT_FILESYSTEM_ENABLED", not STORAGE["ENABLED"])  # noqa: F405

if not STORAGE["ENABLED"] and not _FILESYSTEM_SCREENSHOTS:  # noqa: F405
    raise ImproperlyConfigured(
        "Skrinshot storage sozlanmagan: `S3_ENABLED=true` yoki "
        "`SCREENSHOT_FILESYSTEM_ENABLED=true` bo'lishi shart"
    )

if _FILESYSTEM_SCREENSHOTS:
    # `SERVE_DIRECTLY` production'da faylni gunicorn worker'i orqali
    # uzatadi. 30 ta proktor galereyani varaqlaganda bu butun API'ni
    # to'xtatadi, ustiga `internal` location himoyasi ham chetlab
    # o'tiladi. Bu dev qulayligi, production rejimi emas.
    if SCREENSHOT_STORAGE["SERVE_DIRECTLY"]:  # noqa: F405
        raise ImproperlyConfigured(
            "SCREENSHOT_SERVE_DIRECTLY production'da `false` bo'lishi SHART — "
            "fayllarni nginx `X-Accel-Redirect` orqali berishi kerak"
        )

    # Katalog ishga tushishda mavjud va yozilishi mumkin bo'lishi kerak.
    # Aks holda birinchi skrinshot kelganda 503 chiqadi va sabab
    # log'ning tubida qoladi.
    _SCREENSHOT_ROOT = SCREENSHOT_STORAGE["ROOT"]  # noqa: F405
    try:
        _SCREENSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    except OSError as _exc:
        raise ImproperlyConfigured(
            f"SCREENSHOT_ROOT yaratib bo'lmadi ({_SCREENSHOT_ROOT}): {_exc}"
        ) from _exc
    if not os.access(_SCREENSHOT_ROOT, os.W_OK):
        raise ImproperlyConfigured(
            f"SCREENSHOT_ROOT yozish uchun ochiq emas: {_SCREENSHOT_ROOT}"
        )
