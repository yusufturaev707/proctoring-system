"""
Skrinshotni qabul qilish, saqlash va yetkazish.

Bu yo'l S3 yo'lidan (`services/ingest.py` + presigned URL) TUBDAN farq
qiladi va buni bilib turib tanlash kerak:

    presigned  : binary backend'dan o'tmaydi, ~120 MB/s trafik nolga teng
    filesystem : binary Django worker'idan O'TADI

Ya'ni bu modul yuklama bo'yicha yutuqni emas, sodda infratuzilmani
tanlaydi: MinIO/S3 ko'tarilmagan, bitta serverli o'rnatishlar uchun.
Chegara taxminan bitta bino (~500 client); undan yuqorisida presigned
yo'liga qaytish kerak.

**Qaytarishda esa Django baribir ishtirok etmaydi**: `screenshot_response`
faqat ruxsatni tekshirib, `X-Accel-Redirect` beradi — faylni nginx o'qiydi.

Yozish tartibi ataylab shunday:

    1. baytlarni o'qi (chegara bilan)
    2. HAQIQIY turini aniqla (Pillow) — client aytganiga ishonmaymiz
    3. sha256
    4. faylni atomik yoz
    5. DB qatorini yarat; yiqilsa — faylni o'chir

Fayl avval, qator keyin. Teskarisida (qator avval) fayl yozilmay qolsa,
DB'da "bor" deb ko'rinadigan, lekin ochilmaydigan dalil qoladi — proktor
uchun bu eng yomon holat. Bu tartibda esa eng yomon holat — hech kim
bilmaydigan yetim fayl, va u DB tranzaksiyasi yiqilganda darhol
o'chiriladi.
"""

from __future__ import annotations

import hashlib
import io
import logging
from datetime import datetime
from datetime import timezone as dt_timezone

from django.conf import settings
from django.db import DatabaseError
from django.http import HttpResponseBase
from PIL import Image

from apps.common.exceptions import (
    ScreenshotNotFound,
    ScreenshotRejected,
    ScreenshotStoreFailed,
    ScreenshotTooLarge,
)
from apps.common.screenshot_storage import (
    ScreenshotAlreadyExists,
    get_screenshot_storage,
)
from apps.proctoring.models import ProctoringScreenshot
from apps.proctoring.services import ingest
from apps.proctoring.services import state as session_state

logger = logging.getLogger(__name__)

#: Nom band bo'lib chiqsa shuncha marta `seq` oshirib qayta urinamiz.
#: Bu faqat parallel yuklashlar to'qnashganda ishlaydi, ya'ni juda kam.
_MAX_PATH_ATTEMPTS = 10

__all__ = ["screenshot_store", "screenshot_response", "screenshot_delete"]


# --------------------------------------------------------------------------
# Yozish
# --------------------------------------------------------------------------
def screenshot_store(*, session, upload, captured_at: datetime) -> ProctoringScreenshot:
    """
    Yuklangan faylni tekshiradi, diskka yozadi va metadata qatorini yaratadi.

    `upload` — `UploadedFile` (DRF `FileField`).
    """
    data = _read_upload(upload)
    _image_format, mime_type, extension, dimensions = _detect_image(data)
    content_hash = hashlib.sha256(data).hexdigest()

    # Client soati adashgan bo'lsa vaqtni maqbul oynaga tortamiz —
    # aks holda fayl nomi 2030-yilda paydo bo'ladi va retention unga
    # hech qachon yetmaydi. Original qiymat yo'qolmaydi: u hodisa
    # oqimida (`clamp_time`) allaqachon qayd etilgan.
    captured_at, _original = ingest.clamp_time(captured_at)

    seq = _next_seq(session)
    storage = get_screenshot_storage()

    relative_path = ""
    for _attempt in range(_MAX_PATH_ATTEMPTS):
        relative_path = _build_relative_path(
            exam_id=session.exam_id,
            session_id=session.pk,
            captured_at=captured_at,
            seq=seq,
            extension=extension,
        )
        try:
            storage.save(relative_path, data)
            break
        except ScreenshotAlreadyExists:
            # Bir soniyada bir necha kadr yoki parallel yuklash.
            seq += 1
        except OSError as exc:
            logger.error("Skrinshot diskka yozilmadi (%s): %s", relative_path, exc)
            raise ScreenshotStoreFailed() from exc
    else:
        logger.error(
            "Skrinshot uchun bo'sh nom topilmadi: session=%s captured_at=%s",
            session.pk, captured_at,
        )
        raise ScreenshotStoreFailed()

    try:
        screenshot = ProctoringScreenshot.objects.create(
            session=session,
            file_path=relative_path,
            content_hash=content_hash,
            file_size=len(data),
            mime_type=mime_type,
            seq=seq,
            captured_at=captured_at,
        )
    except DatabaseError:
        # Yetim fayl qoldirmaymiz: uni keyin topish uchun butun daraxtni
        # DB bilan solishtirish kerak bo'ladi.
        storage.delete(relative_path)
        raise

    # Ketma-ket bir xil hash — client oldindan yozilgan tasvirni
    # uzatayotganining eng oson aniqlanadigan belgisi. S3 yo'lida ham
    # aynan shu tekshiruv ishlaydi.
    ingest.check_frozen_frames(session, content_hash)

    logger.debug(
        "Skrinshot saqlandi: session=%s path=%s %sx%s %s bayt",
        session.pk, relative_path, dimensions[0], dimensions[1], len(data),
    )
    return screenshot


def screenshot_delete(screenshot: ProctoringScreenshot) -> bool:
    """
    Fayl va qatorni birga o'chiradi (avval fayl).

    Retention ham, qo'lda o'chirish ham shu yo'ldan yuradi.
    """
    deleted = get_screenshot_storage().delete(screenshot.file_path)
    screenshot.delete()
    return deleted


# --------------------------------------------------------------------------
# Yetkazish
# --------------------------------------------------------------------------
def screenshot_response(screenshot: ProctoringScreenshot) -> HttpResponseBase:
    """
    Ruxsat allaqachon tekshirilgan skrinshot uchun HTTP javobi.

    Javobda tana YO'Q — faqat `X-Accel-Redirect`. Ya'ni bu funksiya
    qaytgandan keyin gunicorn worker'i bo'shaydi va 2 MB faylni nginx
    o'z tezligida uzatadi. Faylni Python orqali o'qish (`FileResponse`)
    worker'ni butun uzatish davomida band qilib turadi — 30 ta proktor
    galereyani varaqlasa, API o'lib qoladi.
    """
    extension = screenshot.file_path.rsplit(".", 1)[-1] if "." in screenshot.file_path else "jpg"
    try:
        return get_screenshot_storage().serve(
            screenshot.file_path,
            content_type=screenshot.mime_type or "application/octet-stream",
            filename=f"session-{screenshot.session_id}-{screenshot.pk}.{extension}",
        )
    except FileNotFoundError as exc:
        logger.warning(
            "Skrinshot qatori bor, fayl yo'q: id=%s path=%s",
            screenshot.pk, screenshot.file_path,
        )
        raise ScreenshotNotFound() from exc


# --------------------------------------------------------------------------
# Ichki yordamchilar
# --------------------------------------------------------------------------
def _read_upload(upload) -> bytes:
    """
    Yuklangan faylni chegara bilan o'qiydi.

    `upload.size` ga ISHONMAYMIZ — u `Content-Length` dan keladi va uni
    client istalgancha yozishi mumkin. Shuning uchun chegara o'qish
    paytida ham qayta tekshiriladi: aks holda "size=1KB" deb aytib,
    1 GB yuborish mumkin bo'lardi.
    """
    max_bytes = settings.SCREENSHOT_STORAGE["MAX_BYTES"]

    declared = getattr(upload, "size", None)
    if declared is not None and declared > max_bytes:
        raise ScreenshotTooLarge(
            f"Skrinshot {declared} bayt, chegara {max_bytes} bayt"
        )

    buffer = io.BytesIO()
    total = 0
    for chunk in upload.chunks():
        total += len(chunk)
        if total > max_bytes:
            raise ScreenshotTooLarge(
                f"Skrinshot {max_bytes} baytdan katta"
            )
        buffer.write(chunk)

    data = buffer.getvalue()
    if not data:
        raise ScreenshotRejected("Bo'sh fayl")
    return data


def _detect_image(data: bytes) -> tuple[str, str, str, tuple[int, int]]:
    """
    Faylning HAQIQIY turini baytlaridan aniqlaydi.

    Client bergan `Content-Type` ham, fayl kengaytmasi ham tekshirilmaydi:
    ikkalasi ham client yozadigan oddiy satr. `screen.jpg` nomi ostida
    HTML yoki SVG kelsa, nginx uni bizning `internal` location'dan
    beradi va proktorning brauzerida ochiladi — ya'ni saqlangan XSS.
    Yagona ishonchli manba — baytlarning o'zi.

    Qaytaradi: `(format, mime_type, extension, (width, height))`.
    """
    conf = settings.SCREENSHOT_STORAGE

    try:
        # `Image.open` faqat sarlavhani o'qiydi, piksellarni ochmaydi —
        # shuning uchun o'lchamni undan OLDIN tekshirish mumkin.
        with Image.open(io.BytesIO(data)) as image:
            image_format = (image.format or "").upper()
            width, height = image.size
    except Exception as exc:
        raise ScreenshotRejected("Fayl haqiqiy rasm emas") from exc

    allowed = conf["ALLOWED_FORMATS"]
    if image_format not in allowed:
        raise ScreenshotRejected(
            f"Format qo'llab-quvvatlanmaydi: {image_format or 'noma`lum'}"
        )

    if width * height > conf["MAX_PIXELS"]:
        # Dekompressiya bombasi: 50 KB PNG ochilganda 30 GB RAM so'rashi
        # mumkin. Bu tekshiruv ochishdan OLDIN turishi shart.
        raise ScreenshotRejected(
            f"Rasm o'lchami juda katta: {width}x{height}"
        )

    try:
        # `verify()` strukturani to'liq tekshiradi (kesilgan yoki
        # buzilgan fayl shu yerda tushadi). U obyektni yaroqsiz
        # qoldiradi, shuning uchun alohida ochiladi.
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
    except Exception as exc:
        raise ScreenshotRejected("Rasm buzilgan yoki to'liq emas") from exc

    mime_type, extension = allowed[image_format]
    return image_format, mime_type, extension, (width, height)


def _next_seq(session) -> int:
    """
    Sessiya ichidagi keyingi tartib raqami.

    Redis hisoblagichi ishlatiladi: u atomik, DB'ga tegmaydi va ayni
    paytda `screenshot_count` write-behind oqimini ham to'ldiradi
    (S3 yo'li ham aynan shu hisoblagichni oshiradi).

    Redis tushgan bo'lsa DB'dan sanaymiz — sekinroq, lekin bu yo'l faqat
    avariya holatida ishlaydi. Raqam takrorlanib qolsa ham xavf yo'q:
    fayl nomini band qilish `O_EXCL` bilan atomik, to'qnashuvda
    `screenshot_store` `seq` ni oshirib qayta uradi.
    """
    try:
        return session_state.increment(session.pk, "shots")
    except Exception as exc:
        logger.warning("Redis'dan seq olinmadi, DB'ga o'tilmoqda: %s", exc)
        return ProctoringScreenshot.objects.filter(session_id=session.pk).count() + 1


def _build_relative_path(
    *, exam_id: int, session_id: int, captured_at: datetime, seq: int, extension: str
) -> str:
    """
    `{exam_id}/{session_id}/{captured_at}_{seq}.{ext}`

    Vaqt UTC'da va ajratuvchisiz yoziladi: `:` Windows'da fayl nomida
    umuman ruxsat etilmaydi, mahalliy vaqt esa server mintaqasi
    o'zgarganda bir xil sessiyada ikki xil nom beradi.

    Sessiya bo'yicha guruhlash — bitta imtihonning barcha dalili bitta
    katalogda: arxivlash, ko'chirish va retention'dan keyin o'chirish
    bitta amalga aylanadi.
    """
    stamp = captured_at.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{exam_id}/{session_id}/{stamp}_{seq}.{extension}"
