"""
Throttling siyosatlari.

Eng muhimi — `PinflLookupThrottle`. JSHSHIR strukturasi ma'lum (tug'ilgan
sana + jins + region), demak qidiruv maydoni kichik. Chegarasiz endpoint
fuqarolarning F.I.Sh. sini ochiq qidirish servisiga aylanadi. Bu texnik
emas, huquqiy xavf.
"""

from __future__ import annotations

import hashlib

from rest_framework.throttling import SimpleRateThrottle


def client_ip(request) -> str:
    """
    So'rovning MANBA manzili.

    ASOSIY QOIDA: proksi header'lariga FAQAT ishonchli proksi ortida
    ishoniladi. `TRUSTED_PROXY_COUNT=0` (standart) bo'lsa, `X-Real-IP`
    ham, `X-Forwarded-For` ham butunlay e'tiborsiz qoldiriladi va faqat
    `REMOTE_ADDR` ishlatiladi.

    Sabab: bu header'larni ISTALGAN client yozib yuborishi mumkin.
    Ilgari bu yerda XFF ning eng chapdagi qiymati olinardi, ya'ni
    uydan turib `X-Forwarded-For: <ruxsat etilgan IP>` yuborish bilan
    IP allowlist ham, throttling kalitlari ham chetlab o'tilardi.

    Proksi ortida (`TRUSTED_PROXY_COUNT=1`):
      * `X-Real-IP` — nginx uni `$remote_addr` dan qo'yadi va client
        yuborgan qiymatni har doim qayta yozadi;
      * zaxira sifatida XFF zanjirining O'NGDAN N-chi elementi: har bir
        ishonchli proksi zanjir oxiriga o'zi ko'rgan manzilni qo'shadi.
    """
    from django.conf import settings

    remote_addr = request.META.get("REMOTE_ADDR", "0.0.0.0")
    try:
        trusted = int(getattr(settings, "TRUSTED_PROXY_COUNT", 0) or 0)
    except (TypeError, ValueError):
        trusted = 0

    if trusted <= 0:
        return remote_addr

    real_ip = (request.META.get("HTTP_X_REAL_IP") or "").strip()
    if real_ip:
        return real_ip

    forwarded = request.META.get("HTTP_X_FORWARDED_FOR") or ""
    parts = [item.strip() for item in forwarded.split(",") if item.strip()]
    if len(parts) >= trusted:
        return parts[-trusted]
    return remote_addr


#: Ma'lum qurilma keshi. Faqat TOPILGAN qurilma keshlanadi: noma'lum
#: ID'larni keshlash tasodifiy ID yuborib keshni to'ldirish yo'li
#: bo'lardi, ular esa baribir qat'iy IP chegarasiga tushadi.
_KNOWN_DEVICE_CACHE_SECONDS = 300


def known_device_pk(request) -> int | None:
    """
    `X-Device-ID` bazadagi qurilmaniki bo'lsa — uning `pk` si, aks holda `None`.

    Ochiq endpointlarda (`preflight`, `access-attempt`, `devices/register`)
    `DeviceResolution` ishlamaydi, shuning uchun qurilma shu yerda
    aniqlanadi. Header'ning O'ZIGA ishonilmaydi: uni istalgan client
    yozadi va har so'rovda yangi ID yuborib chegarani chetlab o'tardi.
    Bazada bor qurilmalar esa soni cheklangan va har birini
    administrator ko'radi (`device_register` chegarasi ostida yaratiladi).
    """
    from django.core.cache import cache

    from apps.devices.models import DeviceToken

    device_id = (request.META.get("HTTP_X_DEVICE_ID") or "").strip()
    max_length = DeviceToken._meta.get_field("device_id").max_length
    if not device_id or len(device_id) > max_length:
        return None

    cache_key = "throttle_known_device:" + hashlib.sha256(device_id.encode()).hexdigest()[:32]
    pk = cache.get(cache_key)
    if pk:
        return pk

    pk = DeviceToken.objects.filter(device_id=device_id).values_list("pk", flat=True).first()
    if pk:
        cache.set(cache_key, pk, _KNOWN_DEVICE_CACHE_SECONDS)
    return pk


def device_or_ip_ident(request) -> str:
    """
    Ochiq endpointlar kaliti: ma'lum qurilma — o'z byudjeti, qolgani — IP.

    Server internetda turganda butun bino bitta NAT manzili bilan
    keladi. Faqat IP bo'yicha chegarada imtihon boshida 500 mashina
    bitta byudjetni bo'lishardi va ~94% i 429 olardi. Ro'yxatdagi
    qurilma shuning uchun o'z kalitini oladi (IP ham kalitda: ID
    boshqa tarmoqdan ishlatilsa, bino byudjetiga tegmaydi). Noma'lum
    yoki header'siz so'rov esa avvalgidek qat'iy IP chegarasida.
    """
    ip = client_ip(request)
    pk = known_device_pk(request)
    if pk:
        return f"dev:{pk}:{ip}"
    return f"ip:{ip}"


class BaseScopedThrottle(SimpleRateThrottle):
    """Berilgan `scope` va ident bo'yicha cheklaydi."""

    scope = "anon"

    def get_ident_value(self, request, view) -> str | None:  # pragma: no cover
        raise NotImplementedError

    def get_cache_key(self, request, view):
        ident = self.get_ident_value(request, view)
        if ident is None:
            return None
        return self.cache_format % {"scope": self.scope, "ident": ident}


class PinflLookupThrottle(BaseScopedThrottle):
    """
    Bitta JSHSHIR uchun soatiga N urinish.

    Kalit sifatida ochiq JSHSHIR emas, uning hash'i ishlatiladi — aks holda
    cache dump'ida barcha qidirilgan JSHSHIR'lar ochiq yotadi.
    """

    scope = "pinfl_lookup"

    def get_ident_value(self, request, view):
        pinfl = (request.data or {}).get("pinfl")
        if not pinfl:
            return None
        return hashlib.sha256(str(pinfl).encode()).hexdigest()[:32]


class PinflLookupOperatorThrottle(BaseScopedThrottle):
    """
    Bitta OPERATOR soatiga nechta har xil JSHSHIR qidira oladi.

    JSHSHIR bo'yicha chegara enumeration'ni to'xtatmaydi (hujumchi har safar
    yangi raqam sinaydi). Ilgari bu chegara qurilmaga bog'langan edi, endi
    esa xodimga: o'g'irlangan hisob bilan bir necha mashinadan qidirish
    shu bilan yopiladi, va chegaraga yetilganda kim ekani ham ma'lum.
    """

    scope = "pinfl_lookup_operator"

    def get_ident_value(self, request, view):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            return f"user:{user.pk}"
        return f"ip:{client_ip(request)}"


class ExitVerifyThrottle(BaseScopedThrottle):
    """
    Chiqish paroli — ALOHIDA scope.

    Ilgari u `SessionStartThrottle` bilan bitta byudjetni bo'lishardi:
    10 marta noto'g'ri parol kiritilsa, o'sha kompyuterda bir soat
    davomida hech kim imtihon boshlay olmasdi.
    """

    scope = "exit_verify"

    def get_ident_value(self, request, view):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            return f"user:{user.pk}"
        return f"ip:{client_ip(request)}"


class FaceAttemptThrottle(BaseScopedThrottle):
    """
    Kirishda MOS KELMAGAN urinishlar — QURILMA bo'yicha.

    IP bo'yicha bo'lishi mumkin emas: butun bino bitta NAT manzili
    ortida turadi va ommaviy kirish paytida 500 mashinaning
    urinishlari bitta byudjetni yer edi — natijada aybsiz
    operatorning urinishi jimgina yozilmay qolardi.

    Sessiya bu bosqichda hali YO'Q (u moslik tasdiqlangach ochiladi),
    shuning uchun `FaceVerifyThrottle` dagi kalit bu yerda ishlamaydi.
    Chegaraning o'zi o'sha `face_verify` byudjetidan: ikkalasi ham
    bitta oqimning ikki yakuni.
    """

    scope = "face_verify"

    def get_ident_value(self, request, view):
        device = getattr(request, "device", None)
        if device is not None:
            return f"dev:{device.pk}"
        return f"ip:{client_ip(request)}"


class FaceVerifyThrottle(BaseScopedThrottle):
    scope = "face_verify"

    def get_ident_value(self, request, view):
        session = getattr(request, "exam_session", None)
        if session is not None:
            return f"sess:{session.pk}"
        return f"ip:{client_ip(request)}"


class SessionStartThrottle(BaseScopedThrottle):
    scope = "session_start"

    def get_ident_value(self, request, view):
        device = getattr(request, "device", None)
        return f"dev:{device.pk}" if device else f"ip:{client_ip(request)}"


class ClientIngestThrottle(BaseScopedThrottle):
    """
    Event/screenshot oqimi uchun yuqori, lekin cheksiz bo'lmagan chegara.

    Normal client daqiqasiga ~30 so'rov yuboradi. 600/min chegarasi
    buzilgan yoki cheksiz siklga tushgan clientni ushlaydi.
    """

    scope = "client_ingest"

    def get_ident_value(self, request, view):
        session = getattr(request, "exam_session", None)
        if session is not None:
            return f"sess:{session.pk}"
        device = getattr(request, "device", None)
        return f"dev:{device.pk}" if device else f"ip:{client_ip(request)}"


class DeviceRegisterThrottle(BaseScopedThrottle):
    """
    Qurilmani ro'yxatga qo'yish — OCHIQ endpoint, demak chegara shart.

    Autentifikatsiya bo'shlig'i emas (yangi qurilma `PENDING` da tug'iladi
    va admin tasdig'isiz hech narsa qila olmaydi), lekin chegarasiz u
    ma'lum MAC/IP bo'yicha cheksiz `PENDING` qator yaratish yo'li bo'lib
    qolardi.

    Kalit — `device_or_ip_ident`: qayta ro'yxatdan o'tayotgan ma'lum
    qurilma o'z byudjetini oladi. YANGI qurilma esa ta'rifga ko'ra
    noma'lum va IP bo'yicha cheklanadi — aynan shu chegara `PENDING`
    qatorlarni cheksiz yaratishni to'xtatadi. Server internetda
    bo'lsa bu IP binoning NAT manzili, ya'ni birinchi ommaviy
    o'rnatishda butun bino shu byudjetni bo'lishadi
    (`THROTTLE_DEVICE_REGISTER`).
    """

    scope = "device_register"

    def get_ident_value(self, request, view):
        return device_or_ip_ident(request)


class PreflightThrottle(BaseScopedThrottle):
    """
    Ishga tushishdagi tarmoq tekshiruvi — OCHIQ endpoint.

    Chegara `device_register` dan yumshoqroq: preflight hech narsa
    YARATMAYDI, u faqat o'qiydi. Lekin cheksiz bo'lishi ham mumkin emas
    — ro'yxatdagi IP'larni tashqaridan sanab chiqish yo'liga aylanardi.
    Kalit — `device_or_ip_ident` (bino NAT'i ortidagi ommaviy ishga
    tushish uchun); tashqi skaner noma'lum qurilma sifatida IP
    chegarasida qoladi.
    """

    scope = "preflight"

    def get_ident_value(self, request, view):
        return device_or_ip_ident(request)


class AccessAttemptThrottle(BaseScopedThrottle):
    """
    Kirish urinishi haqidagi xabar — OCHIQ endpoint.

    Chegara preflight'nikidan yumshoqroq bo'lishi mumkin emas: aks holda
    u jurnalni ma'nosiz yozuvlar bilan to'ldirish (log flooding) yo'liga
    aylanardi va haqiqiy urinishlar ular orasida ko'rinmay qolardi.
    Kalit preflight'niki bilan bir xil (`device_or_ip_ident`).
    """

    scope = "access_attempt"

    def get_ident_value(self, request, view):
        return device_or_ip_ident(request)


class StaffLoginThrottle(BaseScopedThrottle):
    """Xodim login'i — parolni brute-force qilishga qarshi."""

    scope = "staff_login"

    def get_ident_value(self, request, view):
        username = (request.data or {}).get("username", "")
        return f"{client_ip(request)}:{str(username)[:64]}"
