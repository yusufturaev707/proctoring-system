"""
Hodisalarni birlashtirish (event fusion).

NIMA UCHUN KERAK. Alohida olingan hodisa ko'pincha ikki xil
talqinga ega:

    "telefon aniqlandi"   -> stolda yotibdi, teginilmadi?
    "pastga qaradi"       -> qog'ozga qaradi?
    "qo'l pastda"         -> tizzada?

Uchalasi BIR VAQTDA sodir bo'lsa, talqin bitta qoladi: telefon
ishlatilmoqda. Fusion aynan shu — alohida zaif signallardan bitta
kuchli xulosa.

TARKIBIY HODISALAR O'CHIRILMAYDI. Yuqori shubha hodisasi ularning
USTIGA qo'shiladi, o'rniga emas. Sabab dalil zanjirida:
apellyatsiyada "nima uchun yuqori shubha?" degan savolga faqat
tarkibiy hodisalar javob bera oladi. Ular o'chirilsa, xulosa
asossiz da'voga aylanardi.

BALL ESA IKKI MARTA SANALMAYDI. Tarkibiy hodisalarning og'irligi
allaqachon qo'shilgan; fusion hodisasi ularning O'RNINI bosmaydi,
lekin uning o'z og'irligi qo'shimcha xavfni ifodalaydi. Server
tomonda cooldown va 100 ballik tavan bu qo'shilishni cheklaydi.

OYNA ±3 soniya (siyosatdan: `fusion.window_ms`). U ataylab keng:
telefonni chiqarish, unga qarash va qo'lni cho'zish ketma-ket
sodir bo'ladi, bir vaqtda emas.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

#: Telefon deb hisoblanadigan obyekt nomlari.
#:
#: Nom bo'yicha - COCO kodi bo'yicha EMAS: maxsus o'qitilgan
#: modelda kodlar boshqacha bo'ladi, nom esa `CocoObject.name` dan
#: keladi va u administrator nazoratida.
_PHONE_NAMES = {"cell phone", "mobile phone", "phone", "smartphone", "telefon"}


@dataclass
class FusionRule:
    """
    Bitta birlashtirish qoidasi.

    `required` — barcha shartlar bo'lishi SHART.
    `optional` — kamida `min_optional` tasi.

    Ikkiga bo'lish kerak, chunki qoidalar bir xil emas: "telefon +
    pastga qaradi" da telefon majburiy (usiz xulosa ma'nosiz), qo'l
    esa qo'shimcha dalil - u kadrga tushmagan bo'lishi mumkin.
    """

    name: str
    event_type: str
    severity: int
    required: set = field(default_factory=set)
    optional: set = field(default_factory=set)
    min_optional: int = 0
    #: Shu hodisa qayta chiqarilgunga qadar kutish (s).
    cooldown_s: float = 30.0


#: Qoidalar. Tartib MUHIM: birinchi mos kelgani ishlaydi va
#: kuchliroq qoidalar tepada turadi.
RULES = (
    FusionRule(
        name="phone_usage",
        event_type="high_suspicion_phone",
        severity=4,
        required={"phone"},
        optional={"looking_down", "hand_near_phone"},
        min_optional=1,
    ),
    FusionRule(
        name="external_person",
        event_type="high_suspicion_person",
        severity=4,
        required={"multiple_faces"},
        optional={"second_person"},
        min_optional=0,
    ),
    FusionRule(
        name="identity_swap",
        event_type="high_suspicion_identity",
        severity=4,
        required={"face_mismatch"},
        optional={"no_face", "multiple_faces"},
        min_optional=1,
    ),
)


@dataclass
class FusedEvent:
    """Birlashtirilgan xulosa."""

    type: str
    severity: int
    rule: str
    #: Qaysi hodisalardan yig'ildi — dalil zanjiri uchun.
    sources: list = field(default_factory=list)
    payload: dict = field(default_factory=dict)

    def as_payload(self) -> dict:
        return {
            "rule": self.rule,
            # `fused_from` proktorga xulosaning ASOSINI ko'rsatadi.
            # Usiz "yuqori shubha" yorlig'i tekshirib bo'lmaydigan
            # da'vo bo'lardi.
            "fused_from": list(self.sources),
            **self.payload,
        }


class EventFusion:
    """
    Oxirgi hodisalarni oynada ushlab, qoidalarni qo'llaydi.

    `feed()` har bir hodisa uchun chaqiriladi, `evaluate()` esa
    kadr oxirida. Ikkiga bo'lish `TemporalEngine` dagi bilan bir
    xil sababdan: "qaysi belgilar hozir bor" degan savolga javob
    beradigan joy bitta bo'lishi kerak.
    """

    def __init__(self, window_ms: int = 3000) -> None:
        self._window = max(0.5, float(window_ms) / 1000.0)
        #: `{belgi: (vaqt, payload)}` — oynadagi eng oxirgi ko'rinish.
        self._signals: dict = {}
        self._last_fired: dict = {}

    # ------------------------------------------------------------------
    def configure(self, window_ms: int) -> None:
        self._window = max(0.5, float(window_ms) / 1000.0)

    def reset(self) -> None:
        self._signals.clear()
        self._last_fired.clear()

    # ------------------------------------------------------------------
    def feed(self, event, *, now: Optional[float] = None) -> None:
        """Hodisadan BELGILARNI ajratib, oynaga qo'yadi."""
        now = now if now is not None else time.monotonic()
        for signal, payload in self._signals_of(event):
            self._signals[signal] = (now, payload)

    def evaluate(self, *, now: Optional[float] = None) -> list:
        """Oynadagi belgilarga qoidalarni qo'llaydi."""
        now = now if now is not None else time.monotonic()
        self._prune(now)

        present = set(self._signals)
        results: list = []

        for rule in RULES:
            if not rule.required.issubset(present):
                continue
            matched_optional = rule.optional & present
            if len(matched_optional) < rule.min_optional:
                continue

            # `None` - hali hech qachon ishlamagan. Standart qiymat
            # sifatida `0.0` ISHLATILMAYDI: nisbiy soat bilan
            # (sessiya boshidan sanaladigan) birinchi xulosa
            # cooldown ichida qolib, umuman chiqmasdi.
            last = self._last_fired.get(rule.name)
            if last is not None and now - last < rule.cooldown_s:
                # Bir voqea uchun bitta xulosa. Cooldownsiz u har
                # kadrda qayta chiqarilib, hodisa oqimini
                # to'ldirardi.
                continue

            self._last_fired[rule.name] = now
            sources = sorted(rule.required | matched_optional)
            payload = {}
            for signal in sources:
                payload.update(self._signals.get(signal, (0, {}))[1] or {})

            results.append(
                FusedEvent(
                    type=rule.event_type,
                    severity=rule.severity,
                    rule=rule.name,
                    sources=sources,
                    payload=payload,
                )
            )
            log.info("Hodisalar birlashtirildi: %s <- %s", rule.event_type, sources)
        return results

    # ------------------------------------------------------------------
    def _prune(self, now: float) -> None:
        expired = [
            signal
            for signal, (seen, _) in self._signals.items()
            if now - seen > self._window
        ]
        for signal in expired:
            del self._signals[signal]

    @staticmethod
    def _signals_of(event) -> list:
        """
        Hodisadan birlashtirish belgilarini ajratadi.

        YOPILISH hodisalari (`closed`) e'tiborga OLINMAYDI: ular
        voqeaning tugaganini bildiradi va ularni belgi sifatida
        qabul qilish "telefon olib qo'yildi" holatini "telefon
        ishlatilmoqda" xulosasiga aylantirardi.
        """
        payload = getattr(event, "payload", None) or {}
        if payload.get("closed"):
            return []

        event_type = getattr(event, "type", "")
        signals: list = []

        if event_type == "object_detected":
            name = str(payload.get("object") or "").lower()
            if name in _PHONE_NAMES:
                signals.append(("phone", {"object": payload.get("object"),
                                          "track_id": getattr(event, "track_id", None)}))
            else:
                signals.append(("object", {"object": payload.get("object")}))

        elif event_type in ("looking_away", "prolonged_looking_away"):
            if str(payload.get("direction") or "") == "down":
                signals.append(("looking_down", {"direction": "down"}))
            signals.append(("looking_away", {"direction": payload.get("direction")}))

        elif event_type == "multiple_faces":
            signals.append(("multiple_faces", {"faces": payload.get("faces")}))

        elif event_type == "second_person":
            signals.append(("second_person", {}))

        elif event_type == "face_mismatch":
            signals.append(("face_mismatch", {"score": payload.get("score")}))

        elif event_type == "face_not_found":
            signals.append(("no_face", {}))

        elif event_type in ("hand_below_desk", "suspicious_hand_movement"):
            signals.append(("hand_near_phone", {"hands": payload.get("hidden")}))

        return signals
