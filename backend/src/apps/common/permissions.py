"""
Ruxsatlar.

Django'ning standart `auth.Permission` tizimi model-darajasida ishlaydi va
bizning holatimizga to'liq mos kelmaydi: proktorga "faqat o'z binosidagi
sessiyalarni ko'rish" kerak. Shuning uchun `Role -> Permission(code)` va
`region/zone` bo'yicha scoping birga ishlatiladi.
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission

__all__ = ["HasRolePermission", "RegionScopedPermission"]


class HasRolePermission(BasePermission):
    """
    View'da `required_permission = "sessions.view"` ko'rsatiladi.

    Superuser barcha tekshiruvlardan o'tadi.
    """

    message = "Ushbu amal uchun ruxsat yo'q"

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True

        required = getattr(view, "required_permission", None)
        if required is None:
            return True

        if request.method in SAFE_METHODS:
            read_permission = getattr(view, "required_read_permission", required)
            return user.has_role_permission(read_permission)

        return user.has_role_permission(required)


class RegionScopedPermission(BasePermission):
    """
    Obyekt darajasida: foydalanuvchi faqat o'z viloyatidagi ma'lumotni ko'radi.

    Queryset darajasidagi filtrlash har bir viewset'ning `get_queryset()`
    ida; bu esa detail endpoint'lar uchun ikkinchi qatlam (IDOR'ga qarshi).
    """

    message = "Ushbu hudud ma'lumotlariga ruxsatingiz yo'q"

    def has_object_permission(self, request, view, obj):
        user = request.user
        # `is_region_scoped` - qoidaning yagona manbasi: superuser,
        # respublika roli (`Role.is_global`) va viloyatsiz xodim shu
        # yerda ham bir xil ishlaydi.
        if not user.is_region_scoped:
            return True

        region_id = _resolve_region_id(obj)
        return region_id is None or region_id == user.region_id


def _resolve_region_id(obj):
    """Turli modellardan region_id ni topadi."""
    for path in ("region_id", "zone__region_id", "computer__zone__region_id"):
        current = obj
        try:
            for part in path.split("__"):
                current = getattr(current, part)
            if current is not None:
                return current
        except AttributeError:
            continue
    return None
