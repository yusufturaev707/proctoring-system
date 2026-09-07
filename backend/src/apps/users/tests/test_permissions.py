"""
Rol ruxsatlari va hudud chegarasi.

`User.is_region_scoped` — "kim nima ko'radi" qoidasining YAGONA manbai.
Ilgari bu shart o'nta `get_queryset()` da qo'lda takrorlanardi va
ularning birortasini unutish jimgina ma'lumot oshkor bo'lishi demak
edi. Shuning uchun bu yerda barcha kombinatsiyalar sanab chiqiladi.
"""

from django.test import TestCase

from apps.regions.models import Region, Zone
from apps.users.models import Permission, Role, User


class RolePermissionTests(TestCase):
    def setUp(self):
        self.view = Permission.objects.create(code="sessions.view", name="Ko'rish")
        self.terminate = Permission.objects.create(
            code="sessions.terminate", name="Chetlashtirish"
        )
        self.wildcard = Permission.objects.create(code="devices.*", name="Qurilmalar")

        self.role = Role.objects.create(name="Proktor", key=2)
        self.role.permissions.set([self.view, self.wildcard])
        self.user = User.objects.create(username="proktor", role=self.role)

    def test_granted_permission(self):
        self.assertTrue(self.user.has_role_permission("sessions.view"))

    def test_missing_permission(self):
        self.assertFalse(self.user.has_role_permission("sessions.terminate"))

    def test_group_wildcard(self):
        """`devices.*` guruh ichidagi hamma narsani beradi."""
        self.assertTrue(self.user.has_role_permission("devices.view"))
        self.assertTrue(self.user.has_role_permission("devices.revoke"))

    def test_wildcard_does_not_leak_to_other_group(self):
        self.assertFalse(self.user.has_role_permission("users.view"))

    def test_superuser_bypasses_everything(self):
        admin = User.objects.create(username="admin", is_superuser=True)
        self.assertTrue(admin.has_role_permission("hech.qanday.kod"))
        self.assertEqual(admin.permission_codes(), ["*"])

    def test_star_permission(self):
        star = Permission.objects.create(code="*", name="Hammasi")
        role = Role.objects.create(name="Administrator", key=1)
        role.permissions.set([star])
        user = User.objects.create(username="a", role=role)
        self.assertTrue(user.has_role_permission("sessions.terminate"))

    def test_user_without_role_has_nothing(self):
        user = User.objects.create(username="hech kim")
        self.assertEqual(user.permission_codes(), [])
        self.assertFalse(user.has_role_permission("sessions.view"))

    def test_inactive_role_grants_nothing(self):
        """
        Rolni nofaol qilish - ruxsatlarni darhol olib tashlash usuli.

        Foydalanuvchini o'chirmasdan uni to'xtatib turish kerak
        bo'ladi (ta'til, tekshiruv).
        """
        self.role.is_active = False
        self.role.save(update_fields=["is_active"])
        user = User.objects.get(pk=self.user.pk)
        self.assertEqual(user.permission_codes(), [])
        self.assertFalse(user.has_role_permission("sessions.view"))

    def test_permission_codes_are_cached_per_instance(self):
        """
        Ruxsatlar instansiya darajasida keshlanadi.

        Har tekshiruvda M2M so'rovi ketsa, bitta so'rovda o'nlab
        qo'shimcha query paydo bo'lardi.
        """
        with self.assertNumQueries(1):
            self.user.permission_codes()
            self.user.permission_codes()
            self.user.has_role_permission("sessions.view")


class RegionScopeTests(TestCase):
    """
    `is_region_scoped` — filtr qo'llanadimi.

    To'rt holat va ularning har biri boshqa sababdan kelib chiqadi.
    """

    def setUp(self):
        self.region = Region.objects.create(name="Toshkent", dtm_id=1, vm_number=1)
        self.local_role = Role.objects.create(name="Proktor", key=2, is_global=False)
        self.global_role = Role.objects.create(
            name="Administrator", key=1, is_global=True
        )

    def test_regional_user_is_scoped(self):
        user = User.objects.create(
            username="p", role=self.local_role, region=self.region
        )
        self.assertTrue(user.is_region_scoped)

    def test_global_role_is_not_scoped(self):
        """
        Respublika roli viloyat biriktirilgan bo'lsa ham cheklanmaydi.

        Ilgari buning uchun Django superuser'i talab qilinardi; endi
        qaror ROLDA.
        """
        user = User.objects.create(
            username="a", role=self.global_role, region=self.region
        )
        self.assertFalse(user.is_region_scoped)

    def test_superuser_is_not_scoped(self):
        user = User.objects.create(
            username="s", is_superuser=True, region=self.region
        )
        self.assertFalse(user.is_region_scoped)

    def test_user_without_region_is_not_scoped(self):
        """Viloyatsiz xodim cheklanmaydi — tarixiy xulq."""
        user = User.objects.create(username="x", role=self.local_role, region=None)
        self.assertFalse(user.is_region_scoped)

    def test_inactive_global_role_falls_back_to_scoped(self):
        """
        Nofaol rol imtiyoz BERMAYDI.

        Aks holda rolni o'chirib qo'yish uni kuchaytirardi.
        """
        self.global_role.is_active = False
        self.global_role.save(update_fields=["is_active"])
        user = User.objects.create(
            username="a", role=self.global_role, region=self.region
        )
        self.assertTrue(user.is_region_scoped)


class RegionScopedPermissionTests(TestCase):
    """Obyekt darajasidagi ikkinchi qatlam (IDOR'ga qarshi)."""

    def setUp(self):
        from apps.common.permissions import RegionScopedPermission

        self.checker = RegionScopedPermission()
        self.toshkent = Region.objects.create(name="Toshkent", dtm_id=1, vm_number=1)
        self.samarqand = Region.objects.create(name="Samarqand", dtm_id=2, vm_number=2)
        self.role = Role.objects.create(name="Proktor", key=2)
        self.user = User.objects.create(
            username="p", role=self.role, region=self.toshkent
        )

    def _check(self, obj):
        request = type("R", (), {"user": self.user})()
        return self.checker.has_object_permission(request, None, obj)

    def test_allows_own_region_via_zone(self):
        zone = Zone.objects.create(region=self.toshkent, name="1", number=1)
        self.assertTrue(self._check(zone))

    def test_denies_other_region_via_zone(self):
        zone = Zone.objects.create(region=self.samarqand, name="1", number=1)
        self.assertFalse(self._check(zone))

    def test_allows_when_region_cannot_be_resolved(self):
        """
        Hududi aniqlanmagan obyekt to'silmaydi.

        Bu qatlam IKKINCHI himoya; asosiy filtrlash `get_queryset()`
        da. Bu yerda hamma narsani rad etish hududsiz ma'lumotnoma
        yozuvlarini (rol, ruxsat) ochib bo'lmaydigan qilardi.
        """
        self.assertTrue(self._check(object()))

    def test_global_user_sees_everything(self):
        self.user.is_superuser = True
        zone = Zone.objects.create(region=self.samarqand, name="1", number=1)
        self.assertTrue(self._check(zone))
