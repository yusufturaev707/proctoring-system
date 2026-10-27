from django.db.models import Count, Prefetch, Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import SAFE_METHODS, IsAuthenticated
from rest_framework.response import Response

from apps.common.mixins import AuditLogMixin, PermissionRequiredMixin, SoftDeleteRestoreMixin
from apps.common.permissions import HasRolePermission
from apps.controls import offers as offer_services
from apps.controls import services
from apps.controls.api.v1.serializers import (
    AllowedPublicIpSerializer,
    ClientExitPasswordSerializer,
    CocoObjectGroupSerializer,
    CocoObjectSerializer,
    EventRiskWeightSerializer,
    HotKeyboardKeyListSerializer,
    ModelVersionSerializer,
    OfferRevisionSerializer,
    OfferSerializer,
    ProctoringPolicySerializer,
    RdpObjectListSerializer,
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
    Offer,
    ProctoringPolicy,
    RdpObject,
    Setting,
)
from apps.exams.models import Exam


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


class OfferViewSet(SoftDeleteRestoreMixin, ControlsBaseViewSet):
    """
    Oferta matnlari. Respublika darajasida (`republic_write_only`): test
    barcha viloyatlar uchun bitta, uning ofertasi ham.

    Ro'yxatda HTML ham qaytadi — sahifa uni ko'rish oynasida chizadi va
    tahrirlash formasini qo'shimcha so'rovsiz ochadi (yozuvlar soni kam).
    """

    # Alohida ruxsat (`offers.*`, sababi — `users.services.DEFAULT_PERMISSIONS`).
    required_permission = "offers.manage"
    required_read_permission = "offers.view"
    queryset = (
        Offer.objects.select_related("updated_by")
        .prefetch_related(
            Prefetch(
                "exams",
                queryset=Exam.objects.alive().only("id", "name", "is_active", "offer_id").order_by("name"),
                to_attr="alive_exams",
            )
        )
        # `distinct` — test bo'yicha filtr/qidiruv JOIN qo'shadi va sanoqni ko'paytirardi.
        .annotate(consents_count=Count("revisions__consents", distinct=True))
    )
    serializer_class = OfferSerializer
    audit_object_type = "Offer"
    filterset_fields = ["is_active", "exams"]
    search_fields = ["title", "exams__name"]
    ordering_fields = ["updated_at", "title", "version"]

    def get_queryset(self):
        return self.apply_deleted_filter(super().get_queryset())

    def _audit_meta(self, offer, **extra) -> dict:
        meta = {"version": offer.version, "is_active": offer.is_active, **extra}
        changes = getattr(offer, "exam_changes", None)
        if changes and (changes["added"] or changes["removed"]):
            meta["exams"] = changes
        return meta

    def perform_create(self, serializer):
        offer = serializer.save()
        self.log_audit("create", offer, self._audit_meta(offer))

    def perform_update(self, serializer):
        before = serializer.instance.version
        offer = serializer.save()
        # Auditda matnning o'zi YO'Q (u `OfferRevision` da); versiya
        # o'zgargani "matn tahrirlandi" ni, `exams` — qaysi testlar
        # qo'shilgani/ajratilgani (va qaysi ofertadan ko'chgani) ni aytadi.
        self.log_audit("update", offer, self._audit_meta(offer, new_revision=offer.version != before))

    def perform_destroy(self, instance):
        offer_services.delete_offer(instance)
        self.log_audit("delete", instance, {"version": instance.version})

    @action(detail=True, methods=["get"])
    def revisions(self, request, pk=None):
        """Versiyalar tarixi — har biriga nechta rozilik berilgani bilan."""
        offer = self.get_object()
        queryset = (
            offer.revisions.select_related("created_by")
            .annotate(consents_count=Count("consents"))
            .order_by("-version")
        )
        return Response(OfferRevisionSerializer(queryset, many=True).data)


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
    search_fields = ["ip_address", "network", "name"]

    def get_queryset(self):
        # Ilgari ro'yxat umuman cheklanmagan edi: viloyat xodimi barcha
        # binolarning manzillarini (tarmoq chegarasi) ko'rardi.
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


def _with_profiles(queryset):
    """Profillar ro'yxati bitta qo'shimcha so'rovda (`_ProfilesMixin`)."""
    return queryset.prefetch_related(
        Prefetch(
            "settings",
            queryset=Setting.objects.alive().only("id", "name", "is_active").order_by("-is_active", "name"),
            to_attr="alive_profiles",
        )
    )


class RdpObjectViewSet(ControlsBaseViewSet):
    queryset = _with_profiles(RdpObject.objects.all())
    serializer_class = RdpObjectListSerializer
    audit_object_type = "RdpObject"
    filterset_fields = ["is_active"]
    search_fields = ["name", "code"]
    ordering_fields = ["name", "created_at"]


class HotKeyboardKeyViewSet(ControlsBaseViewSet):
    queryset = _with_profiles(HotKeyboardKey.objects.all())
    serializer_class = HotKeyboardKeyListSerializer
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
