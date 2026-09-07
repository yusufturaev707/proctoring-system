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

X_FRAME_OPTIONS = "DENY"

# Admin panelni standart bo'lmagan yo'lga ko'chirish (bot skanerlariga qarshi).
ADMIN_URL = env("ADMIN_URL", "admin/")


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

STATICFILES_STORAGE = "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"

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
