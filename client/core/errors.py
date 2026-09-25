"""
Client tomonidagi xato modeli.

Backend har bir xatoni `{success:false, error:{code, message, details}}`
konvertida qaytaradi (`apps.common.exceptions.api_exception_handler`).
`code` — barqaror kalit, `message` esa o'zgarishi mumkin. Shuning uchun
QARORLAR faqat `code` bo'yicha qabul qilinadi, `message` esa ekranga
chiqariladi.
"""

from __future__ import annotations


class ClientError(Exception):
    """Foydalanuvchiga ko'rsatiladigan xato."""

    def __init__(self, message: str, *, code: str = "", details=None, status: int = 0):
        super().__init__(message)
        self.message = message
        self.code = code or ""
        self.details = details or {}
        self.status = status

    def __str__(self) -> str:
        return self.message


class NetworkError(ClientError):
    """Serverga umuman yetib bo'lmadi (DNS, timeout, uzilish)."""


class AuthError(ClientError):
    """401/403 — qayta login qilish yoki ruxsat yetishmasligi."""


class DeviceNotRegistered(ClientError):
    """
    Server bu `device_id` ni umuman bilmaydi.

    Tasdiqlanmagan (`device_not_approved`) holatidan FARQ QILADI: bu
    yerda qayta ro'yxatdan o'tish o'rinli, u yerda esa faqat kutish
    kerak.
    """


#: Backend `code` -> foydalanuvchi tilidagi xabar.
#:
#: Server matni ham keladi, lekin oqimga ta'sir qiladigan holatlar uchun
#: client o'z matnini beradi: operator nima qilishi kerakligini aniq
#: bilishi shart ("kuting" / "adminga murojaat" / "qayta urining").
ERROR_MESSAGES = {
    "device_not_registered": "Qurilma serverda topilmadi - qayta ro'yxatdan o'tilmoqda.",
    "device_not_approved": "Qurilma administrator tasdig'ini kutmoqda. Tasdiqlangach qaytadan kiring.",
    "device_revoked": "Bu qurilma bloklangan. Administratorga murojaat qiling.",
    "device_already_registered": "Bu kompyuter boshqa mashinaga biriktirilgan. Administratorga murojaat qiling.",
    "device_computer_inactive": "Kompyuter hisobdan chiqarilgan. Administratorga murojaat qiling.",
    "ip_not_allowed": (
        "Tashqi IP manzilga ruxsat yo'q. Bu kompyuter ro'yxatga olinmagan "
        "tarmoqdan ulanmoqda - administratorga murojaat qiling."
    ),
    "ip_allowlist_empty": (
        "Ruxsat etilgan IP'lar ro'yxati bo'sh - administrator hali birorta "
        "manzilni qo'shmagan. Administratorga murojaat qiling."
    ),
    "public_ip_unknown": (
        "Internetga chiqish manzili aniqlanmadi. Tarmoq ulanishini tekshiring."
    ),
    # `candidate_not_found` — platforma JSHSHIR'ni UMUMAN topmadi.
    # Birinchi harakat: raqamni tekshirish, shuning uchun matn ham
    # shu haqda (server matni "Not found" — operatorga hech nima
    # aytmaydi).
    "candidate_not_found": (
        "Bu JSHSHIR test platformasida topilmadi. Raqamni tekshirib "
        "qaytadan kiriting."
    ),
    # `candidate_not_eligible` ATAYLAB RO'YXATDA YO'Q: bu holatda
    # talabgor TOPILGAN, lekin ruxsat yo'q va sababni platformaning
    # o'zi aytadi ("Imtihon kuni emas", "Test allaqachon
    # topshirilgan"). Bizning umumiy matnimiz o'sha aniq sababni
    # bosib qo'yardi — `humanize` server matnini o'tkazadi.
    "session_already_active": "Bu talabgorning boshqa kompyuterda ochiq sessiyasi bor.",
    "exam_not_open": "Imtihon kirish oynasi hozir yopiq.",
    "face_verification_failed": "Yuz mos kelmadi. Qaytadan urinib ko'ring.",
    "identity_not_confirmed": "Avval talabgor shaxsini hujjat bo'yicha tasdiqlang.",
    "session_not_found": "Sessiya topilmadi yoki muddati tugagan.",
    "session_forbidden": "Bu sessiya boshqa qurilmaga tegishli.",
    "external_platform_error": "Tashqi test platformasi javob bermayapti.",
    "throttled": "Juda ko'p urinish. Biroz kutib qaytadan urining.",
}


def humanize(code: str, fallback: str) -> str:
    return ERROR_MESSAGES.get(code, fallback or "Noma'lum xato")
