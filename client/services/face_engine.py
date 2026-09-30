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
import threading
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
from PyQt6.QtCore import QCoreApplication, QThread, pyqtSignal

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


@dataclass(frozen=True)
class ModelProblem:
    """
    Model nega yuklanmadi — operator uchun.

    `kind`:
        missing      — fayl(lar) yo'q (qayta o'rnatish kerak)
        corrupt      — fayl buzilgan / to'liq ko'chirilmagan
        memory       — xotira yetmadi (boshqa dasturlarni yopib qayta)
        runtime      — ONNX Runtime yoki uning DLL/provayderi yuklanmadi
        gpu_required — `FACE_REQUIRE_GPU`, lekin GPU ishlamadi
        unknown      — boshqa

    `retryable` — avtomatik qayta urinishning ma'nosi bormi. Fayl
    yo'q yoki buzilgan bo'lsa yana urinish bir xil natija beradi va
    faqat operatorni kuttiradi.
    """

    kind: str
    title: str
    detail: str

    @property
    def retryable(self) -> bool:
        return self.kind in ("memory", "unknown")


class ModelLoadError(RuntimeError):
    """Tasniflangan yuklash xatosi (`classify_model_error` ni chetlab o'tadi)."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


_MEMORY_MARKERS = (
    "bad_alloc", "failed to allocate", "out of memory", "not enough memory",
    "cannot allocate", "paging file", "memoryerror", "insufficient memory",
    "cudaerrormemoryallocation", "cuda_error_out_of_memory",
)
_MISSING_MARKERS = (
    "no_suchfile", "file doesn't exist", "does not exist", "no such file",
    "should exist",
)
_CORRUPT_MARKERS = (
    "protobuf", "invalid_protobuf", "invalid_graph", "no_model",
    "modelproto", "failed to load model", "load model from", "truncated",
    "unexpected end", "not a valid onnx", "invalid model", "model_path",
)
_RUNTIME_MARKERS = (
    "dll load failed", "loadlibrary", "onnxruntime_providers", "error 126",
    "error 127", "error 193", "winerror 126", "winerror 127", "winerror 193",
    "cudnn", "cublas", "cudart", "executionprovider", "provider",
    "no module named",
)


def classify_model_error(exc: BaseException) -> ModelProblem:
    """
    Istisno -> operatorga tushunarli sabab. SOF FUNKSIYA (testlanadi).

    ONNX Runtime va InsightFace xatolari turli ko'rinishda keladi
    (`RuntimeError`, `onnxruntime...Fail`, `AssertionError`, `OSError`)
    va ularning TURI emas, MATNI sababni aytadi. Shuning uchun matn
    bo'yicha tasniflanadi; tartib muhim — xotira xatosi protobuf
    tahlili paytida ham chiqishi mumkin va u "fayl buzilgan" deb
    ko'rsatilmasligi kerak (fayl joyida, qayta urinish yordam beradi).
    """
    text = "{} {}".format(type(exc).__name__, exc).lower()
    kind = getattr(exc, "kind", "")

    if kind == "gpu_required":
        return ModelProblem(
            "gpu_required",
            "GPU ishlamadi",
            "Bu kompyuterda GPU talab qilingan (FACE_REQUIRE_GPU), lekin uni "
            "ishlatib bo'lmadi. Administratorga murojaat qiling. {}".format(
                str(exc)[:160]
            ).strip(),
        )
    if isinstance(exc, MemoryError) or any(marker in text for marker in _MEMORY_MARKERS):
        return ModelProblem(
            "memory",
            "Xotira yetmadi",
            "Modelni yuklash uchun operativ xotira yetmadi. Boshqa dasturlarni "
            "yoping va «Qayta yuklash» ni bosing.",
        )
    # "Fayl yo'q" "buzilgan" dan OLDIN: ORT ning NO_SUCHFILE matni ham
    # "Load model from ... failed" bilan boshlanadi.
    if (
        kind == "missing"
        or isinstance(exc, (FileNotFoundError, AssertionError))
        or any(marker in text for marker in _MISSING_MARKERS)
    ):
        return ModelProblem(
            "missing",
            "Model fayli topilmadi",
            "Yuz aniqlash modeli fayllari topilmadi. Dasturni qayta o'rnating "
            "yoki administratorga murojaat qiling.",
        )
    if kind == "corrupt" or any(marker in text for marker in _CORRUPT_MARKERS):
        return ModelProblem(
            "corrupt",
            "Model fayli buzilgan",
            "Yuz aniqlash modeli fayli buzilgan yoki to'liq ko'chirilmagan. "
            "Dasturni qayta o'rnating yoki administratorga murojaat qiling.",
        )
    if (
        kind == "runtime"
        or isinstance(exc, ImportError)
        or (isinstance(exc, OSError) and getattr(exc, "winerror", None) in (126, 127, 193))
        or any(marker in text for marker in _RUNTIME_MARKERS)
    ):
        return ModelProblem(
            "runtime",
            "DLL/provayder yuklanmadi",
            "Model ishga tushadigan kutubxona (ONNX Runtime yoki uning "
            "DLL/provayderi) yuklanmadi. Dasturni qayta o'rnating; GPU "
            "nashrida CUDA/cuDNN mosligini tekshiring.",
        )
    return ModelProblem(
        "unknown",
        "Model yuklanmadi",
        "Yuz aniqlash modeli yuklanmadi: {}. «Qayta yuklash» ni bosing; "
        "takrorlansa administratorga murojaat qiling.".format(str(exc)[:160] or type(exc).__name__),
    )


#: Avtomatik qayta urinishlar (faqat `ModelProblem.retryable`) va
#: ular orasidagi pauza. Xotira yetmaganda bir necha soniyadan keyin
#: boshqa jarayonlar (brauzer, yangilanish) xotirani bo'shatgan bo'ladi.
_AUTO_RETRIES = 2
_RETRY_PAUSE_S = 5.0

#: Ishlab turgan yuklovchilar. Referens shu yerda ushlanadi: chaqiruvchi
#: (`MainWindow._on_model_loaded`) o'zinikini `None` qiladi, lekin
#: `finished_loading` thread TUGASHIDAN OLDIN keladi — oxirgi referens
#: tushsa, Qt ishlab turgan thread obyektini yo'q qilib dasturni
#: qulatardi (`camera_worker._LIVE` dagi bilan bir xil tuzoq).
_LOADERS: set = set()


class FaceEngineLoader(QThread):
    """
    Modelni fon thread'ida yuklaydi.

    Dastur ishga tushishi bilan boshlanadi va login formasi bilan
    PARALLEL ketadi: operator login/parol yozguncha model tayyor bo'ladi,
    ya'ni kutish vaqti bekorga sarflanmaydi.

    Xatoda tasniflangan sabab chiqadi (`classify_model_error`,
    `FaceEngine.problem`); vaqtinchalik xato (xotira) avtomatik qayta
    sinaladi, qolganlari — "Qayta yuklash" tugmasi bilan
    (`start_model_loading`).
    """

    progress = pyqtSignal(str)
    finished_loading = pyqtSignal(bool, str)  # (muvaffaqiyat, xabar)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.finished.connect(self._forget)

    def start(self, *args, **kwargs) -> None:
        _LOADERS.add(self)
        app = QCoreApplication.instance()
        if app is not None:
            # Dastur yopilayotganda yuklash tugashini kutamiz: ishlab
            # turgan QThread obyekti yo'q qilinsa jarayon qulaydi.
            app.aboutToQuit.connect(self._wait_on_quit)
        super().start(*args, **kwargs)

    def _forget(self) -> None:
        _LOADERS.discard(self)

    def _wait_on_quit(self) -> None:
        if self.isRunning():
            self.wait(6000)

    def run(self) -> None:
        engine = None
        attempt = 0
        while True:
            try:
                from proctoring.hardware import cuda_runtime

                engine = FaceEngine()
                requested = engine.providers()
                expected = "GPU (CUDA)" if "CUDAExecutionProvider" in requested else "CPU"
                self.progress.emit(
                    "Model yuklanmoqda ({})...".format(expected)
                    if attempt == 0
                    else "Model qayta yuklanmoqda ({}/{})...".format(attempt + 1, _AUTO_RETRIES + 1)
                )
                engine.initialize()

                # XABAR NOSOZLIKNI YASHIRMAYDI. Mashinada karta bor,
                # lekin model CPU'da yuklangan bo'lsa, "Model tayyor -
                # CPU" degan qator hech qanday savol tug'dirmasdi va
                # operator kuzatuvning bir necha barobar sekin
                # ishlayotganini hech qachon bilmasdi.
                message = "Model tayyor - {}".format(engine.device_name)
                cuda = cuda_runtime.prepare()
                if not engine.uses_gpu and (cuda.listed or engine.gpu_failed):
                    message += " (GPU ishlatilmadi)"
                self.finished_loading.emit(True, message)
                return
            except Exception as exc:
                problem = classify_model_error(exc)
                if engine is not None:
                    engine._set_failed(problem)
                log.exception("FaceEngine yuklashda xato (%s)", problem.kind)
                if problem.retryable and attempt < _AUTO_RETRIES:
                    attempt += 1
                    self.progress.emit(
                        "{} — {} s dan keyin qayta urinish...".format(
                            problem.title, int(_RETRY_PAUSE_S)
                        )
                    )
                    time.sleep(_RETRY_PAUSE_S)
                    continue
                self.finished_loading.emit(False, "{}: {}".format(problem.title, problem.detail))
                return


def start_model_loading() -> Optional[FaceEngineLoader]:
    """
    Modelni (qayta) yuklashni boshlaydi. FAQAT asosiy thread'dan.

    Qaytaradi: ishlab turgan yuklovchi (yangi yoki allaqachon
    ishlayotgani — ikkinchisini boshlash bitta modelni ikki marta
    yuklardi) yoki `None` (model allaqachon tayyor). Chaqiruvchi
    signallarga ulanadi; referensni ushlab turishi SHART EMAS.
    """
    for loader in list(_LOADERS):
        if loader.isRunning():
            return loader
    if FaceEngine().is_ready:
        return None
    loader = FaceEngineLoader()
    loader.start()
    return loader


def is_model_loading() -> bool:
    """Hozir yuklovchi ishlayaptimi (UI holati uchun)."""
    return any(loader.isRunning() for loader in list(_LOADERS))


#: `FaceEngine.embed_reference` sabablari — sahifa aynan shular
#: bo'yicha xabar tanlaydi.
REFERENCE_REASONS = (
    "ok", "missing", "invalid", "not_image", "too_small", "no_face",
    "model_not_ready", "error",
)


#: GPU'da ketma-ket shuncha inferensiya xatosidan keyin CPU'ga o'tiladi.
_GPU_RUN_ERRORS = 3

#: Hujjat rasmining eng kichik tomoni (px). Bundan kichik rasmda yuz
#: ~20 px bo'ladi va ArcFace uni 112x112 ga cho'zib, ishonchsiz vektor
#: beradi — natija "mos kelmadi" bo'lib ko'rinardi, sabab esa rasmda.
_MIN_REFERENCE_SIDE_PX = 48


def decode_photo_base64(photo_base64: str) -> bytes:
    """
    Hujjat rasmi (base64) -> baytlar. `data:image/...;base64,` prefiksi
    bo'lsa olib tashlanadi.

    Server prefiksni o'zi olib tashlaydi (`integrations/exam_site.py`),
    lekin client unga TAYANMAYDI: prefiks qolib ketsa `b64decode`
    `validate=False` bilan uni jimgina "yeb", buzilgan baytlar
    qaytarardi va xato "rasm buzilgan" bo'lib ko'rinardi.
    """
    text = str(photo_base64 or "").strip()
    if text.lower().startswith("data:") and "," in text:
        text = text.split(",", 1)[1]
    return base64.b64decode(text, validate=False)


def _check_model_files(directory) -> None:
    """
    Model katalogidagi fayllarni YUKLASHDAN OLDIN tekshiradi.

    Bo'sh (0 bayt) yoki `.onnx` fayli umuman yo'q katalog —
    ko'chirish chala qolgan o'rnatish. ONNX Runtime bunday faylda
    tushunarsiz protobuf xatosi beradi; bu yerda sabab aniq aytiladi.
    """
    try:
        files = sorted(directory.glob("*.onnx"))
    except OSError:
        return
    if not files:
        raise ModelLoadError(
            "missing", "Model katalogida .onnx fayl yo'q: {}".format(directory)
        )
    for path in files:
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size == 0:
            raise ModelLoadError("corrupt", "Model fayli bo'sh: {}".format(path.name))


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
        #: Yuklash bir vaqtda faqat bitta thread'da (qayta yuklash
        #: tugmasi va boshlang'ich yuklovchi ustma-ust tushmasin).
        self._init_lock = threading.Lock()
        #: "idle" | "loading" | "ready" | "failed" — UI shu bo'yicha
        #: "kuting" yoki "qayta yuklang" deydi.
        self._state = "idle"
        self._problem: Optional[ModelProblem] = None
        #: GPU sessiyasi ochilmadi yoki ishlash paytida yiqildi va
        #: dvigatel CPU'ga o'tdi — xabarda "(GPU ishlatilmadi)".
        self.gpu_failed = False
        #: Ketma-ket inferensiya xatolari (GPU'da) — `_run`.
        self._run_errors = 0

    # ------------------------------------------------------------------
    @property
    def is_ready(self) -> bool:
        return self._initialized

    @property
    def state(self) -> str:
        """"idle" | "loading" | "ready" | "failed"."""
        return "ready" if self._initialized else self._state

    @property
    def problem(self) -> Optional[ModelProblem]:
        """Oxirgi yuklash xatosining sababi (`state == "failed"`)."""
        return None if self._initialized else self._problem

    def _set_failed(self, problem: ModelProblem) -> None:
        if not self._initialized:
            self._state = "failed"
            self._problem = problem

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
        """
        Modelni yuklaydi. FAQAT fon thread'idan chaqiriladi.

        Xato YUQORIGA chiqadi (yuklovchi uni tasniflaydi), holat esa
        shu yerda "failed" bo'ladi — UI sahifalari yuklovchining
        signaliga ulanmagan bo'lsa ham sababni `problem` dan o'qiydi.
        """
        with self._init_lock:
            if self._initialized:
                return
            self._state = "loading"
            self._problem = None
            try:
                self._initialize_locked()
            except Exception as exc:
                self._state = "failed"
                self._problem = classify_model_error(exc)
                raise
            self._state = "ready"

    def _initialize_locked(self) -> None:
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
            raise ModelLoadError(
                "gpu_required",
                "GPU talab qilingan (FACE_REQUIRE_GPU), lekin ishlatib "
                "bo'lmadi. {}".format(cuda.reason),
            )

        bundled = FACE_MODEL_ROOT / "models" / FACE_MODEL_NAME
        if not bundled.exists():
            # Frozen rejimda qat'iy: imtihon markazi kompyuteri offline
            # bo'lishi mumkin va InsightFace 30+ soniya timeout bilan
            # tushunarsiz xato beradi. Dev rejimda avtomatik yuklab olish
            # qulayroq, shuning uchun faqat ogohlantiramiz.
            if is_frozen():
                raise ModelLoadError(
                    "missing",
                    "Model fayllari topilmadi: {}. Build'da models/{} "
                    "paketlanmagan.".format(bundled, FACE_MODEL_NAME),
                )
            log.warning("Bundle'da model yo'q (%s) - internetdan yuklanadi", bundled)
        else:
            _check_model_files(bundled)

        # `allowed_modules` - buffalo_l to'plamida 5 ta model bor, bizga
        # esa faqat ikkitasi kerak. Qolganlari (landmark_3d_68 ~143 MB,
        # landmark_2d_106, genderage) yuz yoshi/jinsi va 3D nuqtalar
        # uchun - proktorlikda ishlatilmaydi. Ularsiz yuklash ~2 barobar
        # tez va RAM ~150 MB kam.
        try:
            self._app = self._build_app(FaceAnalysis, providers, ctx_id)
        except Exception as exc:
            problem = classify_model_error(exc)
            if not self._use_gpu or FACE_REQUIRE_GPU or problem.kind in ("missing", "corrupt"):
                raise
            # GPU SESSIYASI OCHILMADI — CPU'ga O'TAMIZ, dasturni
            # to'xtatmaymiz. `cuda_runtime` kutubxonalarni topgan
            # bo'lsa ham sessiya yaratish yiqilishi mumkin (GPU
            # xotirasi to'la, drayver eski, karta "yo'qolgan"). Ilgari
            # bu holatda model UMUMAN yuklanmasdi va FaceID ishlamasdi,
            # holbuki CPU'da hammasi ishlaydi — faqat sekinroq.
            # Nosozlik yashirilmaydi: ERROR log va ekranda "(GPU
            # ishlatilmadi)" (`FaceEngineLoader`).
            log.error(
                "GPU'da model sessiyasi ochilmadi (%s) — CPU'ga o'tiladi",
                str(exc)[:300],
            )
            self.gpu_failed = True
            self._use_gpu = False
            providers = ["CPUExecutionProvider"]
            ctx_id = -1
            self._app = self._build_app(FaceAnalysis, providers, ctx_id)

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

    @staticmethod
    def _build_app(factory, providers: list, ctx_id: int):
        """
        `FaceAnalysis` + `prepare` va TO'LIQLIK tekshiruvi.

        InsightFace tanib olish (recognition) modeli topilmasa XATO
        BERMAYDI — shunchaki embedding'siz yuz qaytaradi va FaceID
        "yuz topilmadi" deb abadiy kutib turardi. Shuning uchun ikkala
        modul borligi shu yerda talab qilinadi.
        """
        app = factory(
            name=FACE_MODEL_NAME,
            root=str(FACE_MODEL_ROOT),
            providers=providers,
            allowed_modules=["detection", "recognition"],
        )
        missing = [
            name for name in ("detection", "recognition")
            if name not in (getattr(app, "models", None) or {})
        ]
        if missing:
            raise ModelLoadError(
                "missing",
                "Model to'plamida {} moduli yo'q ({}).".format(
                    ", ".join(missing), FACE_MODEL_NAME
                ),
            )
        app.prepare(ctx_id=ctx_id, det_thresh=FACE_DET_THRESH, det_size=FACE_DET_SIZE)
        return app

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
        for face in self.analyze(frame):
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

    def analyze(self, frame: np.ndarray) -> list:
        """
        InsightFace'ning XOM natijasi (nuqtalar bilan) — AI qatlami uchun.

        Barcha inferensiya shu yerdan o'tadi (`detect`,
        `identity/face_identity.py`): GPU ishlash paytida yiqilsa
        CPU'ga o'tish qoidasi bitta joyda bo'lishi kerak.
        """
        if not self._initialized or frame is None:
            return []
        return self._run(frame)

    def _run(self, frame: np.ndarray) -> list:
        """
        `app.get()` — GPU nosozligida CPU'ga o'tish bilan.

        Uyqudan uyg'onish, drayver yangilanishi yoki GPU xotirasi
        tugashi CUDA sessiyasini ishlash paytida "o'ldiradi": har
        chaqiruv xato beradi va FaceID ham, davriy tekshiruv ham
        imtihon oxirigacha jimgina ishlamay qoladi. Ketma-ket
        `_GPU_RUN_ERRORS` xatodan keyin dvigatel CPU'da qayta
        quriladi. Bitta xato — o'tkinchi (buzilgan kadr) bo'lishi
        mumkin, shuning uchun darhol emas.
        """
        app = self._app
        try:
            faces = app.get(frame)
        except Exception as exc:
            if self._use_gpu and not FACE_REQUIRE_GPU:
                self._run_errors += 1
                if self._run_errors >= _GPU_RUN_ERRORS:
                    self._fallback_to_cpu(exc)
            raise
        self._run_errors = 0
        return faces

    def _fallback_to_cpu(self, exc: BaseException) -> None:
        """Ishlab turgan dvigatelni CPU'da qayta quradi (bir marta)."""
        with self._init_lock:
            if not self._use_gpu:
                return
            log.error(
                "GPU'da inferensiya ketma-ket yiqildi (%s) — model CPU'da "
                "qayta yuklanadi", str(exc)[:300],
            )
            try:
                from insightface.app import FaceAnalysis

                app = self._build_app(FaceAnalysis, ["CPUExecutionProvider"], -1)
            except Exception:
                # CPU'da ham qurilmadi — eskisi qoladi va xato
                # chaqiruvchida (throttled log) ko'rinadi. Qayta-qayta
                # qurishga urinmaymiz: har kadrda bir necha soniyalik
                # yuklash ishchini qotirardi.
                log.exception("Modelni CPU'da qayta qurib bo'lmadi")
                self._use_gpu = False
                self.gpu_failed = True
                return
            self._app = app
            self._use_gpu = False
            self.gpu_failed = True
            self._run_errors = 0
            self._active_providers = self._session_providers()
            log.warning("FaceEngine endi CPU'da ishlaydi: %s", self._active_providers)

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
        embedding, _reason = self.embed_reference(photo_base64)
        return embedding

    def embed_reference(self, photo_base64: str) -> tuple:
        """
        Hujjat rasmidan etalon: `(embedding | None, sabab)`.

        `embed_image_bytes` dan farqi — SABAB qaytadi
        (`REFERENCE_REASONS`). FaceID sahifasi operatorga har holat
        uchun boshqa gap aytadi: "rasm kelmadi" (platforma), "rasm
        buzilgan" (platforma), "rasm juda kichik" / "rasmda yuz
        topilmadi" (hujjat rasmi sifati), "model hali tayyor emas"
        (kutish kifoya). Bittasi — umumiy "rasmdan yuz olinmadi" —
        operatorni noto'g'ri odamga (administrator o'rniga texnik)
        yuborardi. ISTISNO TASHLAMAYDI.
        """
        if not photo_base64 or not str(photo_base64).strip():
            return None, "missing"
        if not self._initialized:
            return None, "model_not_ready"
        try:
            raw = decode_photo_base64(photo_base64)
        except (binascii.Error, ValueError) as exc:
            log.warning("Etalon rasm base64 emas: %s", exc)
            return None, "invalid"
        if not raw:
            return None, "invalid"
        try:
            import cv2

            image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        except Exception:
            image = None
        if image is None:
            log.warning("Etalon rasmni dekodlab bo'lmadi (%s bayt)", len(raw))
            return None, "not_image"
        height, width = image.shape[:2]
        if min(height, width) < _MIN_REFERENCE_SIDE_PX:
            log.warning("Etalon rasm juda kichik: %sx%s", width, height)
            return None, "too_small"
        try:
            faces = self.detect(image)
            if not faces:
                # HUJJAT RASMIDA yuz ko'pincha butun kadrni egallaydi va
                # detektor chekkaga tegib turgan yuzni o'tkazib yuboradi.
                # Chetiga bo'sh hoshiya qo'shib yana bir marta
                # qaraymiz — yuz o'lchami o'zgarmaydi, faqat "joy" paydo
                # bo'ladi.
                pad_y, pad_x = int(height * 0.3), int(width * 0.3)
                padded = cv2.copyMakeBorder(
                    image, pad_y, pad_y, pad_x, pad_x, cv2.BORDER_CONSTANT, value=(0, 0, 0)
                )
                faces = self.detect(padded)
        except Exception:
            log.exception("Etalon rasmdan yuz olishda xato")
            return None, "error"
        if not faces:
            log.warning("Etalon rasmda yuz topilmadi")
            return None, "no_face"
        # Hujjat rasmida bir nechta yuz bo'lsa - eng kattasi asosiy.
        faces.sort(key=lambda item: (item["bbox"][2] - item["bbox"][0]), reverse=True)
        return faces[0]["embedding"], "ok"

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
