"""
Gunicorn konfiguratsiyasi (HTTP API uchun).

Worker turi tanlash — bu yerdagi eng muhim qaror:

  sync    : har bir worker bitta so'rovni bajaradi. Tashqi API chaqiruvi
            5 soniya kutsa, worker 5 soniya BLOKLANADI. 1000 talaba bir
            vaqtda "Kirish" bossa, 32 worker'li server o'lik holga keladi.

  gthread : har bir worker N ta thread. I/O kutish (ntest, Postgres, Redis)
            thread'ni bloklaydi, lekin worker'ni emas. Bizning yuk profili
            aynan I/O-bound, shuning uchun BUNI TANLAYMIZ.

  gevent  : yanada yuqori konkurrentlik, lekin psycopg2 monkey-patch bilan
            nozik ishlaydi. Ehtiyot bo'ling.

Ishga tushirish:
    gunicorn config.wsgi:application -c deploy/gunicorn.conf.py
"""

import multiprocessing
import os
from pathlib import Path

# `config` paketi `backend/src` da. Dev'da u `pip install -e .` bilan yo'lga
# tushgan, serverda esa bunga tayanmaymiz: gunicorn qayerdan ishga
# tushirilsa ham paketni topadi.
pythonpath = str(Path(__file__).resolve().parent.parent / "src")

# STANDART — FAQAT LOKAL: API nginx ortida turadi. `0.0.0.0` gunicorn'ni
# tarmoqqa to'g'ridan-to'g'ri ochardi: nginx'dagi rate limit chetlab
# o'tiladi, `TRUSTED_PROXY_COUNT=1` da esa soxta `X-Forwarded-For` bilan
# IP ro'yxatini aldash mumkin bo'lardi. Bir necha node — `GUNICORN_BIND`.
bind = os.getenv("GUNICORN_BIND", "127.0.0.1:8002")

worker_class = "gthread"
# Standart 10 (ilgari `2*CPU+1` = 20 yadroda 41). Sabablar (L2 o'lchovi,
# `deploy/MONITORING.md`): worker RSS ~105 MB (o'lchangan, Windows WS),
# so'rov ~5–20 ms (o'lchangan, perf DB); 5000 talaba barqaror ~250 r/s ->
# ~2.5 yadro, login to'lqini ~800 r/s -> ~8 yadro (hisoblangan). 10x8 = 80
# parallel so'rov; qolgan yadrolar uvicorn/Celery/Redis/nginx uchun.
# 41x8 = 328 potensial DB ulanishi PgBouncer pool'idan ancha ko'p edi.
workers = int(os.getenv("GUNICORN_WORKERS", min(10, multiprocessing.cpu_count() * 2 + 1)))
threads = int(os.getenv("GUNICORN_THREADS", 8))

# Bitta so'rov 30 soniyadan ko'p ketmasligi kerak. Tashqi API timeout'i 8s,
# DB statement_timeout 15s — 30s yetarli zaxira.
timeout = 30
graceful_timeout = 30
# Nginx keep-alive'dan biroz uzunroq bo'lishi kerak, aks holda 502 chiqadi.
keepalive = 65
# Login to'lqinida navbat (5000 client 1–5 daqiqada); `net.core.somaxconn`
# ham shundan kichik bo'lmasin (`deploy/sysctl-proctoring.conf`).
backlog = int(os.getenv("GUNICORN_BACKLOG", 4096))

# Xotira sizishining oldini olish: worker ma'lum so'rovdan keyin qayta tug'iladi.
# `jitter` — barcha worker'lar bir vaqtda qayta ishga tushmasligi uchun.
max_requests = 2000
max_requests_jitter = 200

preload_app = True
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info").lower()
access_log_format = '%(h)s %(l)s %(t)s "%(r)s" %(s)s %(b)s %(D)sµs "%({X-Request-ID}o)s"'


def post_fork(server, worker):
    """
    Fork'dan keyin ulanish pool'larini tiklaymiz.

    `preload_app=True` bilan ota-process pool'lari fork'da nusxalanadi va
    bir nechta worker bitta TCP soketni bo'lishib, ma'lumotni buzadi.
    """
    from apps.common.redis_client import reset_pool

    reset_pool()

    from django.db import connections

    connections.close_all()
