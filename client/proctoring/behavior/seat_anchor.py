"""
O'rindiq kalibrlashi — kadrdagi odamlardan qaysi biri TALABGOR.

MUAMMO. Obyekt kamerasi (IP kamera) bitta ish joyi TEPASIDA qat'iy
turadi. Ilgari talabgor "eng baland ramka" deb olinardi, tepadan
qaragan kamerada esa ramka balandligi odamning bo'yini emas, KAMERAGACHA
MASOFANI bildiradi: stol yonida tik turgan odam kameraga yaqinroq va
kattaroq chiqadi. Natijada o'tirgan talabgorning o'zi «Begona odam»
bo'lib belgilanardi, yonidagi odam esa "talabgor" hisoblanardi.

Kadrdagi o'rin ham (markaz) ishonchli emas: kamera stolga odatda qiya
qaraydi va talabgor kadr chetiga yaqin o'tirishi mumkin.

YECHIM — nigoh kalibrlashi bilan bir xil naqsh (`gaze/`): sessiya
boshida boshlang'ich holat o'lchanadi va keyingi hamma narsa shunga
nisbatan. Talabgor — ish joyida BARQAROR turgan odam: kadrda uzluksiz
bor va deyarli qimirlamaydi. Imtihon boshida mashina yonida turgan
operator esa bir necha soniyada ketadi yoki harakatlanadi. Shu odamning
ramka markazi "o'rindiq nuqtasi" bo'lib sessiya davomida MUZLATILADI
(kamera siljimaydi) va keyin talabgor — o'rindiqqa eng yaqin odam.

TAYANCH NUQTA — RAMKA MARKAZI, pose nuqtasi emas. Izlar (`tracks`) har
kadrda ramka beradi, pose esa boshqa chastotada keladi va ba'zi
kadrlarda yo'q. Kalibrlashda va keyingi kadrlarda BIR XIL turdagi nuqta
ishlatilishi shart — aks holda o'rindiq bilan solishtirish ma'nosiz.

KOORDINATALAR KADRGA NISBATAN (0..1) — dalil belgilari bilan bir xil:
rezolyutsiyadan mustaqil chegaralar.

Kalibrlash BIR MA'NOLI bo'lmasa (ikki barqaror odam yoki hech kim)
natija QABUL QILINMAYDI va oyna qaytadan boshlanadi. Noto'g'ri
o'rindiqqa tayanish undan battar: u butun imtihon davomida noto'g'ri
odamni talabgor qilib qo'yardi. Shu vaqt ichida zaxira qoida ishlaydi —
markazga yaqinlik x yuza.

Modul sof mantiq: numpy'ga ham, Qt'ga ham bog'liq emas.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from statistics import median, pstdev
from typing import Optional

log = logging.getLogger(__name__)

#: Kalibrlash oynasi (s). Operator "Boshlash" ni bosib ketishiga yetadi,
#: talabgorning barqarorligini ko'rishga ham.
CALIBRATION_SECONDS = 15.0

#: Oynadagi kadrlarning shuncha ulushida ko'ringan odamgina nomzod.
_MIN_PRESENCE = 0.8

#: Markaz tarqoqligi (kadrga nisbatan, std). O'tirgan odam yozayotganda
#: ham ~0.01-0.02 qimirlaydi; yonidan o'tgan odam 0.1+.
_MAX_SPREAD = 0.04

#: Kalibrlash uchun kamida shuncha kadr: kam kadrdagi "barqarorlik"
#: tasodif bo'lishi mumkin (CPU rejimida obyekt tahlili siyrak).
_MIN_FRAMES = 5

#: Ikki barqaror nomzoddan birini tanlash uchun uning bali ikkinchisidan
#: kamida shuncha barobar katta bo'lishi kerak. Aks holda — noaniq.
_DOMINANCE = 1.5

#: O'rindiqdan shu masofagacha (kadr diagonaliga nisbatan) turgan odam
#: talabgor bo'la oladi. Talabgor stulda suriladi, egiladi — radius
#: shunga yetadi, lekin qo'shni joyni qamrab olmaydi.
_SEAT_RADIUS = 0.22


def _anchor(bbox, width: int, height: int) -> Optional[tuple]:
    """Ramka markazi — kadrga nisbatan (0..1)."""
    if bbox is None or not width or not height:
        return None
    try:
        x1, y1, x2, y2 = (float(value) for value in list(bbox)[:4])
    except (TypeError, ValueError):
        return None
    return ((x1 + x2) / 2.0 / width, (y1 + y2) / 2.0 / height)


def _area(bbox, width: int, height: int) -> float:
    """Ramka yuzasi — kadrga nisbatan (0..1)."""
    try:
        x1, y1, x2, y2 = (float(value) for value in list(bbox)[:4])
    except (TypeError, ValueError):
        return 0.0
    if not width or not height:
        return 0.0
    return max(0.0, x2 - x1) * max(0.0, y2 - y1) / float(width * height)


def fallback_score(bbox, width: int, height: int) -> float:
    """
    Kalibrlashsiz baho: markazga yaqinlik x yuza.

    Faqat yuza — "eng yaqin odam" (eski xatoning o'zi); faqat markaz —
    kadr o'rtasidan o'tgan har kim. Ko'paytma ikkalasini muvozanatlaydi.
    Yaqinlik pastki chegarali: kadr chetidagi talabgor ham nol olmasligi
    kerak.
    """
    anchor = _anchor(bbox, width, height)
    if anchor is None:
        return 0.0
    distance = math.hypot(anchor[0] - 0.5, anchor[1] - 0.5) / math.hypot(0.5, 0.5)
    return _area(bbox, width, height) * max(0.05, 1.0 - distance)


@dataclass
class _TrackStats:
    frames: int = 0
    anchors: list = field(default_factory=list)
    areas: list = field(default_factory=list)


class SeatAnchor:
    """Bitta kamera uchun o'rindiq nuqtasi va talabgorni tanlash."""

    def __init__(self, *, calibration_seconds: float = CALIBRATION_SECONDS) -> None:
        self._calibration_seconds = float(calibration_seconds)
        self.reset()

    def reset(self) -> None:
        """Yangi sessiya — o'rindiq qaytadan o'lchanadi."""
        self._seat: Optional[tuple] = None
        self._track_id = None
        #: Birinchi kuzatuv — "boshlanish sukuti" shundan hisoblanadi.
        self._first_seen: Optional[float] = None
        self._window_start: Optional[float] = None
        self._window_frames = 0
        self._stats: dict = {}

    # ------------------------------------------------------------------
    @property
    def calibrated(self) -> bool:
        return self._seat is not None

    @property
    def seat(self) -> Optional[tuple]:
        return self._seat

    def warming_up(self, now: float) -> bool:
        """
        Imtihonning birinchi `CALIBRATION_SECONDS` soniyasi, o'rindiq hali yo'q.

        Shu vaqt ichida "ikkinchi odam" hisoblanmaydi: imtihon boshida
        operator mashina yonida turadi va bu kutilgan hol. Sukut CHEGARALI
        — birinchi oyna tugagach kalibrlash noaniq qolgan bo'lsa ham
        zaxira qoida bilan kuzatuv to'liq ishlaydi.
        """
        if self.calibrated:
            return False
        if self._first_seen is None:
            # Hali birorta kuzatuv yo'q — sukut shu zahotidan boshlanadi.
            return True
        return (now - self._first_seen) < self._calibration_seconds

    # ------------------------------------------------------------------
    def observe(self, persons: list, width: int, height: int, now: float) -> None:
        """
        Kalibrlash uchun kuzatuv (faqat odam izlari, `track_id` bilan).

        Bo'sh ro'yxat ham kadr hisoblanadi: odam ko'rinmagan kadrlar
        "uzluksiz bor" degan shartni to'g'ri kamaytiradi.
        """
        if self.calibrated or not width or not height:
            return
        if self._first_seen is None:
            self._first_seen = now
        if self._window_start is None:
            self._window_start = now

        self._window_frames += 1
        for track in persons:
            track_id = getattr(track, "track_id", None)
            anchor = _anchor(getattr(track, "bbox", None), width, height)
            if track_id is None or anchor is None:
                continue
            stats = self._stats.setdefault(track_id, _TrackStats())
            stats.frames += 1
            stats.anchors.append(anchor)
            stats.areas.append(_area(track.bbox, width, height))

        if (now - self._window_start) >= self._calibration_seconds:
            self._try_calibrate(now)

    def _try_calibrate(self, now: float) -> None:
        frames = self._window_frames
        candidates = []
        if frames >= _MIN_FRAMES:
            for track_id, stats in self._stats.items():
                if stats.frames < frames * _MIN_PRESENCE or len(stats.anchors) < 2:
                    continue
                spread = max(
                    pstdev(point[0] for point in stats.anchors),
                    pstdev(point[1] for point in stats.anchors),
                )
                if spread > _MAX_SPREAD:
                    continue
                seat = (
                    median(point[0] for point in stats.anchors),
                    median(point[1] for point in stats.anchors),
                )
                distance = math.hypot(seat[0] - 0.5, seat[1] - 0.5) / math.hypot(0.5, 0.5)
                score = median(stats.areas) * max(0.05, 1.0 - distance)
                candidates.append((score, track_id, seat, spread))

        candidates.sort(key=lambda item: item[0], reverse=True)
        if candidates and (
            len(candidates) == 1 or candidates[0][0] >= candidates[1][0] * _DOMINANCE
        ):
            score, track_id, seat, spread = candidates[0]
            self._seat = (round(seat[0], 4), round(seat[1], 4))
            self._track_id = track_id
            log.info(
                "O'rindiq kalibrlandi: (%.2f, %.2f), iz #%s, tarqoqlik %.3f, %s kadr",
                seat[0], seat[1], track_id, spread, frames,
            )
        else:
            # Noaniq: yana bir oyna. Zaxira qoida shu vaqt ichida ishlaydi.
            log.info(
                "O'rindiq kalibrlanmadi (%s nomzod, %s kadr) - qayta urinish",
                len(candidates), frames,
            )
            self._window_start = now
            self._window_frames = 0
        self._stats.clear()

    # ------------------------------------------------------------------
    def pick(self, boxes: list, width: int, height: int,
             track_ids: Optional[list] = None) -> Optional[int]:
        """
        Ro'yxatdagi qaysi ramka talabgorniki — indeks yoki `None`.

        Kalibrlangan: avval o'sha IZ (o'rindiq radiusida bo'lsa), keyin
        o'rindiqqa eng yaqini. Talabgor o'rindiqdan ketgan bo'lsa `None`
        — bu xona kamerasining xulosasi emas, "joyida yo'q" ni asosiy
        kamera (`no_face`) aytadi.

        Kalibrlanmagan: zaxira baho (`fallback_score`).
        """
        if not boxes:
            return None
        if not self.calibrated:
            scores = [fallback_score(box, width, height) for box in boxes]
            best = max(range(len(boxes)), key=scores.__getitem__)
            return best if scores[best] > 0 else None

        diagonal = math.hypot(1.0, 1.0)
        distances = []
        for box in boxes:
            anchor = _anchor(box, width, height)
            distances.append(
                math.inf if anchor is None
                else math.hypot(anchor[0] - self._seat[0], anchor[1] - self._seat[1]) / diagonal
            )

        if track_ids is not None and self._track_id is not None:
            for index, track_id in enumerate(track_ids):
                if track_id == self._track_id and distances[index] <= _SEAT_RADIUS:
                    return index

        nearest = min(range(len(boxes)), key=distances.__getitem__)
        if distances[nearest] > _SEAT_RADIUS:
            return None
        if track_ids is not None:
            # Iz uzilib qayta tug'ilgan (to'silish, kadrdan chiqib-kirish):
            # o'rindiqdagi yangi iz davom etadi.
            self._track_id = track_ids[nearest]
        return nearest
