"""
O'qish so'rovlari.

Har bir selector'da `select_related` / `only` majburiy: 10 000 qatorlik
sessiya ro'yxatida N+1 muammosi 30 000 ta qo'shimcha so'rovga aylanadi.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from django.db.models import Count, Q
from django.utils import timezone

from apps.proctoring.models import (
    EvidenceArtifact,
    AuditLog,
    ExamSession,
    FaceVerificationLog,
    ProctoringEvent,
    ProctoringScreenshot,
    ScreenshotMeta,
    TechnicalProblem,
)


def sessions_base():
    return ExamSession.objects.select_related(
        "exam", "computer", "zone", "zone__region", "device", "terminated_by"
    )


def sessions_for_pinfl(pinfl: str):
    """
    Bitta talabgorning barcha imtihonlari (tarix ekrani).

    `idx_session_pinfl` indeksida ishlaydi. Talabgor bir necha sanada
    topshirishi odatiy hol, shuning uchun bu ro'yxat kerak.
    """
    return sessions_base().filter(pinfl=pinfl).order_by("-exam_date", "-attempt_no")


def sessions_for_monitoring(*, region_id=None, zone_id=None, exam_id=None, exam_date=None):
    """
    Jonli monitoring ro'yxati.

    Faqat faol sessiyalar va faqat kerakli ustunlar. `-risk_score` bo'yicha
    tartiblash `idx_session_risk` qisman indeksidan foydalanadi — proktor
    eng shubhali sessiyalarni tepada ko'radi.
    """
    queryset = sessions_base().exclude(status__in=ExamSession.TERMINAL_STATUSES)

    if region_id:
        queryset = queryset.filter(zone__region_id=region_id)
    if zone_id:
        queryset = queryset.filter(zone_id=zone_id)
    if exam_id:
        queryset = queryset.filter(exam_id=exam_id)
    queryset = queryset.filter(exam_date=exam_date or timezone.localdate())

    return queryset.order_by("-risk_score", "-last_heartbeat_at")


def session_events(session_id: int, *, min_severity: int | None = None, types=None):
    queryset = ProctoringEvent.objects.filter(session_id=session_id)
    if min_severity is not None:
        queryset = queryset.filter(severity__gte=min_severity)
    if types:
        queryset = queryset.filter(type__in=types)
    return queryset.order_by("-occurred_at")


def session_face_logs(session_id: int, *, only_failed: bool = False):
    queryset = FaceVerificationLog.objects.filter(session_id=session_id)
    if only_failed:
        queryset = queryset.filter(passed=False)
    return queryset.order_by("-occurred_at")


def session_screenshots(session_id: int, kind: str | None = None):
    queryset = ScreenshotMeta.objects.filter(session_id=session_id, is_committed=True)
    if kind:
        queryset = queryset.filter(kind=kind)
    return queryset.order_by("-captured_at")


def session_stored_screenshots(session_id: int):
    """Fayl tizimida saqlangan skrinshotlar (`ProctoringScreenshot`)."""
    return ProctoringScreenshot.objects.filter(session_id=session_id).order_by(
        "-captured_at", "-seq"
    )


def stored_screenshot_for_user(screenshot_id: int, user):
    """
    Bitta skrinshot — foydalanuvchining hududi bo'yicha cheklangan holda.

    Hudud filtri AYNAN shu yerda: fayl beruvchi endpoint `get_object()`
    zanjiridan o'tmaydi, ya'ni `RegionScopedPermission` unga qo'llanmaydi.
    Filtrsiz qoldirilsa, boshqa viloyat proktori id'ni tanlab boshqa
    hududdagi talabgorning ekranini ko'ra oladi (IDOR).

    Topilmasa `None` qaytaradi — "ruxsat yo'q" va "mavjud emas" farqi
    oshkor qilinmaydi.
    """
    queryset = ProctoringScreenshot.objects.select_related("session", "session__zone")
    if user.is_region_scoped:
        queryset = queryset.filter(session__zone__region_id=user.region_id)
    return queryset.filter(pk=screenshot_id).first()


def session_evidence(session_id: int, *, kind: str | None = None,
                     event_type: str | None = None):
    """
    Sessiyaning dalillari.

    `kind` va `event_type` bo'yicha filtr — proktor odatda bitta
    hodisaning dalilini qidiradi ("telefon qachon ko'rindi?"), butun
    ro'yxatni varaqlamaydi.
    """
    queryset = EvidenceArtifact.objects.filter(session_id=session_id)
    if kind:
        queryset = queryset.filter(kind=kind)
    if event_type:
        queryset = queryset.filter(event_type=event_type)
    return queryset.order_by("-captured_at", "-id")


def face_log_for_user(log_id: int, user):
    """
    Bitta yuz tekshiruvi qatori — hudud bo'yicha cheklangan holda.

    Hudud filtri IKKI YO'LDAN: sessiya bor bo'lsa uning binosidan,
    yo'q bo'lsa (kirishda rad etilgan urinish) qatordagi `zone` dan.
    Ikkinchisisiz sessiyasiz qatorlar HECH KIMGA ko'rinmasdi yoki
    HAMMAGA ko'rinardi - ikkalasi ham noto'g'ri.

    `evidence_for_user` bilan bir xil sabab: fayl beruvchi endpoint
    `get_object()` zanjiridan o'tmaydi, ya'ni `RegionScopedPermission`
    unga qo'llanmaydi (IDOR).
    """
    queryset = FaceVerificationLog.objects.select_related(
        "session", "session__zone", "zone"
    )
    if user.is_region_scoped:
        queryset = queryset.filter(
            Q(session__zone__region_id=user.region_id)
            | Q(session__isnull=True, zone__region_id=user.region_id)
        )
    return queryset.filter(pk=log_id).first()


def evidence_for_user(evidence_id: int, user):
    """
    Bitta dalil — foydalanuvchining hududi bo'yicha cheklangan holda.

    Hudud filtri AYNAN shu yerda va sabab `stored_screenshot_for_user`
    dagi bilan bir xil: fayl beruvchi endpoint `get_object()`
    zanjiridan o'tmaydi, ya'ni `RegionScopedPermission` unga
    qo'llanmaydi. Filtrsiz boshqa viloyat proktori id'ni tanlab
    begona talabgorning videosini ko'ra olardi (IDOR).
    """
    queryset = EvidenceArtifact.objects.select_related("session", "session__zone")
    if user.is_region_scoped:
        queryset = queryset.filter(session__zone__region_id=user.region_id)
    return queryset.filter(pk=evidence_id).first()


def technical_problems(*, unresolved_only: bool = False, region_id=None):
    queryset = TechnicalProblem.objects.select_related(
        "session", "session__zone", "resolved_by"
    )
    if unresolved_only:
        queryset = queryset.filter(is_resolved=False)
    if region_id:
        queryset = queryset.filter(session__zone__region_id=region_id)
    return queryset.order_by("-started_at")


def audit_logs(*, actor_id=None, action=None, object_type=None):
    queryset = AuditLog.objects.select_related("actor")
    if actor_id:
        queryset = queryset.filter(actor_id=actor_id)
    if action:
        queryset = queryset.filter(action=action)
    if object_type:
        queryset = queryset.filter(object_type=object_type)
    return queryset.order_by("-id")


# --------------------------------------------------------------------------
# Dashboard agregatlari
# --------------------------------------------------------------------------
def dashboard_summary(*, region_id=None, exam_date=None) -> dict:
    """
    Bitta so'rovda barcha hisoblagichlar.

    `Count(filter=Q(...))` bir nechta alohida `COUNT` so'rovini bitta
    jadval skanerlashiga birlashtiradi — 8 ta round-trip o'rniga 1 ta.
    """
    exam_date = exam_date or timezone.localdate()
    queryset = ExamSession.objects.filter(exam_date=exam_date)
    if region_id:
        queryset = queryset.filter(zone__region_id=region_id)

    aggregates = queryset.aggregate(
        total=Count("id"),
        in_progress=Count("id", filter=Q(status=ExamSession.Status.IN_PROGRESS)),
        ready=Count("id", filter=Q(status=ExamSession.Status.READY)),
        face_check=Count("id", filter=Q(status=ExamSession.Status.FACE_CHECK)),
        finished=Count("id", filter=Q(status=ExamSession.Status.FINISHED)),
        terminated=Count("id", filter=Q(status=ExamSession.Status.TERMINATED)),
        technical=Count("id", filter=Q(status=ExamSession.Status.TECHNICAL_PROBLEM)),
        expired=Count("id", filter=Q(status=ExamSession.Status.EXPIRED)),
        high_risk=Count("id", filter=Q(risk_score__gte=50) & ~Q(status__in=ExamSession.TERMINAL_STATUSES)),
    )
    aggregates["date"] = exam_date
    return aggregates


def zone_breakdown(*, region_id=None, exam_date=None) -> list[dict]:
    """
    Bino bo'yicha kesim — dashboard xaritasi uchun.

    IKKI so'rov, bitta JOIN emas. Ilgari `Zone LEFT JOIN exam_session`
    + `COUNT(DISTINCT ...) FILTER (exam_date = ...)` edi: sana sharti
    FILTER ichida bo'lgani uchun JOIN butun sessiyalar TARIXINI
    o'qirdi (perf bazasida 300 000 sessiya — 280-580 ms, har proktor
    har 15 s da). Endi sessiyalar faqat shu sana bo'yicha indeks bilan
    guruhlanadi va binolar ro'yxatiga Python'da qo'shiladi; natija
    shakli (kalitlar, tartib, sessiyasiz binoda nollar) o'zgarmagan.
    """
    from apps.regions.models import Zone

    exam_date = exam_date or timezone.localdate()
    queryset = Zone.objects.filter(deleted_at__isnull=True, is_active=True)
    sessions = ExamSession.objects.filter(exam_date=exam_date)
    if region_id:
        queryset = queryset.filter(region_id=region_id)
        sessions = sessions.filter(zone__region_id=region_id)

    zones = list(
        queryset.values("id", "name", "number", "region__name").order_by("region__name", "number")
    )
    counts = {
        row["zone_id"]: row
        for row in sessions.filter(zone_id__isnull=False)
        .values("zone_id")
        .annotate(
            total=Count("id"),
            active=Count("id", filter=Q(status=ExamSession.Status.IN_PROGRESS)),
            terminated=Count("id", filter=Q(status=ExamSession.Status.TERMINATED)),
            problems=Count("id", filter=Q(status=ExamSession.Status.TECHNICAL_PROBLEM)),
        )
        .order_by()
    }
    for zone in zones:
        row = counts.get(zone["id"]) or {}
        for key in ("total", "active", "terminated", "problems"):
            zone[key] = row.get(key, 0)
    return zones


def _as_date(value):
    """So'rov parametridagi sana (`?date=`) — satr yoki `date`."""
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def event_type_breakdown(*, exam_date=None, region_id=None, limit: int = 15) -> list[dict]:
    """
    Eng ko'p uchraydigan hodisa turlari.

    `occurred_at` oralig'i PARTITSIYA KESISH uchun: faqat
    `session__exam_date` sharti bilan PostgreSQL `proctoring_event` ning
    BARCHA partitsiyalarini (tarix bilan) skanerlardi — perf bazasida
    7 mln hodisada 600 ms, dashboard esa har proktorda 15 s da so'raydi.
    Oraliq sana kunidan +-6 soat keng: kun oxirida boshlangan smena va
    oflayn buferdan kechikib kelgan hodisalar ham kiradi. Soati 6 soatdan
    ko'p adashgan mashinaning hodisasi faqat shu diagrammadan tushadi
    (sessiya sahifasida ko'rinadi).
    """
    exam_date = _as_date(exam_date) or timezone.localdate()
    queryset = ProctoringEvent.objects.filter(session__exam_date=exam_date)
    day_start = timezone.make_aware(datetime.combine(exam_date, time.min))
    queryset = queryset.filter(
        occurred_at__gte=day_start - timedelta(hours=6),
        occurred_at__lt=day_start + timedelta(days=1, hours=6),
    )
    if region_id:
        queryset = queryset.filter(session__zone__region_id=region_id)

    return list(
        queryset.values("type")
        .annotate(count=Count("id"))
        .order_by("-count")[:limit]
    )
