"""
Erkin joylashuv (`Setting.is_booking=False`): talabgor sessiyaga
kiritilgan istalgan bo'sh kompyuterda, joy test boshlanganda yoziladi.

Qo'riqlanadigan qoidalar — ular buzilsa oqibati jim:

  * faqat SESSIYAGA KIRITILGAN, ishchi, bo'sh stol (bazada borligi yetmaydi);
  * joy JSHSHIR tekshiruvida EMAS, `proctoring/start/` da band qilinadi —
    FaceID'dan o'tolmagan talabgor stolni egallab qolmasin;
  * band qilingandan keyin hammasi bron rejimidagidek (o'sha stolga
    bog'langan, «Yakunlash»/chetlashtirishda bo'shaydi);
  * yakunlagan talabgor qo'shni stolda qaytadan boshlay olmaydi;
  * oldindan biriktirilgan talabgor va uning joyi hurmat qilinadi;
  * bron rejimi (standart) o'zgarmagan.
"""

from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.common.exceptions import (
    CandidateAlreadyFinished,
    ComputerBusy,
    ComputerNotInSchedule,
    ComputerOutOfService,
    ExamScheduleMissing,
    SeatNotBooked,
    WrongComputer,
)
from apps.common.tests.utils import RedisStateMixin
from apps.controls.models import Setting
from apps.exams import bookings
from apps.exams.models import ComputerBooking
from apps.proctoring.models import AuditLog
from apps.proctoring.tests import factories
from apps.proctoring.tests.test_camera_api import CameraApiTestCase

PINFL = "30000000000001"
OTHER = "30000000000002"


class FreeSeatResolveTests(TestCase):
    """`resolve_candidate_seat(booking_required=False)` — JSHSHIR tekshiruvi."""

    def setUp(self):
        self.zone = factories.make_zone()
        self.pc1 = factories.make_computer(zone=self.zone, number=1)
        self.pc2 = factories.make_computer(zone=self.zone, number=2)
        self.device = factories.make_device(computer=self.pc2)
        self.schedule = factories.make_schedule(zone=self.zone)
        bookings.generate_seats(self.schedule)

    def _resolve(self, pinfl=PINFL, *, uuid=None, mac=None, required=False):
        return bookings.resolve_candidate_seat(
            schedule=self.schedule, pinfl=pinfl, device=self.device,
            machine_uuid=self.pc2.machine_uuid if uuid is None else uuid,
            mac_address=self.pc2.mac_address if mac is None else mac,
            booking_required=required,
        )

    def test_free_working_seat_is_offered_but_not_taken(self):
        seat = self._resolve()

        self.assertEqual(seat["computer_id"], self.pc2.pk)
        self.assertTrue(seat["auto_assign"])
        # JSHSHIR tekshiruvi joyni BAND QILMAYDI.
        self.assertFalse(ComputerBooking.objects.filter(is_booked=True).exists())

    def test_computer_outside_the_schedule_is_rejected(self):
        """Bazada bor, lekin sessiyaga kiritilmagan stol yaroqsiz."""
        ComputerBooking.objects.filter(schedule=self.schedule, computer=self.pc2).delete()
        with self.assertRaises(ComputerNotInSchedule) as ctx:
            self._resolve()
        self.assertEqual(ctx.exception.extra["current"]["number"], 2)

    def test_schedule_without_seats_admits_nobody(self):
        ComputerBooking.objects.filter(schedule=self.schedule).delete()
        with self.assertRaises(ComputerNotInSchedule):
            self._resolve()

    def test_unknown_machine_is_rejected(self):
        with self.assertRaises(ComputerNotInSchedule) as ctx:
            self._resolve(uuid="4C4C4544-0038-4A10-805A-C7C04F4B3A77", mac="00:E0:4C:68:01:02")
        self.assertIsNone(ctx.exception.extra["current"])

    def test_decommissioned_computer_is_rejected_even_with_old_seat(self):
        type(self.pc2).objects.filter(pk=self.pc2.pk).update(is_active=False)
        with self.assertRaises(ComputerNotInSchedule):
            self._resolve()

    def test_broken_seat_is_rejected(self):
        ComputerBooking.objects.filter(computer=self.pc2).update(is_active=False)
        with self.assertRaises(ComputerOutOfService):
            self._resolve()

    def test_seat_of_another_candidate_is_busy(self):
        bookings.assign(self.schedule, OTHER, computer=self.pc2)
        with self.assertRaises(ComputerBusy) as ctx:
            self._resolve()
        self.assertNotIn(OTHER, str(ctx.exception.detail))

    def test_pre_assigned_candidate_still_goes_to_own_seat(self):
        bookings.assign(self.schedule, PINFL, computer=self.pc1)
        with self.assertRaises(WrongComputer) as ctx:
            self._resolve()
        self.assertEqual(ctx.exception.extra["seat"]["number"], 1)

    def test_pre_assigned_seat_here_is_a_regular_seat(self):
        bookings.assign(self.schedule, PINFL, computer=self.pc2)
        seat = self._resolve()
        self.assertEqual(seat["computer_id"], self.pc2.pk)
        self.assertNotIn("auto_assign", seat)

    def test_cloned_device_is_not_this_desk(self):
        """Juftlik №1 niki, qurilma №2 ga biriktirilgan — administrator ishi."""
        with self.assertRaises(Exception) as ctx:
            self._resolve(uuid=self.pc1.machine_uuid, mac=self.pc1.mac_address)
        self.assertEqual(ctx.exception.detail.code, "device_binding_mismatch")

    def test_finished_candidate_cannot_restart_on_another_desk(self):
        """
        «Yakunlash» joyni bo'shatadi — erkin rejimda bu qayta kirish
        imkoni bo'lib qolmasligi kerak (bron rejimida `seat_not_booked`).
        """
        session = factories.make_session(
            device=self.device, exam=self.schedule.exam, schedule=self.schedule, pinfl=PINFL,
            meta={"seat_release": {"by": "finish"}},
        )
        self.assertIsNotNone(session)
        with self.assertRaises(CandidateAlreadyFinished):
            self._resolve()
        # Administrator qarori — qayta biriktirish — yo'lni ochadi.
        bookings.assign(self.schedule, PINFL, computer=self.pc2)
        self.assertEqual(self._resolve()["computer_id"], self.pc2.pk)

    def test_without_schedule_free_seating_is_refused(self):
        """Joylar test sessiyasida - sessiyasiz erkin joylashuv ishlay olmaydi."""
        with self.assertRaises(ExamScheduleMissing):
            bookings.resolve_candidate_seat(
                schedule=None, pinfl=PINFL, device=self.device, booking_required=False
            )

    def test_without_schedule_soft_booking_mode_is_skipped(self):
        """Ikkala qoida yumshoq (bron rejimi, `REQUIRE_COMPUTER_BOOKING=false`)."""
        self.assertIsNone(
            bookings.resolve_candidate_seat(schedule=None, pinfl=PINFL, device=self.device)
        )

    def test_without_schedule_required_booking_is_not_bypassed(self):
        """
        Ilgari jadval yo'qligi `REQUIRE_COMPUTER_BOOKING=true` ni ham jimgina
        o'chirardi va talabgor istalgan stoldan kirardi.
        """
        with patch.dict(settings.PROCTORING, {"REQUIRE_COMPUTER_BOOKING": True}):
            with self.assertRaises(ExamScheduleMissing):
                bookings.resolve_candidate_seat(schedule=None, pinfl=PINFL, device=self.device)

    def test_booking_mode_is_unchanged(self):
        """Standart rejim: biriktirish yo'q — tekshiruv o'chiq; bor — majburiy."""
        self.assertIsNone(self._resolve(required=True))
        bookings.assign(self.schedule, OTHER, computer=self.pc1)
        with self.assertRaises(SeatNotBooked):
            self._resolve(required=True)


class ClaimForSessionTests(RedisStateMixin, TestCase):
    """`claim_for_session` — joy test boshlanganda yoziladi."""

    def setUp(self):
        super().setUp()
        self.zone = factories.make_zone()
        self.pc1 = factories.make_computer(zone=self.zone, number=1)
        self.device = factories.make_device(computer=self.pc1)
        self.schedule = factories.make_schedule(zone=self.zone)
        bookings.generate_seats(self.schedule)
        self.session = factories.make_session(
            device=self.device, exam=self.schedule.exam, schedule=self.schedule, pinfl=PINFL,
            meta={"seat": {**bookings.computer_payload(self.pc1), "auto_assign": True}},
        )

    def _seat(self):
        return ComputerBooking.objects.get(schedule=self.schedule, computer=self.pc1)

    def test_claim_books_the_seat_and_is_idempotent(self):
        first = bookings.claim_for_session(self.session)
        again = bookings.claim_for_session(self.session)

        self.assertEqual(first.pk, again.pk)
        seat = self._seat()
        self.assertTrue(seat.is_booked)
        self.assertEqual(seat.pinfl, PINFL)
        self.assertIsNone(seat.booked_by)

    def test_session_from_booking_mode_claims_nothing(self):
        self.session.meta = {"seat": bookings.computer_payload(self.pc1)}
        self.assertIsNone(bookings.claim_for_session(self.session))
        self.assertFalse(self._seat().is_booked)

    def test_seat_taken_meanwhile_is_refused(self):
        bookings.assign(self.schedule, OTHER, computer=self.pc1)
        with self.assertRaises(ComputerBusy):
            bookings.claim_for_session(self.session)

    def test_seat_broken_meanwhile_is_refused(self):
        ComputerBooking.objects.filter(computer=self.pc1).update(is_active=False)
        with self.assertRaises(ComputerOutOfService):
            bookings.claim_for_session(self.session)

    def test_candidate_moved_by_admin_meanwhile_is_refused(self):
        pc2 = factories.make_computer(zone=self.zone, number=2)
        bookings.assign(self.schedule, PINFL, computer=pc2)
        with self.assertRaises(WrongComputer) as ctx:
            bookings.claim_for_session(self.session)
        self.assertEqual(ctx.exception.extra["seat"]["number"], 2)

    def test_claimed_seat_follows_booking_release_rules(self):
        """Band qilingandan keyin — bron rejimidagi bo'shatish qoidalari."""
        from apps.proctoring.services import session as session_service

        bookings.claim_for_session(self.session)
        session_service.finish_session(self.session, reason="Dasturdan chiqildi")
        self.assertTrue(self._seat().is_booked)

        self.session.refresh_from_db()
        self.session.status = "in_progress"
        self.session.finished_at = None
        self.session.save(update_fields=["status", "finished_at"])
        session_service.finish_session(self.session, completed=True)
        seat = self._seat()
        self.assertFalse(seat.is_booked)
        self.assertEqual(seat.finished_count, 1)
        # Yakunlagan talabgor qayta kira olmaydi.
        with self.assertRaises(CandidateAlreadyFinished):
            bookings.resolve_candidate_seat(
                schedule=self.schedule, pinfl=PINFL, device=self.device,
                machine_uuid=self.pc1.machine_uuid, mac_address=self.pc1.mac_address,
                booking_required=False,
            )


class FreeSeatingStartApiTests(CameraApiTestCase):
    """`proctoring/start/` — joy kuzatuv bilan BITTA tranzaksiyada."""

    def setUp(self):
        super().setUp()
        self.schedule = factories.make_schedule(zone=self.zone)
        bookings.generate_seats(self.schedule)
        self.session = factories.make_session(
            device=self.device, computer=self.computer,
            exam=self.schedule.exam, schedule=self.schedule, pinfl=PINFL,
            status="ready",
            meta={"seat": {**bookings.computer_payload(self.computer), "auto_assign": True}},
        )
        from apps.proctoring.services import session as session_service

        self.token = session_service.issue_session_token(self.session)

    def _start(self):
        from apps.proctoring.tests.test_client_api import bearer

        # Kamera darvozasi bu testlarning mavzusi emas.
        with patch.dict(settings.PROCTORING, {"REQUIRE_CAMERA_CHECK": False}):
            return self.client.post(
                reverse("client-proctoring-start"),
                {},
                format="json",
                HTTP_AUTHORIZATION=bearer(self.user),
                HTTP_X_DEVICE_ID=self.device.device_id,
                HTTP_X_PROCTORING_SESSION=self.token,
                REMOTE_ADDR="8.8.8.8",
            )

    def test_start_books_the_seat_with_audit(self):
        response = self._start()

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["data"]["seat"]["computer_id"], self.computer.pk)
        booking = ComputerBooking.objects.get(schedule=self.schedule, computer=self.computer)
        self.assertEqual(booking.pinfl, PINFL)
        self.session.refresh_from_db()
        self.assertEqual(self.session.meta["seat_assigned"]["booking_id"], booking.pk)
        audit = AuditLog.objects.get(object_type="ComputerBooking")
        self.assertEqual(audit.meta["by"], "session_start")

    def test_busy_seat_refuses_start_and_keeps_proctoring_idle(self):
        bookings.assign(self.schedule, OTHER, computer=self.computer)
        state_before = self.session.proctoring_state

        response = self._start()

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["error"]["code"], "computer_busy")
        self.session.refresh_from_db()
        # Tranzaksiya qaytdi: kuzatuv holati ham o'zgarmagan, sessiya tirik.
        self.assertEqual(self.session.proctoring_state, state_before)
        self.assertEqual(self.session.status, "ready")


class FreeSeatingLookupTests(TestCase):
    """JSHSHIR tekshiruvi profilga qaraydi va joyni sessiyaga muzlatadi."""

    def setUp(self):
        from apps.controls.models import AllowedPublicIp
        from rest_framework.test import APIClient

        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient()
        self.zone = factories.make_zone()
        self.pc1 = factories.make_computer(zone=self.zone, number=1)
        self.device = factories.make_device(computer=self.pc1)
        setting = factories.make_setting(is_booking=False)
        self.exam = factories.make_exam(setting=setting)
        self.schedule = factories.make_schedule(exam=self.exam, zone=self.zone)
        AllowedPublicIp.objects.create(ip_address="8.8.8.8", zone=self.zone)
        self.operator = factories.make_user(permissions=["client.operate"])

    def _lookup(self):
        from apps.common.exceptions import CandidateNotFound
        from apps.proctoring.tests.test_client_api import bearer

        with patch(
            "apps.integrations.exam_site.check_candidate", side_effect=CandidateNotFound()
        ) as check:
            response = self.client.post(
                reverse("client-candidate-lookup"),
                {
                    "pinfl": PINFL, "exam_id": self.exam.pk,
                    "machine_uuid": self.pc1.machine_uuid, "mac_address": self.pc1.mac_address,
                },
                format="json",
                HTTP_AUTHORIZATION=bearer(self.operator),
                HTTP_X_DEVICE_ID=self.device.device_id,
                REMOTE_ADDR="8.8.8.8",
            )
        return response, check

    def test_computer_outside_schedule_stops_before_platform(self):
        response, check = self._lookup()

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["error"]["code"], "computer_not_in_schedule")
        check.assert_not_called()

    def test_seated_candidate_reaches_platform(self):
        bookings.generate_seats(self.schedule)
        response, check = self._lookup()
        self.assertEqual(response.json()["error"]["code"], "candidate_not_found")
        check.assert_called_once()

    def test_exam_without_schedule_stops_before_platform(self):
        """`REQUIRE_EXAM_SCHEDULE=false` jadvalsiz imtihonni o'tkazadi - bron emas."""
        self.schedule.delete()
        with patch.dict(settings.PROCTORING, {"REQUIRE_EXAM_SCHEDULE": False}):
            response, check = self._lookup()

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["error"]["code"], "exam_schedule_missing")
        check.assert_not_called()

    def test_profile_switch_restores_booking_mode(self):
        Setting.objects.filter(pk=self.exam.setting_id).update(is_booking=True)
        cache.clear()
        bookings.assign(self.schedule, OTHER, computer=self.pc1)
        response, _ = self._lookup()
        self.assertEqual(response.json()["error"]["code"], "seat_not_booked")
