"""
Redis uzilishi va eskirgan sessiyalar (F-03, F-09).

Ikki xavf, ikkalasi ham "bitta nosozlik — 5000 imtihon":

  * Redis o'chsa client API butunlay 500 qaytarardi: sessiya tokeni
    Redis'da tekshirilar, DB zaxirasi esa faqat "topilmadi" holatida
    ishlardi, "Redis ishlamayapti" holatida emas.
  * Ingest ishchisi to'xtasa `last_heartbeat_at` eskirar va
    `close_stale_sessions` sog' sessiyalarni ham yopardi.

Redis uzilishi `get_redis()` ni `ConnectionError` ko'taradigan qilib
taqlid qilinadi — haqiqiy Redis kerak emas.
"""

import time
from contextlib import ExitStack
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.db import OperationalError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from redis.exceptions import ConnectionError as RedisConnectionError
from rest_framework.test import APIClient

from apps.common.exceptions import api_exception_handler
from apps.common.tests.utils import RedisStateMixin
from apps.common.utils.crypto import hash_token
from apps.proctoring.models import ExamSession, ProctoringEvent
from apps.proctoring.tasks import close_stale_sessions
from apps.proctoring.tests import factories
from apps.proctoring.tests.test_client_api import bearer

#: `get_redis` ni o'z nomiga import qilgan barcha modullar.
_REDIS_ENTRY_POINTS = (
    "apps.common.redis_client.get_redis",
    "apps.proctoring.services.state.get_redis",
    "apps.proctoring.services.ingest.get_redis",
    "apps.proctoring.services.risk.get_redis",
    "apps.proctoring.services.stream.get_redis",
    "apps.proctoring.tasks.get_redis",
)


def redis_down():
    """Barcha Redis chaqiruvlari `ConnectionError` beradigan kontekst."""
    stack = ExitStack()
    for target in _REDIS_ENTRY_POINTS:
        stack.enter_context(patch(target, side_effect=RedisConnectionError("Redis o'chiq")))
    return stack


class ClientApiWithoutRedisTests(TestCase):
    """F-09: Redis ishlamasa ham imtihon davom etadi."""

    def setUp(self):
        self.client = APIClient()
        self.device = factories.make_device()
        self.session = factories.make_session(device=self.device, risk_score=17)
        self.operator = factories.make_user(permissions=["client.operate"])
        # Token Redis'siz beriladi: faqat DB'dagi hash va muddat — aynan
        # Redis uzilganda autentifikatsiya tayanadigan yagona manba.
        self.raw_token = "test-session-token-redis-outage"
        self.session.token_hash = hash_token(self.raw_token)
        self.session.token_expires_at = timezone.now() + timedelta(hours=1)
        self.session.save(update_fields=["token_hash", "token_expires_at"])

    def _headers(self):
        return {
            "HTTP_AUTHORIZATION": bearer(self.operator),
            "HTTP_X_DEVICE_ID": self.device.device_id,
            "HTTP_X_PROCTORING_SESSION": self.raw_token,
        }

    def test_heartbeat_is_accepted_and_written_to_database(self):
        before = timezone.now()
        with redis_down():
            response = self.client.post(
                reverse("client-heartbeat"), {"network_ok": True}, format="json", **self._headers()
            )

        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()["data"]
        self.assertFalse(data["should_stop"])
        self.assertEqual(data["risk_score"], 17)
        self.session.refresh_from_db()
        self.assertGreaterEqual(self.session.last_heartbeat_at, before)

    def test_terminated_session_is_still_rejected(self):
        """DB zaxirasi chetlashtirishni chetlab o'tmaydi."""
        ExamSession.objects.filter(pk=self.session.pk).update(
            status=ExamSession.Status.TERMINATED
        )
        with redis_down():
            response = self.client.post(
                reverse("client-heartbeat"), {"network_ok": True}, format="json", **self._headers()
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "session_not_found")

    def test_expired_token_is_rejected(self):
        ExamSession.objects.filter(pk=self.session.pk).update(
            token_expires_at=timezone.now() - timedelta(minutes=1)
        )
        with redis_down():
            response = self.client.post(
                reverse("client-heartbeat"), {"network_ok": True}, format="json", **self._headers()
            )

        self.assertEqual(response.status_code, 404)

    def test_events_are_written_directly_and_accepted(self):
        """Hodisa DB'ga yoziladi va client uni qayta yubormaydi (202, 500 emas)."""
        moment = timezone.now().isoformat()
        with redis_down():
            response = self.client.post(
                reverse("client-events"),
                {
                    "events": [
                        {"type": "window_blur", "severity": 1, "occurred_at": moment},
                        {"type": "hotkey_blocked", "severity": 1, "occurred_at": moment},
                    ]
                },
                format="json",
                **self._headers(),
            )

        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(response.json()["data"]["accepted"], 2)
        self.assertEqual(ProctoringEvent.objects.filter(session=self.session).count(), 2)

    def test_finish_completes_in_database(self):
        with redis_down():
            response = self.client.post(
                reverse("client-session-finish"), {"reason": "test"}, format="json", **self._headers()
            )

        self.assertEqual(response.status_code, 200, response.content)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, ExamSession.Status.FINISHED)
        self.assertIsNotNone(self.session.finished_at)

    def test_unguarded_redis_path_returns_503_with_retry_after(self):
        """Zaxirasi yo'q yo'l — 500 emas, 503 + tasodifiy `Retry-After`."""
        with redis_down():
            response = self.client.get(reverse("client-session-state"), **self._headers())

        self.assertEqual(response.status_code, 503, response.content)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
        self.assertIn(int(response["Retry-After"]), range(5, 16))


class BackendUnavailableHandlerTests(TestCase):
    def test_database_and_redis_outages_map_to_503(self):
        for exc in (OperationalError("DB javob bermadi"), RedisConnectionError("Redis o'chiq")):
            with self.subTest(exc=type(exc).__name__):
                response = api_exception_handler(exc, {})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.data["error"]["code"], "service_unavailable")
                self.assertIn(int(response["Retry-After"]), range(5, 16))

    def test_retry_after_is_spread(self):
        """Bir xil `Retry-After` 5000 clientni bir soniyada qaytarardi."""
        values = {
            int(api_exception_handler(RedisConnectionError("x"), {})["Retry-After"])
            for _ in range(50)
        }
        self.assertGreater(len(values), 1)


class StaleSessionHeartbeatTests(RedisStateMixin, TestCase):
    """F-03: DB'dagi eski vaqt yopish uchun yetarli dalil emas."""

    def setUp(self):
        super().setUp()
        self.stale_after = settings.PROCTORING["STALE_SESSION_AFTER"]
        self.session = factories.make_session(
            device=factories.make_device(),
            last_heartbeat_at=timezone.now() - timedelta(hours=1),
        )

    def test_session_alive_in_redis_is_kept_and_database_synced(self):
        """Ingest ishchisi to'xtagan: DB eski, lekin client heartbeat yuboryapti."""
        from apps.proctoring.services import state as session_state

        session_state.touch_heartbeat(self.session.pk, zone_id=self.session.zone_id)

        result = close_stale_sessions()

        self.session.refresh_from_db()
        self.assertEqual(self.session.status, ExamSession.Status.IN_PROGRESS)
        self.assertGreater(self.session.last_heartbeat_at, timezone.now() - timedelta(minutes=1))
        self.assertEqual(result["closed"], 0)
        self.assertEqual(result["alive"], 1)

    def test_session_dead_everywhere_is_expired(self):
        result = close_stale_sessions()

        self.session.refresh_from_db()
        self.assertEqual(self.session.status, ExamSession.Status.EXPIRED)
        self.assertEqual(result["closed"], 1)

    def test_old_redis_heartbeat_is_expired(self):
        from apps.common.redis_client import get_redis
        from apps.proctoring.services import state as session_state

        get_redis().hset(
            session_state.state_key(self.session.pk),
            "hb",
            int(time.time()) - self.stale_after - 60,
        )

        close_stale_sessions()

        self.session.refresh_from_db()
        self.assertEqual(self.session.status, ExamSession.Status.EXPIRED)

    def test_only_dead_sessions_are_closed(self):
        from apps.proctoring.services import state as session_state

        alive = factories.make_session(
            device=factories.make_device(),
            last_heartbeat_at=timezone.now() - timedelta(hours=2),
        )
        session_state.touch_heartbeat(alive.pk, zone_id=alive.zone_id)

        result = close_stale_sessions()

        alive.refresh_from_db()
        self.session.refresh_from_db()
        self.assertEqual(alive.status, ExamSession.Status.IN_PROGRESS)
        self.assertEqual(self.session.status, ExamSession.Status.EXPIRED)
        self.assertEqual(result["closed"], 1)


class StaleSessionRedisDownTests(TestCase):
    def test_nothing_is_closed_while_redis_is_down(self):
        """Tirikligini tekshirib bo'lmasa — yopmaymiz."""
        session = factories.make_session(
            device=factories.make_device(),
            last_heartbeat_at=timezone.now() - timedelta(hours=1),
        )

        with redis_down():
            result = close_stale_sessions()

        session.refresh_from_db()
        self.assertEqual(session.status, ExamSession.Status.IN_PROGRESS)
        self.assertEqual(result["reason"], "redis_unavailable")
        self.assertEqual(result["closed"], 0)
