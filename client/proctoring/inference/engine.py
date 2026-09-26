"""
Model ishga tushirish qatlami.

VAZIFASI: pipeline kodida `if cuda: ... else: ...` shoxlanishi
BO'LMASLIGI. Detektorlar `engine.run(inputs)` deb chaqiradi va
qurilma haqida hech narsa bilmaydi.

NIMA UCHUN `CudaInferenceEngine` / `CpuInferenceEngine` EMAS.
Dastlabki rejada shunday ikkita sinf ko'zda tutilgandi, lekin
amalda ular FAQAT provayderlar ro'yxati bilan farq qilardi -
sessiya yaratish, kirish/chiqish nomlarini o'qish, `run` chaqiruvi
va xatolarni qayta ishlash bir xil. Ikkita sinf soxta abstraksiya
bo'lardi: har bir tuzatish ikki joyga kiritilishi kerak edi va
ular albatta ajralib ketardi.

Shuning uchun bitta `OnnxEngine` va provayderlar PARAMETR. Haqiqiy
farq (masalan TensorRT yoki OpenVINO) paydo bo'lsa, o'shanda
`InferenceEngine` merosxo'ri yoziladi - abstraksiya allaqachon
tayyor.

MODEL YO'Q BO'LSA - `ModelNotFound`. Bu XATO EMAS, KONFIGURATSIYA
HOLATI: obyekt aniqlash modeli bundle'ga qo'shilmagan bo'lishi
mumkin va o'shanda modul jimgina o'chadi, qolgan kuzatuv esa
ishlayveradi. Istisno tashlanadi, chunki chaqiruvchi buni
BILISHI kerak (hodisa yozadi, operatorga aytadi) - `None`
qaytarish uni jimgina yutib yuborardi.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)


class ModelNotFound(FileNotFoundError):
    """Model fayli topilmadi — modul o'chiriladi, dastur to'xtamaydi."""


class InferenceEngine:
    """
    Model ishga tushirish shartnomasi.

    Merosxo'r ikkita narsani beradi: `run()` va `is_ready`. Kirish
    tayyorlash (letterbox, normalizatsiya) va chiqishni ochish
    (NMS, dekodlash) — DETEKTORNING ishi, bu qatlamniki emas.
    Aks holda har bir yangi model uchun bu yerga shox qo'shilardi.
    """

    @property
    def is_ready(self) -> bool:
        raise NotImplementedError

    def run(self, inputs: dict) -> list:
        """`{kirish_nomi: massiv}` -> chiqish massivlari ro'yxati."""
        raise NotImplementedError

    def close(self) -> None:
        pass


class OnnxEngine(InferenceEngine):
    """ONNX Runtime sessiyasi."""

    def __init__(
        self,
        model_path: Path,
        *,
        providers: Optional[list] = None,
        intra_threads: int = 0,
        name: str = "",
    ) -> None:
        self._path = Path(model_path)
        self._requested = list(providers or ["CPUExecutionProvider"])
        self._intra_threads = int(intra_threads or 0)
        self.name = name or self._path.stem

        self._session = None
        self._input_names: list = []
        self._output_names: list = []
        self._active_providers: list = []
        #: Oxirgi `run()` davomiyligi (ms) — diagnostika uchun.
        self.last_latency_ms: float = 0.0

    # ------------------------------------------------------------------
    @property
    def is_ready(self) -> bool:
        return self._session is not None

    @property
    def providers(self) -> list:
        """
        Sessiya HAQIQATDA ishlatayotgan provayderlar.

        So'ralgan ro'yxat bilan farq qilishi mumkin va bu asosiy
        tuzoq: `CUDAExecutionProvider` mavjud bo'lsa ham, CUDA yoki
        cuDNN kutubxonalari yetishmasa ONNX Runtime ogohlantirish
        yozib JIMGINA CPU'ga tushadi (`services/face_engine.py`
        dagi bilan bir xil holat).
        """
        return list(self._active_providers)

    @property
    def uses_gpu(self) -> bool:
        return "CUDAExecutionProvider" in self._active_providers

    @property
    def input_shape(self) -> tuple:
        """Birinchi kirishning shakli (`None` — dinamik o'lcham)."""
        if self._session is None:
            return ()
        return tuple(self._session.get_inputs()[0].shape)

    # ------------------------------------------------------------------
    def load(self) -> "OnnxEngine":
        """
        Modelni yuklaydi. BLOKLOVCHI (~0.5–3 s) — fon thread'ida.
        """
        if self._session is not None:
            return self

        if not self._path.exists():
            raise ModelNotFound(
                "Model fayli topilmadi: {}".format(self._path)
            )

        import onnxruntime as ort

        from proctoring.hardware import cuda_runtime

        # CUDA kutubxonalari JARAYONGA YUKLANADI. Sessiya yaratishdan
        # oldin bo'lishi shart: ONNX Runtime provayder DLL'ini o'sha
        # paytda ochadi va u paytda kutubxonalar allaqachon
        # yuklangan bo'lishi kerak.
        cuda_runtime.prepare()

        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        if self._intra_threads:
            # CPU rejimida thread sonini CHEKLASH kerak: standart
            # holda ONNX Runtime barcha yadrolarni egallaydi va UI
            # thread'i kadr uzatishga ulgurmay qoladi - oldindan
            # ko'rish uzuq-yuluq bo'lib ko'rinadi.
            options.intra_op_num_threads = self._intra_threads
            options.inter_op_num_threads = 1

        # RO'YXATNI `cuda_runtime` BERADI, `ort.get_available_providers()`
        # EMAS. Ikkinchisida `CUDAExecutionProvider` provayder DLL'i
        # yuklanmaydigan holatda ham turadi va sessiya jimgina CPU'da
        # ochilardi - pastdagi ogohlantirish aynan shu holat uchun
        # yozilgan. Endi u ro'yxatga umuman tushmaydi va sabab
        # ishga tushishda bir marta, aniq matn bilan log'ga chiqadi.
        available = set(cuda_runtime.providers()) | {"CPUExecutionProvider"}
        providers = [item for item in self._requested if item in available]
        if not providers:
            # So'ralgan provayderlarning HECH BIRI mavjud emas.
            # CPU har doim bor, shuning uchun bu yo'l amalda faqat
            # buzilgan o'rnatishda uchraydi.
            providers = ["CPUExecutionProvider"]
        dropped = [item for item in self._requested if item not in available]
        if dropped:
            log.warning(
                "[%s] mavjud bo'lmagan provayderlar tashlab yuborildi: %s",
                self.name, ", ".join(dropped),
            )

        started = time.monotonic()
        self._session = ort.InferenceSession(
            str(self._path), sess_options=options, providers=providers
        )
        self._input_names = [item.name for item in self._session.get_inputs()]
        self._output_names = [item.name for item in self._session.get_outputs()]
        self._active_providers = list(self._session.get_providers())

        log.info(
            "[%s] model yuklandi (%.0f ms) | %s | kirish %s",
            self.name,
            (time.monotonic() - started) * 1000,
            "GPU" if self.uses_gpu else "CPU",
            self.input_shape,
        )
        if "CUDAExecutionProvider" in providers and not self.uses_gpu:
            # `face_engine.py` da tasvirlangan tuzoq: so'raldi,
            # berilmadi va hech qanday xato bo'lmadi.
            log.warning(
                "[%s] CUDA so'raldi, lekin sessiya CPU'da ochildi: %s. "
                "CUDA/cuDNN kutubxonalari o'rnatilganini tekshiring.",
                self.name, self._active_providers,
            )
        return self

    def run(self, inputs) -> list:
        """
        Modelni ishga tushiradi.

        `inputs` — massiv (bitta kirishli model uchun) yoki
        `{nom: massiv}`. Birinchisi qulaylik: detektorlarning
        deyarli hammasi bitta kirishga ega va ularni har safar
        lug'at yasashga majburlash kodni shovqinga to'ldirardi.
        """
        if self._session is None:
            raise RuntimeError("[{}] model yuklanmagan".format(self.name))

        if isinstance(inputs, np.ndarray):
            feed = {self._input_names[0]: inputs}
        else:
            feed = dict(inputs)

        started = time.monotonic()
        outputs = self._session.run(self._output_names, feed)
        self.last_latency_ms = (time.monotonic() - started) * 1000.0
        return outputs

    def close(self) -> None:
        # ONNX Runtime sessiyasi `__del__` da bo'shatiladi, lekin
        # GPU xotirasi shu paytgacha band turadi. Aniq bo'shatish
        # imtihonlar orasida kerak: keyingi sessiya modelni
        # qaytadan yuklaydi.
        self._session = None
        self._active_providers = []


def build_engine(
    model_path,
    profile,
    *,
    name: str = "",
) -> OnnxEngine:
    """
    Profil bo'yicha sozlangan dvigatel.

    Provayderlar va thread soni SHU YERDA belgilanadi - detektorlar
    profil haqida bilmaydi va bilishi ham shart emas.
    """
    return OnnxEngine(
        model_path,
        providers=profile.providers,
        intra_threads=profile.intra_threads,
        name=name,
    )
