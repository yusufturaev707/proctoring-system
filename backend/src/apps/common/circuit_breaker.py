"""
Redis'ga tayangan circuit breaker.

Nima uchun Redis'da, process xotirasida emas: 16 ta gunicorn worker bo'lsa,
har biri o'z holatini yuritadi va tashqi API allaqachon o'lgan bo'lsa ham
har bir worker uni yana 10 marta urib ko'radi. Umumiy holat esa birinchi
worker aniqlagan uzilishni qolganlariga darhol e'lon qiladi.

Holatlar:
    CLOSED    — normal
    OPEN      — chaqiruvlar darhol rad etiladi (tashqi API'ga tegilmaydi)
    HALF_OPEN — bitta sinov chaqiruvi o'tkaziladi
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from apps.common.redis_client import get_redis

logger = logging.getLogger(__name__)

CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """Zanjir ochiq — chaqiruv umuman qilinmadi."""


@dataclass(slots=True)
class CircuitBreaker:
    name: str
    fail_threshold: int = 10
    window: int = 60
    reset_timeout: int = 30

    @property
    def _state_key(self) -> str:
        return f"cb:{self.name}:state"

    @property
    def _fail_key(self) -> str:
        return f"cb:{self.name}:fails"

    @property
    def _probe_key(self) -> str:
        return f"cb:{self.name}:probe"

    def allow(self) -> bool:
        client = get_redis()
        if client.get(self._state_key) != OPEN:
            return True
        # OPEN: faqat bitta worker sinov chaqiruvini o'tkazsin.
        return bool(client.set(self._probe_key, "1", nx=True, ex=self.reset_timeout))

    def record_success(self) -> None:
        client = get_redis()
        pipe = client.pipeline()
        pipe.delete(self._state_key)
        pipe.delete(self._fail_key)
        pipe.delete(self._probe_key)
        pipe.execute()

    def record_failure(self) -> None:
        client = get_redis()
        pipe = client.pipeline()
        pipe.incr(self._fail_key)
        pipe.expire(self._fail_key, self.window)
        failures, _ = pipe.execute()

        if int(failures) >= self.fail_threshold:
            client.set(self._state_key, OPEN, ex=self.reset_timeout)
            logger.error(
                "Circuit breaker '%s' OCHILDI (%s xato / %ss oynada)",
                self.name, failures, self.window,
            )

    def snapshot(self) -> dict:
        client = get_redis()
        return {
            "name": self.name,
            "state": OPEN if client.get(self._state_key) == OPEN else CLOSED,
            "failures": int(client.get(self._fail_key) or 0),
            "threshold": self.fail_threshold,
            "checked_at": time.time(),
        }

    def call(self, func, *args, **kwargs):
        """Funksiyani zanjir himoyasi ostida bajaradi."""
        if not self.allow():
            raise CircuitOpenError(f"Circuit '{self.name}' ochiq")
        try:
            result = func(*args, **kwargs)
        except Exception:
            self.record_failure()
            raise
        self.record_success()
        return result
