"""Test sozlamalari — tez va tashqi bog'liqliklarsiz."""

import tempfile
from pathlib import Path

from .base import *  # noqa: F403
from .base import REST_FRAMEWORK

DEBUG = False
ALLOWED_HOSTS = ["*"]

# `python manage.py test` ni argumentsiz ishlatish uchun
# (sabab `config/test_runner.py` da).
TEST_RUNNER = "config.test_runner.ProctoringTestRunner"

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Testlar xato yo'llarini ATAYLAB bosib o'tadi (buzilgan IntegrityError,
# xavfli fayl yo'li, tashlab yuborilgan hodisa) va ularning har biri
# `WARNING`/`ERROR` yozadi. Bu yozuvlar test chiqishini to'ldirib,
# HAQIQIY nosozlikni ko'rinmas qiladi. Yozuv kerak bo'lsa testda
# `assertLogs` ishlatiladi — u bu sozlamadan qat'i nazar ishlaydi.
LOGGING["root"]["level"] = "CRITICAL"  # noqa: F405
LOGGING["loggers"]["apps"]["level"] = "CRITICAL"  # noqa: F405

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "test",
    }
}
SESSION_ENGINE = "django.contrib.sessions.backends.db"

CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

# Sessiya holati va event stream uchun ALOHIDA Redis bazasi.
#
# Xom Redis'ni (cache'dan farqli) soxtalashtirib bo'lmaydi: kod
# `XADD`, `XAUTOCLAIM` va Lua skriptlariga tayanadi. Shuning uchun
# testlar haqiqiy Redis'da ishlaydi, LEKIN alohida bazada: `TestCase`
# DB tranzaksiyasini qaytaradi, Redis esa qaytarmaydi va testlar dev
# muhitidagi jonli sessiyalarni o'chirib yuborardi.
#
# 15-baza faqat testlar uchun; `RedisStateMixin` uni har testdan oldin
# tozalaydi.
REDIS_STATE_URL = f"{REDIS_URL}/15"  # noqa: F405

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {
    key: None for key in REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
}

PROCTORING["REQUIRE_DEVICE_ID"] = False  # noqa: F405
# `.env` dagi qiymat testlarga O'TMASIN: dasturchining lokal sozlamasi
# (`REQUIRE_COMPUTER_BOOKING=true`, `ALLOW_PRIVATE_SOURCE_IP=true`) ilgari
# sessiya va IP ro'yxati testlarini yiqitardi. Bu qoidalarni tekshiradigan
# testlar ularni `override_settings` bilan o'zi yoqadi.
PROCTORING["REQUIRE_COMPUTER_BOOKING"] = False  # noqa: F405
PROCTORING["ALLOW_PRIVATE_SOURCE_IP"] = False  # noqa: F405
PROCTORING["REQUIRE_MACHINE_MAC"] = False  # noqa: F405
EXTERNAL_PLATFORM["MOCK"] = True  # noqa: F405
STORAGE["ENABLED"] = False  # noqa: F405

# Testlar repo ichiga fayl yozmasin — har bir yurish o'z katalogida.
SCREENSHOT_STORAGE["ROOT"] = Path(  # noqa: F405
    tempfile.mkdtemp(prefix="proctoring-screenshots-")
)
SCREENSHOT_STORAGE["SERVE_DIRECTLY"] = True  # noqa: F405
