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

from proctoring.identity import face_params
from proctoring.identity.candidate import normalize_reference, select_faces, selection_score

log = logging.getLogger(__name__)


def _score(reference: np.ndarray, embedding: np.ndarray) -> Optional[int]:
    """Etalonga o'xshashlik bali (`similarity_score` shkalasi) yoki `None`."""
    from services.face_engine import similarity_score

    try:
        cosine = float(np.dot(reference, embedding))
    except (TypeError, ValueError):
        return None
    return similarity_score(cosine) if np.isfinite(cosine) else None


@dataclass
class Face:
    """Kadrdagi bitta yuz."""

    bbox: np.ndarray                       # [x1, y1, x2, y2]
    det_score: float
    embedding: Optional[np.ndarray] = None
    #: `(106, 2)` yoki `(5, 2)` — nigoh moduli uchun.
    landmarks: Optional[np.ndarray] = None
    #: Etalonga o'xshashlik bali (0..100) — dalil belgisida "kim" degan
    #: savolga javob. Etalon yo'q yoki yuz e'tiborsiz bo'lsa `None`.
    score: Optional[int] = None

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
    #: Asosiy yuz — TALABGOR: etalonga mos yuz (`candidate.select_faces`),
    #: mos yuz bo'lmasa kadrdagi eng KATTASI (kameraga eng yaqin odam).
    primary: Optional[Face] = None
    #: `primary` etalon bo'yicha tanlanganmi (o'lcham bo'yicha emas).
    matched: bool = False
    #: `candidate.FaceSelection.state`: none | far | multiple | ok.
    state: str = "none"
    #: Talabgor yonidagi BEGONA SHAXSLAR (fon va uzoqdagilar kirmaydi).
    strangers: list = field(default_factory=list)
    #: Etalonga o'xshashlik (0..1). Etalon yo'q yoki yuz juda uzoq
    #: (`far` — embedding ishonchsiz) bo'lsa `None`.
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

    @property
    def comparable_embedding(self) -> Optional[np.ndarray]:
        """
        Davriy FaceID solishtiradigan vektor — FaceID ishchisi bilan bir xil
        qoida: faqat `ok` (bitta talabgor yuzi). Uzoqdagi yuz va begona
        shaxs bor kadr "solishtirib bo'lmadi".
        """
        if self.state != "ok" or self.primary is None:
            return None
        return self.primary.embedding

    @property
    def people(self) -> int:
        """Kadrda hisobga olinadigan odamlar: talabgor + begona shaxslar (fonsiz)."""
        return 0 if self.primary is None else 1 + len(self.strangers)

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

    def __init__(self, select_score: Optional[int] = None) -> None:
        self._reference: Optional[np.ndarray] = None
        #: Etalon bo'yicha tanlov bali (0..100) - imtihon chegarasidan
        #: (`candidate.selection_score`).
        self._select_score = selection_score(select_score)

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
        # Etalon NORMALLASHTIRILADI: `FaceEngine.detect` ham
        # normallashtirilgan vektor qaytaradi va cosine o'xshashlik
        # oddiy skalyar ko'paytmaga aylanadi.
        self._reference = normalize_reference(embedding)

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

        # KIM TALABGOR, KIM BEGONA — FaceID ishchisi bilan BITTA qoida
        # (`candidate.select_faces`): etalonga mos yuz talabgor (begona
        # odamning yuzi kattaroq bo'lsa ham), mos yuz bo'lmasa eng
        # kattasi; uning yonidagi yuzlar begona shaxs, uzoqdagi va
        # orqadagi yuzlar fon. Hamma yuz `faces` da qoladi.
        selection = select_faces(
            raw, self._reference,
            min_score=self._select_score,
            # Minimal kenglik — joriy profil qiymati (`face_params`).
            min_width=face_params.min_face_width(),
            width_of=lambda item: item.width,
            embedding_of=lambda item: item.embedding,
        )
        raw.sort(key=lambda item: item.width, reverse=True)
        primary = selection.primary

        if self._reference is not None:
            # Har bir HISOBGA OLINADIGAN yuzning bali: dalil belgisida
            # talabgor ham, begona shaxs ham raqam bilan ko'rinadi. Fon
            # va uzoqdagi yuzlar baholanmaydi — embedding ishonchsiz.
            for face in (primary, *selection.strangers):
                if selection.state != "far" and face.embedding is not None:
                    face.score = _score(self._reference, face.embedding)

        height, width = frame.shape[:2]
        center_x, center_y = primary.center
        result = IdentityResult(
            faces=raw,
            primary=primary,
            matched=selection.matched,
            state=selection.state,
            strangers=list(selection.strangers),
            face_ratio=primary.width / max(1, width),
            offset=float(
                max(
                    abs(center_x - width / 2) / (width / 2),
                    abs(center_y - height / 2) / (height / 2),
                )
            ),
        )

        # UZOQDAGI yuz (`far`) SOLISHTIRILMAYDI: ArcFace uni 112x112 ga
        # cho'zadi va ball sun'iy pasayadi — joyidan turgan talabgor
        # o'rnida kadrda qolgan uzoqdagi odam `face_mismatch` (jiddiylik 3)
        # berardi. FaceID ishchisida ham shu holat "yaqinroq keling".
        if (
            self._reference is not None
            and selection.state != "far"
            and primary.embedding is not None
        ):
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
