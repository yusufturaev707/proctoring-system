import logging

from django.conf import settings
from django.db.models import OuterRef, Prefetch, Subquery
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.mixins import AuditLogMixin, PermissionRequiredMixin, SoftDeleteRestoreMixin
from apps.common.permissions import HasRolePermission
from apps.common.throttling import DeviceRegisterThrottle, client_ip
from apps.common.utils.network import is_private_ip
from apps.devices import selectors, services
from apps.devices.api.v1.serializers import (
    CameraSerializer,
    ComputerSerializer,
    DeviceRegisterSerializer,
    DeviceTokenSerializer,
)
from apps.devices.models import Camera, Computer, DeviceToken
from apps.proctoring.services.audit import record_audit

logger = logging.getLogger(__name__)


class ComputerViewSet(
    PermissionRequiredMixin, AuditLogMixin, SoftDeleteRestoreMixin, viewsets.ModelViewSet
):
    serializer_class = ComputerSerializer
    permission_classes = [IsAuthenticated, HasRolePermission]
    required_permission = "devices.manage"
    required_read_permission = "devices.view"
    audit_object_type = "Computer"
    filterset_fields = ["zone", "zone__region", "status", "is_active"]
    search_fields = ["inventory_code", "ip_address", "mac_address"]
    ordering_fields = ["inventory_code", "last_seen_at"]

    def get_queryset(self):
        from apps.proctoring.models import ExamSession

        # Har bir kompyuter uchun joriy faol sessiyani bitta subquery bilan
        # olamiz — N+1 o'rniga bitta so'rov.
        active_session = ExamSession.objects.filter(
            computer_id=OuterRef("pk"),
            status__in=[
                ExamSession.Status.IN_PROGRESS,
                ExamSession.Status.READY,
                ExamSession.Status.FACE_CHECK,
            ],
        ).values("pk")[:1]

        queryset = self.apply_deleted_filter(
            selectors.computers_base(include_deleted=True)
        ).annotate(active_session_id=Subquery(active_session))
        user = self.request.user
        if user.is_region_scoped:
            queryset = queryset.filter(zone__region_id=user.region_id)
        if self.action in ("retrieve", "list"):
            # Filtrsiz `prefetch_related("cameras")` ikki muammo berardi:
            # M2M through-jadvali yumshoq o'chirishda tozalanmaydi, ya'ni
            # hisobdan chiqarilgan kamera kompyuter kartochkasida ko'rinib
            # turardi; `select_related` yo'qligi esa `cameras_detail` dagi
            # har bir `zone_name`/`region_name` uchun qo'shimcha so'rov
            # keltirib chiqarardi. `cameras_base()` ikkalasini ham yopadi.
            queryset = queryset.prefetch_related(
                Prefetch("cameras", queryset=selectors.cameras_base())
            )
        return queryset


class CameraViewSet(
    PermissionRequiredMixin, AuditLogMixin, SoftDeleteRestoreMixin, viewsets.ModelViewSet
):
    serializer_class = CameraSerializer
    permission_classes = [IsAuthenticated, HasRolePermission]
    required_permission = "devices.manage"
    required_read_permission = "devices.view"
    audit_object_type = "Camera"
    filterset_fields = ["zone", "zone__region", "status", "is_active"]
    search_fields = ["name", "ip_address", "mac_address"]

    def get_queryset(self):
        queryset = self.apply_deleted_filter(selectors.cameras_base(include_deleted=True))
        user = self.request.user
        if user.is_region_scoped:
            queryset = queryset.filter(zone__region_id=user.region_id)
        return queryset


class DeviceTokenViewSet(PermissionRequiredMixin, AuditLogMixin, viewsets.ModelViewSet):
    serializer_class = DeviceTokenSerializer
    permission_classes = [IsAuthenticated, HasRolePermission]
    required_permission = "devices.manage"
    required_read_permission = "devices.view"
    audit_object_type = "DeviceToken"
    http_method_names = ["get", "post", "patch", "head", "options"]
    filterset_fields = ["status", "computer", "computer__zone"]
    search_fields = ["device_id", "hardware_fingerprint", "app_version"]

    def get_queryset(self):
        queryset = selectors.device_tokens_base()
        user = self.request.user
        if user.is_region_scoped:
            queryset = queryset.filter(computer__zone__region_id=user.region_id)
        return queryset

    @extend_schema(responses={200: DeviceTokenSerializer})
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        """Qurilmani faollashtiradi — clientdan so'rov qabul qilish uchun."""
        device = self.get_object()
        device.status = DeviceToken.Status.ACTIVE
        device.save(update_fields=["status", "updated_at"])
        self.log_audit("update", device, {"action": "approve"})
        return Response(DeviceTokenSerializer(device).data)

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        device = self.get_object()
        reason = (request.data or {}).get("reason", "")
        services.revoke_device(device, reason=reason)
        self.log_audit("device_revoke", device, {"reason": reason})
        return Response(DeviceTokenSerializer(device).data)


class DeviceRegisterView(APIView):
    """
    Client o'zini ro'yxatga qo'yadi.

    Ochiq endpoint, lekin yaratilgan qurilma `PENDING` holatida bo'ladi va
    admin tasdiqlamaguncha hech qanday so'rov qabul qilinmaydi. Bu yerda
    hech qanday sir berilmaydi — client so'rovlarini xodim JWT'si
    himoyalaydi, `device_id` esa maxfiy qiymat emas.
    """

    permission_classes: list = []
    authentication_classes: list = []
    # `REST_FRAMEWORK` da `DEFAULT_THROTTLE_CLASSES` YO'Q — chegara har bir
    # view'ga qo'lda ulanadi. Ochiq endpointda buni unutish mumkin emas.
    throttle_classes = [DeviceRegisterThrottle]

    @extend_schema(request=DeviceRegisterSerializer, responses={201: None})
    def post(self, request):
        serializer = DeviceRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Binoni so'rovning TASHQI (NAT) IP'si bo'yicha aniqlaymiz.
        # Bu ikki narsa uchun kerak: LAN IP bo'yicha moslashtirishni
        # to'g'ri binoga cheklash va avtomatik inventarizatsiya.
        observed_ip = client_ip(request)
        zone = services.resolve_zone_by_public_ip(observed_ip)

        # Server bino ICHIDA tursa, u client'ning LAN manzilini ko'radi
        # (marshrutda NAT yo'q) va binoni tashqi IP orqali aniqlay
        # olmaydi. Shu holatda client o'zi aniqlagan tashqi manzil
        # zaxira signal bo'lib ishlaydi.
        #
        # Bu qiymat ISHONCHSIZ (client uni yozib yuboradi), shuning uchun
        # u FAQAT bino tanlashda va faqat server ko'rgan manzil xususiy
        # bo'lganda ishlatiladi. Kirish ruxsatini u hech qachon hal
        # qilmaydi - `check_source_ip` baribir server ko'rgan manzilga
        # qaraydi.
        reported_ip = data.get("public_ip", "")
        if zone is None and reported_ip and is_private_ip(observed_ip):
            zone = services.resolve_zone_by_public_ip(reported_ip)
            if zone is not None:
                logger.info(
                    "Bino client aytgan tashqi IP orqali aniqlandi: %s -> %s "
                    "(server ko'rgan manzil: %s)",
                    reported_ip, zone, observed_ip,
                )

        public_ip = reported_ip or observed_ip

        computer = services.resolve_computer(
            mac_address=data.get("mac_address", ""),
            ip_address=data.get("ip_address", ""),
            inventory_code=data.get("inventory_code", ""),
            zone=zone,
        )

        if computer is None and settings.PROCTORING["AUTO_REGISTER_COMPUTERS"]:
            computer = services.auto_create_computer(
                zone=zone,
                mac_address=data.get("mac_address", ""),
                ip_address=data.get("ip_address", ""),
                inventory_code=data.get("inventory_code", ""),
            )
            if computer is not None:
                record_audit(
                    actor=None,
                    action="create",
                    object_type="Computer",
                    object_id=computer.pk,
                    meta={
                        "auto": True,
                        "public_ip": public_ip,
                        "mac_address": computer.mac_address,
                        "zone": str(zone),
                    },
                    request=request,
                )

        if computer is None:
            logger.info(
                "Qurilma ro'yxatdan o'ta olmadi: mac=%s lan_ip=%s public_ip=%s bino=%s",
                data.get("mac_address") or "-",
                data.get("ip_address") or "-",
                public_ip,
                zone or "aniqlanmadi",
            )
            return Response(
                {
                    "success": False,
                    "data": None,
                    "error": {
                        "code": "computer_not_found",
                        "message": (
                            "Bu kompyuter bazada topilmadi. Administrator uni MAC "
                            "manzili bilan ro'yxatga qo'shishi kerak."
                        ),
                        "details": {
                            "mac_address": data.get("mac_address", ""),
                            "observed_ip": observed_ip,
                            # Bino aniqlanmagani ko'pincha asosiy sabab:
                            # binoning tashqi IP'si `AllowedPublicIp` da yo'q.
                            "zone_resolved": zone is not None,
                            "public_ip": public_ip,
                        },
                    },
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # Bu kompyuter uchun avvaldan faol token bormi?
        existing = DeviceToken.objects.filter(
            computer=computer, status=DeviceToken.Status.ACTIVE
        ).first()
        if existing is not None:
            # Client `device_id` ni yo'qotgan bo'lishi mumkin (%APPDATA%
            # tozalangan, dastur boshqa profilda ishga tushgan). Bunda u
            # o'zi hech qachon tiklanolmaydi: yangi token berilmaydi,
            # eskisi esa unga noma'lum.
            #
            # Shuning uchun mavjud identifikator FAQAT apparat izi mos
            # kelganda qaytariladi - ya'ni so'rov o'sha mashinadan
            # kelayotgani isbotlanganda. Iz boshqa bo'lsa (masalan bir
            # kompyuterni ikki mashina o'ziniki deb da'vo qilyapti), ID
            # berilmaydi va masalani administrator hal qiladi.
            fingerprint = (data.get("hardware_fingerprint") or "")[:128]
            same_machine = bool(
                fingerprint and existing.hardware_fingerprint == fingerprint
            )
            if not same_machine:
                logger.warning(
                    "Qurilma qayta ro'yxatdan o'tmoqchi, lekin apparat izi boshqa: "
                    "pc=%s mavjud=%s kelgan=%s",
                    computer.inventory_code,
                    existing.hardware_fingerprint[:16] or "-",
                    fingerprint[:16] or "-",
                )

            # Javob konvertga ATAYLAB qo'lda o'raladi: `ApiJSONRenderer`
            # tayyor konvertni qayta o'ramaydi, shu tarzda `code` va
            # `details` client uchun barqaror shaklda yetib boradi.
            return Response(
                {
                    "success": False,
                    "data": None,
                    "error": {
                        "code": "device_already_registered",
                        "message": (
                            "Bu kompyuter uchun faol qurilma tokeni mavjud"
                            if same_machine
                            else "Bu kompyuter boshqa mashinaga biriktirilgan. "
                            "Administratorga murojaat qiling."
                        ),
                        "details": (
                            {"device_id": existing.device_id} if same_machine else None
                        ),
                    },
                },
                status=status.HTTP_409_CONFLICT,
            )

        if data.get("info_pc"):
            Computer.objects.filter(pk=computer.pk).update(info_pc=data["info_pc"])

        device = services.register_device(
            computer=computer,
            hardware_fingerprint=data.get("hardware_fingerprint", ""),
            app_version=data.get("app_version", ""),
            app_hash=data.get("app_hash", ""),
            reported_public_ip=reported_ip or None,
        )
        return Response(
            {
                "device_id": device.device_id,
                "status": device.status,
                "computer": {
                    "inventory_code": computer.inventory_code,
                    "zone": computer.zone.name,
                },
                "detail": "Qurilma ro'yxatga olindi, admin tasdig'ini kuting",
            },
            status=status.HTTP_201_CREATED,
        )
