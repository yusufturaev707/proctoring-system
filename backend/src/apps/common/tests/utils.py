"""
Testlar uchun umumiy yordamchilar.

`test*.py` shabloniga tushmaydi, ya'ni test discovery uni test moduli
deb hisoblamaydi.
"""

from __future__ import annotations

import unittest


def redis_available() -> bool:
    """Test Redis'i (15-baza) ishlayaptimi."""
    try:
        from apps.common.redis_client import get_redis

        get_redis().ping()
        return True
    except Exception:
        return False


class RedisStateMixin:
    """
    Xom Redis'ga tayanadigan testlar uchun.

    Ikki narsani qiladi:

      * Redis yo'q bo'lsa testni O'TKAZIB YUBORADI (skip), yiqitmaydi.
        Suite Redis'siz mashinada ham to'liq ishga tushishi kerak —
        aks holda uni hech kim ishga tushirmaydi.
      * Har testdan oldin test bazasini tozalaydi. `TestCase` DB
        tranzaksiyasini qaytaradi, Redis esa holatni SAQLAB QOLADI va
        testlar bir-birining hisoblagichini ko'radi.

    Baza `config.settings.test` da 15-ga o'rnatilgan — dev muhitidagi
    jonli sessiyalar (2-baza) tegilmaydi.
    """

    def setUp(self):
        super().setUp()
        if not redis_available():
            raise unittest.SkipTest("Redis mavjud emas — test o'tkazib yuborildi")
        self._flush_state()
        self.addCleanup(self._flush_state)

    @staticmethod
    def _flush_state() -> None:
        from django.conf import settings

        from apps.common.redis_client import get_redis

        # Qo'shimcha xavfsizlik: faqat 15-bazani tozalaymiz. Sozlama
        # noto'g'ri bo'lsa (masalan kimdir `REDIS_STATE_URL` ni dev
        # bazasiga qaytarsa) test to'plami ma'lumot o'chirmasligi kerak.
        if not str(settings.REDIS_STATE_URL).rstrip("/").endswith("/15"):
            raise AssertionError(
                "REDIS_STATE_URL test bazasiga (15) yo'naltirilmagan: "
                f"{settings.REDIS_STATE_URL}"
            )
        get_redis().flushdb()
