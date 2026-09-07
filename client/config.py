"""
Client konfiguratsiyasi.

Barcha sozlamalar `.env` dan o'qiladi (dev rejimda shu fayl yonidan,
frozen rejimda .exe yonidan). Sabab: bitta build har bir imtihon
markazida boshqa server manzili bilan ishlashi kerak — qayta kompilyatsiya
qilmasdan.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from core.bundle_paths import is_frozen, resource_root, writable_root

_ENV_PATH = (
    Path(sys.executable).parent / ".env"
    if is_frozen()
    else Path(__file__).resolve().parent / ".env"
)
load_dotenv(dotenv_path=_ENV_PATH, override=False)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


APP_NAME = "Proctoring Client"
APP_VERSION = "1.0.0"

# ── Backend ──────────────────────────────────────────────────────────
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api/v1").rstrip("/")
API_TIMEOUT = _env_float("API_TIMEOUT", 30.0)

# TLS: `1`/`0` yoki CA fayl yo'li. Production'da HTTPS + haqiqiy CA shart —
# `0` qiymati MITM'ga ochiq qoldiradi va faqat lokal dev uchun.
# WebSocket manzili (sxema + host, yo'lsiz): `ws://host:8001`.
#
# Bo'sh qoldirilsa `API_BASE_URL` dan chiqariladi
# (`services/realtime.py:default_ws_url`) - bu production'da to'g'ri,
# chunki nginx HTTP va WS ni bitta host ostida beradi. DEV'da esa
# MAJBURIY: u yerda WebSocket alohida process'da, boshqa portda
# (`uvicorn config.asgi:application --port 8001`) ishlaydi.
WS_BASE_URL = os.getenv("WS_BASE_URL", "").strip().rstrip("/")

_ssl_raw = os.getenv("API_SSL_VERIFY", "1").strip()
API_SSL_VERIFY: bool | str
if _ssl_raw in ("0", "false", "False", "no"):
    API_SSL_VERIFY = False
elif _ssl_raw in ("1", "true", "True", "yes"):
    API_SSL_VERIFY = True
else:
    API_SSL_VERIFY = _ssl_raw  # CA bundle yo'li

# ── Qurilma ──────────────────────────────────────────────────────────
# `X-Device-ID` — kredensial EMAS (backend `authentication.py` ga qarang),
# lekin u sessiyani binoga bog'laydi. Fayl %APPDATA% da yashaydi, ya'ni
# dastur qayta o'rnatilsa ham saqlanadi.
DEVICE_ID_FILE = writable_root() / "device_id.json"

# Ixtiyoriy inventar kodi. Berilsa, ro'yxatdan o'tishda MAC bilan birga
# yuboriladi va server uni ikkinchi belgi sifatida ishlatadi (MAC birinchi).
# Ommaviy o'rnatishda uni har bir mashinaning `.env` iga yozib qo'yish
# qulay: shunda MAC manzilini oldindan bazaga kiritish shart emas.
INVENTORY_CODE = os.getenv("INVENTORY_CODE", "").strip()

# ── InsightFace ──────────────────────────────────────────────────────
FACE_MODEL_NAME = os.getenv("FACE_MODEL_NAME", "buffalo_l")
FACE_MODEL_ROOT = resource_root()          # ичида models/<name>/ izlanadi
FACE_DET_SIZE = (640, 640)
FACE_DET_THRESH = _env_float("FACE_DET_THRESH", 0.6)

# Cosine similarity chegarasi. Backend'ga 0..100 shkalada `score` yuboriladi,
# lekin qaror shu yerda ham chiqariladi (operatorga darhol ko'rsatish uchun).
FACE_MATCH_THRESHOLD = _env_float("FACE_MATCH_THRESHOLD", 0.42)

# Yuz bbox kengligi shundan kichik bo'lsa — solishtirilmaydi
# ("Yaqinroq keling"). ArcFace yuzni 112x112 ga tekislaydi, shuning uchun
# ~110 px dan kichik kadr upscale bo'lib, o'xshashlikni pasaytiradi.
MIN_FACE_WIDTH_PX = _env_int("MIN_FACE_WIDTH_PX", 110)

# Ketma-ket shuncha kadr mos kelsa — tasdiqlangan hisoblanadi. Bitta kadr
# yetarli emas: tasodifiy rakurs yoki blur yolg'on natija berishi mumkin.
FACE_MATCH_STREAK = _env_int("FACE_MATCH_STREAK", 3)

# ── Kamera ───────────────────────────────────────────────────────────
CAMERA_INDEX = _env_int("CAMERA_INDEX", 0)
FRAME_WIDTH = _env_int("FRAME_WIDTH", 640)
FRAME_HEIGHT = _env_int("FRAME_HEIGHT", 480)
# Har nechanchi kadr detektsiyaga beriladi. Har kadrni ishlash CPU'da
# ~15 FPS ni 5 FPS ga tushiradi va oldindan ko'rish uzuq-yuluq bo'ladi.
DETECT_EVERY_NTH_FRAME = _env_int("DETECT_EVERY_NTH_FRAME", 3)

# ── Imtihon davomida ─────────────────────────────────────────────────
HEARTBEAT_INTERVAL_MS = _env_int("HEARTBEAT_INTERVAL_MS", 30_000)
EVENT_FLUSH_INTERVAL_MS = _env_int("EVENT_FLUSH_INTERVAL_MS", 5_000)
# Backend `EventBatchSerializer` 200 tadan ko'pini qabul qilmaydi.
EVENT_BATCH_MAX = 200
PERIODIC_FACE_INTERVAL_MS = _env_int("PERIODIC_FACE_INTERVAL_MS", 60_000)

# ── Skrinshot ────────────────────────────────────────────────────────
# Interval, sifat, kenglik va dedup chegarasi SERVERDAN keladi
# (`Setting` -> handshake `config.capture`) - ular imtihonga qarab
# o'zgaradi va clientda qadab qo'yilmasligi kerak. Bu yerda faqat
# mashinaga bog'liq ikkita qiymat qoladi.
#
# `0` - skrinshot umuman olinmaydi. Faqat ishlab chiqish uchun:
# dasturchi ekranida shaxsiy oynalar bo'lishi mumkin.
SCREENSHOT_ENABLED = _env_bool("SCREENSHOT_ENABLED", True)

# Tarmoq uzilganda RAM'da saqlanadigan kadrlar soni. 20 x ~100 KB = 2 MB.
# Kattalashtirish uzilishga chidamlilikni oshiradi, lekin imtihon
# mashinasi (ko'pincha 4 GB RAM) da bu resurs tanqis.
SCREENSHOT_RETRY_QUEUE = _env_int("SCREENSHOT_RETRY_QUEUE", 20)

# ── UI ───────────────────────────────────────────────────────────────
# Imtihon rejimida to'liq ekran majburiy: oynadan chiqish yo'llari
# kamayadi. Dev'da uni o'chirib qo'yish qulay (DevTools, log ko'rish).
FULLSCREEN = _env_bool("FULLSCREEN", True)

# Kiosk rejimi: ramkasiz + doim ustda oyna, global tezkor tugma
# bloklash va parolsiz yopilmaslik.
#
# Standart qiymati FULLSCREEN dan olinadi va bu ataylab: `FULLSCREEN=0`
# yozgan dasturchi dev mashinasida to'satdan Alt+Tab'i ishlamay
# qolishini va oynani yopa olmasligini kutmaydi. Ikkalasini alohida
# boshqarish kerak bo'lsa, `KIOSK_MODE` ni ochiq yozing.
KIOSK_MODE = _env_bool("KIOSK_MODE", FULLSCREEN)

# ── Ishga tushishda boshqa dasturlarni yopish ────────────────────────
# Imtihon mashinasi toza holatda boshlanishi kerak: ochiq brauzer,
# messenjer yoki masofaviy boshqaruv oynasi - nazoratdan tashqaridagi
# kanal. Tafsilotlar `services/app_closer.py` da.
#
# Standart qiymati KIOSK_MODE dan olinadi: bu funksiya kiosk rejimining
# bir qismi va uni alohida yoqishni unutish "himoya bor deb o'ylash"
# holatini yaratardi.
#
# DIQQAT: dev mashinasida buni ochiq `false` qiling. `KIOSK_MODE=true`
# bo'lgan ishlab chiqish muhitida dastur muharrir va terminalni ham
# yopadi - saqlanmagan ish yo'qoladi.
CLOSE_OTHER_APPS = _env_bool("CLOSE_OTHER_APPS", KIOSK_MODE)

# Yopilmaydigan qo'shimcha dasturlar (vergul bilan): antivirus, IT
# agenti, muassasaning o'z dasturi. Tizim jarayonlari va qobiq
# allaqachon kodda himoyalangan.
CLOSE_OTHER_APPS_KEEP = [
    name.strip().lower()
    for name in os.getenv("CLOSE_OTHER_APPS_KEEP", "").split(",")
    if name.strip()
]

# `WM_CLOSE` dan keyin dasturga saqlash uchun beriladigan vaqt.
CLOSE_OTHER_APPS_GRACE_S = _env_float("CLOSE_OTHER_APPS_GRACE_S", 3.0)
