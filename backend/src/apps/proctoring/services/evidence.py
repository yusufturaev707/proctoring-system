"""
Dalil: shubhali hodisaning kadri va qisqa video klipi.

SKRINSHOTDAN FARQI. `ProctoringScreenshot` MUNTAZAM olinadi (har
10 s) va "imtihon qanday o'tdi" degan umumiy manzarani beradi.
Dalil esa HODISAGA bog'langan va "aynan nima ko'rindi" degan
savolga javob beradi - u proktor ekranida hodisa yonida turadi va
apellyatsiyada asosiy hujjat bo'ladi.

STORAGE QAYTA ISHLATILADI. `common/screenshot_storage.py` allaqachon
`save/delete/exists/serve` interfeysini beradi va u fayl turiga
bog'liq emas. Ikkinchi storage yozish `X-Accel-Redirect`
konfiguratsiyasini, yo'l tekshiruvini va bo'sh katalog tozalashni
ikki marta yozish degani bo'lardi. Dalillar o'sha ildizning
`evidence/` shoxida yotadi.

VIDEO TEKSHIRUVI RASMDAN BOSHQACHA. Rasm Pillow bilan to'liq
ochiladi (dekompressiya bombasi ham shu yerda ushlanadi), videoni
esa ochib ko'rib bo'lmaydi - buning uchun ffmpeg kerak va u
serverda yo'q. Shuning uchun video uchun uch qavat:

  1. SEHRLI BAYTLAR - fayl haqiqatan MP4 yoki WebM ekani;
  2. HAJM chegarasi;
  3. nginx `internal` location - fayl faqat Django ruxsat
     bergandan keyin beriladi.

Bu rasmnikidan zaifroq va buni bilish kerak: MP4 sarlavhasi
bilan boshlanadigan ixtiyoriy fayl o'tadi. Lekin u `video/mp4`
sifatida beriladi va brauzer uni skript sifatida bajarmaydi -
ya'ni saqlangan XSS yo'li yopiq qoladi.

YOZISH TARTIBI: avval FAYL, keyin QATOR. Qator yozilmasa fayl
darhol o'chiriladi. Teskarisida ochilmaydigan "dalil" qolardi -
proktor tugmani bosib 404 olardi.
"""

from __future__ import annotations

import hashlib
import io
import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.http import HttpResponseBase
from django.utils import timezone

from apps.common.exceptions import DomainError
from apps.common.screenshot_storage import (
    ScreenshotAlreadyExists,
    get_screenshot_storage,
)
from apps.proctoring.models import EvidenceArtifact

logger = logging.getLogger(__name__)

#: Barcha dalillar shu shoxda. Skrinshotlar bilan bir ildizda,
#: lekin alohida katalogda - retention vazifalari bir-biriga
#: tegmasligi uchun.
EVIDENCE_PREFIX = "evidence"

#: Video formatlari va ularning sehrli baytlari.
#:
#: MP4 (ISO BMFF): 4-8 baytlar `ftyp`.
#: WebM (Matroska): fayl `1A 45 DF A3` bilan boshlanadi.
#:
#: Ikkalasi ham `cv2.VideoWriter` chiqara oladigan formatlar -
#: client tomonda qo'shimcha kutubxona kerak emas.
_VIDEO_SIGNATURES = (
    ("mp4", "video/mp4", lambda data: data[4:8] == b"ftyp"),
    ("webm", "video/webm", lambda data: data[:4] == b"\x1a\x45\xdf\xa3"),
)


class EvidenceRejected(DomainError):
    default_code = "evidence_rejected"
    default_detail = "Dalil fayli qabul qilinmadi"


class EvidenceTooLarge(EvidenceRejected):
    default_code = "evidence_too_large"
    default_detail = "Dalil fayli juda katta"


# --------------------------------------------------------------------------
def store(
    *,
    session,
    upload,
    kind: str,
    captured_at: datetime,
    event_type: str = "",
    camera_role: str = "",
    confidence: int = 0,
    duration_ms: int = 0,
    boxes: list | None = None,
    policy: dict | None = None,
) -> EvidenceArtifact:
    """
    Dalilni saqlaydi: avval fayl, keyin qator.

    `kind` — `frame` yoki `clip`. Ular boshqacha tekshiriladi va
    boshqa muddat bilan saqlanadi.
    """
    kind = (kind or EvidenceArtifact.Kind.FRAME).lower()
    if kind not in (EvidenceArtifact.Kind.FRAME, EvidenceArtifact.Kind.CLIP):
        raise EvidenceRejected("Noma'lum dalil turi: {}".format(kind))

    data = _read_upload(upload, kind)
    mime_type, extension, width, height = _inspect(data, kind)

    digest = hashlib.sha256(data).hexdigest()
    captured_at = captured_at or timezone.now()

    storage = get_screenshot_storage()
    relative_path = ""
    # Bir soniyada bir necha dalil kelishi mumkin (fusion hodisasi
    # kadr va klipni birga yuboradi), shuning uchun nom to'qnashuvi
    # normal hol va u qayta urinish bilan hal qilinadi.
    for attempt in range(5):
        candidate = _build_path(
            session=session,
            kind=kind,
            captured_at=captured_at,
            extension=extension,
            digest=digest,
            attempt=attempt,
        )
        try:
            storage.save(candidate, data)
        except ScreenshotAlreadyExists:
            continue
        relative_path = candidate
        break

    if not relative_path:
        raise EvidenceRejected("Dalil uchun bo'sh nom topilmadi")

    try:
        with transaction.atomic():
            artifact = EvidenceArtifact.objects.create(
                session=session,
                kind=kind,
                storage=EvidenceArtifact.Storage.FS,
                file_path=relative_path,
                content_hash=digest,
                size_bytes=len(data),
                mime_type=mime_type,
                width=width,
                height=height,
                duration_ms=int(duration_ms or 0),
                event_type=(event_type or "")[:48],
                camera_role=(camera_role or "")[:10],
                confidence=max(0, min(100, int(confidence or 0))),
                boxes=list(boxes or []),
                captured_at=captured_at,
                is_committed=True,
                purge_after=_purge_after(kind, policy),
            )
    except Exception:
        # Qator yozilmadi - fayl DARHOL o'chiriladi. Aks holda
        # diskda hech kim bilmaydigan yetim fayl qolardi va uni
        # faqat qo'lda topish mumkin bo'lardi.
        storage.delete(relative_path)
        logger.exception("Dalil qatorini yozib bo'lmadi, fayl o'chirildi: %s", relative_path)
        raise

    logger.info(
        "Dalil saqlandi: sessiya=%s tur=%s hodisa=%s hajm=%s",
        session.pk, kind, event_type or "-", len(data),
    )
    return artifact


def delete(artifact: EvidenceArtifact) -> bool:
    """
    Dalilni o'chiradi: avval FAYL, keyin qator.

    Teskarisida hech kim biladigan yetim fayl qolardi
    (`screenshot_delete` bilan bir xil qoida).
    """
    removed = False
    if artifact.file_path:
        removed = get_screenshot_storage().delete(artifact.file_path)
    artifact.delete()
    return removed


def response(artifact: EvidenceArtifact) -> HttpResponseBase:
    """
    Faylni beradi (`X-Accel-Redirect` yoki to'g'ridan-to'g'ri).

    Baytlar Python'dan O'TMAYDI: ruxsatni Django tekshiradi,
    faylni nginx o'qiydi.
    """
    return get_screenshot_storage().serve(
        artifact.file_path,
        content_type=artifact.mime_type,
        filename="evidence-{}.{}".format(
            artifact.pk, artifact.file_path.rsplit(".", 1)[-1]
        ),
    )


# --------------------------------------------------------------------------
def _read_upload(upload, kind: str) -> bytes:
    """
    Yuklangan faylni chegara bilan o'qiydi.

    `upload.size` ga ISHONMAYMIZ - u `Content-Length` dan keladi
    (`screenshots._read_upload` bilan bir xil sabab).
    """
    conf = settings.PROCTORING["EVIDENCE"]
    max_bytes = int(
        conf["MAX_CLIP_BYTES"] if kind == EvidenceArtifact.Kind.CLIP
        else conf["MAX_FRAME_BYTES"]
    )

    declared = getattr(upload, "size", None)
    if declared is not None and declared > max_bytes:
        raise EvidenceTooLarge(
            "Dalil {} bayt, chegara {} bayt".format(declared, max_bytes)
        )

    buffer = io.BytesIO()
    total = 0
    for chunk in upload.chunks():
        total += len(chunk)
        if total > max_bytes:
            raise EvidenceTooLarge("Dalil {} baytdan katta".format(max_bytes))
        buffer.write(chunk)

    data = buffer.getvalue()
    if not data:
        raise EvidenceRejected("Bo'sh fayl")
    return data


def _inspect(data: bytes, kind: str) -> tuple:
    """Fayl turini BAYTLARIDAN aniqlaydi. Qaytadi: `(mime, ext, w, h)`."""
    if kind == EvidenceArtifact.Kind.CLIP:
        return _inspect_video(data)

    # Kadr uchun rasm tekshiruvi TO'LIQ qayta ishlatiladi: u
    # dekompressiya bombasini ham, kesilgan faylni ham ushlaydi va
    # ikkinchi nusxa yozish o'sha himoyani ikkiga bo'lardi.
    from apps.proctoring.services.screenshots import _detect_image

    _format, mime_type, extension, (width, height) = _detect_image(data)
    return mime_type, extension, width, height


def _inspect_video(data: bytes) -> tuple:
    """
    Video sehrli baytlar bo'yicha.

    O'LCHAM O'QILMAYDI: uni bilish uchun konteynerni ochish kerak
    va bu ffmpeg talab qiladi. `0x0` - "o'lchanmadi" degani va u
    panelda ko'rsatilmaydi.
    """
    if len(data) < 16:
        raise EvidenceRejected("Video fayl juda kichik")

    for _name, mime_type, matches in _VIDEO_SIGNATURES:
        if matches(data):
            return mime_type, mime_type.split("/")[-1], 0, 0

    raise EvidenceRejected(
        "Video formati qo'llab-quvvatlanmaydi (faqat MP4 va WebM)"
    )


def _build_path(*, session, kind, captured_at, extension, digest, attempt) -> str:
    """
    `evidence/{exam}/{session}/{kind}/{vaqt}_{hash}.{ext}`

    Hash nomga KIRITILADI: u to'qnashuvni deyarli imkonsiz qiladi
    va ayni paytda bir xil faylning ikki marta yuborilganini
    ko'rsatadi (client qayta urinishi).
    """
    stamp = captured_at.strftime("%Y%m%d-%H%M%S-%f")
    suffix = "" if attempt == 0 else "-{}".format(attempt)
    return "{}/{}/{}/{}/{}_{}{}.{}".format(
        EVIDENCE_PREFIX,
        session.exam_id,
        session.pk,
        kind,
        stamp,
        digest[:12],
        suffix,
        extension,
    )


def _purge_after(kind: str, policy: dict | None) -> datetime:
    """
    Saqlash muddati — KADR va KLIP uchun ALOHIDA.

    Klip kadrdan ~10 barobar katta: 500 mashinali bino kuniga
    ~5 GB klip yig'adi. Ularni bitta muddat bilan saqlash diskni
    klip hisobiga to'ldirar va kadrlarni ham birga olib ketardi.

    Muddat SHU YERDA hisoblanadi va qatorga yoziladi: tozalash
    vazifasi siyosatni qayta o'qimasligi kerak, chunki u sessiya
    tugagach o'zgargan bo'lishi mumkin.
    """
    evidence = (policy or {}).get("evidence") or {}
    default = settings.PROCTORING["EVIDENCE"]
    if kind == EvidenceArtifact.Kind.CLIP:
        days = int(evidence.get("clip_retention_days") or default["CLIP_RETENTION_DAYS"])
    else:
        days = int(evidence.get("frame_retention_days") or default["FRAME_RETENTION_DAYS"])
    return timezone.now() + timedelta(days=max(1, days))
