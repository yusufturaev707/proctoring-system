"""
Lokal kamera nega ishlamayapti — operatorga tushunarli SABAB.

OpenCV barcha nosozliklarni bitta ko'rinishda beradi: `isOpened()`
`False` yoki `read()` bo'sh. Operator uchun esa ular butunlay
boshqa ishlar:

    | Sabab                         | Kim, nima qiladi                       |
    |-------------------------------|----------------------------------------|
    | Windows maxfiylik taqiqi       | Sozlamalarda kameraga ruxsat beradi    |
    | qurilma ro'yxatda yo'q         | kabelni tekshiradi / qayta ulaydi      |
    | qurilma bor, lekin ochilmaydi  | kamerani band qilgan dasturni yopadi   |

Bitta umumiy "Kamera ochilmadi" matni operatorni noto'g'ri joyni
qidirishga majbur qilardi: maxfiylik taqiqida kabelni qayta ulash
hech narsa bermaydi.

MAXFIYLIK TAQIG'I registrdan o'qiladi
(`CapabilityAccessManager\\ConsentStore\\webcam`). Bu Windows'ning
"Sozlamalar → Maxfiylik va xavfsizlik → Kamera" sahifasi yozadigan
joy: `HKLM` — butun kompyuter uchun, `HKCU` — joriy foydalanuvchi,
`NonPackaged` kalit — "ish stoli ilovalariga ruxsat" (bizning dastur
aynan shu turga kiradi). Aniqlash XAVFSIZLIK CHEGARASI EMAS — faqat
xabar tanlash uchun; o'qib bo'lmasa "taqiq yo'q" deb hisoblanadi.
"""

from __future__ import annotations

import logging
import sys
from typing import Callable, Optional

log = logging.getLogger(__name__)

_CONSENT_KEY = (
    r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager"
    r"\ConsentStore\webcam"
)

PRIVACY_MESSAGE = (
    "Windows kameradan foydalanishni taqiqlagan. Sozlamalar → Maxfiylik "
    "va xavfsizlik → Kamera bo'limida «Kameraga kirish» va «Ish stoli "
    "ilovalariga kameradan foydalanishga ruxsat berish» ni yoqing. "
    "Qayta ulanish avtomatik davom etadi."
)

NOT_FOUND_MESSAGE = (
    "Kamera topilmadi — u uzilgan yoki kabeli chiqib ketgan. Kamerani "
    "qayta ulang; dastur uni o'zi qayta ochadi."
)

BUSY_MESSAGE = (
    "Kamera ochilmadi — uni boshqa dastur (Kamera, Zoom, Teams, brauzer) "
    "band qilgan bo'lishi mumkin. O'sha dasturni yoping; dastur kamerani "
    "o'zi qayta ochadi."
)

LOST_MESSAGE = (
    "Kameradan kadr kelmayapti — u uzilgan yoki javob bermayapti. "
    "Qayta ulanish avtomatik davom etadi."
)


def _read_consent(hive, subkey: str) -> str:
    """Registrdagi `Value` ("Allow"/"Deny") yoki bo'sh satr."""
    import winreg

    try:
        with winreg.OpenKey(hive, subkey) as key:
            value, _kind = winreg.QueryValueEx(key, "Value")
    except OSError:
        return ""
    return str(value or "")


def privacy_denied(reader: Optional[Callable[[object, str], str]] = None) -> bool:
    """
    Windows maxfiylik sozlamasi kamerani taqiqlaganmi.

    `reader(hive, subkey) -> "Allow" | "Deny" | ""` — testda
    almashtiriladi. Xato yoki Windows emas — `False`.
    """
    if sys.platform != "win32" and reader is None:
        return False
    try:
        import winreg

        read = reader or _read_consent
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for subkey in (_CONSENT_KEY, _CONSENT_KEY + r"\NonPackaged"):
                if read(hive, subkey).strip().lower() == "deny":
                    return True
    except Exception:
        log.debug("Kamera maxfiylik sozlamasini o'qib bo'lmadi", exc_info=True)
    return False


def device_present(index: Optional[int], device_path: str = "", devices=None) -> Optional[bool]:
    """
    Qurilma DirectShow ro'yxatida bormi.

    `None` — aniqlab bo'lmadi (ro'yxat olinmadi): bunday holatda
    "topilmadi" deyish xato bo'lardi, chaqiruvchi umumiy matnni tanlaydi.
    `devices` — testda beriladi; berilmasa `dshow.enumerate_devices()`.
    """
    if devices is None:
        if sys.platform != "win32":
            return None
        try:
            from proctoring.camera.dshow import enumerate_devices

            devices = enumerate_devices()
        except Exception:
            log.debug("DirectShow ro'yxati olinmadi", exc_info=True)
            return None
    devices = list(devices or [])
    if not devices:
        # Bo'sh ro'yxat — ikkala ma'no ham mumkin (kamera yo'q yoki COM
        # xatosi), lekin amalda deyarli har doim birinchisi: ulangan
        # kamera DirectShow'da doim sanaladi.
        return False
    if device_path:
        return any(getattr(item, "device_path", "") == device_path for item in devices)
    if index is None:
        return None
    return any(getattr(item, "index", None) == index for item in devices)


def explain_local_failure(
    index: Optional[int],
    device_path: str = "",
    *,
    lost: bool = False,
    privacy_reader=None,
    devices=None,
) -> str:
    """
    Lokal kamera ochilmadi (`lost=False`) yoki kadr bermay qo'ydi
    (`lost=True`) — sababga mos xabar.

    Tartib muhim: maxfiylik taqig'i birinchi (u yoqilgan bo'lsa
    qurilma ro'yxatda bor, lekin ochilmaydi — "band" deb aytish
    operatorni yo'q dasturni qidirishga yuborardi).
    """
    if privacy_denied(privacy_reader):
        return PRIVACY_MESSAGE
    present = device_present(index, device_path, devices)
    if present is False:
        return NOT_FOUND_MESSAGE
    return LOST_MESSAGE if lost else BUSY_MESSAGE
