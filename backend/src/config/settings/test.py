"""Test sozlamalari — tez va tashqi bog'liqliklarsiz."""

import tempfile
from pathlib import Path

from .base import *  # noqa: F403
from .base import REST_FRAMEWORK

DEBUG = False
ALLOWED_HOSTS = ["*"]

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "test",
    }
}
SESSION_ENGINE = "django.contrib.sessions.backends.db"

CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {
    key: None for key in REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
}

PROCTORING["REQUIRE_DEVICE_ID"] = False  # noqa: F405
EXTERNAL_PLATFORM["MOCK"] = True  # noqa: F405
STORAGE["ENABLED"] = False  # noqa: F405

# Testlar repo ichiga fayl yozmasin — har bir yurish o'z katalogida.
SCREENSHOT_STORAGE["ROOT"] = Path(  # noqa: F405
    tempfile.mkdtemp(prefix="proctoring-screenshots-")
)
SCREENSHOT_STORAGE["SERVE_DIRECTLY"] = True  # noqa: F405
