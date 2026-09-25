"""
FaceID integratsiyasi: `X-API-Key`, ochiq sessiyalar, ishchi kompyuterlar, bron.

Bino ikki tizimda TASHQI raqamlar bilan bog'lanadi — `region_dtm_id` +
`zone_number` (FaceID'da `regions.number` + `zone.number`). Testlar
aynan shu juftlik ichki ID'lar o'rniga ishlashini tekshiradi.
"""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.exams import bookings
from apps.exams.models import ComputerBooking
from apps.proctoring.models import AuditLog
from apps.proctoring.tests import factories

KEY = "k" * 40
PINFL = "30000000000001"
OTHER = "30000000000002"


@override_settings(FACEID_INTEGRATION={"API_KEY": KEY, "USER": "faceid"})
class FaceIdApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.region = factories.make_region(dtm_id=12)
        self.zone = factories.make_zone(region=self.region, number=3)
        self.pc1 = factories.make_computer(zone=self.zone, number=1)
        self.pc2 = factories.make_computer(zone=self.zone, number=2)
        self.schedule = factories.make_schedule(zone=self.zone)
        self.service = factories.make_user(
            username="faceid",
            permissions=["bookings.view", "bookings.manage"],
            global_role=True,
        )

    @staticmethod
    def _finish(schedule):
        schedule.starts_at = timezone.now() - timedelta(hours=3)
        schedule.ends_at = timezone.now() - timedelta(minutes=1)
        schedule.save()

    def _get(self, url, key=KEY):
        return self.client.get(url, HTTP_X_API_KEY=key) if key else self.client.get(url)

    def _book(self, number=1, pinfl=PINFL, **extra):
        payload = {
            "schedule": self.schedule.pk,
            "pinfl": pinfl,
            "region_dtm_id": 12,
            "zone_number": 3,
            "computer_number": number,
            **extra,
        }
        return self.client.post(
            "/api/v1/integrations/faceid/book/", payload, format="json", HTTP_X_API_KEY=KEY
        )

    # --- Autentifikatsiya ------------------------------------------------
    def test_missing_or_wrong_key_is_rejected(self):
        self.assertEqual(self._get("/api/v1/integrations/faceid/schedules/", key=None).status_code, 401)
        self.assertEqual(self._get("/api/v1/integrations/faceid/schedules/", key="x" * 40).status_code, 401)

    @override_settings(FACEID_INTEGRATION={"API_KEY": "", "USER": "faceid"})
    def test_empty_configured_key_rejects_everything(self):
        """Bo'sh kalit "tekshiruv o'chiq" degani emas."""
        self.assertEqual(self._get("/api/v1/integrations/faceid/schedules/", key="").status_code, 401)
        response = self.client.get(
            "/api/v1/integrations/faceid/schedules/", HTTP_X_API_KEY="anything"
        )
        self.assertEqual(response.status_code, 401)

    def test_jwt_is_not_accepted_on_this_surface(self):
        self.client.force_authenticate(None)
        response = self.client.get(
            "/api/v1/integrations/faceid/schedules/", HTTP_AUTHORIZATION="Bearer abc"
        )
        self.assertEqual(response.status_code, 401)

    def test_region_scoped_service_user_is_refused(self):
        self.service.role.is_global = False
        self.service.role.save()
        self.service.region = self.region
        self.service.save()
        self.assertEqual(self._get("/api/v1/integrations/faceid/schedules/").status_code, 403)

    # --- Ro'yxatlar ------------------------------------------------------
    def test_schedules_lists_only_unfinished(self):
        finished = factories.make_schedule(zone=self.zone)
        self._finish(finished)

        data = self._get("/api/v1/integrations/faceid/schedules/").json()["data"]

        ids = [row["id"] for row in data]
        self.assertIn(self.schedule.pk, ids)
        self.assertNotIn(finished.pk, ids)
        row = next(row for row in data if row["id"] == self.schedule.pk)
        self.assertEqual((row["zone"]["region_dtm_id"], row["zone"]["zone_number"]), (12, 3))

    def test_computers_skip_broken_and_unnumbered_and_show_bookings(self):
        factories.make_computer(zone=self.zone, number=None)
        broken = factories.make_computer(zone=self.zone, number=5)
        ComputerBooking.objects.create(schedule=self.schedule, computer=broken, is_active=False)
        bookings.assign(self.schedule, OTHER, computer=self.pc2)

        data = self._get(
            f"/api/v1/integrations/faceid/schedules/{self.schedule.pk}/computers/"
        ).json()["data"]

        self.assertEqual([row["number"] for row in data["results"]], [1, 2])
        second = data["results"][1]
        self.assertEqual((second["is_booked"], second["pinfl"]), (True, OTHER))
        self.assertEqual(second["region_dtm_id"], 12)
        # O'qish hech narsa yozmaydi.
        self.assertFalse(ComputerBooking.objects.filter(computer=self.pc1).exists())

    # --- Bron -------------------------------------------------------------
    def test_book_by_external_numbers_is_idempotent(self):
        first = self._book(number=1)
        second = self._book(number=1)

        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(second.json()["data"]["booking_id"], first.json()["data"]["booking_id"])
        booking = ComputerBooking.objects.get(schedule=self.schedule, pinfl=PINFL)
        self.assertEqual(booking.computer, self.pc1)
        self.assertEqual(booking.booked_by, self.service)
        # Takror audit yozmaydi.
        self.assertEqual(AuditLog.objects.filter(meta__by="faceid").count(), 1)

    def test_book_rejects_seat_of_another_candidate(self):
        bookings.assign(self.schedule, OTHER, computer=self.pc1)

        response = self._book(number=1)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "seat_unavailable")

    def test_book_unknown_computer(self):
        response = self._book(number=99)
        self.assertEqual(response.status_code, 409)
        self.assertIn("№99", response.json()["error"]["message"])

    def test_candidate_in_exam_cannot_be_moved(self):
        self._book(number=1)
        factories.make_session(
            device=factories.make_device(computer=self.pc1),
            exam=self.schedule.exam, schedule=self.schedule, pinfl=PINFL,
        )

        response = self._book(number=2)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "seat_in_use")

    def test_finished_schedule_cannot_be_booked(self):
        self._finish(self.schedule)
        self.assertEqual(self._book(number=1).status_code, 404)
