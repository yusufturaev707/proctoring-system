import logging
import random

from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from django.db import IntegrityError, InterfaceError, OperationalError
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Domen xatolari
# --------------------------------------------------------------------------
class DomainError(APIException):
    """
    Biznes-qoida buzilishi. `code` React tomonda tarjima kaliti bo'ladi.

    `extra` — javobning `error.details` qismiga tushadigan TUZILGAN
    ma'lumot. Matn odam uchun, `extra` esa dastur uchun: masalan
    "talabgor boshqa kompyuterga biriktirilgan" xatosida client
    qaysi kompyuterga borish kerakligini matndan ajratib olmaydi —
    raqam, bino va viloyat alohida maydonlarda keladi.
    """

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "So'rovni bajarib bo'lmadi"
    default_code = "domain_error"

    def __init__(self, detail=None, code=None, *, extra: dict | None = None):
        super().__init__(detail, code)
        self.extra = extra


class CameraStreamUnavailable(DomainError):
    """Kamera oqimidan kadr olib bo'lmadi (paneldagi jonli ko'rish)."""

    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Kamera oqimidan kadr olib bo'lmadi"
    default_code = "camera_stream_unavailable"


class CameraViewerUnavailable(DomainError):
    """Serverda dekoder (OpenCV) yo'q - jonli ko'rish o'rnatilmagan."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Serverda OpenCV o'rnatilmagan (opencv-python-headless)"
    default_code = "camera_viewer_unavailable"


class CameraViewerBusy(DomainError):
    """Shu jarayonda jonli ko'rishlar chegarasi to'lgan."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Hozir juda ko'p jonli ko'rish ochiq - biroz kuting"
    default_code = "camera_viewer_busy"


class CameraInactive(DomainError):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Kamera faol emas yoki o'chirilgan"
    default_code = "camera_inactive"


class SessionNotFound(DomainError):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "Imtihon sessiyasi topilmadi yoki muddati tugagan"
    default_code = "session_not_found"


class SessionAlreadyActive(DomainError):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Ushbu talabgor uchun boshqa kompyuterda faol sessiya mavjud"
    default_code = "session_already_active"


class SessionForbidden(DomainError):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "Sessiya ushbu qurilmaga tegishli emas"
    default_code = "session_forbidden"


class FaceVerificationFailed(DomainError):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "Yuz tekshiruvidan o'tilmadi"
    default_code = "face_verification_failed"


class IdentityNotConfirmed(DomainError):
    """
    Operator talabgor shaxsini hujjat bo'yicha hali tasdiqlamagan.

    FaceID buni ayta olmaydi — etalon shu sessiyaning o'zida olinadi.
    Shuning uchun imtihonga kirish aynan shu nuqtada to'siladi.
    """

    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "Talabgor shaxsi operator tomonidan tasdiqlanmagan"
    default_code = "identity_not_confirmed"


class IdentityAlreadyConfirmed(DomainError):
    """Tasdiq bir marta beriladi — audit izini qayta yozib bo'lmaydi."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "Bu sessiyada shaxs allaqachon tasdiqlangan"
    default_code = "identity_already_confirmed"


class DeviceNotRegistered(DomainError):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = "Qurilma ro'yxatdan o'tmagan yoki bloklangan"
    default_code = "device_not_registered"


class DeviceNotApproved(DomainError):
    """
    Qurilma bazada BOR, lekin admin hali tasdiqlamagan (`PENDING`).

    `DeviceNotRegistered` dan ATAYLAB ajratilgan: client ikkalasiga
    boshqacha javob berishi kerak. Noma'lum `device_id` - qayta
    ro'yxatdan o'tish sababi; tasdiqlanmagan qurilma esa faqat kutishni
    talab qiladi. Ajratilmasa, client har login'da yangi `PENDING` qator
    yaratib, adminga o'nlab bir xil qurilma ko'rsatardi.
    """

    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = "Qurilma administrator tasdig'ini kutmoqda"
    default_code = "device_not_approved"


class DeviceRevoked(DomainError):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = "Qurilma bloklangan"
    default_code = "device_revoked"


class DeviceComputerInactive(DomainError):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = "Kompyuter hisobdan chiqarilgan"
    default_code = "device_computer_inactive"


class DeviceSignatureInvalid(DomainError):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = "Qurilma imzosi noto'g'ri"
    default_code = "device_signature_invalid"


class IpNotAllowed(DomainError):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "Ushbu IP manzildan kirish taqiqlangan"
    default_code = "ip_not_allowed"


class PublicIpUnknown(DomainError):
    """
    Client qaysi tashqi manzildan kelayotgani ANIQLANMADI.

    `ip_not_allowed` dan farq qiladi va shuning uchun alohida kod: u
    yerda manzil ma'lum va u ro'yxatda yo'q (administrator IP qo'shishi
    kerak), bu yerda esa manzilning o'zi yo'q — clientda internet yo'q.
    Ikkalasi operatorga butunlay boshqa harakatni ko'rsatadi.
    """

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Tashqi IP manzil aniqlanmadi — internet aloqasini tekshiring"
    default_code = "public_ip_unknown"


class ExternalPlatformError(DomainError):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Tashqi test platformasi javob bermayapti"
    default_code = "external_platform_error"


class ExternalPlatformUnavailable(DomainError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Tashqi platforma vaqtincha mavjud emas, biroz kuting"
    default_code = "external_platform_unavailable"


class MachineNotVerified(DomainError):
    """
    Mashina (Machine UUID, MAC) qurilma biriktirilgan kompyuterga mos emas.

    Handshake buni faqat BAYROQ bilan aytadi (`machine.allowed`) va to'siqni
    client UI qo'yadi; `REQUIRE_MACHINE_MATCH=true` da server ham JSHSHIR
    tekshiruvida rad etadi — o'zgartirilgan client bayroqni e'tiborsiz
    qoldirib imtihon ochmasligi uchun. Matn `verify_machine` dan (handshake
    bilan bir xil), `details.status` — `not_found` / `mismatch` / ...
    """

    status_code = status.HTTP_409_CONFLICT
    default_detail = "Bu mashina bazadagi kompyuter yozuviga mos kelmadi"
    default_code = "machine_not_verified"


class BackendUnavailable(DomainError):
    """
    Redis yoki PostgreSQL vaqtincha javob bermayapti — 503 + `Retry-After`.

    Ilgari bunday xato 500 `internal_error` bo'lib chiqardi: client uni
    "server buzilgan" deb tushunardi va server "qachon qaytish kerak"
    degan signal bermasdi. `Retry-After` TASODIFIY (5–15 s): 5000 client
    bir xil muddatni olsa, tiklangan serverga hammasi bir soniyada
    qaytib urilardi. Client 503 ni va bu sarlavhani hurmat qiladi
    (`client/services/api_client.py`, `Retry-After` darvozasi).
    """

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Server vaqtincha band — biroz kutib qayta urinib ko'ring"
    default_code = "service_unavailable"

    def __init__(self, detail=None, code=None, *, extra: dict | None = None):
        super().__init__(detail, code, extra=extra)
        # DRF handler'i `wait` dan `Retry-After` sarlavhasini yasaydi.
        self.wait = random.randint(5, 15)


class CandidateNotFound(DomainError):
    """
    Tashqi platforma talabgorni UMUMAN topmadi (`status != 1`).

    `CandidateNotEligible` dan ATAYLAB ajratilgan va bu operator
    uchun ikki boshqa harakat: bu yerda JSHSHIR xato kiritilgan
    bo'lishi mumkin (raqamni tekshirish kerak), u yerda esa raqam
    to'g'ri va sabab platformada (ro'yxatda yo'q, imtihon kuni
    emas). Bitta xato kodi bilan operator qaysi biri ekanini
    bilmasdi.
    """

    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "Talabgor test platformasida topilmadi"
    default_code = "candidate_not_found"


class CandidateNotEligible(DomainError):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "Talabgorda ushbu imtihonga ruxsat yo'q"
    default_code = "candidate_not_eligible"


class ExamNotOpen(DomainError):
    """
    Kirish oynasi yopiq (`ExamSchedule`).

    Bu shunchaki qulaylik tekshiruvi emas: oynadan tashqarida JSHSHIR
    qidiruvi ochiq qolsa, endpoint fuqarolarning F.I.Sh. sini 24/7
    qidirish servisiga aylanadi.
    """

    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "Imtihonga kirish oynasi hozir ochiq emas"
    default_code = "exam_not_open"


class SeatNotBooked(DomainError):
    """
    Test sessiyasida bron YURITILADI, lekin talabgor hech qaysi
    kompyuterga biriktirilmagan.

    Tashqi platformaga so'rov KETMAYDI: joyi yo'q talabgor bu binoda
    imtihon topshira olmaydi va uning ma'lumotini so'rash kerak emas.
    """

    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "Talabgor bu test sessiyasida hech qaysi kompyuterga biriktirilmagan"
    default_code = "seat_not_booked"


class WrongComputer(DomainError):
    """
    Talabgor BOSHQA kompyuterga biriktirilgan.

    `extra.seat` — u borishi kerak bo'lgan joy (raqam, bino, viloyat),
    `extra.current` — hozirgi mashina. Client ikkalasini yonma-yon
    ko'rsatadi: operator talabgorni to'g'ri stolga yo'naltiradi.
    """

    status_code = status.HTTP_409_CONFLICT
    default_detail = "Talabgor boshqa kompyuterga biriktirilgan"
    default_code = "wrong_computer"


class SeatOutOfService(DomainError):
    """Talabgorning kompyuteri shu sessiyada BUZILGAN deb belgilangan."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = (
        "Talabgorga biriktirilgan kompyuter buzilgan deb belgilangan — "
        "administrator uni boshqa kompyuterga ko'chirishi kerak"
    )
    default_code = "seat_out_of_service"


class SeatUnavailable(DomainError):
    """Panel/API: tanlangan joy band, buzilgan yoki sessiya doirasida emas."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "Bu kompyuterga biriktirib bo'lmaydi"
    default_code = "seat_unavailable"


class SeatInUse(DomainError):
    """
    Talabgor shu joyda IMTIHONDA — bronni bo'shatib ham, ko'chirib ham bo'lmaydi.

    Yo'l ikkita va ikkalasi ham sessiya orqali: talabgor «Yakunlash» ni
    bosadi yoki administrator uni CHETLASHTIRADI — ikkalasida joy o'zi
    bo'shaydi (`bookings.release_after_session`).
    """

    status_code = status.HTTP_409_CONFLICT
    default_detail = (
        "Talabgor hozir imtihonda — joyni bo'shatib bo'lmaydi. "
        "Avval sessiyani chetlashtiring."
    )
    default_code = "seat_in_use"


class ScreenshotRejected(DomainError):
    """
    Yuklangan fayl rasm emas yoki ruxsat etilmagan formatda.

    Client'ning `Content-Type` i ham, kengaytmasi ham tekshirilmaydi —
    ikkalasi ham oddiy satr. Qaror faqat baytlarning o'ziga qarab
    qabul qilinadi (`services/screenshots.py`).
    """

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Fayl haqiqiy rasm emas yoki formati qo'llab-quvvatlanmaydi"
    default_code = "screenshot_rejected"


class ScreenshotTooLarge(DomainError):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    default_detail = "Skrinshot hajmi ruxsat etilgan chegaradan katta"
    default_code = "screenshot_too_large"


class ScreenshotNotFound(DomainError):
    """
    DB'da qator bor, lekin fayl diskda yo'q.

    Odatda retention fayllarni o'chirib, qatorlarni o'chirishga ulgurmagan
    holat. Proktor uchun bu 404, tizim uchun esa log'dagi ogohlantirish.
    """

    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "Skrinshot fayli topilmadi"
    default_code = "screenshot_not_found"


class ScreenshotStoreFailed(DomainError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Skrinshotni saqlab bo'lmadi, keyinroq urinib ko'ring"
    default_code = "screenshot_store_failed"


# --------------------------------------------------------------------------
# Exception handler
# --------------------------------------------------------------------------
def _flatten(detail):
    """DRF detail obyektini JSON-safe strukturaga aylantiradi."""
    if isinstance(detail, dict):
        return {key: _flatten(value) for key, value in detail.items()}
    if isinstance(detail, (list, tuple)):
        return [_flatten(item) for item in detail]
    return str(detail)


#: DB cheklovi nomi -> foydalanuvchi uchun tushunarli xabar.
#
# PostgreSQL xatosi ("duplicate key value violates unique constraint
# \"unique_zone_region_number\"") foydalanuvchiga hech narsa aytmaydi.
# Cheklov nomlari migratsiyalarda aniq belgilangan, shuning uchun ularni
# xaritalash ishonchli.
CONSTRAINT_MESSAGES = {
    # --- Shartli cheklovlar (soft-delete modellar) ---
    # Bular `deleted_at IS NULL` sharti bilan ishlaydi, ya'ni o'chirilgan
    # yozuv nom/kod/MAC ni band qilib qolmaydi.
    "unique_zone_region_number": "Bu viloyatda shunday raqamli bino allaqachon mavjud",
    "unique_computer_zone_ip": "Bu binoda shunday IP manzilli kompyuter allaqachon mavjud",
    "unique_computer_inventory_code": "Bunday inventar kodi allaqachon ishlatilgan",
    "unique_computer_zone_number": "Bu binoda shu raqamli kompyuter allaqachon bor",
    "unique_computer_mac": "Bunday MAC manzilli kompyuter allaqachon ro'yxatdan o'tgan",
    "unique_camera_mac": "Bunday MAC manzilli kamera allaqachon ro'yxatdan o'tgan",
    "unique_exam_name": "Bunday nomli imtihon allaqachon mavjud",
    "unique_setting_name": "Bunday nomli profil allaqachon mavjud",
    "unique_active_setting": "Global standart profil faqat bitta bo'lishi mumkin",

    # --- Oddiy unique (soft-delete emas) ---
    "unique_session_attempt": "Bu talabgor uchun shu urinish allaqachon qayd etilgan",
    "unique_session_client_event": "Bu hodisa allaqachon qabul qilingan",
    "device_token_device_id_key": "Bunday qurilma ID allaqachon ro'yxatdan o'tgan",
    "users_username_key": "Bunday login allaqachon band",
    "region_name_key": "Bunday nomli viloyat allaqachon mavjud",
    "region_dtm_id_key": "Bunday DTM ID allaqachon ishlatilgan",
    "region_vm_number_key": "Bunday VM raqami allaqachon ishlatilgan",
    "roles_name_key": "Bunday nomli rol allaqachon mavjud",
    "roles_key_key": "Bunday kalitli rol allaqachon mavjud",
}


def _integrity_message(exc: IntegrityError) -> str:
    text = str(exc)
    for constraint, message in CONSTRAINT_MESSAGES.items():
        if constraint in text:
            return message
    if "violates foreign key" in text or "still referenced" in text:
        return "Bu yozuvga boshqa ma'lumotlar bog'langan — avval ularni o'chiring"
    if "duplicate key" in text:
        return "Bunday yozuv allaqachon mavjud"
    if "not-null constraint" in text:
        return "Majburiy maydon to'ldirilmagan"
    return "Ma'lumot yaxlitligi buzildi"


def api_exception_handler(exc, context):
    if isinstance(exc, Http404):
        exc = DomainError("Obyekt topilmadi", code="not_found")
        exc.status_code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, PermissionDenied):
        exc = DomainError("Ruxsat yo'q", code="permission_denied")
        exc.status_code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, DjangoValidationError):
        exc = DomainError(_flatten(exc.message_dict if hasattr(exc, "message_dict") else exc.messages))
    elif isinstance(exc, IntegrityError):
        logger.warning("IntegrityError: %s", exc)
        exc = DomainError(_integrity_message(exc), code="integrity_error")
        exc.status_code = status.HTTP_409_CONFLICT
    elif isinstance(exc, (RedisError, OperationalError, InterfaceError)):
        # Infratuzilma nosozligi (Redis/DB ulanishi), kod xatosi emas:
        # stack trace emas, bitta qator — uzilish paytida 5000 client
        # log'ni bir daqiqada gigabaytga to'ldirardi.
        logger.error("Ichki xizmat javob bermayapti (%s): %s", type(exc).__name__, exc)
        exc = BackendUnavailable()

    response = drf_exception_handler(exc, context)

    if response is None:
        # Kutilmagan xato — to'liq stack trace log'ga, clientga umumiy xabar.
        logger.exception("Kutilmagan xato: %s", exc)
        return Response(
            {
                "success": False,
                "data": None,
                "error": {
                    "code": "internal_error",
                    "message": "Ichki server xatosi",
                    "details": None,
                },
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    detail = response.data
    code = getattr(exc, "default_code", "error")
    message = exc.default_detail if hasattr(exc, "default_detail") else "Xatolik"

    if isinstance(detail, dict) and "detail" in detail:
        message = str(detail["detail"])
        details = getattr(exc, "extra", None)
        code = getattr(detail["detail"], "code", code)
    else:
        details = _flatten(detail)
        message = "Kiritilgan ma'lumotlar noto'g'ri"

    response.data = {
        "success": False,
        "data": None,
        "error": {"code": code, "message": str(message), "details": details},
    }
    return response
