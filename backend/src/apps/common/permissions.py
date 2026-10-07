"""
Ruxsatlar.

Django'ning standart `auth.Permission` tizimi model-darajasida ishlaydi va
bizning holatimizga to'liq mos kelmaydi: proktorga "faqat o'z binosidagi
sessiyalarni ko'rish" kerak. Shuning uchun `Role -> Permission(code)` va
`region/zone` bo'yicha scoping birga ishlatiladi.
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission

__all__ = [
    "HasPanelAccess",
    "HasRegionAssignment",
    "HasRolePermission",
    "RegionScopedPermission",
    "RepublicLevelWrite",
    "scope_region_id",
]


class HasRegionAssignment(BasePermission):
    """
    Admin yuzasida: viloyat darajasidagi xodimga viloyat biriktirilgan.

    Faqat ADMIN yuzasiga qo'yiladi (`PermissionRequiredMixin`, dashboard,
    WebSocket monitor) — desktop client'ning ruxsat zanjiri alohida:
    operator hisobidagi tuzatilmagan maydon imtihon kuni butun binoni
    to'xtatib qo'ymasligi kerak.

    `code` frontendga ochiq sabab beradi: panel oddiy "ruxsat yo'q"
    o'rniga "hisobingizga viloyat biriktirilmagan" ekranini ko'rsatadi.
    """

    message = "Hisobingizga viloyat biriktirilmagan — administratorga murojaat qiling"
    code = "region_not_assigned"

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return True  # autentifikatsiyani boshqa klass hal qiladi
        return not user.lacks_region


class HasPanelAccess(BasePermission):
    """
    Admin yuzasi: rolda `panel.access` bor (`User.has_panel_access`).

    Desktop client va panel bitta JWT bilan ishlaydi, ya'ni client'da
    login qilgan Operator tokeni panel API'siga ham yaroqli. Ruxsat
    kodlari buni to'smaydi: eski bazalarda Operator rolida
    `sessions.view` qolgan. Shuning uchun panelning HAR BIR endpointi
    yuzaning o'zini alohida tekshiradi — `PermissionRequiredMixin`,
    dashboard, fayl view'lari va `MonitorConsumer`.
    """

    message = "Rolingiz admin panel uchun emas — u faqat desktop client dasturida ishlaydi"
    code = "panel_access_denied"

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return True  # autentifikatsiyani boshqa klass hal qiladi
        return user.has_panel_access


class RepublicLevelWrite(BasePermission):
    """
    UMUMIY ma'lumotni faqat respublika darajasi O'ZGARTIRADI.

    Rollar, viloyatlar ro'yxati, client sozlama profillari, AI siyosati,
    imtihonlar — barcha viloyatlar uchun BITTA yozuv. Viloyat
    foydalanuvchisi ularni o'qiydi (o'z ishida kerak), lekin tahrirlasa
    boshqa viloyatlardagi xodimlar, imtihonlar va mashinalarga ta'sir
    qiladi — ya'ni viloyat chegarasi yozish orqali buzilardi. Ruxsat
    kodi (`controls.manage` va h.k.) buni hal qilmaydi: u "nima" degan
    savolga javob beradi, "qayerda" degan savolga emas.
    """

    message = "Bu umumiy ma'lumot — uni faqat respublika darajasidagi xodim o'zgartiradi"
    code = "republic_level_only"

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        return bool(user and user.is_authenticated and not user.is_region_scoped)


def scope_region_id(user):
    """
    So'rovdagi `region` parametri QACHON e'tiborga olinadi.

    Viloyat foydalanuvchisi uchun — hech qachon: uning viloyati majburiy
    (aks holda filtr maydoni chegarani chetlab o'tish vositasi bo'lardi).
    Respublika darajasidagi foydalanuvchi uchun `None` — "barcha".

    Ilgari bu savol `None if user.is_superuser else user.region_id`
    shaklida to'rt joyda takrorlanardi va respublika roli (`is_global`)
    bilan kelgan Administrator o'zini viloyatga qamab qo'yardi yoki
    (viloyat biriktirilgan bo'lsa) faqat o'shani ko'rardi.
    """
    return user.region_id if user.is_region_scoped else None


class HasRolePermission(BasePermission):
    """
    View'da `required_permission = "sessions.view"` ko'rsatiladi.

    `action_permissions = {"warn": "sessions.warn"}` — amalga xos ruxsat
    (`required_permission` / `required_read_permission` dan USTUN). Usiz
    POST amallarning hammasi bitta `required_permission` ga tushardi:
    `sessions.warn` berilgan, lekin chetlashtirish huquqi yo'q rol
    ogohlantirish ham yubora olmasdi.

    Superuser barcha tekshiruvlardan o'tadi.
    """

    message = "Ushbu amal uchun ruxsat yo'q"

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True

        action_permissions = getattr(view, "action_permissions", None) or {}
        action = getattr(view, "action", None)
        if action in action_permissions:
            return user.has_role_permission(action_permissions[action])

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
