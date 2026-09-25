"""
FaceID kadri: kirishda va test davomida olingan JONLI rasm.

NIMA UCHUN UMUMAN SAQLANADI. Solishtirish clientda bajariladi va
serverga faqat ball keladi - ya'ni "nega bu ball chiqdi?" degan
savolga javob beradigan yagona narsa o'sha paytdagi kadr. Apellyatsiya
ham, "kim urinib ko'rgan?" tekshiruvi ham aynan shu rasmga tayanadi.

STORAGE QAYTA ISHLATILADI (`common/screenshot_storage.py`), rasmlar
o'sha ildizning `faceid/` shoxida. Uchinchi storage yozish
`X-Accel-Redirect` konfiguratsiyasini, yo'l tekshiruvini va bo'sh
katalog tozalashni yana bir marta yozish degani bo'lardi - dalil
(`evidence.py`) allaqachon shu qarordan o'tgan.

TEKSHIRUV RASM UCHUN TO'LIQ. Baytlar Pillow bilan ochiladi
(`screenshots._detect_image`): `.jpg` niqobidagi HTML `internal`
location'dan berilsa bu saqlangan XSS bo'lardi, dekompressiya
bombasi esa worker'ni o'ldirardi. Ikkinchi nusxa yozish o'sha
himoyani ikkiga bo'lardi.

YOZISH TARTIBI: avval FAYL, keyin QATOR (butun loyihadagi qoida).
Qator yozilmasa fayl `discard()` bilan darhol o'chiriladi.

RASM - DALIL, TO'SIQ EMAS. Fayl buzilgan bo'lsa tekshiruvning o'zi
bekor qilinmaydi: chaqiruvchi xatoni yutadi va qatorni rasmsiz
yozadi. Aks holda buzilgan JPEG butun imtihonni to'xtatardi.
"""

from __future__ import annotations

import hashlib
import io
import logging
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.conf import settings
from django.http import HttpResponseBase
from django.utils import timezone

from apps.common.exceptions import DomainError
from apps.common.screenshot_storage import (
    ScreenshotAlreadyExists,
    get_screenshot_storage,
)

logger = logging.getLogger(__name__)

#: Barcha FaceID kadrlari shu shoxda - skrinshot va dalil bilan bir
#: ildizda, lekin alohida katalogda: retention vazifalari bir-biriga
#: tegmasligi kerak.
FACEID_PREFIX = "faceid"

#: Sessiya hali yo'q bo'lgan urinishlar (kirishda rad etilgan) shu
#: katalogga tushadi: guruhlaydigan sessiyaning o'zi yo'q.
PENDING_DIR = "pending"


class FaceImageRejected(DomainError):
    default_code = "face_image_rejected"
    default_detail = "Yuz rasmi qabul qilinmadi"


class FaceImageTooLarge(FaceImageRejected):
    default_code = "face_image_too_large"
    default_detail = "Yuz rasmi juda katta"


# --------------------------------------------------------------------------
def store(
    *,
    data: bytes,
    exam_id: int | None,
    session=None,
    occurred_at: datetime | None = None,
    policy: dict | None = None,
    kind: str = "live",
) -> tuple[str, datetime]:
    """
    Kadrni diskka yozadi. Qaytadi: `(nisbiy_yo'l, purge_after)`.

    Qator SHU CHAQIRUVDAN KEYIN yaratiladi - tartib ataylab shunday
    (fayl avval). Chaqiruvchi qatorni yoza olmasa `discard()` ni
    chaqiradi.
    """
    if not data:
        raise FaceImageRejected("Bo'sh fayl")

    from apps.proctoring.services.screenshots import _detect_image

    _format, _mime, extension, _dimensions = _detect_image(data)
    digest = hashlib.sha256(data).hexdigest()
    occurred_at = occurred_at or timezone.now()

    storage = get_screenshot_storage()
    relative_path = ""
    # Bir soniyada ikkita urinish bo'lishi mumkin (operator "qaytadan"
    # ni tez bosdi), shuning uchun nom to'qnashuvi normal hol.
    for attempt in range(5):
        candidate = _build_path(
            exam_id=exam_id,
            session=session,
            occurred_at=occurred_at,
            extension=extension,
            digest=digest,
            attempt=attempt,
            kind=kind,
        )
        try:
            storage.save(candidate, data)
        except ScreenshotAlreadyExists:
            continue
        except OSError as exc:
            logger.error("FaceID rasmi diskka yozilmadi (%s): %s", candidate, exc)
            raise FaceImageRejected("Rasmni saqlab bo'lmadi") from exc
        relative_path = candidate
        break

    if not relative_path:
        raise FaceImageRejected("Rasm uchun bo'sh nom topilmadi")

    return relative_path, purge_after(policy)


def discard(relative_path: str) -> bool:
    """Yetim faylni o'chiradi (qator yozilmagan holat)."""
    if not relative_path:
        return False
    return get_screenshot_storage().delete(relative_path)


def response(log, *, kind: str = "live") -> HttpResponseBase:
    """
    Rasmni beradi (`X-Accel-Redirect`).

    `kind="reference"` - kirishdagi ETALON (pasport) rasmi,
    `kind="live"` - kameradan olingan kadr. Ikkalasi bitta qatorda
    yashaydi, chunki ular BIR TEKSHIRUVNING ikki tomoni: ballni
    tushuntirish uchun ikkalasi birga kerak va ularni alohida
    jadvalga ajratish har ko'rsatishda ikkinchi so'rov degani
    bo'lardi.

    Baytlar Python'dan O'TMAYDI: ruxsatni Django tekshiradi, faylni
    nginx o'qiydi (`screenshots.screenshot_response` bilan bir xil
    mas'uliyat bo'linishi).
    """
    path = log.reference_image_path if kind == "reference" else log.image_path
    extension = path.rsplit(".", 1)[-1].lower() if "." in path else "jpg"
    content_type = "image/png" if extension == "png" else "image/jpeg"
    return get_screenshot_storage().serve(
        path,
        content_type=content_type,
        filename="faceid-{}-{}.{}".format(log.pk, kind, extension),
    )


def read_upload(upload) -> bytes:
    """
    Yuklangan faylni CHEGARA bilan o'qiydi.

    `upload.size` ga ISHONMAYMIZ - u `Content-Length` dan keladi va uni
    client istalgancha yozadi (`screenshots._read_upload` bilan bir xil
    sabab).

    Chegara dalil KADRIniki bilan bir xil: bu ham bitta kadr va u ham
    o'sha kameradan keladi. Ikkinchi sozlama kiritish bir xil narsani
    ikki joyda sozlashga majbur qilardi.
    """
    max_bytes = int(settings.PROCTORING["EVIDENCE"]["MAX_FRAME_BYTES"])

    declared = getattr(upload, "size", None)
    if declared is not None and declared > max_bytes:
        raise FaceImageTooLarge(
            "Rasm {} bayt, chegara {} bayt".format(declared, max_bytes)
        )

    buffer = io.BytesIO()
    total = 0
    for chunk in upload.chunks():
        total += len(chunk)
        if total > max_bytes:
            raise FaceImageTooLarge("Rasm {} baytdan katta".format(max_bytes))
        buffer.write(chunk)

    data = buffer.getvalue()
    if not data:
        raise FaceImageRejected("Bo'sh fayl")
    return data


def purge_after(policy: dict | None = None) -> datetime:
    """
    Saqlash muddati - DALIL KADRI bilan bir xil.

    Sabab: bu ham talabgorning yuzi va uning maxfiylik og'irligi dalil
    kadridan farq qilmaydi. Alohida sozlama qo'shish administratorni
    "ikkalasini bir xil qilib qo'yish" ishiga majbur qilardi, farqli
    qo'yilgani esa hech qanday amaliy ma'no bermasdi.
    """
    evidence = (policy or {}).get("evidence") or {}
    default = settings.PROCTORING["EVIDENCE"]["FRAME_RETENTION_DAYS"]
    days = int(evidence.get("frame_retention_days") or default)
    return timezone.now() + timedelta(days=max(1, days))


# --------------------------------------------------------------------------
def _build_path(*, exam_id, session, occurred_at, extension, digest, attempt, kind="live") -> str:
    """
    `faceid/{exam}/{session|pending}/{vaqt}_{hash}[_ref].{ext}`

    Vaqt UTC'da: mahalliy vaqt server mintaqasi o'zgarganda bir xil
    sessiyada ikki xil nom berardi. Hash nomda - to'qnashuvni deyarli
    imkonsiz qiladi va bir xil kadr ikki marta yuborilganini
    ko'rsatadi (client qayta urinishi).
    """
    stamp = occurred_at.astimezone(dt_timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    suffix = "" if attempt == 0 else "-{}".format(attempt)
    # Etalon fayl nomida ALOHIDA belgi: bitta tekshiruvning ikkala
    # fayli bir katalogda yotadi va diskni qo'lda ko'rayotgan odam
    # qaysi biri hujjat rasmi ekanini nomdan bilishi kerak.
    marker = "_ref" if kind == "reference" else ""
    return "{}/{}/{}/{}_{}{}{}.{}".format(
        FACEID_PREFIX,
        int(exam_id or 0),
        session.pk if session is not None else PENDING_DIR,
        stamp,
        digest[:12],
        marker,
        suffix,
        extension,
    )
