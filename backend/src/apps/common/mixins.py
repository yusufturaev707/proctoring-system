from django.db import IntegrityError
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.common.exceptions import DomainError
from apps.common.permissions import HasRolePermission


class PermissionRequiredMixin:
    """`required_permission` atributini `HasRolePermission` bilan bog'laydi."""

    required_permission: str | None = None

    def get_permissions(self):
        permissions = super().get_permissions()
        if self.required_permission:
            permissions.append(HasRolePermission())
        return permissions


class AuditLogMixin:
    """
    O'zgartiruvchi amallarni AuditLog'ga yozadi.

    Proktorlik tizimida "kim, kimni, qachon chetlashtirdi" savoli sudda
    beriladi — shuning uchun audit ixtiyoriy emas.
    """

    audit_object_type: str | None = None

    def log_audit(self, action: str, obj=None, meta: dict | None = None):
        from apps.proctoring.services.audit import record_audit

        record_audit(
            actor=self.request.user,
            action=action,
            object_type=self.audit_object_type or self.queryset.model.__name__,
            object_id=getattr(obj, "pk", None),
            meta=meta or {},
            request=self.request,
        )

    def perform_create(self, serializer):
        instance = serializer.save()
        self.log_audit("create", instance)
        return instance

    def perform_update(self, serializer):
        instance = serializer.save()
        self.log_audit("update", instance)
        return instance

    def perform_destroy(self, instance):
        self.log_audit("delete", instance)
        instance.delete()


class SoftDeleteRestoreMixin:
    """
    Yumshoq o'chirilgan yozuvlarni ko'rish va TIKLASH.

    `SoftDeleteModel` "hech narsa yo'qolmasin" uchun kiritilgan, lekin
    yo'qolgan yozuvni qaytarish yo'li yo'q edi: ro'yxatlar `.alive()`
    bilan filtrlanadi, API'da `restore` amali yo'q edi, panelda esa
    "Savat" yo'q. Natijada tasodifan o'chirilgan kompyuterni faqat DB
    yoki Django admin orqali qaytarish mumkin edi — imtihon kuni bu
    butun ish o'rnini to'xtatadi.

    Ikkita narsa qo'shiladi:

      * `?deleted=only` — faqat o'chirilganlar, `?deleted=all` — hammasi.
        Standart holat o'zgarmaydi: faqat tiriklar.
      * `POST {id}/restore/` — yozuvni qaytaradi.

    Tiklash `get_object()` orqali ketadi, ya'ni ruxsat va hudud
    tekshiruvlari (`RegionScopedPermission`) joyida qoladi: boshqa
    viloyatning yozuvini tiklab bo'lmaydi.
    """

    #: Faqat `restore` chaqiruvi davomida `get_object()` o'chirilganlarni
    #: ham ko'rishi kerak — aks holda u 404 beradi.
    _include_deleted_override = False

    @property
    def deleted_mode(self) -> str:
        if self._include_deleted_override:
            return "all"
        raw = (self.request.query_params.get("deleted") or "").strip().lower()
        if raw in ("1", "true", "only", "yes"):
            return "only"
        if raw == "all":
            return "all"
        return "alive"

    def apply_deleted_filter(self, queryset):
        """Viewset `get_queryset()` da FILTRSIZ queryset berib, shuni chaqiradi."""
        mode = self.deleted_mode
        if mode == "only":
            return queryset.filter(deleted_at__isnull=False)
        if mode == "all":
            return queryset
        return queryset.filter(deleted_at__isnull=True)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        self._include_deleted_override = True
        try:
            instance = self.get_object()
        finally:
            self._include_deleted_override = False

        if instance.deleted_at is None:
            raise DomainError("Bu yozuv o'chirilmagan", code="not_deleted")

        try:
            instance.restore()
        except IntegrityError as exc:
            # Shartli unikal cheklovlar (`unique_computer_mac` va h.k.)
            # faqat TIRIK qatorlar orasida ishlaydi. Yozuv o'chirilgach
            # uning kodi/MAC'i bo'shab qoladi va boshqa yozuv uni band
            # qilishi mumkin — o'shanda tiklash konfliktga uriladi.
            raise DomainError(
                "Tiklab bo'lmadi: bu yozuvning kodi yoki manzili boshqa "
                "yozuv tomonidan band qilingan. Avval o'shani o'zgartiring.",
                code="restore_conflict",
            ) from exc

        if hasattr(self, "log_audit"):
            self.log_audit("restore", instance)

        serializer = self.get_serializer(instance)
        return Response(serializer.data)
