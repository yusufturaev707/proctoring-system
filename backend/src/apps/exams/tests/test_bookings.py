"""
Kompyuter bronlari: servis, panel API va JSHSHIR tekshiruvi.

Eng qimmat xatolar — ikkita va testlar aynan ularni ushlaydi:

  * talabgor NOTO'G'RI stolda imtihonni boshlab yuboradi (bayonnomada
    boshqa kompyuter, boshqa kamera, boshqa PiP);
  * bron yuritilmaydigan sessiya yangi qoida tufayli TO'XTAB qoladi
    (mavjud o'rnatishlar imtihon kuni hech kimni kiritmaydi).
"""

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.common.exceptions import (
    SeatInUse,
    SeatNotBooked,
    SeatOutOfService,
    SeatUnavailable,
    WrongComputer,
)
from apps.common.tests.utils import RedisStateMixin
from apps.controls.models import AllowedPublicIp
from apps.exams import bookings
from apps.exams.models import ComputerBooking
from apps.proctoring.tests import factories
from apps.proctoring.tests.test_client_api import bearer

PINFL = "30000000000001"
OTHER = "30000000000002"


class SeatServiceTests(TestCase):
    def setUp(self):
        self.zone = factories.make_zone()
        self.pc1 = factories.make_computer(zone=self.zone, number=1)
        self.pc2 = factories.make_computer(zone=self.zone, number=2)
        self.schedule = factories.make_schedule(zone=self.zone)

    def test_generate_is_idempotent_and_skips_decommissioned(self):
        factories.make_computer(zone=self.zone, number=3, is_active=False)
        factories.make_computer(number=4)  # boshqa bino

        self.assertEqual(bookings.generate_seats(self.schedule), {"created": 2, "total": 2})
        self.assertEqual(bookings.generate_seats(self.schedule), {"created": 0, "total": 2})

    def test_global_schedule_covers_every_building(self):
        """Umumiy sessiya (`zone=NULL`) — barcha viloyatlarning barcha binolari."""
        factories.make_computer(number=9)
        schedule = factories.make_schedule(zone=None)
        self.assertEqual(bookings.generate_seats(schedule)["created"], 3)

    def test_auto_assign_takes_lowest_free_working_number(self):
        bookings.generate_seats(self.schedule)
        ComputerBooking.objects.filter(computer=self.pc1).update(is_active=False)

        booking, previous = bookings.assign(self.schedule, PINFL)

        self.assertEqual(booking.computer, self.pc2)
        self.assertIsNone(previous)
        self.assertTrue(booking.is_booked)

    def test_auto_assign_is_idempotent(self):
        """Tashqi tizim so'rovni takrorlasa ikkinchi joy band bo'lmaydi."""
        first, _ = bookings.assign(self.schedule, PINFL)
        second, _ = bookings.assign(self.schedule, PINFL)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(ComputerBooking.objects.filter(is_booked=True).count(), 1)

    def test_explicit_assign_moves_candidate(self):
        bookings.assign(self.schedule, PINFL, computer=self.pc1)

        booking, previous = bookings.assign(self.schedule, PINFL, computer=self.pc2)

        self.assertEqual(previous, self.pc1.pk)
        self.assertEqual(booking.computer, self.pc2)
        old = ComputerBooking.objects.get(schedule=self.schedule, computer=self.pc1)
        self.assertFalse(old.is_booked)
        self.assertEqual(old.pinfl, "")

    def test_busy_or_broken_seat_is_rejected(self):
        bookings.assign(self.schedule, PINFL, computer=self.pc1)
        with self.assertRaises(SeatUnavailable):
            bookings.assign(self.schedule, OTHER, computer=self.pc1)

        ComputerBooking.objects.create(schedule=self.schedule, computer=self.pc2, is_active=False)
        with self.assertRaises(SeatUnavailable):
            bookings.assign(self.schedule, OTHER, computer=self.pc2)

    def test_computer_outside_schedule_zone_is_rejected(self):
        stranger = factories.make_computer(number=7)
        with self.assertRaises(SeatUnavailable):
            bookings.assign(self.schedule, PINFL, computer=stranger)

    def test_invalid_pinfl_is_rejected(self):
        with self.assertRaises(Exception) as ctx:
            bookings.assign(self.schedule, "123")
        self.assertEqual(getattr(ctx.exception.detail, "code", None), "invalid_pinfl")

    def test_database_forbids_two_seats_for_one_candidate(self):
        """Ilova tekshiruvi parallel so'rovda o'tib ketsa ham baza ushlaydi."""
        ComputerBooking.objects.create(
            schedule=self.schedule, computer=self.pc1, is_booked=True, pinfl=PINFL
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ComputerBooking.objects.create(
                schedule=self.schedule, computer=self.pc2, is_booked=True, pinfl=PINFL
            )

    def test_database_forbids_flag_without_pinfl(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            ComputerBooking.objects.create(schedule=self.schedule, computer=self.pc1, is_booked=True)

    def test_bulk_assign_reports_each_row(self):
        results = bookings.bulk_assign(
            self.schedule,
            [
                {"pinfl": PINFL, "computer": self.pc1.pk},
                {"pinfl": OTHER, "computer": self.pc1.pk},  # band
                {"pinfl": "12"},  # yaroqsiz
            ],
        )
        self.assertEqual([item["ok"] for item in results], [True, False, False])
        self.assertEqual(results[1]["code"], "seat_unavailable")
        self.assertEqual(results[2]["code"], "invalid_pinfl")


class CandidateSeatTests(TestCase):
    """`resolve_candidate_seat` — JSHSHIR tekshiruvidagi qaror."""

    def setUp(self):
        self.zone = factories.make_zone()
        self.pc1 = factories.make_computer(zone=self.zone, number=1)
        self.pc2 = factories.make_computer(zone=self.zone, number=2)
        self.device = factories.make_device(computer=self.pc2)
        self.schedule = factories.make_schedule(zone=self.zone)

    def _resolve(self, pinfl=PINFL, mac="", uuid=""):
        return bookings.resolve_candidate_seat(
            schedule=self.schedule, pinfl=pinfl, device=self.device,
            machine_uuid=uuid, mac_address=mac,
        )

    def test_physical_uuid_decides_the_desk(self):
        """JSHSHIR tekshiruvida "bu mashina" - Machine UUID bo'yicha."""
        bookings.assign(self.schedule, PINFL, computer=self.pc2)
        with self.assertRaises(WrongComputer) as ctx:
            # MAC №2 niki, lekin ona plata №1 niki - UUID hal qiladi.
            self._resolve(uuid=self.pc1.machine_uuid, mac=self.pc2.mac_address)
        self.assertEqual(ctx.exception.extra["current"]["number"], 1)

        seat = self._resolve(uuid=self.pc2.machine_uuid.lower(), mac="00:00:00:00:00:01")
        self.assertEqual(seat["computer_id"], self.pc2.pk)

    def test_unknown_uuid_does_not_fall_back_to_mac_of_uuid_record(self):
        """
        UUID bazada yo'q - MAC faqat UUID'SIZ yozuvda qidiriladi: UUID'i
        boshqa bo'lgan mashina MAC bo'yicha "shu stol" bo'lib qolmasin.
        """
        bookings.assign(self.schedule, PINFL, computer=self.pc2)
        seat = self._resolve(
            uuid="4C4C4544-0038-4A10-805A-C7C04F4B3A77", mac=self.pc1.mac_address
        )
        self.assertEqual(seat["computer_id"], self.pc2.pk)  # qurilma biriktiruvi

    def test_not_enforced_without_any_booking(self):
        """Bron yuritilmaydigan sessiya avvalgidek ishlaydi."""
        self.assertIsNone(self._resolve())

    @override_settings(PROCTORING={**settings.PROCTORING, "REQUIRE_COMPUTER_BOOKING": True})
    def test_required_setting_enforces_empty_schedule(self):
        with self.assertRaises(SeatNotBooked):
            self._resolve()

    def test_unbooked_candidate_is_rejected_once_schedule_uses_bookings(self):
        bookings.assign(self.schedule, OTHER, computer=self.pc1)
        with self.assertRaises(SeatNotBooked):
            self._resolve()

    def test_wrong_computer_says_where_to_go(self):
        bookings.assign(self.schedule, PINFL, computer=self.pc1)

        with self.assertRaises(WrongComputer) as ctx:
            self._resolve()

        extra = ctx.exception.extra
        self.assertEqual(extra["seat"]["number"], 1)
        self.assertEqual(extra["seat"]["zone_name"], self.zone.name)
        self.assertEqual(extra["current"]["number"], 2)
        self.assertNotIn("mac_address", extra["seat"])

    def test_right_computer_returns_seat(self):
        bookings.assign(self.schedule, PINFL, computer=self.pc2)
        seat = self._resolve(mac=self.pc2.mac_address)
        self.assertEqual(seat["computer_id"], self.pc2.pk)

    def test_physical_mac_wins_over_device_binding(self):
        """Qurilma №2 ga biriktirilgan, lekin dastur №1 da ishlayapti."""
        bookings.assign(self.schedule, PINFL, computer=self.pc2)
        with self.assertRaises(WrongComputer) as ctx:
            self._resolve(mac=self.pc1.mac_address)
        self.assertEqual(ctx.exception.extra["current"]["number"], 1)

    def test_right_desk_but_cloned_device_is_not_called_wrong_computer(self):
        """
        Talabgor to'g'ri stolda (MAC mos), qurilma boshqa kompyuterga
        biriktirilgan — "boshqa kompyuterga boring" deyish noto'g'ri.
        """
        bookings.assign(self.schedule, PINFL, computer=self.pc1)
        with self.assertRaises(Exception) as ctx:
            self._resolve(mac=self.pc1.mac_address.lower().replace(":", "-"))
        self.assertNotIsInstance(ctx.exception, WrongComputer)
        self.assertEqual(ctx.exception.detail.code, "device_binding_mismatch")

    def test_broken_seat_is_reported_before_location(self):
        bookings.assign(self.schedule, PINFL, computer=self.pc1)
        ComputerBooking.objects.filter(computer=self.pc1).update(is_active=False)
        with self.assertRaises(SeatOutOfService):
            self._resolve()

    def test_mac_from_another_building_is_ignored(self):
        """
        MAC faqat BINO ichida qidiriladi (`verify_machine` bilan bir xil).

        Boshqa binodagi mashina bu joy bo'la olmaydi va uni "bu mashina"
        deb ko'rsatish operatorga begona binoning kompyuterini aytardi.
        Topilmasa qurilma biriktiruvi ishlaydi.
        """
        stranger = factories.make_computer(number=5)  # boshqa bino
        bookings.assign(self.schedule, PINFL, computer=self.pc2)

        seat = self._resolve(mac=stranger.mac_address)

        self.assertEqual(seat["computer_id"], self.pc2.pk)

    def test_without_device_searches_the_seat_building(self):
        """
        Qurilma yo'q (`REQUIRE_DEVICE_ID=false`) — qidiruv talabgor
        joyining binosida. `DeviceToken.computer` NOT NULL, ya'ni
        "biriktirilmagan qurilma" amalda faqat shu holat.
        """
        self.device = None
        bookings.assign(self.schedule, PINFL, computer=self.pc1)

        seat = self._resolve(mac=self.pc1.mac_address)

        self.assertEqual(seat["computer_id"], self.pc1.pk)


class LookupEndpointSeatTests(TestCase):
    """HTTP darajasi: joy `error.details` da TUZILGAN holda keladi."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient()
        self.zone = factories.make_zone()
        self.pc1 = factories.make_computer(zone=self.zone, number=1)
        self.pc2 = factories.make_computer(zone=self.zone, number=2)
        self.device = factories.make_device(computer=self.pc2)
        self.exam = factories.make_exam()
        self.schedule = factories.make_schedule(exam=self.exam, zone=self.zone)
        AllowedPublicIp.objects.create(ip_address="8.8.8.8", zone=self.zone)
        self.operator = factories.make_user(permissions=["client.operate"])

    def _lookup(self, pinfl=PINFL, mac=None, uuid=None):
        payload = {"pinfl": pinfl, "exam_id": self.exam.pk}
        if mac:
            payload["mac_address"] = mac
        if uuid:
            payload["machine_uuid"] = uuid
        return self.client.post(
            reverse("client-candidate-lookup"),
            payload,
            format="json",
            HTTP_AUTHORIZATION=bearer(self.operator),
            HTTP_X_DEVICE_ID=self.device.device_id,
            REMOTE_ADDR="8.8.8.8",
        )

    def test_wrong_computer_details(self):
        bookings.assign(self.schedule, PINFL, computer=self.pc1)

        response = self._lookup(mac=self.pc2.mac_address)

        self.assertEqual(response.status_code, 409, response.content)
        error = response.json()["error"]
        self.assertEqual(error["code"], "wrong_computer")
        self.assertEqual(error["details"]["seat"]["number"], 1)
        self.assertIn("№1", error["message"])

    def test_success_carries_seat(self):
        bookings.assign(self.schedule, PINFL, computer=self.pc2)

        response = self._lookup(mac=self.pc2.mac_address)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["data"]["seat"]["number"], 2)

    def test_wrong_computer_by_machine_uuid(self):
        bookings.assign(self.schedule, PINFL, computer=self.pc2)

        response = self._lookup(uuid=self.pc1.machine_uuid)

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["error"]["details"]["current"]["number"], 1)

    def test_malformed_machine_uuid_is_400(self):
        response = self._lookup(uuid="not-a-uuid")
        self.assertEqual(response.status_code, 400)


class BookingApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.region = factories.make_region()
        self.zone = factories.make_zone(region=self.region)
        self.pc1 = factories.make_computer(zone=self.zone, number=1)
        self.pc2 = factories.make_computer(zone=self.zone, number=2)
        self.schedule = factories.make_schedule(zone=None)
        self.admin = factories.make_user(permissions=["bookings.view", "bookings.manage"])
        self.client.force_authenticate(self.admin)

    def test_generate_assign_release_flow(self):
        response = self.client.post(
            "/api/v1/computer-bookings/generate/", {"schedule": self.schedule.pk}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["data"]["created"], 2)

        response = self.client.post(
            "/api/v1/computer-bookings/assign/",
            {"schedule": self.schedule.pk, "pinfl": PINFL},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        row = response.json()["data"]
        self.assertEqual(row["computer_number"], 1)
        self.assertEqual(row["pinfl"], PINFL)

        stats = self.client.get(
            "/api/v1/computer-bookings/stats/", {"schedule": self.schedule.pk}
        ).json()["data"]
        self.assertEqual((stats["total"], stats["booked"], stats["free"]), (2, 1, 1))

        response = self.client.post(f"/api/v1/computer-bookings/{row['id']}/release/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["data"]["is_booked"])

    def test_patch_cannot_write_pinfl(self):
        """Biriktirish faqat `assign/` orqali — PATCH tekshiruvni chetlab o'tmaydi."""
        booking = ComputerBooking.objects.create(schedule=self.schedule, computer=self.pc1)
        response = self.client.patch(
            f"/api/v1/computer-bookings/{booking.pk}/",
            {"pinfl": PINFL, "is_booked": True, "is_active": False},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        booking.refresh_from_db()
        self.assertEqual((booking.pinfl, booking.is_booked, booking.is_active), ("", False, False))

    def test_booked_seat_cannot_be_deleted(self):
        booking, _ = bookings.assign(self.schedule, PINFL, computer=self.pc1)
        response = self.client.delete(f"/api/v1/computer-bookings/{booking.pk}/")
        self.assertEqual(response.status_code, 409)

    def test_region_admin_sees_only_own_region(self):
        other = factories.make_computer(number=5)
        ComputerBooking.objects.create(schedule=self.schedule, computer=other)
        ComputerBooking.objects.create(schedule=self.schedule, computer=self.pc1)
        regional = factories.make_user(
            permissions=["bookings.view", "bookings.manage"], region=self.region
        )
        self.client.force_authenticate(regional)

        rows = self.client.get("/api/v1/computer-bookings/").json()["data"]
        results = rows["results"] if isinstance(rows, dict) else rows
        self.assertEqual([row["computer"] for row in results], [self.pc1.pk])

        response = self.client.post(
            "/api/v1/computer-bookings/assign/",
            {"schedule": self.schedule.pk, "pinfl": PINFL, "computer": other.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 409)

    def test_view_permission_cannot_assign(self):
        self.client.force_authenticate(factories.make_user(permissions=["bookings.view"]))
        response = self.client.post(
            "/api/v1/computer-bookings/assign/",
            {"schedule": self.schedule.pk, "pinfl": PINFL},
            format="json",
        )
        self.assertEqual(response.status_code, 403)


class ReleaseAfterFinishTests(RedisStateMixin, TestCase):
    """
    Talabgor «Yakunlash» ni bosdi — joy keyingi talabgorga bo'shaydi.

    Faqat shu yo'l: dasturdan chiqish, tok o'chishi (expired) va
    chetlashtirish joyni band QOLDIRADI — talabgor o'sha stolga qaytishi
    yoki administrator qaror qilishi kerak.
    """

    def setUp(self):
        super().setUp()
        self.zone = factories.make_zone()
        self.pc1 = factories.make_computer(zone=self.zone, number=1)
        self.pc2 = factories.make_computer(zone=self.zone, number=2)
        self.device = factories.make_device(computer=self.pc1)
        self.schedule = factories.make_schedule(zone=self.zone)
        bookings.assign(self.schedule, PINFL, computer=self.pc1)
        self.session = factories.make_session(
            device=self.device, exam=self.schedule.exam, schedule=self.schedule, pinfl=PINFL
        )

    def _seat(self, computer=None):
        return ComputerBooking.objects.get(schedule=self.schedule, computer=computer or self.pc1)

    def test_completed_finish_frees_the_seat_for_the_next_candidate(self):
        from apps.proctoring.services import session as session_service

        session_service.finish_session(self.session, completed=True)

        seat = self._seat()
        self.assertFalse(seat.is_booked)
        self.assertEqual(seat.pinfl, "")
        self.assertEqual(seat.finished_count, 1)
        self.assertIsNotNone(seat.last_finished_at)
        self.session.refresh_from_db()
        self.assertEqual(self.session.meta["seat_release"]["seat"]["number"], 1)
        # Avtomatik biriktirish bo'shagan joyni qaytadan beradi.
        booking, _ = bookings.assign(self.schedule, OTHER)
        self.assertEqual(booking.computer, self.pc1)

    def test_finish_without_completed_keeps_the_seat(self):
        """Dasturdan chiqish (Ctrl+Q) — talabgor testni topshirmagan."""
        from apps.proctoring.services import session as session_service

        session_service.finish_session(self.session, reason="Dasturdan chiqildi")

        seat = self._seat()
        self.assertTrue(seat.is_booked)
        self.assertEqual(seat.finished_count, 0)

    def test_expired_and_client_side_termination_keep_the_seat(self):
        """
        Tok o'chishi — talabgor o'sha stolga qaytadi; client'dagi "shaxs
        rad etildi" (`release_seat` yo'q) — administrator qarori emas.
        """
        from apps.proctoring.services import session as session_service

        session_service.expire_session(self.session)
        self.assertTrue(self._seat().is_booked)

        bookings.assign(self.schedule, OTHER, computer=self.pc2)
        other = factories.make_session(
            device=factories.make_device(computer=self.pc2),
            exam=self.schedule.exam, schedule=self.schedule, pinfl=OTHER,
        )
        session_service.terminate_session(other, reason="test")
        self.assertTrue(self._seat(self.pc2).is_booked)

    def test_admin_termination_frees_the_seat(self):
        from apps.proctoring.services import session as session_service

        session_service.terminate_session(self.session, reason="test", release_seat=True)

        seat = self._seat()
        self.assertFalse(seat.is_booked)
        self.assertEqual(seat.finished_count, 1)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, "terminated")
        self.assertEqual(self.session.meta["seat_release"]["by"], "terminate")
        # Chetlashtirilgan talabgor qayta kira olmaydi — bron tekshiruvi
        # oxirgi joy bo'shagach ham ishlaydi.
        with self.assertRaises(SeatNotBooked):
            bookings.resolve_candidate_seat(schedule=self.schedule, pinfl=PINFL, device=self.device)

    def test_finish_without_booking_is_not_an_error(self):
        from apps.proctoring.services import session as session_service

        ComputerBooking.objects.filter(pk=self._seat().pk).update(
            is_booked=False, pinfl="", booked_at=None
        )
        session_service.finish_session(self.session, completed=True)

        self.session.refresh_from_db()
        self.assertEqual(self.session.status, "finished")
        self.assertNotIn("seat_release", self.session.meta)

    def test_enforcement_survives_the_last_candidate_finishing(self):
        """
        Oxirgi talabgor yakunlagach ham bron tekshiruvi O'CHMAYDI.

        Aks holda yakunlagan talabgor ham, bronsiz begona ham istalgan
        stolda qayta kira olardi.
        """
        from apps.proctoring.services import session as session_service

        session_service.finish_session(self.session, completed=True)

        self.assertFalse(ComputerBooking.objects.filter(is_booked=True).exists())
        self.assertTrue(bookings.bookings_enforced(self.schedule))
        with self.assertRaises(SeatNotBooked):
            bookings.resolve_candidate_seat(schedule=self.schedule, pinfl=PINFL, device=self.device)

    def test_endpoint_releases_only_with_completed_flag(self):
        from apps.proctoring.services import session as session_service

        client = APIClient()
        operator = factories.make_user(permissions=["client.operate"])
        token = session_service.issue_session_token(self.session)

        response = client.post(
            reverse("client-session-finish"),
            {"reason": "Operator yakunladi", "completed": True},
            format="json",
            HTTP_AUTHORIZATION=bearer(operator),
            HTTP_X_DEVICE_ID=self.device.device_id,
            HTTP_X_PROCTORING_SESSION=token,
        )

        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()["data"]
        self.assertTrue(data["seat_released"])
        self.assertEqual(data["seat"]["number"], 1)
        self.assertFalse(self._seat().is_booked)
        from apps.proctoring.models import AuditLog

        audit = AuditLog.objects.get(object_type="ComputerBooking")
        self.assertEqual(audit.meta["by"], "session_finish")


class SeatInUseTests(RedisStateMixin, TestCase):
    """
    Talabgor imtihonda — panel joyini bo'shata ham, ko'chira ham olmaydi.

    Yagona yo'l — sessiya: «Yakunlash» yoki administrator chetlashtirishi.
    """

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.zone = factories.make_zone()
        self.pc1 = factories.make_computer(zone=self.zone, number=1)
        self.pc2 = factories.make_computer(zone=self.zone, number=2)
        self.schedule = factories.make_schedule(zone=self.zone)
        self.booking, _ = bookings.assign(self.schedule, PINFL, computer=self.pc1)
        self.session = factories.make_session(
            device=factories.make_device(computer=self.pc1),
            exam=self.schedule.exam, schedule=self.schedule, pinfl=PINFL,
        )
        self.admin = factories.make_user(
            permissions=["bookings.view", "bookings.manage", "sessions.view", "sessions.terminate"]
        )
        self.client.force_authenticate(self.admin)

    def test_release_is_refused_for_every_open_status(self):
        """`ready` ham: kuzatuv rad etilgan talabgor FaceID sahifasida kutadi."""
        for status in ("ready", "in_progress", "technical_problem"):
            self.session.status = status
            self.session.save(update_fields=["status"])
            with self.assertRaises(SeatInUse):
                bookings.release(self.booking)
        self.booking.refresh_from_db()
        self.assertTrue(self.booking.is_booked)

    def test_release_is_allowed_after_the_session_ends(self):
        for status in ("finished", "expired", "terminated"):
            bookings.assign(self.schedule, PINFL, computer=self.pc1)
            self.session.status = status
            self.session.save(update_fields=["status"])
            self.booking.refresh_from_db()
            bookings.release(self.booking)
            self.booking.refresh_from_db()
            self.assertFalse(self.booking.is_booked, status)

    def test_move_is_refused_during_the_exam(self):
        with self.assertRaises(SeatInUse):
            bookings.assign(self.schedule, PINFL, computer=self.pc2)
        self.assertTrue(ComputerBooking.objects.get(pk=self.booking.pk).is_booked)

    def test_panel_release_returns_409_seat_in_use(self):
        response = self.client.post(f"/api/v1/computer-bookings/{self.booking.pk}/release/")

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["error"]["code"], "seat_in_use")
        self.assertTrue(ComputerBooking.objects.get(pk=self.booking.pk).is_booked)

    def test_bulk_move_reports_the_row(self):
        response = self.client.post(
            "/api/v1/computer-bookings/bulk-assign/",
            {"schedule": self.schedule.pk, "items": [{"pinfl": PINFL, "computer": self.pc2.pk}]},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        row = response.json()["data"]["results"][0]
        self.assertEqual((row["ok"], row["code"]), (False, "seat_in_use"))

    def test_panel_terminate_releases_the_seat(self):
        response = self.client.post(
            f"/api/v1/sessions/{self.session.pk}/terminate/",
            {"reason": "Qoidabuzarlik"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        booking = ComputerBooking.objects.get(pk=self.booking.pk)
        self.assertFalse(booking.is_booked)
        self.assertEqual(booking.finished_count, 1)
        from apps.proctoring.models import AuditLog

        audit = AuditLog.objects.get(action="session_terminate")
        self.assertTrue(audit.meta["seat_released"])
