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

from django.conf import settings
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


class ChallengeDeviceBindingTests(SessionFlowTestCase):
    """
    Challenge'ni FAQAT uni olgan qurilma ishlata oladi.

    JSHSHIR tekshiruvidagi kompyuter broni SHU qurilma uchun
    chiqarilgan. Ilgari challenge istalgan mashinada sessiya ochardi,
    ya'ni bron faqat "JSHSHIR to'g'ri stolda kiritildi" ni isbotlardi.
    """

    def setUp(self):
        super().setUp()
        self.stranger = factories.make_device()

    def _verify(self, challenge, device):
        return session_service.verify_initial_face(
            challenge=challenge,
            embedding=[0.1] * 512,
            score=None,
            faces_detected=1,
            device=device,
            computer=device.computer if device else None,
        )

    def test_other_device_cannot_open_the_session(self):
        result = self._lookup()
        with self.assertRaises(SessionNotFound):
            self._verify(result["challenge"], self.stranger)
        self.assertFalse(ExamSession.objects.exists())

    def test_missing_device_cannot_open_the_session(self):
        result = self._lookup()
        with self.assertRaises(SessionNotFound):
            self._verify(result["challenge"], None)

    def test_foreign_attempt_does_not_burn_the_challenge(self):
        """
        Begona so'rov haqiqiy egasining challenge'ini yo'q qilmasligi
        kerak - aks holda talabgor sababsiz JSHSHIR ni qaytadan
        kiritishga majbur bo'lardi.
        """
        result = self._lookup()
        with self.assertRaises(SessionNotFound):
            self._verify(result["challenge"], self.stranger)

        session = self._verify(result["challenge"], self.device)
        self.assertEqual(session.device_id, self.device.pk)

    def test_other_device_cannot_record_entry_failure(self):
        """Begona qurilma boshqa talabgor nomidan urinish yoza olmaydi."""
        result = self._lookup()
        with self.assertRaises(SessionNotFound):
            session_service.record_entry_face_failure(
                challenge=result["challenge"], score=10, device=self.stranger,
                computer=self.stranger.computer,
            )
        self.assertFalse(FaceVerificationLog.objects.exists())


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

    def test_client_score_is_recorded(self):
        """
        Client hisoblagan ball QATORDA qoladi.

        Ilgari bu yerga 0 yozilardi: solishtirish serverda edi va
        kirishda etalon hali yo'q edi. Endi solishtirish clientda
        bo'lib bo'lgan va ball uning yagona izi - apellyatsiyada
        "qanday o'xshashlik bilan kiritilgan?" degan savolga faqat
        shu javob beradi.
        """
        result = self._lookup()
        session = session_service.verify_initial_face(
            challenge=result["challenge"],
            embedding=[0.1] * 512,
            score=91,
            faces_detected=1,
            device=self.device,
            computer=self.computer,
        )
        log = FaceVerificationLog.objects.get(session=session)
        self.assertEqual(log.score, 91)
        self.assertEqual(log.stage, FaceVerificationLog.Stage.INITIAL)
        self.assertEqual(log.source, FaceVerificationLog.Source.CLIENT)
        # Kontekst qatorning O'ZIDA: sessiya anonimlashtirilgach ham
        # "qaysi imtihon, qaysi bino" savoli javobsiz qolmaydi.
        self.assertEqual(log.exam_id, self.exam.pk)
        self.assertEqual(log.zone_id, self.computer.zone_id)

    def test_score_below_threshold_is_refused(self):
        """
        Chegaradan past ball bilan sessiya OCHILMAYDI.

        Bunday urinish `face/attempt/` ga borishi kerak edi. Aks holda
        "mos kelmadi" yozuvi bilan ochilgan sessiya paydo bo'lardi va
        uni bayonnomada tushuntirib bo'lmasdi.
        """
        result = self._lookup()
        with self.assertRaises(FaceVerificationFailed):
            session_service.verify_initial_face(
                challenge=result["challenge"],
                embedding=[0.1] * 512,
                score=10,
                faces_detected=1,
                device=self.device,
                computer=self.computer,
            )
        self.assertFalse(ExamSession.objects.exists())

    def test_enrollment_without_score_is_allowed(self):
        """
        Etalon rasm bo'lmasa client ball YUBORMAYDI.

        Solishtiriladigan narsaning o'zi yo'q, ya'ni chegara ham
        qo'llanmaydi - qaror operatorning hujjat tekshiruviga qoladi.
        """
        session = self._make_session()
        log = FaceVerificationLog.objects.get(session=session)
        self.assertEqual(log.score, 0)
        self.assertTrue(log.passed)

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

        self.assertTrue(access["login_url"])
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

    def test_login_url_is_the_platform_test_link(self):
        """
        WebView platformaning O'Z havolasini ochadi.

        Token havolaning ICHIDA va uni cookie yoki POST body'ga
        ko'chirib bo'lmaydi: platforma uni AYNAN URL'dan kutadi
        (`data.test_link`). Ilgari bu yerda teskari qoida bor edi
        (token URL'da bo'lmasin) va u boshqa platforma uchun
        yozilgan edi — u yerda tokenni biz berardik, bu yerda esa
        havolani platformaning o'zi tayyorlaydi.

        Xavf o'z kuchida qoladi (URL brauzer tarixida va `Referer`
        da qoladi), lekin uni kamaytirish endi platforma tomonida:
        havola bir martalik va qisqa muddatli bo'lishi kerak.
        Bizning tomondan himoya — WebView `off_the_record`
        profilida ochiladi, ya'ni tarix diskda saqlanmaydi.
        """
        session = self._confirmed()
        result = session_service.issue_exam_access(session)

        self.assertEqual(result["login_url"], session.external_test_link)
        self.assertEqual(result["delivery"], "url")

    def test_test_link_is_stored_encrypted(self):
        """Havola ichida token bor — bazada ochiq yotmasligi kerak."""
        session = self._confirmed()

        self.assertTrue(session.external_test_link)
        self.assertNotIn(
            session.external_test_link, session.external_test_link_enc
        )

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

    def test_site_header_never_reaches_the_client(self):
        """
        Platforma kredensiali client'ga BERILMAYDI.

        Backend — ko'prik: platformaga so'rovni faqat u yuboradi
        (`integrations/exam_site.py`). Sarlavhani client'ga berish
        500 ta imtihon mashinasiga platforma API kalitini tarqatish
        demak edi — bunday tokenni bekor qilib ham, kim ishlatganini
        aniqlab ham bo'lmaydi.
        """
        from apps.exams import services as exam_services

        session = self._confirmed()
        header = "Authorization: Bearer Sccpeeiruieruierei3434u"
        exam_services.set_site_header(session.exam, header)
        session.exam.save(update_fields=["site_header_encrypted"])

        result = session_service.issue_exam_access(session)

        self.assertNotIn("site_header", result)
        self.assertNotIn("Sccpeeiruieruierei3434u", str(result))


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


class EntryFaceFailureTests(SessionFlowTestCase):
    """
    Kirishda MOS KELMAGAN urinish: sessiyasiz yozuv.

    Aynan shu holat eng qimmatli: kadrda boshqa odam turgan bo'lishi
    mumkin, sessiya esa ochilmaydi va uni bog'laydigan hech narsa
    yo'q.
    """

    def test_records_row_without_session(self):
        result = self._lookup()
        outcome = session_service.record_entry_face_failure(
            challenge=result["challenge"],
            score=31,
            faces_detected=1,
            device=self.device,
            computer=self.computer,
        )

        self.assertTrue(outcome["recorded"])
        self.assertEqual(outcome["attempts"], 1)
        log = FaceVerificationLog.objects.get(pk=outcome["id"])
        self.assertIsNone(log.session_id)
        self.assertFalse(log.passed)
        self.assertEqual(log.score, 31)
        self.assertEqual(log.pinfl, "30000000000001")
        self.assertEqual(log.exam_id, self.exam.pk)
        self.assertEqual(log.zone_id, self.computer.zone_id)
        # Sessiya YARATILMAYDI: talabgor hali kirmadi.
        self.assertFalse(ExamSession.objects.exists())

    def test_challenge_survives_and_allows_retry(self):
        """
        Muvaffaqiyatsiz urinish `challenge` ni SARFLAMAYDI.

        Sarflansa, birinchi "mos kelmadi" dan keyin talabgor qaytadan
        JSHSHIR kiritishga majbur bo'lardi - holbuki qayta urinish
        aynan kutilgan xulq (yorug'lik, ko'zoynak, bosh burilishi).
        """
        result = self._lookup()
        session_service.record_entry_face_failure(
            challenge=result["challenge"], score=20, device=self.device,
            computer=self.computer,
        )
        second = session_service.record_entry_face_failure(
            challenge=result["challenge"], score=25, device=self.device,
            computer=self.computer,
        )
        self.assertEqual(second["attempts"], 2)

        # Shu challenge bilan sessiya baribir ochiladi.
        session = session_service.verify_initial_face(
            challenge=result["challenge"],
            embedding=[0.1] * 512,
            score=88,
            faces_detected=1,
            device=self.device,
            computer=self.computer,
        )
        self.assertEqual(session.status, ExamSession.Status.READY)

    def test_expired_challenge_is_refused(self):
        with self.assertRaises(SessionNotFound):
            session_service.record_entry_face_failure(
                challenge="yo-q-challenge", score=10, device=self.device,
                computer=self.computer,
            )


class PeriodicFaceTests(SessionFlowTestCase):
    """
    Test davomidagi tekshiruv - SOLISHTIRISH CLIENTDA.

    Server ballni qayta hisoblamaydi (buning uchun rasmdan embedding
    olish kerak, ya'ni serverda ML runtime): u chegarani qo'llaydi,
    hisoblagichni yuritadi va chetlashtirish qarorini chiqaradi.
    """

    def setUp(self):
        super().setUp()
        from apps.controls import services as controls_services

        self.session = self._make_session()
        self.config = controls_services.get_client_config(self.exam)
        self.threshold = int(self.config["face"]["min_score_exam"])

    def _verify(self, score, faces=1, passed_since_last=0):
        return session_service.verify_periodic_face(
            session=self.session,
            score=score,
            faces_detected=faces,
            passed_since_last=passed_since_last,
            config=self.config,
        )

    def test_score_above_threshold_passes(self):
        result = self._verify(self.threshold + 5)
        self.assertTrue(result["passed"])
        self.assertEqual(result["fail_count"], 0)

    def test_log_source_is_client(self):
        """
        Ball CLIENTNIKI va buni bayonnomada ko'rsatib turish shart.

        `source` "kim hisobladi" degan savolga javob beradi; server
        uni qayta hisoblay olmaydi.
        """
        self._verify(10)
        log = FaceVerificationLog.objects.filter(
            stage=FaceVerificationLog.Stage.PERIODIC
        ).latest("id")
        self.assertEqual(log.source, FaceVerificationLog.Source.CLIENT)
        self.assertEqual(log.threshold, self.threshold)

    def test_mismatch_increments_fail_counter_and_creates_event(self):
        result = self._verify(self.threshold - 30)

        self.assertFalse(result["passed"])
        self.assertEqual(result["fail_count"], 1)
        self.assertTrue(
            ProctoringEvent.objects.filter(
                type=ProctoringEvent.Type.FACE_MISMATCH
            ).exists()
        )

    def test_passed_since_last_resets_the_counter(self):
        """
        Faqat KETMA-KET muvaffaqiyatsizliklar hisobga olinadi.

        Client faqat xatolarni yuboradi, ya'ni oradagi muvaffaqiyatli
        tekshiruvlar sonini AYTISHI kerak - aks holda server ikki soat
        oralab kelgan uchta xatoni "ketma-ket" deb o'qirdi.
        """
        low = self.threshold - 30
        self._verify(low)
        result = self._verify(low, passed_since_last=4)
        self.assertEqual(result["fail_count"], 1)

    def test_limit_notifies_the_panel_but_does_not_terminate(self):
        """
        Chegaraga yetish — XABAR, chetlashtirish emas.

        Qarorni proktor qabul qiladi: u kadrni va dalil rasmlarini
        ko'rib turibdi, client esa faqat ballni biladi. Yorug'lik
        o'zgarishi tufayli ketma-ket uchta past ball butun imtihonni
        bekor qilishi mumkin emas.
        """
        low = max(0, self.threshold - 30)
        max_fail = int(self.config["face"]["max_fail"])
        for _ in range(max_fail - 1):
            self.assertFalse(self._verify(low)["limit_reached"])

        result = self._verify(low)
        self.assertTrue(result["limit_reached"])

        # Sessiya TIRIK qoladi.
        self.session.refresh_from_db()
        self.assertNotIn(self.session.status, ExamSession.TERMINAL_STATUSES)

        # Panelga kritik hodisa ketdi.
        event = ProctoringEvent.objects.filter(
            type=ProctoringEvent.Type.HIGH_SUSPICION_IDENTITY
        ).latest("id")
        self.assertEqual(event.severity, ProctoringEvent.Severity.CRITICAL)
        self.assertEqual(event.payload["source"], "periodic_face")
        self.assertEqual(event.payload["fail_count"], max_fail)

    def test_limit_event_is_sent_once_per_streak(self):
        """
        Chegaradan keyingi har bir xato yana kritik hodisa bermaydi.

        Bergan taqdirda panel bir xil xabar bilan to'lar va proktor
        uni o'qishni to'xtatardi; tarkibiy `face_mismatch` hodisalari
        esa avvalgidek kelaveradi.
        """
        low = max(0, self.threshold - 30)
        max_fail = int(self.config["face"]["max_fail"])
        for _ in range(max_fail + 2):
            self._verify(low)

        self.assertEqual(
            ProctoringEvent.objects.filter(
                type=ProctoringEvent.Type.HIGH_SUSPICION_IDENTITY
            ).count(),
            1,
        )

    def test_multiple_faces_creates_its_own_event_type(self):
        # Ball yuqori, lekin kadrda ikkita yuz - bu ham xato.
        self._verify(self.threshold + 5, faces=2)
        self.assertTrue(
            ProctoringEvent.objects.filter(
                type=ProctoringEvent.Type.MULTIPLE_FACES
            ).exists()
        )

    def test_no_face_creates_its_own_event_type(self):
        self._verify(0, faces=0)
        self.assertTrue(
            ProctoringEvent.objects.filter(
                type=ProctoringEvent.Type.FACE_NOT_FOUND
            ).exists()
        )

    def test_face_checks_counter_is_not_touched(self):
        """
        `face_checks` ni SERVER SANAMAYDI.

        Unga faqat muvaffaqiyatsiz tekshiruvlar keladi; jami sonni
        client heartbeat bilan yozadi. Server ham sanasa, bir xil
        tekshiruv ikki marta hisoblanardi.
        """
        self._verify(10)
        state = session_state.get_state(self.session.pk)
        self.assertEqual(int(state.get("face_checks", 0) or 0), 0)
        self.assertEqual(int(state.get("face_fails", 0) or 0), 1)


class PlatformContractTests(SessionFlowTestCase):
    """
    Platforma javobidan WebView havolasigacha — uchidan-uchiga.

    Bu yerda MOCK O'CHIRILADI va HTTP qatlami o'rniga platformaning
    hujjatidagi namuna javob qo'yiladi. Sabab: oradagi har bir
    bo'g'in (talqin -> pending -> sessiya -> `exam/access/`)
    alohida sinalgan, lekin ular ORASIDAGI shartnoma faqat shu
    yerda tekshiriladi. Aynan o'sha joyda maydon nomi adashsa,
    xato imtihon kuni chiqardi.
    """

    SUCCESS = {
        "status": 1,
        "message": "Success",
        "data": {
            "id": 72235,
            "abitur_id": 72441,
            "imie": 30309975270036,
            "is_finished": 1,
            "image_base64": "data:image/jpeg;base64,QUJD",
            "lname": "TO‘RAYEV",
            "fname": "YUSUF",
            "mname": "JUMMA O‘G‘LI",
            "duration_time": 180,
            "test_link": "https://test.uz/login?token=-JNtDZDDcPgkdXRgQab7fBjs3Hs",
            "message": "Testga ruxsat!",
            "status": True,
        },
    }

    def _flow(self, payload):
        from unittest.mock import patch

        from django.test import override_settings

        conf = dict(settings.EXTERNAL_PLATFORM, MOCK=False)
        with override_settings(EXTERNAL_PLATFORM=conf), patch(
            "apps.integrations.exam_site._request", return_value=payload
        ):
            return self._lookup()

    def test_reference_photo_reaches_the_client(self):
        """
        `image_base64` -> FaceID etaloni.

        Solishtirish uchun AYNAN shu rasm ishlatiladi; `data:` prefiksi
        olib tashlanadi, chunki client toza base64 kutadi.
        """
        result = self._flow(self.SUCCESS)

        self.assertTrue(result["has_reference_face"])
        self.assertEqual(result["candidate"]["photo_base64"], "QUJD")

    def test_platform_message_reaches_the_client(self):
        result = self._flow(self.SUCCESS)
        self.assertEqual(result["platform"]["message"], "Testga ruxsat!")

    def test_name_and_duration_reach_the_client(self):
        """
        `lname`/`fname`/`mname` va `duration_time` — ikkala sahifada.

        Client ularni talabgor kartasida va FaceID sahifasida
        ko'rsatadi. Maydon nomi adashsa, ekranda jimgina niqoblangan
        JSHSHIR qolardi va nosozlik "platforma ism bermadi" bo'lib
        ko'rinardi.
        """
        result = self._flow(self.SUCCESS)
        candidate = result["candidate"]

        self.assertEqual(candidate["last_name"], "TO‘RAYEV")
        self.assertEqual(candidate["first_name"], "YUSUF")
        self.assertEqual(candidate["full_name"], "TO‘RAYEV YUSUF JUMMA O‘G‘LI")
        # Davomiylik DAQIQADA ketadi: "3 soat" ko'rinishi client
        # tomondagi taqdimot qarori.
        self.assertEqual(result["duration_minutes"], 180)

    def test_duration_is_frozen_into_the_session(self):
        """
        Davomiylik sessiyaga MUZLATILADI.

        Platforma qiymatni keyin o'zgartirsa ham, bayonnomada
        talabgorga AYNAN qancha vaqt berilgani qolishi kerak.
        """
        from unittest.mock import patch as mock_patch

        from django.test import override_settings

        conf = dict(settings.EXTERNAL_PLATFORM, MOCK=False)
        with override_settings(EXTERNAL_PLATFORM=conf), mock_patch(
            "apps.integrations.exam_site._request", return_value=self.SUCCESS
        ):
            lookup = self._lookup()
            session = session_service.verify_initial_face(
                challenge=lookup["challenge"],
                embedding=[0.1] * 512,
                score=None,
                faces_detected=1,
                device=self.device,
                computer=self.computer,
            )

        self.assertEqual(session.meta["platform"]["duration_minutes"], 180)
        self.assertEqual(session.last_name, "TO‘RAYEV")

    def test_test_link_is_not_exposed_before_face_check(self):
        """
        Havola JSHSHIR tekshiruvida BERILMAYDI.

        Berilsa, FaceID va operator tasdig'ini butunlay chetlab
        o'tish mumkin bo'lardi: havolani nusxalab, brauzerda
        ochish kifoya edi.
        """
        result = self._flow(self.SUCCESS)

        self.assertNotIn("test_link", str(result))

    def test_link_reaches_the_webview_after_identity(self):
        from unittest.mock import patch

        from django.test import override_settings

        conf = dict(settings.EXTERNAL_PLATFORM, MOCK=False)
        with override_settings(EXTERNAL_PLATFORM=conf), patch(
            "apps.integrations.exam_site._request", return_value=self.SUCCESS
        ):
            lookup = self._lookup()
            session = session_service.verify_initial_face(
                challenge=lookup["challenge"],
                embedding=[0.1] * 512,
                score=None,
                faces_detected=1,
                device=self.device,
                computer=self.computer,
            )
        session_service.confirm_identity(
            session, actor=self.operator, document_type="passport", document_number="A1"
        )

        access = session_service.issue_exam_access(session)

        self.assertEqual(access["login_url"], self.SUCCESS["data"]["test_link"])
        # Allowlist AYNAN o'sha havoladan olinadi, `site_url` dan emas.
        self.assertIn("test.uz", access["allowed_domains"])

    def test_is_finished_does_not_block_the_webview(self):
        """
        `is_finished: 1` WebView'ni TO'SMAYDI.

        Platformaning namunasida u `1` bo'lgani holda ruxsat
        berilgan. Uni `external_status="finished"` deb yozish
        `_CLOSED_PLATFORM_STATUSES` orqali imtihonni to'sardi.
        """
        from unittest.mock import patch

        from django.test import override_settings

        conf = dict(settings.EXTERNAL_PLATFORM, MOCK=False)
        with override_settings(EXTERNAL_PLATFORM=conf), patch(
            "apps.integrations.exam_site._request", return_value=self.SUCCESS
        ):
            lookup = self._lookup()
            session = session_service.verify_initial_face(
                challenge=lookup["challenge"],
                embedding=[0.1] * 512,
                score=None,
                faces_detected=1,
                device=self.device,
                computer=self.computer,
            )
        session_service.confirm_identity(
            session, actor=self.operator, document_type="passport", document_number="A1"
        )

        # Istisno TASHLANMASLIGI kerak.
        session_service.issue_exam_access(session)
        self.assertTrue(session.meta["platform"]["is_finished"])


class IdentityConfirmWithoutDocumentTests(TestCase):
    """
    Hujjat maydonlarisiz tasdiqlash — client aynan shunday yuboradi.

    Operator hujjatni EKRANDA ko'zi bilan tekshiradi: hujjat rasmi
    chapda, jonli kadr o'ngda. Raqamni qo'lda kiritish har talabgorda
    takrorlanadigan ish edi va u tekshiruvga hech nima qo'shmasdi -
    operator baribir o'sha raqamni hujjatdan ko'chirardi.

    Audit izi SAQLANADI: kim tasdiqlagani va qachon - `identity`
    meta'sida, ya'ni "kim javobgar" savoliga javob bor.
    """

    def setUp(self):
        from apps.proctoring.api.v1.client_serializers import IdentityConfirmSerializer

        self.serializer_class = IdentityConfirmSerializer

    def test_confirm_without_document_fields(self):
        serializer = self.serializer_class(data={"decision": "confirm"})
        serializer.is_valid(raise_exception=True)

        # Kalitlar MAVJUD bo'lishi shart: view ularni to'g'ridan-to'g'ri
        # o'qiydi va `default` bo'lmasa `KeyError` bilan 500 qaytarardi.
        self.assertEqual(serializer.validated_data["document_type"], "")
        self.assertEqual(serializer.validated_data["document_number"], "")
        self.assertEqual(serializer.validated_data["note"], "")

    def test_reject_still_requires_a_reason(self):
        """
        Rad etish sababsiz bo'lmaydi va bu qoida SAQLANDI.

        Tasdiqlashdan farqi javobgarlikda: rad etish talabgorni
        imtihondan chetlatadi va qaror apellyatsiyaga tushishi
        mumkin - sababsiz yozuv "nega qo'yilmagan?" degan savolga
        javob bermasdi.
        """
        serializer = self.serializer_class(data={"decision": "reject"})
        self.assertFalse(serializer.is_valid())
        self.assertIn("reason", serializer.errors)

    def test_document_fields_are_still_accepted(self):
        """Maydonlar API'da qoldi — boshqa o'rnatish ularni yuborishi mumkin."""
        serializer = self.serializer_class(
            data={
                "decision": "confirm",
                "document_type": "passport",
                "document_number": "AA1234567",
            }
        )
        serializer.is_valid(raise_exception=True)
        self.assertEqual(serializer.validated_data["document_type"], "passport")
