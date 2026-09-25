"""
`backend/.env` ni sozlama moduli TANLANISHIDAN OLDIN yuklash.

`settings/base.py` ham `.env` ni o'qiydi, lekin u juda kech:
`DJANGO_SETTINGS_MODULE` ni `manage.py`, `wsgi.py`, `asgi.py` va
`celery.py` undan OLDIN tanlaydi (`setdefault(... "config.settings.local")`).
Natijada `.env` dagi `DJANGO_SETTINGS_MODULE=config.settings.production`
jimgina e'tiborsiz qolardi va gunicorn/uvicorn/Celery production serverida
LOCAL sozlamalar bilan ishlardi — DEBUG, throttling o'chiq, fayllarni Django
beradi. Har kirish nuqtasi shu funksiyani `setdefault` dan oldin chaqiradi.

`override=False`: haqiqiy muhit o'zgaruvchisi (systemd `Environment=`,
`--settings`) har doim `.env` dan ustun.
"""

from pathlib import Path

from dotenv import load_dotenv

# src/config/env.py -> backend/
ROOT_DIR = Path(__file__).resolve().parent.parent.parent


def load_env() -> None:
    load_dotenv(ROOT_DIR / ".env", override=False)
