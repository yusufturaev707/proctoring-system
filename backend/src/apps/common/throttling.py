"""
Throttling siyosatlari.

Eng muhimi — `PinflLookupThrottle`. JSHSHIR strukturasi ma'lum (tug'ilgan
sana + jins + region), demak qidiruv maydoni kichik. Chegarasiz endpoint
fuqarolarning F.I.Sh. sini ochiq qidirish servisiga aylanadi. Bu texnik
emas, huquqiy xavf.
"""

from __future__ import annotations

import hashlib

from rest_framework.exceptions import Throttled
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

    Ochiq endpointlarda (`auth/login`, `devices/register`)
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
    #: Client'ga aytiladigan nom (`error.details.scope`, `ScopeDetailsThrottleMixin`).
    #: Ichki `scope` emas: u sozlama kaliti va o'zgarishi mumkin, client esa
    #: shu qiymatga qarab operatorga NIMA to'silganini aytadi.
    public_scope = ""

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
    public_scope = "pinfl"

    def get_ident_value(self, request, view):
        pinfl = (request.data or {}).get("pinfl")
        if not pinfl:
            return None
        return hashlib.sha256(str(pinfl).encode()).hexdigest()[:32]


def device_user_ident(request) -> str:
    """
    Kalit: ro'yxatdagi QURILMA + xodim — har mashinaga o'z byudjeti.

    Nima uchun xodimning o'zi yetmaydi: operator hisobi REGIONGA bitta
    (bino ~500 mashina) va `user:{pk}` kaliti bilan butun bino bitta
    soatlik byudjetni bo'lishardi — kirish to'lqinida talabgorlarning
    yarmi 429 olardi. Chegarani oshirish esa himoyani butun region uchun
    bo'shatardi.

    Qurilma `request.device` dan (`DeviceResolution` uni bazadan topib,
    holatini tekshirgan) yoki, u yo'q yuzalarda (`exit/verify/` faqat JWT
    oladi), `known_device_pk` orqali — ikkalasida ham faqat BAZADAGI
    qurilma: soxta `X-Device-ID` yangi byudjet bermaydi, IP kalitiga
    tushadi. Xodim + qurilmasiz so'rov bino IP'si bo'yicha.
    """
    device = getattr(request, "device", None)
    device_pk = device.pk if device is not None else known_device_pk(request)
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        if device_pk:
            return f"dev:{device_pk}:user:{user.pk}"
        return f"user:{user.pk}:ip:{client_ip(request)}"
    if device_pk:
        return f"dev:{device_pk}:{client_ip(request)}"
    return f"ip:{client_ip(request)}"


class PinflLookupOperatorThrottle(BaseScopedThrottle):
    """
    Bitta OPERATOR HISOBI soatiga nechta JSHSHIR qidira oladi — KENG chegara.

    JSHSHIR bo'yicha chegara enumeration'ni to'xtatmaydi (hujumchi har safar
    yangi raqam sinaydi). Bu chegara xodimga bog'langan: o'g'irlangan hisob
    bilan ko'p mashinadan qidirish shu bilan yopiladi va chegaraga
    yetilganda kim ekani ham ma'lum.

    Hisob regionga bitta, ya'ni bu butun binoning byudjeti — u bino
    hajmiga moslab KENG qo'yiladi (`THROTTLE_PINFL_OPERATOR`). Bitta
    mashinaning qat'iy chegarasi alohida: `PinflLookupDeviceThrottle`.
    """

    scope = "pinfl_lookup_operator"
    public_scope = "operator"

    def get_ident_value(self, request, view):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            return f"user:{user.pk}"
        return f"ip:{client_ip(request)}"


class PinflLookupDeviceThrottle(BaseScopedThrottle):
    """
    Bitta MASHINA soatiga nechta JSHSHIR qidira oladi — QAT'IY chegara.

    Mashina smenada bir necha talabgorni qidiradi, ya'ni qonuniy ish bu
    chegaraga yetmaydi; bitta mashinadan JSHSHIR'larni sanab chiqish esa
    shu yerda to'xtaydi. Region bo'yicha keng chegara bilan BIRGA ishlaydi.
    """

    scope = "pinfl_lookup_device"
    public_scope = "device"

    def get_ident_value(self, request, view):
        return device_user_ident(request)


#: Bir nechta chegara birdan to'lsa client'ga ENG KENGI aytiladi: u ko'proq
#: narsani to'sadi va operatorning harakati shunga bog'liq (boshqa talabgorni
#: qidirish ham yordam bermaydi).
_SCOPE_BREADTH = ("operator", "device", "pinfl")


class ScopedThrottled(Throttled):
    """429, `error.details` da qaysi chegara to'lgani va haqiqiy kutish."""

    def __init__(self, wait=None, *, scope: str = ""):
        super().__init__(wait)
        # `api_exception_handler` `extra` ni `error.details` ga qo'yadi.
        self.extra = {"scope": scope, "wait": self.wait}


class ScopeDetailsThrottleMixin:
    """
    429 javobiga `details.scope` va `details.wait` qo'shadi.

    NIMA UCHUN. DRF faqat "kuting" deydi, qaysi chegara to'lganini emas.
    JSHSHIR qidiruvida bu operator uchun ikki boshqa vaziyat: bitta
    JSHSHIR to'silgan bo'lsa keyingi talabgorni bemalol qidirsa bo'ladi,
    mashina yoki hisob chegarasi to'lgan bo'lsa — yo'q. `wait` —
    serverning haqiqiy muddati: client `Retry-After` ni 300 s bilan
    cheklaydi (`client/services/net_policy.py`) va operatorga "5 daqiqa"
    deb, keyin yana rad etardi.

    Qolgani DRF'niki bilan bir xil: har chegara tekshiriladi (o'tgani
    so'rovni hisobga yozadi), `Retry-After` — eng uzun kutish.
    """

    def check_throttles(self, request):
        blocked: list[tuple[str, float | None]] = []
        for throttle in self.get_throttles():
            if not throttle.allow_request(request, self):
                blocked.append((getattr(throttle, "public_scope", ""), throttle.wait()))
        if not blocked:
            return
        durations = [wait for _, wait in blocked if wait is not None]
        scopes = {scope for scope, _ in blocked}
        scope = next((name for name in _SCOPE_BREADTH if name in scopes), "")
        raise ScopedThrottled(max(durations, default=None), scope=scope)


class ExitVerifyThrottle(BaseScopedThrottle):
    """
    Chiqish paroli — ALOHIDA scope, hisob bo'yicha KENG chegara.

    Ilgari u `SessionStartThrottle` bilan bitta byudjetni bo'lishardi:
    10 marta noto'g'ri parol kiritilsa, o'sha kompyuterda bir soat
    davomida hech kim imtihon boshlay olmasdi.

    Hisob regionga bitta, ya'ni bu binoning kun oxiridagi barcha
    chiqishlari byudjeti (`THROTTLE_EXIT_VERIFY`). Parolni bitta
    mashinada tanlashni `ExitVerifyDeviceThrottle` to'xtatadi.
    """

    scope = "exit_verify"

    def get_ident_value(self, request, view):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            return f"user:{user.pk}"
        return f"ip:{client_ip(request)}"


class ExitVerifyDeviceThrottle(BaseScopedThrottle):
    """Chiqish paroli — bitta MASHINA bo'yicha QAT'IY chegara."""

    scope = "exit_verify_device"

    def get_ident_value(self, request, view):
        return device_user_ident(request)


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


class StaffLoginThrottle(BaseScopedThrottle):
    """
    Xodim login'i — bino (IP) + login bo'yicha KENG chegara.

    Operator hisobi regionga bitta va regionda bitta bino bor, ya'ni bu
    kalit amalda "butun bino": unga kirish to'lqinidagi barcha mashinalar
    sig'ishi kerak (`THROTTLE_STAFF_LOGIN`). Uning vazifasi — binodan
    kelayotgan umumiy hujumni to'xtatish (ro'yxatdagi qurilmalar ID'si
    diskda yotadi va yig'ib olinishi mumkin). Bitta mashinadagi parol
    tanlash — `StaffLoginDeviceThrottle`.
    """

    scope = "staff_login"

    def get_ident_value(self, request, view):
        username = (request.data or {}).get("username", "")
        return f"{client_ip(request)}:{str(username)[:64]}"


class StaffLoginDeviceThrottle(BaseScopedThrottle):
    """
    Xodim login'i — bitta MASHINA (`X-Device-ID`) + login bo'yicha QAT'IY chegara.

    Login'da hali xodim yo'q, shuning uchun kalit `device_or_ip_ident`:
    ro'yxatdagi qurilma — o'z byudjeti, ro'yxatdan o'tmagan yoki soxta
    ID — bino IP'si bo'yicha umumiy byudjet. Client login so'rovida ham
    `X-Device-ID` yuboradi (`client/services/api_client.py:_headers`).
    """

    scope = "staff_login_device"

    def get_ident_value(self, request, view):
        username = (request.data or {}).get("username", "")
        return f"{device_or_ip_ident(request)}:{str(username)[:64]}"
