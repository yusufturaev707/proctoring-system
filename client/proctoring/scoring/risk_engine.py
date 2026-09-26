"""
Client tomonidagi xavf balli — FAQAT KO'RSATISH uchun.

BU BALL SERVERGA YUBORILMAYDI va hech qanday qaror qabul
qilmaydi. Haqiqiy ball serverda hisoblanadi
(`proctoring/services/risk.py`) va u yerda hodisalar allaqachon
tekshirilgan, og'irliklar DB'dan olingan, cooldown atomik.

Nima uchun u holda client tomonda ham kerak: operator ekranda
holatni KO'RISHI kerak. Serverdan ball faqat heartbeat javobida
keladi (30 soniyada bir marta) va u paytda proktor allaqachon
aralashgan bo'lishi mumkin. Mahalliy ball nishonni DARHOL
o'zgartiradi.

QIYMATLAR FARQ QILISHI MUMKIN va bu normal: client barcha
hodisalarni ko'radi, server esa faqat yetkazib berilganlarini
(tarmoq uzilganda bufer to'planadi). Shuning uchun UI'da mahalliy
ball "taxminiy" sifatida ko'rsatilishi va serverning qiymati
kelganda U BILAN ALMASHTIRILISHI kerak.

ALGORITM serverdagi bilan AYNAN bir xil: bir xil pasayish, bir
xil cooldown, bir xil tavan. Aks holda ikki ekranda ikki xil son
turardi va operator qaysi biriga ishonishni bilmasdi.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

#: Koddagi zaxira og'irliklar.
#:
#: Server `EventRiskWeight` jadvalidan oladi va u client'ga
#: YUBORILMAYDI (sozlama hajmini oshirardi). Shuning uchun bu
#: yerdagi qiymatlar `ingest.RISK_WEIGHTS` bilan bir xil
#: bo'lishi kerak - ular ajralib ketsa, ikki ekranda ikki xil
#: son turadi.
WEIGHTS: dict[str, int] = {
    "window_blur": 3,
    "fullscreen_exit": 5,
    "hotkey_blocked": 2,
    "clipboard_blocked": 4,
    "multi_monitor": 12,
    "camera_lost": 10,
    "camera_blocked": 15,
    "rdp_detected": 30,
    "vm_detected": 25,
    "process_blacklisted": 15,
    "face_not_found": 6,
    "face_mismatch": 12,
    "multiple_faces": 20,
    "object_detected": 15,
    "client_anomaly": 20,
    "navigation_blocked": 8,
    "network_lost": 2,
    # AI hodisalari
    "face_occluded": 5,
    "face_too_far": 2,
    "face_too_close": 2,
    "student_left_frame": 10,
    "second_person": 25,
    "looking_away": 5,
    "prolonged_looking_away": 15,
    "excessive_head_movement": 4,
    "eyes_closed": 2,
    "hand_below_desk": 10,
    "suspicious_hand_movement": 8,
    "unauthorized_device": 20,
    "high_suspicion_phone": 40,
    "high_suspicion_person": 45,
    "high_suspicion_identity": 45,
    "camera_degraded": 3,
    "camera_reconnected": 0,
    "proctoring_degraded": 5,
}


@dataclass
class RiskState:
    """Ballning joriy holati."""

    score: int = 0
    level: str = "normal"
    breakdown: dict = field(default_factory=dict)
    #: Serverdan kelgan qiymat (mavjud bo'lsa) — u ustun.
    server_score: Optional[int] = None

    @property
    def display(self) -> int:
        """Ekranda ko'rsatiladigan ball."""
        return self.server_score if self.server_score is not None else self.score

    @property
    def is_estimate(self) -> bool:
        return self.server_score is None


class RiskEngine:
    """Mahalliy ball: pasayish + cooldown + tavan."""

    def __init__(self, policy: Optional[dict] = None) -> None:
        self._decay_per_min = 5
        self._cooldown_s = 60
        self._thresholds = (20, 40, 70)
        self._score = 0.0
        self._updated_at = time.monotonic()
        self._breakdown: dict = {}
        self._cooldowns: dict = {}
        self._server_score: Optional[int] = None
        self.configure(policy or {})

    # ------------------------------------------------------------------
    def configure(self, policy: dict) -> None:
        risk = (policy or {}).get("risk") or {}
        self._decay_per_min = int(risk.get("decay_per_min", 5) or 0)
        self._cooldown_s = int(risk.get("cooldown_s", 60) or 0)
        self._thresholds = (
            int(risk.get("low", 20)),
            int(risk.get("medium", 40)),
            int(risk.get("high", 70)),
        )

    def reset(self) -> None:
        """Yangi talabgor — ball noldan."""
        self._score = 0.0
        self._updated_at = time.monotonic()
        self._breakdown.clear()
        self._cooldowns.clear()
        self._server_score = None

    # ------------------------------------------------------------------
    def add(self, event_type: str, *, now: Optional[float] = None) -> RiskState:
        """Hodisani ballga qo'shadi."""
        now = now if now is not None else time.monotonic()
        points = WEIGHTS.get(event_type, 1)
        if points <= 0:
            return self.state(now=now)

        if self._cooldown_s > 0:
            # `None` tekshiruvi MAJBURIY: `0.0` haqiqiy vaqt bo'lishi
            # mumkin (nisbiy soat) va `if last:` uni "hech qachon"
            # deb o'qirdi.
            last = self._cooldowns.get(event_type)
            if last is not None and (now - last) < self._cooldown_s:
                # Takror hodisa ballga qo'shilmaydi, lekin hodisaning
                # o'zi baribir yuboriladi - dalil yo'qolmaydi.
                return self.state(now=now)
            self._cooldowns[event_type] = now

        self._score = min(100.0, self._decayed(now) + points)
        self._updated_at = now
        # Tarkib PASAYMAYDI: u "nima bo'lgan" degan savolga javob
        # beradi (serverdagi bilan bir xil qoida).
        self._breakdown[event_type] = self._breakdown.get(event_type, 0) + points
        return self.state(now=now)

    def set_server_score(self, score: Optional[int]) -> None:
        """
        Serverdan kelgan ball — u USTUN.

        Heartbeat javobida keladi. Mahalliy ball tozalanmaydi:
        keyingi hodisa uni yana oshiradi va aloqa uzilsa u yana
        ishlaydi.
        """
        self._server_score = None if score is None else max(0, min(100, int(score)))

    def state(self, *, now: Optional[float] = None) -> RiskState:
        now = now if now is not None else time.monotonic()
        score = int(round(self._decayed(now)))
        return RiskState(
            score=score,
            level=self._level(score),
            breakdown=dict(self._breakdown),
            server_score=self._server_score,
        )

    # ------------------------------------------------------------------
    def _decayed(self, now: float) -> float:
        """
        Vaqt o'tishi bilan pasaygan ball.

        LAZY: fon taymeri yo'q. Har o'qishda oxirgi o'zgarishdan
        beri o'tgan vaqt bo'yicha hisoblanadi - natija bir xil,
        xarajat nol.
        """
        if self._score <= 0 or self._decay_per_min <= 0:
            return max(0.0, self._score)
        minutes = max(0.0, (now - self._updated_at) / 60.0)
        return max(0.0, self._score - self._decay_per_min * minutes)

    def _level(self, score: int) -> str:
        low, medium, high = self._thresholds
        if score >= high:
            return "high"
        if score >= medium:
            return "medium"
        if score >= low:
            return "low"
        return "normal"
