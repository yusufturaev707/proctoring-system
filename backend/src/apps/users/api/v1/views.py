from django.db.models import Count
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from apps.common.mixins import AuditLogMixin, PermissionRequiredMixin
from apps.common.permissions import HasRolePermission
from apps.common.throttling import StaffLoginThrottle, client_ip
from apps.proctoring.services.audit import record_audit
from apps.users import services
from apps.users.api.v1.serializers import (
    FaceProfileSerializer,
    LoginSerializer,
    PermissionSerializer,
    RoleSerializer,
    SetPasswordSerializer,
    TokenPairSerializer,
    UserDetailSerializer,
    UserListSerializer,
    UserWriteSerializer,
)
from apps.users.models import Permission, Role, User


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [StaffLoginThrottle]

    @extend_schema(request=LoginSerializer, responses=TokenPairSerializer)
    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]
        ip_address = client_ip(request)
        services.record_login(user, ip_address)
        record_audit(actor=user, action="login", object_type="User", object_id=user.pk, request=request)

        return Response(TokenPairSerializer.for_user(user, context={"request": request}))


class RefreshView(TokenRefreshView):
    """
    simplejwt'ning standart view'i.

    `ROTATE_REFRESH_TOKENS=True` va `BLACKLIST_AFTER_ROTATION=True` bo'lgani
    uchun har bir refresh yangi juftlik qaytaradi va eskisi bekor qilinadi.
    O'g'irlangan refresh token bir marta ishlatilsa, haqiqiy foydalanuvchi
    keyingi urinishda 401 oladi — bu o'g'irlanishni aniqlash signali.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        raw_refresh = (request.data or {}).get("refresh")
        if raw_refresh:
            try:
                RefreshToken(raw_refresh).blacklist()
            except (TokenError, AttributeError):
                pass
        record_audit(actor=request.user, action="logout", object_type="User",
                     object_id=request.user.pk, request=request)
        return Response({"detail": "Chiqildi"})


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=UserDetailSerializer)
    def get(self, request):
        user = (
            User.objects.select_related("role", "region", "zone")
            .prefetch_related("role__permissions")
            .get(pk=request.user.pk)
        )
        return Response(UserDetailSerializer(user, context={"request": request}).data)


# --------------------------------------------------------------------------
# CRUD
# --------------------------------------------------------------------------
class UserViewSet(PermissionRequiredMixin, AuditLogMixin, viewsets.ModelViewSet):
    queryset = User.objects.select_related("role", "region", "zone")
    permission_classes = [IsAuthenticated, HasRolePermission]
    required_permission = "users.manage"
    required_read_permission = "users.view"
    audit_object_type = "User"

    # DIQQAT: `filter_backends` bu yerda QAYTA E'LON QILINMAYDI. Uni
    # `[DjangoFilterBackend]` deb yozish `DEFAULT_FILTER_BACKENDS` ni
    # butunlay almashtiradi va quyidagi `search_fields` / `ordering_fields`
    # jimgina ishlamay qoladi — panelda qidiruv maydoni bosilaveradi,
    # lekin natija hech qachon filtrlanmaydi.
    filterset_fields = ["role", "region", "zone", "is_active", "is_staff"]
    search_fields = ["username", "first_name", "last_name", "phone"]
    ordering_fields = ["id", "username", "created_at", "last_login_at"]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return UserWriteSerializer
        if self.action == "list":
            return UserListSerializer
        return UserDetailSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        # Viloyatga biriktirilgan admin faqat o'z viloyatidagilarni ko'radi.
        if user.is_region_scoped:
            queryset = queryset.filter(region_id=user.region_id)
        if self.action == "retrieve":
            queryset = queryset.prefetch_related("role__permissions")
        return queryset

    @extend_schema(request=SetPasswordSerializer, responses={200: None})
    @action(detail=True, methods=["post"], url_path="set-password")
    def set_password(self, request, pk=None):
        user = self.get_object()
        serializer = SetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.set_password(user, serializer.validated_data["password"])
        self.log_audit("update", user, {"field": "password"})
        return Response({"detail": "Parol yangilandi"})

    @extend_schema(request=FaceProfileSerializer, responses=FaceProfileSerializer)
    @action(detail=True, methods=["get", "put"], url_path="face-profile")
    def face_profile(self, request, pk=None):
        user = self.get_object()
        if request.method == "GET":
            profile = getattr(user, "face_profile", None)
            if profile is None:
                return Response({"detail": "Yuz profili yo'q"}, status=status.HTTP_404_NOT_FOUND)
            return Response(FaceProfileSerializer(profile).data)

        serializer = FaceProfileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = services.upsert_face_profile(
            user=user,
            embedding=serializer.validated_data.get("embedding"),
            photo_key=serializer.validated_data.get("photo_key", ""),
            model_name=serializer.validated_data.get("embedding_model", ""),
        )
        self.log_audit("update", user, {"field": "face_profile"})
        return Response(FaceProfileSerializer(profile).data)


class RoleViewSet(PermissionRequiredMixin, AuditLogMixin, viewsets.ModelViewSet):
    queryset = (
        Role.objects.prefetch_related("permissions")
        .annotate(users_count=Count("users", distinct=True))
        # annotate() Meta.ordering ni GROUP BY dan chiqarib tashlaydi —
        # tartibni aniq ko'rsatish shart, aks holda sahifalash beqaror bo'ladi.
        .order_by("key")
    )
    serializer_class = RoleSerializer
    permission_classes = [IsAuthenticated, HasRolePermission]
    required_permission = "users.manage"
    required_read_permission = "users.view"
    audit_object_type = "Role"
    # Rol barcha viloyatlar uchun BITTA: viloyat admini uni tahrirlasa,
    # boshqa viloyatlardagi xodimlarning huquqlari ham o'zgarardi.
    republic_write_only = True
    filterset_fields = ["is_active", "is_global"]
    search_fields = ["name"]


class PermissionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Permission.objects.all()
    serializer_class = PermissionSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["group"]
    pagination_class = None
