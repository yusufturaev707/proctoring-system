from django.db import IntegrityError
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.common.exceptions import DomainError
from apps.common.permissions import (
    HasPanelAccess,
    HasRegionAssignment,
    HasRolePermission,
    RepublicLevelWrite,
)


class PermissionRequiredMixin:
    """
    Admin yuzasi: panel kirishi + `required_permission` + viloyat biriktiruvi.

    `HasPanelAccess` va `HasRegionAssignment` HAR DOIM qo'shiladi — bu
    mixin faqat admin panel viewset'larida ishlatiladi: client rolidagi
    (Operator) token ham, viloyati yo'q viloyat xodimi ham ulardan
    birortasini ochmasligi kerak. `HasPanelAccess` BIRINCHI turadi —
    Operator "ruxsat yo'q" emas, "rolingiz panel uchun emas" degan
    aniq sababni olsin.
    """

    required_permission: str | None = None
    #: Yozuv barcha viloyatlar uchun BITTA (rol, sozlama, imtihon) —
    #: o'zgartirish faqat respublika darajasida (`RepublicLevelWrite`).
    republic_write_only: bool = False

    def get_permissions(self):
        permissions = super().get_permissions()
        permissions.insert(0, HasPanelAccess())
        permissions.append(HasRegionAssignment())
        if self.required_permission:
            permissions.append(HasRolePermission())
        if self.republic_write_only:
            permissions.append(RepublicLevelWrite())
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


class BulkSelectionMixin:
    """
    Ommaviy amal uchun TANLOV: `{"ids": [...]}` yoki `{"all": true}`.

    `all` — "filtrga mos HAMMASI", faqat joriy sahifa emas: filtr va
    qidiruv so'rovning QUERY parametrlarida keladi (ro'yxat bilan bir
    xil) va `filter_queryset` ularni qo'llaydi. Ikkala holatda ham tanlov
    `get_queryset()` dan o'tadi — viloyat chegarasi va "Savat" filtri
    ro'yxatdagidek; begona viloyatning ID'si jimgina tushib qoladi.
    """

    #: Bitta so'rovdagi ID'lar chegarasi (panel sahifasi 100 tagacha).
    bulk_max_ids = 5000

    def bulk_queryset(self):
        from rest_framework.exceptions import ValidationError

        data = self.request.data or {}
        queryset = self.filter_queryset(self.get_queryset())
        if data.get("all") is True:
            return queryset
        ids = data.get("ids")
        if not isinstance(ids, list) or not ids:
            raise ValidationError({"ids": ["Hech narsa tanlanmagan"]})
        if len(ids) > self.bulk_max_ids:
            raise ValidationError({"ids": [f"Bir martada ko'pi bilan {self.bulk_max_ids} ta"]})
        try:
            ids = {int(item) for item in ids}
        except (TypeError, ValueError):
            raise ValidationError({"ids": ["ID butun son bo'lishi kerak"]})
        return queryset.filter(pk__in=ids)
