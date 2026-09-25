import os
import sys

from celery import Celery
from celery.schedules import crontab

from config.env import load_env  # noqa: E402

# `.env` dagi DJANGO_SETTINGS_MODULE shu yerda ko'rinishi uchun (`config/env.py`).
load_env()
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

app = Celery("proctoring")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# WINDOWS'DA `prefork` ISHLAMAYDI — va bu JIMGINA sodir bo'ladi.
#
# Celery'ning standart pool'i `fork()` ga tayanadi; Windows'da
# billiard uni taqlid qiladi, lekin vazifalar bola jarayonga
# yetib bormaydi: ishchi "ready" deydi, vazifalarni navbatdan OLADI,
# lekin birortasini ham BAJARMAYDI (`inspect stats` -> `"total": {}`).
# Ishlab chiqish mashinasida aynan shunday bo'lgan va ~3 hafta
# sezilmagan: hodisalar Redis oqimida qolib ketgan (DB'ga yozilmagan),
# `last_heartbeat_at` yangilanmagani uchun paneldagi sessiya "aloqa
# yo'q" bo'lib qolgan, xavf balli faqat sessiya yakunida paydo
# bo'lgan, broker navbatlarida esa ~93 000 ta vazifa to'plangan.
#
# `threads` Windows'da ishlaydi va bu yuklama uchun mos: vazifalar
# asosan I/O (Redis, PostgreSQL). Buyruq qatoridagi `-P` baribir USTUN
# turadi; Linux (production) `prefork` da qoladi.
if sys.platform == "win32":
    app.conf.worker_pool = "threads"

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
    # IP kameralar holati. `expires` oraliqdan kichik: navbat to'lib
    # qolsa eski tekshiruvlar to'planib, bir vaqtda ishga tushmasin.
    "probe-cameras": {
        "task": "devices.probe_cameras",
        "schedule": 60.0,
        "options": {"queue": "maintenance", "expires": 50},
    },
    "rotate-event-partitions": {
        "task": "proctoring.rotate_event_partitions",
        "schedule": crontab(hour=3, minute=0),
        # HAR davriy vazifada `expires` bo'lishi SHART: ishchi ishlamay
        # qolgan kunlarda navbatda to'plangan "tik"lar tiklangach
        # BIRDANIGA bajarilmasligi kerak (Windows `prefork` hodisasida
        # bu ikkitasi 26 martadan to'planib qolgan edi).
        "options": {"queue": "maintenance", "expires": 20 * 3600},
    },
    "purge-expired-artifacts": {
        "task": "proctoring.purge_expired_artifacts",
        "schedule": crontab(hour=4, minute=0),
        "options": {"queue": "maintenance", "expires": 20 * 3600},
    },
    # Fayl tizimidagi skrinshotlar — SOATIGA, kunlik emas.
    # 500 client × 3 soat × 10s ≈ 500 000 fayl/kun. Kunlik bitta yurishda
    # bu bir necha soatlik `unlink` bo'roni bo'lib, o'sha paytdagi
    # imtihonga xalaqit qiladi. Kichik soatlik partiyalar yukni yoyadi.
    # Dalillar SKRINSHOTLARDAN ALOHIDA tozalanadi: ularning muddati
    # qatorda yozilgan (siyosatdan), skrinshotniki esa sanadan
    # hisoblanadi.
    "purge-expired-evidence": {
        "task": "proctoring.purge_expired_evidence",
        "schedule": crontab(minute=25),
        "options": {"queue": "maintenance", "expires": 3300},
    },
    "purge-expired-screenshots": {
        "task": "proctoring.purge_expired_screenshots",
        "schedule": crontab(minute=30),
        "options": {"queue": "maintenance", "expires": 3300},
    },
    # FaceID kadrlari: KUNIGA bir marta yetadi. Ular skrinshotdan
    # ming barobar kam (sessiyaga bittadan + muvaffaqiyatsiz
    # tekshiruvlar), ya'ni soatlik yurish bo'sh so'rovdan boshqa
    # narsa bermasdi.
    "purge-expired-face-images": {
        "task": "proctoring.purge_expired_face_images",
        "schedule": crontab(hour=4, minute=20),
        "options": {"queue": "maintenance", "expires": 20 * 3600},
    },
}


@app.task(bind=True, name="debug.ping")
def ping(self):
    return "pong"
