"""
Xavf balli: to'planish, pasayish va TUSHUNTIRISH.

Ilgari ball oddiy hisoblagich edi: `bump_risk(session_id, delta)` uni
oshirar va 100 da to'xtardi. Uchta muammo bor edi va uchalasi ham
chetlashtirish qarorini asossiz qilardi:

  1. PASAYMASDI. Imtihon boshida bir marta oyna fokusini yo'qotgan
     talabgor uch soat davomida o'sha ball bilan yurardi. Uzoq
     imtihonda deyarli hamma "yuqori xavf" bo'lib chiqardi va
     ro'yxat ma'nosini yo'qotardi.
  2. TAKROR SANARDI. Kamera burchagi noto'g'ri bo'lgani uchun yuz
     vaqti-vaqti bilan yo'qolsa, har yo'qolish ball qo'shardi va
     TEXNIK nosozlik talabgorning aybiga aylanardi.
  3. TUSHUNTIRMASDI. Proktor "72" ni ko'rardi va boshqa hech narsa.
     Chetlashtirish esa asoslanishi kerak: "72 ball, shundan 40 tasi
     telefon" — bu tekshirib bo'ladigan da'vo, "72" esa yo'q.

Bu modul uchalasini ham yopadi.

BALL PASAYISHI LAZY hisoblanadi. Fon vazifasi YO'Q: har 10 soniyada
10 000 sessiyaning ballini kamaytirish bekorga yuk bo'lardi. O'rniga
oxirgi o'zgarish vaqti saqlanadi va pasayish O'QILGANDA yoki
KEYINGI qo'shilganda hisoblanadi. Natija bir xil, xarajat nol.
"""

from __future__ import annotations

import logging
import time

from django.conf import settings

from apps.common.redis_client import get_redis
from apps.proctoring.services import state as session_state

logger = logging.getLogger(__name__)

#: Ball tarkibi shu hash'da: `{hodisa_turi: ball}`.
_BREAKDOWN = "sess:risk"

#: Takror hisoblashga qarshi qulf: `sess:rcd:{sessiya}:{tur}`.
_COOLDOWN = "sess:rcd"

#: Ball va uning oxirgi o'zgarish vaqti `sess:st:{id}` hash'ida
#: (`risk` va `risk_at` maydonlari) — ular allaqachon flush
#: qilinadigan holatda va alohida kalit keraksiz round-trip
#: bo'lardi.
_RISK_FIELD = "risk"
_RISK_AT_FIELD = "risk_at"


def breakdown_key(session_id: int) -> str:
    return "{}:{}".format(_BREAKDOWN, session_id)


def cooldown_key(session_id: int, event_type: str) -> str:
    return "{}:{}:{}".format(_COOLDOWN, session_id, event_type)


# --------------------------------------------------------------------------
def resolve_config(policy: dict | None) -> dict:
    """
    Siyosatdan risk sozlamalarini ajratadi.

    Siyosat yo'q bo'lsa standart qiymatlar — `_default_proctoring`
    dagilar bilan bir xil bo'lishi SHART, aks holda sozlanmagan
    tizim boshqacha ishlardi.
    """
    risk = (policy or {}).get("risk") or {}
    return {
        "decay_per_min": int(risk.get("decay_per_min", 5) or 0),
        "cooldown_s": int(risk.get("cooldown_s", 60) or 0),
        "low": int(risk.get("low", 20)),
        "medium": int(risk.get("medium", 40)),
        "high": int(risk.get("high", 70)),
    }


def weight_for(event_type: str) -> int:
    """
    Hodisa og'irligi: avval DB, keyin koddagi zaxira.

    DB jadvali (`EventRiskWeight`) bo'sh bo'lsa — bu "og'irlik yo'q"
    degani EMAS. Sozlanmagan tizim ballni umuman hisoblamasa,
    chetlashtirish qarori asossiz qolardi. Shuning uchun
    `ingest.RISK_WEIGHTS` zaxira sifatida saqlanadi.
    """
    from apps.controls.services import risk_weight_map
    from apps.proctoring.services.ingest import RISK_WEIGHTS

    try:
        configured = risk_weight_map()
    except Exception:
        # Kesh yoki DB javob bermadi — zaxira baribir ishlaydi.
        logger.warning("Xavf og'irliklarini o'qib bo'lmadi", exc_info=True)
        configured = {}

    if event_type in configured:
        return int(configured[event_type])
    return int(RISK_WEIGHTS.get(event_type, 1))


def cooldown_for(event_type: str, config: dict) -> int:
    """
    Takror oralig'i: avval TURNIKI, keyin siyosatdagi umumiy qiymat.

    Hodisa turlarining tabiati har xil va bitta umumiy son ularni
    sozlashga imkon bermasdi: `window_blur`/`looking_away` tez-tez
    takrorlanadigan shovqin (uzun oyna kerak, aks holda ball shular
    hisobiga to'ladi), telefon yoki ikkinchi odam esa kam va jiddiy
    (qisqa oyna kerak - ikki daqiqada ikki marta telefon chiqarish
    ikki alohida fakt).

    Turga berilgan qiymat siyosatdagi `0` (cooldown o'chirilgan) dan
    ham USTUN: u aniq tur uchun ongli ravishda qo'yilgan qaror.
    Jadvalni o'qib bo'lmasa siyosat qiymati ishlaydi - `weight_for`
    dagi bilan bir xil qoida.
    """
    from apps.controls.services import risk_cooldown_map

    try:
        per_type = risk_cooldown_map()
    except Exception:
        logger.warning("Hodisa cooldown'larini o'qib bo'lmadi", exc_info=True)
        per_type = {}

    if event_type in per_type:
        return int(per_type[event_type])
    return int(config.get("cooldown_s") or 0)


# --------------------------------------------------------------------------
def apply(
    *,
    session_id: int,
    event_type: str,
    config: dict,
    weight: int | None = None,
    now: float | None = None,
) -> int:
    """
    Hodisani ballga qo'shadi. Yangi ballni qaytaradi.

    Takroriy hodisa COOLDOWN oynasi ichida ballga QO'SHILMAYDI,
    lekin hodisaning o'zi baribir yoziladi — dalil yo'qolmaydi,
    faqat ball ikki marta sanalmaydi.

    IKKI SOAT ISHLATILADI va buni bilish kerak:

        pasayish  -> `now` parametri (sinash uchun almashtiriladi)
        cooldown  -> Redis TTL (HAQIQIY soat)

    Cooldown ataylab TTL'da qoldirilgan: u atomik bo'lishi shart.
    Bir vaqtda kelgan ikkita bir xil hodisadan faqat bittasi
    ballga qo'shilishi kerak va buni Python'dagi vaqt solishtirish
    kafolatlay olmaydi (poyga). Ishlab chiqarishda ikkala soat ham
    bir xil, farq faqat testda ko'rinadi.
    """
    points = weight_for(event_type) if weight is None else int(weight)
    if points <= 0:
        return current(session_id=session_id, config=config, now=now)

    cooldown = cooldown_for(event_type, config)
    if cooldown > 0 and not _acquire_cooldown(session_id, event_type, cooldown):
        return current(session_id=session_id, config=config, now=now)

    return _add(session_id=session_id, event_type=event_type,
                points=points, config=config, now=now)


def current(*, session_id: int, config: dict, now: float | None = None) -> int:
    """
    Ballning HOZIRGI qiymati (pasayish hisobga olingan).

    Redis'dagi xom qiymat eskirgan bo'lishi mumkin: u oxirgi
    hodisadan beri o'zgarmagan, vaqt esa o'tgan.
    """
    return current_from_state(session_state.get_state(session_id), config=config, now=now)


def current_from_state(raw: dict, *, config: dict, now: float | None = None) -> int:
    """
    `current` ning Redis'ga bormaydigan varianti — holat allaqachon o'qilgan.

    `flush_session_state` 5000 sessiya holatini BITTA pipeline bilan
    oladi; ilgari u har sessiya uchun `current` orqali o'sha hash'ni
    yana bir marta o'qirdi (5000 qo'shimcha round-trip har 10 s da).
    """
    return _decayed(
        value=int(raw.get(_RISK_FIELD) or 0),
        updated_at=float(raw.get(_RISK_AT_FIELD) or 0),
        decay_per_min=int(config.get("decay_per_min") or 0),
        now=now or time.time(),
    )


def breakdown(session_id: int) -> dict:
    """`{hodisa_turi: ball}` — ballning tarkibi."""
    try:
        raw = get_redis().hgetall(breakdown_key(session_id))
    except Exception:
        logger.debug("Ball tarkibini o'qib bo'lmadi", exc_info=True)
        return {}
    return _parse_breakdown(raw)


def breakdowns(session_ids: list[int]) -> dict[int, dict]:
    """
    Bir nechta sessiya tarkibi BITTA pipeline'da (`flush_session_state`).

    Redis yiqilsa bo'sh lug'atlar — `breakdown` bilan bir xil yumshoq xulq.
    """
    if not session_ids:
        return {}
    try:
        pipe = get_redis().pipeline(transaction=False)
        for session_id in session_ids:
            pipe.hgetall(breakdown_key(session_id))
        results = pipe.execute()
    except Exception:
        logger.debug("Ball tarkiblarini o'qib bo'lmadi", exc_info=True)
        return {session_id: {} for session_id in session_ids}
    return {
        session_id: _parse_breakdown(raw) for session_id, raw in zip(session_ids, results)
    }


def _parse_breakdown(raw) -> dict:
    result = {}
    for key, value in (raw or {}).items():
        try:
            result[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return result


def level(score: int, config: dict) -> str:
    """Ball -> daraja. Chegaralar siyosatdan."""
    if score >= int(config.get("high", 70)):
        return "high"
    if score >= int(config.get("medium", 40)):
        return "medium"
    if score >= int(config.get("low", 20)):
        return "low"
    return "normal"


def clear(session_id: int) -> None:
    try:
        get_redis().delete(breakdown_key(session_id))
    except Exception:
        logger.debug("Ball tarkibini o'chirib bo'lmadi", exc_info=True)


# --------------------------------------------------------------------------
def _acquire_cooldown(session_id: int, event_type: str, seconds: int) -> bool:
    """
    Shu tur uchun oyna ochiqmi.

    Atomik `SET NX`: bir vaqtda kelgan ikkita bir xil hodisadan
    faqat bittasi ballga qo'shiladi. Python'da tekshirish
    (`if not exists: set`) poyga beradi va ikkalasi ham o'tardi.

    Redis yo'q bo'lsa — RUXSAT beriladi. Cooldown optimizatsiya,
    uning ishlamasligi ballni biroz oshiradi; taqiqlash esa
    ballni umuman hisoblamas edi.
    """
    try:
        return bool(
            get_redis().set(cooldown_key(session_id, event_type), "1", ex=seconds, nx=True)
        )
    except Exception:
        logger.debug("Cooldown tekshirib bo'lmadi", exc_info=True)
        return True


def _add(*, session_id: int, event_type: str, points: int,
         config: dict, now: float | None) -> int:
    """Pasayishni qo'llab, ballni oshiradi va tarkibini yozadi."""
    now = now or time.time()
    decay_per_min = int(config.get("decay_per_min") or 0)

    try:
        client = get_redis()
        key = session_state.state_key(session_id)
        raw = client.hmget(key, _RISK_FIELD, _RISK_AT_FIELD)
        previous = int(raw[0] or 0) if raw else 0
        updated_at = float(raw[1] or 0) if raw and len(raw) > 1 else 0.0

        decayed = _decayed(
            value=previous, updated_at=updated_at, decay_per_min=decay_per_min, now=now
        )
        value = max(0, min(100, decayed + points))

        ttl = settings.PROCTORING["SESSION_TOKEN_TTL"]
        pipe = client.pipeline()
        pipe.hset(key, mapping={_RISK_FIELD: value, _RISK_AT_FIELD: int(now)})
        pipe.expire(key, ttl)
        # Tarkib PASAYMAYDI - u "nima bo'lgan" degan savolga javob
        # beradi, "hozir qanchalik xavfli" degan savolga emas.
        # Pasaytirilsa, apellyatsiyada "40 ball telefon uchun edi"
        # degan da'voni tasdiqlab bo'lmasdi.
        pipe.hincrby(breakdown_key(session_id), event_type, points)
        pipe.expire(breakdown_key(session_id), ttl)
        pipe.sadd(session_state.dirty_set_key(), session_id)
        pipe.execute()
        return value
    except Exception:
        # Redis tushsa ball yo'qoladi, lekin HODISA yo'qolmaydi -
        # u DB'ga yoziladi va bal keyinchalik qayta hisoblanishi
        # mumkin. Oqimni to'xtatish esa dalilni yo'qotardi.
        logger.warning("Xavf ballini yangilab bo'lmadi", exc_info=True)
        return 0


def _decayed(*, value: int, updated_at: float, decay_per_min: int, now: float) -> int:
    """
    Vaqt o'tishi bilan pasaygan ball.

    `updated_at` nol bo'lsa (eski sessiya, migratsiyagacha yozilgan)
    pasayish QO'LLANMAYDI: noma'lum vaqtdan pasaytirish ballni
    asossiz nolga tushirardi.
    """
    if value <= 0 or decay_per_min <= 0 or updated_at <= 0:
        return max(0, value)
    minutes = max(0.0, (now - updated_at) / 60.0)
    return max(0, int(round(value - decay_per_min * minutes)))
