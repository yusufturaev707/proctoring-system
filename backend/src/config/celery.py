import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

app = Celery("proctoring")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# --------------------------------------------------------------------------
# Periodik vazifalar
#
# Ingest buffer'lari tez-tez, texnik xizmat vazifalari kamdan-kam ishlaydi.
# Buffer flush intervali — kechikish va DB yozish soni orasidagi muvozanat:
# 5s => sekundiga 2000 event bo'lsa, bitta COPY'da ~10 000 qator.
# --------------------------------------------------------------------------
app.conf.beat_schedule = {
    "flush-event-buffer": {
        "task": "proctoring.flush_event_buffer",
        "schedule": 5.0,
        "options": {"queue": "ingest", "expires": 10},
    },
    "flush-screenshot-buffer": {
        "task": "proctoring.flush_screenshot_buffer",
        "schedule": 5.0,
        "options": {"queue": "ingest", "expires": 10},
    },
    "flush-session-state": {
        "task": "proctoring.flush_session_state",
        "schedule": 10.0,
        "options": {"queue": "ingest", "expires": 20},
    },
    "close-stale-sessions": {
        "task": "proctoring.close_stale_sessions",
        "schedule": 60.0,
        "options": {"queue": "maintenance", "expires": 55},
    },
    "refresh-device-status": {
        "task": "devices.refresh_device_status",
        "schedule": 30.0,
        "options": {"queue": "maintenance", "expires": 25},
    },
    "rotate-event-partitions": {
        "task": "proctoring.rotate_event_partitions",
        "schedule": crontab(hour=3, minute=0),
        "options": {"queue": "maintenance"},
    },
    "purge-expired-artifacts": {
        "task": "proctoring.purge_expired_artifacts",
        "schedule": crontab(hour=4, minute=0),
        "options": {"queue": "maintenance"},
    },
    # Fayl tizimidagi skrinshotlar — SOATIGA, kunlik emas.
    # 500 client × 3 soat × 10s ≈ 500 000 fayl/kun. Kunlik bitta yurishda
    # bu bir necha soatlik `unlink` bo'roni bo'lib, o'sha paytdagi
    # imtihonga xalaqit qiladi. Kichik soatlik partiyalar yukni yoyadi.
    "purge-expired-screenshots": {
        "task": "proctoring.purge_expired_screenshots",
        "schedule": crontab(minute=30),
        "options": {"queue": "maintenance", "expires": 3300},
    },
}


@app.task(bind=True, name="debug.ping")
def ping(self):
    return "pong"
