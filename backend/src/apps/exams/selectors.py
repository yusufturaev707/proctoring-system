"""
Imtihon jadvali bo'yicha o'qish query'lari.

`ExamSchedule` ikki xil joyda kerak bo'ladi — client handshake'ida (bugungi
imtihonlar ro'yxati) va JSHSHIR qidiruvida (kirish oynasi ochiqmi). Query
mantiqi bitta joyda turishi shart: aks holda handshake client'ga imtihonni
ko'rsatib, `candidate/lookup/` uni rad etadigan holat paydo bo'ladi.
"""

from __future__ import annotations

from django.db.models import F, Q
from django.utils import timezone

from apps.exams.models import ExamSchedule


def active_schedules(*, dates: list, zone_id: int | None = None, exam_id: int | None = None):
    """
    Berilgan sanalardagi faol jadvallar.

    Zonaga biriktirilgan jadvallar ham, global (`zone=NULL`) jadvallar ham
    qaytariladi; zona jadvali ustun bo'lishi uchun oldinga suriladi.

    `nulls_last` ATAYLAB aniq berilgan: PostgreSQL'da `DESC` standart holda
    NULL'ni ro'yxat BOSHIGA qo'yadi, ya'ni oddiy `order_by("-zone_id")`
    global jadvalni zona jadvalidan ustun qilib qo'yardi.
    """
    queryset = ExamSchedule.objects.filter(
        exam_date__in=dates, is_active=True, deleted_at__isnull=True
    ).select_related("exam")

    if zone_id is not None:
        queryset = queryset.filter(Q(zone_id=zone_id) | Q(zone__isnull=True))
    else:
        queryset = queryset.filter(zone__isnull=True)

    if exam_id is not None:
        queryset = queryset.filter(exam_id=exam_id)

    return queryset.order_by(F("zone_id").desc(nulls_last=True), "starts_at")


def schedules_for_date(*, exam_date, zone_id: int | None = None, exam_id: int | None = None):
    """Bitta sana uchun (client handshake ro'yxati)."""
    return active_schedules(dates=[exam_date], zone_id=zone_id, exam_id=exam_id)


def exam_has_schedules(exam_id: int) -> bool:
    """
    Imtihon uchun umuman jadval tuzilganmi.

    Jadvalsiz imtihon "tekshiruv o'chirilgan" deb qaraladi — `is_ip_allowed`
    dagi bilan bir xil qoida: dastlabki o'rnatish bosqichida noto'liq
    konfiguratsiya tizimni butunlay bloklab qo'ymasligi kerak.
    """
    return ExamSchedule.objects.filter(
        exam_id=exam_id, is_active=True, deleted_at__isnull=True
    ).exists()


def resolve_open_schedule(*, exam_id: int, zone_id: int | None = None, at=None):
    """
    Hozir kirish oynasi ochiq bo'lgan jadvalni topadi.

    Qaytaradi `(schedule, error)`:
        (schedule, None)      — oyna ochiq
        (None, "no_schedule") — imtihon uchun jadval umuman tuzilmagan
        (None, "closed")      — jadval bor, lekin hozir oyna yopiq

    Kechagi sana ham so'raladi: 23:00 da boshlanib yarim kechadan o'tadigan
    seans yoki uzun `checkin_lead_minutes` bilan oldingi kunga tushib qolgan
    kirish oynasi shu tufayli topiladi. Filtr `exam_date` bo'yicha, lekin
    yakuniy qaror `is_open()` — ya'ni haqiqiy `starts_at`/`ends_at` bo'yicha.
    """
    at = at or timezone.now()
    today = timezone.localdate(at)
    dates = [today, today - timezone.timedelta(days=1)]

    candidates = list(active_schedules(dates=dates, zone_id=zone_id, exam_id=exam_id))
    for schedule in candidates:
        if schedule.is_open(at):
            return schedule, None

    if not candidates and not exam_has_schedules(exam_id):
        return None, "no_schedule"
    return None, "closed"


def next_schedule(*, exam_id: int, zone_id: int | None = None, at=None):
    """
    Keyingi rejalashtirilgan oyna.

    Xato xabarida "qachon ochiladi" deb ko'rsatish uchun — talabgor imtihon
    markazida turib "ruxsat yo'q" degan quruq xabarni olmasligi kerak.
    """
    at = at or timezone.now()
    return (
        ExamSchedule.objects.filter(
            exam_id=exam_id, is_active=True, deleted_at__isnull=True, ends_at__gt=at
        )
        .filter(Q(zone_id=zone_id) | Q(zone__isnull=True))
        .order_by("starts_at")
        .first()
    )
