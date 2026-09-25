from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import SAFE_METHODS, IsAuthenticated
from rest_framework.response import Response

from apps.common.mixins import AuditLogMixin, PermissionRequiredMixin, SoftDeleteRestoreMixin
from apps.common.permissions import HasRolePermission
from apps.controls import services
from apps.controls.api.v1.serializers import (
    AllowedPublicIpSerializer,
    ClientExitPasswordSerializer,
    CocoObjectGroupSerializer,
    CocoObjectSerializer,
    EventRiskWeightSerializer,
    HotKeyboardKeySerializer,
    ModelVersionSerializer,
    ProctoringPolicySerializer,
    RdpObjectSerializer,
    SettingSerializer,
)
from apps.controls.models import (
    AllowedPublicIp,
    ClientExitPassword,
    CocoObject,
    CocoObjectGroup,
    EventRiskWeight,
    HotKeyboardKey,
    ModelVersion,
    ProctoringPolicy,
    RdpObject,
    Setting,
)


class ControlsBaseViewSet(PermissionRequiredMixin, AuditLogMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasRolePermission]
    required_permission = "controls.manage"
    required_read_permission = "controls.view"
    # Client siyosati BARCHA viloyatlarning mashinalariga amal qiladi.
    # Viloyatga bog'langan ikki istisno (chiqish paroli, IP ro'yxati)
    # buni o'zi `False` qiladi va chegarani serializer'da tekshiradi.
    republic_write_only = True


class SettingViewSet(SoftDeleteRestoreMixin, ControlsBaseViewSet):
    queryset = (
        Setting.objects
        # `proctoring` - `ai_proctoring` maydoni uchun (N+1 bo'lmasin).
        .select_related("detect_model", "proctoring")
        .prefetch_related("detect_classes", "rdp_objects", "hotkeys")
    )
    serializer_class = SettingSerializer
    audit_object_type = "Setting"
    filterset_fields = ["is_active"]
    search_fields = ["name"]

    def get_queryset(self):
        return self.apply_deleted_filter(super().get_queryset())

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="exam",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    "Imtihon ID'si. Berilsa — o'sha imtihonning profili, "
                    "aks holda global standart qaytariladi."
                ),
            )
        ],
        responses={200: None},
    )
    @action(detail=False, methods=["get"], url_path="client-config")
    def client_config(self, request):
        """
        Client oladigan JSON — admin uni oldindan ko'rishi uchun.

        Javob shakli client oladigan bilan AYNAN bir xil (o'ram qo'shilmaydi):
        oldindan ko'rishning ma'nosi shundaki, ekranda ko'ringan narsa
        qurilmaga ketadigan narsa bo'lishi kerak. Qaysi profil ishlaganini
        javobdagi `setting_id` va `name` maydonlaridan bilish mumkin.
        """
        from apps.exams.models import Exam

        raw_exam_id = request.query_params.get("exam")
        if not raw_exam_id:
            return Response(services.get_client_config())

        # Xatolar `Response(...)` bilan emas, exception orqali qaytariladi:
        # faqat shunda ular `api_exception_handler` dan o'tib, qolgan API
        # bilan bir xil `{code, message, details}` o'ramini oladi.
        try:
            exam_id = int(raw_exam_id)
        except (TypeError, ValueError):
            raise ValidationError({"exam": "Imtihon ID'si butun son bo'lishi kerak"})

        # Nofaol imtihon ham ko'riladi: admin uni yoqishdan OLDIN
        # profilini tekshirmoqchi bo'lishi tabiiy.
        exam = (
            Exam.objects.select_related("setting")
            .filter(pk=exam_id, deleted_at__isnull=True)
            .first()
        )
        if exam is None:
            raise NotFound("Imtihon topilmadi")

        return Response(services.get_client_config(exam))

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        setting = self.get_object()
        setting.is_active = True
        setting.save()
        self.log_audit("setting_change", setting, {"action": "activate"})
        return Response(SettingSerializer(setting).data)


class ClientExitPasswordViewSet(ControlsBaseViewSet):
    """
    Viloyat bo'yicha chiqish parollari.

    Ruxsat `controls.exit_password_*` — client siyosatidan ALOHIDA:
    bu parol kiosk qulfini ochadi, ya'ni uni bilgan odam imtihon
    o'rtasida dasturni yopa oladi.

    Hududga bog'langan xodim faqat O'Z viloyatining parolini ko'radi:
    boshqa viloyatlarning kalitini ko'rishga (hatto "parol o'rnatilgan"
    faktini ham) uning ehtiyoji yo'q.
    """

    queryset = ClientExitPassword.objects.select_related("region")
    serializer_class = ClientExitPasswordSerializer
    required_permission = "controls.exit_password_manage"
    required_read_permission = "controls.exit_password_view"
    audit_object_type = "ClientExitPassword"
    republic_write_only = False
    filterset_fields = ["region", "is_active"]
    search_fields = ["name", "region__name"]
    ordering_fields = ["region__dtm_id", "updated_at"]

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if user.is_region_scoped:
            queryset = queryset.filter(region_id=user.region_id)
        return queryset

    def log_audit(self, action, instance, meta=None):
        # Audit yozuvi hech qachon parolni (hatto hash'ini ham) o'z
        # ichiga olmaydi - `AuditLogMixin` standart holda o'zgargan
        # maydonlarni yozadi.
        meta = {k: v for k, v in (meta or {}).items() if k != "password"}
        meta["region"] = getattr(instance.region, "name", "")
        return super().log_audit(action, instance, meta)


class AllowedPublicIpViewSet(ControlsBaseViewSet):
    queryset = AllowedPublicIp.objects.select_related("zone", "zone__region")
    serializer_class = AllowedPublicIpSerializer
    audit_object_type = "AllowedPublicIp"
    republic_write_only = False
    # Client siyosatidan ALOHIDA ruxsat: bu tarmoq chegarasi, bitta
    # noto'g'ri yozuv butun markazni tizimdan uzib qo'yadi.
    required_permission = "controls.ip_manage"
    required_read_permission = "controls.ip_view"
    filterset_fields = ["zone", "zone__region", "is_active"]
    search_fields = ["ip_address", "name"]

    def get_queryset(self):
        # Ilgari ro'yxat umuman cheklanmagan edi: viloyat xodimi barcha
        # binolarning tashqi manzillarini (tarmoq chegarasi) ko'rardi.
        # Binosiz (umumiy) manzil — `ExamSchedule` dagi naqsh: viloyatga
        # HAM amal qiladi, shuning uchun uni O'QIYDI, lekin o'zgartira
        # olmaydi (yozish — faqat o'z binolari).
        queryset = super().get_queryset()
        user = self.request.user
        if user.is_region_scoped:
            region = Q(zone__region_id=user.region_id)
            if self.request.method in SAFE_METHODS:
                region |= Q(zone__isnull=True)
            queryset = queryset.filter(region)
        return queryset

    def perform_create(self, serializer):
        instance = super().perform_create(serializer)
        services.invalidate_ip_cache()
        return instance

    def perform_update(self, serializer):
        instance = super().perform_update(serializer)
        services.invalidate_ip_cache()
        return instance

    def perform_destroy(self, instance):
        super().perform_destroy(instance)
        services.invalidate_ip_cache()


class ModelVersionViewSet(ControlsBaseViewSet):
    queryset = ModelVersion.objects.all()
    serializer_class = ModelVersionSerializer
    audit_object_type = "ModelVersion"
    filterset_fields = ["is_active"]
    # `search_fields` siz panel qidiruvi JIMGINA ishlamaydi: maydon
    # bosiladi, so'rov ketadi, natija esa hech qachon filtrlanmaydi.
    search_fields = ["name", "code"]
    ordering_fields = ["name", "created_at"]


class CocoObjectGroupViewSet(ControlsBaseViewSet):
    queryset = CocoObjectGroup.objects.all()
    serializer_class = CocoObjectGroupSerializer
    audit_object_type = "CocoObjectGroup"
    filterset_fields = ["is_active"]
    search_fields = ["name", "code"]


class CocoObjectViewSet(ControlsBaseViewSet):
    queryset = CocoObject.objects.select_related("group")
    serializer_class = CocoObjectSerializer
    audit_object_type = "CocoObject"
    filterset_fields = ["group", "is_active"]
    search_fields = ["name", "code"]
    ordering_fields = ["code", "name", "severity"]


class RdpObjectViewSet(ControlsBaseViewSet):
    queryset = RdpObject.objects.all()
    serializer_class = RdpObjectSerializer
    audit_object_type = "RdpObject"
    filterset_fields = ["is_active"]
    search_fields = ["name", "code"]
    ordering_fields = ["name", "created_at"]


class HotKeyboardKeyViewSet(ControlsBaseViewSet):
    queryset = HotKeyboardKey.objects.all()
    serializer_class = HotKeyboardKeySerializer
    audit_object_type = "HotKeyboardKey"
    filterset_fields = ["is_active"]
    search_fields = ["name", "code"]
    ordering_fields = ["name", "created_at"]


class ProctoringPolicyViewSet(ControlsBaseViewSet):
    """
    AI kuzatuv siyosati.

    ALOHIDA RUXSAT (`controls.proctoring_*`), `controls.manage` emas.
    Sabab boshqa `controls` sahifalari bilan bir xil mantiqda: bu
    yerdagi qiymatlar chetlashtirish statistikasiga bevosita ta'sir
    qiladi. Xavf chegarasini pasaytirish yoki dalil to'plashni
    o'chirish - skrinshot oralig'ini o'zgartirishdan butunlay boshqa
    javobgarlik darajasi va uni "sozlamalarni boshqarish" bilan bitta
    ruxsatga qo'shib yuborish mumkin emas.
    """

    queryset = ProctoringPolicy.objects.select_related("setting")
    serializer_class = ProctoringPolicySerializer
    required_permission = "controls.proctoring_manage"
    required_read_permission = "controls.proctoring_view"
    audit_object_type = "ProctoringPolicy"
    filterset_fields = ["setting", "is_enabled", "camera_count"]
    search_fields = ["setting__name"]
    ordering_fields = ["setting__name", "updated_at"]


class EventRiskWeightViewSet(ControlsBaseViewSet):
    """
    Hodisa og'irliklari.

    Kesh HAR BIR o'zgarishda tozalanadi. Bu `AllowedPublicIpViewSet`
    dagi bilan bir xil naqsh va bir xil sabab: administrator panelda
    qiymatni o'zgartirib, hech narsa o'zgarmaganini ko'rsa (5 daqiqa
    davomida), u buni xato deb hisoblaydi va yana o'zgartiradi.
    """

    queryset = EventRiskWeight.objects.all()
    serializer_class = EventRiskWeightSerializer
    required_permission = "controls.proctoring_manage"
    required_read_permission = "controls.proctoring_view"
    audit_object_type = "EventRiskWeight"
    filterset_fields = ["is_active"]
    search_fields = ["event_type"]
    ordering_fields = ["weight", "event_type", "cooldown_s"]

    def perform_create(self, serializer):
        instance = super().perform_create(serializer)
        services.invalidate_risk_weight_cache()
        return instance

    def perform_update(self, serializer):
        instance = super().perform_update(serializer)
        services.invalidate_risk_weight_cache()
        return instance

    def perform_destroy(self, instance):
        super().perform_destroy(instance)
        services.invalidate_risk_weight_cache()
