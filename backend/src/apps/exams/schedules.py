"""
Bitta imtihon seanslarining KIRISH OYNALARI kesishmasligi.

Nima uchun: `candidate/lookup/` client yuborgan seansni emas, imtihonning
HOZIR OCHIQ seansini o'zi tanlaydi (`selectors.resolve_open_schedule`,
`starts_at` bo'yicha birinchisi). Bitta imtihonning ikki seansi bir vaqtda
ochiq bo'lsa, 2-smena talabgori 1-smena seansiga tushadi: bron rejimida
`seat_not_booked` (bron 2-smenada), erkin rejimda sessiya va joy boshqa
smenaga yoziladi. Tanlovni client'ga berish o'rniga (client yangilanishi,
login'dagi eskirgan ro'yxat) xato sozlamaning o'zi saqlanmaydi.

Kirish oynasi — `opens_at` (`starts_at − checkin_lead_minutes`) dan
`ends_at` gacha. Chegarada tegish (12:00 tugaydi, 12:00 ochiladi) kesishma
EMAS.

Ko'lam — AYNAN bir xil `zone` (ikkalasi umumiy yoki bitta bino). Bino
seansi umumiy seans bilan kesishishi RUXSAT: u shu bino uchun umumiy
seansni ataylab almashtiradi va selektor uni oldinga qo'yadi
(`active_schedules`, `nulls_last`).

Nofaol va o'chirilgan seans hisobga olinmaydi. Qoida BITTA joyda: panel
(`ExamScheduleSerializer.validate`), Django admin (`ExamSchedule.clean`),
tiklash (`ExamScheduleViewSet.restore`), tekshiruv buyrug'i
(`audit_schedule_overlaps`).
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.exams.models import ExamSchedule


def find_overlap(
    *, exam_id, zone_id, starts_at, ends_at, lead_minutes, exclude_pk=None
) -> ExamSchedule | None:
    """Kirish oynasi berilgan oyna bilan kesishadigan birinchi seans yoki `None`."""
    opens_at = starts_at - timedelta(minutes=lead_minutes or 0)
    rows = (
        ExamSchedule.objects.filter(
            exam_id=exam_id, is_active=True, deleted_at__isnull=True, ends_at__gt=opens_at
        )
        .filter(**({"zone__isnull": True} if zone_id is None else {"zone_id": zone_id}))
        .order_by("starts_at")
    )
    if exclude_pk is not None:
        rows = rows.exclude(pk=exclude_pk)
    # Ikkinchi yarmi (`other.opens_at < ends_at`) Pythonda: `opens_at`
    # property, imtihonning kelgusi seanslari esa bir necha qator.
    for other in rows:
        if other.opens_at < ends_at:
            return other
    return None


def overlap_of(schedule: ExamSchedule) -> ExamSchedule | None:
    """Saqlangan (yoki saqlanayotgan) seans uchun. Nofaolni tekshirmaydi."""
    if not schedule.is_active or not schedule.starts_at or not schedule.ends_at:
        return None
    return find_overlap(
        exam_id=schedule.exam_id,
        zone_id=schedule.zone_id,
        starts_at=schedule.starts_at,
        ends_at=schedule.ends_at,
        lead_minutes=schedule.checkin_lead_minutes,
        exclude_pk=schedule.pk,
    )


def window_label(opens_at, ends_at) -> str:
    start, end = timezone.localtime(opens_at), timezone.localtime(ends_at)
    if start.date() == end.date():
        return "{:%d.%m.%Y %H:%M}–{:%H:%M}".format(start, end)
    return "{:%d.%m.%Y %H:%M} – {:%d.%m.%Y %H:%M}".format(start, end)


def overlap_message(other: ExamSchedule, *, starts_at, ends_at, lead_minutes) -> str:
    lead = timedelta(minutes=lead_minutes or 0)
    opens_at = starts_at - lead
    # Qaysi tomonga surish kerakligi — seans o'sha seansdan KEYIN yoki OLDIN.
    if starts_at >= other.starts_at:
        fix = "boshlanishni {:%d.%m.%Y %H:%M} dan keyinga suring".format(
            timezone.localtime(other.ends_at + lead)
        )
    else:
        fix = "tugashni {:%d.%m.%Y %H:%M} gacha qisqartiring".format(
            timezone.localtime(other.opens_at)
        )
    return (
        "Bu imtihonning boshqa seansi bilan kirish oynasi kesishadi: u seansda "
        "kirish {}, bu seansda — {}. Bitta imtihon seanslarining kirish "
        "oynalari ustma-ust tushmasligi kerak (aks holda talabgor boshqa "
        "smenaga tushadi): {} yoki «kirish necha daqiqa oldin ochiladi» ni "
        "kamaytiring.".format(
            window_label(other.opens_at, other.ends_at), window_label(opens_at, ends_at), fix
        )
    )
