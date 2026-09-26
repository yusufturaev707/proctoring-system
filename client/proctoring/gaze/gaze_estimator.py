"""
Nigoh: talabgor ekranga qaraydimi.

ASOSIY QAROR — MUTLAQ EMAS, NISBIY BURCHAK.

`head_pose.py` qaytaradigan gradus mutlaq ma'noda ±10-15 gacha
adashishi mumkin (kamera kalibrlanmagan, sabab o'sha modulda).
Bundan tashqari mutlaq nolning o'zi ham ma'nosiz: kamera monitor
tepasida, yonida yoki pastda turishi mumkin va "ekranga qarash"
har bir ish o'rnida boshqa burchak beradi.

Shuning uchun BOSHLANG'ICH HOLAT o'lchanadi: sessiya boshida
talabgor ekranga qarab turganda bir necha soniya davomida
o'rtacha yaw/pitch yig'iladi va u NOL deb qabul qilinadi. Keyingi
barcha xulosalar shu noldan OG'ISHGA nisbatan chiqariladi.

Bu bitta o'zgarish butun modulning ishonchliligini hal qiladi:
mutlaq chegara bilan monitor yonida turgan kamerali mashinada
talabgor DOIM "chetga qaragan" bo'lardi.

MODUL XULOSA CHIQARMAYDI. U "hozir og'ish 34 gradus" deydi;
"uzoq vaqt chetga qaradi" degan hodisa temporal qatlamda (M4)
tug'iladi va u siyosat chegaralariga tayanadi.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np

from proctoring.gaze.head_pose import HeadPose, estimate_head_pose

log = logging.getLogger(__name__)

#: Kalibrlash uchun yig'iladigan namunalar soni.
#:
#: 30 namuna 10 FPS da ~3 soniya. Kamroq bo'lsa tasodifiy harakat
#: (bosh qimirlashi) nolni siljitadi; ko'proq bo'lsa kalibrlash
#: sezilarli kechikadi va uning davomida nigoh baholanmaydi.
_CALIBRATION_SAMPLES = 30

#: Kalibrlashda qabul qilinadigan eng katta tarqoqlik (gradus).
#:
#: Talabgor kalibrlash paytida qimirlab tursa, o'rtacha ma'nosiz
#: bo'ladi. Bunday holatda kalibrlash BEKOR qilinadi va mutlaq
#: qiymatlarga qaytiladi - noto'g'ri nolga tayanishdan ko'ra
#: aniqroq.
_MAX_CALIBRATION_STD = 12.0

#: Ko'z ochiqligini baholash chegarasi (EAR - eye aspect ratio).
_EYE_CLOSED_RATIO = 0.16

#: `2d106det` dagi ko'z konturlari (yuqori/pastki qovoq va burchaklar).
_LEFT_EYE = (35, 36, 33, 37, 39, 42)
_RIGHT_EYE = (89, 90, 87, 91, 93, 96)


def _angle_delta(value: float, baseline: float) -> float:
    """
    Ikki burchak ayirmasi, ±180 chegarasini hisobga olib.

    Oddiy ayirish burchak ±180 dan o'tganda 359 gradusli "og'ish"
    beradi. `head_pose._normalize_pitch` bu holatni pitch uchun
    allaqachon yopgan, lekin yaw uchun u qolgan: talabgor deyarli
    yon tomonga burilganda (yaw ~180 ga yaqin) ayirma sakrardi.

    Amalda bunday burilish imtihonda uchramaydi, lekin sakragan
    qiymat "uzoq vaqt chetga qaradi" hodisasini beradi - va uni
    keyinchalik bayonnomadan tushuntirib bo'lmasdi.
    """
    delta = (value - baseline + 180.0) % 360.0 - 180.0
    return float(delta)


@dataclass
class GazeResult:
    """Bitta kadr uchun nigoh holati."""

    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    #: Kalibrlangan noldan og'ish (gradus). Kalibrlanmagan bo'lsa
    #: mutlaq qiymatga teng.
    yaw_offset: float = 0.0
    pitch_offset: float = 0.0
    #: Umumiy og'ish - `looking_away` chegarasi shunga qo'llanadi.
    deviation: float = 0.0
    eyes_open: Optional[bool] = None
    calibrated: bool = False
    valid: bool = False

    @property
    def direction(self) -> str:
        """
        Og'ish YO'NALISHI - hodisa matnida ishlatiladi.

        "Chetga qaradi" degan xabar operatorga kam narsa aytadi;
        "o'ngga qaradi" esa u ko'rishi kerak bo'lgan tomonni
        ko'rsatadi (masalan qo'shni stol).
        """
        if not self.valid:
            return ""
        if abs(self.yaw_offset) >= abs(self.pitch_offset):
            return "right" if self.yaw_offset > 0 else "left"
        return "up" if self.pitch_offset > 0 else "down"

    def as_dict(self) -> dict:
        return {
            "yaw": round(self.yaw, 1),
            "pitch": round(self.pitch, 1),
            "roll": round(self.roll, 1),
            "deviation": round(self.deviation, 1),
            "direction": self.direction,
            "eyes_open": self.eyes_open,
            "calibrated": self.calibrated,
        }


class GazeEstimator:
    """
    Bosh holati + kalibrlash + ko'z ochiqligi.

    Sessiya boshida `reset()` chaqiriladi: kalibrlash HAR BIR
    talabgor uchun qaytadan bajarilishi kerak - odamlar bo'yi va
    o'tirish holati boshqacha.
    """

    def __init__(self) -> None:
        self._samples: deque = deque(maxlen=_CALIBRATION_SAMPLES)
        self._baseline: Optional[tuple] = None
        self._calibration_failed = False
        self._started_at = time.monotonic()

    # ------------------------------------------------------------------
    @property
    def is_calibrated(self) -> bool:
        return self._baseline is not None

    @property
    def baseline(self) -> Optional[tuple]:
        return self._baseline

    def reset(self) -> None:
        self._samples.clear()
        self._baseline = None
        self._calibration_failed = False
        self._started_at = time.monotonic()

    # ------------------------------------------------------------------
    def estimate(self, landmarks: np.ndarray, frame_shape: tuple) -> GazeResult:
        """Kadrdagi yuz nuqtalaridan nigoh holati."""
        pose = estimate_head_pose(landmarks, frame_shape)
        if not pose.valid:
            return GazeResult()

        self._collect(pose)

        yaw_offset, pitch_offset = pose.yaw, pose.pitch
        if self._baseline is not None:
            yaw_offset = _angle_delta(pose.yaw, self._baseline[0])
            pitch_offset = _angle_delta(pose.pitch, self._baseline[1])

        return GazeResult(
            yaw=pose.yaw,
            pitch=pose.pitch,
            roll=pose.roll,
            yaw_offset=yaw_offset,
            pitch_offset=pitch_offset,
            # Umumiy og'ish - ikki o'q bo'yicha evklid masofasi.
            # Alohida chegara qo'yish "biroz o'ngga va biroz pastga"
            # holatini o'tkazib yuborardi, holbuki u ikkalasidan
            # ham kattaroq og'ish.
            deviation=float(np.hypot(yaw_offset, pitch_offset)),
            eyes_open=self._eyes_open(landmarks),
            calibrated=self._baseline is not None,
            valid=True,
        )

    # ------------------------------------------------------------------
    def _collect(self, pose: HeadPose) -> None:
        """Kalibrlash namunalarini yig'adi."""
        if self._baseline is not None or self._calibration_failed:
            return

        self._samples.append((pose.yaw, pose.pitch))
        if len(self._samples) < _CALIBRATION_SAMPLES:
            return

        values = np.array(self._samples, dtype=np.float32)
        spread = float(values.std(axis=0).max())
        if spread > _MAX_CALIBRATION_STD:
            # Talabgor qimirlab turgan - o'rtacha ma'nosiz.
            # Kalibrlashni BEKOR qilamiz va mutlaq qiymatlarga
            # qaytamiz: noto'g'ri nolga tayanish undan battar.
            self._calibration_failed = True
            log.info(
                "Nigoh kalibrlanmadi: tarqoqlik %.1f gradus (chegara %.1f). "
                "Mutlaq burchaklar ishlatiladi.",
                spread, _MAX_CALIBRATION_STD,
            )
            return

        self._baseline = (float(values[:, 0].mean()), float(values[:, 1].mean()))
        log.info(
            "Nigoh kalibrlandi: yaw=%.1f pitch=%.1f (%.1f s)",
            self._baseline[0], self._baseline[1], time.monotonic() - self._started_at,
        )

    def _eyes_open(self, landmarks: np.ndarray) -> Optional[bool]:
        """
        Ko'z ochiqligi (EAR - eye aspect ratio).

        `None` — o'lchab bo'lmadi (nuqtalar yetarli emas). Uni
        `False` bilan almashtirish "ko'zlar yumuq" degan soxta
        hodisani har bir 5 nuqtali kadrda berardi.

        EAR — ko'zning balandligi/kengligi nisbati. Ko'z yumilganda
        balandlik nolga intiladi, kenglik esa o'zgarmaydi.
        """
        points = np.asarray(landmarks, dtype=np.float32)
        if points.ndim != 2 or len(points) < 106:
            return None

        ratios = []
        for indices in (_LEFT_EYE, _RIGHT_EYE):
            try:
                selected = points[list(indices), :2]
            except IndexError:
                return None
            width = float(np.linalg.norm(selected[0] - selected[1]))
            if width <= 1e-3:
                continue
            height = float(np.mean([
                np.linalg.norm(selected[2] - selected[3]),
                np.linalg.norm(selected[4] - selected[5]),
            ]))
            ratios.append(height / width)

        if not ratios:
            return None
        return bool(np.mean(ratios) > _EYE_CLOSED_RATIO)
