"""
Sessiyaning "issiq" holati — Redis'da.

Nima uchun DB'da emas: 10 000 talaba har 30 soniyada heartbeat yuborsa,
bu 333 UPDATE/s. Har bir UPDATE — WAL yozuvi, indeks yangilanishi,
autovacuum yuki. Redis'da bu bepul, DB'ga esa har 10 soniyada bitta
batch bilan ko'chiriladi (write-behind).

Muhim istisno: KRITIK hodisalar (chetlashtirish, yuz tekshiruvidan
o'tmaslik) write-behind EMAS, darhol DB'ga yoziladi. "Chalkashlik"
ma'lumoti yo'qolsa mayli, "dalil" yo'qolmasligi kerak.
"""

from __future__ import annotations

import json
import time

from django.conf import settings

from apps.common.redis_client import acquire_lock, get_redis, release_lock

_PREFIX = "sess"


# --------------------------------------------------------------------------
# Kalitlar
# --------------------------------------------------------------------------
def token_key(token_hash: str) -> str:
    return f"{_PREFIX}:tok:{token_hash}"


def state_key(session_id: int) -> str:
    return f"{_PREFIX}:st:{session_id}"


def dirty_set_key() -> str:
    return f"{_PREFIX}:dirty"


def candidate_lock_key(pinfl: str, exam_id: int) -> str:
    # JSHSHIR Redis kalitiga OCHIQ yozilmaydi — kalitlar `SCAN` bilan
    # ro'yxatlanadi va monitoring vositalarida ko'rinadi.
    from apps.common.utils.crypto import opaque_key

    return f"{_PREFIX}:lock:{opaque_key(pinfl)}:{exam_id}"


def pending_key(challenge: str) -> str:
    return f"{_PREFIX}:pending:{challenge}"


def zone_online_key(zone_id: int) -> str:
    return f"{_PREFIX}:online:{zone_id}"


# --------------------------------------------------------------------------
# Sessiya tokeni -> sessiya
# --------------------------------------------------------------------------
def store_session_token(*, token_hash: str, payload: dict, ttl: int | None = None) -> None:
    """
    Token -> sessiya xaritasi.

    Opaque token (JWT emas) ataylab tanlangan: proktor talabgorni
    chetlashtirsa, kirish huquqi O'SHA SONIYADA o'chishi kerak. JWT'ni
    bekor qilib bo'lmaydi.
    """
    ttl = ttl or settings.PROCTORING["SESSION_TOKEN_TTL"]
    get_redis().set(token_key(token_hash), json.dumps(payload), ex=ttl)


def resolve_session_token(token_hash: str) -> dict | None:
    raw = get_redis().get(token_key(token_hash))
    return json.loads(raw) if raw else None


def revoke_session_token(token_hash: str) -> None:
    get_redis().delete(token_key(token_hash))


# --------------------------------------------------------------------------
# Pending sessiya (JSHSHIR tekshirildi, FaceID hali emas)
# --------------------------------------------------------------------------
def store_pending(challenge: str, payload: dict) -> None:
    get_redis().set(
        pending_key(challenge),
        json.dumps(payload),
        ex=settings.PROCTORING["PENDING_SESSION_TTL"],
    )


def peek_pending(challenge: str) -> dict | None:
    """
    O'qiydi, lekin O'CHIRMAYDI.

    Kirishdagi muvaffaqiyatsiz urinishni yozish uchun kerak: urinish
    challenge'ni sarflamasligi kerak, aks holda birinchi "mos kelmadi"
    dan keyin talabgor qaytadan JSHSHIR kiritishga majbur bo'lardi -
    holbuki qayta urinish aynan kutilgan xulq (yorug'lik, ko'zoynak,
    bosh burilishi).
    """
    raw = get_redis().get(pending_key(challenge))
    return json.loads(raw) if raw else None


def consume_pending(challenge: str) -> dict | None:
    """Bir martalik: o'qiydi va darhol o'chiradi."""
    client = get_redis()
    pipe = client.pipeline()
    pipe.get(pending_key(challenge))
    pipe.delete(pending_key(challenge))
    raw, _ = pipe.execute()
    return json.loads(raw) if raw else None


# --------------------------------------------------------------------------
# "Bitta talabgor = bitta faol sessiya" qulfi
# --------------------------------------------------------------------------
def lock_candidate(pinfl: str, exam_id: int, owner: str, ttl: int | None = None) -> bool:
    """
    "Do'stim mening o'rnimga topshiradi" hujumini yopadi.

    Atomik SETNX: ikkita kompyuterdan bir vaqtda urinilsa, faqat bittasi
    o'tadi. Bu tekshiruvni Python'da qilish (`if not exists: set`) race
    condition beradi.
    """
    return acquire_lock(
        candidate_lock_key(pinfl, exam_id),
        owner,
        ttl or settings.PROCTORING["SESSION_TOKEN_TTL"],
    )


def unlock_candidate(pinfl: str, exam_id: int, owner: str) -> None:
    release_lock(candidate_lock_key(pinfl, exam_id), owner)


# --------------------------------------------------------------------------
# Issiq holat (heartbeat, hisoblagichlar)
# --------------------------------------------------------------------------
def touch_heartbeat(session_id: int, *, zone_id: int | None = None, extra: dict | None = None) -> None:
    """
    Heartbeat — DB'ga TEGMAYDI.

    Faqat Redis HASH yangilanadi va sessiya "dirty" to'plamiga qo'shiladi;
    Celery uni 10 soniyada bir marta DB'ga ko'chiradi.
    """
    client = get_redis()
    now = int(time.time())
    key = state_key(session_id)

    pipe = client.pipeline()
    mapping = {"hb": now}
    if extra:
        mapping.update({key_: _encode(value) for key_, value in extra.items()})
    pipe.hset(key, mapping=mapping)
    pipe.expire(key, settings.PROCTORING["SESSION_TOKEN_TTL"])
    pipe.sadd(dirty_set_key(), session_id)
    if zone_id is not None:
        # Bino bo'yicha "online" ro'yxati — dashboard shundan o'qiydi.
        pipe.zadd(zone_online_key(zone_id), {str(session_id): now})
        pipe.expire(zone_online_key(zone_id), 3600)
    pipe.execute()


def increment(session_id: int, field: str, amount: int = 1) -> int:
    """Hisoblagichni oshiradi (event_count, face_fail_count, ...)."""
    client = get_redis()
    key = state_key(session_id)
    pipe = client.pipeline()
    pipe.hincrby(key, field, amount)
    pipe.expire(key, settings.PROCTORING["SESSION_TOKEN_TTL"])
    pipe.sadd(dirty_set_key(), session_id)
    value, _, _ = pipe.execute()
    return int(value)


def reset_counter(session_id: int, field: str) -> None:
    """Hisoblagichni nolga qaytaradi (masalan muvaffaqiyatli FaceID'dan keyin)."""
    client = get_redis()
    pipe = client.pipeline()
    pipe.hset(state_key(session_id), field, 0)
    pipe.sadd(dirty_set_key(), session_id)
    pipe.execute()


def bump_risk(session_id: int, delta: int) -> int:
    """
    Xavf ballini oshiradi (0–100 oralig'ida).

    Proktor 10 000 sessiyani ko'ra olmaydi — u eng xavflilarini ko'rishi
    kerak. Shu ball tartiblash uchun ishlatiladi.
    """
    value = increment(session_id, "risk", delta)
    if value > 100:
        get_redis().hset(state_key(session_id), "risk", 100)
        return 100
    return value


def get_state(session_id: int) -> dict:
    raw = get_redis().hgetall(state_key(session_id))
    return {key: _coerce(value) for key, value in raw.items()}


def get_states(session_ids: list[int]) -> dict[int, dict]:
    """Bir nechta sessiya holatini bitta round-trip'da oladi (dashboard uchun)."""
    if not session_ids:
        return {}
    client = get_redis()
    pipe = client.pipeline()
    for session_id in session_ids:
        pipe.hgetall(state_key(session_id))
    results = pipe.execute()
    return {
        session_id: {key: _coerce(value) for key, value in raw.items()}
        for session_id, raw in zip(session_ids, results)
    }


def drain_dirty(limit: int = 5000) -> list[int]:
    """Yangilangan sessiyalar ro'yxatini oladi va to'plamni tozalaydi."""
    client = get_redis()
    pipe = client.pipeline()
    pipe.smembers(dirty_set_key())
    pipe.delete(dirty_set_key())
    members, _ = pipe.execute()
    return [int(item) for item in list(members)[:limit]]


def clear_state(session_id: int, zone_id: int | None = None) -> None:
    client = get_redis()
    pipe = client.pipeline()
    pipe.delete(state_key(session_id))
    pipe.srem(dirty_set_key(), session_id)
    if zone_id is not None:
        pipe.zrem(zone_online_key(zone_id), str(session_id))
    pipe.execute()


def _encode(value):
    """
    Redis faqat str/bytes/int/float qabul qiladi.

    `bool` ni ataylab `int` ga aylantiramiz — u `isinstance(v, int)` ga
    to'g'ri keladi, lekin redis-py uni rad etadi va `DataError` beradi.
    """
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value)
    if value is None:
        return ""
    return value


def _coerce(value: str):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value
