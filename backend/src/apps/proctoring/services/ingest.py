"""
Hodisa va skrinshot metadata'sini qabul qilish.

Bu — butun tizimning eng yuqori yuklamali yo'li. Hisob-kitob (10 000 talaba):

    Event      : ~2 000 req/s
    Screenshot : ~1 000 req/s
    Heartbeat  : ~333  req/s

Agar har bir hodisa alohida `INSERT` bo'lsa, bu 3 000 tranzaksiya/sekund.
PostgreSQL buni ko'tara olmaydi (WAL fsync, indeks yangilanishi, autovacuum).

Yechim — ikki bosqichli yozish:

    HTTP so'rov  ->  Redis Stream (XADD, ~0.2 ms)   [darhol javob]
    Celery       ->  bulk_create (5 s da bir marta) [~10 000 qator/batch]

Natijada DB'ga sekundiga 3 000 emas, ~0.2 tranzaksiya tushadi.

Istisno: KRITIK hodisalar (severity >= HIGH) buffer'dan tashqari, darhol
yoziladi va WebSocket orqali proktorga uzatiladi. Dalil yo'qolmasligi kerak.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from apps.common.redis_client import get_redis
from apps.proctoring.models import ProctoringEvent, ScreenshotMeta
from apps.proctoring.services import risk as risk_service
from apps.proctoring.services import state as session_state

logger = logging.getLogger(__name__)

#: Hodisa turi -> xavf balliga qo'shiladigan qiymat.
#:
#: BU ZAXIRA RO'YXAT. Amaldagi qiymatlar `controls.EventRiskWeight`
#: jadvalida va ular administrator tomonidan sozlanadi
#: (`services/risk.py:weight_for`). Kod ichidagi qiymatlar jadval
#: bo'sh bo'lganda ishlaydi: "sozlanmagan tizim ballni umuman
#: hisoblamaydi" holati chetlashtirish qarorini asossiz qoldirardi.
RISK_WEIGHTS: dict[str, int] = {
    ProctoringEvent.Type.WINDOW_BLUR: 3,
    ProctoringEvent.Type.FULLSCREEN_EXIT: 5,
    ProctoringEvent.Type.HOTKEY_BLOCKED: 2,
    ProctoringEvent.Type.CLIPBOARD_BLOCKED: 4,
    ProctoringEvent.Type.MULTI_MONITOR: 12,
    ProctoringEvent.Type.CAMERA_LOST: 10,
    ProctoringEvent.Type.CAMERA_BLOCKED: 15,
    ProctoringEvent.Type.RDP_DETECTED: 30,
    ProctoringEvent.Type.VM_DETECTED: 25,
    ProctoringEvent.Type.PROCESS_BLACKLISTED: 15,
    ProctoringEvent.Type.FACE_NOT_FOUND: 6,
    ProctoringEvent.Type.FACE_MISMATCH: 12,
    ProctoringEvent.Type.MULTIPLE_FACES: 20,
    ProctoringEvent.Type.OBJECT_DETECTED: 15,
    ProctoringEvent.Type.CLIENT_ANOMALY: 20,
    ProctoringEvent.Type.NAVIGATION_BLOCKED: 8,
    ProctoringEvent.Type.NETWORK_LOST: 2,
}

#: Shu darajadan yuqori hodisalar buffer'ni chetlab, darhol yoziladi.
IMMEDIATE_SEVERITY = ProctoringEvent.Severity.HIGH


def push_event(
    *,
    session_id: int,
    zone_id: int | None,
    type: str,
    severity: int,
    occurred_at: datetime,
    payload: dict | None = None,
    screenshot_key: str = "",
    client_event_id: str = "",
    risk_config: dict | None = None,
) -> None:
    """
    Bitta hodisani navbatga qo'yadi (yoki kritik bo'lsa — darhol yozadi).

    `risk_config` — imtihon siyosatidagi ball sozlamalari
    (pasayish, cooldown, chegaralar). Berilmasa standart qiymatlar
    ishlatiladi: bu yo'l sessiyasiz kontekstlarda (masalan
    `check_frozen_frames`) chaqiriladi va u yerda imtihon profilini
    o'qish uchun qo'shimcha so'rov kerak bo'lardi.
    """
    occurred_at, original = clamp_time(occurred_at)
    record = {
        "session_id": session_id,
        "zone_id": zone_id or 0,
        "type": type,
        "severity": int(severity),
        "occurred_at": occurred_at.isoformat(),
        "payload": json.dumps(_with_original_time(payload, original)),
        "screenshot_key": screenshot_key,
        "client_event_id": client_event_id,
    }

    session_state.increment(session_id, "events")
    _apply_risk(session_id, type, risk_config)

    if int(severity) >= IMMEDIATE_SEVERITY:
        _write_immediately(record)
    else:
        _enqueue(settings.PROCTORING["EVENT_STREAM_KEY"], record)

    _broadcast(record)


def push_events_batch(*, session, events: list[dict]) -> int:
    """
    Client bir necha hodisani bitta so'rovda yuboradi (batch).

    Bu client tomonidagi eng muhim optimizatsiya: 5 soniyalik oynada
    to'plangan hodisalar bitta HTTP so'rovda ketadi. Trafik va TLS
    handshake soni keskin kamayadi.
    """
    accepted = 0
    skewed = 0
    pipeline_records: list[dict] = []

    # Siyosat BIR MARTA o'qiladi: u keshlangan, lekin har hodisa
    # uchun chaqirish 200 ta hodisali batch'da 200 ta kesh
    # qidiruvini bergan bo'lardi.
    from apps.controls.services import get_client_config

    risk_config = risk_service.resolve_config(
        (get_client_config(session.exam) or {}).get("proctoring")
    )

    for item in events:
        event_type = item.get("type")
        if event_type not in ProctoringEvent.Type.values:
            continue

        occurred_at, original = clamp_time(item.get("occurred_at"))
        severity = int(item.get("severity", ProctoringEvent.Severity.LOW))
        if original:
            skewed += 1
        record = {
            "session_id": session.pk,
            "zone_id": session.zone_id or 0,
            "type": event_type,
            "severity": severity,
            "occurred_at": occurred_at.isoformat(),
            "payload": json.dumps(_with_original_time(item.get("payload"), original)),
            "screenshot_key": item.get("screenshot_key", "") or "",
            "client_event_id": str(item.get("client_event_id", ""))[:64],
        }

        if severity >= IMMEDIATE_SEVERITY:
            _write_immediately(record)
        else:
            pipeline_records.append(record)

        _apply_risk(session.pk, event_type, risk_config)
        _broadcast(record)
        accepted += 1

    if pipeline_records:
        _enqueue_many(settings.PROCTORING["EVENT_STREAM_KEY"], pipeline_records)

    if accepted:
        session_state.increment(session.pk, "events", accepted)
    if skewed:
        # Mashina soati adashgan — bu texnik nosozlik belgisi.
        logger.warning(
            "Sessiya %s: %s/%s hodisada vaqt chegaradan tashqarida edi",
            session.pk, skewed, accepted,
        )

    return accepted


def push_screenshot_meta(
    *,
    session,
    object_key: str,
    kind: str,
    sha256: str,
    size_bytes: int,
    width: int,
    height: int,
    captured_at: datetime,
) -> None:
    """Skrinshot metadata'si — binary allaqachon S3'da."""
    captured_at, _ = clamp_time(captured_at)
    record = {
        "session_id": session.pk,
        "kind": kind,
        "object_key": object_key,
        "sha256": sha256,
        "size_bytes": int(size_bytes or 0),
        "width": int(width or 0),
        "height": int(height or 0),
        "captured_at": captured_at.isoformat(),
    }
    _enqueue(settings.PROCTORING["SCREENSHOT_STREAM_KEY"], record)
    session_state.increment(session.pk, "shots")

    # Ketma-ket bir xil hash — client oldindan yozilgan tasvir uzatayotgan
    # bo'lishi mumkin. Bu eng oson aniqlanadigan spoofing belgisi.
    if sha256:
        check_frozen_frames(session, sha256)


def _apply_risk(session_id: int, event_type: str, config: dict | None) -> None:
    """
    Hodisani xavf balliga qo'shadi.

    ILGARI bu oddiy `bump_risk(delta)` edi va uchta narsa yo'q edi:
    pasayish, takror hisoblashga qarshi oyna va tarkib. Uchalasi ham
    `services/risk.py` da - sabab o'sha modul docstring'ida.

    Xato YUTILADI: ball hisoblanmagani hodisani yo'qotmasligi kerak.
    Hodisa dalil, ball esa tartiblash vositasi.
    """
    try:
        risk_service.apply(
            session_id=session_id,
            event_type=event_type,
            config=config or risk_service.resolve_config(None),
        )
    except Exception:
        logger.warning("Xavf balli yangilanmadi (%s)", event_type, exc_info=True)


# --------------------------------------------------------------------------
# Redis Stream
# --------------------------------------------------------------------------
def _enqueue(stream: str, record: dict) -> None:
    try:
        get_redis().xadd(
            stream,
            record,
            maxlen=settings.PROCTORING["EVENT_STREAM_MAXLEN"],
            approximate=True,
        )
    except Exception as exc:
        # Redis tushsa — hodisani yo'qotgandan ko'ra to'g'ridan-to'g'ri
        # DB'ga yozgan yaxshi (sekinroq, lekin dalil saqlanadi).
        logger.error("Redis stream'ga yozib bo'lmadi, DB'ga o'tilmoqda: %s", exc)
        _write_immediately(record)


def _enqueue_many(stream: str, records: list[dict]) -> None:
    try:
        client = get_redis()
        pipe = client.pipeline()
        for record in records:
            pipe.xadd(
                stream,
                record,
                maxlen=settings.PROCTORING["EVENT_STREAM_MAXLEN"],
                approximate=True,
            )
        pipe.execute()
    except Exception as exc:
        logger.error("Redis batch xatosi, DB'ga o'tilmoqda: %s", exc)
        for record in records:
            _write_immediately(record)


def _write_immediately(record: dict) -> None:
    """
    Kritik hodisa yoki Redis ishlamayotgan holat uchun.

    Xato YUTILMAYDI: yozib bo'lmagan hodisa dead-letter oqimiga
    ko'chiriladi. Ilgari u faqat log'ga chiqib, kritik dalil jimgina
    yo'qolardi.
    """
    from apps.proctoring.services.stream import to_dead_letter

    try:
        ProctoringEvent.objects.create(
            session_id=record["session_id"],
            type=record["type"],
            severity=record["severity"],
            occurred_at=_parse_time(record["occurred_at"]),
            payload=json.loads(record["payload"]) if isinstance(record["payload"], str) else record["payload"],
            screenshot_key=record.get("screenshot_key", ""),
            client_event_id=record.get("client_event_id", ""),
        )
    except Exception as exc:
        logger.exception("Hodisani yozib bo'lmadi: %s", exc)
        to_dead_letter(settings.PROCTORING["EVENT_STREAM_KEY"], record, f"immediate: {exc}")


# --------------------------------------------------------------------------
# Realtime
# --------------------------------------------------------------------------
#: Dashboard'ga uzatiladigan payload kalitlari (oq ro'yxat).
#
# Payload'ni TO'LIQ uzatib bo'lmaydi: uni client to'ldiradi, ya'ni u
# ishonchsiz va cheklanmagan. Buzilgan client har hodisaga bir
# megabaytlik matn qo'shsa, u channel layer'ining `capacity` (2000)
# buferini to'ldirib, BARCHA proktorlarning kanalini o'ldiradi.
#
# Ro'yxatdagi kalitlar — hodisani ekranda bir qatorda tushuntirish
# uchun yetadiganlari: "Client anomaliyasi" degan yorliqning o'zi
# proktorga hech narsa aytmaydi, "Client anomaliyasi — bir xil
# kadrlar" esa aytadi.
_BROADCAST_DETAIL_KEYS = (
    "processes",   # rdp_detected — qaysi dastur
    "count",       # multi_monitor — ekranlar, second_person — odamlar
    "key",         # hotkey_blocked — qaysi kombinatsiya
    "repeats",     # hotkey_blocked — necha marta
    "reason",      # client_anomaly / camera_lost — sabab
    "kind",        # client_anomaly — turi
    "host",        # navigation_blocked — qaysi domen
    "score",       # face_* — ball
    "threshold",   # face_* — chegara
    "faces",       # face_* — nechta yuz
    # --- AI kuzatuv (M3-M5) ---
    "object",      # object_detected — qaysi buyum
    "confidence",  # har qanday AI hodisasi — ishonch (0-100)
    "duration_ms", # temporal hodisa — qancha davom etdi
    "camera_role", # qaysi kamera ko'rdi (primary | secondary)
    "track_id",    # ByteTrack izi — ikkita telefonni ajratish uchun
    "direction",   # looking_away — qaysi tomonga qaradi
    "deviation",   # looking_away — necha gradus
    "rule",        # fusion — qaysi qoida ishladi
    "fused_from",  # fusion — qaysi hodisalardan yig'ildi
    "module",      # proctoring_degraded — qaysi modul o'chdi
    "similarity",  # face_mismatch — etalonga o'xshashlik
    # --- Masofaviy boshqaruv / virtualizatsiya tozalash ---
    #
    # `neutralized` PROKTOR UCHUN HAL QILUVCHI: "AnyDesk topildi va
    # yopildi" bilan "AnyDesk topildi, yopib bo'lmadi" butunlay
    # boshqa vaziyat. Birinchisi bayonnomaga yozuv, ikkinchisi esa
    # darhol aralashuvni talab qiladi — ekran hozir ham boshqa
    # odamga ochiq bo'lishi mumkin.
    "neutralized", # tozalash muvaffaqiyatli bo'ldimi
    "codes",       # qaysi qoidalar ishladi (anydesk, virtualbox...)
    "label",       # dasturning o'qiladigan nomi
    "evidence",    # NEGA shu deb qaror qilindi (imzo, OriginalFilename)
    "service",     # qaysi Windows xizmati
    "process",     # qaysi jarayon
)

#: Bitta matn maydonining eng ko'p uzunligi.
_DETAIL_TEXT_LIMIT = 120

#: Ro'yxatdan nechta element uzatiladi.
_DETAIL_LIST_LIMIT = 5


def _broadcast_detail(raw_payload) -> dict:
    """
    Payload'dan dashboard uchun ixcham tafsilot ajratadi.

    Har bir qiymat turi va uzunligi bo'yicha CHEKLANADI — bu yerda
    client bergan ma'lumot proktorning brauzeriga o'tadi.
    """
    if isinstance(raw_payload, str):
        try:
            payload = json.loads(raw_payload)
        except (TypeError, ValueError):
            return {}
    else:
        payload = raw_payload

    if not isinstance(payload, dict):
        return {}

    detail = {}
    for key in _BROADCAST_DETAIL_KEYS:
        if key not in payload:
            continue
        value = payload[key]
        if isinstance(value, bool) or isinstance(value, (int, float)):
            detail[key] = value
        elif isinstance(value, str):
            detail[key] = value[:_DETAIL_TEXT_LIMIT]
        elif isinstance(value, (list, tuple)):
            detail[key] = [
                str(item)[:_DETAIL_TEXT_LIMIT]
                for item in list(value)[:_DETAIL_LIST_LIMIT]
            ]
    return detail


def _broadcast(record: dict) -> None:
    """
    Proktor dashboard'iga push.

    Faqat sezilarli hodisalar uzatiladi. 10 000 sessiyadan kelayotgan
    HAR BIR hodisani WebSocket'ga yuborish — dashboard'ni ham, Redis
    pub/sub'ni ham yiqitadi. Chegara `MONITOR_MIN_SEVERITY` bilan
    boshqariladi.
    """
    if int(record["severity"]) < settings.PROCTORING["MONITOR_MIN_SEVERITY"]:
        return

    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        layer = get_channel_layer()
        if layer is None:
            return

        zone_id = record.get("zone_id") or 0
        async_to_sync(layer.group_send)(
            f"zone.{zone_id}",
            {
                "type": "proctoring.event",
                "payload": {
                    "session_id": record["session_id"],
                    "event_type": record["type"],
                    "severity": record["severity"],
                    "occurred_at": record["occurred_at"],
                    # Hodisani bir qatorda tushuntiradigan ixcham
                    # tafsilot (oq ro'yxat bo'yicha, cheklangan).
                    "detail": _broadcast_detail(record.get("payload")),
                },
            },
        )
    except Exception as exc:
        # Realtime — qo'shimcha qulaylik, u ishlamasa ham ingest to'xtamasligi
        # kerak. Lekin JIMGINA emas: ilgari xato `debug` da yozilardi va
        # panelda "hodisa kelmayapti" degan shikoyatning sababini log'dan
        # topib bo'lmasdi. Daqiqasiga bittadan ko'p emas — Redis uzilganda
        # har hodisa uchun qator yozish jurnalni to'ldirardi.
        global _last_broadcast_warning
        now = time.monotonic()
        if now - _last_broadcast_warning >= 60:
            _last_broadcast_warning = now
            logger.warning("Panelga uzatilmadi (zone.%s): %s", record.get("zone_id"), exc)


#: Oxirgi `_broadcast` ogohlantirishi (monotonik soat) — log cheklovi.
_last_broadcast_warning = float("-inf")


# --------------------------------------------------------------------------
# Anomaliya aniqlash
# --------------------------------------------------------------------------
def check_frozen_frames(session, sha256: str, threshold: int = 5) -> None:
    """
    Ketma-ket bir xil kadrlarni aniqlaydi.

    Talabgor qimirlamasligi mumkin, lekin JPEG shovqini tufayli hash
    hech qachon aynan bir xil bo'lmaydi. Bir xil hash — bu bitta fayl
    qayta-qayta yuborilayotgani, ya'ni client soxtalashtirilgan.
    """
    client = get_redis()
    key = f"sess:lasthash:{session.pk}"
    try:
        pipe = client.pipeline()
        pipe.get(key)
        pipe.set(key, sha256, ex=600)
        previous, _ = pipe.execute()

        counter_key = f"sess:samehash:{session.pk}"
        if previous == sha256:
            repeats = client.incr(counter_key)
            client.expire(counter_key, 600)
            if repeats == threshold:
                push_event(
                    session_id=session.pk,
                    zone_id=session.zone_id,
                    type=ProctoringEvent.Type.CLIENT_ANOMALY,
                    severity=ProctoringEvent.Severity.CRITICAL,
                    occurred_at=timezone.now(),
                    payload={
                        "reason": "identical_frames",
                        "repeats": repeats,
                        "sha256": sha256[:16],
                    },
                )
        else:
            client.delete(counter_key)
    except Exception as exc:
        logger.debug("Frozen frame tekshiruvi xatosi: %s", exc)


def _parse_time(value) -> datetime:
    if isinstance(value, datetime):
        return value if timezone.is_aware(value) else timezone.make_aware(value)
    if not value:
        return timezone.now()
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return timezone.now()
    return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)


def clamp_time(value) -> tuple[datetime, str | None]:
    """
    Client aytgan vaqtni maqbul oynaga tortadi.

    Nima uchun kerak: `proctoring_event` `occurred_at` bo'yicha kunlik
    partitsiyalangan. Soati noto'g'ri sozlangan bitta mashina 2030-yilni
    yuborsa, o'sha qator uchun partitsiya yo'q va INSERT butun batchni
    yiqitadi — ya'ni bitta buzuq soat butun oqimni to'xtatadi.

    Vaqt TASHLANMAYDI: client aytgan qiymat `payload` ga ko'chiriladi.
    U ham dalil — mashina soati adashganini keyin ko'rish mumkin.

    Qaytaradi: `(chegaraga_tortilgan_vaqt, original_yoki_None)`.
    """
    parsed = _parse_time(value)
    now = timezone.now()

    ceiling = now + timedelta(seconds=settings.PROCTORING["EVENT_MAX_FUTURE_SKEW"])
    floor = now - timedelta(seconds=settings.PROCTORING["EVENT_MAX_BACKFILL"])

    if parsed > ceiling:
        return now, parsed.isoformat()
    if parsed < floor:
        # Oflayn buferdan kelgan haqiqiy eski hodisa bo'lishi mumkin,
        # shuning uchun `now` emas, chegaraning o'ziga qo'yamiz —
        # tartib saqlanadi.
        return floor, parsed.isoformat()
    return parsed, None


def _with_original_time(payload: dict | None, original: str | None) -> dict:
    payload = dict(payload or {})
    if original:
        payload["_client_occurred_at"] = original
    return payload
