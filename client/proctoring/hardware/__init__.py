"""
Apparat aniqlash va unumdorlik profili.

Ikki savol, ikki modul:

    gpu_detector        - mashinada NIMA bor?
    performance_profile - shu apparatda NIMA ishlatiladi?

Ikkalasi ataylab ajratilgan: birinchisi faktlarni yig'adi va hech
qanday qaror qabul qilmaydi, ikkinchisi esa qaror qabul qiladi va
o'lchamaydi. Aralashtirilsa, "GPU bor" degan faktdan "demak yuqori
profil" degan xulosa avtomatik chiqib ketardi - holbuki bu ikkisi
orasida CUDA kutubxonalari, VRAM hajmi va model fayllarining
mavjudligi turadi.
"""

from proctoring.hardware.gpu_detector import HardwareInfo, detect, hardware_probe
from proctoring.hardware.performance_profile import (
    PROFILES,
    PerformanceProfile,
    select_profile,
)

__all__ = [
    "HardwareInfo",
    "PROFILES",
    "PerformanceProfile",
    "detect",
    "hardware_probe",
    "report",
    "select_profile",
]


def report(timeout: float = 0.0) -> dict:
    """
    Handshake uchun apparat xabari.

    Profil bu yerda `override` SIZ tanlanadi va bu ataylab:
    handshake login paytida, imtihon tanlashdan OLDIN bajariladi -
    o'sha paytda qaysi siyosat qo'llanishi hali ma'lum emas
    (`gpu_profile_override` imtihon profilida yotadi). Ya'ni bu
    qiymat "mashina NIMA KO'TARADI" degan savolga javob beradi,
    "kuzatuv qaysi profilda ishladi" degan savolga emas -
    ikkinchisi sessiyada (`ExamSession.ai_profile`) qoladi va u
    yerda override ham hisobga olingan.

    Aniqlanmagan bo'lsa qiymatlar BO'SH qaytadi va bu xato emas:
    server bo'sh maydonga tegmaydi, keyingi handshake esa
    (operator har imtihonda qaytadan kiradi) tayyor qiymatni
    yozadi.
    """
    info = hardware_probe.resolve(timeout)
    if hardware_probe.cached is None:
        # Hali aniqlanmagan. Tekshiruv AYNAN shu (maydonlar bo'sh
        # emasligi EMAS): `nvidia-smi` yo'q, psutil yo'q va
        # onnxruntime yo'q mashinada natija haqiqatan ham bo'sh
        # bo'ladi va u ham to'liq javob - "hech narsa topilmadi"
        # degani "hali qaramadik" degani emas.
        return {}
    profile = select_profile(info)
    return {
        "gpu_name": info.gpu_name,
        "performance_profile": profile.name,
        "detail": info.as_dict(),
    }
