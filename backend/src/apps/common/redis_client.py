"""
Xom Redis klienti — django-redis cache'idan alohida.

Nima uchun alohida: sessiya holati, heartbeat, event stream va nonce'lar
cache emas — ular *holat*. Cache `IGNORE_EXCEPTIONS=True` bilan ishlaydi va
jimgina `None` qaytarishi mumkin; holat uchun bu qabul qilib bo'lmaydi.
"""

from __future__ import annotations

import functools
import threading

import redis
from django.conf import settings

_lock = threading.Lock()
_pool: redis.ConnectionPool | None = None


def get_redis() -> redis.Redis:
    """
    Process bo'yicha yagona connection pool.

    Har so'rovda yangi ulanish ochish 1000 rps'da Redis'ni file descriptor
    bilan to'ldiradi — shuning uchun pool majburiy.
    """
    global _pool
    if _pool is None:
        with _lock:
            if _pool is None:
                _pool = redis.ConnectionPool.from_url(
                    settings.REDIS_STATE_URL,
                    max_connections=200,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                    socket_keepalive=True,
                    health_check_interval=30,
                    retry_on_timeout=True,
                    decode_responses=True,
                )
    return redis.Redis(connection_pool=_pool)


def reset_pool() -> None:
    """Testlar va fork'dan keyin (Celery worker) chaqiriladi."""
    global _pool
    with _lock:
        if _pool is not None:
            _pool.disconnect()
        _pool = None


# --------------------------------------------------------------------------
# Lua skriptlari — atomiklik uchun
# --------------------------------------------------------------------------
# Bitta JSHSHIR uchun bitta faol sessiya. SETNX + TTL bitta atomik amalda;
# aks holda ikkita kompyuter bir vaqtda tekshirsa, ikkalasi ham o'tib ketadi.
_ACQUIRE_LOCK_LUA = """
local current = redis.call('GET', KEYS[1])
if current == false then
    redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
    return 1
elseif current == ARGV[1] then
    redis.call('EXPIRE', KEYS[1], ARGV[2])
    return 1
else
    return 0
end
"""


@functools.lru_cache(maxsize=None)
def _script(source: str):
    return get_redis().register_script(source)


def acquire_lock(key: str, owner: str, ttl: int) -> bool:
    """Qulfni egallaydi yoki o'zi egasi bo'lsa TTL'ni uzaytiradi."""
    return bool(_script(_ACQUIRE_LOCK_LUA)(keys=[key], args=[owner, ttl]))


def release_lock(key: str, owner: str) -> None:
    client = get_redis()
    if client.get(key) == owner:
        client.delete(key)
