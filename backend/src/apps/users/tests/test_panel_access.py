"""
Panel yuzasi (`panel.access`), to'liq huquq (`*`) va rol muharriri.

Desktop client va panel BIR XIL JWT bilan ishlaydi. Shuning uchun
"Operator panelga kira olmaydi" qoidasi ikki qatlamda tekshiriladi:
login (`surface="panel"`) va har bir panel endpointi (`HasPanelAccess`) —
client login'idan olingan token ham panelda hech narsa ochmasligi kerak.
"""

from io import StringIO

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from apps.proctoring.tests import factories
from apps.proctoring.tests.test_client_api import bearer
from apps.users.models import Permission, Role, User

PASSWORD = "Parol-Juda-Kuchli-2026"


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient()

    def as_user(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=bearer(user))
        return self.client

    @staticmethod
    def with_password(user):
        user.set_password(PASSWORD)
        user.save(update_fields=["password"])
        return user

    @staticmethod
    def error_code(response):
        return response.json()["error"]["code"]


class PanelLoginTests(_Base):
    def setUp(self):
        super().setUp()
        # Eski bazadagi Operator: client ruxsatlari + panel ruxsati
        # (`sessions.view`), lekin `panel.access` YO'Q.
        self.operator = self.with_password(factories.make_user(
            permissions=["client.operate", "client.identity", "sessions.view"],
            panel_access=False,
        ))
        self.proctor = self.with_password(factories.make_user(
            permissions=["sessions.view", "dashboard.view"],
        ))

    def login(self, user, **extra):
        return self.client.post(
            "/api/v1/auth/login/",
            {"username": user.username, "password": PASSWORD, **extra},
            format="json",
        )

    def test_operator_cannot_log_into_panel(self):
        response = self.login(self.operator, surface="panel")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.error_code(response), "panel_access_denied")

    def test_operator_still_logs_into_client(self):
        """Client `surface` yubormaydi — oqim o'zgarmagan."""
        response = self.login(self.operator)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["data"]["user"]["has_panel_access"])

    def test_panel_role_logs_in(self):
        response = self.login(self.proctor, surface="panel")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["user"]["has_panel_access"])

    def test_unknown_surface_rejected(self):
        self.assertEqual(self.login(self.proctor, surface="admin").status_code, 400)


class PanelEndpointTests(_Base):
    """Client token'i panel API'sida HECH NARSA ochmaydi — ruxsat kodi bo'lsa ham."""

    def setUp(self):
        super().setUp()
        self.operator = factories.make_user(
            permissions=["client.operate", "sessions.view", "bookings.view", "technical.view"],
            panel_access=False,
        )

    def test_every_panel_surface_is_closed(self):
        client = self.as_user(self.operator)
        for url in (
            "/api/v1/sessions/",
            "/api/v1/computer-bookings/",
            "/api/v1/technical-problems/",
            "/api/v1/dashboard/summary/",
            "/api/v1/permissions/",
        ):
            with self.subTest(url=url):
                response = client.get(url)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(self.error_code(response), "panel_access_denied")

    def test_me_is_available_to_client(self):
        """`/auth/me/` client'ga ham kerak — u yuzaga bog'liq emas."""
        response = self.as_user(self.operator).get("/api/v1/auth/me/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["surfaces"], ["client"])

    def test_panel_access_alone_opens_nothing_else(self):
        """`panel.access` — faqat eshik: bo'limlarni ruxsat kodlari ochadi."""
        user = factories.make_user(permissions=["panel.access"])
        self.assertEqual(self.as_user(user).get("/api/v1/sessions/").status_code, 403)


class FullAccessTests(_Base):
    def test_star_grants_everything_including_future_codes(self):
        user = factories.make_user(permissions=["*"], panel_access=False)
        self.assertTrue(user.has_panel_access)
        self.assertTrue(user.has_role_permission("kelajakdagi.ruxsat"))
        self.assertEqual(self.as_user(user).get("/api/v1/sessions/").status_code, 200)


class ActionPermissionTests(_Base):
    """`warn` va `terminate` — ikki alohida qaror (`action_permissions`)."""

    def test_warn_does_not_require_terminate(self):
        user = factories.make_user(permissions=["sessions.view", "sessions.warn"])
        client = self.as_user(user)
        # Yo'q sessiya: ruxsat qatlamidan O'TGANINI 404 ko'rsatadi (403 emas).
        response = client.post("/api/v1/sessions/999999/warn/", {"message": "x"}, format="json")
        self.assertEqual(response.status_code, 404)
        response = client.post("/api/v1/sessions/999999/terminate/", {"reason": "x"}, format="json")
        self.assertEqual(response.status_code, 403)


class RoleEditorGuardTests(_Base):
    def setUp(self):
        super().setUp()
        self.admin = factories.make_user(permissions=["users.view", "users.manage"])
        self.role = self.admin.role

    def patch_role(self, role, **payload):
        return self.as_user(self.admin).patch(f"/api/v1/roles/{role.pk}/", payload, format="json")

    def ids(self, *codes):
        return [
            Permission.objects.get_or_create(code=code, defaults={"name": code})[0].pk
            for code in codes
        ]

    def test_cannot_escalate_own_role(self):
        response = self.patch_role(
            self.role, permission_ids=self.ids("users.view", "users.manage", "panel.access", "*"),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("permission_ids", response.json()["error"]["details"])

    def test_cannot_strip_own_panel_access(self):
        response = self.patch_role(self.role, permission_ids=self.ids("users.view", "users.manage"))
        self.assertEqual(response.status_code, 400)

    def test_cannot_deactivate_own_role(self):
        self.assertEqual(self.patch_role(self.role, is_active=False).status_code, 400)

    def test_can_edit_other_role_within_own_rights(self):
        other = Role.objects.create(name="Navbatchi", key=7001)
        response = self.patch_role(other, permission_ids=self.ids("panel.access", "users.view"))
        self.assertEqual(response.status_code, 200)

    def test_role_with_users_is_not_deleted(self):
        other = Role.objects.create(name="Band", key=7002)
        User.objects.create(username="band-xodim", role=other)
        response = self.as_user(self.admin).delete(f"/api/v1/roles/{other.pk}/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.error_code(response), "role_in_use")
        self.assertTrue(Role.objects.filter(pk=other.pk).exists())

    def test_cannot_delete_or_block_self(self):
        client = self.as_user(self.admin)
        self.assertEqual(client.delete(f"/api/v1/users/{self.admin.pk}/").status_code, 400)
        response = client.patch(f"/api/v1/users/{self.admin.pk}/", {"is_active": False}, format="json")
        self.assertEqual(response.status_code, 400)


class SeedRolesTests(TestCase):
    """`seed_base_data` har deploy'da ishlaydi — administrator qarorini bosmaydi."""

    def seed(self, *args):
        call_command("seed_base_data", *args, stdout=StringIO())

    def codes(self, name):
        return set(Role.objects.get(name=name).permissions.values_list("code", flat=True))

    def test_fresh_install_matrix(self):
        self.seed()
        self.assertIn("*", self.codes("Administrator"))
        self.assertIn("panel.access", self.codes("Proktor"))
        operator = self.codes("Operator")
        self.assertNotIn("panel.access", operator)
        self.assertTrue(all(code.startswith("client.") for code in operator))

    def test_rerun_keeps_panel_changes(self):
        self.seed()
        proctor = Role.objects.get(name="Proktor")
        proctor.permissions.add(Permission.objects.get(code="audit.view"))
        self.seed()
        self.assertIn("audit.view", self.codes("Proktor"))
        self.seed("--reset-roles")
        self.assertNotIn("audit.view", self.codes("Proktor"))

    def test_upgrade_backfills_panel_access_once(self):
        """Eski baza: `panel.access` hali yo'q, rollar panel kodlari bilan ochilardi."""
        # Ba'zi ruxsatlarni migratsiyalar yaratadi (`exams.0007`) — shuning
        # uchun get_or_create; yangi kodlar esa aniq yo'q bo'lsin.
        Permission.objects.filter(code__in=["panel.access", "*"]).delete()
        view = Permission.objects.get_or_create(code="bookings.view", defaults={"name": "x"})[0]
        operate = Permission.objects.get_or_create(code="client.operate", defaults={"name": "x"})[0]
        integration = Role.objects.create(name="Bron tizimi", key=8001)
        integration.permissions.set([view])
        operator = Role.objects.create(name="Operator", key=5)
        operator.permissions.set([operate, view])

        self.seed()

        self.assertIn("panel.access", self.codes("Bron tizimi"))
        self.assertNotIn("panel.access", self.codes("Operator"))
        # Mavjud Operatorning ruxsatlariga tegilmagan — faqat panel yopilgan.
        self.assertIn("bookings.view", self.codes("Operator"))
