"""
Client konfiguratsiyasi — `.env` QATLAMI.

Sozlamalar `.env` dan o'qiladi. Qayerdan — `core/bundle_paths.env_file_path`
hal qiladi: `PROCTORING_ENV_FILE` -> (o'rnatilgan dasturda)
`%ProgramData%/ProctoringClient/.env` -> `.exe` yonidagi `.env`;
dev rejimda `client/.env`. Sabab: bitta build har bir imtihon
markazida boshqa server manzili bilan ishlashi kerak — qayta
kompilyatsiya qilmasdan.

IKKI QATLAM (`CLAUDE.md`: "Client sozlamalari: .env va panel"):

  * FAQAT SHU YERDA — serverga ulanishdan OLDIN kerak bo'ladigan
    (manzil, TLS, kiosk, monitorlar, dasturlarni yopish, standart
    tezkor tugmalar), MASHINAGA xos (kamera indeksi, GPU, disk) yoki
    lokal bo'lishi SHART bo'lgan qiymatlar;
  * ZAXIRA — imtihon/bino bo'yicha o'zgaradigan operatsion qiymatlar.
    Ularning egasi admin paneldagi `Setting` profili va ular
    `AppState.config` orqali keladi. Bu yerdagi qiymat faqat server
    javob bermagan yoki kalitni bilmaydigan eski server bo'lgan holat
    uchun. Ularni TO'G'RIDAN-TO'G'RI O'QIMANG — faqat
    `services/runtime_settings.get(config, "kalit")` orqali: aks
    holda panelda o'zgartirilgan qiymat shu sahifada jimgina
    e'tiborsiz qoladi.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from core.bundle_paths import env_file_path, is_frozen, resource_root, writable_root
from version import APP_NAME, __version__ as APP_VERSION

#: Yuklangan `.env` fayli (yoki `None`). `main` uni log'ga yozadi:
#: "qaysi server manzili?" degan savolga birinchi javob - qaysi fayl
#: o'qilgani. Frozen rejimda `None` deyarli har doim o'rnatish nosozligi.
ENV_FILE: Path | None = env_file_path()

# O'RNATILGAN dasturda `.env` MUHITDAN USTUN (`override=True`), dev'da
# esa aksincha. Sabab kiosk himoyasi: ProgramData'dagi faylni oddiy
# foydalanuvchi faqat o'qiy oladi, foydalanuvchi darajasidagi muhit
# o'zgaruvchisini esa istalgan talabgor yoza oladi
# (`setx KIOSK_MODE false`) va `override=False` bilan u administrator
# faylidan ustun turardi. Dev'da esa terminaldagi `set X=...` bilan
# vaqtincha almashtirish qulay va xavfsiz.
if ENV_FILE is not None:
    load_dotenv(dotenv_path=ENV_FILE, override=is_frozen())


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


def _env_list(name: str, default: str = "") -> list:
    """Vergul bilan ajratilgan ro'yxat (kichik harfda, bo'shlari tashlanadi)."""
    return [
        item.strip().lower()
        for item in os.getenv(name, default).split(",")
        if item.strip()
    ]


# `APP_NAME` / `APP_VERSION` — `version.py` dan (yuqorida import):
# spec, o'rnatuvchi va dastur bitta manbadan o'qiydi.

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
# Detektor ishonchi LOKAL va bu ataylab: u model YUKLANAYOTGANDA
# (`FaceAnalysis.prepare`) beriladi, model esa login formasi bilan
# parallel, ya'ni server javobidan OLDIN yuklanadi. Uni serverdan
# olish modelni har imtihon profilida qayta yuklashni talab qilardi.
FACE_DET_THRESH = _env_float("FACE_DET_THRESH", 0.6)

# Cosine similarity chegarasi — FAQAT ZAXIRA.
#
# Haqiqiy chegara SERVERDAN keladi va u imtihonga biriktirilgan
# sozlamada: `config.face.min_score_initial` (kirishda) va
# `config.face.min_score_exam` (test davomida), ikkalasi ham 0..100
# shkalada. Client ularni `score_to_cosine()` bilan o'giradi.
#
# Bu qiymat sozlama umuman kelmagan holat uchun (tarmoq xatosi):
# 0.42 cosine ~ 71 ball, ya'ni standart chegara bilan bir xil.
# Uni kattalashtirish aybsiz talabgorni to'sardi, kichraytirish esa
# tekshiruvni ma'nosiz qilardi.
FACE_MATCH_THRESHOLD = _env_float("FACE_MATCH_THRESHOLD", 0.42)

# ── GPU (CUDA) ───────────────────────────────────────────────────────
# GPU MAJBURIYMI. Standart `false`: CPU'da kuzatuv bir necha barobar
# sekin, lekin ISHLAYDI - butun imtihonni videokarta nosozligi
# tufayli to'xtatish bundan battar. `true` qiymati faqat GPU'li
# mashinalar uchun ataylab yig'ilgan o'rnatishda ma'noga ega:
# o'shanda model CPU'da yuklanishi jimgina emas, ochiq xato bo'ladi
# ("Model yuklanmadi") va administrator sababni darhol ko'radi.
#
# Qiymatdan qat'i nazar sabab har doim log'da va ekranda qoladi
# (`proctoring/hardware/cuda_runtime.py`).
FACE_REQUIRE_GPU = _env_bool("FACE_REQUIRE_GPU", False)

# CUDA kutubxonalari yotgan QO'SHIMCHA kataloglar (`;` bilan).
#
# Odatda kerak emas: `cuda_runtime` ularni `pip` paketlaridan
# (`nvidia-*`, `torch/lib`), .exe yonidagi `cuda/` katalogidan va
# `CUDA_PATH` dan o'zi topadi. Bu qiymat nostandart o'rnatish uchun
# - masalan kutubxonalar tarmoq diskida yoki boshqa versiyadagi
# Toolkit yonida turgan holat.
CUDA_DLL_DIR = os.getenv("CUDA_DLL_DIR", "").strip()

# Yuz bbox kengligi shundan kichik bo'lsa — solishtirilmaydi
# ("Yaqinroq keling"). ArcFace yuzni 112x112 ga tekislaydi, shuning uchun
# ~110 px dan kichik kadr upscale bo'lib, o'xshashlikni pasaytiradi.
#
# LOKAL: bu imtihon qoidasi emas, MODEL (112 px tekislash) va KADR
# O'LCHAMI (`FRAME_WIDTH`, u ham lokal) xususiyati. Yana: qoida
# `select_candidate_face` da va AI qatlami u bilan bir xil javob
# berishi shart ("KADRDA KIM TALABGOR") - imtihon profiliga qarab
# o'zgaradigan chegara ikki qatlamni ajratib yuborardi.
MIN_FACE_WIDTH_PX = _env_int("MIN_FACE_WIDTH_PX", 110)

# ── FaceID oqimi: ZAXIRA (egasi — panel, `Setting.faceid_*`) ─────────
# Quyidagi to'rttasi `config.face.{guide_seconds, match_streak,
# fail_streak, fail_min_seconds}` dan, IMTIHON PROFILIDAN keladi.
# Bu yerdagi qiymatlar faqat sozlama kelmagan holat uchun va ular
# modeldagi standartlar bilan bir xil.
#
# FaceID sahifasida kamera ochilgach talabgorga yuzini OVAL ichiga
# joylash uchun beriladigan vaqt (soniya). Shu vaqt ichida yuz
# aniqlanmaydi ham, solishtirilmaydi ham - sanoq tugagach boshlanadi.
#
# Nima uchun: kamera ochilishi bilan tekshiruv boshlansa, talabgor
# hali o'tirib ulgurmagan, boshini burgan yoki kameraga yaqinlashib
# kelayotgan bo'ladi. O'sha kadrlar "Yaqinroq keling", "Yuz topilmadi"
# yoki hatto past ball beradi va urinish boshidanoq buzilgan
# holatda boshlanardi. `0` - sanoq o'chiriladi (tekshiruv darhol).
FACE_GUIDE_SECONDS = _env_int("FACE_GUIDE_SECONDS", 5)

# Ketma-ket shuncha kadr mos kelsa — tasdiqlangan hisoblanadi. Bitta kadr
# yetarli emas: tasodifiy rakurs yoki blur yolg'on natija berishi mumkin.
FACE_MATCH_STREAK = _env_int("FACE_MATCH_STREAK", 3)

# Urinish MUVAFFAQIYATSIZ deb yopilishi uchun IKKALA shart ham
# bajarilishi kerak: ketma-ket shuncha kadr mos kelmasin VA shuncha
# vaqt o'tsin.
#
# Ikkitasi kerak — bu loyihaning temporal qatlamidagi bilan bir xil
# qoida ("bitta kadr hech qachon qaror emas"). Faqat kadr soniga
# tayanish tez kameradа 2-3 soniyada xulosa chiqarardi: ko'zoynagini
# to'g'rilayotgan yoki yon tomonga qaragan HAQIQIY talabgor ham
# "kira olmadi" bo'lib, operator har uch soniyada "Qaytadan urinish"
# ni bosishga majbur bo'lardi. Faqat vaqtga tayanish esa sekin
# kamerada bir nechta kadr bilan qaror qabul qilardi.
FACE_FAIL_STREAK = _env_int("FACE_FAIL_STREAK", 15)
FACE_FAIL_MIN_SECONDS = _env_float("FACE_FAIL_MIN_SECONDS", 8.0)

# ── Kamera ───────────────────────────────────────────────────────────
# Zaxira indeks: kamera taqsimoti hali aniqlanmagan holat uchun
# (masalan dev'da sahifani to'g'ridan-to'g'ri ochish). Odatdagi
# oqimda qurilmani ROL tanlaydi - `AppState.cameras` dagi taqsimot
# (`proctoring/camera/roles.py`), va u tekshiruv sahifasida
# operator ko'rgan/tanlagan taqsimotning O'ZI.
CAMERA_INDEX = _env_int("CAMERA_INDEX", 0)

# So'raladigan kadr o'lchami — BARCHA sahifalar uchun bitta qiymat.
#
# Ilgari FaceID sahifasi 640x480 so'rardi, kuzatuv va tekshiruv esa
# 1280x720. Natijada tekshiruvdan o'tgan rezolyutsiya bilan
# imtihondagi rezolyutsiya boshqa-boshqa bo'lardi va "min_width"
# siyosati aslida hech qachon FaceID kadriga qo'llanmagan bo'lardi.
FRAME_WIDTH = _env_int("FRAME_WIDTH", 1280)
FRAME_HEIGHT = _env_int("FRAME_HEIGHT", 720)
# Har nechanchi kadr detektsiyaga beriladi. Har kadrni ishlash CPU'da
# ~15 FPS ni 5 FPS ga tushiradi va oldindan ko'rish uzuq-yuluq bo'ladi.
DETECT_EVERY_NTH_FRAME = _env_int("DETECT_EVERY_NTH_FRAME", 3)

# ── Imtihon davomida: ZAXIRA (egasi — panel, `Setting` "Tarmoq") ─────
# Haqiqiy qiymatlar `config.network.heartbeat_interval` va
# `event_batch_interval` (soniyada). Ilgari client ularni UMUMAN
# o'qimasdi: panelda "Heartbeat intervali" bor edi, lekin hamma
# mashina shu yerdagi 30 s bilan ishlardi.
HEARTBEAT_INTERVAL_MS = _env_int("HEARTBEAT_INTERVAL_MS", 30_000)
EVENT_FLUSH_INTERVAL_MS = _env_int("EVENT_FLUSH_INTERVAL_MS", 5_000)
# Tarmoq uzilganda RAM'da ushlanadigan hodisalar soni - ZAXIRA
# (`config.network.offline_buffer_size`; ilgari u ham o'qilmasdi va
# navbat kodda 5000 ga qadab qo'yilgan edi).
OFFLINE_BUFFER_SIZE = _env_int("OFFLINE_BUFFER_SIZE", 5000)
# Backend `EventBatchSerializer` 200 tadan ko'pini qabul qilmaydi.
EVENT_BATCH_MAX = 200
# Davriy FaceID oralig'i — ZAXIRA qiymat.
#
# Haqiqiy oraliq serverdan keladi (`config.face.interval`, standart
# 10 s). Ilgari bu yerdagi 60 s ishlatilardi va u serverdagi sozlama
# bilan jimgina ziddiyatda edi: administrator 10 s qo'yardi, client
# esa daqiqada bir marta tekshirardi. Endi solishtirish clientda va
# u tarmoqqa chiqmaydi, ya'ni tez-tez tekshirish arzon.
PERIODIC_FACE_INTERVAL_MS = _env_int("PERIODIC_FACE_INTERVAL_MS", 60_000)

# ── Skrinshot ────────────────────────────────────────────────────────
# Skrinshot TAYMER BILAN OLINMAYDI — faqat test platformasi buyurganda
# (`POST /api/capture_screen`, pastdagi "Lokal xizmat"). Sifat, kenglik
# va serverga yuborish SERVERDAN keladi (`Setting` -> `config.capture`).
#
# `0` - skrinshot umuman olinmaydi. Faqat ishlab chiqish uchun:
# dasturchi ekranida shaxsiy oynalar bo'lishi mumkin.
SCREENSHOT_ENABLED = _env_bool("SCREENSHOT_ENABLED", True)

# Skrinshot serverga ham yuboriladimi - ZAXIRA. Egasi
# `config.capture.upload` (`Setting.is_screenshot_upload`): "faqat
# mashinada saqlash" yoki "saqlab, fonda serverga yuborish" - imtihon
# qarori. Standart `true`: sozlama kelmagan holatda proktor ekrani
# jimgina bo'sh qolmasligi kerak.
SCREENSHOT_UPLOAD = _env_bool("SCREENSHOT_UPLOAD", True)

# ── Lokal xizmat (test platformasi uchun) ────────────────────────────
# Client `127.0.0.1:<port>` da kichik HTTP xizmat ochadi
# (`services/local_service.py`): test platformasining frontendi
# `GET /api/device_info` (UUID, IP, MAC, kompyuter raqami) va
# `POST /api/capture_screen` (skrinshot buyrug'i) ga murojaat qiladi.
# Port platforma bilan SHARTNOMA - uni faqat platforma bilan birga
# o'zgartiring. Faqat loopback'da tinglanadi: tarmoqdan ko'rinmaydi.
LOCAL_SERVICE_ENABLED = _env_bool("LOCAL_SERVICE_ENABLED", True)
LOCAL_SERVICE_PORT = _env_int("LOCAL_SERVICE_PORT", 8050)
# Qo'shimcha ruxsat etilgan Origin'lar (vergul bilan), `*` - hammasi
# (faqat dev: platformani oddiy brauzerda sinash). Imtihon davomida
# test platformasining domenlari (`allowed_domains`) O'ZI qo'shiladi.
LOCAL_SERVICE_ALLOWED_ORIGINS = _env_list("LOCAL_SERVICE_ALLOWED_ORIGINS", "")

# "Client ishlab turibdi" signalining oralig'i (ms) - ZAXIRA.
#
# Haqiqiy qiymatni SERVER aytadi (`config.network.presence_interval`)
# va u panel maydoni emas: oraliq serverdagi presence TTL'iga
# bog'langan (`devices.services.PRESENCE_TTL`, 100 s - kamida ikki
# barobar katta bo'lishi shart, aks holda bitta kechikkan signal
# mashinani panelda "offline" qilardi) va ikkala son bitta joyda
# (`devices.services.PRESENCE_PING_INTERVAL`). Ilgari ular ikki
# tomonda alohida yashardi va TTL o'zgarsa 500 mashinani qo'lda
# tahrirlash kerak edi.
PRESENCE_PING_MS = _env_int("PRESENCE_PING_MS", 45_000)

# Skrinshot va dalillarning MAHALLIY nusxasi (`services/local_archive.py`).
#
# Serverga yuborish bundan MUSTAQIL va o'z holicha qoladi - arxiv
# ikkinchi nusxa: tarmoq uzilganda yoki dastur yopilganda navbatdagi
# kadrlar yo'qoladi, mashinadagi nusxa esa qoladi.
#
# DEV MASHINASIDA `false` QILING: aks holda dastur eng bo'sh diskda
# `ProctoringArchive` katalogini yaratib, ekran kadrlarini yozib
# boradi.
LOCAL_ARCHIVE_ENABLED = _env_bool("LOCAL_ARCHIVE_ENABLED", True)

# Arxiv ildizi - OCHIQ ko'rsatilgan yo'l.
#
# Bo'sh qoldirilsa eng bo'sh QAT'IY disk avtomatik tanlanadi
# (olinadigan va tarmoq disklari chetlab o'tiladi). Qiymat berilsa
# avtomatik tanlov umuman ishlamaydi: administrator diskni o'zi
# tanlagan bo'lsa, yangi disk ulangan kuni fayllar boshqa joyga
# ketmasligi kerak.
LOCAL_ARCHIVE_ROOT = os.getenv("LOCAL_ARCHIVE_ROOT", "").strip()

# Mashinadagi yozuvlar necha kun saqlanadi.
#
# Tozalash dastur ISHGA TUSHGANDA bir marta bajariladi. Muddatsiz
# arxiv diskni to'ldiradi: bitta ekran yozuvi ~360 MB, kuniga 2-3
# imtihon. `0` - tozalash o'chiriladi (administrator o'zi tozalaydi).
#
# ARXIVNING UCHALA QIYMATI LOKAL. Yoqilishi - dev bayrog'i (dasturchi
# diskiga talabgor ekrani yozilmasligi kerak); ildiz va muddat -
# MASHINA DISKIGA bog'liq (120 GB SSD va 2 TB HDD da "necha kun
# sig'adi" boshqa javob); tozalash esa serverga ulanishdan OLDIN
# bajariladi. Serverdagi muddat bu yerda xavfli ham bo'lardi: ishga
# tushishda zaxira bilan tozalab, keyin serverdan uzunroq muddat
# kelsa, dalil allaqachon o'chgan bo'lardi. Imtihon bo'yicha
# "mashinada nima qolsin" degan qaror panelda - `is_screen_record`.
LOCAL_ARCHIVE_RETENTION_DAYS = _env_int("LOCAL_ARCHIVE_RETENTION_DAYS", 30)

# ── Ekran yozuvi: ZAXIRA (egasi — panel, `Setting.screen_record_*`) ──
# Test sahifasi ochilgandan imtihon yakunlangunga qadar ekran video
# qilib yoziladi va u FAQAT mashinada qoladi - serverga uning
# manzili boradi (`services/screen_recorder.py`).
#
# Haqiqiy qiymatlar `config.capture.{screen_record, record_fps,
# record_width, record_pip_percent}` dan, IMTIHON PROFILIDAN (yozuv
# test sahifasi ochilganda boshlanadi). Ilgari panelda "Ekranni
# yozish" bor edi, lekin client uni o'qimasdi va shu bayroq bo'yicha
# yozardi - ikkita manba, ikkita javob.
SCREEN_RECORD_ENABLED = _env_bool("SCREEN_RECORD_ENABLED", True)

# Kadr chastotasi va kengligi - hajm bilan kelishuv.
#
# O'lchangan qiymatlar (mp4v, haqiqiy ekran + jonli kamera, 3 soat):
#   1280 @ 1 FPS -> ~110 MB   "qotib-qotib": har soniyada bitta kadr,
#                             matn PSNR 39.8 dB
#   1280 @ 5 FPS -> ~470 MB   silliq, matn PSNR 48.0 dB
#   1600 @ 5 FPS -> ~550 MB   <- standart: silliq va tiniqroq matn
#   1280 @ 8 FPS -> ~730 MB   5 FPS dan sezilarli silliq emas
#
# 5 FPS da video 1 FPS dagidan TINIQROQ ham chiqadi: ekran
# o'zgarmagan kadrlarda kodlovchi tasvirni aniqlashtirib boradi.
# Kenglikni pasaytirish esa dalilni YO'QOTADI - kichik shriftdagi
# savol matnini o'qib bo'lmay qoladi.
#
# Ekran FON THREAD'IDA olinadi (GDI, `services/screen_recorder.py`),
# ya'ni chastota test sahifasining (WebView) silliqligiga ta'sir
# qilmaydi - u faqat protsessor va disk bilan cheklanadi.
SCREEN_RECORD_FPS = _env_float("SCREEN_RECORD_FPS", 5.0)
SCREEN_RECORD_WIDTH = _env_int("SCREEN_RECORD_WIDTH", 1600)

# Kamera tasviri ekran yozuvining O'NG YUQORI burchagida (PiP) -
# "kompyuter oldida kim o'tirgan" degan savolga javob shu yerda.
#
# Kenglik ULUSH sifatida: qat'iy piksel yozuv kengligi
# o'zgarganda nisbatni buzardi. 12%: 1600 px yozuvda ~192x144 -
# yuz tanib olinadi, ekran mazmuni esa deyarli yopilmaydi (20% da
# 320x240 bo'lib, test sahifasining sezilarli qismini yopardi).
SCREEN_RECORD_PIP_RATIO = _env_float("SCREEN_RECORD_PIP_RATIO", 0.12)

# Skrinshotga ishlab turgan kamera kadri qo'shiladi - ekran OSTIGA
# qo'shilgan tasmadagi kichik ramkalarda (`services/camera_overlay.py`):
# yuz kamerasi o'ngda, ikkinchi kamera chapda. Ekran tasviri hech
# qayerda yopilmaydi. Ulush - skrinshot kengligiga nisbatan.
#
# ZAXIRA: egasi `config.capture.{camera_overlay, camera_overlay_percent}`
# (trafik bilan kelishuv - 500 mashina x har 10 s, ya'ni imtihon qarori).
#
# 960 px li skrinshotda 16% ~154 px: yuz tanib olinadi, tasma esa
# rasmni ~24% ga balandlashtiradi. Kattalashtirish har bir
# skrinshotni og'irlashtiradi (500 mashina x har 10 s).
SCREENSHOT_CAMERA_OVERLAY = _env_bool("SCREENSHOT_CAMERA_OVERLAY", True)
SCREENSHOT_PIP_RATIO = _env_float("SCREENSHOT_PIP_RATIO", 0.16)

# Kamera kadri shuncha soniyadan eski bo'lsa skrinshotga QO'YILMAYDI -
# o'rniga "kadr yo'q" ramkasi chiziladi. Eskirgan kadr o'tgan
# daqiqadagi odamni hozirgi ekran bilan birga ko'rsatardi.
#
# LOKAL: chegara KAMERAGA bog'liq - IP kamerada RTSP kechikishi
# 0.4-1.4 s o'lchangan, sekinroq kamerada undan ko'p. Imtihon
# qoidasi emas, apparat xususiyati.
CAMERA_FRAME_MAX_AGE_S = _env_float("CAMERA_FRAME_MAX_AGE_S", 3.0)

# Tarmoq uzilganda RAM'da saqlanadigan kadrlar soni. 20 x ~100 KB = 2 MB.
# Kattalashtirish uzilishga chidamlilikni oshiradi, lekin imtihon
# mashinasi (ko'pincha 4 GB RAM) da bu resurs tanqis - ya'ni qiymat
# MASHINANING XOTIRASIGA bog'liq va lokal qoladi.
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

# Bloklanadigan tezkor tugmalarning STANDART ro'yxati (vergul bilan).
#
# Dastur ishga tushishi bilan (preflight'dan OLDIN) qo'llanadi: ilgari
# ro'yxat faqat serverdan kelardi va preflight javobi kelguncha (server
# javob bermasa - umuman) mashina qulfsiz turardi - aynan talabgor
# oldida. Server ro'yxati kelsa (preflight, handshake, imtihon profili)
# u bu ro'yxatni ALMASHTIRADI; server BO'SH ro'yxat bersa bu standart
# QOLADI (`services/lockdown.py:resolve_hotkeys`).
#
# Faqat `KIOSK_MODE` da ishlaydi. `ctrl+q` bu yerda yozilsa ham
# bloklanmaydi - u chiqishning yagona yo'li. `alt+shift` (til
# almashtirish) ataylab YO'Q. Nusxa/qo'yish (`ctrl+c`/`ctrl+v`) ham
# yo'q: ular imtihon qoidasi va panelda imtihon profiliga yoziladi.
DEFAULT_BLOCKED_HOTKEYS = (
    "alt+tab,alt+shift+tab,alt+esc,win,ctrl+esc,alt+f4,alt+space,"
    "print screen,ctrl+shift+esc,f12,ctrl+shift+i"
)
BLOCKED_HOTKEYS = _env_list("BLOCKED_HOTKEYS", DEFAULT_BLOCKED_HOTKEYS)

# ── Ortiqcha monitorlar ──────────────────────────────────────────────
# Imtihon BITTA ekranda o'tadi. Ikkinchi monitor kiosk rejimining
# butun mantig'ini bekor qiladi: bizning oynamiz asosiy ekranni
# egallaydi, talabgor esa yonidagi ekranda ochiq qolgan hujjatni
# ko'rib turadi - skrinshot ham faqat asosiy ekranni oladi, ya'ni
# bayonnomada bundan iz qolmaydi. Tafsilotlar
# `services/display_control.py` da.
#
# Standart qiymati KIOSK_MODE dan: bu ham kiosk rejimining qismi va
# uni alohida yoqishni unutish "himoya bor deb o'ylash" holatini
# yaratardi. DEV MASHINASIDA `false` qiling - aks holda ikkinchi
# monitoringiz dastur ishga tushganda o'chadi.
DISABLE_EXTRA_MONITORS = _env_bool("DISABLE_EXTRA_MONITORS", KIOSK_MODE)

# O'chirilgan monitorlar dastur yopilishida QAYTARILADI.
#
# Uzish registrga yoziladi, ya'ni u qayta yuklashdan keyin ham
# saqlanadi. Qaytarmaslik mashinani imtihondan KEYIN ham bitta
# ekranda qoldirardi va operator uni Windows sozlamalaridan qo'lda
# tiklashga majbur bo'lardi. `false` faqat maxsus holat uchun:
# monitor umuman ishlatilmasligi kerak bo'lgan doimiy o'rnatish.
RESTORE_MONITORS_ON_EXIT = _env_bool("RESTORE_MONITORS_ON_EXIT", True)

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
CLOSE_OTHER_APPS_KEEP = _env_list("CLOSE_OTHER_APPS_KEEP")

# `WM_CLOSE` dan keyin dasturga saqlash uchun beriladigan vaqt.
CLOSE_OTHER_APPS_GRACE_S = _env_float("CLOSE_OTHER_APPS_GRACE_S", 3.0)

# ── Masofaviy boshqaruv va virtualizatsiyani tozalash ────────────────
# `CLOSE_OTHER_APPS` dan ALOHIDA bayroq va ikkalasi ham kerak: birinchisi
# ko'rinadigan oynasi bor har qanday dasturni yopadi, bu esa aynan
# nomma-nom tanilgan dasturni - OYNASI BO'LMASA HAM. AnyDesk xizmati,
# VBoxSVC va `remoting_host.exe` ning oynasi yo'q va ularni faqat
# ikkinchisi ko'radi. Tafsilotlar `services/threat_scanner.py` da.
#
# SKANER LOKAL, SIYOSAT PANELDA. Yoqilishi, ruxsat ro'yxati va VDI
# bayrog'i shu yerda qoladi: birinchi `sweep()` Qt'dan va serverdan
# OLDIN ishlaydi, ruxsat ro'yxati muassasaning o'z IT agenti (mashina
# obrazining qismi), VDI esa infratuzilma xususiyati. Qaysi dasturlar
# qidirilishi (`Setting.rdp_objects`) va topilgani imtihonni to'sishi
# (`Setting.is_threat_block_exam`) esa IMTIHON qarori va panelda.
THREAT_SCAN_ENABLED = _env_bool("THREAT_SCAN_ENABLED", KIOSK_MODE)

# Topilgan, lekin yo'q qilib bo'lmagan tahdid imtihonni TO'SADIMI -
# ZAXIRA (egasi `config.rdp.block_exam`, imtihon profilidan).
#
# Standart `true`: "topdim, lekin qo'limdan kelmadi" holatini jimgina
# o'tkazib yuborish tekshiruvning o'zini bekor qilardi. `false` qilinsa
# hodisa baribir yoziladi va proktor panelda ko'radi - faqat operator
# imtihonni boshlay oladi.
THREAT_BLOCK_EXAM = _env_bool("THREAT_BLOCK_EXAM", True)

# E'tiborsiz qoldiriladigan qoida kodlari yoki jarayon nomlari (vergul
# bilan): muassasaning o'z IT yordam agenti, inventarizatsiya dasturi.
# Kodlar ro'yxati `services/threat_rules.py` da (`anydesk`, `vnc`, ...).
THREAT_SCAN_ALLOW = _env_list("THREAT_SCAN_ALLOW")

# Client virtual mashina ICHIDA ishlashi mumkinmi.
#
# Standart `false`: mehmon tizimda kiosk rejimi ham, tezkor tugmalar
# bloki ham tashqariga chiqmaydi - talabgor yonida haqiqiy ish stolini
# ochiq qoldira oladi. VDI o'rnatishlarida (butun sinf virtual
# mashinalarda) buni `true` qilish kerak, aks holda hech bir mashina
# imtihonni boshlay olmaydi.
THREAT_ALLOW_VIRTUAL_HOST = _env_bool("THREAT_ALLOW_VIRTUAL_HOST", False)
