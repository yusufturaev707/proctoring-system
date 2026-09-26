"""
Temporal tasdiqlash — butun tizimning markaziy qoidasi.

BITTA KADR HECH QACHON QAROR EMAS.

Bu shior emas, aniq muhandislik qarori. Detektorlar shovqin
beradi: blur, yorug'lik chaqnashi, qo'lning bir zumlik harakati,
modelning tasodifiy xatosi. Har bir aniqlanishni hodisaga
aylantirish ikki oqibatga olib keladi va ikkalasi ham qimmat:

  * AYBSIZ TALABGOR ayblanadi. Proktorlikda bu eng qimmat xato
    turi - u apellyatsiya, tergov va obro'ga zarar demakdir;
  * dalil oqimi shovqinga ko'miladi. 100 kadr ko'ringan telefon
    100 ta yozuv bo'lsa, proktor ular orasidagi haqiqiy hodisani
    ko'rmaydi.

QANDAY ISHLAYDI. Har bir "shart" (masalan "telefon #7 kadrda")
kuzatiladi va u TASDIQLANISHI uchun uchta talabga birdan javob
berishi kerak:

    ketma-ket kadr soni  >=  min_frames
    davomiyligi          >=  min_duration_ms
    o'rtacha ishonch     >=  min_confidence

Uchalasi ham kerak va ular bir-birini almashtirmaydi: yuqori
FPS da 5 kadr 0.2 soniya (juda qisqa), past FPS da esa 5 kadr
2 soniya (yetarli). Faqat kadr soniga tayanish CPU rejimida
hodisani cheksiz kechiktirardi; faqat vaqtga tayanish esa bitta
tasodifiy aniqlanishni 2 soniya ushlab turib, tasdiqlab
yuborardi.

TASDIQLANGACH SHART OCHIQ QOLADI va yangi hodisa TUG'ILMAYDI.
U faqat shart YO'QOLGANDA yopiladi - va o'shanda ham darhol
emas: `release_ms` oynasi obyekt qisman berkilganda (qo'l
telefonni yopganda) izni saqlab qoladi.

MODUL HODISA TURINI BILMAYDI. U "shart tasdiqlandi" deydi;
qaysi hodisa turi va qanday jiddiylik - `behavior_analyzer.py`
ning ishi.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class Condition:
    """
    Bitta shartning kuzatuv qoidalari.

    `key` — shartning O'ZGARMAS identifikatori. Obyektlar uchun u
    `track_id` ni o'z ichiga oladi (`object:7:cell phone`), ya'ni
    ikkita telefon ikkita alohida shart bo'ladi. Yagona kalit
    ishlatilsa, ikkinchi telefon birinchisining hodisasiga
    qo'shilib ketardi.
    """

    key: str
    min_frames: int = 5
    min_duration_ms: int = 1200
    min_confidence: float = 0.0
    #: Shart yo'qolgach shuncha ms kutiladi (qisman berkilish).
    release_ms: int = 800
    #: Hodisaga qo'shiladigan o'zgarmas ma'lumot (tur, klass nomi).
    meta: dict = field(default_factory=dict)


@dataclass
class TemporalEvent:
    """Tasdiqlangan (yoki yopilgan) shart."""

    key: str
    started_at: float
    ended_at: Optional[float] = None
    frames: int = 0
    #: O'rtacha va eng yuqori ishonch — hodisaning `confidence` si.
    mean_confidence: float = 0.0
    max_confidence: float = 0.0
    meta: dict = field(default_factory=dict)
    #: Oxirgi kuzatuvdagi qo'shimcha ma'lumot (bbox, burchak).
    payload: dict = field(default_factory=dict)

    @property
    def duration_ms(self) -> int:
        end = self.ended_at if self.ended_at is not None else time.monotonic()
        return int(max(0.0, end - self.started_at) * 1000)

    @property
    def is_open(self) -> bool:
        return self.ended_at is None

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "duration_ms": self.duration_ms,
            "frames": self.frames,
            "confidence": round(self.mean_confidence, 3),
            "max_confidence": round(self.max_confidence, 3),
            **self.meta,
            **self.payload,
        }


@dataclass
class _Candidate:
    """Hali tasdiqlanmagan yoki ochiq shart (ichki holat)."""

    condition: Condition
    first_seen: float
    last_seen: float
    frames: int = 0
    confidences: list = field(default_factory=list)
    confirmed: bool = False
    #: Tasdiqlangan hodisa (ochiq bo'lsa).
    event: Optional[TemporalEvent] = None
    payload: dict = field(default_factory=dict)

    @property
    def mean_confidence(self) -> float:
        return sum(self.confidences) / len(self.confidences) if self.confidences else 0.0


class TemporalEngine:
    """
    Shartlarni kuzatadi va tasdiqlangan hodisalarni chiqaradi.

    Har kadrda ikki qadam:

        observe(key, ...)   - shart HOZIR bor deb belgilaydi
        tick()              - kadrni yakunlaydi va hodisalarni beradi

    Ikki qadamga bo'lish MAJBURIY: `observe` faqat ko'ringan
    shartlar uchun chaqiriladi va "qaysilari YO'Q" degan savolga
    javob beradigan yagona joy `tick()` - u kuzatilmagan shartlarni
    topadi va ularni yopadi.
    """

    def __init__(self) -> None:
        self._candidates: dict = {}
        self._seen_this_frame: set = set()

    # ------------------------------------------------------------------
    def reset(self) -> None:
        """Yangi sessiya — barcha shartlar unutiladi."""
        self._candidates.clear()
        self._seen_this_frame.clear()

    @property
    def open_events(self) -> list:
        return [
            item.event
            for item in self._candidates.values()
            if item.confirmed and item.event is not None
        ]

    def is_open(self, key: str) -> bool:
        candidate = self._candidates.get(key)
        return bool(candidate and candidate.confirmed)

    # ------------------------------------------------------------------
    def observe(
        self,
        condition: Condition,
        *,
        confidence: float = 1.0,
        payload: Optional[dict] = None,
        now: Optional[float] = None,
    ) -> None:
        """Shart shu kadrda MAVJUD deb belgilaydi."""
        now = now if now is not None else time.monotonic()
        self._seen_this_frame.add(condition.key)

        candidate = self._candidates.get(condition.key)
        if candidate is None:
            candidate = _Candidate(
                condition=condition, first_seen=now, last_seen=now
            )
            self._candidates[condition.key] = candidate

        candidate.last_seen = now
        candidate.frames += 1
        candidate.confidences.append(float(confidence))
        if payload:
            candidate.payload = dict(payload)

        # Qoidalar OCHIQ hodisaga qayta qo'llanmaydi: tasdiqlangan
        # shart ochiq qoladi va uni har kadrda qayta tekshirish
        # faqat vaqt sarflardi.
        if candidate.confirmed:
            if candidate.event is not None:
                candidate.event.frames = candidate.frames
                candidate.event.mean_confidence = candidate.mean_confidence
                candidate.event.max_confidence = max(candidate.confidences)
                candidate.event.payload = candidate.payload
            return

    def tick(self, *, now: Optional[float] = None) -> tuple:
        """
        Kadrni yakunlaydi.

        Qaytadi: `(ochilgan_hodisalar, yopilgan_hodisalar)`.

        Ochilish va yopilish ALOHIDA ro'yxatda: birinchisi
        "boshlandi" hodisasini yozadi, ikkinchisi esa unga
        davomiylik qo'shadi. Ularni bitta ro'yxatda berish
        chaqiruvchini turini tekshirishga majbur qilardi.
        """
        now = now if now is not None else time.monotonic()
        opened: list = []
        closed: list = []

        for key in list(self._candidates):
            candidate = self._candidates[key]
            present = key in self._seen_this_frame

            if present and not candidate.confirmed:
                event = self._try_confirm(candidate, now)
                if event is not None:
                    opened.append(event)
                continue

            if present:
                continue

            # --- Shart bu kadrda YO'Q ---
            gap_ms = (now - candidate.last_seen) * 1000
            if gap_ms < candidate.condition.release_ms:
                # Qisqa uzilish - shart hali ochiq hisoblanadi.
                continue

            if candidate.confirmed and candidate.event is not None:
                # Yopilish vaqti - shart OXIRGI ko'ringan payt,
                # `release_ms` kutish tugagan payt EMAS. Aks holda
                # har bir hodisa davomiyligi bekorga 0.8 soniyaga
                # uzayardi.
                candidate.event.ended_at = candidate.last_seen
                candidate.event.frames = candidate.frames
                candidate.event.mean_confidence = candidate.mean_confidence
                candidate.event.max_confidence = max(candidate.confidences or [0.0])
                closed.append(candidate.event)

            del self._candidates[key]

        self._seen_this_frame.clear()
        return opened, closed

    # ------------------------------------------------------------------
    @staticmethod
    def _try_confirm(candidate: _Candidate, now: float) -> Optional[TemporalEvent]:
        """Uchala talabga ham javob bersa - hodisa ochiladi."""
        rule = candidate.condition
        duration_ms = (now - candidate.first_seen) * 1000

        if candidate.frames < rule.min_frames:
            return None
        if duration_ms < rule.min_duration_ms:
            return None
        if candidate.mean_confidence < rule.min_confidence:
            return None

        candidate.confirmed = True
        candidate.event = TemporalEvent(
            key=rule.key,
            # Boshlanish - shart BIRINCHI ko'ringan payt, tasdiqlangan
            # payt emas: hodisa haqiqatda o'shanda boshlangan va
            # dalil kadri ham o'sha vaqtdan olinishi kerak.
            started_at=candidate.first_seen,
            frames=candidate.frames,
            mean_confidence=candidate.mean_confidence,
            max_confidence=max(candidate.confidences),
            meta=dict(rule.meta),
            payload=dict(candidate.payload),
        )
        log.debug(
            "Shart tasdiqlandi: %s (%s kadr, %.0f ms, ishonch %.2f)",
            rule.key, candidate.frames, duration_ms, candidate.mean_confidence,
        )
        return candidate.event

    def close_all(self, *, now: Optional[float] = None) -> list:
        """
        Barcha ochiq hodisalarni yopadi (sessiya yakunlanganda).

        Usiz oxirgi hodisalar davomiyligsiz qolardi: ular ochilgan,
        lekin hech qachon yopilmagan bo'lardi va bayonnomada
        "telefon aniqlandi, davomiyligi noma'lum" deb turardi.
        """
        now = now if now is not None else time.monotonic()
        closed = []
        for candidate in self._candidates.values():
            if candidate.confirmed and candidate.event is not None:
                candidate.event.ended_at = min(now, candidate.last_seen)
                closed.append(candidate.event)
        self._candidates.clear()
        self._seen_this_frame.clear()
        return closed
