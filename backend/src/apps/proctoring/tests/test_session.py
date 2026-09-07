"""
Sessiya hayot sikli.

Diqqat markazidagi uch qoida:

  1. **Shaxs tasdig'i — qaytib bo'lmaydigan nuqta.** FaceID uni bera
     olmaydi (etalon shu sessiyaning o'zida olinadi), shuning uchun
     `exam/access/` operator tasdig'isiz ochilmaydi.

  2. **Chetlashtirish DARHOL kuchga kiradi.** Token Redis'dan
     o'chiriladi va keyingi so'rov 401 oladi. Bu — JWT ishlatmaslik
     sababi.

  3. **Bitta talabgor = bitta faol sessiya**, atomik Redis qulfi bilan.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.common.exceptions import (
    ExamNotOpen,
    FaceVerificationFailed,
    IdentityAlreadyConfirmed,
    IdentityNotConfirmed,
    SessionAlreadyActive,
    SessionNotFound,
)
from apps.common.tests.utils import RedisStateMixin
from apps.common.utils.crypto import hash_token
from apps.proctoring.models import ExamSession, FaceVerificationLog, ProctoringEvent
from apps.proctoring.services import session as session_service
from apps.proctoring.services import state as session_state
from apps.proctoring.tests import factories


class SessionFlowTestCase(RedisStateMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.exam = factories.make_exam()
        self.schedule = factories.make_schedule(exam=self.exam)
        self.device = factories.make_device()
        self.computer = self.device.computer
        self.operator = factories.make_user(permissions=["client.identity"])

    def _lookup(self, pinfl="30000000000001", device=None):
        device = device or self.device
        return session_service.lookup_candidate(
            pinfl=pinfl, exam=self.exam, device=device, zone=device.computer.zone
        )

    def _make_session(self, pinfl="30000000000001", device=None):
        """Talabgorni qidiradi va FaceID'dan o'tkazib sessiya yaratadi."""
        device = device or self.device
        result = self._lookup(pinfl, device=device)
        return session_service.verify_initial_face(
            challenge=result["challenge"],
            embedding=[0.1] * 512,
            score=None,
            faces_detected=1,
            device=device,
            computer=device.computer,
        )


class LookupCandidateTests(SessionFlowTestCase):
    def test_returns_challenge_and_masked_pinfl(self):
        result = self._lookup()
        self.assertTrue(result["challenge"])
        # Ochiq JSHSHIR javobga TUSHMAYDI.
        self.assertNotIn("30000000000001", str(result["candidate"]))
        self.assertEqual(result["candidate"]["masked_pinfl"], "3000******0001")

    def test_no_session_row_is_created_yet(self):
        """
        Bu bosqichda DB'ga hech nima yozilmaydi.

        FaceID'dan o'tmagan talabgor uchun sessiya qatori yaratish
        keraksiz yozish va noto'g'ri statistika demak.
        """
        self._lookup()
        self.assertEqual(ExamSession.objects.count(), 0)

    def test_schedule_is_carried_into_the_session(self):
        session = self._make_session()
        self.assertEqual(session.schedule_id, self.schedule.pk)

    def test_closed_window_is_rejected_before_touching_external_api(self):
        """
        Kirish oynasi ENG BIRINCHI tekshiriladi.

        Oyna yopiq bo'lsa tashqi API'ga umuman tegilmaydi — aks holda
        JSHSHIR qidiruvi 24/7 ochiq turardi.
        """
        self.schedule.starts_at = timezone.now() + timedelta(days=2)
        self.schedule.ends_at = self.schedule.starts_at + timedelta(hours=3)
        self.schedule.exam_date = timezone.localdate(self.schedule.starts_at)
        self.schedule.save()

        with self.assertRaises(ExamNotOpen):
            self._lookup()

    def test_challenge_is_single_use(self):
        result = self._lookup()
        session_service.verify_initial_face(
            challenge=result["challenge"],
            embedding=[0.1] * 512,
            score=None,
            faces_detected=1,
            device=self.device,
            computer=self.computer,
        )
        with self.assertRaises(SessionNotFound):
            session_service.verify_initial_face(
                challenge=result["challenge"],
                embedding=[0.1] * 512,
                score=None,
                faces_detected=1,
                device=self.device,
                computer=self.computer,
            )


class InitialFaceTests(SessionFlowTestCase):
    def test_creates_session_in_ready_state(self):
        session = self._make_session()
        self.assertEqual(session.status, ExamSession.Status.READY)
        self.assertEqual(session.zone_id, self.computer.zone_id)
        self.assertEqual(session.attempt_no, 1)

    def test_reference_embedding_is_normalized(self):
        """Etalon normalizatsiya qilinadi — cosine shunga tayanadi."""
        session = self._make_session()
        norm = sum(value * value for value in session.reference_embedding) ** 0.5
        self.assertAlmostEqual(norm, 1.0, places=5)

    def test_client_score_is_ignored(self):
        """
        Client aytgan `score` E'TIBORGA OLINMAYDI.

        Solishtirish uchun etalon yo'q (u shu yerda OLINYAPTI), ya'ni
        `score: 100` yuborish orqali tekshiruvni chetlab o'tish mumkin
        bo'lardi.
        """
        result = self._lookup()
        session = session_service.verify_initial_face(
            challenge=result["challenge"],
            embedding=[0.1] * 512,
            score=100,
            faces_detected=1,
            device=self.device,
            computer=self.computer,
        )
        log = FaceVerificationLog.objects.get(session=session)
        self.assertEqual(log.score, 0)
        self.assertEqual(log.stage, FaceVerificationLog.Stage.INITIAL)

    def test_multiple_faces_are_rejected(self):
        result = self._lookup()
        with self.assertRaises(FaceVerificationFailed):
            session_service.verify_initial_face(
                challenge=result["challenge"],
                embedding=[0.1] * 512,
                score=None,
                faces_detected=2,
                device=self.device,
                computer=self.computer,
            )

    def test_identity_is_not_verified_yet(self):
        session = self._make_session()
        self.assertFalse(session.identity_verified)

    def test_second_attempt_same_day_increments_attempt_no(self):
        first = self._make_session()
        session_service.finish_session(first)
        second = self._make_session()
        self.assertEqual(second.attempt_no, 2)

    def test_candidate_lock_blocks_a_second_machine(self):
        """
        "Do'stim mening o'rnimga topshiradi" — atomik Redis qulfi.

        Birinchi sessiya faol turganda, o'sha JSHSHIR bilan BOSHQA
        kompyuterda sessiya ochib bo'lmaydi.
        """
        self._make_session()
        second_device = factories.make_device()
        with self.assertRaises(SessionAlreadyActive):
            self._make_session(device=second_device)

    def test_same_machine_may_retake_its_own_lock(self):
        """
        O'SHA kompyuter qulfni qayta egallay oladi.

        Bu ataylab: client qayta ishga tushsa yoki sessiya
        tugatilmasdan uzilsa, operator o'sha mashinada davom
        ettirishi kerak. Qulf begona mashinaga qarshi, o'ziga emas.

        `acquire_lock` Lua skripti aynan shu holatni ajratadi: egasi
        bir xil bo'lsa TTL uzaytiriladi. Shuning uchun birinchi sessiya
        hali YAKUNLANMAGAN bo'lsa ham ikkinchisi ochiladi.
        """
        first = self._make_session()
        second = self._make_session()

        self.assertEqual(first.attempt_no, 1)
        self.assertEqual(second.attempt_no, 2)
        self.assertEqual(second.device_id, first.device_id)

    def test_active_session_on_another_device_is_rejected_at_lookup(self):
        """
        Ikkinchi to'siq qulfdan OLDIN ishlaydi.

        `lookup_candidate` faol sessiyani ko'rib, tashqi API'ga
        umuman tegmasdan rad etadi — bu FaceID'gacha bo'lgan
        keraksiz ishni ham tejaydi.
        """
        self._make_session()
        with self.assertRaises(SessionAlreadyActive):
            self._lookup(device=factories.make_device())


class IdentityConfirmationTests(SessionFlowTestCase):
    def test_exam_access_is_blocked_without_confirmation(self):
        session = self._make_session()
        with self.assertRaises(IdentityNotConfirmed):
            session_service.issue_exam_access(session)

    def test_confirmation_opens_the_exam(self):
        session = self._make_session()
        session_service.confirm_identity(
            session,
            actor=self.operator,
            document_type="passport",
            document_number="AA1234567",
        )
        access = session_service.issue_exam_access(session)

        self.assertTrue(access["platform_session_token"])
        self.assertEqual(session.status, ExamSession.Status.IN_PROGRESS)
        self.assertIsNotNone(session.started_at)

    def test_confirmation_records_who_and_when(self):
        session = self._make_session()
        session_service.confirm_identity(
            session,
            actor=self.operator,
            document_type="id_card",
            document_number="ID999",
            note="izoh",
        )
        identity = session.identity
        self.assertTrue(identity["verified"])
        self.assertEqual(identity["by"], self.operator.username)
        self.assertEqual(identity["document_number"], "ID999")
        self.assertIn("at", identity)

    def test_confirmation_is_single_use(self):
        """
        Tasdiq BIR MARTA beriladi.

        Qayta yozish audit izini buzadi va "kim tasdiqlagan" savoliga
        ikki xil javob paydo bo'ladi.
        """
        session = self._make_session()
        session_service.confirm_identity(
            session, actor=self.operator, document_type="passport", document_number="A1"
        )
        with self.assertRaises(IdentityAlreadyConfirmed):
            session_service.confirm_identity(
                session,
                actor=self.operator,
                document_type="passport",
                document_number="A2",
            )

    def test_rejection_terminates_the_session(self):
        """
        Rad etish "tasdiqlamay qo'yaqolish" dan FARQ QILADI.

        Tasdiqlanmagan sessiya shunchaki ochilmaydi; rad etilgani esa
        chetlashtiriladi va dalil sifatida qayd etiladi.
        """
        session = self._make_session()
        session_service.reject_identity(
            session, actor=self.operator, reason="Hujjat mos kelmadi"
        )
        session.refresh_from_db()
        self.assertEqual(session.status, ExamSession.Status.TERMINATED)
        self.assertTrue(session.identity["rejected"])
        self.assertIn("Hujjat mos kelmadi", session.termination_reason)


class ExamAccessTests(SessionFlowTestCase):
    def _confirmed(self):
        session = self._make_session()
        session_service.confirm_identity(
            session, actor=self.operator, document_type="passport", document_number="A1"
        )
        return session

    def test_token_is_not_placed_in_the_url(self):
        """
        Tashqi platforma tokeni URL'da EMAS.

        URL'dagi token brauzer tarixi, `Referer` header'i va nginx
        access log orqali sizib chiqadi.
        """
        access = self._confirmed()
        result = session_service.issue_exam_access(access)
        self.assertNotIn(result["platform_session_token"], result["login_url"])
        self.assertIn(result["delivery"], ("post", "cookie"))

    def test_closed_platform_status_blocks_access(self):
        session = self._confirmed()
        session.external_status = "finished"
        session.save(update_fields=["external_status"])
        with self.assertRaises(ExamNotOpen):
            session_service.issue_exam_access(session)

    def test_expired_platform_window_blocks_access(self):
        session = self._confirmed()
        session.external_access_until = timezone.now() - timedelta(minutes=1)
        session.save(update_fields=["external_access_until"])
        with self.assertRaises(ExamNotOpen):
            session_service.issue_exam_access(session)

    def test_allowed_domains_are_returned(self):
        session = self._confirmed()
        result = session_service.issue_exam_access(session)
        self.assertTrue(result["allowed_domains"])


class SessionTokenTests(SessionFlowTestCase):
    def test_only_the_hash_is_stored(self):
        """
        Ochiq token faqat javobda mavjud.

        DB va Redis'da uning HMAC hash'i yotadi: Redis dump'i sizib
        chiqsa, faol sessiyalarni o'g'irlab bo'lmaydi.
        """
        session = self._make_session()
        raw = session_service.issue_session_token(session)

        session.refresh_from_db()
        self.assertNotEqual(session.token_hash, raw)
        self.assertEqual(session.token_hash, hash_token(raw))
        self.assertIsNotNone(session_state.resolve_session_token(hash_token(raw)))

    def test_token_is_revoked_on_terminate(self):
        """
        Chetlashtirish DARHOL kuchga kiradi.

        Token Redis'dan o'chadi va talabgorning keyingi so'rovi 401
        oladi — aynan shu JWT ishlatmaslik sababi.
        """
        session = self._make_session()
        raw = session_service.issue_session_token(session)
        digest = hash_token(raw)

        session_service.terminate_session(session, actor=self.operator, reason="Qoida buzildi")

        self.assertIsNone(session_state.resolve_session_token(digest))
        self.assertEqual(session.status, ExamSession.Status.TERMINATED)

    def test_terminate_writes_a_critical_event(self):
        session = self._make_session()
        session_service.terminate_session(session, actor=self.operator, reason="sabab")
        event = ProctoringEvent.objects.get(
            session=session, type=ProctoringEvent.Type.SESSION_TERMINATED
        )
        self.assertEqual(event.severity, ProctoringEvent.Severity.CRITICAL)
        self.assertEqual(event.payload["actor"], self.operator.username)

    def test_terminate_is_idempotent(self):
        session = self._make_session()
        session_service.terminate_session(session, actor=self.operator, reason="1")
        session_service.terminate_session(session, actor=self.operator, reason="2")
        self.assertEqual(
            ProctoringEvent.objects.filter(
                type=ProctoringEvent.Type.SESSION_TERMINATED
            ).count(),
            1,
        )

    def test_finish_releases_the_candidate_lock(self):
        """
        Yakunlangan sessiya qulfni bo'shatadi.

        Aks holda elektr uzilgandan keyin talabgor qayta kira olmasdi.
        """
        session = self._make_session()
        session_service.finish_session(session)
        # Qulf bo'shagani — o'sha JSHSHIR bilan yangi sessiya ochilishi.
        again = self._make_session()
        self.assertEqual(again.attempt_no, 2)

    def test_finish_flushes_hot_counters_into_the_row(self):
        session = self._make_session()
        session_state.increment(session.pk, "events", 7)
        session_state.bump_risk(session.pk, 33)

        session_service.finish_session(session)

        session.refresh_from_db()
        self.assertEqual(session.event_count, 7)
        self.assertEqual(session.risk_score, 33)
        self.assertEqual(session.status, ExamSession.Status.FINISHED)

    def test_risk_score_is_capped_at_100(self):
        session = self._make_session()
        session_state.bump_risk(session.pk, 500)
        session_service.finish_session(session)
        session.refresh_from_db()
        self.assertEqual(session.risk_score, 100)


class PeriodicFaceTests(SessionFlowTestCase):
    def setUp(self):
        super().setUp()
        from apps.controls import services as controls_services

        self.session = self._make_session()
        self.config = controls_services.get_client_config(self.exam)

    def _verify(self, embedding, faces=1):
        return session_service.verify_periodic_face(
            session=self.session,
            embedding=embedding,
            score=None,
            faces_detected=faces,
            image_key="",
            config=self.config,
        )

    def test_matching_face_passes(self):
        """Etalon bilan bir xil vektor — to'liq moslik."""
        result = self._verify(list(self.session.reference_embedding))
        self.assertTrue(result["passed"])
        self.assertEqual(result["score"], 100)

    def test_server_recomputes_the_score(self):
        """
        Server clientdan kelgan ballga ISHONMAYDI.

        Etalon bor bo'lsa cosine qaytadan hisoblanadi va manba
        `SERVER` deb belgilanadi.
        """
        result = session_service.verify_periodic_face(
            session=self.session,
            embedding=list(self.session.reference_embedding),
            score=0,  # client "mos kelmadi" deyapti
            faces_detected=1,
            image_key="",
            config=self.config,
        )
        self.assertTrue(result["passed"])
        log = FaceVerificationLog.objects.filter(
            stage=FaceVerificationLog.Stage.PERIODIC
        ).latest("id")
        self.assertEqual(log.source, FaceVerificationLog.Source.SERVER)

    def test_mismatch_increments_fail_counter_and_creates_event(self):
        wrong = [-value for value in self.session.reference_embedding]
        result = self._verify(wrong)

        self.assertFalse(result["passed"])
        self.assertEqual(result["fail_count"], 1)
        self.assertTrue(
            ProctoringEvent.objects.filter(
                type=ProctoringEvent.Type.FACE_MISMATCH
            ).exists()
        )

    def test_success_resets_the_counter(self):
        """
        Faqat KETMA-KET muvaffaqiyatsizliklar hisobga olinadi.

        Bitta tasodifiy xato (yorug'lik o'zgardi, bosh burildi)
        talabgorni chetlashtirmasligi kerak.
        """
        wrong = [-value for value in self.session.reference_embedding]
        self._verify(wrong)
        self._verify(list(self.session.reference_embedding))
        result = self._verify(wrong)
        self.assertEqual(result["fail_count"], 1)

    def test_terminate_flag_after_max_fail(self):
        wrong = [-value for value in self.session.reference_embedding]
        max_fail = int(self.config["face"]["max_fail"])
        for _ in range(max_fail - 1):
            self.assertFalse(self._verify(wrong)["should_terminate"])
        self.assertTrue(self._verify(wrong)["should_terminate"])

    def test_multiple_faces_creates_its_own_event_type(self):
        self._verify(list(self.session.reference_embedding), faces=2)
        self.assertTrue(
            ProctoringEvent.objects.filter(
                type=ProctoringEvent.Type.MULTIPLE_FACES
            ).exists()
        )

    def test_no_face_creates_its_own_event_type(self):
        self._verify(None, faces=0)
        self.assertTrue(
            ProctoringEvent.objects.filter(
                type=ProctoringEvent.Type.FACE_NOT_FOUND
            ).exists()
        )
