"""
HTTP API'ni Windows'da gunicorn `gthread` ga YAQIN ishga tushirish.

    uvicorn lt_http_app:app --workers 10      (`tools/local_stack.ps1 -HttpWorkers`)

NIMA UCHUN `config.asgi` EMAS: Django ASGI ostida sinxron view HAR SO'ROV
uchun yangi thread'da ishlaydi (asgiref `ThreadSensitiveContext`), DB
ulanishi esa thread'ga bog'langan — `CONN_MAX_AGE > 0` bilan ulanishlar
yopilmay yig'iladi (sinovda bitta jarayon 17 tagacha ushladi va
PostgreSQL `max_connections` ga yetib, so'rovlar 500 bilan yiqildi).
Production gunicorn (`deploy/gunicorn.conf.py`) — WSGI, QAT'IY thread
pool, ya'ni ulanishlar soni = jarayonlar × thread'lar. Bu yerda ham
xuddi shunday: uvicorn WSGI adapteri, `LT_HTTP_THREADS` ta thread.
"""

import os

from uvicorn.middleware.wsgi import WSGIMiddleware

from config.wsgi import application

app = WSGIMiddleware(application, workers=int(os.getenv("LT_HTTP_THREADS", "8")))
