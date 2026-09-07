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

    Kalit — IP. Bino ichida har bir kompyuterning o'z manzili bor
    (`unique_computer_zone_ip`), shuning uchun ommaviy o'rnatishda
    mashinalar bir-birining byudjetini yemaydi.
    """

    scope = "device_register"

    def get_ident_value(self, request, view):
        return client_ip(request)


class PreflightThrottle(BaseScopedThrottle):
    """
    Ishga tushishdagi tarmoq tekshiruvi — OCHIQ endpoint.

    Chegara `device_register` dan yumshoqroq: preflight hech narsa
    YARATMAYDI, u faqat o'qiydi. Lekin cheksiz bo'lishi ham mumkin emas
    — ro'yxatdagi IP'larni tashqaridan sanab chiqish yo'liga aylanardi.
    """

    scope = "preflight"

    def get_ident_value(self, request, view):
        return client_ip(request)


class AccessAttemptThrottle(BaseScopedThrottle):
    """
    Kirish urinishi haqidagi xabar — OCHIQ endpoint.

    Chegara preflight'nikidan yumshoqroq bo'lishi mumkin emas: aks holda
    u jurnalni ma'nosiz yozuvlar bilan to'ldirish (log flooding) yo'liga
    aylanardi va haqiqiy urinishlar ular orasida ko'rinmay qolardi.
    """

    scope = "access_attempt"

    def get_ident_value(self, request, view):
        return client_ip(request)


class StaffLoginThrottle(BaseScopedThrottle):
    """Xodim login'i — parolni brute-force qilishga qarshi."""

    scope = "staff_login"

    def get_ident_value(self, request, view):
        username = (request.data or {}).get("username", "")
        return f"{client_ip(request)}:{str(username)[:64]}"
