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

bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")

worker_class = "gthread"
workers = int(os.getenv("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))
threads = int(os.getenv("GUNICORN_THREADS", 8))

# Bitta so'rov 30 soniyadan ko'p ketmasligi kerak. Tashqi API timeout'i 8s,
# DB statement_timeout 15s — 30s yetarli zaxira.
timeout = 30
graceful_timeout = 30
# Nginx keep-alive'dan biroz uzunroq bo'lishi kerak, aks holda 502 chiqadi.
keepalive = 65

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
