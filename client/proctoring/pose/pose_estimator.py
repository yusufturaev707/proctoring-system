"""
Poza va qo'llar (YOLOv8-pose, 17 nuqta).

NIMA UCHUN MEDIAPIPE EMAS. Dastlabki texnik topshiriqda MediaPipe
Pose/Hands ko'zda tutilgandi va undan voz kechildi:

  * MediaPipe IKKINCHI runtime (TFLite/XNNPACK). U GPU'ni ONNX
    bilan bo'lishmaydi - VRAM ikki marta band bo'ladi va ikkala
    modul ham sekinlashadi;
  * PyInstaller bilan paketlash og'riqli: `.tflite` resurslari,
    `protobuf` versiya konflikti va `numpy` pin'i bilan urush
    (loyihada `numpy==1.26.4` insightface uchun qadab qo'yilgan);
  * YOLOv8-pose obyekt detektori bilan BIR XIL kirish tayyorlash
    va bir xil NMS ishlatadi (`detection/ops.py`), ya'ni kod
    qayta ishlatiladi.

QO'L PANJASI KUZATILMAYDI - faqat BILAK (wrist). MediaPipe Hands
21 nuqtali panja beradi, COCO pozasi esa bilak bilan tugaydi.
Proktorlik uchun bu YETARLI: "qo'l stol ostida", "qo'l yuzga
tegdi", "qo'l telefon yonida" savollarining hammasi bilak
o'rni bilan hal bo'ladi. Barmoq harakatini kuzatish esa 30 FPS
da ham ishonchsiz va u soxta hodisalar manbai bo'lardi.

Bu modul XULOSA CHIQARMAYDI. U 17 nuqtani qaytaradi; "qo'l stol
ostida" degan qaror `behavior/` da (M4) va u siyosat chegaralariga
tayanadi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

from proctoring.detection.ops import Letterbox, nms, xywh_to_xyxy
from proctoring.inference.engine import ModelNotFound, OnnxEngine, build_engine

log = logging.getLogger(__name__)

#: COCO-17 kalit nuqtalari (YOLOv8-pose chiqishi shu tartibda).
KEYPOINTS = (
    "nose",
    "left_eye", "right_eye",
    "left_ear", "right_ear",
    "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow",
    "left_wrist", "right_wrist",
    "left_hip", "right_hip",
    "left_knee", "right_knee",
    "left_ankle", "right_ankle",
)

_INDEX = {name: position for position, name in enumerate(KEYPOINTS)}

#: Nuqta "ko'rindi" deb hisoblanadigan eng kichik ishonch.
#:
#: Past chegara xayoliy nuqtalarni o'tkazadi (model kadrdan
#: tashqaridagi bilakni "taxmin qiladi") va ular "qo'l stol
#: ostida" degan soxta xulosaga olib kelardi.
_VISIBLE = 0.5


@dataclass
class Pose:
    """Bitta odamning pozasi."""

    score: float
    bbox: np.ndarray                     # [x1, y1, x2, y2]
    #: `(17, 3)` — x, y, ishonch. Asl kadr koordinatalarida.
    keypoints: np.ndarray

    def point(self, name: str) -> Optional[tuple]:
        """
        Nuqta koordinatasi yoki `None` (ko'rinmasa).

        `None` va `(0, 0)` FARQ QILADI: ikkinchisi kadrning chap
        yuqori burchagi va uni "nuqta yo'q" deb talqin qilish
        stol ostidagi qo'lni yuqoriga ko'chirib yuborardi.
        """
        index = _INDEX.get(name)
        if index is None:
            return None
        x, y, confidence = self.keypoints[index]
        if confidence < _VISIBLE:
            return None
        return float(x), float(y)

    def visible(self, name: str) -> bool:
        return self.point(name) is not None

    @property
    def wrists(self) -> dict:
        return {
            "left": self.point("left_wrist"),
            "right": self.point("right_wrist"),
        }

    @property
    def shoulder_line(self) -> Optional[float]:
        """
        Yelkalar chizig'ining Y koordinatasi.

        "Qo'l stol ostida" xulosasi uchun tayanch: stol chetini
        kadrdan bilib bo'lmaydi, lekin yelkaga nisbatan pastda
        turgan bilak - ishonchli belgi. Qaror `behavior/` da.
        """
        left = self.point("left_shoulder")
        right = self.point("right_shoulder")
        points = [item[1] for item in (left, right) if item is not None]
        return float(np.mean(points)) if points else None

    def as_dict(self) -> dict:
        return {
            "score": round(float(self.score), 3),
            "bbox": [int(value) for value in self.bbox],
            "keypoints": {
                name: (
                    None
                    if self.keypoints[index][2] < _VISIBLE
                    else [int(self.keypoints[index][0]), int(self.keypoints[index][1])]
                )
                for name, index in _INDEX.items()
            },
        }


class PoseEstimator:
    """YOLOv8-pose."""

    def __init__(self, model_path, profile, *, confidence: float = 0.5,
                 iou_threshold: float = 0.45, max_people: int = 4) -> None:
        self._engine: OnnxEngine = build_engine(model_path, profile, name="pose")
        self._letterbox = Letterbox(size=profile.pose_size)
        self._confidence = float(confidence)
        self._iou = float(iou_threshold)
        # Kadrda ko'p odam bo'lishi mumkin emas, lekin model shovqinda
        # o'nlab "odam" topishi mumkin. Chegara ularni kesib tashlaydi
        # va keyingi qatlamlarni himoyalaydi.
        self._max_people = int(max_people)
        self._error = ""

    # ------------------------------------------------------------------
    @property
    def is_ready(self) -> bool:
        return self._engine.is_ready

    @property
    def error(self) -> str:
        return self._error

    @property
    def last_latency_ms(self) -> float:
        return self._engine.last_latency_ms

    def load(self) -> bool:
        try:
            self._engine.load()
        except ModelNotFound as exc:
            self._error = str(exc)
            log.warning("Poza baholash o'chirildi: %s", exc)
            return False
        except Exception as exc:
            self._error = "Modelni yuklab bo'lmadi: {}".format(str(exc)[:200])
            log.exception("Poza modelini yuklashda xato")
            return False
        return True

    def close(self) -> None:
        self._engine.close()

    # ------------------------------------------------------------------
    def estimate(self, frame: np.ndarray) -> list:
        if not self.is_ready or frame is None:
            return []
        try:
            tensor = self._letterbox.apply(frame)
            outputs = self._engine.run(tensor)
        except Exception:
            log.exception("Poza inference xatosi")
            return []
        return self._decode(outputs[0])

    def _decode(self, output: np.ndarray) -> list:
        """
        YOLOv8-pose chiqishi: `(1, 56, N)`.

        56 = 4 (ramka) + 1 (odam ishonchi) + 17*3 (nuqta: x, y, conf).
        Obyekt detektoridan farqi shu: bu yerda BITTA klass bor
        ("person"), shuning uchun klass ballari o'rniga bitta ishonch
        turadi va undan keyin darhol nuqtalar boshlanadi.
        """
        array = np.asarray(output)
        if array.ndim == 3:
            array = array[0]
        if array.ndim != 2:
            log.error("Poza chiqishining shakli kutilmagan: %s", array.shape)
            return []
        if array.shape[0] < array.shape[1]:
            array = array.T

        expected = 5 + len(KEYPOINTS) * 3
        if array.shape[1] != expected:
            log.error(
                "Poza chiqishida %s ustun kutilgandi, %s keldi — model "
                "YOLOv8-pose emasmi?",
                expected, array.shape[1],
            )
            return []

        scores = array[:, 4]
        keep = scores >= self._confidence
        if not keep.any():
            return []

        array = array[keep]
        scores = scores[keep]
        boxes = xywh_to_xyxy(array[:, :4])

        keep_index = nms(boxes, scores, self._iou)[: self._max_people]
        if not keep_index:
            return []

        boxes = self._letterbox.restore(boxes[keep_index])
        keypoints = array[keep_index, 5:].reshape(len(keep_index), len(KEYPOINTS), 3)
        # Nuqtalar ham letterbox ichida - ularni ham qaytarish kerak.
        # Ishonch ustuni (`[..., 2]`) O'ZGARMAYDI.
        keypoints[..., :2] = self._letterbox.restore_points(keypoints[..., :2])

        return [
            Pose(score=float(scores[position]), bbox=boxes[index], keypoints=keypoints[index])
            for index, position in enumerate(keep_index)
        ]
