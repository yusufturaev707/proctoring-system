import os

from django.core.wsgi import get_wsgi_application

from config.env import load_env  # noqa: E402

# `.env` dagi DJANGO_SETTINGS_MODULE shu yerda ko'rinishi uchun (`config/env.py`).
load_env()
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

application = get_wsgi_application()
