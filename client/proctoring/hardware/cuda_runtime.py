"""
CUDA kutubxonalarini TOPADI va CUDA provayderi haqiqatda ishlashini
tekshiradi.

MUAMMO. `onnxruntime.get_available_providers()` ro'yxatida
`CUDAExecutionProvider` borligi u ISHLAYDI degani emas. Provayder
alohida DLL (`onnxruntime_providers_cuda.dll`) va u CUDA runtime
kutubxonalariga bog'liq (`cudart`, `cublas`, `cublasLt`, `cufft`,
`cudnn`). Ular topilmasa ONNX Runtime log'ga bitta qator yozib
JIMGINA CPU'ga tushadi — dastur ishlayveradi, faqat bir necha
barobar sekin, va hech kim buni sezmaydi.

Ishlab chiqish mashinasida aynan shu holat edi: GTX 1660 SUPER,
drayver o'rnatilgan, `onnxruntime-gpu` o'rnatilgan — lekin paketning
CUDA 13 uchun yig'ilgan nashri edi va mashinada faqat CUDA 12
kutubxonalari bor. Natijada InsightFace CPU'da yuklanardi.

IKKI SABAB, IKKI YECHIM va ular aralashtirilmaydi:

  * DLL BOR, LEKIN QIDIRUV YO'LIDA EMAS — bu yerda hal qilinadi.
    Kutubxonalar `pip` paketlari ichida yotadi (`nvidia-*`,
    `torch/lib`) va Windows ularni o'z-o'zidan topmaydi. Yechim:
    ularni OLDINDAN, to'liq yo'l bilan jarayonga yuklash — shundan
    keyin provayder DLL'ining yashirin importi allaqachon
    yuklangan modulga tushadi.
  * DLL UMUMAN YO'Q yoki VERSIYASI BOSHQA — bu yerda faqat
    ANIQLANADI. `onnxruntime-gpu` ning CUDA 13 nashri
    `cublasLt64_13.dll` ni so'raydi, CUDA 12 nashri esa
    `cublasLt64_12.dll` ni; birinchisini ikkinchisi bilan
    almashtirib bo'lmaydi. Yagona yechim - paketni mos nashri
    bilan almashtirish, shuning uchun modul aynan QAYSI fayl
    yetishmayotganini aytadi.

NIMA UCHUN KERAKLI DLL RO'YXATI QADAB QO'YILMAGAN. Ro'yxat
`onnxruntime` versiyasiga qarab o'zgaradi (CUDA 12 -> 13 o'tishida
hamma nomlar o'zgardi). Shuning uchun u provayder DLL'ining O'ZIDAN
o'qiladi — PE import jadvali. Bu bir necha kilobayt o'qish va
natija har doim shu o'rnatishga mos.

MODUL HECH NARSANI TO'XTATMAYDI: CUDA topilmasa ro'yxat CPU bilan
qaytadi va kuzatuv ishlayveradi. Qaror chaqiruvchida
(`FACE_REQUIRE_GPU`).
"""

from __future__ import annotations

import ctypes
import logging
import os
import struct
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"

#: Qaysi importlar CUDA'ga tegishli deb hisoblanadi.
#
# Nomning O'ZI emas, PREFIKSI: versiya raqami nomning qismi
# (`cublas64_12.dll`) va u ONNX Runtime nashriga qarab o'zgaradi.
# Tizim kutubxonalari (KERNEL32, MSVCP140, api-ms-win-*) bu
# ro'yxatga tushmaydi — ular Windows bilan keladi va ularni
# qidirishning ma'nosi yo'q.
_CUDA_PREFIXES = (
    "cudart", "cublas", "cudnn", "cufft", "curand", "cusparse",
    "cusolver", "nvrtc", "nvjitlink", "cupti", "nccl",
)

#: Qo'shilgan katalog "tutqichlari".
#
# SAQLANISHI SHART: `os.add_dll_directory` qaytargan obyekt yo'q
# qilinganda katalog qidiruv yo'lidan OLIB TASHLANADI. Uni mahalliy
# o'zgaruvchida qoldirish "ba'zan ishlaydi, ba'zan yo'q" turidagi
# eng qimmat xatoni berardi.
_dll_dirs: list = []

_lock = threading.Lock()
_status: Optional["CudaStatus"] = None

#: Nomzod kataloglar — bir marta hisoblanadi.
#
# Ro'yxat fayl tizimini kezadi (`site-packages/nvidia/*`) va u har
# kutubxona uchun qaytarilsa, bir necha marta takrorlanardi.
_directories: Optional[list] = None


@dataclass
class CudaStatus:
    """CUDA provayderi holati — bir marta hisoblanadi."""

    #: Provayder ishlatilishi mumkinmi.
    available: bool = False
    #: `onnxruntime` ro'yxatida umuman bormi (paket nashri GPU'mi).
    listed: bool = False
    #: Topilmagan kutubxonalar — diagnostikaning o'zagi.
    missing: list = field(default_factory=list)
    #: Kutubxonalar qayerdan yuklandi.
    loaded_from: list = field(default_factory=list)
    onnxruntime_version: str = ""
    #: Provayder ro'yxatda bor, lekin DLL'ining o'zi yo'q. CPU
    #: o'rnatuvchisi `onnxruntime-gpu` paketini olib keladi, provayder
    #: DLL'ini esa hajm uchun chiqarib tashlaydi - usiz `reason`
    #: "sabab noma'lum" derdi va administrator mavjud bo'lmagan
    #: nosozlikni qidirardi.
    no_provider: bool = False

    @property
    def reason(self) -> str:
        """Nega ishlamayapti — BITTA jumlada, administrator uchun."""
        if self.available:
            return ""
        if not self.listed:
            return (
                "onnxruntime ning CPU nashri o'rnatilgan — GPU uchun "
                "`pip install onnxruntime-gpu` kerak."
            )
        if self.missing:
            return (
                "CUDA kutubxonalari topilmadi: {}. `onnxruntime-gpu` nashri "
                "mashinadagi CUDA versiyasiga mos emas yoki kutubxonalar "
                "umuman o'rnatilmagan.".format(", ".join(self.missing))
            )
        if self.no_provider:
            return (
                "Bu nashrda CUDA provayderi yo'q (CPU build) — GPU uchun "
                "o'rnatuvchining GPU nashri kerak."
            )
        return "CUDA provayderi yuklanmadi (sabab noma'lum)."


# --------------------------------------------------------------------------
def prepare() -> CudaStatus:
    """
    CUDA kutubxonalarini jarayonga yuklaydi va holatni qaytaradi.

    BIR MARTA bajariladi va natija keshlanadi: DLL'lar jarayon
    umriga yuklanadi, ikkinchi chaqiruv esa faqat o'sha ishni
    takrorlardi. Apparat ham imtihon o'rtasida o'zgarmaydi.

    THREAD-SAFE: modelni yuklovchi (`FaceEngineLoader`) va apparat
    aniqlovchi (`hardware_probe`) ikkalasi ham fon thread'ida
    ishlaydi va bir vaqtda chaqirishi mumkin.
    """
    global _status
    with _lock:
        if _status is None:
            try:
                _status = _detect()
            except Exception:
                # Aniqlash yiqilishi model yuklanishini to'xtatmasligi
                # kerak: "CUDA yo'q" deb CPU yo'li bilan davom etamiz.
                log.exception("CUDA holatini aniqlab bo'lmadi — CPU ishlatiladi")
                _status = CudaStatus()
        return _status


def providers() -> list:
    """
    ONNX Runtime uchun provayderlar ro'yxati.

    CUDA HAQIQATDA ishlamasa u ro'yxatga QO'SHILMAYDI. Ilgari
    "mavjud" bo'lsa qo'shilardi va natija ikki joyda yolg'on
    berardi: log "GPU (CUDA)" deb yozar, sessiya esa CPU'da
    ochilardi; unumdorlik profili ham GPU profilini tanlab,
    modellarni CPU'da og'ir sozlamalar bilan ishga tushirardi.
    """
    return (
        ["CUDAExecutionProvider", "CPUExecutionProvider"]
        if prepare().available
        else ["CPUExecutionProvider"]
    )


# --------------------------------------------------------------------------
def _detect() -> CudaStatus:
    status = CudaStatus()
    try:
        import onnxruntime as ort
    except Exception:
        log.warning("onnxruntime import qilinmadi", exc_info=True)
        return status

    status.onnxruntime_version = getattr(ort, "__version__", "")
    status.listed = "CUDAExecutionProvider" in ort.get_available_providers()
    if not status.listed or not _IS_WINDOWS:
        # Windows'dan tashqarida kutubxonalar tizim yo'lida
        # (`LD_LIBRARY_PATH`) va ularni bu yerda qidirishning
        # ma'nosi yo'q — ro'yxatdagi provayderga ishonamiz.
        status.available = status.listed
        return status

    provider_dll = _provider_dll(ort)
    if provider_dll is None:
        status.no_provider = True
        return status

    required = _required_libraries(provider_dll)
    if not required:
        # Import jadvalini o'qib bo'lmadi. Provayder ro'yxatda bor,
        # ya'ni uni ishlatib ko'rish mumkin — sessiya baribir
        # o'zining haqiqiy provayderini aytadi
        # (`OnnxEngine.providers`).
        log.info("CUDA bog'liqliklari o'qilmadi — provayder ro'yxatdagicha olinadi")
        status.available = True
        return status

    _register_directories()
    _preload_via_onnxruntime(ort)

    for name in required:
        source = _load_library(name)
        if source:
            status.loaded_from.append(source)
        else:
            status.missing.append(name)

    if not status.missing:
        _preload_cudnn_siblings(status.loaded_from)

    status.available = not status.missing
    if status.available:
        log.info(
            "CUDA tayyor (onnxruntime %s): %s ta kutubxona yuklandi",
            status.onnxruntime_version, len(required),
        )
    else:
        log.warning("CUDA ishlatilmaydi: %s", status.reason)
    return status


def _provider_dll(ort) -> Optional[Path]:
    """`onnxruntime_providers_cuda.dll` ning yo'li."""
    try:
        root = Path(ort.__file__).resolve().parent / "capi"
    except Exception:
        return None
    path = root / "onnxruntime_providers_cuda.dll"
    if not path.exists():
        log.warning("CUDA provayderi fayli topilmadi: %s", path)
        return None
    return path


def _required_libraries(path: Path) -> list:
    """
    Provayder DLL'i talab qiladigan CUDA kutubxonalari.

    PE import jadvalidan o'qiladi, ya'ni ro'yxat AYNAN shu
    o'rnatishga tegishli: CUDA 12 nashri `cublasLt64_12.dll` ni,
    CUDA 13 nashri `cublasLt64_13.dll` ni so'raydi va ularni
    almashtirib bo'lmaydi.
    """
    try:
        names = _imported_modules(path)
    except Exception:
        log.debug("PE import jadvalini o'qib bo'lmadi: %s", path, exc_info=True)
        return []
    return [
        name for name in names
        if name.lower().startswith(_CUDA_PREFIXES)
    ]


def _imported_modules(path: Path) -> list:
    """PE faylning import jadvalidagi DLL nomlari."""
    data = path.read_bytes()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        return []

    optional = pe + 24
    magic = struct.unpack_from("<H", data, optional)[0]
    # PE32+ (64 bit) da ma'lumot kataloglari 112-baytdan, PE32 da
    # 96-baytdan boshlanadi: farq `ImageBase` va uchta `SizeOf*`
    # maydonining kengligida.
    directories = optional + (112 if magic == 0x20B else 96)
    import_rva = struct.unpack_from("<I", data, directories + 8)[0]
    if not import_rva:
        return []

    sections = []
    section_count = struct.unpack_from("<H", data, pe + 6)[0]
    optional_size = struct.unpack_from("<H", data, pe + 20)[0]
    for index in range(section_count):
        offset = pe + 24 + optional_size + index * 40
        virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from(
            "<IIII", data, offset + 8
        )
        sections.append((virtual_address, max(virtual_size, raw_size), raw_offset))

    def to_offset(rva: int) -> Optional[int]:
        for address, size, raw in sections:
            if address <= rva < address + size:
                return rva - address + raw
        return None

    names: list = []
    cursor = to_offset(import_rva)
    if cursor is None:
        return []
    while True:
        descriptor = data[cursor:cursor + 20]
        # Import jadvali NOL bilan to'ldirilgan yozuv bilan tugaydi.
        if len(descriptor) < 20 or descriptor == b"\0" * 20:
            break
        name_rva = struct.unpack_from("<I", descriptor, 12)[0]
        cursor += 20
        if not name_rva:
            continue
        start = to_offset(name_rva)
        if start is None:
            continue
        end = data.index(b"\0", start)
        names.append(data[start:end].decode("ascii", "replace"))
    return names


# --------------------------------------------------------------------------
def _candidate_directories() -> list:
    """
    CUDA kutubxonalari qayerda bo'lishi mumkin — TARTIB bilan.

    Tartib ishonchlilik bo'yicha: ochiq ko'rsatilgan katalog, bundle
    bilan kelgan nusxa, `pip` paketlari, tizimdagi CUDA Toolkit.
    """
    global _directories
    if _directories is not None:
        return _directories

    directories: list = []

    def add(value) -> None:
        if not value:
            return
        path = Path(value)
        if path.is_dir() and path not in directories:
            directories.append(path)

    # 1. Ochiq ko'rsatilgan yo'l(lar) — administratorning qarori har
    #    doim ustun. Qiymat `config` dan olinadi, `os.getenv` dan
    #    emas: `.env` faylini aynan `config` o'qiydi va to'g'ridan-
    #    to'g'ri muhitdan olish uni jimgina e'tiborsiz qoldirardi.
    for item in _configured_directories().split(os.pathsep):
        add(item.strip())

    # 2. Bundle bilan kelgan nusxa. Ikki joy va ikkalasi ham kerak:
    #    o'rnatuvchi DLL'larni `_internal/cuda/` ga qo'yadi
    #    (`resource_root()` onedir'da aynan `_internal`), qo'lda
    #    to'ldiriladigan nusxa esa `.exe` YONIDAGI `cuda/` da bo'ladi -
    #    ilgari faqat birinchisi qaralardi va izohdagi "exe yonidagi"
    #    yo'l amalda ishlamasdi.
    try:
        from core.bundle_paths import is_frozen, resource_root

        add(resource_root() / "cuda")
        if is_frozen():
            add(Path(sys.executable).resolve().parent / "cuda")
    except Exception:
        log.debug("Bundle ildizi aniqlanmadi", exc_info=True)

    # 3. `pip` paketlari. `nvidia-*` g'ildiraklari rasmiy yo'l;
    #    `torch/lib` esa ishlab chiqish mashinasida allaqachon bor
    #    (torch CUDA va cuDNN ni o'zi bilan olib keladi) va u
    #    tekshiruvni qo'shimcha yuklamasdan ishlatadi.
    for site_dir in _site_packages():
        nvidia = site_dir / "nvidia"
        if nvidia.is_dir():
            for child in sorted(nvidia.iterdir()):
                add(child / "bin")
        add(site_dir / "torch" / "lib")

    # 4. Tizimdagi CUDA Toolkit.
    for name, value in os.environ.items():
        if name.upper().startswith("CUDA_PATH"):
            add(Path(value) / "bin")

    _directories = directories
    return directories


def _configured_directories() -> str:
    try:
        from config import CUDA_DLL_DIR

        return CUDA_DLL_DIR or ""
    except Exception:
        # `config` yuklanmasa (test yoki alohida ishga tushirish)
        # muhitdagi qiymat zaxira bo'lib qoladi.
        return os.getenv("CUDA_DLL_DIR", "") or ""


def _site_packages() -> list:
    paths = []
    for entry in sys.path:
        if not entry:
            continue
        path = Path(entry)
        if path.name in ("site-packages", "dist-packages") and path.is_dir():
            paths.append(path)
    return paths


def _register_directories() -> None:
    """
    Kataloglarni DLL qidiruv yo'liga qo'shadi.

    `os.add_dll_directory` YETARLI EMAS va buni bilish kerak: u
    faqat NOM bilan yuklanadigan kutubxonalarga ta'sir qiladi,
    ONNX Runtime esa provayder DLL'ini to'liq yo'l bilan yuklaydi
    va uning yashirin importlari boshqa qoidalar bo'yicha
    qidiriladi. Shuning uchun katalog qo'shish faqat BIRINCHI
    qadam; ikkinchisi — kutubxonalarni oldindan yuklash
    (`_load_library`), chunki jarayonda allaqachon yuklangan
    modul qayta qidirilmaydi.
    """
    if not _dll_dirs:
        for directory in _candidate_directories():
            try:
                _dll_dirs.append(os.add_dll_directory(str(directory)))
            except (OSError, AttributeError):
                log.debug("Katalogni qo'shib bo'lmadi: %s", directory)


def _preload_via_onnxruntime(ort) -> None:
    """
    ONNX Runtime ning o'z yuklovchisi (1.21+ da bor).

    U `nvidia-*` paketlarini bizdan yaxshiroq biladi (qaysi
    kutubxona qaysi paketda ekanini versiyaga qarab hal qiladi),
    shuning uchun avval o'shanga imkon beramiz. Bo'lmasa ham
    muammo yo'q — keyingi qadam kutubxonalarni o'zi yuklaydi.
    """
    preload = getattr(ort, "preload_dlls", None)
    if preload is None:
        return
    try:
        preload(cuda=True, cudnn=True, msvc=True)
    except Exception:
        log.debug("onnxruntime.preload_dlls ishlamadi", exc_info=True)


def _preload_cudnn_siblings(loaded: list) -> None:
    """
    cuDNN ning ICHKI kutubxonalarini to'liq yo'l bilan oldindan yuklaydi.

    `cudnn64_9.dll` provayderning import jadvalida bor va uni
    `_load_library` yuklaydi. Lekin cuDNN 9 bo'laklarga bo'lingan
    (`cudnn_graph`, `cudnn_engines_*`, `cudnn_ops`...) va ularni
    o'zi, birinchi Conv paytida, faqat NOM bo'yicha `LoadLibrary`
    qiladi - `add_dll_directory` bunga ta'sir qilmaydi. Topilmasa
    `CUDNN_BACKEND_API_FAILED` chiqadi va ONNX Runtime sessiyani
    JIMGINA CPU'ga o'tkazadi, log esa "GPU (CUDA)" deb turaveradi.
    Aynan shu holat pip'dagi cuDNN 9.26 bilan build'da bo'lgan
    (`cudnn_engines_tensor_ir64_9.dll`); 9.10 ga qadalgan, lekin
    keyingi yangilanish bu tuzoqqa qaytib tushmasligi kerak.

    `cudnn_graph` BIRINCHI: qolganlari unga bog'liq.
    """
    directories = []
    for source in loaded:
        path = Path(source)
        if path.name.lower().startswith("cudnn64_") and path.is_absolute():
            directories.append(path.parent)
    if not directories:
        # Nom bo'yicha yuklangan (torch yoki `preload_dlls`) - u holda
        # bo'laklarni ham o'sha yuklovchi olib kelgan.
        return
    for directory in directories:
        files = sorted(
            directory.glob("cudnn*64_*.dll"),
            key=lambda item: (not item.name.lower().startswith("cudnn_graph"), item.name),
        )
        for candidate in files:
            try:
                ctypes.WinDLL(str(candidate))
            except OSError:
                log.debug("cuDNN bo'lagi yuklanmadi: %s", candidate)


def _load_library(name: str) -> str:
    """
    Kutubxonani jarayonga yuklaydi. Natija — qayerdan yuklangani.

    Avval NOM bo'yicha: u allaqachon yuklangan bo'lishi mumkin
    (`preload_dlls` yoki torch) yoki qidiruv yo'lida topilishi
    mumkin. Keyin nomzod kataloglardan TO'LIQ YO'L bilan — bu
    `add_dll_directory` ta'sir qilmaydigan holatlarni qoplaydi.
    """
    try:
        ctypes.WinDLL(name)
        return name
    except OSError:
        pass

    for directory in _candidate_directories():
        candidate = directory / name
        if not candidate.exists():
            continue
        try:
            ctypes.WinDLL(str(candidate))
            return str(candidate)
        except OSError:
            log.debug("Kutubxona yuklanmadi: %s", candidate)
    return ""
