"""
Tarmoq qayta urinish siyosati — SOF mantiq (Qt ham, httpx ham yo'q).

NIMA UCHUN ALOHIDA MODUL: bir xil qoida besh joyda kerak (API so'rovi,
hodisalar buferi, skrinshot navbati, WebSocket, WebView qayta
yuklash) va ularning har biri o'zicha "15 s dan keyin qayta" yozsa,
server qayta ishga tushganda 5000 mashina BIR LAHZADA urilib, uni
yana yiqitadi (reconnect storm). Bu yerda uchta qoida bor:

  1. Kechikish eksponensial o'sadi va CHEGARALANGAN (`cap`).
  2. Har kechikishga TASODIFIY qism qo'shiladi (jitter) — bir vaqtda
     uzilgan mashinalar keyin turli paytlarda qaytadi.
  3. Server `Retry-After` desa — undan oldin urinilmaydi.

Modul testlanadi (`tests/test_net_policy.py`), shuning uchun vaqt va
tasodif manbalari parametr.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Callable, Optional

#: `Retry-After` qiymatining yuqori chegarasi (soniya).
#
# Buzilgan yoki noto'g'ri sozlangan proksi "Retry-After: 86400" qaytarishi
# mumkin; unga ko'r-ko'rona ishonish mashinani imtihon davomida bir
# kunga "jim" qilib qo'yardi.
MAX_RETRY_AFTER_S = 300.0

#: Qayta urinishga arziydigan HTTP statuslari.
#
# 408/429 — 4xx ichidagi yagona istisnolar: so'rov o'zi to'g'ri, server
# faqat "hozir emas" demoqda. 502/503/504 — nginx/proksi: backend
# qayta ishga tushmoqda yoki band. 500 ATAYLAB YO'Q: bu serverdagi xato
# va uni takrorlash faqat yuk qo'shadi.
RETRYABLE_STATUSES = frozenset({408, 429, 502, 503, 504})

#: HTTP metodlari, ularni takrorlash xavfsiz (RFC 9110, 9.2.2).
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})


def backoff_delay(
    attempt: int,
    *,
    base: float,
    cap: float,
    rng: Callable[[], float] = random.random,
) -> float:
    """
    `attempt`-urinishdan keyingi kutish (soniya), "equal jitter" bilan.

    Yarmi qat'iy, yarmi tasodifiy: [exp/2, exp]. To'liq tasodifiy
    ("full jitter") ba'zan ~0 beradi — uzilgan tarmoqda bu deyarli
    darhol qayta urinish va sikl degani; yarmi qat'iy bo'lsa pastki
    chegara kafolatlangan.
    """
    attempt = max(0, int(attempt))
    # 2**attempt katta sonlarda float'ni to'ldirmasin — chegaradan
    # keyin baribir `cap`.
    exp = cap if attempt >= 32 else min(cap, base * (2 ** attempt))
    exp = max(0.0, exp)
    return exp / 2.0 + rng() * exp / 2.0


def parse_retry_after(value, *, now: Optional[float] = None,
                      limit: float = MAX_RETRY_AFTER_S) -> Optional[float]:
    """
    `Retry-After` sarlavhasini soniyaga o'giradi (`None` — yo'q/yaroqsiz).

    Ikki shakl (RFC 9110, 10.2.3): butun soniya yoki HTTP-sana. Natija
    `[0, limit]` oralig'iga qisiladi.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        seconds = float(text)
    except ValueError:
        try:
            moment = parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError):
            return None
        if moment is None:
            return None
        current = time.time() if now is None else now
        seconds = moment.timestamp() - current
    if seconds != seconds:  # NaN
        return None
    return max(0.0, min(float(limit), seconds))


def is_retryable_status(status: int) -> bool:
    return int(status or 0) in RETRYABLE_STATUSES


#: Server so'rov TANASINI rad etgan statuslar (validatsiya, hajm, tur).
POISON_STATUSES = frozenset({400, 413, 415, 422})


def is_poison_payload(status: int) -> bool:
    """
    Element o'zi yaroqsiz — takrorlash natijani o'zgartirmaydi.

    Navbatlar (hodisa, skrinshot) uchun muhim: bunday elementni navbat
    boshiga qaytarish uni "zaharli" qiladi — orqasidagi hamma narsa
    abadiy kutib qoladi.

    Qolgan 4xx ATAYLAB bu yerda EMAS: 401 — token (refresh hal qiladi),
    403 `ip_not_allowed` — bino zaxira kanalga o'tgan bo'lishi mumkin,
    409/404 — holat. Ularda element to'g'ri, muhit vaqtincha noto'g'ri;
    tashlab yuborish dalilni yo'qotardi.
    """
    return int(status or 0) in POISON_STATUSES


@dataclass
class Backoff:
    """
    Davriy yuboruvchining holati: ketma-ket xatolar soni va keyingi ruxsat.

    Ishlatilishi:

        delay = backoff.failure(retry_after)   # xatodan keyin
        if backoff.ready(): ...                # yuborish mumkinmi
        backoff.success()                      # muvaffaqiyat — nolga
    """

    base: float
    cap: float
    rng: Callable[[], float] = field(default=random.random, repr=False)
    clock: Callable[[], float] = field(default=time.monotonic, repr=False)
    failures: int = 0
    not_before: float = 0.0

    def failure(self, retry_after: Optional[float] = None) -> float:
        """Xatoni qayd etadi va keyingi urinishgacha kutishni qaytaradi."""
        delay = backoff_delay(self.failures, base=self.base, cap=self.cap, rng=self.rng)
        self.failures += 1
        if retry_after is not None:
            # Server aytgan muddatdan OLDIN emas; ustiga kichik jitter —
            # hammaga bir xil `Retry-After` berilgan bo'lsa ham ular
            # bir soniyada qaytib kelmasin.
            delay = max(delay, float(retry_after) + self.rng() * min(5.0, self.base))
        self.not_before = self.clock() + delay
        return delay

    def success(self) -> None:
        self.failures = 0
        self.not_before = 0.0

    def ready(self) -> bool:
        return self.clock() >= self.not_before

    def remaining(self) -> float:
        return max(0.0, self.not_before - self.clock())

    def nudge(self, within: float) -> None:
        """
        Kutishni QISQARTIRADI (uzaytirmaydi): `within` soniya ichida,
        tasodifiy paytda.

        Aloqa tiklangani boshqa kanaldan bilinganda (heartbeat o'tdi,
        kompyuter uyqudan uyg'ondi) navbat bir daqiqa kutmasligi kerak
        — lekin 5000 mashina ham BIR LAHZADA yubormasligi kerak.
        """
        target = self.clock() + self.rng() * max(0.0, within)
        if self.not_before > target:
            self.not_before = target
