"""
InsightFace dvigateli.

Yuklash mexanizmi referens loyihadan olingan (`face-id-desktop`):
model bundle ichidan olinadi, yuklash fon thread'ida ketadi va UI
bloklanmaydi.

Referensdan farqi - `torch` YO'Q. U yerda 1:N qidiruv bor edi (minglab
talaba galereyasi), shuning uchun GPU tensor kerak edi. Bu yerda esa
faqat 1:1 solishtirish: pasport rasmi va kameradagi yuz. Ikkita 512
o'lchamli vektorning skalyar ko'paytmasi uchun numpy ortig'i bilan
yetadi, torch esa bundle'ga ~2 GB qo'shadi.
"""

from __future__ import annotations

import base64
import binascii
import logging
from typing import Optional

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from config import (
    FACE_DET_SIZE,
    FACE_DET_THRESH,
    FACE_MATCH_THRESHOLD,
    FACE_MODEL_NAME,
    FACE_MODEL_ROOT,
)
from core.bundle_paths import is_frozen
from core.singleton import SingletonMeta

log = logging.getLogger(__name__)


def cosine_to_percent(similarity: float) -> int:
    """
    Cosine similarity [-1..1] -> foiz [0..100].

    Backend `score` ni 0..100 oralig'ida kutadi (`FaceVerifySerializer`).
    Manfiy o'xshashlik "umuman boshqa odam" degani, shuning uchun 0 ga
    siqiladi. sqrt (gamma 0.5) - past qiymatlarni cho'zib, operatorga
    farqni ko'rsatish uchun; chegara baribir cosine ustida tekshiriladi.
    """
    value = max(0.0, min(1.0, float(similarity or 0.0)))
    return int(round((value ** 0.5) * 100))


class FaceEngineLoader(QThread):
    """
    Modelni fon thread'ida yuklaydi.

    Dastur ishga tushishi bilan boshlanadi va login formasi bilan
    PARALLEL ketadi: operator login/parol yozguncha model tayyor bo'ladi,
    ya'ni kutish vaqti bekorga sarflanmaydi.
    """

    progress = pyqtSignal(str)
    finished_loading = pyqtSignal(bool, str)  # (muvaffaqiyat, xabar)

    def run(self) -> None:
        try:
            engine = FaceEngine()
            requested = engine.providers()
            expected = "GPU (CUDA)" if "CUDAExecutionProvider" in requested else "CPU"
            self.progress.emit("Model yuklanmoqda ({})...".format(expected))
            engine.initialize()
            # Xabar HAQIQIY qurilmani aytadi: CUDA so'ralib, sessiya
            # CPU'da ochilgan bo'lishi mumkin.
            self.finished_loading.emit(True, "Model tayyor - {}".format(engine.device_name))
        except Exception as exc:
            log.exception("FaceEngine yuklashda xato")
            self.finished_loading.emit(False, "Model yuklanmadi: {}".format(str(exc)[:120]))


class FaceEngine(metaclass=SingletonMeta):
    """
    Yuz aniqlash va solishtirish.

    Singleton: ONNX sessiyasi ~300 MB xotira oladi va uni har sahifada
    qayta yaratish mumkin emas.
    """

    def __init__(self) -> None:
        self._app = None
        self._initialized = False
        self._use_gpu = False
        #: `prepare()` dan keyin sessiya HAQIQATDA ishlatayotgan provayderlar.
        self._active_providers: list = []
        self._threshold = float(FACE_MATCH_THRESHOLD)

    # ------------------------------------------------------------------
    @property
    def is_ready(self) -> bool:
        return self._initialized

    @property
    def threshold(self) -> float:
        return self._threshold

    def set_threshold(self, value: float) -> None:
        try:
            self._threshold = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            pass

    @property
    def device_name(self) -> str:
        if not self._initialized:
            return "-"
        return "GPU (CUDA)" if self._use_gpu else "CPU"

    @property
    def active_providers(self) -> list:
        return list(self._active_providers)

    @staticmethod
    def providers() -> list:
        """
        ONNX Runtime provayderlari.

        `CUDAExecutionProvider` ro'yxatda bo'lishi u ISHLASHINI anglatmaydi
        (CUDA DLL'lari yetishmasligi mumkin), lekin bu holatda
        InsightFace o'zi CPU'ga tushadi - shuning uchun ro'yxatga qo'shamiz.
        """
        try:
            import onnxruntime as ort

            available = ort.get_available_providers()
            log.info("ONNX provayderlari: %s", available)
            if "CUDAExecutionProvider" in available:
                return ["CUDAExecutionProvider", "CPUExecutionProvider"]
        except Exception:
            log.warning("onnxruntime provayderlarini o'qib bo'lmadi", exc_info=True)
        return ["CPUExecutionProvider"]

    def initialize(self) -> None:
        """Modelni yuklaydi. FAQAT fon thread'idan chaqiriladi."""
        if self._initialized:
            return
        from insightface.app import FaceAnalysis

        providers = self.providers()
        self._use_gpu = "CUDAExecutionProvider" in providers
        ctx_id = 0 if self._use_gpu else -1

        bundled = FACE_MODEL_ROOT / "models" / FACE_MODEL_NAME
        if not bundled.exists():
            # Frozen rejimda qat'iy: imtihon markazi kompyuteri offline
            # bo'lishi mumkin va InsightFace 30+ soniya timeout bilan
            # tushunarsiz xato beradi. Dev rejimda avtomatik yuklab olish
            # qulayroq, shuning uchun faqat ogohlantiramiz.
            if is_frozen():
                raise FileNotFoundError(
                    "Model fayllari topilmadi: {}. Build'da models/{} "
                    "paketlanmagan.".format(bundled, FACE_MODEL_NAME)
                )
            log.warning("Bundle'da model yo'q (%s) - internetdan yuklanadi", bundled)

        # `allowed_modules` - buffalo_l to'plamida 5 ta model bor, bizga
        # esa faqat ikkitasi kerak. Qolganlari (landmark_3d_68 ~143 MB,
        # landmark_2d_106, genderage) yuz yoshi/jinsi va 3D nuqtalar
        # uchun - proktorlikda ishlatilmaydi. Ularsiz yuklash ~2 barobar
        # tez va RAM ~150 MB kam.
        self._app = FaceAnalysis(
            name=FACE_MODEL_NAME,
            root=str(FACE_MODEL_ROOT),
            providers=providers,
            allowed_modules=["detection", "recognition"],
        )
        self._app.prepare(ctx_id=ctx_id, det_thresh=FACE_DET_THRESH, det_size=FACE_DET_SIZE)

        # HAQIQIY provayderni sessiyadan o'qiymiz.
        #
        # `get_available_providers()` da `CUDAExecutionProvider` borligi u
        # ISHLAYDI degani emas: `onnxruntime-gpu` o'rnatilgan, lekin CUDA
        # yoki cuDNN kutubxonalari yetishmagan bo'lsa, ONNX Runtime
        # ogohlantirish yozib jimgina CPU'ga tushadi. So'ralgan ro'yxatga
        # qarab "GPU" deb ko'rsatsak, log ham, UI ham YOLG'ON aytadi va
        # keyin "nega sekin?" degan savolga javob topib bo'lmaydi.
        self._active_providers = self._session_providers()
        if self._active_providers:
            self._use_gpu = "CUDAExecutionProvider" in self._active_providers
            if "CUDAExecutionProvider" in providers and not self._use_gpu:
                log.warning(
                    "CUDA so'raldi, lekin sessiya CPU'da ishga tushdi: %s. "
                    "CUDA/cuDNN kutubxonalari o'rnatilganini tekshiring.",
                    self._active_providers,
                )

        self._initialized = True
        log.info(
            "FaceEngine tayyor (%s) | provayderlar: %s",
            self.device_name,
            self._active_providers or providers,
        )

    def _session_providers(self) -> list:
        """
        Yuklangan modellardan birining ONNX sessiyasi qaysi provayderlarda
        ishlayotganini qaytaradi. Aniqlab bo'lmasa - bo'sh ro'yxat.
        """
        try:
            for model in (self._app.models or {}).values():
                session = getattr(model, "session", None)
                if session is not None:
                    return list(session.get_providers())
        except Exception:
            log.debug("Sessiya provayderlarini o'qib bo'lmadi", exc_info=True)
        return []

    # ------------------------------------------------------------------
    def detect(self, frame: np.ndarray) -> list:
        """
        Kadrdagi barcha yuzlar: normallashtirilgan embedding + bbox.

        Embedding SHU YERDA normallashtiriladi - keyin cosine similarity
        oddiy skalyar ko'paytmaga aylanadi va har bir solishtirishda
        norma qayta hisoblanmaydi.
        """
        if not self._initialized or frame is None:
            return []
        results = []
        for face in self._app.get(frame):
            embedding = getattr(face, "embedding", None)
            if embedding is None:
                continue
            norm = float(np.linalg.norm(embedding))
            if norm <= 0:
                continue
            results.append(
                {
                    "embedding": (embedding / norm).astype(np.float32),
                    "bbox": [int(value) for value in face.bbox],
                    "det_score": float(face.det_score),
                }
            )
        return results

    def embed_image_bytes(self, raw: bytes) -> Optional[np.ndarray]:
        """
        Rasm baytlaridan etalon embedding (pasport surati).

        `None` qaytishi ikki xil ma'noni bildiradi: rasmni o'qib bo'lmadi
        yoki unda yuz topilmadi. Ikkalasida ham natija bir xil - etalonsiz
        oqim, shuning uchun ajratilmaydi (sabab log'da qoladi).
        """
        if not self._initialized or not raw:
            return None
        import cv2

        buffer = np.frombuffer(raw, dtype=np.uint8)
        image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
        if image is None:
            log.warning("Etalon rasmni dekodlab bo'lmadi (%s bayt)", len(raw))
            return None

        faces = self.detect(image)
        if not faces:
            log.warning("Etalon rasmda yuz topilmadi")
            return None
        # Hujjat rasmida bir nechta yuz bo'lsa - eng kattasi asosiy.
        faces.sort(key=lambda item: (item["bbox"][2] - item["bbox"][0]), reverse=True)
        return faces[0]["embedding"]

    def embed_base64(self, photo_base64: str) -> Optional[np.ndarray]:
        if not photo_base64:
            return None
        try:
            raw = base64.b64decode(photo_base64, validate=False)
        except (binascii.Error, ValueError) as exc:
            log.warning("Etalon rasm base64 emas: %s", exc)
            return None
        return self.embed_image_bytes(raw)

    @staticmethod
    def similarity(left: np.ndarray, right: np.ndarray) -> float:
        """Ikkita normallashtirilgan vektor uchun cosine similarity."""
        if left is None or right is None:
            return 0.0
        return float(np.dot(left, right))

    def matches(self, reference: np.ndarray, probe: np.ndarray) -> tuple[bool, float]:
        score = self.similarity(reference, probe)
        return score >= self._threshold, score
