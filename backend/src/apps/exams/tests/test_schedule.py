"""
Imtihon jadvali — kirish oynasi.

Nima uchun bu muhim: `candidate/lookup/` faqat ochiq oyna ichida
ishlaydi. Oyna noto'g'ri hisoblansa, JSHSHIR qidiruvi 24/7 ochiq
turadi va endpoint fuqarolarning F.I.Sh. sini qidirish servisiga
aylanadi.

Ikkinchi xavf — handshake va lookup BIR XIL selektordan foydalanishi.
Ular ajralib ketsa, client'ga ko'rsatilgan imtihon keyingi qadamda
rad etiladi va operator sababini topa olmaydi.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.exams import selectors
from apps.exams import services as exam_services
from apps.exams.models import Exam, ExamSchedule
from apps.regions.models import Region, Zone


class ScheduleTestCase(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Toshkent", dtm_id=1, vm_number=1)
        self.zone = Zone.objects.create(region=self.region, name="1-bino", number=1)
        self.other_zone = Zone.objects.create(region=self.region, name="2-bino", number=2)
        self.exam = Exam.objects.create(name="Matematika")
        self.now = timezone.now()

    def _schedule(self, *, starts_in_minutes, duration=180, lead=60, zone=None, active=True):
        starts_at = self.now + timedelta(minutes=starts_in_minutes)
        return ExamSchedule.objects.create(
            exam=self.exam,
            zone=zone,
            exam_date=timezone.localdate(starts_at),
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=duration),
            checkin_lead_minutes=lead,
            is_active=active,
        )


class IsOpenTests(ScheduleTestCase):
    def test_open_during_checkin_window(self):
        """Kirish oynasi imtihondan `lead` daqiqa oldin ochiladi."""
        schedule = self._schedule(starts_in_minutes=30, lead=60)
        self.assertTrue(schedule.is_open(self.now))

    def test_closed_before_checkin_window(self):
        schedule = self._schedule(starts_in_minutes=120, lead=60)
        self.assertFalse(schedule.is_open(self.now))

    def test_open_during_exam(self):
        schedule = self._schedule(starts_in_minutes=-30, duration=180)
        self.assertTrue(schedule.is_open(self.now))

    def test_closed_after_end(self):
        schedule = self._schedule(starts_in_minutes=-300, duration=180)
        self.assertFalse(schedule.is_open(self.now))

    def test_inactive_is_never_open(self):
        schedule = self._schedule(starts_in_minutes=0, active=False)
        self.assertFalse(schedule.is_open(self.now))

    def test_opens_at_property(self):
        schedule = self._schedule(starts_in_minutes=90, lead=45)
        self.assertEqual(schedule.opens_at, schedule.starts_at - timedelta(minutes=45))

    def test_boundaries_are_inclusive(self):
        """
        Chegara ICHIGA kiradi.

        Aks holda aynan oyna ochilgan soniyada kelgan talabgor rad
        etilardi va u buni tushuntira olmasdi.
        """
        schedule = self._schedule(starts_in_minutes=60, lead=60)
        self.assertTrue(schedule.is_open(schedule.opens_at))
        self.assertTrue(schedule.is_open(schedule.ends_at))


class ResolveOpenScheduleTests(ScheduleTestCase):
    def test_returns_open_schedule(self):
        schedule = self._schedule(starts_in_minutes=10, zone=self.zone)
        found, error = selectors.resolve_open_schedule(
            exam_id=self.exam.pk, zone_id=self.zone.pk
        )
        self.assertEqual(found, schedule)
        self.assertIsNone(error)

    def test_no_schedule_is_distinguished_from_closed(self):
        """
        "Jadval umuman yo'q" va "jadval bor, lekin yopiq" - BOSHQA
        holatlar.

        Birinchisi dastlabki o'rnatish bosqichi va uni
        `REQUIRE_EXAM_SCHEDULE=false` da o'tkazib yuborish mumkin;
        ikkinchisi esa haqiqiy rad etish.
        """
        _, error = selectors.resolve_open_schedule(exam_id=self.exam.pk)
        self.assertEqual(error, "no_schedule")

        self._schedule(starts_in_minutes=600)  # bor, lekin hali yopiq
        _, error = selectors.resolve_open_schedule(exam_id=self.exam.pk)
        self.assertEqual(error, "closed")

    def test_zone_schedule_wins_over_global(self):
        """
        Bino jadvali global jadvaldan USTUN.

        `nulls_last` ataylab: PostgreSQL `DESC` da NULL'ni boshiga
        qo'yadi va oddiy `order_by("-zone_id")` global jadvalni
        birinchi qilib qo'yardi.
        """
        self._schedule(starts_in_minutes=5, zone=None)
        zone_schedule = self._schedule(starts_in_minutes=5, zone=self.zone)
        found, _ = selectors.resolve_open_schedule(
            exam_id=self.exam.pk, zone_id=self.zone.pk
        )
        self.assertEqual(found, zone_schedule)

    def test_other_zone_schedule_is_invisible(self):
        self._schedule(starts_in_minutes=5, zone=self.other_zone)
        found, error = selectors.resolve_open_schedule(
            exam_id=self.exam.pk, zone_id=self.zone.pk
        )
        self.assertIsNone(found)
        # Jadval boshqa binoga tegishli bo'lsa ham u MAVJUD, ya'ni
        # "umuman yo'q" emas.
        self.assertEqual(error, "closed")

    def test_yesterday_schedule_still_found(self):
        """
        Kechagi sanadagi seans ham qidiriladi.

        23:00 da boshlanib yarim kechadan o'tadigan imtihon yoki uzun
        `checkin_lead_minutes` bilan oldingi kunga tushib qolgan
        kirish oynasi shu tufayli topiladi.
        """
        starts_at = self.now - timedelta(hours=2)
        ExamSchedule.objects.create(
            exam=self.exam,
            exam_date=timezone.localdate(starts_at) - timedelta(days=1),
            starts_at=starts_at,
            ends_at=starts_at + timedelta(hours=4),
        )
        # `exam_date` ataylab noto'g'ri (kechagi), lekin vaqt oynasi ochiq:
        # yakuniy qaror `is_open()` bo'yicha chiqadi.
        found, _ = selectors.resolve_open_schedule(exam_id=self.exam.pk)
        self.assertIsNotNone(found)

    def test_soft_deleted_schedule_is_ignored(self):
        schedule = self._schedule(starts_in_minutes=5)
        schedule.delete()
        _, error = selectors.resolve_open_schedule(exam_id=self.exam.pk)
        self.assertEqual(error, "no_schedule")


class NextScheduleTests(ScheduleTestCase):
    def test_returns_nearest_upcoming(self):
        self._schedule(starts_in_minutes=600)
        soon = self._schedule(starts_in_minutes=200)
        found = selectors.next_schedule(exam_id=self.exam.pk)
        self.assertEqual(found, soon)

    def test_ignores_finished(self):
        self._schedule(starts_in_minutes=-600, duration=60)
        self.assertIsNone(selectors.next_schedule(exam_id=self.exam.pk))


class ExamModelTests(TestCase):
    def test_allowed_domain_comes_from_site_url(self):
        """
        Domen `site_url` dan olinadi — YAGONA manba.

        Ro'yxat client'da `QWebEngineUrlRequestInterceptor`
        allowlist'iga aylanadi; bo'sh qaytsa WebView'da hech nima
        bloklanmasdi.
        """
        exam = Exam.objects.create(
            name="Fizika", site_url="https://ntest.uzbmb.uz/login"
        )
        self.assertEqual(exam.get_allowed_domains(), ["ntest.uzbmb.uz"])

    def test_port_and_path_are_stripped(self):
        """
        Faqat HOST qoladi.

        Interceptor host bo'yicha solishtiradi, ya'ni ro'yxatda port
        yoki yo'l qolsa hech bir so'rov mos kelmasdi va butun
        platforma bloklanardi.
        """
        exam = Exam.objects.create(
            name="Kimyo", site_url="https://test.example.uz:8443/exam/login"
        )
        self.assertEqual(exam.get_allowed_domains(), ["test.example.uz"])


class ExamSiteHeaderTests(TestCase):
    """
    Platforma sarlavhasi: "Authorization: Bearer <token>".

    Qiymat KREDENSIAL, shuning uchun u bazada shifrlangan holda
    yotadi va admin API'sida faqat niqob bo'lib qaytadi. Ilgari bu
    o'rinda `allowed_domains` ro'yxati bor edi va u boshqa savolga
    javob berardi ("qaysi domenlar ochiq"); yangi maydon esa
    platformaga KIRISHNI ta'minlaydi.
    """

    def setUp(self):
        self.exam = Exam.objects.create(
            name="Ingliz tili", site_url="https://ntest.uzbmb.uz/login"
        )

    def test_round_trip(self):
        header = "Authorization: Bearer Sccpeeiruieruierei3434u"
        exam_services.set_site_header(self.exam, header)
        self.exam.save(update_fields=["site_header_encrypted"])

        self.exam.refresh_from_db()
        self.assertEqual(exam_services.get_site_header(self.exam), header)

    def test_value_is_not_stored_in_clear_text(self):
        """
        Bazani o'qish tokenni bermasligi kerak.

        Bu `Camera.password_encrypted` bilan bir xil qoida: bitta
        SQL dump tashqi platformaning API'siga to'liq kirish
        berardi.
        """
        exam_services.set_site_header(
            self.exam, "Authorization: Bearer Sccpeeiruieruierei3434u"
        )
        self.assertNotIn("Sccpeeiruieruierei3434u", self.exam.site_header_encrypted)
        self.assertTrue(self.exam.site_header_encrypted)

    def test_empty_value_clears_the_header(self):
        exam_services.set_site_header(self.exam, "Authorization: Bearer x")
        exam_services.set_site_header(self.exam, "")

        self.assertEqual(self.exam.site_header_encrypted, "")
        self.assertEqual(exam_services.get_site_header(self.exam), "")

    def test_mask_keeps_the_name_and_hides_the_value(self):
        exam_services.set_site_header(
            self.exam, "Authorization: Bearer Sccpeeiruieruierei3434u"
        )
        masked = exam_services.mask_site_header(self.exam)

        self.assertTrue(masked.startswith("Authorization: "))
        self.assertNotIn("Sccpeeiruieruierei3434u", masked)
        # Administrator "to'g'ri token turibdimi?" degan savolga javob
        # topishi uchun boshi va oxiri qoladi.
        self.assertIn("Bear", masked)
        self.assertIn("434u", masked)

    def test_mask_is_empty_when_no_header(self):
        self.assertEqual(exam_services.mask_site_header(self.exam), "")

    def test_header_without_colon_is_fully_masked(self):
        """Nomi ajratilmagan qiymatning qaysi qismi sir ekani noma'lum."""
        exam_services.set_site_header(self.exam, "SccpeeiruieruiereiXYZ")
        masked = exam_services.mask_site_header(self.exam)

        self.assertNotIn("eeiruieruierei", masked)
