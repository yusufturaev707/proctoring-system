"""
Imtihon sessiyasining hayot sikli.

Oqim:
    1. lookup_candidate()   JSHSHIR -> tashqi API -> Candidate (+challenge)
    2. verify_initial_face() FaceID -> ExamSession yaratiladi
    3. issue_exam_access()   bir martalik tashqi token + WebView konfiguratsiyasi
    4. ... monitoring ...
    5. finish_session() / terminate_session()
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.common.exceptions import (
    CandidateNotEligible,
    ExamNotOpen,
    ExternalPlatformError,
    FaceVerificationFailed,
    IdentityAlreadyConfirmed,
    IdentityNotConfirmed,
    SessionAlreadyActive,
    SessionNotFound,
)
from apps.common.utils.crypto import (
    encrypt,
    generate_token,
    hash_token,
    mask_pinfl,
    normalize_pinfl,
)
from apps.proctoring.models import (
    ExamSession,
    FaceVerificationLog,
    ProctoringEvent,
)
from apps.proctoring.services import state as session_state

logger = logging.getLogger(__name__)

#: Tashqi platformada test yakunlangan hisoblanadigan statuslar —
#: bunday sessiyaga WebView ochilmaydi.
_CLOSED_PLATFORM_STATUSES = frozenset(
    {"finished", "completed", "submitted", "closed", "expired", "cancelled"}
)


def _parse_dt(value):
    """Tashqi platformadan kelgan ISO vaqtni `datetime` ga aylantiradi."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if timezone.is_aware(value) else timezone.make_aware(value)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        logger.warning("Tashqi platforma vaqtini o'qib bo'lmadi: %r", value)
        return None
    return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)


# --------------------------------------------------------------------------
# 1-qadam: JSHSHIR bo'yicha talabgorni aniqlash
# --------------------------------------------------------------------------
def lookup_candidate(*, pinfl: str, exam, device=None, zone=None, ip_address: str = "") -> dict:
    """
    Tashqi platformadan talabgorni oladi va `Candidate` yozuvini yangilaydi.

    Bu yerda hali sessiya YARATILMAYDI — faqat `challenge` beriladi.
    Sabab: FaceID'dan o'tmagan talabgor uchun DB'da sessiya qatorlari
    yaratish keraksiz yozish va noto'g'ri statistika demak.

    Eng birinchi tekshiruv — kirish oynasi. Tashqi API'ga (va JSHSHIR
    keshiga) oyna yopiq bo'lsa umuman tegilmaydi.
    """
    from apps.integrations.exam_platform import get_client

    schedule = _require_open_schedule(exam, zone)

    pinfl = normalize_pinfl(pinfl)
    data = get_client().lookup_candidate(pinfl, exam.external_code or exam.key)
    if not data.get("eligible"):
        raise CandidateNotEligible()

    # Platforma sessiya tokenini bermasa, WebView'ni ochib bo'lmaydi —
    # buni FaceID'dan keyin emas, HOZIR aytgan ma'qul.
    if not data.get("session_token"):
        logger.error(
            "ntest talabgorga sessiya tokeni bermadi: pinfl=%s exam=%s",
            mask_pinfl(pinfl), exam.pk,
        )
        raise CandidateNotEligible(
            "Tashqi platforma bu talabgor uchun sessiya ochmadi"
        )

    # Faol sessiya allaqachon bormi (boshqa kompyuterda)?
    existing = (
        ExamSession.objects.filter(
            pinfl=pinfl,
            exam=exam,
            exam_date=timezone.localdate(),
        )
        .exclude(status__in=ExamSession.TERMINAL_STATUSES)
        .first()
    )
    if existing is not None and existing.computer_id and device is not None:
        if existing.device_id and existing.device_id != device.pk:
            raise SessionAlreadyActive()

    # Talabgor ma'lumoti challenge bilan birga tashiladi — sessiya
    # FaceID'dan keyin yaratiladi va shu ma'lumot unga MUZLATIB yoziladi.
    challenge = generate_token(24)
    session_state.store_pending(
        challenge,
        {
            "pinfl": pinfl,
            "last_name": data.get("last_name", ""),
            "first_name": data.get("first_name", ""),
            "middle_name": data.get("middle_name", ""),
            "external_candidate_id": data.get("external_id", ""),
            # Tashqi platformaning O'Z sessiyasi — WebView shu bilan ochiladi.
            "external_session_token": data.get("session_token", ""),
            "external_status": data.get("status", ""),
            "external_access_from": data.get("access_from"),
            "external_access_until": data.get("access_until"),
            "exam_id": exam.pk,
            # Qaysi seansga tegishli ekani AYNAN SHU YERDA aniqlangan,
            # aks holda `ExamSession.schedule` NULL qolardi.
            "schedule_id": getattr(schedule, "pk", None),
            "device_id": getattr(device, "pk", None),
            "ip": ip_address,
        },
    )

    full_name = " ".join(
        part
        for part in (
            data.get("last_name", ""), data.get("first_name", ""), data.get("middle_name", "")
        )
        if part
    ).strip()

    # Etalon rasm — client kirishdagi FaceID'da AYNAN shuni kameradagi
    # yuz bilan solishtiradi. Rasm DB'ga yozilmaydi va sessiyaga
    # muzlatilmaydi: u faqat shu tekshiruv uchun, bir marta uzatiladi.
    reference_photo = data.get("photo_base64", "") or ""

    return {
        "challenge": challenge,
        "candidate": {
            "full_name": full_name,
            "last_name": data.get("last_name", ""),
            "first_name": data.get("first_name", ""),
            "middle_name": data.get("middle_name", ""),
            "masked_pinfl": mask_pinfl(pinfl),
            "external_candidate_id": data.get("external_id", ""),
            "photo_key": "",
            # `photo_url` — rasm tashqi manzilda bo'lsa; `photo_base64` —
            # bevosita kelgan bo'lsa. Client qaysi biri bo'lsa shuni oladi.
            "photo_url": data.get("photo_url", ""),
            "photo_base64": reference_photo,
        },
        # Etalon rasm kelgan bo'lsa — solishtirish mumkin. Kelmasa client
        # "enrollment" rejimida ishlaydi: yuz qayd etiladi, lekin hujjat
        # bo'yicha tasdiq butunlay operator zimmasida qoladi.
        "has_reference_face": bool(reference_photo or data.get("photo_url")),
        "challenge_expires_in": settings.PROCTORING["PENDING_SESSION_TTL"],
        # Platforma bergan kirish oynasi va test holati — client buni
        # ekranda ko'rsatishi va sanoqni shunga qarab yuritishi mumkin.
        "platform": {
            "status": data.get("status", ""),
            "access_from": data.get("access_from"),
            "access_until": data.get("access_until"),
        },
        # Client imtihon tugash vaqtini bilishi kerak (sanoq va avtomatik yopish).
        "schedule": (
            {
                "id": schedule.pk,
                "starts_at": schedule.starts_at,
                "ends_at": schedule.ends_at,
            }
            if schedule is not None
            else None
        ),
    }


def _require_open_schedule(exam, zone):
    """
    Kirish oynasi tekshiruvi (`ExamSchedule`).

    `ExamSchedule` aynan shu uchun kiritilgan: oynadan tashqarida JSHSHIR
    qidiruvi ochiq qolsa, u fuqarolarning F.I.Sh. sini 24/7 qidirish
    servisiga aylanadi.

    Jadval umuman tuzilmagan bo'lsa tekshiruv o'chirilgan hisoblanadi —
    `is_ip_allowed` dagi bilan bir xil qoida. `REQUIRE_EXAM_SCHEDULE=true`
    bu yumshoqlikni o'chiradi (production uchun tavsiya).
    """
    from apps.exams import selectors as exam_selectors

    zone_id = getattr(zone, "pk", None)
    schedule, error = exam_selectors.resolve_open_schedule(exam_id=exam.pk, zone_id=zone_id)

    if schedule is not None:
        return schedule

    if error == "no_schedule" and not settings.PROCTORING["REQUIRE_EXAM_SCHEDULE"]:
        logger.warning(
            "Imtihon %s uchun jadval tuzilmagan — kirish oynasi tekshirilmadi", exam.pk
        )
        return None

    upcoming = exam_selectors.next_schedule(exam_id=exam.pk, zone_id=zone_id)
    if upcoming is not None:
        raise ExamNotOpen(
            f"Kirish oynasi {timezone.localtime(upcoming.opens_at):%d.%m.%Y %H:%M} da ochiladi"
        )
    raise ExamNotOpen("Bu imtihon uchun rejalashtirilgan seans topilmadi")


# --------------------------------------------------------------------------
# 2-qadam: kirishdagi yuz tekshiruvi -> sessiya yaratish
# --------------------------------------------------------------------------
@transaction.atomic
def verify_initial_face(
    *,
    challenge: str,
    embedding: list[float] | None,
    score: int | None,
    image_key: str = "",
    faces_detected: int = 1,
    device=None,
    computer=None,
    ip_address: str = "",
) -> ExamSession:
    """
    Sessiyani yaratadi va yuz etalonini qayd etadi.

    Etalon SESSIYAGA tegishli, shuning uchun bu bosqich har doim
    ro'yxatga olish (enrollment) — solishtiriladigan avvalgi vektor
    yo'q. Demak bu yerda shaxs TASDIQLANMAYDI:

        FaceID kafolati    : "sessiya davomida odam almashtirilmadi"
        Shaxs kafolati     : operatorning hujjat bo'yicha tekshiruvi

    Clientdan kelgan `score` ataylab E'TIBORGA OLINMAYDI — solishtirish
    uchun etalon bo'lmagach, u faqat client aytgan raqam bo'lardi va
    `score: 100` yuborish orqali tekshiruvni chetlab o'tish mumkin edi.
    """
    from apps.common.utils.vectors import normalize
    from apps.controls import services as controls_services

    pending = session_state.consume_pending(challenge)
    if pending is None:
        raise SessionNotFound("Tekshiruv muddati tugagan, qaytadan urinib ko'ring")

    from apps.exams.models import Exam

    exam = Exam.objects.select_related("setting").get(pk=pending["exam_id"])
    # Sozlama AYNAN SHU YERDA olinadi — imtihon endigina ma'lum bo'ldi.
    config = controls_services.get_client_config(exam)
    face_required = bool(config["face"]["enabled_student"])

    # Etalonni olish uchun aynan bitta yuz ko'rinishi shart.
    if face_required and (not embedding or faces_detected != 1):
        _log_face_attempt(
            pinfl=pending.get("pinfl", ""),
            faces_detected=faces_detected,
            reason="no_embedding" if not embedding else "faces_detected",
        )
        raise FaceVerificationFailed(
            "Kamerada aynan bitta yuz aniq ko'rinishi kerak "
            f"(topilgani: {faces_detected})"
        )

    session = _create_session(
        pending=pending,
        exam=exam,
        device=device,
        computer=computer,
        ip_address=ip_address,
        reference_embedding=normalize(embedding) if embedding else None,
    )

    FaceVerificationLog.objects.create(
        session=session,
        stage=FaceVerificationLog.Stage.INITIAL,
        source=FaceVerificationLog.Source.CLIENT,
        score=0,
        threshold=int(config["face"]["min_score_initial"]),
        passed=bool(embedding),
        faces_detected=faces_detected,
        image_key=image_key,
        occurred_at=timezone.now(),
    )

    # Shaxs hali tasdiqlanmagan — operator hujjat bilan tasdiqlamaguncha
    # `issue_exam_access` imtihonni ochmaydi. Hodisa YARATILMAYDI: bu holat
    # har bir sessiyada uchraydi, ya'ni hodisa oqimida sof shovqin bo'lardi.
    session.meta = {**(session.meta or {}), "identity": {"verified": False}}
    session.save(update_fields=["meta", "updated_at"])

    return session


# --------------------------------------------------------------------------
# Operator tasdig'i — shaxsni aniqlashning YAGONA ishonchli nuqtasi
# --------------------------------------------------------------------------
@transaction.atomic
def confirm_identity(
    session: ExamSession,
    *,
    actor,
    document_type: str,
    document_number: str,
    note: str = "",
) -> ExamSession:
    """
    Operator talabgor shaxsini hujjat bo'yicha tasdiqlaydi.

    Tasdiq BIR MARTA beriladi: qayta yozish audit izini buzadi va
    "kim tasdiqlagan" savoliga ikki xil javob paydo bo'ladi.
    """
    if session.identity_verified:
        raise IdentityAlreadyConfirmed()
    if session.status in ExamSession.TERMINAL_STATUSES:
        raise SessionNotFound("Sessiya yakunlangan")

    session.meta = {
        **(session.meta or {}),
        "identity": {
            "verified": True,
            "by_id": actor.pk,
            "by": actor.username,
            "by_full_name": actor.get_full_name(),
            "at": timezone.now().isoformat(),
            "document_type": document_type,
            "document_number": document_number,
            "note": note[:500],
        },
    }
    session.save(update_fields=["meta", "updated_at"])

    logger.info(
        "Shaxs tasdiqlandi: session=%s operator=%s hujjat=%s",
        session.public_id, actor.username, document_type,
    )
    return session


def reject_identity(session: ExamSession, *, actor, reason: str) -> ExamSession:
    """
    Hujjat mos kelmadi — sessiya darhol tugatiladi.

    Bu "tasdiqlamay qo'yaqolish" dan farq qiladi: tasdiqlanmagan sessiya
    shunchaki ochilmaydi, rad etilgani esa CHETLASHTIRILADI va dalil
    sifatida qayd etiladi.
    """
    session.meta = {
        **(session.meta or {}),
        "identity": {
            "verified": False,
            "rejected": True,
            "by_id": actor.pk,
            "by": actor.username,
            "at": timezone.now().isoformat(),
            "reason": reason[:500],
        },
    }
    session.save(update_fields=["meta", "updated_at"])

    logger.warning(
        "Shaxs RAD ETILDI: session=%s operator=%s sabab=%s",
        session.public_id, actor.username, reason,
    )
    return terminate_session(
        session, actor=actor, reason=f"Shaxs tasdiqlanmadi: {reason}"
    )


def _create_session(
    *, pending: dict, exam, device, computer, ip_address, reference_embedding=None
) -> ExamSession:
    exam_date = timezone.localdate()
    pinfl = pending["pinfl"]

    # "Bitta talabgor = bitta faol sessiya" — atomik Redis qulfi.
    owner = f"dev:{getattr(device, 'pk', 'na')}"
    if not session_state.lock_candidate(pinfl, exam.pk, owner):
        raise SessionAlreadyActive()

    # Urinish raqami KUN ichida hisoblanadi — boshqa sanadagi imtihon
    # yangi sessiya sifatida 1-urinishdan boshlanadi.
    last_attempt = (
        ExamSession.objects.filter(pinfl=pinfl, exam=exam, exam_date=exam_date)
        .order_by("-attempt_no")
        .values_list("attempt_no", flat=True)
        .first()
    )

    zone = computer.zone if computer is not None else None
    session = ExamSession.objects.create(
        pinfl=pinfl,
        last_name=pending.get("last_name", ""),
        first_name=pending.get("first_name", ""),
        middle_name=pending.get("middle_name", ""),
        external_candidate_id=pending.get("external_candidate_id", ""),
        external_session_token_enc=encrypt(pending.get("external_session_token", "")) or "",
        external_status=(pending.get("external_status") or "")[:32],
        external_access_from=_parse_dt(pending.get("external_access_from")),
        external_access_until=_parse_dt(pending.get("external_access_until")),
        reference_embedding=reference_embedding,
        # Imtihondan 90 kun keyin PII anonimlashtiriladi.
        anonymize_after=timezone.now() + timezone.timedelta(days=90),
        exam=exam,
        schedule_id=pending.get("schedule_id"),
        computer=computer,
        zone=zone,
        device=device,
        attempt_no=(last_attempt or 0) + 1,
        exam_date=exam_date,
        status=ExamSession.Status.READY,
        ip_address=ip_address or None,
        mac_address=computer.mac_address if computer is not None else "",
        last_heartbeat_at=timezone.now(),
    )
    logger.info("Sessiya yaratildi: %s (urinish %s)", session.public_id, session.attempt_no)
    return session


def _log_face_attempt(*, pinfl: str, faces_detected: int, reason: str) -> None:
    """Sessiyasiz muvaffaqiyatsiz urinish — sessiya hali yaratilmagan."""
    logger.info(
        "Kirishdagi FaceID rad etildi: pinfl=%s sabab=%s yuzlar=%s",
        mask_pinfl(pinfl), reason, faces_detected,
    )


# --------------------------------------------------------------------------
# 3-qadam: sessiya tokeni + tashqi platformaga kirish
# --------------------------------------------------------------------------
def issue_session_token(session: ExamSession) -> str:
    """
    Opaque sessiya tokeni (JWT emas).

    Ochiq token faqat shu yerda mavjud; DB va Redis'da uning HMAC hash'i
    saqlanadi. Redis dump'i sizib chiqsa, faol sessiyalarni o'g'irlab
    bo'lmaydi.
    """
    raw_token = generate_token(32)
    digest = hash_token(raw_token)
    ttl = settings.PROCTORING["SESSION_TOKEN_TTL"]

    session.token_hash = digest
    session.token_expires_at = timezone.now() + timezone.timedelta(seconds=ttl)
    session.save(update_fields=["token_hash", "token_expires_at", "updated_at"])

    session_state.store_session_token(
        token_hash=digest,
        payload={
            "session_id": session.pk,
            "public_id": str(session.public_id),
            "exam_id": session.exam_id,
            "device_id": session.device_id,
            "zone_id": session.zone_id,
            "status": session.status,
        },
        ttl=ttl,
    )
    return raw_token


def issue_exam_access(session: ExamSession, *, ip_address: str = "") -> dict:
    """
    Tashqi platformaga kirish uchun bir martalik token.

    Token URL'ga QO'YILMAYDI — client uni cookie sifatida o'rnatadi yoki
    POST body'da yuboradi. URL'dagi token brauzer tarixi, `Referer`
    header'i va nginx access log orqali sizib chiqadi.

    Shaxs tasdig'i AYNAN SHU YERDA to'siladi: bu — qaytib bo'lmaydigan
    nuqta. Undan keyin talabgor tashqi platformada test topshira boshlaydi.
    """
    if settings.PROCTORING["REQUIRE_IDENTITY_CONFIRMATION"] and not session.identity_verified:
        raise IdentityNotConfirmed()

    platform_token = session.external_session_token
    if not platform_token:
        # Lookup paytida token kelmagan bo'lsa sessiya umuman
        # yaratilmasligi kerak edi — bu holat kelib chiqsa, muammo bizda.
        logger.error(
            "Sessiya %s da tashqi platforma tokeni yo'q", session.public_id
        )
        raise ExternalPlatformError(
            "Tashqi platforma sessiyasi topilmadi, qaytadan kiring"
        )

    if not session.external_access_open:
        raise ExamNotOpen(
            "Tashqi platforma bu talabgorga hozir kirishga ruxsat bermayapti"
        )

    if session.external_status in _CLOSED_PLATFORM_STATUSES:
        raise ExamNotOpen(
            f"Test tashqi platformada allaqachon yakunlangan ({session.external_status})"
        )

    if session.status == ExamSession.Status.READY:
        session.status = ExamSession.Status.IN_PROGRESS
        session.started_at = timezone.now()
        session.save(update_fields=["status", "started_at", "updated_at"])

    logger.info(
        "WebView ochildi: session=%s ip=%s", session.public_id, ip_address or "-"
    )

    remaining = None
    if session.external_access_until:
        remaining = max(
            0, int((session.external_access_until - timezone.now()).total_seconds())
        )

    return {
        "login_url": session.exam.site_url,
        # ATAYLAB "token" emas: bu TASHQI platformaning sessiya tokeni,
        # bizning `proctoring_session_token` bilan aralashtirilmasin.
        "platform_session_token": platform_token,
        # `post` — token form body'da; `cookie` — QWebEngineProfile orqali.
        "delivery": settings.PROCTORING["EXTERNAL_TOKEN_DELIVERY"],
        "platform_access_until": session.external_access_until,
        "platform_access_seconds_left": remaining,
        "allowed_domains": session.exam.get_allowed_domains(),
    }


# --------------------------------------------------------------------------
# Davriy yuz tekshiruvi
# --------------------------------------------------------------------------
def verify_periodic_face(
    *,
    session: ExamSession,
    embedding: list[float] | None,
    score: int | None,
    faces_detected: int,
    image_key: str,
    config: dict,
    occurred_at=None,
) -> dict:
    """
    Test davomidagi yuz tekshiruvi.

    Yuklama nuqtai nazaridan eng muhim qaror shu yerda: embedding CLIENTDA
    hisoblanadi va serverga 512 float (~2 KB) keladi, rasm emas. Server
    faqat cosine solishtiradi (~5 µs). Aks holda 10 000 talaba × 10s =
    1000 GPU inference/sekund kerak bo'lardi.

    Clientga to'liq ishonib bo'lmagani uchun `audit_rate` ulushidagi
    tekshiruvlarda rasm ham so'raladi va serverda qayta baholanadi.
    """
    from apps.common.utils.vectors import similarity_score

    occurred_at = occurred_at or timezone.now()
    threshold = int(config["face"]["min_score_exam"])

    source = FaceVerificationLog.Source.CLIENT
    if embedding and session.reference_embedding:
        # Etalon kirishda shu sessiyaning O'ZIDA olingan — server qayta
        # hisoblaydi, clientdan kelgan ballga ishonmaymiz.
        score = similarity_score(embedding, session.reference_embedding)
        source = FaceVerificationLog.Source.SERVER
    elif score is None:
        score = 0

    passed = bool(score >= threshold and faces_detected == 1)

    FaceVerificationLog.objects.create(
        session=session,
        stage=FaceVerificationLog.Stage.PERIODIC,
        source=source,
        score=score,
        threshold=threshold,
        passed=passed,
        faces_detected=faces_detected,
        image_key=image_key,
        occurred_at=occurred_at,
    )

    session_state.increment(session.pk, "face_checks")
    fail_count = 0
    if not passed:
        fail_count = session_state.increment(session.pk, "face_fails")
        session_state.bump_risk(session.pk, 8)

        event_type = (
            ProctoringEvent.Type.MULTIPLE_FACES
            if faces_detected > 1
            else ProctoringEvent.Type.FACE_NOT_FOUND
            if faces_detected == 0
            else ProctoringEvent.Type.FACE_MISMATCH
        )
        from apps.proctoring.services.ingest import push_event

        push_event(
            session_id=session.pk,
            zone_id=session.zone_id,
            type=event_type,
            severity=ProctoringEvent.Severity.HIGH,
            occurred_at=occurred_at,
            payload={"score": score, "threshold": threshold, "faces": faces_detected},
            screenshot_key=image_key,
        )
    else:
        # Muvaffaqiyatli tekshiruv hisoblagichni tiklaydi — bitta tasodifiy
        # xato (yorug'lik o'zgardi, bosh burildi) talabgorni chetlashtirmasligi
        # kerak. Faqat KETMA-KET muvaffaqiyatsizliklar hisobga olinadi.
        session_state.reset_counter(session.pk, "face_fails")

    max_fail = int(config["face"]["max_fail"])
    should_terminate = fail_count >= max_fail

    # Tasodifiy server auditi: client embedding'ini sinovdan o'tkazish.
    audit_rate = float(config["face"].get("audit_rate", 0))
    require_audit = secrets.randbelow(1000) < int(audit_rate * 1000)

    return {
        "passed": passed,
        "score": score,
        "threshold": threshold,
        "fail_count": fail_count,
        "max_fail": max_fail,
        "should_terminate": should_terminate,
        "require_server_audit": require_audit,
    }


# --------------------------------------------------------------------------
# Yakunlash
# --------------------------------------------------------------------------
@transaction.atomic
def finish_session(session: ExamSession, *, reason: str = "") -> ExamSession:
    if session.status in ExamSession.TERMINAL_STATUSES:
        return session

    _flush_counters(session)
    session.status = ExamSession.Status.FINISHED
    session.finished_at = timezone.now()
    session.save(
        update_fields=[
            "status", "finished_at", "event_count", "screenshot_count",
            "face_fail_count", "face_check_count", "risk_score", "updated_at",
        ]
    )
    _release(session)
    _broadcast_status(session)
    _notify_external(session, "finished", {"reason": reason})
    return session


@transaction.atomic
def terminate_session(session: ExamSession, *, actor=None, reason: str = "") -> ExamSession:
    """
    Chetlashtirish — DARHOL kuchga kiradi.

    Token Redis'dan o'chiriladi, shuning uchun keyingi so'rov 401 oladi.
    Bu aynan JWT ishlatmaslik sababi.
    """
    if session.status in ExamSession.TERMINAL_STATUSES:
        return session

    _flush_counters(session)
    session.status = ExamSession.Status.TERMINATED
    session.finished_at = timezone.now()
    session.terminated_by = actor
    session.termination_reason = reason[:500]
    session.save(
        update_fields=[
            "status", "finished_at", "terminated_by", "termination_reason",
            "event_count", "screenshot_count", "face_fail_count",
            "face_check_count", "risk_score", "updated_at",
        ]
    )

    ProctoringEvent.objects.create(
        session=session,
        type=ProctoringEvent.Type.SESSION_TERMINATED,
        severity=ProctoringEvent.Severity.CRITICAL,
        occurred_at=timezone.now(),
        payload={"reason": reason, "actor": getattr(actor, "username", "system")},
    )

    _release(session)
    _broadcast_status(session, reason=reason)
    _notify_external(session, "terminated", {"reason": reason})
    return session


def expire_session(session: ExamSession) -> ExamSession:
    """Heartbeat kelmay qolgan sessiya (client o'lgan yoki tarmoq uzilgan)."""
    _flush_counters(session)
    session.status = ExamSession.Status.EXPIRED
    session.finished_at = timezone.now()
    session.save(
        update_fields=[
            "status", "finished_at", "event_count", "screenshot_count",
            "face_fail_count", "face_check_count", "risk_score", "updated_at",
        ]
    )
    _release(session)
    _broadcast_status(session)
    return session


def _broadcast_status(session: ExamSession, **fields) -> None:
    """Dashboard'ga holat o'zgarishini yetkazadi (xatosi oqimni to'xtatmaydi)."""
    from apps.proctoring.services.realtime import broadcast_session_update

    broadcast_session_update(session, **fields)


def _flush_counters(session: ExamSession) -> None:
    """Redis hisoblagichlarini yakuniy holatga ko'chiradi."""
    hot = session_state.get_state(session.pk)
    session.event_count = int(hot.get("events", session.event_count) or 0)
    session.screenshot_count = int(hot.get("shots", session.screenshot_count) or 0)
    session.face_fail_count = int(hot.get("face_fails", session.face_fail_count) or 0)
    session.face_check_count = int(hot.get("face_checks", session.face_check_count) or 0)
    session.risk_score = min(100, int(hot.get("risk", session.risk_score) or 0))


def _release(session: ExamSession) -> None:
    session_state.revoke_session_token(session.token_hash)
    session_state.clear_state(session.pk, session.zone_id)
    if session.pinfl:
        session_state.unlock_candidate(
            session.pinfl, session.exam_id, f"dev:{session.device_id or 'na'}"
        )


def _notify_external(session: ExamSession, status: str, meta: dict) -> None:
    """
    Tashqi platformaga xabar — KRITIK YO'LDA EMAS.

    Celery orqali ketadi; talabgor tashqi API javobini kutmaydi.
    """
    from apps.proctoring.tasks import report_session_result

    try:
        report_session_result.delay(str(session.public_id), status, meta)
    except Exception as exc:
        # Broker tushgan bo'lsa ham sessiya yakunlanishi kerak.
        logger.warning("Natijani navbatga qo'yib bo'lmadi: %s", exc)
