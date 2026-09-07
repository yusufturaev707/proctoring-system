"""
PyQt6 desktop client API.

Barcha endpointlar xodim JWT'si ostida (`client.operate` ruxsati);
imtihon boshlangandan keyingilar qo'shimcha `X-Proctoring-Session` talab qiladi.
Qurilma imzosi YO'Q — `X-Device-ID` kredensial emas, identifikator.

Yuklama nuqtai nazaridan muhim qarorlar:
  * event va screenshot metadata Redis Stream'ga tushadi, DB'ga emas;
  * heartbeat DB'ga tegmaydi (faqat Redis).

Skrinshot uchun IKKI yo'l bor va o'rnatish profiliga qarab bittasi
tanlanadi:

  * `screenshots/presign/` + `commit/` — binary MinIO/S3 ga to'g'ridan
    to'g'ri ketadi, backend'dan O'TMAYDI. Yuqori yuklama uchun yagona
    variant (10 000 client ≈ 120 MB/s).
  * `screenshots/upload/` — binary shu worker orqali diskka yoziladi.
    Obyekt storage'i yo'q, bitta serverli o'rnatishlar uchun.
"""

import logging

from django.conf import settings
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.common.exceptions import IpNotAllowed, PublicIpUnknown, SessionNotFound
from apps.common.permissions import HasRolePermission
from apps.common.storage import build_object_key, presign_put
from apps.common.throttling import (
    AccessAttemptThrottle,
    ClientIngestThrottle,
    ExitVerifyThrottle,
    FaceVerifyThrottle,
    PinflLookupOperatorThrottle,
    PinflLookupThrottle,
    PreflightThrottle,
    SessionStartThrottle,
    client_ip,
)
from apps.controls import services as controls_services
from apps.devices import services as device_services
from apps.proctoring.api.v1.client_serializers import (
    AccessAttemptSerializer,
    CandidateLookupSerializer,
    EventBatchSerializer,
    ExitVerifySerializer,
    FaceVerifySerializer,
    HandshakeSerializer,
    HeartbeatSerializer,
    IdentityConfirmSerializer,
    PeriodicFaceSerializer,
    PreflightSerializer,
    PresignRequestSerializer,
    ScreenshotCommitBatchSerializer,
    ScreenshotUploadSerializer,
    SessionFinishSerializer,
    TechnicalProblemReportSerializer,
)
from apps.proctoring.authentication import DeviceResolution, SessionTokenAuthentication
from apps.proctoring.models import ExamSession, ProctoringEvent, ScreenshotMeta, TechnicalProblem
from apps.proctoring.services import ingest, screenshots as screenshot_service
from apps.proctoring.services import session as session_service
from apps.proctoring.services import state as session_state
from apps.proctoring.services.audit import record_audit

logger = logging.getLogger(__name__)

#: Kirish urinishlari uchun ALOHIDA jurnal (`client_access.log`).
#:
#: Alohida, chunki uni boshqa odam va boshqa savol bilan o'qiydi:
#: "falon kompyuter nega kira olmayapti?". Umumiy log'da bu yozuvlar
#: har bir so'rov qatori orasida ko'rinmay ketardi.
access_logger = logging.getLogger("client_access")


class ClientBaseView(APIView):
    """
    Client endpointlari uchun umumiy asos.

    Desktop ilovaga xodim (operator) login/parol bilan kiradi, shuning
    uchun bu yerda ham admin panel bilan BIR XIL JWT ishlatiladi.
    Qurilma imzosi yo'q — `X-Device-ID` faqat "qaysi kompyuter" degan
    savolga javob beradi.

    Zanjir tartibi muhim: `DeviceResolution` va `SessionTokenAuthentication`
    `None` qaytaradi (ular faqat `request.device` / `request.exam_session`
    ni to'ldiradi), shuning uchun DRF ularni o'tib `JWTAuthentication` ga
    yetadi. JWT oxirida turishi SHART.
    """

    authentication_classes = [DeviceResolution, JWTAuthentication]
    permission_classes = [IsAuthenticated, HasRolePermission]
    required_permission = "client.operate"

    @property
    def device(self):
        return getattr(self.request, "device", None)

    def check_source_ip(self, zone_id=None) -> str:
        """
        Haqiqiy IP tekshiruvi — FAQAT server ko'rgan manzil bo'yicha.

        Preflight'dan farqi shu va u ataylab: preflight client aytgan
        qiymatga qaraydi (uni o'zgartirish mumkin), bu esa TCP ulanishi
        kelgan manzilga.

        Xato XABARI muhim. Ilgari u faqat "Ruxsat etilmagan IP: X"
        derdi va eng chalkash holatni — preflight o'tib, keyingi so'rov
        rad etilishini — umuman tushuntirmasdi. Sabab esa deyarli har
        doim bitta: server clientni NAT orqali ko'rmayapti, ya'ni u
        binoning tashqi manzilini emas, LAN manzilini ko'ryapti.
        """
        from apps.common.utils.network import is_private_ip

        ip_address = client_ip(self.request)
        if controls_services.is_ip_allowed(ip_address, zone_id):
            return ip_address

        if is_private_ip(ip_address):
            # Bu konfiguratsiya xatosi, hujum emas: xususiy manzilni
            # ommaviy IP ro'yxati bo'yicha baholab bo'lmaydi.
            logger.warning(
                "Manba manzili XUSUSIY (%s, zone=%s) — `AllowedPublicIp` "
                "ro'yxati unga javob bera olmaydi. Server imtihon "
                "tarmog'ining ichida yoki client bilan bir mashinada "
                "bo'lsa, `ALLOW_PRIVATE_SOURCE_IP=true` qo'ying; nginx "
                "ortida bo'lsa `TRUSTED_PROXY_COUNT` ni to'g'ri sozlang.",
                ip_address, zone_id,
            )
        else:
            logger.warning(
                "Ruxsat etilmagan IP: %s (zone=%s). Manzil `AllowedPublicIp` "
                "ro'yxatida yo'q yoki boshqa binoga biriktirilgan.",
                ip_address, zone_id,
            )
        raise IpNotAllowed()


class SessionRequiredView(ClientBaseView):
    """Faol imtihon sessiyasi talab qilinadigan endpointlar."""

    authentication_classes = [
        DeviceResolution,
        SessionTokenAuthentication,
        JWTAuthentication,
    ]

    @property
    def session(self) -> ExamSession:
        exam_session = getattr(self.request, "exam_session", None)
        if exam_session is None:
            raise SessionNotFound("X-Proctoring-Session header'i yo'q yoki yaroqsiz")
        return exam_session


# --------------------------------------------------------------------------
# 0. Preflight — client login formasini ko'rsatishdan OLDIN
# --------------------------------------------------------------------------
class PreflightView(APIView):
    """
    "Bu kompyuter ruxsat etilgan binodanmi?" — oqimning eng birinchi savoli.

    OCHIQ endpoint: u login'dan OLDIN chaqiriladi, ya'ni hali na JWT,
    na `device_id` bor. Bu bo'shliq emas — javobda hech qanday sir yo'q:
    client so'rov yuborgan manzilni allaqachon biladi, biz esa faqat
    "shu manzil ro'yxatdami" degan javobni qaytaramiz. Ro'yxatning
    o'zini sanab chiqishga `PreflightThrottle` yo'l qo'ymaydi.

    Nega alohida endpoint kerak (handshake yetmaydi):
      * handshake xodim JWT'sini talab qiladi, ya'ni operator avval
        login/parol kiritishi kerak bo'lardi — noto'g'ri tarmoqda esa
        bu urinishning ma'nosi yo'q;
      * to'siq sababi (`ip_not_allowed`) oqimning o'rtasida emas,
        boshida ko'rinishi kerak: operator nima qilishini darhol bilsin.

    Qaror FAQAT client aytgan public IP bo'yicha chiqadi — sababi
    `controls.services.network_preflight` da. Bu qulaylik to'sig'i;
    haqiqiy himoya `ClientBaseView.check_source_ip` da qoladi.
    """

    permission_classes: list = []
    authentication_classes: list = []
    throttle_classes = [PreflightThrottle]

    @extend_schema(request=PreflightSerializer, responses={200: None})
    def post(self, request):
        serializer = PreflightSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        observed_ip = client_ip(request)
        public_ip = serializer.validated_data.get("public_ip", "")
        result = controls_services.network_preflight(
            public_ip=public_ip, observed_ip=observed_ip
        )

        if result["allowed"]:
            # Qulflash siyosati SHU YERDA beriladi - login'dan oldin.
            # Handshake'dagi `config.hotkeys` bilan bir xil manba;
            # client uni kirish tugagach o'sha qiymat bilan qayta
            # qo'llaydi (bino sozlamasi boshqacha bo'lishi mumkin).
            result["hotkeys"] = controls_services.client_hotkeys()
            return Response(result)

        if result["allowlist_empty"]:
            # Sabab operatorda emas, sozlamada: ruxsat etilgan IP'lar
            # ro'yxatida bitta ham faol yozuv yo'q.
            logger.error(
                "Preflight rad etildi: ruxsat etilgan IP'lar ro'yxati BO'SH "
                "(public_ip=%s). Administrator kamida bitta manzil qo'shishi kerak.",
                public_ip or "-",
            )
        elif not public_ip:
            raise PublicIpUnknown()

        # Konvert ATAYLAB qo'lda: `IpNotAllowed` istisnosi `details` ni
        # yo'qotadi (`api_exception_handler` `detail` lug'atida uni
        # tashlab yuboradi), operatorga esa AYNAN qaysi manzil rad
        # etilgani kerak — u shu raqamni administratorga aytadi.
        return Response(
            {
                "success": False,
                "data": None,
                "error": {
                    "code": IpNotAllowed.default_code,
                    "message": (
                        "Ruxsat etilgan IP'lar ro'yxati bo'sh — administrator "
                        "hali birorta manzilni qo'shmagan."
                        if result["allowlist_empty"]
                        else "Tashqi IP manzilga ruxsat yo'q. Bu kompyuter "
                        "ro'yxatga olinmagan tarmoqdan ulanmoqda."
                    ),
                    "details": {
                        "public_ip": public_ip,
                        "observed_ip": observed_ip,
                        "allowlist_empty": result["allowlist_empty"],
                    },
                },
            },
            status=status.HTTP_403_FORBIDDEN,
        )


class AccessAttemptView(APIView):
    """
    Dasturga kirish urinishini JURNALGA yozadi.

    Alohida endpoint, alohida jurnal (`client_access.log`) — ataylab:

      * `AuditLog` XODIM harakatlari uchun (kim nimani o'zgartirdi) va
        u huquqiy dalil; ro'yxatdan o'tmagan mashinaning muvaffaqiyatsiz
        urinishi u yerda begona yozuv bo'lardi;
      * bu jurnalning O'QUVCHISI boshqa — tizim administratori "falon
        kompyuter nega kira olmayapti?" degan savolga javob qidiradi va
        unga bitta faylda MAC, LAN IP, public IP va natija ketma-ket
        turgani kerak;
      * urinishlar soni ko'p va ular DB'ga yozilsa, imtihon kunining
        boshida (bir vaqtda minglab client ishga tushadi) jadval
        bekorga o'sardi.

    Endpoint OCHIQ va hech narsani hal qilmaydi — u faqat yozadi.
    Shuning uchun bu yerda hech qanday sir yo'q, lekin
    `AccessAttemptThrottle` uni jurnalni to'ldirish yo'liga
    aylantirishga yo'l qo'ymaydi.
    """

    permission_classes: list = []
    authentication_classes: list = []
    throttle_classes = [AccessAttemptThrottle]

    @extend_schema(request=AccessAttemptSerializer, responses={202: None})
    def post(self, request):
        serializer = AccessAttemptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        observed_ip = client_ip(request)
        public_ip = data.get("public_ip", "")
        # Server o'z xulosasini QAYTADAN hisoblaydi: client aytgan
        # natijaga ishonib jurnal yozilsa, u faqat client to'g'ri
        # ishlaganini tasdiqlaydi va buzilgan/o'zgartirilgan client
        # haqida hech narsa aytmaydi.
        verdict = controls_services.network_preflight(
            public_ip=public_ip, observed_ip=observed_ip
        )
        zone = verdict["zone"] or {}
        region = verdict["region"] or {}

        access_logger.info(
            "KIRISH URINISHI | mac=%s lan_ip=%s public_ip=%s manba_ip=%s host=%s v%s "
            "| ruxsat=%s bino=%s | login_sahifasi=%s | kod=%s",
            data.get("mac_address") or "-",
            data.get("ip_address") or "-",
            public_ip or "-",
            observed_ip,
            data.get("hostname") or "-",
            data.get("app_version") or "-",
            "HA" if verdict["allowed"] else "YO'Q",
            "{}{}".format(
                zone.get("name") or "aniqlanmadi",
                " ({})".format(region["name"]) if region.get("name") else "",
            ),
            "OCHILDI" if data.get("entered_login") else "OCHILMADI",
            data.get("code") or "-",
        )

        # Client aytgani bilan server xulosasi zid bo'lsa — bu alohida
        # signal: yo client eskirgan, yo o'zgartirilgan.
        if bool(data.get("entered_login")) != bool(verdict["allowed"]):
            access_logger.warning(
                "ZIDLIK: client login_sahifasi=%s, server ruxsat=%s "
                "(mac=%s public_ip=%s)",
                "OCHILDI" if data.get("entered_login") else "OCHILMADI",
                "HA" if verdict["allowed"] else "YO'Q",
                data.get("mac_address") or "-",
                public_ip or "-",
            )

        # 202: yozib olindi, lekin client uchun hech narsani o'zgartirmaydi.
        # Client bu javobni kutmaydi ham — jurnalga yozish oqimni
        # to'xtatmasligi kerak.
        return Response(status=status.HTTP_202_ACCEPTED)


# --------------------------------------------------------------------------
# 1. Handshake — client konfiguratsiyani oladi
# --------------------------------------------------------------------------
class HandshakeView(ClientBaseView):
    @extend_schema(request=HandshakeSerializer, responses={200: None})
    def post(self, request):
        device = self.device
        serializer = HandshakeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        computer = device.computer if device else None
        zone = computer.zone if computer else None
        ip_address = self.check_source_ip(zone.pk if zone else None)

        if device is not None:
            anomalies = device_services.record_handshake(
                device,
                ip_address=ip_address,
                app_version=data.get("app_version", ""),
                app_hash=data.get("app_hash", ""),
                hardware_fingerprint=data.get("hardware_fingerprint", ""),
                reported_public_ip=data.get("public_ip", ""),
            )
            # Ilgari bu faqat log'ga tushardi, ya'ni panelda hech kim
            # ko'rmasdi. Hodisa (`ProctoringEvent`) yozib bo'lmaydi —
            # handshake paytida sessiya hali yo'q; audit izi esa aynan
            # shunday "qurilma darajasidagi" holatlar uchun.
            for anomaly in anomalies:
                record_audit(
                    actor=request.user,
                    action="client_anomaly",
                    object_type="DeviceToken",
                    object_id=device.pk,
                    meta={"device_id": device.device_id, **anomaly},
                    request=request,
                )

        if computer is not None:
            device_services.mark_online(computer)

        from apps.exams import selectors as exam_selectors
        from apps.exams.models import Exam

        # Ro'yxat `candidate/lookup/` bilan BIR XIL selektordan olinadi —
        # aks holda client'ga ko'rsatilgan imtihon keyingi qadamda rad
        # etilishi mumkin.
        now = timezone.now()
        schedules = list(
            exam_selectors.schedules_for_date(
                exam_date=timezone.localdate(now), zone_id=zone.pk if zone else None
            ).select_related("exam__exam_type")
        )

        # Fallback ro'yxati uchun: qaysi imtihonlarda umuman faol jadval
        # bor. Bitta so'rov — har bir imtihon uchun alohida tekshirish
        # 50 ta so'rovga aylanardi.
        fallback_exams = []
        scheduled_exam_ids = set()
        if not schedules:
            from apps.exams.models import ExamSchedule

            fallback_exams = list(
                Exam.objects.filter(is_active=True, deleted_at__isnull=True)
                .select_related("exam_type")[:50]
            )
            scheduled_exam_ids = set(
                ExamSchedule.objects.filter(
                    exam_id__in=[item.pk for item in fallback_exams],
                    is_active=True,
                    deleted_at__isnull=True,
                ).values_list("exam_id", flat=True)
            )

        available_exams = (
            [
                {
                    "id": item.exam.pk,
                    "name": item.exam.name,
                    # Client "test turi -> test" ikki bosqichli tanlov
                    # qiladi, shuning uchun tur ham ro'yxat bilan keladi.
                    "exam_type_id": item.exam.exam_type_id,
                    "exam_type_name": (
                        item.exam.exam_type.name if item.exam.exam_type_id else ""
                    ),
                    "schedule_id": item.pk,
                    "opens_at": item.opens_at,
                    "starts_at": item.starts_at,
                    "ends_at": item.ends_at,
                    # Client yopiq seansni tanlashga ruxsat bermasligi kerak.
                    "is_open": item.is_open(now),
                }
                for item in schedules
            ]
            if schedules
            else [
                # Bugunga jadval yo'q. Bu ikki xil holat bo'lishi mumkin:
                #
                #   * imtihon uchun jadval UMUMAN tuzilmagan — tekshiruv
                #     o'chirilgan hisoblanadi va kirish ochiq
                #     (`REQUIRE_EXAM_SCHEDULE` ni qarang);
                #   * jadval bor, lekin boshqa sanaga — bugun kirish yopiq.
                #
                # Farqlash SHART: aks holda handshake imtihonni "ochiq" deb
                # ko'rsatadi, `candidate/lookup/` esa uni `exam_not_open`
                # bilan rad etadi. Operator uchun bu tushunarsiz holat
                # (`exams/selectors.py` docstring'i aynan bundan ogohlantiradi).
                {
                    "id": exam.pk,
                    "name": exam.name,
                    "exam_type_id": exam.exam_type_id,
                    "exam_type_name": exam.exam_type.name if exam.exam_type_id else "",
                    "schedule_id": None,
                    "is_open": exam.pk not in scheduled_exam_ids,
                }
                for exam in fallback_exams
            ]
        )

        return Response(
            {
                "server_time": now,
                "device": {
                    "device_id": device.device_id if device else None,
                    "status": device.status if device else "unregistered",
                },
                "computer": (
                    {
                        "inventory_code": computer.inventory_code,
                        "zone_id": zone.pk if zone else None,
                        "zone_name": zone.name if zone else "",
                    }
                    if computer
                    else None
                ),
                "config": controls_services.get_client_config(),
                "exams": available_exams,
                # Shu ish stantsiyasini kuzatuvchi IP kameralar.
                #
                # RTSP kredensiallari ATAYLAB berilmaydi (`build_rtsp_url`
                # docstring'iga qarang): client kompyuterida saqlangan parol
                # barcha kameralarga kirish demakdir. Bu ro'yxat operatorga
                # "shu joyni qaysi kameralar ko'radi" ni ko'rsatish va
                # kamera oflayn bo'lsa ogohlantirish uchun.
                "cameras": (
                    [
                        {
                            "id": camera.pk,
                            "name": camera.name,
                            "ip_address": camera.ip_address,
                            "status": camera.status,
                            "is_active": camera.is_active,
                        }
                        for camera in computer.cameras.all()
                        if camera.deleted_at is None
                    ]
                    if computer is not None
                    else []
                ),
            }
        )


# --------------------------------------------------------------------------
# 2. JSHSHIR bo'yicha talabgorni aniqlash
# --------------------------------------------------------------------------
class CandidateLookupView(ClientBaseView):
    """
    Eng nozik endpoint butun tizimda.

    JSHSHIR strukturasi ma'lum (tug'ilgan sana + jins + hudud kodi), demak
    qidiruv maydoni kichik. Chegarasiz bu endpoint fuqarolarning F.I.Sh. sini
    ochiq qidirish servisiga aylanadi. Shuning uchun uch qavat himoya:
      1. Qurilma imzosi (ro'yxatdan o'tgan client bo'lishi shart)
      2. IP allowlist (imtihon markazi tarmog'i)
      3. Ikki xil throttle (JSHSHIR bo'yicha + qurilma bo'yicha)
    """

    throttle_classes = [PinflLookupThrottle, PinflLookupOperatorThrottle]

    @extend_schema(request=CandidateLookupSerializer, responses={200: None})
    def post(self, request):
        device = self.device
        serializer = CandidateLookupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        computer = device.computer if device else None
        zone = computer.zone if computer else None
        ip_address = self.check_source_ip(zone.pk if zone else None)

        from apps.exams.models import Exam

        exam = Exam.objects.filter(
            pk=serializer.validated_data["exam_id"], is_active=True, deleted_at__isnull=True
        ).first()
        if exam is None:
            return Response(
                {"detail": "Imtihon topilmadi yoki faol emas"}, status=status.HTTP_404_NOT_FOUND
            )

        result = session_service.lookup_candidate(
            pinfl=serializer.validated_data["pinfl"],
            exam=exam,
            device=device,
            # Zona kerak: bino jadvali global jadvaldan ustun bo'ladi.
            zone=zone,
            ip_address=ip_address,
        )
        return Response(result)


# --------------------------------------------------------------------------
# 3. Kirishdagi FaceID -> sessiya
# --------------------------------------------------------------------------
class FaceVerifyView(ClientBaseView):
    throttle_classes = [SessionStartThrottle]

    @extend_schema(request=FaceVerifySerializer, responses={201: None})
    def post(self, request):
        device = self.device
        serializer = FaceVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        computer = device.computer if device else None
        zone = computer.zone if computer else None
        ip_address = self.check_source_ip(zone.pk if zone else None)

        # Konfiguratsiya ATAYLAB bu yerda olinmaydi: qaysi imtihon ekani
        # faqat `challenge` ichida, uni esa `verify_initial_face` ochadi.
        # Bu yerda `get_client_config()` chaqirilsa, imtihonga biriktirilgan
        # sozlama e'tiborsiz qolib, global chegara qo'llanilardi.
        session = session_service.verify_initial_face(
            challenge=data["challenge"],
            embedding=data.get("embedding"),
            score=data.get("score"),
            image_key=data.get("image_key", ""),
            faces_detected=data["faces_detected"],
            device=device,
            computer=computer,
            ip_address=ip_address,
        )

        raw_token = session_service.issue_session_token(session)
        if computer is not None:
            device_services.mark_online(computer, in_exam=True)

        return Response(
            {
                "proctoring_session_token": raw_token,
                "session": {
                    "public_id": str(session.public_id),
                    "status": session.status,
                    "attempt_no": session.attempt_no,
                    "exam": {"id": session.exam_id, "name": session.exam.name},
                },
                "expires_in": settings.PROCTORING["SESSION_TOKEN_TTL"],
            },
            status=status.HTTP_201_CREATED,
        )


# --------------------------------------------------------------------------
# 4. Tashqi platformaga kirish (WebView)
# --------------------------------------------------------------------------
class ExamAccessView(SessionRequiredView):
    @extend_schema(responses={200: None})
    def post(self, request):
        session = self.session
        ip_address = client_ip(request)
        access = session_service.issue_exam_access(session, ip_address=ip_address)

        # WebView'ni qulflash ko'rsatmalari — client shu ro'yxatni
        # QWebEngineUrlRequestInterceptor allowlist sifatida ishlatadi.
        access["webview_policy"] = {
            "allowed_domains": access.pop("allowed_domains", []),
            "block_devtools": True,
            "block_context_menu": True,
            "block_new_windows": True,
            "block_downloads": True,
            "block_print": True,
            "off_the_record": True,
        }
        return Response(access)


# --------------------------------------------------------------------------
# 4b. Operator shaxsni tasdiqlaydi
# --------------------------------------------------------------------------
class IdentityConfirmView(SessionRequiredView):
    """
    Talabgor shaxsini hujjat bo'yicha tasdiqlash — `exam/access/` dan OLDIN.

    Alohida ruxsat talab qiladi: oddiy operator imtihonni olib borishi
    mumkin (`client.operate`), lekin shaxsni tasdiqlash — alohida
    javobgarlik va uni istalgan xodimga berib bo'lmaydi.
    """

    required_permission = "client.identity"

    @extend_schema(request=IdentityConfirmSerializer, responses={200: None})
    def post(self, request):
        serializer = IdentityConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        session = self.session

        if data["decision"] == "reject":
            reason = data["reason"].strip()
            session_service.reject_identity(session, actor=request.user, reason=reason)
            record_audit(
                actor=request.user,
                action="identity_reject",
                object_type="ExamSession",
                object_id=session.pk,
                meta={"reason": reason, "pinfl": session.pinfl},
                request=request,
            )
            return Response(
                {
                    "decision": "reject",
                    "status": session.status,
                    "detail": "Shaxs tasdiqlanmadi — sessiya chetlashtirildi",
                }
            )

        session = session_service.confirm_identity(
            session,
            actor=request.user,
            document_type=data["document_type"],
            document_number=data["document_number"].strip(),
            note=data.get("note", ""),
        )
        record_audit(
            actor=request.user,
            action="identity_confirm",
            object_type="ExamSession",
            object_id=session.pk,
            meta={
                "pinfl": session.pinfl,
                "full_name": session.full_name,
                "document_type": data["document_type"],
                "document_number": data["document_number"].strip(),
            },
            request=request,
        )
        return Response(
            {
                "decision": "confirm",
                "identity": session.identity,
                "detail": "Shaxs tasdiqlandi, imtihonni boshlash mumkin",
            }
        )


# --------------------------------------------------------------------------
# 5. Davriy FaceID
# --------------------------------------------------------------------------
class PeriodicFaceView(SessionRequiredView):
    throttle_classes = [FaceVerifyThrottle]

    @extend_schema(request=PeriodicFaceSerializer, responses={200: None})
    def post(self, request):
        serializer = PeriodicFaceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        session = self.session
        # Imtihonning o'z sozlamasi — chegara va `max_fail` shundan olinadi.
        config = controls_services.get_client_config(session.exam)
        result = session_service.verify_periodic_face(
            session=session,
            embedding=data.get("embedding"),
            score=data.get("score"),
            faces_detected=data["faces_detected"],
            image_key=data.get("image_key", ""),
            config=config,
            occurred_at=data.get("occurred_at"),
        )

        if result["should_terminate"]:
            session_service.terminate_session(
                session,
                reason=f"FaceID {result['fail_count']} marta ketma-ket muvaffaqiyatsiz",
            )
            result["terminated"] = True

        return Response(result)


# --------------------------------------------------------------------------
# 6. Hodisalar (batch)
# --------------------------------------------------------------------------
class EventBatchView(SessionRequiredView):
    throttle_classes = [ClientIngestThrottle]

    @extend_schema(request=EventBatchSerializer, responses={202: None})
    def post(self, request):
        serializer = EventBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        accepted = ingest.push_events_batch(
            session=self.session, events=serializer.validated_data["events"]
        )
        # 202 Accepted — hodisalar navbatga olindi, hali DB'ga yozilmadi.
        # Client javobni kutmasligi kerak, shuning uchun bu to'g'ri kod.
        return Response({"accepted": accepted}, status=status.HTTP_202_ACCEPTED)


# --------------------------------------------------------------------------
# 7. Skrinshotlar
# --------------------------------------------------------------------------
class ScreenshotPresignView(SessionRequiredView):
    """
    Yuklash uchun presigned URL beradi.

    Client faylni TO'G'RIDAN-TO'G'RI MinIO/S3 ga yuboradi. 10 000 talaba
    uchun bu ~120 MB/s trafikni backend'dan butunlay olib tashlaydi.
    """

    throttle_classes = [ClientIngestThrottle]

    @extend_schema(request=PresignRequestSerializer, responses={200: None})
    def post(self, request):
        serializer = PresignRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        session = self.session

        if not settings.STORAGE["ENABLED"]:
            return Response(
                {"detail": "Object storage yoqilmagan", "storage_enabled": False},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        uploads = []
        for _ in range(data["count"]):
            object_key = build_object_key(str(session.public_id), data["kind"])
            presigned = presign_put(object_key, data["content_type"])
            if presigned:
                uploads.append(presigned)

        return Response({"uploads": uploads})


class ScreenshotCommitView(SessionRequiredView):
    """Yuklash tugagach metadata'ni tasdiqlaydi (batch)."""

    throttle_classes = [ClientIngestThrottle]

    @extend_schema(request=ScreenshotCommitBatchSerializer, responses={202: None})
    def post(self, request):
        serializer = ScreenshotCommitBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        session = self.session
        for item in serializer.validated_data["screenshots"]:
            ingest.push_screenshot_meta(
                session=session,
                object_key=item["object_key"],
                kind=item["kind"],
                sha256=item.get("sha256", ""),
                size_bytes=item["size_bytes"],
                width=item["width"],
                height=item["height"],
                captured_at=item["captured_at"],
            )
        return Response(
            {"accepted": len(serializer.validated_data["screenshots"])},
            status=status.HTTP_202_ACCEPTED,
        )


class ScreenshotUploadView(SessionRequiredView):
    """
    Skrinshotni TO'G'RIDAN-TO'G'RI backend'ga yuklaydi (fayl tizimi yo'li).

    Bu `presign/` + `commit/` juftligining muqobili, ularning o'rniga
    EMAS. Farqi arxitektura darajasida:

        presign  : binary MinIO'ga ketadi, backend faqat metadata ko'radi
        upload   : binary shu worker'dan o'tadi va diskka yoziladi

    Ya'ni bu endpoint yuklamani backend'ga qaytaradi. U obyekt storage'i
    yo'q o'rnatishlar uchun: bitta bino, ~500 client. Undan kattarog'ida
    presigned yo'lini yoqish kerak, aks holda gunicorn worker'lari
    fayl uzatish bilan band bo'lib qoladi.

    Fayl `multipart/form-data` da keladi. Django uni
    `FILE_UPLOAD_MAX_MEMORY_SIZE` gacha xotirada, undan kattasini
    vaqtinchalik faylda ushlaydi — ya'ni 5 MB chegara bilan RAM xavfsiz.
    """

    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [ClientIngestThrottle]

    @extend_schema(request=ScreenshotUploadSerializer, responses={201: None})
    def post(self, request):
        serializer = ScreenshotUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        screenshot = screenshot_service.screenshot_store(
            session=self.session,
            upload=serializer.validated_data["file"],
            captured_at=serializer.validated_data["captured_at"],
        )

        # `file_path` javobda YO'Q: u serverning ichki katalog
        # strukturasi va client uchun hech qanday ma'no bermaydi.
        return Response(
            {
                "id": screenshot.pk,
                "content_hash": screenshot.content_hash,
                "file_size": screenshot.file_size,
                "mime_type": screenshot.mime_type,
                "captured_at": screenshot.captured_at,
            },
            status=status.HTTP_201_CREATED,
        )


# --------------------------------------------------------------------------
# 8. Heartbeat
# --------------------------------------------------------------------------
class HeartbeatView(SessionRequiredView):
    """
    Faollik signali — DB'ga TEGMAYDI.

    10 000 talaba × 30s = 333 rps. Agar har biri `UPDATE exam_session`
    bo'lsa, bu 333 WAL yozuvi/sekund faqat "men tirikman" degani uchun.
    Redis'da bu amalda bepul; DB'ga Celery 10 soniyada bir marta batch
    bilan ko'chiradi.
    """

    throttle_classes = [ClientIngestThrottle]

    @extend_schema(request=HeartbeatSerializer, responses={200: None})
    def post(self, request):
        serializer = HeartbeatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        session = self.session
        session_state.touch_heartbeat(
            session.pk, zone_id=session.zone_id, extra=serializer.validated_data
        )

        hot = session_state.get_state(session.pk)
        return Response(
            {
                "server_time": timezone.now(),
                "status": session.status,
                "risk_score": int(hot.get("risk", 0) or 0),
                # Client shu bayroqni ko'rib imtihonni yopadi.
                "should_stop": session.status in ExamSession.TERMINAL_STATUSES,
            }
        )


# --------------------------------------------------------------------------
# 9. Texnik muammo
# --------------------------------------------------------------------------
class TechnicalProblemReportView(SessionRequiredView):
    @extend_schema(request=TechnicalProblemReportSerializer, responses={201: None})
    def post(self, request):
        serializer = TechnicalProblemReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        session = self.session
        problem = TechnicalProblem.objects.create(
            session=session,
            kind=serializer.validated_data["kind"],
            description=serializer.validated_data.get("description", ""),
            started_at=timezone.now(),
        )
        session.status = ExamSession.Status.TECHNICAL_PROBLEM
        session.save(update_fields=["status", "updated_at"])

        ingest.push_event(
            session_id=session.pk,
            zone_id=session.zone_id,
            type=ProctoringEvent.Type.CLIENT_ANOMALY,
            severity=ProctoringEvent.Severity.HIGH,
            occurred_at=timezone.now(),
            payload={"technical_problem_id": problem.pk, "kind": problem.kind},
        )
        return Response({"id": problem.pk, "status": session.status}, status=status.HTTP_201_CREATED)


# --------------------------------------------------------------------------
# 10. Dasturdan chiqish
# --------------------------------------------------------------------------
class ExitVerifyView(APIView):
    """
    Dasturdan chiqishga ruxsat — IKKI xil parol qabul qilinadi.

    1. Xodimning O'Z paroli (JWT bo'lsa). Eng yaxshi holat: audit iziga
       ism yoziladi va parol shu odamning o'ziniki, ya'ni umumiy sir
       emas.
    2. Viloyatning chiqish paroli (`controls.ClientExitPassword`).
       Bu YAGONA yo'l dastur login sahifasida turganda: o'sha paytda
       hech qanday xodim tizimda yo'q, mashinani esa qonuniy yopish
       kerak bo'lishi mumkin (jihoz ko'chirilyapti, kun tugadi,
       preflight rad etgan ekranda qolib ketgan).

    Shuning uchun endpoint AUTENTIFIKATSIYANI TALAB QILMAYDI. Bu
    bo'shliq emas: u hech narsa ochmaydi va hech qanday ma'lumot
    bermaydi — faqat "parol to'g'rimi" degan javobni qaytaradi va
    o'sha javob bilan client o'z oynasini yopadi. Brute-force'ga
    qarshi `ExitVerifyThrottle`, har bir urinish esa log'da.

    Qurilma `DeviceResolution` orqali ANIQLANMAYDI: u noma'lum yoki
    tasdiqlanmagan qurilmada istisno tashlaydi, holbuki aynan shunday
    mashinani yopish kerak bo'ladi. Qurilma bu yerda ixtiyoriy va
    faqat viloyatni aniqlashga yordam beradi.
    """

    authentication_classes = [JWTAuthentication]
    permission_classes: list = []
    throttle_classes = [ExitVerifyThrottle]

    @staticmethod
    def _device(request):
        """`X-Device-ID` -> `DeviceToken` yoki `None`. Istisno tashlamaydi."""
        device_id = request.META.get("HTTP_X_DEVICE_ID")
        if not device_id:
            return None
        from apps.devices.models import DeviceToken

        return (
            DeviceToken.objects.select_related(
                "computer", "computer__zone", "computer__zone__region"
            )
            .filter(device_id=device_id)
            .first()
        )

    @staticmethod
    def _region_id(device, public_ip: str):
        """
        Viloyat: avval qurilma zanjiri, keyin tashqi IP.

        Qurilma ishonchliroq — u serverdagi yozuv bilan bog'langan.
        Tashqi IP esa client aytgan qiymat, lekin u faqat QAYSI
        parol solishtirilishini tanlaydi: noto'g'ri viloyat
        ko'rsatilsa, solishtirish shunchaki mos kelmaydi.
        """
        zone = getattr(getattr(device, "computer", None), "zone", None)
        if zone is not None and zone.region_id:
            return zone.region_id

        if public_ip:
            zone = device_services.resolve_zone_by_public_ip(public_ip)
            if zone is not None:
                return zone.region_id
        return None

    @extend_schema(request=ExitVerifySerializer, responses={200: None})
    def post(self, request):
        serializer = ExitVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        password = serializer.validated_data["password"]

        device = self._device(request)
        user = request.user if request.user.is_authenticated else None

        # 1. Xodimning o'z paroli.
        if user is not None and user.check_password(password):
            return self._allow(request, device, method="staff", user=user)

        # 2. Viloyatning chiqish paroli.
        region_id = self._region_id(device, serializer.validated_data.get("public_ip", ""))
        row = controls_services.verify_exit_password(password, region_id=region_id)
        if row is not None:
            return self._allow(
                request, device, method="region", user=user, region=row.region
            )

        # Parol umuman sozlanmaganmi? Bu "noto'g'ri parol" EMAS va
        # client'ga shunday deb aytilsa, operator yo'q parolni
        # qidirib qolardi. Bundan ham yomoni: kiosk rejimida chiqishning
        # boshqa yo'li yo'q va mashina quvvatdan uzilmaguncha ochiq
        # qolardi. Shuning uchun alohida kod - client uni tasdiqlash
        # dialogiga aylantiradi.
        if not controls_services.has_exit_password(region_id=region_id):
            logger.error(
                "Chiqish paroli SOZLANMAGAN (viloyat=%s). Administrator uni "
                "panelda yaratishi kerak - shungacha chiqish parolsiz ochiq.",
                region_id or "aniqlanmadi",
            )
            return Response(
                {
                    "success": False,
                    "data": None,
                    "error": {
                        "code": "exit_password_not_configured",
                        "message": "Bu viloyat uchun chiqish paroli sozlanmagan",
                        "details": {"region_id": region_id},
                    },
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        logger.warning(
            "Chiqish paroli noto'g'ri: user=%s device=%s viloyat=%s",
            getattr(user, "username", "-"),
            getattr(device, "device_id", "-"),
            region_id or "aniqlanmadi",
        )
        return Response(
            {
                "success": False,
                "data": None,
                "error": {
                    "code": "exit_password_invalid",
                    "message": "Parol noto'g'ri",
                    "details": None,
                },
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    @staticmethod
    def _allow(request, device, *, method: str, user=None, region=None):
        """Ruxsat berildi — audit iziga QAYSI kalit ishlatilgani yoziladi."""
        record_audit(
            actor=user,
            action="client_exit",
            object_type="DeviceToken",
            object_id=getattr(device, "pk", None),
            meta={
                "device_id": getattr(device, "device_id", ""),
                # Xodim paroli bilan chiqish va viloyat paroli bilan
                # chiqish HAR XIL hodisa: birinchisida kim chiqqani
                # ma'lum, ikkinchisida esa faqat qaysi viloyatning
                # kaliti ishlatilgani.
                "method": method,
                "region": getattr(region, "name", ""),
            },
            request=request,
        )
        logger.info(
            "Chiqishga ruxsat berildi (%s): user=%s device=%s",
            method,
            getattr(user, "username", "-"),
            getattr(device, "device_id", "-"),
        )
        return Response({"detail": "Chiqishga ruxsat", "method": method})


# --------------------------------------------------------------------------
# 11. Sessiyani yakunlash
# --------------------------------------------------------------------------
class SessionFinishView(SessionRequiredView):
    @extend_schema(request=SessionFinishSerializer, responses={200: None})
    def post(self, request):
        serializer = SessionFinishSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        session = session_service.finish_session(
            self.session, reason=serializer.validated_data.get("reason", "")
        )
        if session.computer_id:
            device_services.mark_online(session.computer)

        return Response(
            {
                "status": session.status,
                "finished_at": session.finished_at,
                "duration_seconds": session.duration_seconds,
            }
        )


class SessionStateView(SessionRequiredView):
    """Client qayta ulanganda holatni tiklash uchun."""

    def get(self, request):
        session = self.session
        hot = session_state.get_state(session.pk)
        return Response(
            {
                "public_id": str(session.public_id),
                "status": session.status,
                "started_at": session.started_at,
                "risk_score": int(hot.get("risk", session.risk_score) or 0),
                "face_fail_count": int(hot.get("face_fails", 0) or 0),
                "config": controls_services.get_client_config(session.exam),
                "should_stop": session.status in ExamSession.TERMINAL_STATUSES,
            }
        )
