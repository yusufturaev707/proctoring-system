"""
Imtihon profilida FaceID O'CHIQ (`Setting.is_faceid_student`, `is_faceid_exam`).

Ilgari ikkala kalit ham clientga borardi, lekin kuchga kirmasdi: kirishda
client kamerani baribir ochardi (serializer vektorsiz so'rovni 400 bilan
rad etardi), test davomida esa eski client davriy natijani yuboraverardi
va u `face_fails`/`high_suspicion_identity` ga tushardi.
"""

from django.core.cache import cache
from django.test import TestCase

from apps.common.exceptions import FaceVerificationFailed
from apps.common.tests.utils import RedisStateMixin
from apps.controls import services as controls_services
from apps.proctoring.api.v1.client_serializers import FaceVerifySerializer
from apps.proctoring.models import ExamSession, FaceVerificationLog
from apps.proctoring.services import session as session_service
from apps.proctoring.tests import factories


class FaceDisabledTestCase(RedisStateMixin, TestCase):
    student = True
    in_exam = True

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        setting = factories.make_setting(
            is_faceid_student=self.student, is_faceid_exam=self.in_exam
        )
        self.exam = factories.make_exam(setting=setting)
        factories.make_schedule(exam=self.exam)
        self.device = factories.make_device()

    def _challenge(self, pinfl="30000000000001"):
        return session_service.lookup_candidate(
            pinfl=pinfl, exam=self.exam, device=self.device,
            zone=self.device.computer.zone, **factories.machine_of(self.device),
        )["challenge"]

    def _verify(self, **kwargs):
        return session_service.verify_initial_face(
            challenge=self._challenge(), device=self.device,
            computer=self.device.computer, **kwargs,
        )


class EntryFaceDisabledTests(FaceDisabledTestCase):
    student = False

    def test_session_opens_without_embedding(self):
        """Client kamerani ochmaydi — vektor, ball va rasm yo'q."""
        session = self._verify(embedding=None, score=None, faces_detected=0)
        self.assertEqual(session.status, ExamSession.Status.READY)
        self.assertIsNone(session.reference_embedding)
        self.assertEqual(session.meta.get("face_entry"), "disabled")
        # Shaxs kafolati avvalgidek operatorniki.
        self.assertFalse(session.identity_verified)

    def test_no_failed_looking_log_row(self):
        """Tekshiruv bo'lmagan — panelda "o'tmadi" qatori chiqmasligi kerak."""
        self._verify(embedding=None, score=None, faces_detected=0)
        self.assertFalse(FaceVerificationLog.objects.exists())

    def test_serializer_accepts_request_without_embedding_and_score(self):
        serializer = FaceVerifySerializer(data={"challenge": "abc", "faces_detected": 0})
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_old_client_with_embedding_is_still_recorded(self):
        """Bayroqni bilmagan client solishtirib yuborsa — avvalgidek yoziladi."""
        session = self._verify(embedding=[0.1] * 512, score=90, faces_detected=1)
        self.assertIsNotNone(session.reference_embedding)
        self.assertTrue(FaceVerificationLog.objects.get(session=session).passed)


class EntryFaceRequiredTests(FaceDisabledTestCase):
    def test_request_without_embedding_is_refused(self):
        """Qoida serializer'dan servisga ko'chdi — yoqilgan profilda saqlanadi."""
        with self.assertRaises(FaceVerificationFailed):
            self._verify(embedding=None, score=None, faces_detected=0)
        self.assertFalse(ExamSession.objects.exists())


class PeriodicFaceDisabledTests(FaceDisabledTestCase):
    in_exam = False

    def test_old_client_report_is_ignored(self):
        session = self._verify(embedding=[0.1] * 512, score=90, faces_detected=1)
        config = controls_services.get_client_config(self.exam)
        for _ in range(int(config["face"]["max_fail"]) + 1):
            result = session_service.verify_periodic_face(
                session=session, score=5, faces_detected=1, config=config,
            )
        self.assertTrue(result["disabled"])
        self.assertFalse(result["limit_reached"])
        self.assertEqual(result["fail_count"], 0)
        self.assertFalse(
            FaceVerificationLog.objects.filter(
                stage=FaceVerificationLog.Stage.PERIODIC
            ).exists()
        )
