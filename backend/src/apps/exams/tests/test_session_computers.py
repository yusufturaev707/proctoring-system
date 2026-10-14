"""
Sessiyani QO'LDA tuzish: bino kompyuterlarini tanlab kiritish va chiqarish.

Asosiy xavflar:

  * talabgor o'tirgan yoki o'tirib bo'lgan joy ro'yxatdan tushib qoladi
    (bayonnoma isboti yo'qoladi, imtihondagi talabgor start'da rad etiladi);
  * avtomatik biriktirish administrator ataylab qoldirgan zaxira
    mashinalarni sessiyaga jimgina qaytarib qo'shadi.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.exams import bookings
from apps.exams.models import ComputerBooking
from apps.proctoring.tests import factories

PINFL = "30000000000001"
URL = "/api/v1/computer-bookings/zone-computers/"


class SessionComputersServiceTests(TestCase):
    def setUp(self):
        self.zone = factories.make_zone()
        self.pc1 = factories.make_computer(zone=self.zone, number=1)
        self.pc2 = factories.make_computer(zone=self.zone, number=2)
        self.pc3 = factories.make_computer(zone=self.zone, number=3)
        self.schedule = factories.make_schedule(zone=None)

    def _seated(self):
        return set(
            ComputerBooking.objects.filter(schedule=self.schedule).values_list("computer_id", flat=True)
        )

    def test_add_only_chosen_computers(self):
        result = bookings.update_session_computers(
            self.schedule, self.zone.pk, add=[self.pc1.pk, self.pc3.pk]
        )
        self.assertEqual((result["added"], result["removed"], result["skipped"]), (2, 0, []))
        self.assertEqual(self._seated(), {self.pc1.pk, self.pc3.pk})

        # Takroriy qo'shish xavfsiz va sanalmaydi.
        again = bookings.update_session_computers(self.schedule, self.zone.pk, add=[self.pc1.pk])
        self.assertEqual(again["added"], 0)

    def test_out_of_scope_computer_is_skipped(self):
        other = factories.make_computer(number=9)  # boshqa bino
        retired = factories.make_computer(zone=self.zone, number=4, is_active=False)
        result = bookings.update_session_computers(
            self.schedule, self.zone.pk, add=[self.pc1.pk, other.pk, retired.pk]
        )
        self.assertEqual(result["added"], 1)
        self.assertEqual({item["computer"] for item in result["skipped"]}, {other.pk, retired.pk})
        self.assertEqual(self._seated(), {self.pc1.pk})

    def test_remove_free_seat_but_keep_locked_ones(self):
        bookings.update_session_computers(
            self.schedule, self.zone.pk, add=[self.pc1.pk, self.pc2.pk, self.pc3.pk]
        )
        bookings.assign(self.schedule, PINFL, computer=self.pc1)
        ComputerBooking.objects.filter(computer=self.pc2).update(finished_count=1)

        result = bookings.update_session_computers(
            self.schedule, self.zone.pk, remove=[self.pc1.pk, self.pc2.pk, self.pc3.pk]
        )

        self.assertEqual(result["removed"], 1)
        reasons = {item["computer"]: item["reason"] for item in result["skipped"]}
        self.assertEqual(reasons, {self.pc1.pk: "booked", self.pc2.pk: "used"})
        self.assertEqual(self._seated(), {self.pc1.pk, self.pc2.pk})

    def test_free_seating_candidate_at_the_desk_keeps_the_seat(self):
        """Erkin rejim: joy start'gacha band emas, lekin stolda talabgor bor."""
        bookings.update_session_computers(self.schedule, self.zone.pk, add=[self.pc1.pk])
        factories.make_session(computer=self.pc1, schedule=self.schedule, status="ready")

        result = bookings.update_session_computers(self.schedule, self.zone.pk, remove=[self.pc1.pk])

        self.assertEqual(result["removed"], 0)
        self.assertEqual(result["skipped"][0]["reason"], "in_exam")

    def test_remove_is_limited_to_the_zone(self):
        other = factories.make_computer(number=9)
        ComputerBooking.objects.create(schedule=self.schedule, computer=other)
        result = bookings.update_session_computers(self.schedule, self.zone.pk, remove=[other.pk])
        self.assertEqual(result["removed"], 0)
        self.assertIn(other.pk, self._seated())

    def test_zone_listing_marks_session_membership(self):
        bookings.update_session_computers(self.schedule, self.zone.pk, add=[self.pc2.pk])
        bookings.assign(self.schedule, PINFL, computer=self.pc2)

        rows = {row["computer"]: row for row in bookings.zone_computers(self.schedule, self.zone.pk)["results"]}

        self.assertEqual(set(rows), {self.pc1.pk, self.pc2.pk, self.pc3.pk})
        self.assertIsNone(rows[self.pc1.pk]["seat"])
        self.assertIsNotNone(rows[self.pc2.pk]["seat"])
        self.assertEqual(rows[self.pc2.pk]["lock"], "booked")

    def test_auto_assign_respects_a_curated_session(self):
        """Avtomatik biriktirish qoldirilgan zaxira mashinani qaytarib qo'shmaydi."""
        bookings.update_session_computers(self.schedule, self.zone.pk, add=[self.pc3.pk])

        booking, _ = bookings.assign(self.schedule, PINFL, zone_id=self.zone.pk)

        self.assertEqual(booking.computer, self.pc3)
        self.assertEqual(self._seated(), {self.pc3.pk})

    def test_auto_assign_still_builds_an_empty_session(self):
        """Hech kim tuzmagan sessiya — eski xulq: joylar yig'iladi."""
        booking, _ = bookings.assign(self.schedule, PINFL, zone_id=self.zone.pk)
        self.assertEqual(booking.computer, self.pc1)
        self.assertEqual(len(self._seated()), 3)


class SessionComputersApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.region = factories.make_region()
        self.zone = factories.make_zone(region=self.region)
        self.pc1 = factories.make_computer(zone=self.zone, number=1)
        self.pc2 = factories.make_computer(zone=self.zone, number=2)
        self.schedule = factories.make_schedule(zone=None)
        self.client.force_authenticate(
            factories.make_user(permissions=["bookings.view", "bookings.manage"])
        )

    def test_list_then_update(self):
        response = self.client.get(URL, {"schedule": self.schedule.pk, "zone": self.zone.pk})
        self.assertEqual(response.status_code, 200, response.content)
        rows = response.json()["data"]["results"]
        self.assertEqual([row["number"] for row in rows], [1, 2])
        self.assertTrue(all(row["seat"] is None for row in rows))

        response = self.client.post(
            URL, {"schedule": self.schedule.pk, "zone": self.zone.pk, "add": [self.pc2.pk]}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["data"]["added"], 1)

        response = self.client.post(
            URL, {"schedule": self.schedule.pk, "zone": self.zone.pk, "remove": [self.pc2.pk]}, format="json"
        )
        self.assertEqual(response.json()["data"]["removed"], 1)

    def test_empty_change_is_400(self):
        response = self.client.post(
            URL, {"schedule": self.schedule.pk, "zone": self.zone.pk}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_zone_is_required(self):
        response = self.client.get(URL, {"schedule": self.schedule.pk})
        self.assertEqual(response.status_code, 400)

    def test_region_admin_cannot_touch_other_region(self):
        other = factories.make_computer(number=7)
        self.client.force_authenticate(
            factories.make_user(permissions=["bookings.view", "bookings.manage"], region=self.region)
        )
        rows = self.client.get(
            URL, {"schedule": self.schedule.pk, "zone": other.zone_id}
        ).json()["data"]["results"]
        self.assertEqual(rows, [])

        result = self.client.post(
            URL, {"schedule": self.schedule.pk, "zone": other.zone_id, "add": [other.pk]}, format="json"
        ).json()["data"]
        self.assertEqual(result["added"], 0)
        self.assertFalse(ComputerBooking.objects.filter(computer=other).exists())

    def test_view_permission_cannot_update(self):
        self.client.force_authenticate(factories.make_user(permissions=["bookings.view"]))
        response = self.client.post(
            URL, {"schedule": self.schedule.pk, "zone": self.zone.pk, "add": [self.pc1.pk]}, format="json"
        )
        self.assertEqual(response.status_code, 403)
