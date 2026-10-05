"""
Client qayta ishga tushgach shu mashinada yangi urinish ochilsa, eskisi
DARHOL yopiladi va bog'lanadi (`session._replace_previous_on_device`).

Ilgari eskisi `STALE_SESSION_AFTER` gacha "jarayonda" turardi va
yopilganda "bitta talabgor - bitta sessiya" qulfini (egasi qurilma,
ikkalasida bir xil) yangi sessiyadan tortib olardi.
"""

from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.common.redis_client import get_redis
from apps.common.tests.utils import RedisStateMixin
from apps.controls.models import AllowedPublicIp
from apps.proctoring.models import ExamSession
from apps.proctoring.services import session as session_service
from apps.proctoring.services import state as session_state
from apps.proctoring.tasks import close_stale_sessions
from apps.proctoring.tests import factories
from apps.proctoring.tests.test_client_api import bearer

PINFL = "30000000000001"


class ReplacePreviousSessionTests(RedisStateMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.exam = factories.make_exam()
        factories.make_schedule(exam=self.exam)
        self.device = factories.make_device()
        self.auth = bearer(factories.make_user(permissions=["client.operate"]))
        AllowedPublicIp.objects.create(ip_address="8.8.8.8", zone=self.device.computer.zone)
        cache.clear()
        self.addCleanup(cache.clear)

    def enter(self) -> ExamSession:
        """JSHSHIR tekshiruvi + yuz tasdig'i - qayta ishga tushgandagi yo'l."""
        challenge = session_service.lookup_candidate(
            pinfl=PINFL, exam=self.exam, device=self.device, zone=self.device.computer.zone,
            **factories.machine_of(self.device),
        )["challenge"]
        response = self.client.post(
            reverse("client-face-verify"),
            {"challenge": challenge, "embedding": [0.1] * 512, "score": 88, "faces_detected": 1},
            format="json",
            HTTP_AUTHORIZATION=self.auth,
            HTTP_X_DEVICE_ID=self.device.device_id,
            REMOTE_ADDR="8.8.8.8",
        )
        self.assertEqual(response.status_code, 201, response.content)
        return ExamSession.objects.order_by("-attempt_no").first()

    def test_previous_session_is_closed_and_linked(self):
        first = self.enter()
        second = self.enter()
        first.refresh_from_db()

        self.assertEqual(first.status, ExamSession.Status.EXPIRED)
        self.assertIsNotNone(first.finished_at)
        self.assertEqual(first.meta["replaced_by"], str(second.public_id))
        self.assertEqual(second.meta["previous_session"], str(first.public_id))
        self.assertEqual(second.attempt_no, first.attempt_no + 1)
        # Panelda bitta faol sessiya.
        self.assertEqual(
            ExamSession.objects.exclude(status__in=ExamSession.TERMINAL_STATUSES).count(), 1
        )

    def test_candidate_lock_stays_with_the_new_session(self):
        first = self.enter()
        self.enter()
        # Eski client o'lgan: heartbeat kelmay qolgan. Tuzatishsiz aynan
        # shu yerda `close_stale_sessions` eskisini yopib, qulfni
        # yangi sessiyadan tortib olardi.
        ExamSession.objects.filter(pk=first.pk).update(
            last_heartbeat_at=timezone.now() - timedelta(hours=1)
        )
        close_stale_sessions()
        owner = get_redis().get(session_state.candidate_lock_key(PINFL, self.exam.pk))
        self.assertEqual(owner, f"dev:{self.device.pk}")

    def test_first_session_is_left_untouched(self):
        first = self.enter()
        self.assertNotIn("previous_session", first.meta)
        self.assertNotEqual(first.status, ExamSession.Status.EXPIRED)
