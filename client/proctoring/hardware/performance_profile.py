"""
Unumdorlik profili: apparatdan konkret sozlamalarga.

Profil BITTA joyda tanlanadi va undan keyin butun pipeline uni
o'qiydi. Muqobil — har bir modul o'zi "GPU bormi?" deb so'rashi
edi va u ikki narsani buzardi: qaror to'rt joyda takrorlanardi
(va ajralib ketardi), hamda modullar bir-biriga mos kelmaydigan
qarorlar qabul qilishi mumkin edi — masalan yuz moduli GPU'ni
tanlab, obyekt moduli CPU'ga tushib, ikkalasi ham sekinlashardi.

CHEGARALAR QAT'IY EMAS. Profil "shu mashinada nima ishlaydi"
degan TAXMIN va u har doim to'g'ri bo'lavermaydi: bir xil GTX 1660
Super ikki xil mashinada boshqacha natija beradi (PCIe versiyasi,
CPU, sovutish). Shuning uchun profil pipeline ishga tushgach
PASAYTIRILISHI mumkin — bu modul faqat BOSHLANG'ICH qiymatni
beradi.

MINIMAL TAVSIYA ETILADIGAN GPU — GTX 1660 Super (6 GB). U
`MEDIUM` profilining pastki chegarasi: YOLOv8s 512 FP16 + ArcFace
bemalol sig'adi va ~30 FPS xom kadr oqimida barcha modullar o'z
chastotasida ishlaydi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from proctoring.hardware.gpu_detector import HardwareInfo

log = logging.getLogger(__name__)


@dataclass
class PerformanceProfile:
    """Bitta profil: model o'lchami, aniqlik va chastotalar."""

    name: str
    label: str
    #: ONNX Runtime provayderlari (tartib MUHIM - birinchisi ustun).
    providers: list = field(default_factory=lambda: ["CPUExecutionProvider"])
    #: FP16 yarim aniqlik. Faqat CUDA'da ma'noga ega: CPU'da u
    #: sekinlashtiradi (har amalda float32 ga o'girish kerak).
    fp16: bool = False

    #: Modellarning kirish o'lchami.
    detect_size: int = 640
    pose_size: int = 640
    face_det_size: int = 640

    #: Model fayli qo'shimchasi: `yolov8{suffix}.onnx`.
    model_suffix: str = "n"

    #: Har bir modulning MAKSIMAL chastotasi (kadr/soniya).
    #
    # Siyosat (`ProctoringPolicy.*_fps`) bundan PASTROQ qiymat
    # so'rashi mumkin va o'shanda siyosat yutadi. Yuqoriroq
    # so'rasa - profil yutadi: apparat ko'tara olmaydigan
    # chastotani siyosat bilan majburlab bo'lmaydi.
    identity_fps: int = 5
    object_fps: int = 2
    pose_fps: int = 3
    gaze_fps: int = 5

    #: Bir vaqtda ishlaydigan inference thread'lari.
    intra_threads: int = 0          # 0 - ONNX Runtime o'zi tanlaydi
    #: Kadr navbatining uzunligi. To'lganda ENG ESKI kadr tashlanadi.
    queue_size: int = 2

    def limit_fps(self, module: str, requested: int) -> int:
        """
        Siyosat so'ragan chastotani apparat imkoniyati bilan cheklaydi.

        `0` - modul o'chirilgan. Bu qiymat HAR DOIM o'tadi: siyosat
        modulni o'chirsa, apparat uni yoqa olmaydi.
        """
        ceiling = getattr(self, "{}_fps".format(module), 0)
        if requested <= 0:
            return 0
        return max(1, min(int(requested), int(ceiling)))

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "providers": list(self.providers),
            "fp16": self.fp16,
            "detect_size": self.detect_size,
            "model_suffix": self.model_suffix,
            "fps": {
                "identity": self.identity_fps,
                "objects": self.object_fps,
                "pose": self.pose_fps,
                "gaze": self.gaze_fps,
            },
        }


_CUDA = ["CUDAExecutionProvider", "CPUExecutionProvider"]

#: Profillar. Nom SERVERGA ham ketadi (`ExamSession.ai_profile`),
#: shuning uchun kalitlar barqaror bo'lishi shart.
PROFILES: dict[str, PerformanceProfile] = {
    "high": PerformanceProfile(
        name="high",
        label="Yuqori (RTX 4070+)",
        providers=_CUDA,
        fp16=True,
        detect_size=640,
        pose_size=640,
        face_det_size=640,
        model_suffix="m",
        identity_fps=15,
        object_fps=10,
        pose_fps=10,
        gaze_fps=15,
        queue_size=3,
    ),
    "medium": PerformanceProfile(
        name="medium",
        label="O'rta (GTX 1660S / RTX 2060-3060)",
        providers=_CUDA,
        fp16=True,
        detect_size=512,
        pose_size=512,
        face_det_size=640,
        model_suffix="s",
        identity_fps=10,
        object_fps=6,
        pose_fps=8,
        gaze_fps=10,
        queue_size=2,
    ),
    "low": PerformanceProfile(
        name="low",
        label="Past (kuchsiz GPU)",
        providers=_CUDA,
        fp16=False,
        detect_size=416,
        pose_size=416,
        face_det_size=480,
        model_suffix="n",
        identity_fps=6,
        object_fps=3,
        pose_fps=4,
        gaze_fps=6,
        queue_size=2,
    ),
    "cpu": PerformanceProfile(
        name="cpu",
        label="Faqat CPU",
        providers=["CPUExecutionProvider"],
        fp16=False,
        detect_size=416,
        pose_size=416,
        face_det_size=480,
        model_suffix="n",
        # CPU'da obyekt aniqlash 416x416 da ~300 ms oladi. 2 FPS -
        # bu real chegara; undan yuqorisi kadr navbatini to'ldiradi
        # va kechikish bir necha soniyaga chiqadi.
        identity_fps=3,
        object_fps=1,
        pose_fps=1,
        gaze_fps=3,
        intra_threads=2,
        queue_size=1,
    ),
    #: Eng zaif mashinalar: FAQAT shaxs tekshiruvi.
    #
    # Loyihaning `client/config.py` izohida imtihon mashinasi
    # "ko'pincha 4 GB RAM" deb yozilgan. Bunday mashinada YOLO ham,
    # poza ham xotiraga sig'maydi va ularni ishga tushirish butun
    # dasturni almashinuv fayliga tushirib yuboradi - imtihon esa
    # umuman ishlamay qoladi.
    #
    # Shuning uchun eng past profil "hammasini sekin qilish" emas,
    # "eng muhimini saqlab qolish": yuz tekshiruvi ishlaydi,
    # qolgani o'chadi.
    "minimal": PerformanceProfile(
        name="minimal",
        label="Minimal (zaif mashina — faqat yuz)",
        providers=["CPUExecutionProvider"],
        fp16=False,
        detect_size=320,
        pose_size=320,
        face_det_size=320,
        model_suffix="n",
        identity_fps=2,
        object_fps=0,
        pose_fps=0,
        gaze_fps=0,
        intra_threads=1,
        queue_size=1,
    ),
}

#: `minimal` profilga tushirish chegaralari.
_MINIMAL_RAM_GB = 6.0
_MINIMAL_CORES = 4

#: GPU profillarining VRAM chegaralari (foydalanish mumkin bo'lgan).
_HIGH_VRAM_MB = 7000
_MEDIUM_VRAM_MB = 3500


def select_profile(info: HardwareInfo, *, override: str = "") -> PerformanceProfile:
    """
    Apparatga mos profilni tanlaydi.

    `override` — siyosatdagi `gpu_profile_override` (`auto` yoki
    aniq nom). Administrator tanlovi HAR DOIM ustun: u mashinani
    ko'rgan va avtomatik tanlov noto'g'ri bo'lishi mumkin.
    Noma'lum nom e'tiborsiz qoldiriladi va log'da qoladi.
    """
    override = (override or "").strip().lower()
    if override and override != "auto":
        profile = PROFILES.get(override)
        if profile is not None:
            log.info("Unumdorlik profili siyosatdan: %s", profile.name)
            return profile
        log.warning("Noma'lum profil '%s' — avtomatik tanlovga o'tildi", override)

    # 1. Eng zaif mashinalar - GPU bor-yo'qligidan QAT'I NAZAR.
    #
    # Tekshiruv birinchi turadi: 4 GB RAM li mashinada diskret
    # karta bo'lishi mumkin, lekin modellarni yuklash uchun
    # tizim xotirasi baribir yetmaydi (ONNX modelni avval RAM'ga
    # o'qiydi).
    if info.ram_gb and info.ram_gb < _MINIMAL_RAM_GB:
        log.info("Minimal profil: RAM %.1f GB < %.1f GB", info.ram_gb, _MINIMAL_RAM_GB)
        return PROFILES["minimal"]
    if info.cpu_cores and info.cpu_cores < _MINIMAL_CORES and not info.cuda_available:
        log.info("Minimal profil: %s yadro, GPU yo'q", info.cpu_cores)
        return PROFILES["minimal"]

    # 2. CUDA yo'q - CPU. Sabab `gpu_warning` da va u log'da
    #    allaqachon chiqqan.
    if not info.cuda_available:
        return PROFILES["cpu"]

    # 3. VRAM bo'yicha. Karta NOMI bo'yicha emas: ro'yxat har yili
    #    eskiradi va noma'lum yangi model eng past profilga
    #    tushib qolardi.
    vram = info.usable_vram_mb
    if vram >= _HIGH_VRAM_MB:
        return PROFILES["high"]
    if vram >= _MEDIUM_VRAM_MB:
        return PROFILES["medium"]
    return PROFILES["low"]
