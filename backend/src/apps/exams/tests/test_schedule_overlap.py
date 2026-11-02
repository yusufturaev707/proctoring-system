"""
Bitta imtihon seanslarining kirish oynalari kesishmasligi (`exams/schedules.py`).

Kesishsa `candidate/lookup/` birinchi seansni tanlaydi va 2-smena talabgori
1-smenaga tushadi (bron rejimida `seat_not_booked`). Seanslar fixture'da ORM
bilan yaratiladi (tekshiruvsiz, eski ma'lumot kabi) — qoida panel, Django
admin, tiklash va tekshiruv buyrug'i yo'llarida tekshiriladi.
"""

from datetime import datetime, timedelta
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.exams.models import Exam, ExamSchedule
from apps.proctoring.tests import factories
from apps.proctoring.tests.test_client_api import bearer
from apps.regions.models import Region, Zone


class ScheduleOverlapTests(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Toshkent", dtm_id=1, vm_number=1)
        self.zone = Zone.objects.create(region=self.region, name="1-bino", number=1)
        self.other_zone = Zone.objects.create(region=self.region, name="2-bino", number=2)
        self.exam = Exam.objects.create(name="Matematika")
        self.day = timezone.localdate() + timedelta(days=3)
        # 1-smena: 09:00-12:00, kirish 08:00 dan.
        self.first = self._create(9, 12)
        self.client = APIClient()
        admin = factories.make_user(permissions=["exams.view", "exams.manage"], global_role=True)
        self.client.credentials(HTTP_AUTHORIZATION=bearer(admin))

    def _at(self, hours):
        midnight = timezone.make_aware(datetime.combine(self.day, datetime.min.time()))
        return midnight + timedelta(hours=hours)

    def _create(self, start, end, *, zone=None, lead=60, exam=None, **kwargs):
        return ExamSchedule.objects.create(
            exam=exam or self.exam, zone=zone, exam_date=self.day,
            starts_at=self._at(start), ends_at=self._at(end),
            checkin_lead_minutes=lead, **kwargs,
        )

    def _post(self, start, end, *, zone=None, lead=60, exam=None, **extra):
        return self.client.post("/api/v1/exam-schedules/", {
            "exam": (exam or self.exam).pk, "zone": getattr(zone, "pk", None),
            "exam_date": self.day.isoformat(),
            "starts_at": self._at(start).isoformat(),
            "ends_at": self._at(end).isoformat(),
            "checkin_lead_minutes": lead, **extra,
        }, format="json")

    def _patch(self, schedule, data):
        return self.client.patch(f"/api/v1/exam-schedules/{schedule.pk}/", data, format="json")

    # -- panel -------------------------------------------------------------
    def test_overlapping_window_is_rejected(self):
        """2-smena 12:30 da — kirishi 11:30 da ochiladi, 1-smena esa 12:00 gacha."""
        response = self._post(12.5, 15)
        self.assertEqual(response.status_code, 400, response.content)
        message = str(response.json()["error"])
        self.assertIn("kesishadi", message)
        # Nima qilish kerakligini aytadi: 12:00 + 60 daqiqa.
        self.assertIn("13:00", message)

    def test_touching_windows_are_allowed(self):
        """12:00 da tugaydi, 12:00 da ochiladi — kesishma emas."""
        response = self._post(13, 16)
        self.assertEqual(response.status_code, 201, response.content)

    def test_earlier_session_gets_shorten_advice(self):
        """Yangi seans mavjudidan OLDIN bo'lsa — "tugashni qisqartiring"."""
        self.assertEqual(self._post(5, 8).status_code, 201)  # 1-smena kirishi 08:00 — tegadi
        response = self._post(4, 8.5)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("qisqartiring", str(response.json()["error"]))

    def test_smaller_lead_resolves_overlap(self):
        """12:30 seans 30 daqiqa oldin ochilsa — 12:00 da, tegadi."""
        self.assertEqual(self._post(12.5, 15, lead=30).status_code, 201)

    def test_other_exam_is_independent(self):
        other_exam = Exam.objects.create(name="Fizika")
        self.assertEqual(self._post(10, 13, exam=other_exam).status_code, 201)

    def test_zone_scopes_are_independent(self):
        """A variant: bino seansi umumiy seans bilan kesishishi RUXSAT (ataylab ustun)."""
        self.assertEqual(self._post(10, 13, zone=self.zone).status_code, 201)
        # Lekin bitta binoning ikki seansi — kesishma.
        self.assertEqual(self._post(11, 14, zone=self.zone).status_code, 400)
        self.assertEqual(self._post(11, 14, zone=self.other_zone).status_code, 201)

    def test_inactive_and_deleted_do_not_block(self):
        self.first.is_active = False
        self.first.save(update_fields=["is_active"])
        self.assertEqual(self._post(10, 13).status_code, 201)

        exam = Exam.objects.create(name="Kimyo")
        self._create(9, 12, exam=exam).delete()
        self.assertEqual(self._post(10, 13, exam=exam).status_code, 201)

    def test_inactive_new_session_is_not_checked(self):
        self.assertEqual(self._post(10, 13, is_active=False).status_code, 201)

    def test_patch_does_not_compare_with_itself(self):
        response = self._patch(self.first, {"ends_at": self._at(12.5).isoformat()})
        self.assertEqual(response.status_code, 200, response.content)

    def test_patch_into_overlap_is_rejected(self):
        second = self._create(13, 16)
        response = self._patch(second, {"starts_at": self._at(12.5).isoformat()})
        self.assertEqual(response.status_code, 400, response.content)

    def test_patch_lead_into_overlap_is_rejected(self):
        second = self._create(13, 16)
        response = self._patch(second, {"checkin_lead_minutes": 90})
        self.assertEqual(response.status_code, 400, response.content)

    def test_reactivating_into_overlap_is_rejected(self):
        """Nofaolni qayta yoqish (faqat `is_active`) ham tekshiriladi."""
        second = self._create(12.5, 15, is_active=False)
        response = self._patch(second, {"is_active": True})
        self.assertEqual(response.status_code, 400, response.content)

    def test_restore_into_overlap_is_rejected(self):
        """Tiklash serializer'dan o'tmaydi — alohida tekshiriladi."""
        self.first.delete()
        self._create(10, 13)
        response = self.client.post(f"/api/v1/exam-schedules/{self.first.pk}/restore/")
        self.assertEqual(response.status_code, 400, response.content)
        self.first.refresh_from_db()
        self.assertIsNotNone(self.first.deleted_at)

    def test_restore_without_overlap_works(self):
        self.first.delete()
        response = self.client.post(f"/api/v1/exam-schedules/{self.first.pk}/restore/")
        self.assertEqual(response.status_code, 200, response.content)

    def test_overnight_session_is_checked(self):
        """23:00-02:00 seansi bilan ertangi 02:30 seansi (kirish 01:30) kesishadi."""
        exam = Exam.objects.create(name="Tungi")
        self._create(23, 26, exam=exam)
        self.assertEqual(self._post(26.5, 29, exam=exam).status_code, 400)
        self.assertEqual(self._post(27, 29, exam=exam).status_code, 201)

    # -- Django admin ------------------------------------------------------
    def test_model_clean_uses_same_rule(self):
        candidate = ExamSchedule(
            exam=self.exam, exam_date=self.day,
            starts_at=self._at(12.5), ends_at=self._at(15), checkin_lead_minutes=60,
        )
        with self.assertRaises(ValidationError) as ctx:
            candidate.clean()
        self.assertIn("starts_at", ctx.exception.message_dict)
        # Saqlangan qatorni o'zi bilan solishtirmaydi.
        self.first.clean()

    # -- tekshiruv buyrug'i ------------------------------------------------
    def test_audit_command_reports_existing_overlaps(self):
        out = StringIO()
        call_command("audit_schedule_overlaps", stdout=out)
        self.assertIn("Kesishgan seans yo'q", out.getvalue())

        self._create(12.5, 15)  # ORM — tekshiruvsiz, eski ma'lumot kabi
        out = StringIO()
        call_command("audit_schedule_overlaps", stdout=out)
        self.assertIn("Kesishgan juftliklar: 1 ta", out.getvalue())
