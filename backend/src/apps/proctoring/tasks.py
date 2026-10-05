"""
Fon vazifalari.

Eng muhimi — `flush_event_buffer`. Bu tizimning yuqori yuklamaga
bardoshligini ta'minlaydigan asosiy mexanizm:

    HTTP so'rov  ->  Redis Stream (XADD)       ~0.2 ms, DB'ga tegmaydi
    Celery (5s)  ->  bulk_create (10 000 qator) bitta tranzaksiya

Bu 3 000 tranzaksiya/sekundni ~0.2 tranzaksiya/sekundga aylantiradi.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone
from redis.exceptions import RedisError

from apps.common.redis_client import get_redis
from apps.proctoring.models import (
    ExamSession,
    FaceVerificationLog,
    ProctoringEvent,
    ScreenshotMeta,
)
from apps.proctoring.services import risk as risk_service
from apps.proctoring.services import state as session_state
from apps.proctoring.services import stream as stream_service

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Ingest buffer -> PostgreSQL
#
# Ishonchlilik mexanikasi `services/stream.py` da: osilib qolgan
# yozuvlarni qaytarib olish, batch yiqilganda qator-ma-qator o'tish va
# yozib bo'lmagan qatorni dead-letter oqimiga ko'chirish.
# --------------------------------------------------------------------------
@shared_task(name="proctoring.flush_event_buffer")
def flush_event_buffer():
    """
    Redis Stream'dagi hodisalarni PostgreSQL'ga ommaviy yozadi.

    `ignore_conflicts=True` — `client_event_id` bo'yicha dublikatlar
    jimgina tashlab yuboriladi. Client tarmoq uzilishidan keyin
    buferini qayta yuborishi normal holat.

    Celery `retry` ATAYLAB ishlatilmaydi: yiqilgan batch qayta
    o'qilmasdi (`>` faqat yangi xabarlarni beradi) va o'sha yozuvlar
    abadiy PEL'da qolib ketardi. Endi tiklash `XAUTOCLAIM` orqali
    keyingi siklda o'z-o'zidan bo'ladi.
    """
    stream = settings.PROCTORING["EVENT_STREAM_KEY"]
    client = get_redis()
    batch_size = settings.PROCTORING["EVENT_BATCH_SIZE"]

    # BITTA ishga tushishda bir necha batch — vaqt byudjeti ichida.
    #
    # Ilgari vazifa 5 s da BITTA batch (2000) o'qirdi, ya'ni oqimning
    # yuqori chegarasi 2000 / 5 s = 400 hodisa/s edi (hisoblangan). Undan
    # tez kelsa navbat o'sadi va `EVENT_STREAM_MAXLEN` (approximate trim)
    # oxir-oqibat HALI YOZILMAGAN yozuvlarni ham kesib tashlardi. Bitta
    # batch perf bazasida ~0.3 s yoziladi (o'lchangan: 2000 qator, ~6600
    # hodisa/s), shuning uchun byudjet (`EVENT_FLUSH_BUDGET_S`, 3 s)
    # jadval oralig'idan (5 s) va `expires` (10 s) dan qisqa qoladi.
    # Har batch avvalgidek alohida yoziladi va ACK qilinadi — ishonchlilik
    # mexanikasi (`XAUTOCLAIM`, qator-ma-qator, `:dead`) o'zgarmagan.
    budget = float(settings.PROCTORING.get("EVENT_FLUSH_BUDGET_S", 3.0))
    deadline = time.monotonic() + budget
    total = {"read": 0, "written": 0, "dead": 0}
    while True:
        result = _flush_event_batch(client, stream, batch_size)
        for key in total:
            total[key] += result[key]
        if result["read"] < batch_size or time.monotonic() >= deadline:
            return total


def _flush_event_batch(client, stream: str, batch_size: int) -> dict:
    """Bitta batch: o'qish -> yozish -> ACK (avvalgi `flush_event_buffer` tanasi)."""
    entries = stream_service.read_batch(client, stream, batch_size)
    if not entries:
        return {"read": 0, "written": 0, "dead": 0}

    rows: list[tuple[str, dict, ProctoringEvent]] = []
    malformed: list[str] = []

    for entry_id, fields in entries:
        try:
            rows.append(
                (
                    entry_id,
                    fields,
                    ProctoringEvent(
                        session_id=int(fields["session_id"]),
                        type=fields["type"],
                        severity=int(fields["severity"]),
                        occurred_at=_parse(fields["occurred_at"]),
                        payload=json.loads(fields.get("payload") or "{}"),
                        screenshot_key=fields.get("screenshot_key", ""),
                        client_event_id=fields.get("client_event_id", ""),
                    ),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            # Yozuvning o'zi buzuq — model obyektiga aylantirib bo'lmadi.
            logger.warning("Buzilgan event yozuvi: %s", exc)
            stream_service.to_dead_letter(stream, fields, f"parse: {exc}")
            malformed.append(entry_id)

    result = stream_service.write_with_fallback(ProctoringEvent, rows, stream)
    stream_service.ack(client, stream, result["ok"] + malformed)

    dead = result["dead"] + len(malformed)
    if dead:
        logger.error("Event flush: %s ta yozuv dead-letter'ga ketdi", dead)

    return {
        "read": len(entries),
        "written": len(result["ok"]) - result["dead"],
        "dead": dead,
    }


@shared_task(name="proctoring.flush_screenshot_buffer")
def flush_screenshot_buffer():
    """Skrinshot metadata'sini ommaviy yozadi (binary allaqachon S3'da)."""
    stream = settings.PROCTORING["SCREENSHOT_STREAM_KEY"]
    client = get_redis()

    entries = stream_service.read_batch(
        client, stream, settings.PROCTORING["EVENT_BATCH_SIZE"]
    )
    if not entries:
        return {"read": 0, "written": 0, "dead": 0}

    # Retention: skrinshotlar 90 kundan keyin o'chiriladi.
    purge_after = timezone.now() + timedelta(days=90)
    rows: list[tuple[str, dict, ScreenshotMeta]] = []
    malformed: list[str] = []

    for entry_id, fields in entries:
        try:
            rows.append(
                (
                    entry_id,
                    fields,
                    ScreenshotMeta(
                        session_id=int(fields["session_id"]),
                        kind=fields.get("kind", "screen"),
                        object_key=fields["object_key"],
                        sha256=fields.get("sha256", ""),
                        size_bytes=int(fields.get("size_bytes", 0)),
                        width=int(fields.get("width", 0)),
                        height=int(fields.get("height", 0)),
                        captured_at=_parse(fields["captured_at"]),
                        is_committed=True,
                        purge_after=purge_after,
                        question_id=fields.get("question_id", "") or "",
                        question_number=int(fields["question_number"])
                        if str(fields.get("question_number") or "").isdigit() else None,
                    ),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("Buzilgan screenshot yozuvi: %s", exc)
            stream_service.to_dead_letter(stream, fields, f"parse: {exc}")
            malformed.append(entry_id)

    result = stream_service.write_with_fallback(ScreenshotMeta, rows, stream)
    stream_service.ack(client, stream, result["ok"] + malformed)
    _drop_replaced_question_shots(
        {(row.session_id, row.question_id) for _, _, row in rows if row.question_id}
    )

    return {
        "read": len(entries),
        "written": len(result["ok"]) - result["dead"],
        "dead": result["dead"] + len(malformed),
    }


def _drop_replaced_question_shots(pairs: set) -> int:
    """
    Savolga BITTA kadr (S3 yo'li): eng yangisidan boshqalari o'chiriladi.

    Fayl tizimi yo'lida bu qator YANGILASH bilan qilinadi
    (`services/screenshots.py`); bu yerda yozish ommaviy va ikki bosqichli,
    shuning uchun tozalash yozilgandan KEYIN. Tartib retention bilan bir
    xil: avval obyekt, keyin qator. Xato yutiladi - eng yomon holat
    vaqtincha ikki kadr, dalil yo'qolishi emas; keyingi yozuv tozalaydi.
    """
    from apps.common.storage import delete_objects

    removed = 0
    for session_id, question_id in pairs:
        try:
            stale = list(
                ScreenshotMeta.objects.filter(session_id=session_id, question_id=question_id)
                .order_by("-captured_at", "-id").values_list("id", "object_key")[1:]
            )
            if not stale:
                continue
            delete_objects([key for _, key in stale])
            ScreenshotMeta.objects.filter(id__in=[pk for pk, _ in stale]).delete()
            removed += len(stale)
        except Exception:
            logger.warning(
                "Eski savol kadri o'chirilmadi: session=%s q=%s", session_id, question_id,
                exc_info=True,
            )
    return removed


@shared_task(name="proctoring.flush_session_state")
def flush_session_state():
    """
    Redis'dagi issiq holatni sessiyalarga ko'chiradi (write-behind).

    Har bir heartbeat uchun `UPDATE` qilish o'rniga, 10 soniyada bir
    marta o'zgargan sessiyalarni bitta `bulk_update` bilan yangilaymiz.
    """
    session_ids = session_state.drain_dirty()
    if not session_ids:
        return {"updated": 0}

    states = session_state.get_states(session_ids)
    # `select_related("exam")` MAJBURIY: har bir sessiya uchun
    # siyosat o'qiladi (`_policy_for`) va u `session.exam` ga
    # murojaat qiladi. Usiz bu 5000 sessiyali flush'da 5000 ta
    # qo'shimcha so'rov degani - har 10 soniyada.
    sessions = list(
        ExamSession.objects.select_related("exam").filter(pk__in=session_ids)
    )
    if not sessions:
        return {"updated": 0}

    now = timezone.now()
    now_ts = now.timestamp()
    breakdowns = risk_service.breakdowns([session.pk for session in sessions])
    # Siyosat imtihonga bog'liq - imtihon bo'yicha BIR MARTA o'qiladi
    # (ilgari har sessiyada kesh so'rovi, ya'ni Redis round-trip).
    risk_configs: dict[int, dict] = {}
    to_update: list[ExamSession] = []

    for session in sessions:
        state = states.get(session.pk) or {}
        if not state:
            continue

        heartbeat = state.get("hb")
        if heartbeat:
            session.last_heartbeat_at = datetime.fromtimestamp(
                int(heartbeat), tz=timezone.get_current_timezone()
            )
        session.event_count = int(state.get("events", session.event_count) or 0)
        session.screenshot_count = int(state.get("shots", session.screenshot_count) or 0)
        session.face_fail_count = int(state.get("face_fails", session.face_fail_count) or 0)
        session.face_check_count = int(state.get("face_checks", session.face_check_count) or 0)
        # Ball PASAYISH bilan o'qiladi: Redis'dagi xom qiymat oxirgi
        # hodisadan beri o'zgarmagan, vaqt esa o'tgan
        # (`services/risk.py` - lazy pasayish). Holat yuqorida pipeline
        # bilan o'qilgan - qayta so'ralmaydi.
        config = risk_configs.get(session.exam_id)
        if config is None:
            config = risk_configs[session.exam_id] = risk_service.resolve_config(
                _policy_for(session)
            )
        session.risk_score = risk_service.current_from_state(state, config=config, now=now_ts)
        session.risk_breakdown = breakdowns.get(session.pk) or {}
        session.updated_at = now
        to_update.append(session)

    if to_update:
        _write_session_state(to_update)
    return {"updated": len(to_update)}


#: `_write_session_state` bitta UPDATE'dagi qatorlar soni (parametrlar
#: soni = 9 x shu; PostgreSQL chegarasi 65535).
_STATE_UPDATE_CHUNK = 1000


def _write_session_state(sessions: list[ExamSession]) -> None:
    """
    Issiq holat ustunlarini `UPDATE ... FROM (VALUES ...)` bilan yozadi.

    `bulk_update` EMAS — o'lchangan sabab: 5000 sessiyada u 8 ustun x
    5000 qatorlik `CASE WHEN` ifodasini Python'da quradi va flush 11.9 s
    davom etardi (jadval 10 s da bir ishga tushadi, ya'ni vazifalar
    ustma-ust yig'ilardi); DB'ning o'z vaqti atigi ~1.1 s edi. Natija
    bir xil: xuddi shu 8 ustun, xuddi shu qiymatlar, bitta tranzaksiya.
    """
    from django.db import connections, transaction

    columns = "(id, hb, ev, sh, ff, fc, rs, rb, ua)"
    first_row = (
        "(%s::bigint, %s::timestamptz, %s::integer, %s::integer, %s::integer,"
        " %s::integer, %s::integer, %s::jsonb, %s::timestamptz)"
    )
    row = "(%s, %s, %s, %s, %s, %s, %s, %s, %s)"
    with transaction.atomic(using="default"), connections["default"].cursor() as cursor:
        for start in range(0, len(sessions), _STATE_UPDATE_CHUNK):
            chunk = sessions[start:start + _STATE_UPDATE_CHUNK]
            params: list = []
            for session in chunk:
                params.extend([
                    session.pk, session.last_heartbeat_at, session.event_count,
                    session.screenshot_count, session.face_fail_count,
                    session.face_check_count, session.risk_score,
                    json.dumps(session.risk_breakdown or {}), session.updated_at,
                ])
            values = ", ".join([first_row] + [row] * (len(chunk) - 1))
            cursor.execute(
                f"UPDATE {ExamSession._meta.db_table} AS s SET "
                "last_heartbeat_at = v.hb, event_count = v.ev, screenshot_count = v.sh, "
                "face_fail_count = v.ff, face_check_count = v.fc, risk_score = v.rs, "
                "risk_breakdown = v.rb, updated_at = v.ua "
                f"FROM (VALUES {values}) AS v {columns} WHERE s.id = v.id",
                params,
            )


def _policy_for(session) -> dict:
    """
    Sessiya imtihonining kuzatuv siyosati.

    Keshlangan (`controls.services.get_client_config`), shuning uchun
    har bir sessiya uchun chaqirish xavfsiz: bir xil imtihondagi
    500 sessiya bitta kesh yozuvini o'qiydi.
    """
    from apps.controls.services import get_client_config

    try:
        return (get_client_config(session.exam) or {}).get("proctoring") or {}
    except Exception:
        logger.warning("Siyosatni o'qib bo'lmadi: %s", session.pk, exc_info=True)
        return {}


# --------------------------------------------------------------------------
# Texnik xizmat
# --------------------------------------------------------------------------
@shared_task(name="proctoring.close_stale_sessions")
def close_stale_sessions():
    """
    Heartbeat kelmay qolgan sessiyalarni yopadi.

    Client o'lgan, elektr uzilgan yoki tarmoq yo'qolgan bo'lishi mumkin.
    Bunday sessiyalar abadiy "jarayonda" qolib ketmasligi kerak — aks
    holda `SessionAlreadyActive` qulfi talabgorni qayta kirishdan
    to'sib qo'yadi.

    DB'DAGI VAQT YETARLI DALIL EMAS. `last_heartbeat_at` ni faqat ingest
    ishchisi (`flush_session_state`) Redis'dan ko'chiradi; u to'xtasa
    yoki kechiksa, 15 daqiqadan keyin bu vazifa SOG' sessiyalarni ham
    (daqiqasiga 500 tadan) yopib, imtihonlarni to'xtatardi. Shuning
    uchun har nomzod yopilishdan oldin Redis'dagi haqiqiy `hb` bilan
    tekshiriladi:

      * Redis'da yangi `hb` — sessiya tirik: yopilmaydi, DB vaqti
        tuzatiladi (aks holda ular har safar birinchi 500 talikni
        egallab, haqiqatan o'lganlarini to'sib qo'yardi);
      * Redis ishlamayapti — tirikligini bilib bo'lmaydi: shu yurishda
        HECH KIM yopilmaydi (uzilish paytida heartbeat DB'ga yoziladi —
        `HeartbeatView`);
      * Redis'da `hb` yo'q yoki u ham eski — yopiladi.
    """
    stale_after = settings.PROCTORING["STALE_SESSION_AFTER"]
    threshold = timezone.now() - timedelta(seconds=stale_after)
    stale = list(
        ExamSession.objects.filter(
            status__in=[
                ExamSession.Status.IN_PROGRESS,
                ExamSession.Status.READY,
                ExamSession.Status.FACE_CHECK,
            ],
            last_heartbeat_at__lt=threshold,
        ).order_by("last_heartbeat_at")[:500]
    )
    if not stale:
        return {"closed": 0}

    try:
        states = session_state.get_states([session.pk for session in stale])
    except RedisError as exc:
        logger.error(
            "close_stale_sessions: Redis ishlamayapti — heartbeat tekshirilmadi, "
            "%s ta nomzod yopilmadi: %s", len(stale), exc,
        )
        return {"closed": 0, "skipped": len(stale), "reason": "redis_unavailable"}

    alive = _alive_heartbeats(stale, states, stale_after=stale_after)
    if alive:
        # Bu holatning o'zi nosozlik belgisi: write-behind ishlamayapti.
        logger.warning(
            "close_stale_sessions: %s ta sessiya DB'da eskirgan, lekin Redis'da tirik — "
            "`flush_session_state` (ingest ishchisi) ishlayaptimi?", len(alive),
        )
        _sync_heartbeats(alive)

    from apps.proctoring.services.session import expire_session

    closed = 0
    for session in stale:
        if session.pk in alive:
            continue
        try:
            expire_session(session)
            closed += 1
        except Exception as exc:
            logger.error("Sessiyani yopishda xato (%s): %s", session.pk, exc)

    if closed:
        logger.info("%s ta eskirgan sessiya yopildi", closed)
    return {"closed": closed, "alive": len(alive)}


def _alive_heartbeats(sessions, states: dict, *, stale_after: int) -> dict[int, int]:
    """`session_id -> hb` — Redis'dagi heartbeat'i hali eskirmagan sessiyalar."""
    now_ts = time.time()
    alive: dict[int, int] = {}
    for session in sessions:
        raw = (states.get(session.pk) or {}).get("hb")
        try:
            heartbeat = int(raw)
        except (TypeError, ValueError):
            continue
        if now_ts - heartbeat < stale_after:
            alive[session.pk] = heartbeat
    return alive


def _sync_heartbeats(alive: dict[int, int]) -> None:
    """Redis'dagi haqiqiy heartbeat vaqtini DB'ga yozadi (bitta UPDATE)."""
    from django.db.models import Case, DateTimeField, Value, When

    tz = timezone.get_current_timezone()
    ExamSession.objects.filter(pk__in=list(alive)).update(
        last_heartbeat_at=Case(
            *[
                When(pk=pk, then=Value(datetime.fromtimestamp(heartbeat, tz=tz)))
                for pk, heartbeat in alive.items()
            ],
            output_field=DateTimeField(),
        )
    )


@shared_task(name="proctoring.report_session_result", bind=True, max_retries=5)
def report_session_result(self, public_id: str, status: str, meta: dict):
    """
    Sessiya natijasini tashqi platformaga yuboradi.

    Kritik yo'lda emas — shuning uchun retry va uzun backoff bilan.
    Talabgor bu chaqiruvni kutmaydi.
    """
    from apps.integrations.exam_platform import get_client

    ok = get_client().report_result(session_id=public_id, status=status, meta=meta)
    if not ok:
        # 30s, 60s, 120s... — tashqi API tiklanishiga vaqt beramiz.
        raise self.retry(countdown=30 * (2**self.request.retries), max_retries=5)
    return {"reported": public_id}


def _create_daily_partition(cursor, day) -> str:
    """
    Bir kunlik partitsiya yaratadi.

    DEFAULT partitsiyada shu kunga tegishli qatorlar bo'lsa, PostgreSQL
    `CREATE ... PARTITION OF` ni RAD ETADI. Shuning uchun avval o'sha
    qatorlarni vaqtincha chiqarib olib, partitsiya yaratilgach qaytaramiz.
    Hammasi bitta tranzaksiyada — orada hodisa yo'qolmasin.

    Xato MATNIGA tayanmaymiz, oldindan so'rov bilan tekshiramiz: server
    xabarlari lokalga bog'liq (rus tilidagi PostgreSQL "would be violated"
    demaydi) va bunday tekshiruv jimgina buzilardi.
    """
    name = f"proctoring_event_{day:%Y%m%d}"
    bounds = [day, day + timedelta(days=1)]

    cursor.execute("SELECT to_regclass(%s)", [name])
    if cursor.fetchone()[0] is not None:
        return name

    cursor.execute(
        "SELECT EXISTS(SELECT 1 FROM proctoring_event_default "
        "WHERE occurred_at >= %s AND occurred_at < %s)",
        bounds,
    )
    has_orphans = cursor.fetchone()[0]

    if not has_orphans:
        cursor.execute(
            f"CREATE TABLE {name} PARTITION OF proctoring_event "
            f"FOR VALUES FROM (%s) TO (%s)",
            bounds,
        )
        return name

    logger.warning(
        "%s: DEFAULT partitsiyada shu kunning qatorlari bor — ko'chirilmoqda", name
    )
    cursor.execute(
        "CREATE TEMP TABLE _moved_rows ON COMMIT DROP AS "
        "WITH moved AS ("
        "  DELETE FROM proctoring_event_default "
        "   WHERE occurred_at >= %s AND occurred_at < %s RETURNING *"
        ") SELECT * FROM moved",
        bounds,
    )
    cursor.execute(
        f"CREATE TABLE {name} PARTITION OF proctoring_event FOR VALUES FROM (%s) TO (%s)",
        bounds,
    )
    cursor.execute("INSERT INTO proctoring_event SELECT * FROM _moved_rows")
    cursor.execute("SELECT count(*) FROM _moved_rows")
    logger.info("%s: %s ta qator DEFAULT dan ko'chirildi", name, cursor.fetchone()[0])
    cursor.execute("DROP TABLE _moved_rows")
    return name


@shared_task(name="proctoring.rotate_event_partitions")
def rotate_event_partitions(days_ahead: int = 7):
    """
    Kelgusi kunlar uchun partitsiyalar yaratadi.

    `proctoring_event` jadvali `occurred_at` bo'yicha RANGE partitsiyalangan.
    Partitsiya oldindan yaratilmasa, yangi kun boshlanganda INSERT xato
    beradi va butun batch yiqiladi.

    DEFAULT partitsiya — oxirgi himoya qatlami. Beat bir hafta ishlamay
    qolsa yoki kutilmagan sana kelsa, qator YO'QOLMAYDI: u DEFAULT ga
    tushadi va keyingi rotatsiyada o'z kuniga ko'chiriladi.
    """
    from django.db import connection, transaction

    created = []
    today = timezone.localdate()

    with transaction.atomic(), connection.cursor() as cursor:
        # Jadval partitsiyalanganmi? Bo'lmasa — bu vazifa bekor.
        cursor.execute(
            "SELECT 1 FROM pg_partitioned_table pt "
            "JOIN pg_class c ON c.oid = pt.partrelid "
            "WHERE c.relname = 'proctoring_event'"
        )
        if cursor.fetchone() is None:
            logger.debug("proctoring_event partitsiyalanmagan — rotatsiya o'tkazib yuborildi")
            return {"created": [], "default": False}

        cursor.execute(
            "CREATE TABLE IF NOT EXISTS proctoring_event_default "
            "PARTITION OF proctoring_event DEFAULT"
        )

        # Kechagi kun ham: vaqt mintaqasi chegarasidagi hodisalar uchun.
        for offset in range(-1, days_ahead + 1):
            created.append(_create_daily_partition(cursor, today + timedelta(days=offset)))

        cursor.execute("SELECT count(*) FROM proctoring_event_default")
        orphans = cursor.fetchone()[0]

    if orphans:
        logger.warning(
            "DEFAULT partitsiyada %s ta qator qoldi — sanasi kutilgan "
            "oynadan tashqarida", orphans,
        )

    return {"created": created, "default": True, "default_rows": orphans}


@shared_task(name="proctoring.purge_expired_artifacts")
def purge_expired_artifacts(batch_size: int = 5000):
    """
    Retention siyosati: eski skrinshotlar va PII.

    Skrinshotlar avval object storage'dan, keyin metadata DB'dan
    o'chiriladi (teskari tartibda qilinsa "yetim" fayllar qoladi).
    """
    from apps.common.storage import delete_objects

    now = timezone.now()

    expired = list(
        ScreenshotMeta.objects.filter(purge_after__lt=now).values_list("id", "object_key")[
            :batch_size
        ]
    )
    deleted_objects = 0
    if expired:
        deleted_objects = delete_objects([key for _, key in expired])
        ScreenshotMeta.objects.filter(id__in=[pk for pk, _ in expired]).delete()

    # Sessiyadagi talabgor PII'sini anonimlashtirish. Sessiya qatori
    # O'CHIRILMAYDI — hodisalar, audit va statistika unga bog'langan;
    # faqat shaxsni aniqlash imkoni yo'qoladi.
    #
    # `bulk_update` emas, `update()`: bu yerda hech qanday Python mantiq
    # yo'q va yuz minglab qator bo'lishi mumkin.
    stale_pii = ExamSession.objects.filter(
        anonymize_after__lt=now, is_anonymized=False
    ).values_list("id", flat=True)[:batch_size]
    ids = list(stale_pii)

    anonymized = 0
    if ids:
        anonymized = ExamSession.objects.filter(id__in=ids).update(
            pinfl=None,
            last_name="",
            first_name="",
            middle_name="",
            external_candidate_id="",
            reference_embedding=None,
            photo_key="",
            is_anonymized=True,
            updated_at=now,
        )

    if ids:
        # Yuz tekshiruvi qatorlaridagi JSHSHIR ham bo'shatiladi:
        # anonimlashtirilgan sessiya yonida ochiq PII qolsa,
        # anonimlashtirishning o'zi ma'nosiz bo'lardi. Qator
        # o'chirilmaydi — ball va vaqt statistikaga kerak.
        FaceVerificationLog.objects.filter(session_id__in=ids).exclude(pinfl="").update(
            pinfl=""
        )

    return {"screenshots_purged": deleted_objects, "sessions_anonymized": anonymized}


def _parse(value) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)


@shared_task(name="proctoring.purge_expired_evidence")
def purge_expired_evidence(batch_size: int = 1000, max_batches: int = 50):
    """
    Muddati o'tgan dalillarni o'chiradi.

    SKRINSHOT TOZALASHIDAN ALOHIDA va bu ataylab: dalilning muddati
    QATORDA yozilgan (`purge_after`), skrinshotniki esa sanadan
    hisoblanadi. Ularni birlashtirish dalil uchun siyosatdagi
    muddatni e'tiborsiz qoldirardi.

    Tartib SKRINSHOTNIKI bilan bir xil: avval FAYL, keyin qator.
    Teskarisida hech kim biladigan yetim fayl qolardi.

    Kichik partiyalar: 500 mashinali bino kuniga ~4000 dalil
    yig'adi va bitta yurishda ularning hammasini o'chirish
    imtihon paytidagi diskni band qilardi.
    """
    from apps.proctoring.models import EvidenceArtifact
    from apps.proctoring.services import evidence as evidence_service

    now = timezone.now()
    removed = files = 0

    for _ in range(max_batches):
        batch = list(
            EvidenceArtifact.objects.filter(purge_after__lt=now)
            .order_by("purge_after")[:batch_size]
        )
        if not batch:
            break

        for artifact in batch:
            try:
                if evidence_service.delete(artifact):
                    files += 1
                removed += 1
            except Exception:
                # Bitta fayl o'chmagani qolganlarini to'xtatmasligi
                # kerak: sabab odatda huquqlarda va u keyingi
                # yurishda takrorlanadi.
                logger.exception("Dalilni o'chirib bo'lmadi: %s", artifact.pk)

    if removed:
        logger.info("Dalillar tozalandi: %s qator, %s fayl", removed, files)
    return {"removed": removed, "files": files}


@shared_task(name="proctoring.purge_expired_face_images")
def purge_expired_face_images(batch_size: int = 2000, max_batches: int = 20):
    """
    Muddati o'tgan FaceID kadrlari: FAYL o'chiriladi, QATOR QOLADI.

    DALIL TOZALASHIDAN FARQI SHU. `EvidenceArtifact` butunlay
    o'chiriladi - u faqat fayl haqidagi yozuv. Yuz tekshiruvi qatori
    esa fayldan ANCHA ko'proq narsani saqlaydi: ball, chegara, vaqt
    va natija. Ular bayonnomaning bir qismi va rasm muddati
    tugagani uchun yo'qolmasligi kerak - "80 ball bilan kiritilgan"
    degan yozuv rasmsiz ham dalil bo'lib qoladi.

    Tartib: avval FAYL, keyin qatordagi yo'l. Teskarisida jarayon
    o'rtada yiqilsa, diskda hech kim biladigan yetim fayl qolardi.

    Kichik partiyalar: retention bir kunda minglab faylni o'chirishi
    mumkin va bu imtihon paytidagi diskni band qilardi.
    """
    from apps.proctoring.services import face_images

    now = timezone.now()
    removed = files = 0

    for _ in range(max_batches):
        batch = list(
            FaceVerificationLog.objects.filter(image_purge_after__lt=now)
            .exclude(image_path="", reference_image_path="")
            .order_by("image_purge_after")
            .values_list("id", "image_path", "reference_image_path")[:batch_size]
        )
        if not batch:
            break

        cleared = []
        for log_id, path, reference_path in batch:
            # IKKALA FAYL BIRGA ketadi: jonli kadr va hujjat rasmi
            # bitta tekshiruvning ikki tomoni, bittasini qoldirish
            # yarim dalil berardi.
            try:
                for candidate in (path, reference_path):
                    if candidate and face_images.discard(candidate):
                        files += 1
            except Exception:
                # Bitta fayl o'chmagani qolganlarini to'xtatmasligi
                # kerak: sabab odatda huquqlarda va u keyingi
                # yurishda takrorlanadi.
                logger.exception("FaceID rasmini o'chirib bo'lmadi: %s", path)
                continue
            cleared.append(log_id)

        if cleared:
            removed += FaceVerificationLog.objects.filter(id__in=cleared).update(
                image_path="", reference_image_path="", image_purge_after=None
            )

        if len(batch) < batch_size:
            break

    if removed:
        logger.info("FaceID kadrlari tozalandi: %s qator, %s fayl", removed, files)
    return {"cleared": removed, "files": files}


@shared_task(name="proctoring.purge_expired_screenshots")
def purge_expired_screenshots(batch_size: int = 2000, max_batches: int = 50):
    """
    Muddati o'tgan skrinshotlar: FAYL va DB qatori BIRGA o'chiriladi.

    Tartib muhim — avval fayl, keyin qator. Teskarisida (qator avval)
    jarayon o'rtada yiqilsa, diskda hech kim biladigan yetim fayl qoladi:
    uni topish uchun butun daraxtni DB bilan solishtirish kerak bo'ladi.
    Bu tartibda esa eng yomon holat — fayli yo'q qator, u keyingi
    yurishda baribir o'chadi (`storage.delete` topilmasa `False` qaytaradi,
    xato ko'tarmaydi).

    Nima uchun soatiga: 500 client × 3 soat × 10s ≈ 500 000 fayl/kun.
    Kunlik bitta yurishda bu diskka bir necha soatlik `unlink` bo'roni
    beradi va o'sha paytdagi imtihonga xalaqit qiladi. Soatlik kichik
    partiyalar yukni tekis yoyadi.

    `batch_size` — bitta so'rovda olinadigan qator soni;
    `max_batches` — bitta yurishdagi chegara (task cheksiz ishlamasin).
    """
    from apps.common.screenshot_storage import get_screenshot_storage
    from apps.proctoring.models import ProctoringScreenshot

    retention_days = settings.SCREENSHOT_STORAGE["RETENTION_DAYS"]
    cutoff = timezone.now() - timedelta(days=retention_days)
    storage = get_screenshot_storage()

    files_deleted = 0
    rows_deleted = 0
    missing = 0

    for _batch in range(max_batches):
        expired = list(
            ProctoringScreenshot.objects.filter(captured_at__lt=cutoff)
            .order_by("captured_at")
            .values_list("id", "file_path")[:batch_size]
        )
        if not expired:
            break

        removable: list[int] = []
        for screenshot_id, file_path in expired:
            try:
                if storage.delete(file_path):
                    files_deleted += 1
                else:
                    missing += 1
                removable.append(screenshot_id)
            except OSError as exc:
                # Disk to'la, huquq yo'q, NFS uzildi — qatorni QOLDIRAMIZ.
                # U keyingi yurishda qayta uriniladi; o'chirib yuborsak
                # fayl abadiy yetim bo'lib qoladi.
                logger.error(
                    "Skrinshot fayli o'chirilmadi (id=%s, %s): %s",
                    screenshot_id, file_path, exc,
                )

        if removable:
            rows_deleted += ProctoringScreenshot.objects.filter(
                id__in=removable
            ).delete()[0]

        if len(expired) < batch_size:
            break

    # Bo'shab qolgan sessiya kataloglari. Ularsiz bir yildan keyin diskda
    # millionlab bo'sh katalog qoladi va backup ham, `ls` ham imkonsiz.
    pruned_dirs = storage.prune_empty_dirs() if rows_deleted else 0

    return {
        "files_deleted": files_deleted,
        "rows_deleted": rows_deleted,
        "files_missing": missing,
        "dirs_pruned": pruned_dirs,
        "retention_days": retention_days,
    }
