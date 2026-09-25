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
    FACE_REQUIRE_GPU,
)
from core.bundle_paths import is_frozen
from core.singleton import SingletonMeta

log = logging.getLogger(__name__)


def similarity_score(similarity: float) -> int:
    """
    Cosine similarity -> ball [0..100]: `max(0, cos) * 100`.

    FORMULA SERVERNIKI BILAN AYNAN BIR XIL
    (`apps/common/utils/vectors.py:similarity_score`) va bu majburiy:
    chegara serverdan keladi (`Setting.faceid_min_score_student` /
    `faceid_min_score_exam`), solishtirishni esa client bajaradi.
    Ikki xil shkala bo'lsa, bitta chegara ikki joyda ikki xil
    ma'noni anglatardi va farqni faqat log'dan topish mumkin bo'lardi.

    MANFIY COSINE 0 GA SIQILADI: manfiy o'xshashlik "boshqa odam"
    degan xulosadan nariga hech narsa qo'shmaydi. Shu tufayli ball
    "necha foiz o'xshash" degan savolga to'g'ridan-to'g'ri javob
    beradi — 0 umuman o'xshamaydi, 100 aynan o'sha kadr.

    Ikki marta o'zgargan: `sqrt(cos)*100` (faqat ekran uchun edi) ->
    `(cos+1)/2*100` (butunlay boshqa odamga 50 ball berardi va
    panelda "yarmi o'xshash" bo'lib ko'rinardi) -> hozirgisi.
    """
    value = max(0.0, min(1.0, float(similarity or 0.0)))
    return max(0, min(100, int(round(value * 100))))


def score_to_cosine(score) -> float:
    """
    Ball [0..100] -> cosine [0..1]. `similarity_score` ning teskarisi.

    AI qatlamiga kerak: `behavior_analyzer` xom cosine bilan ishlaydi
    (har kadrda ball hisoblash bekorga yumaloqlash bo'lardi), chegara
    esa serverdan ball ko'rinishida keladi.
    """
    try:
        value = max(0.0, min(100.0, float(score)))
    except (TypeError, ValueError):
        return float(FACE_MATCH_THRESHOLD)
    return value / 100.0


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
            from proctoring.hardware import cuda_runtime

            engine = FaceEngine()
            requested = engine.providers()
            expected = "GPU (CUDA)" if "CUDAExecutionProvider" in requested else "CPU"
            self.progress.emit("Model yuklanmoqda ({})...".format(expected))
            engine.initialize()

            # XABAR NOSOZLIKNI YASHIRMAYDI. Mashinada karta bor,
            # lekin model CPU'da yuklangan bo'lsa, "Model tayyor -
            # CPU" degan qator hech qanday savol tug'dirmasdi va
            # operator kuzatuvning bir necha barobar sekin
            # ishlayotganini hech qachon bilmasdi.
            message = "Model tayyor - {}".format(engine.device_name)
            cuda = cuda_runtime.prepare()
            if not engine.uses_gpu and cuda.listed:
                message += " (GPU ishlatilmadi)"
            self.finished_loading.emit(True, message)
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

    # ------------------------------------------------------------------
    @property
    def is_ready(self) -> bool:
        return self._initialized

    @property
    def uses_gpu(self) -> bool:
        """Sessiya HAQIQATDA GPU'da ishlayaptimi (so'ralgani emas)."""
        return self._initialized and self._use_gpu

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
        ONNX Runtime provayderlari — CUDA faqat HAQIQATDA ishlasa.

        Ilgari bu yerda `ort.get_available_providers()` ro'yxatida
        `CUDAExecutionProvider` borligi yetarli deb hisoblanardi va
        izohda "bu holatda InsightFace o'zi CPU'ga tushadi" deb
        yozilgandi. U tushardi ham — LEKIN JIMGINA: log'da bitta
        qator qolar, ekranda esa "Model tayyor" ko'rinardi va
        mashinada GPU borligi hech qanday farq qilmasdi.

        Endi ro'yxatni `cuda_runtime` beradi: u CUDA kutubxonalarini
        oldindan yuklaydi (ular `pip` paketlari ichida yotadi va
        Windows ularni o'z-o'zidan topmaydi) va topilmasa AYNAN
        qaysi fayl yetishmayotganini aytadi.
        """
        from proctoring.hardware import cuda_runtime

        return cuda_runtime.providers()

    def initialize(self) -> None:
        """Modelni yuklaydi. FAQAT fon thread'idan chaqiriladi."""
        if self._initialized:
            return
        from insightface.app import FaceAnalysis

        from proctoring.hardware import cuda_runtime

        cuda = cuda_runtime.prepare()
        providers = self.providers()
        self._use_gpu = "CUDAExecutionProvider" in providers
        # `ctx_id` InsightFace'ga qaysi qurilmani ishlatishni aytadi
        # (-1 = CPU). Uni provayderlar ro'yxatidan MUSTAQIL qo'yish
        # mumkin emas: CPU provayderi bilan `ctx_id=0` model
        # tayyorlashda GPU'ni qidiradi va xato beradi.
        ctx_id = 0 if self._use_gpu else -1

        if not self._use_gpu and cuda.listed:
            # GPU UCHUN YIG'ILGAN PAKET, LEKIN ISHLAMADI. Bu eng
            # chalkash holat: administrator `onnxruntime-gpu` ni
            # o'rnatgan va hammasi joyida deb hisoblaydi.
            log.error("GPU ishlatilmaydi. %s", cuda.reason)
        if not self._use_gpu and FACE_REQUIRE_GPU:
            # QAT'IY REJIM ixtiyoriy va standart bo'yicha O'CHIRIQ:
            # CPU'da kuzatuv sekin, lekin ishlaydi va butun imtihonni
            # to'xtatish bundan battar. Yoqilgan bo'lsa - xato
            # yuqoriga chiqadi va ekranda "Model yuklanmadi" bo'lib
            # ko'rinadi (`FaceEngineLoader`).
            raise RuntimeError(
                "GPU talab qilingan (FACE_REQUIRE_GPU), lekin ishlatib "
                "bo'lmadi. {}".format(cuda.reason)
            )

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

    @classmethod
    def compare(cls, reference: np.ndarray, probe: np.ndarray) -> int:
        """
        Ikkita embedding -> BALL (0..100).

        CHEGARA BU YERDA YO'Q va bo'lmasligi ham kerak: u imtihonga
        biriktirilgan sozlamadan keladi va kirish bilan test davomidagi
        qiymatlar boshqacha bo'lishi mumkin
        (`min_score_initial` / `min_score_exam`). Dvigatel ichida
        saqlangan chegara ikkalasidan ham "g'olib" chiqib, jimgina
        noto'g'ri qaror berardi.
        """
        return similarity_score(cls.similarity(reference, probe))
