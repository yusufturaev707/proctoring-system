"""
Hodisalarni qabul qilish qatlami.

Ikki narsa tekshiriladi:

  1. `clamp_time` — client aytgan vaqtni maqbul oynaga tortadi. Bu
     ishonchlilik uchun KRITIK: `proctoring_event` `occurred_at`
     bo'yicha kunlik partitsiyalangan va soati adashgan bitta mashina
     2030-yilni yuborsa, o'sha qator uchun partitsiya bo'lmaydi va
     INSERT BUTUN batchni yiqitadi.

  2. Jiddiylik bo'yicha marshrutlash — `HIGH` va undan yuqorisi
     buferni chetlab o'tib darhol DB'ga yoziladi. "Dalil yo'qoldi"
     holati bo'lmasligi kerak.
"""

from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from apps.common.tests.utils import RedisStateMixin
from apps.proctoring.models import ProctoringEvent
from apps.proctoring.services import ingest
from apps.proctoring.tests import factories


class ClampTimeTests(TestCase):
    """Vaqt chegaralari — partitsiyani himoya qiladi."""

    def test_normal_time_passes_through(self):
        moment = timezone.now() - timedelta(minutes=5)
        clamped, original = ingest.clamp_time(moment)
        self.assertEqual(clamped, moment)
        self.assertIsNone(original)

    def test_future_time_is_pulled_to_now(self):
        """
        Kelajakdagi vaqt HOZIRGA tortiladi.

        Chegaraga emas, aynan `now` ga: kelajakdagi qiymat har doim
        xato (soat adashgan), ya'ni uni saqlashning ma'nosi yo'q.
        """
        future = timezone.now() + timedelta(days=365)
        clamped, original = ingest.clamp_time(future)
        self.assertLess(clamped, timezone.now() + timedelta(seconds=1))
        self.assertIsNotNone(original)

    def test_small_future_skew_is_tolerated(self):
        """
        Kichik oldinga siljish - normal holat.

        Mashina soati bir necha soniyaga farq qilishi odatiy va uni
        anomaliya deb belgilash log'ni shovqinga to'ldirardi.
        """
        skew = settings.PROCTORING["EVENT_MAX_FUTURE_SKEW"]
        moment = timezone.now() + timedelta(seconds=skew // 2)
        clamped, original = ingest.clamp_time(moment)
        self.assertEqual(clamped, moment)
        self.assertIsNone(original)

    def test_very_old_time_is_pulled_to_floor_not_now(self):
        """
        Juda eski vaqt CHEGARAGA tortiladi, `now` ga EMAS.

        U oflayn buferdan kelgan haqiqiy eski hodisa bo'lishi mumkin;
        `now` ga ko'chirish hodisalar TARTIBINI buzardi.
        """
        old = timezone.now() - timedelta(days=30)
        clamped, original = ingest.clamp_time(old)
        floor = timezone.now() - timedelta(
            seconds=settings.PROCTORING["EVENT_MAX_BACKFILL"]
        )
        self.assertAlmostEqual(clamped.timestamp(), floor.timestamp(), delta=5)
        self.assertIsNotNone(original)

    def test_original_value_is_preserved_in_payload(self):
        """
        Client aytgan vaqt TASHLANMAYDI - u `payload` ga ko'chadi.

        U ham dalil: mashina soati adashganini keyin ko'rish mumkin.
        """
        future = (timezone.now() + timedelta(days=1)).isoformat()
        _, original = ingest.clamp_time(future)
        payload = ingest._with_original_time({"a": 1}, original)
        self.assertEqual(payload["a"], 1)
        self.assertEqual(payload["_client_occurred_at"], original)

    def test_iso_string_is_parsed(self):
        moment = timezone.now() - timedelta(minutes=1)
        clamped, _ = ingest.clamp_time(moment.isoformat())
        self.assertAlmostEqual(clamped.timestamp(), moment.timestamp(), delta=1)

    def test_z_suffix_is_parsed(self):
        clamped, _ = ingest.clamp_time("2026-09-07T10:00:00Z")
        self.assertIsNotNone(clamped.tzinfo)

    def test_garbage_falls_back_to_now(self):
        """Buzilgan qiymat butun batchni yiqitmasligi kerak."""
        for value in ("salom", "", None, 12345):
            with self.subTest(value=value):
                clamped, _ = ingest.clamp_time(value)
                self.assertAlmostEqual(
                    clamped.timestamp(), timezone.now().timestamp(), delta=5
                )


class RiskWeightTests(TestCase):
    def test_every_weight_maps_to_a_real_event_type(self):
        """
        Xaritada mavjud bo'lmagan hodisa turi qolib ketmasin.

        Tur nomi o'zgarsa, vazni JIMGINA ishlamay qoladi va xavf balli
        noto'g'ri hisoblanadi.
        """
        valid = set(ProctoringEvent.Type.values)
        unknown = set(ingest.RISK_WEIGHTS) - valid
        self.assertEqual(unknown, set())

    def test_remote_control_is_the_heaviest(self):
        """RDP - imtihon paytidagi eng jiddiy texnik buzilish."""
        heaviest = max(ingest.RISK_WEIGHTS, key=ingest.RISK_WEIGHTS.get)
        self.assertEqual(heaviest, ProctoringEvent.Type.RDP_DETECTED)


class PushEventTests(RedisStateMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.session = factories.make_session()

    def test_critical_event_is_written_immediately(self):
        """
        `HIGH` va undan yuqorisi buferga TUSHMAYDI.

        Chetlashtirish va yuz tekshiruvidan o'tmaslik dalil bo'lib,
        ular Redis'da flush kutib turmasligi kerak.
        """
        ingest.push_event(
            session_id=self.session.pk,
            zone_id=self.session.zone_id,
            type=ProctoringEvent.Type.RDP_DETECTED,
            severity=ProctoringEvent.Severity.CRITICAL,
            occurred_at=timezone.now(),
            payload={"processes": ["AnyDesk.exe"]},
        )
        event = ProctoringEvent.objects.get(session=self.session)
        self.assertEqual(event.type, ProctoringEvent.Type.RDP_DETECTED)
        self.assertEqual(event.payload["processes"], ["AnyDesk.exe"])

    def test_low_severity_event_goes_to_the_stream(self):
        ingest.push_event(
            session_id=self.session.pk,
            zone_id=self.session.zone_id,
            type=ProctoringEvent.Type.HOTKEY_BLOCKED,
            severity=ProctoringEvent.Severity.LOW,
            occurred_at=timezone.now(),
        )
        # DB'ga hali yozilmagan — u Celery flush'ini kutadi.
        self.assertEqual(ProctoringEvent.objects.count(), 0)

        from apps.common.redis_client import get_redis

        stream = settings.PROCTORING["EVENT_STREAM_KEY"]
        self.assertEqual(get_redis().xlen(stream), 1)

    def test_risk_score_is_incremented(self):
        from apps.proctoring.services import state as session_state

        ingest.push_event(
            session_id=self.session.pk,
            zone_id=self.session.zone_id,
            type=ProctoringEvent.Type.MULTI_MONITOR,
            severity=ProctoringEvent.Severity.HIGH,
            occurred_at=timezone.now(),
        )
        hot = session_state.get_state(self.session.pk)
        self.assertEqual(
            hot["risk"], ingest.RISK_WEIGHTS[ProctoringEvent.Type.MULTI_MONITOR]
        )
        self.assertEqual(hot["events"], 1)

    def test_redis_failure_falls_back_to_direct_write(self):
        """
        Redis tushsa hodisa YO'QOLMAYDI.

        Sekinroq yo'l (to'g'ridan-to'g'ri DB) tanlanadi — proktorlikda
        "dalil yo'qoldi" holati bo'lmasligi kerak.
        """
        with mock.patch.object(
            ingest, "get_redis", side_effect=RuntimeError("redis o'chgan")
        ):
            ingest._enqueue(
                settings.PROCTORING["EVENT_STREAM_KEY"],
                {
                    "session_id": self.session.pk,
                    "zone_id": 0,
                    "type": ProctoringEvent.Type.WINDOW_BLUR,
                    "severity": 1,
                    "occurred_at": timezone.now().isoformat(),
                    "payload": "{}",
                    "screenshot_key": "",
                    "client_event_id": "",
                },
            )
        self.assertEqual(ProctoringEvent.objects.count(), 1)


class PushEventsBatchTests(RedisStateMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.session = factories.make_session()

    def _batch(self, events):
        return ingest.push_events_batch(session=self.session, events=events)

    def test_accepts_known_types(self):
        accepted = self._batch(
            [
                {
                    "type": ProctoringEvent.Type.WINDOW_BLUR,
                    "severity": 2,
                    "occurred_at": timezone.now().isoformat(),
                },
                {
                    "type": ProctoringEvent.Type.WINDOW_FOCUS,
                    "severity": 0,
                    "occurred_at": timezone.now().isoformat(),
                },
            ]
        )
        self.assertEqual(accepted, 2)

    def test_unknown_type_is_dropped_silently(self):
        """
        Noma'lum tur BUTUN batchni yiqitmaydi.

        Yangi client eski serverga yangi hodisa yuborishi mumkin;
        u tufayli qolgan hodisalarni yo'qotish noto'g'ri bo'lardi.
        """
        accepted = self._batch(
            [
                {"type": "kelajakdagi_hodisa", "severity": 2},
                {"type": ProctoringEvent.Type.WINDOW_BLUR, "severity": 2},
            ]
        )
        self.assertEqual(accepted, 1)

    def test_critical_events_in_batch_are_written_immediately(self):
        self._batch(
            [
                {"type": ProctoringEvent.Type.WINDOW_BLUR, "severity": 1},
                {"type": ProctoringEvent.Type.VM_DETECTED, "severity": 4},
            ]
        )
        self.assertEqual(
            list(ProctoringEvent.objects.values_list("type", flat=True)),
            [ProctoringEvent.Type.VM_DETECTED],
        )

    def test_batch_risk_is_capped(self):
        """
        Bitta batch xavf ballini cheksiz oshira olmaydi.

        Aks holda buzilgan client 40 ta hodisa yuborib, sessiyani
        darhol eng xavfli qilib qo'yardi va proktorning ro'yxati
        ma'nosini yo'qotardi.
        """
        from apps.proctoring.services import state as session_state

        self._batch(
            [{"type": ProctoringEvent.Type.RDP_DETECTED, "severity": 1}] * 10
        )
        hot = session_state.get_state(self.session.pk)
        self.assertLessEqual(hot["risk"], 40)

    def test_client_event_id_is_truncated(self):
        """Uzun ID DB ustunini (`max_length=64`) buzmasligi kerak."""
        self._batch(
            [
                {
                    "type": ProctoringEvent.Type.VM_DETECTED,
                    "severity": 4,
                    "client_event_id": "x" * 200,
                }
            ]
        )
        event = ProctoringEvent.objects.get()
        self.assertEqual(len(event.client_event_id), 64)

    def test_empty_batch(self):
        self.assertEqual(self._batch([]), 0)
