"""
Oferta: saqlash, versiyalash va client'ga berish — BITTA JOYDA.

Panel serializer'i va testlar ofertani faqat shu yerdagi `save_offer`
orqali yozadi. Sabab — versiya qoidasi: matn yoki sarlavha o'zgarsa YANGI
`OfferRevision` yaratilishi shart, aks holda tahrirlar tarixi jimgina
uzilardi.

Talabgorning roziligi SERVERGA YOZILMAYDI: client matnni har JSHSHIR
qidiruvida ko'rsatadi va «Roziman» siz davom ettirmaydi.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework import status

from apps.common.exceptions import DomainError
from apps.common.html_sanitizer import html_text, sanitize_html

#: Tozalangan HTML chegarasi. Oferta odatda 5-30 KB; chegara JSHSHIR
#: javobini (u matnni o'zida tashiydi) va client xotirasini himoya qiladi.
MAX_CONTENT_LENGTH = 200_000

#: Matnli oferta shundan qisqa bo'lmaydi — "." yoki "test" kabi tasodifiy
#: saqlangan matn amaldagi bo'lib qolmasin.
MIN_TEXT_LENGTH = 20


class OfferContentError(ValueError):
    """Matn yaroqsiz — serializer uni maydon xatosiga aylantiradi."""


def clean_content(raw: str) -> str:
    """Muharrir HTML'i -> toza HTML. Bo'sh yoki ortiqcha uzun matn rad etiladi."""
    html = sanitize_html(raw)
    if len(html_text(html)) < MIN_TEXT_LENGTH:
        raise OfferContentError(f"Oferta matni kamida {MIN_TEXT_LENGTH} belgidan iborat bo'lishi kerak")
    if len(html) > MAX_CONTENT_LENGTH:
        raise OfferContentError("Oferta matni juda uzun")
    return html


@transaction.atomic
def save_offer(*, offer=None, title: str, content: str, is_active=None, exams=None, actor=None):
    """
    Ofertani yaratadi yoki yangilaydi; matn o'zgarsa yangi versiya.

    `content` — TOZALANGAN bo'lishi shart (`clean_content`): bu yerda
    qayta tozalanmaydi.

    `is_active`, `exams` — `None` bo'lsa o'zgarmaydi. `exams` berilsa
    oferta AYNAN shu imtihonlarniki bo'ladi (`assign_exams`).
    """
    from apps.controls.models import Offer, OfferRevision

    title = (title or "").strip()
    created = offer is None
    if created:
        offer = Offer(title=title, content=content)
    changed = created or offer.title != title or offer.content != content

    if is_active is not None:
        offer.is_active = bool(is_active)
    offer.title = title
    offer.content = content
    offer.updated_by = actor
    if changed:
        offer.version += 1
    offer.save()

    if changed:
        OfferRevision.objects.create(
            offer=offer,
            version=offer.version,
            title=title,
            content=content,
            created_by=actor,
        )
    if exams is not None:
        offer.exam_changes = assign_exams(offer, exams)
    return offer


def assign_exams(offer, exams) -> dict:
    """
    Ofertani AYNAN shu imtihonlarga biriktiradi: qolganlari undan ajraladi.

    Imtihonning ofertasi bitta (`Exam.offer`) — boshqa ofertadagi imtihon
    tanlansa u shu ofertaga KO'CHADI. Qaytadi: `{"added": [...],
    "removed": [...], "moved": {exam_id: eski_offer_id}}` — audit uchun.
    """
    from apps.exams.models import Exam

    wanted = {exam.pk for exam in exams}
    current = set(Exam.objects.alive().filter(offer=offer).values_list("pk", flat=True))
    moved = dict(
        Exam.objects.filter(pk__in=wanted - current, offer__isnull=False)
        .values_list("pk", "offer_id")
    )
    added, removed = sorted(wanted - current), sorted(current - wanted)
    if added:
        Exam.objects.filter(pk__in=added).update(offer=offer, updated_at=timezone.now())
    if removed:
        Exam.objects.filter(pk__in=removed).update(offer=None, updated_at=timezone.now())
    return {"added": added, "removed": removed, "moved": moved}


class OfferInUse(DomainError):
    """Testga biriktirilgan ofertani o'chirib bo'lmaydi."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "Oferta testlarga biriktirilgan — avval testlardan ajrating"
    default_code = "offer_in_use"


@transaction.atomic
def delete_offer(offer) -> None:
    """
    Yumshoq o'chirish — faqat hech bir tirik imtihon unga bog'lanmagan bo'lsa.

    Jimgina ajratish emas, RAD: o'chirish imtihondan oferta qadamini
    olib tashlardi va administrator buni sezmay qolardi.
    """
    names = list(offer.exams.alive().order_by("name").values_list("name", flat=True)[:4])
    if names:
        shown = ", ".join(f"«{name}»" for name in names[:3]) + (" va boshqalar" if len(names) > 3 else "")
        raise OfferInUse(
            f"Oferta testlarga biriktirilgan: {shown}. Avval ularni ofertadan ajrating",
            extra={"exams": names[:3]},
        )
    offer.delete()


def current_revision(exam):
    """
    Imtihon ofertasining oxirgi versiyasi (`None` — oferta ko'rsatilmaydi).

    So'ralmaydi: imtihonga oferta biriktirilmagan, oferta nofaol yoki
    o'chirilgan. Versiyalar faqat o'sadi, ya'ni eng kattasi — joriy matn.
    Keshsiz: JSHSHIR qidiruvi talabgorga bir marta, keshni bekor qilishni
    unutish esa eski matnni ko'rsatardi.
    """
    from apps.controls.models import OfferRevision

    if exam is None or not exam.offer_id:
        return None
    return (
        OfferRevision.objects.filter(
            offer_id=exam.offer_id, offer__is_active=True, offer__deleted_at__isnull=True
        )
        .select_related("offer")
        .order_by("-version")
        .first()
    )


def client_payload(revision) -> dict:
    """JSHSHIR javobidagi `offer` — client dialogi shuni chizadi."""
    return {
        "offer_id": revision.offer_id,
        "version": revision.version,
        "title": revision.title,
        "content_html": revision.content,
        "published_at": revision.created_at,
    }
