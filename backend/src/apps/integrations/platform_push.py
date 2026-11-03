"""
Test platformasiga NATIJA YUBORISH: kirishdagi FaceID va skrinshotlar.

Manzillar imtihonda (`Exam.face_result_url`, `Exam.screenshot_url`),
har biri ALOHIDA va ixtiyoriy: BO'SH — o'sha tur YUBORILMAYDI (vazifa
navbatga ham qo'yilmaydi). Sarlavha — `Exam.site_header_encrypted`
(JSHSHIR tekshiruvi bilan bitta platforma, bitta kredensial).

CLIENT PLATFORMAGA O'ZI YUBORMAYDI (`exam_site.py` dagi sabab):
kredensial serverda, ma'lumot allaqachon bizda — FaceID kadri
`face/verify/` / `face/attempt/` bilan, skrinshot `screenshots/upload/`
yoki S3 `commit/` bilan keladi. Server uni saqlagandan KEYIN fonda uzatadi.

NIMA UCHUN CELERY VA NIMA UCHUN FAQAT ID. Platforma sekin yoki o'chiq
bo'lsa ham FaceID sahifasi va skrinshot yuklash kutmasligi kerak — so'rov
tranzaksiya tasdiqlangach (`on_commit`) navbatga qo'yiladi va javob darhol
qaytadi. Navbatga RASM EMAS, ID tushadi: 500 mashina × savol kadri (~300 KB)
Redis brokerini (`noeviction`) to'ldirib, sessiya tokenlarini ham
xavf ostiga qo'yardi. Vazifa baytlarni saqlangan joyidan o'qiydi
(`screenshot_storage.read` / `storage.read_object`); fayl tozalangan yoki
savol kadri almashgan bo'lsa — yuborilmaydi (eskisini yuborish ma'nosiz,
yangisining o'z vazifasi bor).

Qayta urinish faqat vaqtinchalik xatoda (`PUSH_RETRY`), platforma rad
etsa (4xx) — ERROR log, tamom. Takroriy yetkazish istisno emas (vazifa
`acks_late`, retry): platforma yozuvni `id` bo'yicha taniydi.

Platformaga boradigan tana (JSON, `image_base64` — platformaning o'z
javobidagi kabi `data:` URI):

    FaceID:     {"type": "face_result", "id": 123, "imie": "...",
                 "passed": true, "score": 63, "threshold": 42,
                 "occurred_at": "...", "exam_code": "...",
                 "session_id": "<uuid>" | null, "image_base64": "data:..."}
    Skrinshot:  {"type": "screenshot", "id": "fs:45", "imie": "...",
                 "session_id": "<uuid>", "exam_code": "...",
                 "q_id": "1", "q_n": 3, "captured_at": "...",
                 "image_base64": "data:..."}
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime

from django.conf import settings
from django.db import transaction

from apps.integrations import exam_site

logger = logging.getLogger(__name__)

#: Skrinshot manbalari: fayl tizimi qatori (`ProctoringScreenshot`) yoki
#: S3 obyekti (`ScreenshotMeta` hali yozilmagan — u oqim orqali keladi).
SOURCE_FS = "fs"
SOURCE_S3 = "s3"


# --------------------------------------------------------------------------
# Navbatga qo'yish (so'rov ichida, arzon)
# --------------------------------------------------------------------------
def _exam_url(exam_id, field: str) -> str:
    from apps.exams.models import Exam

    if not exam_id:
        return ""
    return (Exam.objects.filter(pk=exam_id).values_list(field, flat=True).first() or "").strip()


def _enqueue(task, *args) -> None:
    def send():
        try:
            task.delay(*args)
        except Exception as exc:
            # Broker o'chiq — FaceID/skrinshot baribir qabul qilinadi,
            # yuborish yo'qoladi va bu log'da ko'rinadi.
            logger.warning("Platformaga yuborish navbatga qo'yilmadi (%s): %s", task.name, exc)

    transaction.on_commit(send)


def schedule_face_result(log_row) -> None:
    """Kirishdagi FaceID yozuvi (o'tdi / o'tmadi) — manzil bo'lsa navbatga."""
    from apps.integrations.tasks import push_face_result

    if _exam_url(log_row.exam_id, "face_result_url"):
        _enqueue(push_face_result, log_row.pk)


def schedule_fs_screenshot(screenshot, *, exam_id) -> None:
    """Fayl tizimidagi skrinshot qatori; `content_hash` — almashganini bilish uchun."""
    from apps.integrations.tasks import push_screenshot

    if _exam_url(exam_id, "screenshot_url"):
        _enqueue(push_screenshot, SOURCE_FS, {
            "id": screenshot.pk, "content_hash": screenshot.content_hash,
        })


def schedule_s3_screenshot(session, *, object_key: str, captured_at: datetime,
                           question_id: str = "", question_number=None) -> None:
    """S3 skrinshoti (`commit/`): qator hali yo'q, metadata argumentda."""
    from apps.integrations.tasks import push_screenshot

    if _exam_url(session.exam_id, "screenshot_url"):
        _enqueue(push_screenshot, SOURCE_S3, {
            "session_id": session.pk,
            "object_key": object_key,
            "captured_at": captured_at.isoformat(),
            "question_id": question_id or "",
            "question_number": question_number,
        })


# --------------------------------------------------------------------------
# Yuborish (Celery ichida)
# --------------------------------------------------------------------------
def send_face_result(log_id: int) -> str:
    """Qaytadi: `exam_site.PUSH_*` yoki `"skipped"` (manzil/yozuv yo'q)."""
    from apps.proctoring.models import FaceVerificationLog

    log_row = (
        FaceVerificationLog.objects.select_related("exam", "session")
        .filter(pk=log_id).first()
    )
    if log_row is None or not log_row.exam_id:
        return "skipped"
    exam = log_row.exam
    # Manzil vazifa paytida QAYTA o'qiladi: administrator uni orada
    # tozalagan bo'lsa yuborilmaydi.
    url = (exam.face_result_url or "").strip()
    if not url:
        return "skipped"

    image = b""
    if log_row.image_path:
        image = _read_fs(log_row.image_path, settings.PROCTORING["EVIDENCE"]["MAX_FRAME_BYTES"]) or b""
    # Rasm o'qilmasa ham (tozalangan, saqlanmagan) natija yuboriladi:
    # JSHSHIR va ball baribir platforma uchun yozuv.
    payload = {
        "type": "face_result",
        "id": log_row.pk,
        "imie": log_row.pinfl,
        "passed": bool(log_row.passed),
        "score": int(log_row.score),
        "threshold": int(log_row.threshold),
        "occurred_at": log_row.occurred_at.isoformat(),
        "exam_code": exam.external_code,
        "session_id": str(log_row.session.public_id) if log_row.session_id else None,
        "image_base64": _data_uri(image),
    }
    return _post(exam, url, payload)


def send_screenshot(source: str, ref: dict) -> str:
    if source == SOURCE_FS:
        return _send_fs_screenshot(ref)
    if source == SOURCE_S3:
        return _send_s3_screenshot(ref)
    logger.error("Noma'lum skrinshot manbai: %r", source)
    return "skipped"


def _send_fs_screenshot(ref: dict) -> str:
    from apps.proctoring.models import ProctoringScreenshot

    row = (
        ProctoringScreenshot.objects.select_related("session__exam")
        .filter(pk=ref.get("id")).first()
    )
    # Savol kadri o'rnida yangilanadi: hash boshqa — yangi kadr bor va
    # uning o'z vazifasi navbatda.
    if row is None or row.content_hash != ref.get("content_hash"):
        return "skipped"
    exam = row.session.exam
    url = (exam.screenshot_url or "").strip()
    if not url:
        return "skipped"
    image = _read_fs(row.file_path, settings.SCREENSHOT_STORAGE["MAX_BYTES"])
    if not image:
        return "skipped"
    return _post(exam, url, _screenshot_payload(
        ident=f"{SOURCE_FS}:{row.pk}", session=row.session, captured_at=row.captured_at,
        question_id=row.question_id, question_number=row.question_number, image=image,
    ))


def _send_s3_screenshot(ref: dict) -> str:
    from apps.common.storage import read_object
    from apps.proctoring.models import ExamSession

    session = ExamSession.objects.select_related("exam").filter(pk=ref.get("session_id")).first()
    if session is None:
        return "skipped"
    url = (session.exam.screenshot_url or "").strip()
    if not url:
        return "skipped"
    object_key = ref.get("object_key") or ""
    try:
        image = read_object(object_key, max_bytes=settings.SCREENSHOT_STORAGE["MAX_BYTES"])
    except ValueError as exc:
        logger.error("Skrinshot yuborilmadi: %s", exc)
        return "skipped"
    except Exception as exc:
        logger.warning("Skrinshot S3'dan o'qilmadi (%s): %s", object_key, exc)
        return exam_site.PUSH_RETRY
    if not image:
        # Obyekt yo'q: almashtirilgan savol kadri yoki tozalangan.
        return "skipped"
    try:
        captured_at = datetime.fromisoformat(ref.get("captured_at") or "")
    except ValueError:
        captured_at = None
    return _post(session.exam, url, _screenshot_payload(
        ident=f"{SOURCE_S3}:{object_key}", session=session, captured_at=captured_at,
        question_id=ref.get("question_id") or "",
        question_number=ref.get("question_number"), image=image,
    ))


def _screenshot_payload(*, ident, session, captured_at, question_id, question_number, image) -> dict:
    return {
        "type": "screenshot",
        "id": ident,
        "imie": session.pinfl or "",
        "session_id": str(session.public_id),
        "exam_code": session.exam.external_code,
        # Nomlar platformaning o'z `capture_screen` buyrug'idagi bilan bir
        # xil — u qaysi savolga javob kelganini o'z kaliti bilan taniydi.
        "q_id": question_id or "",
        "q_n": question_number,
        "captured_at": captured_at.isoformat() if captured_at else None,
        "image_base64": _data_uri(image),
    }


def _post(exam, url: str, payload: dict) -> str:
    from apps.exams import services as exam_services

    return exam_site.post_json(
        url=url, site_header=exam_services.get_site_header(exam), payload=payload,
    )


def _read_fs(relative_path: str, max_bytes: int) -> bytes | None:
    from apps.common.screenshot_storage import get_screenshot_storage

    try:
        return get_screenshot_storage().read(relative_path, max_bytes=int(max_bytes))
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.warning("Platformaga yuboriladigan fayl o'qilmadi (%s): %s", relative_path, exc)
        return None


_MAGIC = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"RIFF", "image/webp"),
)


def _data_uri(data: bytes) -> str:
    """`data:image/jpeg;base64,...`; bo'sh baytlar — bo'sh satr."""
    if not data:
        return ""
    mime = next((kind for magic, kind in _MAGIC if data.startswith(magic)), "image/jpeg")
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
