"""
FaceID kadri: saqlash, berish va tozalash.

Uch mavzu va ular uchtala qarordan kelib chiqadi:

  1. **Sessiyasiz urinish.** Kirishdagi tekshiruv sessiya
     YARATILISHIDAN oldin bo'ladi, ya'ni "kira olmadi" holatini
     sessiyaga bog'lab bo'lmaydi - aynan o'sha holat esa eng
     qimmatli yozuv.
  2. **Rasm - dalil, to'siq emas.** Buzilgan JPEG tekshiruvni
     yiqitmasligi kerak: qator rasmsiz yoziladi.
  3. **Tozalash faylni oladi, qatorni QOLDIRADI.** Ball, chegara va
     vaqt bayonnomaning qismi va rasm muddati tugagani uchun
     yo'qolmasligi kerak.
"""

import io
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from PIL import Image

from apps.common.screenshot_storage import get_screenshot_storage
from apps.controls import services as controls_services
from apps.common.tests.utils import RedisStateMixin
from apps.proctoring.models import FaceVerificationLog
from apps.proctoring.services import face_images
from apps.proctoring.services import session as session_service
from apps.proctoring.tasks import purge_expired_face_images
from apps.proctoring.tests import factories


def image_bytes(fmt="JPEG", size=(320, 240)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, "red").save(buffer, format=fmt)
    return buffer.getvalue()


class StorePathTests(TestCase):
    def setUp(self):
        self.exam = factories.make_exam()

    def test_pending_path_when_session_is_missing(self):
        """
        Sessiyasiz urinish `pending/` katalogiga tushadi.

        Guruhlaydigan sessiyaning o'zi yo'q, `0/` yoki bo'sh segment
        esa yo'lni tushunarsiz qilardi.
        """
        path, purge_after = face_images.store(
            data=image_bytes(), exam_id=self.exam.pk, session=None
        )
        self.assertTrue(path.startswith("faceid/{}/pending/".format(self.exam.pk)))
        self.assertTrue(path.endswith(".jpg"))
        self.assertGreater(purge_after, timezone.now())
        self.assertTrue(get_screenshot_storage().exists(path))

    def test_rejects_non_image_bytes(self):
        """
        Tur BAYTLARDAN aniqlanadi.

        `.jpg` niqobidagi HTML `internal` location'dan berilsa, bu
        saqlangan XSS bo'lardi.
        """
        with self.assertRaises(Exception):
            face_images.store(
                data=b"<html><script>alert(1)</script></html>",
                exam_id=self.exam.pk,
            )

    def test_discard_removes_the_file(self):
        path, _ = face_images.store(data=image_bytes(), exam_id=self.exam.pk)
        self.assertTrue(face_images.discard(path))
        self.assertFalse(get_screenshot_storage().exists(path))

    def test_purge_after_follows_frame_retention(self):
        """
        Muddat DALIL KADRI bilan bir xil: bu ham talabgorning yuzi.
        """
        policy = {"evidence": {"frame_retention_days": 3}}
        moment = face_images.purge_after(policy)
        self.assertLess(moment, timezone.now() + timedelta(days=3, minutes=1))
        self.assertGreater(moment, timezone.now() + timedelta(days=2))


class EntryImageTests(RedisStateMixin, TestCase):
    """Kirishdagi tekshiruv rasmni ham saqlaydi."""

    def setUp(self):
        super().setUp()
        self.exam = factories.make_exam()
        self.schedule = factories.make_schedule(exam=self.exam)
        self.device = factories.make_device()
        self.computer = self.device.computer

    def _lookup(self, pinfl="30000000000001"):
        return session_service.lookup_candidate(
            pinfl=pinfl, exam=self.exam, device=self.device, zone=self.computer.zone
        )

    def test_successful_entry_stores_the_frame(self):
        result = self._lookup()
        session = session_service.verify_initial_face(
            challenge=result["challenge"],
            embedding=[0.1] * 512,
            score=90,
            image=image_bytes(),
            faces_detected=1,
            device=self.device,
            computer=self.computer,
        )
        log = FaceVerificationLog.objects.get(session=session)
        self.assertTrue(log.image_path)
        # Fayl SESSIYA katalogida: bitta imtihonning hamma izi bir joyda.
        self.assertIn("/{}/".format(session.pk), log.image_path)
        self.assertTrue(get_screenshot_storage().exists(log.image_path))
        self.assertIsNotNone(log.image_purge_after)

    def test_entry_stores_the_document_photo_too(self):
        """
        Kirishda IKKITA rasm saqlanadi: hujjat va jonli kadr.

        Ballning o'zi hech narsani isbotlamaydi - apellyatsiyada
        "47 ball" degan yozuv emas, hujjatdagi odam va kameradagi
        odam YONMA-YON kerak bo'ladi.
        """
        result = self._lookup()
        session = session_service.verify_initial_face(
            challenge=result["challenge"],
            embedding=[0.1] * 512,
            score=90,
            image=image_bytes(),
            reference_image=image_bytes(),
            faces_detected=1,
            device=self.device,
            computer=self.computer,
        )
        log = FaceVerificationLog.objects.get(session=session)

        self.assertTrue(log.reference_image_path)
        self.assertNotEqual(log.reference_image_path, log.image_path)
        # Nomdan qaysi biri hujjat rasmi ekani ko'rinadi.
        self.assertIn("_ref", log.reference_image_path)
        self.assertTrue(get_screenshot_storage().exists(log.reference_image_path))

    def test_periodic_check_has_no_document_photo(self):
        """
        Test davomida hujjat rasmi SAQLANMAYDI.

        U yerda etalon pasport rasmi emas, kirishda tasdiqlangan
        kadr - va uni har 10 soniyada qayta yozish bir xil rasmni
        yuzlab marta diskka tushirardi.
        """
        result = self._lookup()
        session = session_service.verify_initial_face(
            challenge=result["challenge"],
            embedding=[0.1] * 512,
            score=90,
            image=image_bytes(),
            reference_image=image_bytes(),
            faces_detected=1,
            device=self.device,
            computer=self.computer,
        )
        session_service.verify_periodic_face(
            session=session,
            score=10,
            faces_detected=1,
            image=image_bytes(),
            config=controls_services.get_client_config(self.exam),
        )
        periodic = FaceVerificationLog.objects.filter(
            session=session, stage=FaceVerificationLog.Stage.PERIODIC
        ).first()

        self.assertIsNotNone(periodic)
        self.assertTrue(periodic.image_path)
        self.assertEqual(periodic.reference_image_path, "")

    def test_broken_image_does_not_block_the_session(self):
        """
        RASM - DALIL, TO'SIQ EMAS.

        Buzilgan fayl uchun sessiyani ochmaslik butun imtihonni
        to'xtatardi; sabab log'da qoladi.
        """
        result = self._lookup()
        session = session_service.verify_initial_face(
            challenge=result["challenge"],
            embedding=[0.1] * 512,
            score=90,
            image=b"bu rasm emas",
            faces_detected=1,
            device=self.device,
            computer=self.computer,
        )
        log = FaceVerificationLog.objects.get(session=session)
        self.assertEqual(log.image_path, "")

    def test_failed_attempt_stores_the_frame_without_session(self):
        result = self._lookup()
        outcome = session_service.record_entry_face_failure(
            challenge=result["challenge"],
            score=22,
            image=image_bytes(),
            device=self.device,
            computer=self.computer,
        )
        log = FaceVerificationLog.objects.get(pk=outcome["id"])
        self.assertIsNone(log.session_id)
        self.assertIn("/pending/", log.image_path)
        self.assertTrue(get_screenshot_storage().exists(log.image_path))


class PurgeTests(TestCase):
    """Tozalash faylni oladi, QATORNI QOLDIRADI."""

    def setUp(self):
        self.exam = factories.make_exam()

    def _row(self, *, expired: bool) -> FaceVerificationLog:
        path, _ = face_images.store(data=image_bytes(), exam_id=self.exam.pk)
        return FaceVerificationLog.objects.create(
            exam=self.exam,
            stage=FaceVerificationLog.Stage.INITIAL,
            score=40,
            threshold=70,
            passed=False,
            image_path=path,
            image_purge_after=timezone.now()
            + timedelta(days=-1 if expired else 30),
            occurred_at=timezone.now(),
        )

    def test_expired_image_is_removed_but_row_survives(self):
        row = self._row(expired=True)
        path = row.image_path

        result = purge_expired_face_images()

        row.refresh_from_db()
        self.assertEqual(result["cleared"], 1)
        self.assertEqual(row.image_path, "")
        self.assertIsNone(row.image_purge_after)
        # Qatorning O'ZI qoladi: ball va vaqt bayonnomaning qismi.
        self.assertEqual(row.score, 40)
        self.assertFalse(get_screenshot_storage().exists(path))

    def test_fresh_image_is_kept(self):
        row = self._row(expired=False)
        purge_expired_face_images()
        row.refresh_from_db()
        self.assertTrue(row.image_path)
