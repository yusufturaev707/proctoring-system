"""
Desktop client uchun autentifikatsiya.

Uch qatlam, uchtasi ham boshqa savolga javob beradi:

  1. `JWTAuthentication` (simplejwt)  — KIM ishlatyapti. Desktop ilovaga
     xodim login/parol bilan kiradi, xuddi admin panelga kirgandek.

  2. `DeviceResolution`  — QAYSI kompyuter. Imzo YO'Q: `X-Device-ID`
     shunchaki identifikator, kredensial emas. Sessiya qaysi mashinada
     va qaysi binoda o'tayotganini shu belgilaydi.

  3. `SessionTokenAuthentication` — QAYSI imtihon sessiyasi.
     Opaque token, Redis'da yashaydi, darhol bekor qilinadi.

Nima uchun qurilma HMAC imzosi olib tashlandi: u "qaysi kompyuter" ni
isbotlardi, lekin "kim" ni emas. Talabgorni chetlashtirish yoki uning
shaxsini tasdiqlash — ism-sharifi ma'lum xodimga bog'lanishi kerak
bo'lgan qarorlar. Xodim login'i buni beradi va ustiga audit izini ham
qo'shadi; imzo esa faqat qo'shimcha murakkablik edi.

Nima uchun sessiya tokeni JWT emas: proktor chetlashtirganda kirish
huquqi O'SHA SONIYADA o'chishi kerak. JWT'ni bekor qilib bo'lmaydi;
blacklist qo'shsangiz — u endi JWT emas, shunchaki sekinroq sessiya.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication

from apps.common.exceptions import (
    DeviceComputerInactive,
    DeviceNotApproved,
    DeviceNotRegistered,
    DeviceRevoked,
    SessionForbidden,
    SessionNotFound,
)
from apps.common.utils.crypto import hash_token
from apps.devices.models import DeviceToken
from apps.proctoring.models import ExamSession
from apps.proctoring.services import state as session_state

logger = logging.getLogger(__name__)


class _BearerHeaderMixin:
    """
    401 va 403 ni ajratib turish uchun.

    DRF javob kodini `authenticators[0].authenticate_header()` bo'yicha
    tanlaydi: `None` qaytsa — 403, satr qaytsa — 401. Ro'yxatda birinchi
    bo'lib turadigan yordamchi klasslar bu metodni bermasa, tokensiz
    so'rov 403 oladi va client "qayta login qilish kerakmi yoki ruxsat
    yetishmayaptimi" degan savolga javob topa olmaydi.
    """

    def authenticate_header(self, request):
        return 'Bearer realm="api"'


class DeviceResolution(_BearerHeaderMixin, BaseAuthentication):
    """
    `X-Device-ID` -> `request.device`.

    DRF `authentication_classes` ro'yxatida turadi, lekin foydalanuvchini
    ANIQLAMAYDI — `None` qaytaradi va DRF zanjirni davom ettirib
    `JWTAuthentication` ga o'tadi. Shuning uchun JWT ro'yxatda oxirgi
    bo'lishi shart.
    """

    def authenticate(self, request):
        device_id = request.META.get("HTTP_X_DEVICE_ID")

        if not device_id:
            if settings.PROCTORING["REQUIRE_DEVICE_ID"]:
                raise DeviceNotRegistered("X-Device-ID header'i yo'q")
            request.device = None
            return None

        # `computer__zone__region` ham JOIN'ga kiradi: mashina
        # tekshiruvi (`verify_machine`) xabarida viloyat va bino nomi
        # turadi va usiz har handshake bitta qo'shimcha so'rov
        # qilardi. Zanjir kalta va uchala jadval ham kichik.
        device = (
            DeviceToken.objects.select_related(
                "computer", "computer__zone", "computer__zone__region"
            )
            .filter(device_id=device_id)
            .first()
        )
        if device is None:
            # Noma'lum `device_id`. Client uchun bu QAYTA RO'YXATDAN O'TISH
            # signali: token serverda o'chirilgan bo'lishi mumkin (baza
            # tozalangan, qurilma qayta yaratilgan), client esa eski
            # identifikatorni diskda saqlab turadi va o'zi hech qachon
            # chiqa olmaydigan holatga tushadi.
            raise DeviceNotRegistered()

        if device.status == DeviceToken.Status.PENDING:
            raise DeviceNotApproved()
        if device.status == DeviceToken.Status.REVOKED:
            raise DeviceRevoked()
        if not device.is_usable:
            raise DeviceNotRegistered()

        # Kompyuterning O'ZI hisobdan chiqarilgan bo'lishi mumkin.
        # `Computer` yumshoq o'chiriladi (`deleted_at`), shuning uchun
        # FK'dagi `CASCADE` amalda hech qachon ishlamaydi va token
        # `ACTIVE` bo'lib qolaveradi — bu tekshiruvsiz binodan olib
        # qo'yilgan mashinadagi client so'rov yuborishda davom etardi.
        computer = device.computer
        if computer.deleted_at is not None or not computer.is_active:
            logger.warning(
                "Faol bo'lmagan kompyuterdan so'rov: device=%s pc=%s",
                device.device_id, computer.pk,
            )
            raise DeviceComputerInactive()

        request.device = device
        return None


class SessionTokenAuthentication(_BearerHeaderMixin, BaseAuthentication):
    """
    Header: `X-Proctoring-Session: <opaque>`

    Avval Redis (issiq yo'l), topilmasa DB (Redis tushgan holat uchun).
    """

    def authenticate(self, request):
        raw_token = request.META.get("HTTP_X_PROCTORING_SESSION")
        if not raw_token:
            request.exam_session = None
            return None

        digest = hash_token(raw_token)
        payload = session_state.resolve_session_token(digest)

        if payload is None:
            session = self._from_database(digest)
        else:
            session = (
                ExamSession.objects.select_related("exam", "computer", "zone", "device")
                .filter(pk=payload["session_id"])
                .first()
            )

        if session is None:
            raise SessionNotFound()
        if session.status in ExamSession.TERMINAL_STATUSES:
            raise SessionNotFound("Sessiya yakunlangan")

        # Token boshqa qurilmadan kelgan bo'lsa — rad etiladi.
        device = getattr(request, "device", None)
        if device is not None and session.device_id and session.device_id != device.pk:
            logger.warning(
                "Sessiya tokeni boshqa qurilmadan: session=%s device=%s",
                session.pk, device.pk,
            )
            raise SessionForbidden()

        request.exam_session = session
        return None

    @staticmethod
    def _from_database(digest: str) -> ExamSession | None:
        """Redis tushgan bo'lsa — DB'dan tiklaymiz."""
        session = (
            ExamSession.objects.select_related("exam", "computer", "zone", "device")
            .filter(token_hash=digest, token_expires_at__gt=timezone.now())
            .first()
        )
        if session is not None:
            session_state.store_session_token(
                token_hash=digest,
                payload={
                    "session_id": session.pk,
                    "public_id": str(session.public_id),
                    "exam_id": session.exam_id,
                    "device_id": session.device_id,
                    "zone_id": session.zone_id,
                    "status": session.status,
                },
            )
        return session


class LenientSessionTokenAuthentication(SessionTokenAuthentication):
    """
    Yaroqsiz yoki yakunlangan tokenni RAD ETMAYDI - sessiyasiz o'tkazadi.

    FAQAT `client/recordings/` uchun. Proktor chetlashtirganda token
    client bilmagan holda bekor bo'ladi, client esa o'sha paytda
    yakunlangan ekran yozuvining manzilini yuboradi - hali eski
    token bilan. Qat'iy tekshiruv so'rovni view'ga yetkazmasdan
    `session_not_found` bilan qaytarardi va sessiyani `public_id`
    bo'yicha topadigan yo'l (`recordings.session_without_token`)
    hech qachon ishlamasdi.

    `SessionForbidden` (token BOSHQA qurilmaniki) avvalgidek rad
    etiladi: bu yaroqsiz token emas, begona token.
    """

    def authenticate(self, request):
        try:
            return super().authenticate(request)
        except SessionNotFound:
            request.exam_session = None
            return None
