"""
Apparatni aniqlash: CPU, RAM, GPU, CUDA.

ENG MUHIM AJRATISH: "GPU BOR" va "GPU ISHLATILADI" — ikki BOSHQA
fakt va ular tez-tez mos kelmaydi.

Ikki xil holat va ikkalasi ham jimgina o'tadi:

  * `onnxruntime` ning CPU nashri o'rnatilgan —
    `CUDAExecutionProvider` umuman mavjud emas;
  * GPU nashri o'rnatilgan va provayder RO'YXATDA BOR, lekin
    uning CUDA kutubxonalari topilmaydi (paket boshqa CUDA
    versiyasi uchun yig'ilgan). Bu loyihaning ishlab chiqish
    mashinasidagi holat edi.

Ikkalasida ham natija bir xil: model CPU'da ishlaydi va hech kim
buni sezmaydi — dastur ishlayveradi, faqat bir necha barobar
sekin. Ikkinchisini faqat `cuda_runtime` ajrata oladi va u aynan
qaysi kutubxona yetishmayotganini aytadi.

`services/face_engine.py` bu tuzoqni allaqachon tasvirlagan
("CUDA so'raldi, lekin sessiya CPU'da ishga tushdi") va u yerda
xulosa SESSIYADAN o'qilardi — ya'ni model yuklanib bo'lgandan
KEYIN. Bu modul esa uni OLDINDAN aniqlaydi va SABABINI aytadi:
profil tanlash ham, handshake'dagi yozuv ham undan oldin bo'ladi.

Bu modul HECH QANDAY QAROR QABUL QILMAYDI. U faqat faktlarni
yig'adi; profil tanlash `performance_profile.py` da.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

#: Windows'da konsol oynasi ochilmasligi uchun (`services/system_info.py`
#: dagi bilan bir xil sabab).
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


@dataclass
class HardwareInfo:
    """Mashinaning o'lchangan tavsifi."""

    cpu_cores: int = 0
    cpu_threads: int = 0
    ram_gb: float = 0.0

    #: `nvidia-smi` ko'rgan karta (bo'sh — karta yo'q yoki drayver yo'q).
    gpu_name: str = ""
    gpu_vram_mb: int = 0
    driver_version: str = ""

    #: ONNX Runtime HAQIQATDA taklif qiladigan provayderlar.
    providers: list = field(default_factory=list)
    onnxruntime_version: str = ""
    #: CUDA nega ishlamayapti — `cuda_runtime` bergan aniq sabab
    #: (qaysi kutubxona yetishmayapti). Bo'sh — muammo yo'q.
    cuda_reason: str = ""

    #: Diagnostika: nima uchun GPU ishlatilmayapti.
    #
    # Bo'sh satr — muammo yo'q. Aks holda bu matn log'ga va
    # handshake'dagi `info_pc` ga tushadi: administrator "nega bu
    # mashinada kuzatuv sekin?" degan savolga panelda javob topishi
    # kerak, aks holda javob faqat o'sha mashinaning log faylida
    # qoladi va u yerga hech kim qaramaydi.
    gpu_warning: str = ""

    @property
    def has_gpu(self) -> bool:
        """Mashinada NVIDIA kartasi bor (ishlatilishidan qat'i nazar)."""
        return bool(self.gpu_name)

    @property
    def cuda_available(self) -> bool:
        """ONNX Runtime CUDA'da ishlay oladi."""
        return "CUDAExecutionProvider" in self.providers

    @property
    def usable_vram_mb(self) -> int:
        """
        Model uchun ajratish mumkin bo'lgan VRAM.

        Kartaning to'liq hajmi ISHLATILMAYDI: displey, brauzer
        (QtWebEngine ham GPU'ni ishlatadi) va OS o'z ulushini oladi.
        ~1.2 GB zaxira qoldiriladi — GTX 1660 Super (6 GB) da bu
        ~4.8 GB, ya'ni YOLOv8m + ArcFace bemalol sig'adi.
        """
        return max(0, self.gpu_vram_mb - 1200)

    def as_dict(self) -> dict:
        return {
            "cpu_cores": self.cpu_cores,
            "cpu_threads": self.cpu_threads,
            "ram_gb": round(self.ram_gb, 1),
            "gpu_name": self.gpu_name,
            "gpu_vram_mb": self.gpu_vram_mb,
            "driver_version": self.driver_version,
            "providers": list(self.providers),
            "onnxruntime": self.onnxruntime_version,
            "cuda_available": self.cuda_available,
            "gpu_warning": self.gpu_warning,
            "cuda_reason": self.cuda_reason,
        }


# --------------------------------------------------------------------------
def detect() -> HardwareInfo:
    """
    Apparatni aniqlaydi.

    BLOKLOVCHI: `nvidia-smi` chaqiruvi ~200-800 ms oladi. Ishga
    tushishda bir marta, fon thread'ida bajariladi.
    """
    info = HardwareInfo()
    _detect_cpu(info)
    _detect_gpu(info)
    _detect_runtime(info)
    _explain_gpu(info)

    log.info(
        "Apparat: CPU %s yadro / %.1f GB RAM | GPU %s | CUDA %s",
        info.cpu_cores or "?",
        info.ram_gb,
        info.gpu_name or "yo'q",
        "bor" if info.cuda_available else "yo'q",
    )
    if info.gpu_warning:
        log.warning("GPU ishlatilmayapti: %s", info.gpu_warning)
    return info


def _detect_cpu(info: HardwareInfo) -> None:
    try:
        import psutil

        info.cpu_cores = psutil.cpu_count(logical=False) or 0
        info.cpu_threads = psutil.cpu_count(logical=True) or 0
        info.ram_gb = psutil.virtual_memory().total / (1024 ** 3)
    except Exception:
        log.debug("CPU/RAM aniqlanmadi", exc_info=True)


def _detect_gpu(info: HardwareInfo) -> None:
    """
    `nvidia-smi` orqali karta va drayver.

    NIMA UCHUN `nvidia-smi`, `torch` yoki `pynvml` EMAS: ikkalasi
    ham yangi bog'liqlik va ular bundle'ga yuzlab megabayt qo'shadi.
    `nvidia-smi` esa drayver bilan birga keladi — u yo'q bo'lsa,
    CUDA ham baribir ishlamaydi, ya'ni javob bir xil.
    """
    command = [
        "nvidia-smi",
        "--query-gpu=name,memory.total,driver_version",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, timeout=8.0, creationflags=_NO_WINDOW
        )
    except (OSError, subprocess.SubprocessError) as exc:
        # `nvidia-smi` yo'q — bu XATO EMAS: mashinada NVIDIA kartasi
        # bo'lmasligi butunlay normal holat.
        log.debug("nvidia-smi topilmadi: %s", exc)
        return

    text = result.stdout.decode("utf-8", errors="replace").strip()
    if not text:
        return

    # Bir nechta karta bo'lsa - birinchisi. Ko'p kartali imtihon
    # mashinasi amalda uchramaydi, uchrasa ham model bittasida
    # ishlaydi.
    parts = [item.strip() for item in text.splitlines()[0].split(",")]
    if parts:
        info.gpu_name = parts[0]
    if len(parts) > 1:
        match = re.search(r"\d+", parts[1])
        info.gpu_vram_mb = int(match.group()) if match else 0
    if len(parts) > 2:
        info.driver_version = parts[2]


def _detect_runtime(info: HardwareInfo) -> None:
    """
    ONNX Runtime QAYSI provayderlarni HAQIQATDA bera oladi.

    `get_available_providers()` YETARLI EMAS va bu modulning butun
    mavzusi shu: ro'yxatda `CUDAExecutionProvider` turgani u
    ishlaydi degani emas — provayder DLL'i CUDA kutubxonalariga
    bog'liq va ular topilmasa ONNX Runtime jimgina CPU'ga tushadi.
    `cuda_runtime` aynan shuni tekshiradi (va topilgan
    kutubxonalarni oldindan yuklaydi), shuning uchun bu yerdagi
    `cuda_available` endi rost qiymat.

    Bu shunchaki diagnostika emas: `select_profile` aynan shu
    bayroqqa qarab GPU yoki CPU profilini tanlaydi. Yolg'on
    "CUDA bor" modellarni GPU sozlamalari bilan CPU'da ishga
    tushirardi - eng yomon kombinatsiya.
    """
    from proctoring.hardware import cuda_runtime

    try:
        import onnxruntime as ort

        info.onnxruntime_version = getattr(ort, "__version__", "")
        listed = list(ort.get_available_providers())
    except Exception:
        log.warning("onnxruntime aniqlanmadi", exc_info=True)
        return

    status = cuda_runtime.prepare()
    info.providers = (
        listed if status.available
        else [item for item in listed if item != "CUDAExecutionProvider"]
    )
    info.cuda_reason = status.reason


def _explain_gpu(info: HardwareInfo) -> None:
    """
    "GPU nega ishlatilmayapti" — bitta jumlada.

    Bu matn administratorga boradi, shuning uchun u DIAGNOZ
    bo'lishi kerak, "GPU yo'q" degan bayonot emas: uchta sabab
    butunlay boshqa harakat talab qiladi.
    """
    if info.cuda_available:
        info.gpu_warning = ""
        return

    if not info.providers:
        info.gpu_warning = (
            "onnxruntime umuman yuklanmadi — paket o'rnatilmagan yoki buzilgan."
        )
        return

    if not info.has_gpu:
        info.gpu_warning = (
            "Mashinada NVIDIA kartasi topilmadi (yoki drayver o'rnatilmagan) — "
            "kuzatuv CPU rejimida ishlaydi."
        )
        return

    # ENG CHALKASH HOLAT: karta bor, drayver bor, lekin runtime
    # CUDA'ni bera olmaydi. Dastur ishlayveradi va hech qanday xato
    # bermaydi - faqat bir necha barobar sekin.
    #
    # SABAB `cuda_runtime` DAN: u faqat "CUDA yo'q" demaydi, aynan
    # qaysi kutubxona yetishmayotganini aytadi. Umumiy matn
    # administratorni `onnxruntime-gpu` ni qayta o'rnatishga
    # yuborardi - holbuki paket o'rnatilgan, faqat uning CUDA
    # nashri mashinadagiga mos emas.
    info.gpu_warning = "«{}» kartasi topildi (drayver {}), lekin {}".format(
        info.gpu_name,
        info.driver_version or "?",
        info.cuda_reason
        or "onnxruntime{} CUDA'ni qo'llab-quvvatlamaydi.".format(
            " " + info.onnxruntime_version if info.onnxruntime_version else ""
        ),
    )


# --------------------------------------------------------------------------
# Keshlangan aniqlash
# --------------------------------------------------------------------------
class HardwareProbe:
    """
    `detect()` natijasini BIR MARTA hisoblaydi.

    Natija ikki joyda kerak va ular oqimning turli nuqtalarida:
    handshake (qurilma yozuviga GPU va profil yoziladi) va kuzatuv
    boshlanishi (profil tanlanadi). Har ikkalasida qayta aniqlash
    `nvidia-smi` ni ikki marta chaqirardi (~200-800 ms) va natija
    baribir bir xil bo'lardi - apparat imtihon o'rtasida o'zgarmaydi.

    Kesh MUDDATSIZ, `PublicIpResolver` dan farqli: tashqi IP bino
    kanali o'zgarganda o'zgaradi, videokarta esa yo'q.

    Naqsh o'sha yerdan olingan: dastur ishga tushganda fon
    thread'ida boshlanadi, chaqiruvchi esa tayyor bo'lmasa
    KUTMAYDI - handshake'ni apparat aniqlash uchun sekinlashtirish
    login oqimini uzaytirardi, holbuki maydonlar ixtiyoriy
    (`record_handshake` bo'sh qiymatga tegmaydi va keyingi
    handshake ularni yozadi).
    """

    def __init__(self) -> None:
        self._info: Optional[HardwareInfo] = None
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    @property
    def cached(self) -> Optional[HardwareInfo]:
        """Bloklamaydi: hali aniqlanmagan bo'lsa `None`."""
        return self._info

    def prefetch(self) -> None:
        """Fon thread'ida aniqlaydi (dastur ishga tushganda chaqiriladi)."""
        with self._lock:
            if self._info is not None:
                return
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._refresh, name="hardware-probe", daemon=True
            )
            self._thread.start()

    def resolve(self, timeout: float = 0.0) -> HardwareInfo:
        """
        Aniqlangan apparat. `timeout` berilsa - shuncha kutadi.

        Kutish tugagach ham tayyor bo'lmasa BO'SH `HardwareInfo`
        qaytadi (`None` emas): chaqiruvchi har safar tekshirishga
        majbur bo'lmasligi kerak, bo'sh qiymatlar esa "noma'lum"
        degan ma'noni to'g'ri ifodalaydi.
        """
        if self._info is not None:
            return self._info
        self.prefetch()
        if timeout > 0 and self._thread is not None:
            self._thread.join(timeout)
        return self._info or HardwareInfo()

    def _refresh(self) -> None:
        try:
            self._info = detect()
        except Exception:
            # Apparat aniqlanmasa kuzatuv baribir ishlashi kerak:
            # profil tanlash bo'sh `HardwareInfo` bilan eng past
            # profilni beradi va bu xavfsiz standart.
            log.warning("Apparat aniqlanmadi", exc_info=True)
            self._info = HardwareInfo()


#: Yagona nusxa - kesh butun dastur bo'ylab bitta bo'lishi kerak.
hardware_probe = HardwareProbe()
