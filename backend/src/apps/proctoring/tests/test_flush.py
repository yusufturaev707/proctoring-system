"""
Write-behind va ingest flush'ining o'tkazuvchanlik tuzatishlari.

* `flush_session_state` — `bulk_update` o'rniga `UPDATE ... FROM (VALUES)`:
  qiymatlar avvalgidek yozilishi shart.
* `flush_event_buffer` — bitta ishga tushishda bir necha batch.
* `drain_dirty` — `limit` dan ortig'i keyingi siklga qoladi.
"""

from datetime import timedelta

from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.common.tests.utils import RedisStateMixin
from apps.proctoring import tasks
from apps.proctoring.models import ExamSession, ProctoringEvent
from apps.proctoring.services import ingest, risk
from apps.proctoring.services import state as session_state
from apps.proctoring.tests import factories


class FlushSessionStateTests(RedisStateMixin, TestCase):
    def test_hot_state_is_written_to_every_session(self):
        first = factories.make_session()
        second = factories.make_session(risk_score=7)
        session_state.touch_heartbeat(first.pk, extra={"face_checks": 12})
        session_state.increment(first.pk, "events", 5)
        session_state.increment(first.pk, "shots", 3)
        session_state.increment(first.pk, "face_fails", 2)
        risk.apply(session_id=first.pk, event_type="multi_monitor",
                   config=risk.resolve_config(None))
        # Ikkinchisida faqat heartbeat — hisoblagichlar joyida qoladi.
        session_state.touch_heartbeat(second.pk)

        result = tasks.flush_session_state()

        self.assertEqual(result, {"updated": 2})
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(
            (first.event_count, first.screenshot_count, first.face_fail_count, first.face_check_count),
            (5, 3, 2, 12),
        )
        self.assertGreater(first.risk_score, 0)
        self.assertEqual(first.risk_breakdown, risk.breakdown(first.pk))
        self.assertIsNotNone(first.last_heartbeat_at)
        self.assertLess(abs((timezone.now() - first.last_heartbeat_at).total_seconds()), 5)
        self.assertEqual(second.event_count, 0)
        self.assertEqual(second.risk_breakdown, {})

    def test_many_sessions_span_several_update_chunks(self):
        sessions = [factories.make_session() for _ in range(5)]
        for index, session in enumerate(sessions):
            session_state.increment(session.pk, "events", index + 1)

        original = tasks._STATE_UPDATE_CHUNK
        tasks._STATE_UPDATE_CHUNK = 2
        try:
            result = tasks.flush_session_state()
        finally:
            tasks._STATE_UPDATE_CHUNK = original

        self.assertEqual(result, {"updated": 5})
        counts = dict(
            ExamSession.objects.filter(pk__in=[s.pk for s in sessions]).values_list("pk", "event_count")
        )
        self.assertEqual([counts[s.pk] for s in sessions], [1, 2, 3, 4, 5])

    def test_drain_dirty_keeps_the_rest_for_the_next_run(self):
        for session_id in range(1, 8):
            session_state.touch_heartbeat(session_id)

        first = session_state.drain_dirty(limit=5)
        second = session_state.drain_dirty(limit=5)

        self.assertEqual(len(first), 5)
        self.assertEqual(sorted(first + second), list(range(1, 8)))
        self.assertEqual(session_state.drain_dirty(limit=5), [])


class FlushEventBufferTests(RedisStateMixin, TestCase):
    def test_one_run_drains_several_batches(self):
        session = factories.make_session()
        now = timezone.now() - timedelta(seconds=1)
        for index in range(7):
            ingest.push_event(
                session_id=session.pk, zone_id=session.zone_id, type="window_blur",
                severity=1, occurred_at=now, client_event_id=f"e{index}",
            )

        proctoring = {**settings.PROCTORING, "EVENT_BATCH_SIZE": 3, "EVENT_FLUSH_BUDGET_S": 30.0}
        with override_settings(PROCTORING=proctoring):
            result = tasks.flush_event_buffer()

        self.assertEqual(result["read"], 7)
        self.assertEqual(ProctoringEvent.objects.filter(session=session).count(), 7)

    def test_budget_stops_the_loop(self):
        session = factories.make_session()
        now = timezone.now() - timedelta(seconds=1)
        for index in range(6):
            ingest.push_event(
                session_id=session.pk, zone_id=session.zone_id, type="window_blur",
                severity=1, occurred_at=now, client_event_id=f"b{index}",
            )

        proctoring = {**settings.PROCTORING, "EVENT_BATCH_SIZE": 2, "EVENT_FLUSH_BUDGET_S": 0.0}
        with override_settings(PROCTORING=proctoring):
            first = tasks.flush_event_buffer()
            rest = tasks.flush_event_buffer()

        # Byudjet 0 — bitta batch, qolgani keyingi ishga tushishga.
        self.assertEqual(first["read"], 2)
        self.assertEqual(rest["read"], 2)
