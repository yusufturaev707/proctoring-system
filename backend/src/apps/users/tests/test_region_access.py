"""
Viloyat chegarasi — admin yuzasi bo'ylab.

Uch qatlam va har birida jimgina sizib chiqish bo'lgan:

  * KIM: viloyatsiz viloyat xodimi ilgari HAMMA narsani ko'rardi;
  * O'QISH: audit, IP ro'yxati, dashboard va texnik muammolarda chegara
    yo'q yoki faqat `is_superuser` ga qaralgan edi (respublika roli o'z
    viloyatiga qamalardi);
  * YOZISH: begona viloyat binosiga kompyuter/kamera/seans qo'shish,
    respublika rolini berish, umumiy sozlamani o'zgartirish mumkin edi.
"""

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.controls.models import AllowedPublicIp
from apps.proctoring.models import AuditLog, TechnicalProblem
from apps.proctoring.tests import factories
from apps.proctoring.tests.test_client_api import bearer
from apps.users.models import Role


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient()
        self.home = factories.make_region()
        self.away = factories.make_region()
        self.home_zone = factories.make_zone(region=self.home)
        self.away_zone = factories.make_zone(region=self.away)

    def as_user(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=bearer(user))
        return self.client

    @staticmethod
    def ids(response):
        body = response.json()["data"]
        rows = body["results"] if isinstance(body, dict) else body
        return {row["id"] for row in rows}

    @staticmethod
    def error_code(response):
        return response.json()["error"]["code"]


class RegionlessUserTests(_Base):
    """Viloyat darajasidagi rol + viloyat yo'q = admin panelda HECH NARSA."""

    def setUp(self):
        super().setUp()
        self.user = factories.make_user(
            permissions=["sessions.view", "devices.view", "dashboard.view", "audit.view"],
            global_role=False,
        )

    def test_lists_are_closed_with_explicit_reason(self):
        client = self.as_user(self.user)
        for path in ("/api/v1/sessions/", "/api/v1/computers/", "/api/v1/audit-logs/"):
            response = client.get(path)
            self.assertEqual(response.status_code, 403, path)
            self.assertEqual(self.error_code(response), "region_not_assigned", path)

    def test_dashboard_is_closed(self):
        response = self.as_user(self.user).get("/api/v1/dashboard/summary/")
        self.assertEqual(response.status_code, 403)

    def test_me_tells_the_panel_why(self):
        response = self.as_user(self.user).get("/api/v1/auth/me/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["lacks_region"])

    def test_global_role_without_region_is_not_blocked(self):
        admin = factories.make_user(permissions=["sessions.view"], global_role=True)
        self.assertEqual(self.as_user(admin).get("/api/v1/sessions/").status_code, 200)


class ReadScopeTests(_Base):
    def setUp(self):
        super().setUp()
        self.proctor = factories.make_user(
            permissions=[
                "sessions.view", "technical.view", "dashboard.view",
                "audit.view", "controls.ip_view",
            ],
            region=self.home,
        )

    def test_audit_log_shows_only_own_region_staff(self):
        colleague = factories.make_user(permissions=[], region=self.home)
        stranger = factories.make_user(permissions=[], region=self.away)
        own = AuditLog.objects.create(actor=colleague, action="login")
        AuditLog.objects.create(actor=stranger, action="login")
        AuditLog.objects.create(actor=None, action="client_anomaly")

        ids = self.ids(self.as_user(self.proctor).get("/api/v1/audit-logs/"))

        self.assertEqual(ids, {own.pk})

    def test_allowed_ips_are_scoped_but_shared_ones_are_readable(self):
        own = AllowedPublicIp.objects.create(ip_address="8.8.8.1", zone=self.home_zone)
        shared = AllowedPublicIp.objects.create(ip_address="8.8.8.2", zone=None)
        AllowedPublicIp.objects.create(ip_address="8.8.8.3", zone=self.away_zone)

        ids = self.ids(self.as_user(self.proctor).get("/api/v1/allowed-ips/"))

        self.assertEqual(ids, {own.pk, shared.pk})

    def test_technical_problems_are_scoped(self):
        home_session = factories.make_session(computer=factories.make_computer(zone=self.home_zone))
        away_session = factories.make_session(computer=factories.make_computer(zone=self.away_zone))
        own = TechnicalProblem.objects.create(session=home_session, started_at=timezone.now())
        TechnicalProblem.objects.create(session=away_session, started_at=timezone.now())

        ids = self.ids(self.as_user(self.proctor).get("/api/v1/technical-problems/"))

        self.assertEqual(ids, {own.pk})

    def test_republic_role_with_region_still_sees_everything(self):
        """
        Ilgari `is_superuser` ga qaralardi: viloyati bor Administrator
        (respublika roli) texnik muammolarda faqat o'z viloyatini ko'rardi.
        """
        admin = factories.make_user(
            permissions=["technical.view"], region=self.home, global_role=True
        )
        for zone in (self.home_zone, self.away_zone):
            TechnicalProblem.objects.create(
                session=factories.make_session(computer=factories.make_computer(zone=zone)),
                started_at=timezone.now(),
            )

        ids = self.ids(self.as_user(admin).get("/api/v1/technical-problems/"))

        self.assertEqual(len(ids), 2)

    def test_dashboard_requires_its_permission(self):
        """Ilgari faqat `IsAuthenticated` edi — Operator ham sonlarni olardi."""
        operator = factories.make_user(permissions=["client.operate"], region=self.home)
        self.assertEqual(
            self.as_user(operator).get("/api/v1/dashboard/summary/").status_code, 403
        )
        self.assertEqual(
            self.as_user(self.proctor).get("/api/v1/dashboard/summary/").status_code, 200
        )


class WriteScopeTests(_Base):
    def setUp(self):
        super().setUp()
        self.admin = factories.make_user(
            permissions=[
                "devices.view", "devices.manage", "regions.view", "regions.manage",
                "exams.view", "exams.manage", "controls.view", "controls.manage",
                "controls.ip_view", "controls.ip_manage", "users.view", "users.manage",
            ],
            region=self.home,
        )

    def post(self, path, payload):
        return self.as_user(self.admin).post(path, payload, format="json")

    def test_computer_only_into_own_region(self):
        payload = {
            "number": 5, "inventory_code": "INV-X1",
            "ip_address": "10.0.0.5", "mac_address": "AA:00:00:00:00:01",
        }
        away = self.post("/api/v1/computers/", {**payload, "zone": self.away_zone.pk})
        self.assertEqual(away.status_code, 400, away.content)
        self.assertIn("zone", away.json()["error"]["details"])

        home = self.post("/api/v1/computers/", {**payload, "zone": self.home_zone.pk})
        self.assertEqual(home.status_code, 201, home.content)

    def test_computer_cannot_be_moved_to_another_region(self):
        computer = factories.make_computer(zone=self.home_zone)
        response = self.as_user(self.admin).patch(
            f"/api/v1/computers/{computer.pk}/", {"zone": self.away_zone.pk}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.content)

    def test_camera_only_into_own_region(self):
        response = self.post("/api/v1/cameras/", {
            "name": "Zal", "zone": self.away_zone.pk,
            "ip_address": "10.0.0.9", "mac_address": "AA:00:00:00:00:09",
        })
        self.assertEqual(response.status_code, 400, response.content)

    def test_zone_only_into_own_region(self):
        response = self.post("/api/v1/zones/", {"region": self.away.pk, "name": "Begona", "number": 7})
        self.assertEqual(response.status_code, 400, response.content)

    def test_shared_schedule_is_republic_level(self):
        exam = factories.make_exam()
        now = timezone.now()
        payload = {
            "exam": exam.pk, "exam_date": timezone.localdate().isoformat(),
            "starts_at": now.isoformat(),
            "ends_at": (now + timezone.timedelta(hours=2)).isoformat(),
        }
        shared = self.post("/api/v1/exam-schedules/", {**payload, "zone": None})
        self.assertEqual(shared.status_code, 400, shared.content)
        away = self.post("/api/v1/exam-schedules/", {**payload, "zone": self.away_zone.pk})
        self.assertEqual(away.status_code, 400, away.content)

    def test_shared_ip_is_republic_level(self):
        response = self.post("/api/v1/allowed-ips/", {"ip_address": "8.8.4.4", "zone": None})
        self.assertEqual(response.status_code, 400, response.content)

    def test_shared_settings_are_read_only(self):
        """Client sozlamasi barcha viloyat mashinalariga amal qiladi."""
        client = self.as_user(self.admin)
        self.assertEqual(client.get("/api/v1/hotkeys/").status_code, 200)
        response = client.post("/api/v1/hotkeys/", {"name": "Win", "key": "win"}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.error_code(response), "republic_level_only")

    def test_roles_are_read_only(self):
        role = Role.objects.create(name="Mahalliy", key=900)
        response = self.as_user(self.admin).patch(
            f"/api/v1/roles/{role.pk}/", {"is_global": True}, format="json"
        )
        self.assertEqual(response.status_code, 403)

    def test_cannot_grant_republic_role(self):
        """
        Kam ruxsatli respublika roli ham chegarani OLIB TASHLAYDI —
        ruxsatlar tekshiruvi buni ushlamasdi.
        """
        wide = Role.objects.create(name="Keng", key=901, is_global=True)
        response = self.post("/api/v1/users/", {
            "username": "yangi", "password": "Str0ng!Pass-2026",
            "role": wide.pk, "region": self.home.pk,
        })
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("role", response.json()["error"]["details"])


class UserShapeTests(_Base):
    def setUp(self):
        super().setUp()
        self.admin = factories.make_user(
            permissions=["users.view", "users.manage"], global_role=True
        )
        self.local_role = Role.objects.create(name="Viloyat", key=902, is_global=False)

    def post(self, payload):
        return self.as_user(self.admin).post(
            "/api/v1/users/",
            {"username": f"u{Role.objects.count()}", "password": "Str0ng!Pass-2026", **payload},
            format="json",
        )

    def test_regional_role_requires_region(self):
        response = self.post({"role": self.local_role.pk})
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("region", response.json()["error"]["details"])

    def test_zone_must_belong_to_region(self):
        response = self.post({
            "role": self.local_role.pk, "region": self.home.pk, "zone": self.away_zone.pk,
        })
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("zone", response.json()["error"]["details"])

    def test_consistent_account_is_created(self):
        response = self.post({
            "role": self.local_role.pk, "region": self.home.pk, "zone": self.home_zone.pk,
        })
        self.assertEqual(response.status_code, 201, response.content)


class SeatMapTests(_Base):
    """Joylar xaritasi: `zones/` va `seats/` ham viloyat chegarasida."""

    def setUp(self):
        super().setUp()
        from apps.exams import bookings

        self.schedule = factories.make_schedule(zone=None)
        self.home_pc = factories.make_computer(zone=self.home_zone, number=1)
        factories.make_computer(zone=self.home_zone, number=2)
        factories.make_computer(zone=self.away_zone, number=1)
        bookings.generate_seats(self.schedule)
        bookings.assign(self.schedule, "30000000000009", computer=self.home_pc)
        self.viewer = factories.make_user(permissions=["bookings.view"], region=self.home)

    def test_zones_are_scoped_and_counted(self):
        response = self.as_user(self.viewer).get(
            "/api/v1/computer-bookings/zones/", {"schedule": self.schedule.pk}
        )
        self.assertEqual(response.status_code, 200, response.content)
        rows = response.json()["data"]["results"]
        self.assertEqual([row["zone"] for row in rows], [self.home_zone.pk])
        self.assertEqual((rows[0]["total"], rows[0]["booked"], rows[0]["free"]), (2, 1, 1))

    def test_foreign_zone_seats_are_empty(self):
        client = self.as_user(self.viewer)
        own = client.get(
            "/api/v1/computer-bookings/seats/",
            {"schedule": self.schedule.pk, "zone": self.home_zone.pk},
        )
        self.assertEqual(len(own.json()["data"]["results"]), 2)
        away = client.get(
            "/api/v1/computer-bookings/seats/",
            {"schedule": self.schedule.pk, "zone": self.away_zone.pk},
        )
        self.assertEqual(away.json()["data"]["results"], [])

    def test_schedule_is_required(self):
        response = self.as_user(self.viewer).get("/api/v1/computer-bookings/zones/")
        self.assertEqual(response.status_code, 400)
