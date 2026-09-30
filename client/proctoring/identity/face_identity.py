"""
Shaxs moduli — mavjud `FaceEngine` ustidagi yupqa qatlam.

MODEL QAYTA YUKLANMAYDI. `services/face_engine.py` allaqachon
InsightFace `buffalo_l` ni yuklaydi, u singleton va ONNX sessiyasi
~300 MB oladi. Pipeline uchun ikkinchi nusxa ochish xotirani ikki
barobar oshirar va GTX 1660 Super (6 GB) da YOLO uchun joy
qoldirmasdi.

BU QATLAM NIMA QO'SHADI:

  * pipeline uchun BIR XIL shakl. Qolgan modullar (`detection`,
    `pose`, `gaze`) dataclass qaytaradi; `FaceEngine` esa lug'at.
    Farqni pipeline ichida hal qilish har bir modul uchun alohida
    shox degani edi;
  * NIGOH UCHUN NUQTALAR. `FaceEngine.detect` faqat embedding va
    ramka qaytaradi, `gaze` esa 106 nuqtali landmark talab
    qiladi. Ular InsightFace obyektida bor, lekin tashqariga
    chiqarilmagan;
  * yuz o'lchami va kadrdagi o'rni — "juda uzoq", "juda yaqin",
    "kadrdan chiqdi" xulosalari uchun.

XULOSA CHIQARILMAYDI. Bu yerda faqat o'xshashlik SONI (cosine)
hisoblanadi. "Yuz mos kelmadi" degan HODISA temporal qatlamda
tug'iladi (`behavior_analyzer`, chegara imtihon profilidan), qaror
esa serverda: u xabar qilingan ballni `faceid_min_score_exam` bilan
solishtiradi va chetlashtirishni hal qiladi. Solishtirishning o'zi
ikkala holatda ham SHU YERDA - ikkala vektor ham clientda.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class Face:
    """Kadrdagi bitta yuz."""

    bbox: np.ndarray                       # [x1, y1, x2, y2]
    det_score: float
    embedding: Optional[np.ndarray] = None
    #: `(106, 2)` yoki `(5, 2)` — nigoh moduli uchun.
    landmarks: Optional[np.ndarray] = None

    @property
    def width(self) -> int:
        return int(self.bbox[2] - self.bbox[0])

    @property
    def center(self) -> tuple:
        return (
            float((self.bbox[0] + self.bbox[2]) / 2),
            float((self.bbox[1] + self.bbox[3]) / 2),
        )


@dataclass
class IdentityResult:
    """Bitta kadr uchun shaxs holati."""

    faces: list = field(default_factory=list)
    #: Asosiy yuz — kadrdagi eng KATTASI (kameraga eng yaqin odam).
    primary: Optional[Face] = None
    #: Etalonga o'xshashlik (0..1). Etalon yo'q bo'lsa `None`.
    similarity: Optional[float] = None
    #: Yuzning kadr kengligiga nisbati — "uzoq/yaqin" uchun.
    face_ratio: float = 0.0
    #: Markazdan chetlashish (0..1) — "kadrdan chiqmoqda" uchun.
    offset: float = 0.0

    @property
    def count(self) -> int:
        return len(self.faces)

    @property
    def has_face(self) -> bool:
        return self.primary is not None

    def as_dict(self) -> dict:
        return {
            "faces": self.count,
            "similarity": (
                None if self.similarity is None else round(float(self.similarity), 3)
            ),
            "face_ratio": round(self.face_ratio, 3),
            "offset": round(self.offset, 3),
            "bbox": (
                [int(value) for value in self.primary.bbox] if self.primary else None
            ),
        }


class FaceIdentity:
    """Pipeline uchun shaxs moduli."""

    def __init__(self) -> None:
        self._reference: Optional[np.ndarray] = None

    # ------------------------------------------------------------------
    @property
    def is_ready(self) -> bool:
        from services.face_engine import FaceEngine

        return FaceEngine().is_ready

    @property
    def has_reference(self) -> bool:
        return self._reference is not None

    def set_reference(self, embedding) -> None:
        """
        Sessiya etaloni.

        FaceID sahifasida olingan embedding shu yerga beriladi.
        `None` - etalonsiz rejim: o'xshashlik hisoblanmaydi, lekin
        yuz bor-yo'qligi va soni baribir kuzatiladi.
        """
        if embedding is None:
            self._reference = None
            return
        vector = np.asarray(embedding, dtype=np.float32).ravel()
        norm = float(np.linalg.norm(vector))
        # Etalon NORMALLASHTIRILADI: `FaceEngine.detect` ham
        # normallashtirilgan vektor qaytaradi va cosine o'xshashlik
        # oddiy skalyar ko'paytmaga aylanadi.
        self._reference = (vector / norm) if norm > 0 else None

    def reset(self) -> None:
        self._reference = None

    # ------------------------------------------------------------------
    def analyse(self, frame: np.ndarray) -> IdentityResult:
        """Kadrni tahlil qiladi. Istisno TASHLAMAYDI."""
        if frame is None or not self.is_ready:
            return IdentityResult()

        from services.face_engine import FaceEngine

        engine = FaceEngine()
        try:
            raw = self._detect_with_landmarks(engine, frame)
        except Exception:
            log.exception("Yuz aniqlashda xato")
            return IdentityResult()

        if not raw:
            return IdentityResult()

        # Eng katta yuz — asosiy. Kadrga tasodifan tushgan uzoqdagi
        # odam (koridordan o'tayotgan) talabgorning o'rnini
        # egallamasligi kerak.
        raw.sort(key=lambda item: item.width, reverse=True)
        primary = raw[0]

        height, width = frame.shape[:2]
        center_x, center_y = primary.center
        result = IdentityResult(
            faces=raw,
            primary=primary,
            face_ratio=primary.width / max(1, width),
            offset=float(
                max(
                    abs(center_x - width / 2) / (width / 2),
                    abs(center_y - height / 2) / (height / 2),
                )
            ),
        )

        if self._reference is not None and primary.embedding is not None:
            result.similarity = float(np.dot(self._reference, primary.embedding))
        return result

    # ------------------------------------------------------------------
    @staticmethod
    def _detect_with_landmarks(engine, frame: np.ndarray) -> list:
        """
        InsightFace natijasini NUQTALAR bilan birga oladi.

        `FaceEngine.detect` nuqtalarni tashlab yuboradi (ular unga
        kerak emas edi). Bu yerda `app.get()` to'g'ridan-to'g'ri
        chaqiriladi va nuqtalar saqlanadi - nigoh moduli aynan
        ularsiz ishlay olmaydi.

        `landmark_2d_106` FAQAT `allowed_modules` ga qo'shilgan
        bo'lsa mavjud (`face_engine.initialize` uni ataylab
        o'chirgan - o'shanda u kerak emas edi). Yo'q bo'lsa 5
        nuqtali `kps` ishlatiladi va bosh holati ANIQLIGI pastroq,
        lekin baribir hisoblanadi.
        """
        # `engine.analyze` — `_app.get()` emas: GPU ishlash paytida
        # yiqilsa CPU'ga o'tish qoidasi dvigatelda (`FaceEngine._run`)
        # va u bu yo'lni ham qamrashi kerak.
        analyze = getattr(engine, "analyze", None)
        if analyze is None:
            return []

        faces = []
        for item in analyze(frame):
            embedding = getattr(item, "embedding", None)
            if embedding is not None:
                norm = float(np.linalg.norm(embedding))
                embedding = (embedding / norm).astype(np.float32) if norm > 0 else None

            landmarks = getattr(item, "landmark_2d_106", None)
            if landmarks is None:
                landmarks = getattr(item, "kps", None)

            faces.append(
                Face(
                    bbox=np.asarray(item.bbox, dtype=np.float32),
                    det_score=float(item.det_score),
                    embedding=embedding,
                    landmarks=(
                        np.asarray(landmarks, dtype=np.float32)
                        if landmarks is not None
                        else None
                    ),
                )
            )
        return faces
