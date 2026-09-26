"""
Xulq tahlili: xom belgilardan HODISAGA.

Bu modul AI modullari bilan hodisa oqimi orasidagi yagona
ko'prik. Kirish - bitta kadrning belgilari (yuzlar, izlar, poza,
nigoh); chiqish - `services/monitoring.py` buferiga qo'yiladigan
hodisalar.

IKKI DARAJALI QOIDA. Ko'p hodisalar ikkita chegaraga ega va ular
BOSHQA-BOSHQA javob talab qiladi:

    yuz yo'q  2 s   -> ogohlantirish (severity 1)  ball kichik
    yuz yo'q  5 s   -> shubha        (severity 3)  ball katta

Ikkinchisi birinchisini ALMASHTIRADI, ustiga qo'shilmaydi: bitta
uzluksiz holat uchun ikkita hodisa yozilsa, ball ikki marta
sanalardi va bayonnomada bir voqea ikki qatorga bo'linardi.

CHEGARALAR SIYOSATDAN keladi (`config.proctoring.temporal`).
Ularni koddan qadab qo'yish har bir imtihon uchun bir xil
qattiqlik degani bo'lardi - holbuki mashq testi va sertifikat
imtihoni butunlay boshqa talab qiladi.

MODUL BALL HISOBLAMAYDI va CHETLASHTIRMAYDI. U hodisa taklif
qiladi; ball serverda (`services/risk.py`), chetlashtirish esa
proktorda.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from proctoring.behavior.seat_anchor import SeatAnchor
from proctoring.behavior.temporal_engine import Condition, TemporalEngine

log = logging.getLogger(__name__)

#: COCO "person" klassining kodi - YOLOv8/YOLO11 COCO modellarida 0.
_PERSON_CODE = 0

#: Ikkinchi odam hisoblanishi uchun uning ramkasi YUZASI talabgornikining
#: kamida shu ulushi bo'lishi kerak. Yuza, balandlik emas: tepadan
#: qaragan kamerada ikkalasi ham masofaga bog'liq, lekin balandlik
#: o'tirgan va tik turgan odamni butunlay boshqacha o'lchaydi. 0.25 —
#: eski balandlik chegarasi (0.5) ning yuzadagi tengi: yonida turgan
#: yoki egilgan odam o'tadi, orqa qatordagi kichik odam o'tmaydi.
_SECOND_PERSON_AREA_RATIO = 0.25


def _box_area(track) -> float:
    x1, y1, x2, y2 = (float(value) for value in track.bbox)
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def _mark(label: str, kind: str, bbox, features, conf: Optional[float] = None) -> Optional[dict]:
    """
    Dalil kadrida chiziladigan bitta belgi — kadrga NISBATAN (0..1).

    Piksel EMAS va bu hal qiluvchi: ramka detektor kadrida (IP kamerada
    2688x1520) hisoblanadi, dalil kadri esa halqa buferdan, 640 px ga
    kichraytirilgan. Pikselni to'g'ridan-to'g'ri chizish ramkani rasmdan
    tashqariga chiqarardi. Nisbiy koordinata esa har qanday o'lchamdagi
    kadrga (va paneldagi har qanday ko'rinish o'lchamiga) to'g'ri tushadi.

    `kind` — panel rangi uchun: `object` (taqiqlangan narsa), `person`
    (begona odam), `student` (talabgorning o'zi — kontekst), `face`.
    """
    width, height = features.frame_width, features.frame_height
    if bbox is None or not width or not height:
        return None
    try:
        x1, y1, x2, y2 = (float(value) for value in list(bbox)[:4])
    except (TypeError, ValueError):
        return None
    box = [
        min(1.0, max(0.0, x1 / width)),
        min(1.0, max(0.0, y1 / height)),
        min(1.0, max(0.0, x2 / width)),
        min(1.0, max(0.0, y2 / height)),
    ]
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    mark = {"label": str(label)[:48], "kind": kind, "box": [round(value, 4) for value in box]}
    if conf is not None:
        mark["conf"] = round(float(conf), 3)
    return mark


def _marks(*items) -> list:
    return [item for item in items if item]


def _face_mark(identity, features, label: str) -> list:
    """Asosiy (talabgor) yuzi — yuzga oid hodisada "qaysi yuz" degan javob."""
    primary = getattr(identity, "primary", None)
    if primary is None:
        return []
    return _marks(_mark(label, "face", primary.bbox, features))


@dataclass
class FrameFeatures:
    """
    Bitta kadrning barcha belgilari.

    Barcha maydonlar IXTIYORIY: modullar mustaqil ishlaydi va
    ularning har biri o'chirilgan bo'lishi mumkin. `None` va bo'sh
    ro'yxat FARQ QILADI - birinchisi "modul ishlamadi", ikkinchisi
    "modul ishladi, hech nima topmadi". Ularni aralashtirish
    o'chirilgan modulni "hech narsa yo'q" deb talqin qilardi.
    """

    #: Kadr vaqti (monotonik soat). `None` — chaqiruvchi bermadi.
    #
    # `0.0` STANDART QIYMAT BO'LA OLMAYDI: u haqiqiy vaqt bo'lishi
    # mumkin (sessiya boshidan hisoblanadigan nisbiy soat) va
    # `timestamp or time.monotonic()` uni "berilmagan" deb talqin
    # qilardi. Natijada birinchi kadr joriy monotonik vaqtni olar,
    # keyingilari esa nisbiy vaqtni - davomiylik MANFIY chiqib,
    # hech bir shart tasdiqlanmasdi.
    timestamp: Optional[float] = None
    camera_role: str = "primary"
    frame_width: int = 0
    frame_height: int = 0

    identity: object = None          # IdentityResult | None
    tracks: Optional[list] = None    # ByteTrack izlari
    poses: Optional[list] = None     # Pose ro'yxati
    gaze: object = None              # GazeResult | None

    #: Etalonga o'xshashlik chegarasi (0..1). Siyosatdan.
    face_threshold: float = 0.42


@dataclass
class BehaviorEvent:
    """Chiqish hodisasi — client buferining shakli."""

    type: str
    severity: int
    payload: dict = field(default_factory=dict)
    #: Temporal hodisa kaliti — yopilganda davomiylik qo'shish uchun.
    key: str = ""
    duration_ms: int = 0
    confidence: int = 0
    camera_role: str = ""
    track_id: Optional[int] = None

    def as_payload(self) -> dict:
        """`SessionMonitor.push_event` uchun payload."""
        data = dict(self.payload)
        # Belgilar faqat DALIL kadri uchun (`EvidenceRecorder`). Hodisa
        # qatorida rasm yo'q va ular har hodisani bekorga og'irlashtirardi.
        data.pop("marks", None)
        if self.duration_ms:
            data["duration_ms"] = self.duration_ms
        if self.confidence:
            data["confidence"] = self.confidence
        if self.camera_role:
            data["camera_role"] = self.camera_role
        if self.track_id is not None:
            data["track_id"] = self.track_id
        return data


#: Ikki darajali holatlar: `(ogohlantirish_turi, shubha_turi)`.
#:
#: Ikkinchisi birinchisini ALMASHTIRADI - modul docstring'iga qarang.
_ESCALATION = {
    "no_face": ("face_not_found", "face_not_found"),
    "gaze_away": ("looking_away", "prolonged_looking_away"),
}


class BehaviorAnalyzer:
    """Kadr belgilarini hodisalarga aylantiradi."""

    def __init__(self, policy: Optional[dict] = None) -> None:
        self._engine = TemporalEngine()
        self._policy = {}
        self._temporal = {}
        self._escalated: set = set()
        #: Bosh burchagi tarixi — "harakat ko'p" xulosasi uchun.
        self._head_history: list = []
        #: Kamera roli -> o'rindiq kalibrlashi (`seat_anchor.py`). Rol
        #: bo'yicha, chunki bitta kamerali rejimda obyekt tahlili ham
        #: veb-kamerada ketadi va uning o'rindig'i boshqa.
        self._seats: dict = {}
        self.configure(policy or {})

    # ------------------------------------------------------------------
    def configure(self, policy: dict) -> None:
        """
        Siyosatni qo'llaydi (`config.proctoring`).

        Har talabgordan oldin chaqiriladi: imtihon almashsa
        chegaralar ham almashadi.
        """
        self._policy = policy or {}
        temporal = self._policy.get("temporal") or {}
        self._temporal = {
            "no_face_warn_s": float(temporal.get("no_face_warn_s", 2)),
            "no_face_suspicious_s": float(temporal.get("no_face_suspicious_s", 5)),
            "gaze_away_warn_s": float(temporal.get("gaze_away_warn_s", 2)),
            "gaze_away_suspicious_s": float(temporal.get("gaze_away_suspicious_s", 5)),
            "object_min_frames": int(temporal.get("object_min_frames", 5)),
            "object_min_conf": float(temporal.get("object_min_conf", 0.80)),
            "object_min_duration_ms": int(temporal.get("object_min_duration_ms", 1200)),
        }

    def reset(self) -> None:
        """Yangi talabgor — barcha holat unutiladi."""
        self._engine.reset()
        self._escalated.clear()
        self._head_history.clear()
        # O'rindiq HAR SESSIYADA qaytadan o'lchanadi: kamera siljimaydi,
        # lekin stul suriladi va talabgor boshqa joyga o'tirishi mumkin.
        self._seats.clear()

    def _seat(self, role: str) -> SeatAnchor:
        return self._seats.setdefault(role or "primary", SeatAnchor())

    def seat_of(self, role: str):
        """O'rindiq nuqtasi (0..1) yoki `None` — diagnostika va test uchun."""
        anchor = self._seats.get(role or "primary")
        return anchor.seat if anchor is not None else None

    def finish(self) -> list:
        """Sessiya yakuni — ochiq hodisalar yopiladi."""
        return [self._closed_event(item) for item in self._engine.close_all()]

    # ------------------------------------------------------------------
    def analyse(self, features: FrameFeatures) -> list:
        """Bitta kadr -> hodisalar ro'yxati (bo'sh bo'lishi mumkin)."""
        now = features.timestamp if features.timestamp is not None else time.monotonic()

        self._observe_identity(features, now)
        self._observe_objects(features, now)
        self._observe_gaze(features, now)
        self._observe_pose(features, now)

        opened, closed = self._engine.tick(now=now)

        events = [self._opened_event(item, features) for item in opened]
        events.extend(self._closed_event(item) for item in closed)
        return [item for item in events if item is not None]

    # ------------------------------------------------------------------
    # Kuzatuvlar
    # ------------------------------------------------------------------
    def _observe_identity(self, features: FrameFeatures, now: float) -> None:
        identity = features.identity
        if identity is None:
            # Modul ishlamadi - hech qanday xulosa chiqarilmaydi.
            # "Yuz yo'q" deb hisoblash o'chirilgan modulni
            # buzilishga aylantirardi.
            return

        if not identity.has_face:
            self._observe_two_stage("no_face", features, now, severity_low=2)
            return

        if identity.count > 1:
            # IKKINCHI ODAM. Bu darhol shubhali, lekin baribir
            # temporal tasdiqlashdan o'tadi: kadr chetidan o'tib
            # ketgan xodim bir-ikki kadrda ko'rinishi mumkin.
            self._engine.observe(
                Condition(
                    key="multiple_faces",
                    min_frames=3,
                    min_duration_ms=900,
                    meta={"event": "multiple_faces", "severity": 3},
                ),
                confidence=1.0,
                payload={
                    "faces": identity.count,
                    # Eng kattasi — talabgor (`face_identity` qoidasi),
                    # qolganlari — kadrdagi boshqa yuzlar.
                    "marks": _marks(*[
                        _mark(
                            "Talabgor" if face is identity.primary else "Boshqa yuz",
                            "student" if face is identity.primary else "person",
                            face.bbox, features,
                        )
                        for face in identity.faces[:10]
                    ]),
                },
                now=now,
            )

        # Yuz o'lchami - "uzoq/yaqin". Chegaralar konservativ:
        # ular sifat ogohlantirishi, buzilish emas.
        if identity.face_ratio and identity.face_ratio < 0.06:
            self._observe_simple("face_too_far", "face_too_far", 1, now,
                                 payload={"ratio": round(identity.face_ratio, 3),
                                          "marks": _face_mark(identity, features, "Uzoqda")})
        elif identity.face_ratio > 0.55:
            self._observe_simple("face_too_close", "face_too_close", 1, now,
                                 payload={"ratio": round(identity.face_ratio, 3),
                                          "marks": _face_mark(identity, features, "Juda yaqin")})

        if identity.offset > 0.6:
            self._observe_simple("student_left_frame", "student_left_frame", 2, now,
                                 payload={"offset": round(identity.offset, 3),
                                          "marks": _face_mark(identity, features, "Kadr chetida")})

        similarity = identity.similarity
        if similarity is not None and similarity < features.face_threshold:
            # MOS KELMASLIK - eng jiddiy shaxs hodisasi. Chegara
            # imtihon profilidan keladi va u serverda ham
            # qo'llanadi (`verify_periodic_face`).
            self._engine.observe(
                Condition(
                    key="face_mismatch",
                    min_frames=5,
                    min_duration_ms=1500,
                    meta={"event": "face_mismatch", "severity": 3},
                ),
                confidence=float(1.0 - similarity),
                payload={
                    "score": int(round(max(0.0, similarity) * 100)),
                    "threshold": int(round(features.face_threshold * 100)),
                    "marks": _face_mark(
                        identity, features,
                        "Mos emas · {}%".format(int(round(max(0.0, similarity) * 100))),
                    ),
                },
                now=now,
            )

    def _observe_objects(self, features: FrameFeatures, now: float) -> None:
        if features.tracks is None:
            return

        # ODAM ODDIY OBYEKT EMAS. Talabgorning o'zi har kadrda "odam"
        # va uni `object_detected` ga aylantirish har imtihonda
        # uzluksiz soxta hodisa, klip va xavf balli berardi - sozlamada
        # "Odam" klassi tanlangan bo'lsa (odatiy tanlov), aynan shunday
        # bo'lardi. Savol "odam bormi?" emas, "IKKINCHI odam bormi?".
        persons = [track for track in features.tracks if track.code == _PERSON_CODE]
        self._seat(features.camera_role).observe(
            persons, features.frame_width, features.frame_height, now
        )
        self._observe_second_person(persons, features, now)

        for track in features.tracks:
            if track.code == _PERSON_CODE:
                continue
            # Kalit `track_id` ni O'Z ICHIGA OLADI: ikkita telefon
            # ikkita alohida hodisa bo'lishi kerak. Yagona kalitda
            # ikkinchisi birinchisiga qo'shilib ketardi.
            self._engine.observe(
                Condition(
                    key="object:{}:{}".format(track.track_id, track.cls),
                    min_frames=self._temporal["object_min_frames"],
                    min_duration_ms=self._temporal["object_min_duration_ms"],
                    min_confidence=self._temporal["object_min_conf"],
                    meta={
                        "event": "object_detected",
                        "severity": 3,
                        "object": track.cls,
                        "track_id": track.track_id,
                    },
                ),
                confidence=float(track.score),
                payload={
                    "bbox": [int(value) for value in track.bbox],
                    # Nom serverdagi klass ro'yxatidan ("Telefon") —
                    # panel aynan NIMA topilganini rasm ustida yozadi.
                    "marks": _marks(
                        _mark(track.cls, "object", track.bbox, features, conf=track.score)
                    ),
                },
                now=now,
            )

    def _observe_second_person(self, persons: list, features: FrameFeatures, now: float) -> None:
        """
        Kadrda talabgordan tashqari YAQIN odam - `second_person`.

        TALABGOR — O'RINDIQDAGI ODAM (`seat_anchor.SeatAnchor`), eng
        katta yoki eng baland EMAS. Obyekt kamerasi ish joyi tepasida
        turadi va u yerda ramka o'lchami kameragacha masofani bildiradi:
        ilgari yonida tik turgan odam "talabgor", stolda o'tirgan
        talabgorning o'zi esa «Begona odam» bo'lib chiqardi.

        Qolganlar faqat talabgor bilan TAQQOSLANADIGAN yuzada bo'lsa
        hisoblanadi (`_SECOND_PERSON_AREA_RATIO`): kadr chetiga orqa
        qatordagi odamlar ham tushadi va ular kichik ko'rinadi. Yonida
        turgan yoki egilib gapirayotgan odam esa katta ko'rinadi -
        aynan u kerak.

        KALIBRLASH SUKUTI (`warming_up`): imtihonning dastlabki
        soniyalarida operator mashina yonida turadi va bu kutilgan hol.
        Talabgor o'rindiqda bo'lmasa (`pick` -> `None`) ham hodisa
        chiqmaydi: "joyida yo'q" ni asosiy kamera aytadi (`no_face`).

        Kalit BITTA (`second_person`), track bo'yicha emas: savol
        "nechta begona odam" emas, "begona odam bormi" - odamlar
        almashib turganda hodisalar bo'linib ketmasligi kerak.
        """
        if len(persons) < 2:
            return
        seat = self._seat(features.camera_role)
        if seat.warming_up(now):
            return
        index = seat.pick(
            [track.bbox for track in persons],
            features.frame_width, features.frame_height,
            [getattr(track, "track_id", None) for track in persons],
        )
        if index is None:
            return
        student = persons[index]
        student_area = _box_area(student)
        if student_area <= 0:
            return
        near = [
            track for position, track in enumerate(persons)
            if position != index
            and _box_area(track) >= student_area * _SECOND_PERSON_AREA_RATIO
        ]
        if not near:
            return
        strongest = max(near, key=lambda track: float(track.score))
        self._engine.observe(
            Condition(
                key="second_person",
                min_frames=self._temporal["object_min_frames"],
                min_duration_ms=self._temporal["object_min_duration_ms"],
                min_confidence=self._temporal["object_min_conf"],
                meta={"event": "second_person", "severity": 3},
            ),
            confidence=float(strongest.score),
            payload={
                "count": 1 + len(near),
                "bbox": [int(value) for value in strongest.bbox],
                # Talabgor ham belgilanadi: "qaysi biri begona" degan
                # savolga faqat ikkalasi yonma-yon javob beradi.
                "marks": _marks(
                    _mark("Talabgor", "student", student.bbox, features, conf=student.score),
                    *[
                        _mark("Begona odam", "person", track.bbox, features, conf=track.score)
                        for track in near[:5]
                    ],
                ),
            },
            now=now,
        )

    def _observe_gaze(self, features: FrameFeatures, now: float) -> None:
        gaze = features.gaze
        if gaze is None or not getattr(gaze, "valid", False):
            return

        self._track_head_movement(gaze, now)

        if gaze.eyes_open is False:
            self._observe_simple("eyes_closed", "eyes_closed", 1, now)

        # Og'ish chegarasi: kalibrlangan noldan 25 gradus. Mutlaq
        # burchak ISHLATILMAYDI - sabab `gaze_estimator.py` da.
        if gaze.deviation >= 25.0:
            self._observe_two_stage(
                "gaze_away",
                features,
                now,
                severity_low=1,
                payload={
                    "direction": gaze.direction,
                    "deviation": int(round(gaze.deviation)),
                    "marks": _face_mark(
                        features.identity, features,
                        "Nigoh chetda · {}°".format(int(round(gaze.deviation))),
                    ),
                },
            )

    def _observe_pose(self, features: FrameFeatures, now: float) -> None:
        if not features.poses:
            return

        # TALABGORNING pozasi — o'rindiq qoidasi bilan (`second_person`
        # bilan bir xil). Ilgari birinchi aniqlangan odam olinardi va
        # yonida turgan odamning qo'llari talabgorga yozilishi mumkin edi.
        index = self._seat(features.camera_role).pick(
            [item.bbox for item in features.poses],
            features.frame_width, features.frame_height,
        )
        if index is None:
            return
        pose = features.poses[index]
        shoulder = pose.shoulder_line
        if shoulder is None:
            return

        # QO'L STOL OSTIDA. Stol chetini kadrdan bilib bo'lmaydi,
        # lekin yelka chizig'idan sezilarli PASTDA turgan va
        # kadrdan chiqib ketayotgan bilak ishonchli belgi.
        #
        # `frame_height` bo'lmasa tekshiruv o'tkazilmaydi: nisbatni
        # hisoblab bo'lmaydi va mutlaq piksel har rezolyutsiyada
        # boshqa ma'no berardi.
        if not features.frame_height:
            return

        threshold = shoulder + features.frame_height * 0.18
        hidden = [
            side
            for side, point in pose.wrists.items()
            if point is None or point[1] > threshold
        ]
        if len(hidden) == 2:
            # IKKALA qo'l ham ko'rinmasa - shubhali. Bittasi
            # ko'rinmasligi odatiy hol (sichqoncha, qog'oz).
            self._observe_simple(
                "hand_below_desk", "hand_below_desk", 2, now,
                min_frames=8, min_duration_ms=2500,
                payload={
                    "hidden": hidden,
                    "marks": _marks(_mark("Qo'llar ko'rinmaydi", "person", pose.bbox, features)),
                },
            )

    def _track_head_movement(self, gaze, now: float) -> None:
        """
        Bosh harakatining tarqoqligi.

        Uzluksiz katta harakat - "atrofga qarab chiqmoqda" belgisi.
        Bitta keskin burilishdan FARQ QILADI va aynan shu sababli
        tarqoqlik (std) o'lchanadi, tezlik emas.
        """
        self._head_history.append((now, gaze.yaw, gaze.pitch))
        # Oyna - 10 soniya.
        while self._head_history and now - self._head_history[0][0] > 10.0:
            self._head_history.pop(0)

        if len(self._head_history) < 20:
            return

        values = np.array([(item[1], item[2]) for item in self._head_history])
        spread = float(values.std(axis=0).max())
        if spread > 18.0:
            self._observe_simple(
                "excessive_head_movement", "excessive_head_movement", 1, now,
                min_frames=1, min_duration_ms=0,
                payload={"spread": round(spread, 1)},
            )

    # ------------------------------------------------------------------
    # Yordamchilar
    # ------------------------------------------------------------------
    def _observe_simple(self, key, event_type, severity, now, *,
                        min_frames=5, min_duration_ms=1200, payload=None) -> None:
        self._engine.observe(
            Condition(
                key=key,
                min_frames=min_frames,
                min_duration_ms=min_duration_ms,
                meta={"event": event_type, "severity": severity},
            ),
            payload=payload or {},
            now=now,
        )

    def _observe_two_stage(self, key, features, now, *, severity_low, payload=None) -> None:
        """
        Ikki darajali holat: ogohlantirish -> shubha.

        Ikkalasi ALOHIDA shart sifatida kuzatiladi va ikkalasi ham
        holat davom etgan sayin OCHIQ qoladi. Bu ikki narsani
        beradi:

          * jiddiylashish hodisasi ham davomiylikka ega bo'ladi.
            Uni bir marta kuzatib qo'yish yetarli emasdi: shart
            keyingi kadrda "yo'qolgan" hisoblanib, hodisa o'sha
            zahoti yopilardi va bayonnomada nol davomiylikli
            keraksiz yozuv qolardi;
          * epizod tugab, YANGISI boshlansa jiddiylashish QAYTA
            ishlaydi. Ilgari bayroq faqat `reset()` da tozalanardi,
            ya'ni bir talabgorda ikkinchi uzoq chalg'ish umuman
            qayd etilmasdi.
        """
        warn_type, high_type = _ESCALATION[key]
        warn_s = self._temporal["{}_warn_s".format(key)]
        high_s = self._temporal["{}_suspicious_s".format(key)]
        high_key = "{}:high".format(key)

        self._engine.observe(
            Condition(
                key=key,
                min_frames=3,
                min_duration_ms=int(warn_s * 1000),
                meta={"event": warn_type, "severity": severity_low},
            ),
            payload=payload or {},
            now=now,
        )

        candidate = self._engine._candidates.get(key)
        if candidate is None:
            # Asosiy shart yo'qoldi - epizod tugadi. Bayroq
            # tozalanadi, keyingi epizod qaytadan jiddiylashishi
            # mumkin.
            self._escalated.discard(key)
            return

        escalated = key in self._escalated
        if not escalated:
            if not candidate.confirmed:
                return
            if (now - candidate.first_seen) < high_s:
                return
            self._escalated.add(key)

        # Chegara oshgach HAR KADRDA kuzatiladi - hodisa holat
        # davom etgan sayin ochiq qoladi.
        self._engine.observe(
            Condition(
                key=high_key,
                min_frames=1,
                min_duration_ms=0,
                meta={"event": high_type, "severity": 3, "escalated": True},
            ),
            payload=payload or {},
            now=now,
        )

    def _opened_event(self, temporal, features: FrameFeatures) -> Optional[BehaviorEvent]:
        meta = temporal.meta
        event_type = meta.get("event")
        if not event_type:
            return None
        return BehaviorEvent(
            type=event_type,
            severity=int(meta.get("severity", 1)),
            key=temporal.key,
            confidence=int(round(temporal.mean_confidence * 100)),
            camera_role=features.camera_role,
            track_id=meta.get("track_id"),
            payload={
                key: value
                for key, value in temporal.as_dict().items()
                if key not in ("key", "confidence", "max_confidence", "event",
                               "severity", "track_id", "duration_ms", "frames")
            },
        )

    def _closed_event(self, temporal) -> Optional[BehaviorEvent]:
        """
        Yopilgan hodisa — DAVOMIYLIK bilan.

        Alohida hodisa turi yaratilmaydi: server yopilishni
        `duration_ms` bo'yicha taniydi va uni ochilgan hodisaga
        biriktiradi (`client_event_id` orqali). Yangi tur qo'shish
        `EVENT_CATEGORY` va `EVENT_LABEL` ro'yxatlarini ikki
        barobar uzaytirardi.
        """
        meta = temporal.meta
        event_type = meta.get("event")
        if not event_type:
            return None
        return BehaviorEvent(
            type=event_type,
            # Yopilish INFO darajasida: hodisaning o'zi allaqachon
            # yozilgan, bu faqat unga davomiylik qo'shadi.
            severity=0,
            key=temporal.key,
            duration_ms=temporal.duration_ms,
            confidence=int(round(temporal.mean_confidence * 100)),
            track_id=meta.get("track_id"),
            payload={"closed": True, **{
                key: value for key, value in temporal.meta.items()
                if key not in ("event", "severity", "track_id")
            }},
        )
