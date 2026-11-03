"""
Test platformasiga natija yuborish (`integrations/platform_push.py`).

Qo'riqlanadigan qoidalar:

  1. Manzil BO'SH — hech narsa navbatga qo'yilmaydi (FaceID ham, skrinshot ham).
  2. FaceID: o'tgan VA o'tmagan urinish — rasm (`data:` URI), JSHSHIR, ball.
  3. Navbatga ID tushadi, rasm vazifa paytida storage'dan o'qiladi;
     almashgan savol kadri / yo'q fayl yuborilmaydi.
  4. 4xx — qayta urinilmaydi; tarmoq/5xx — qayta urinish, chegara bilan.
  5. Yuborish breaker'i JSHSHIR tekshiruvinikidan alohida.
"""

import base64
import io
from unittest import mock

import requests
from celery.exceptions import Retry
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from PIL import Image

from apps.common.screenshot_storage import get_screenshot_storage
from apps.common.tests.utils import RedisStateMixin
from apps.exams import services as exam_services
from apps.integrations import exam_site, platform_push, tasks
from apps.proctoring.models import FaceVerificationLog
from apps.proctoring.services import screenshots as screenshot_service
from apps.proctoring.services import session as session_service
from apps.proctoring.tests import factories

FACE_URL = "https://api.test.uz/faceid/result"
SHOT_URL = "https://api.test.uz/screenshot"


def jpeg(color="red") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(buffer, format="JPEG")
    return buffer.getvalue()


def response(status: int, text: str = "") -> mock.Mock:
    return mock.Mock(status_code=status, text=text)


class PostJsonTests(RedisStateMixin, TestCase):
    def post(self, side_effect):
        session = mock.Mock()
        session.post.side_effect = side_effect
        with mock.patch.object(exam_site, "_get_session", return_value=session):
            outcome = exam_site.post_json(
                url=FACE_URL, site_header="Authorization: Bearer t0k", payload={"a": 1},
            )
        return outcome, session

    def test_success_sends_json_with_exam_header(self):
        outcome, session = self.post([response(201)])
        self.assertEqual(outcome, exam_site.PUSH_SENT)
        _args, kwargs = session.post.call_args
        self.assertEqual(kwargs["json"], {"a": 1})
        self.assertEqual(kwargs["headers"], {"Authorization": "Bearer t0k"})

    def test_client_error_is_final(self):
        self.assertEqual(self.post([response(422, "imie yo'q")])[0], exam_site.PUSH_REJECTED)

    def test_transient_errors_are_retried(self):
        for side_effect in ([response(503)], [response(429)], requests.ConnectionError("x")):
            with self.subTest(side_effect=side_effect):
                self.assertEqual(self.post(side_effect)[0], exam_site.PUSH_RETRY)

    def test_push_breaker_is_separate_from_lookup(self):
        """Yiqilgan qabul endpointi JSHSHIR tekshiruvini to'smasin."""
        with mock.patch.object(exam_site, "_breaker", wraps=exam_site._breaker) as breaker:
            self.post([response(200)])
        breaker.assert_called_once_with("api.test.uz", "exam_site_push")


class FacePushTests(RedisStateMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.exam = factories.make_exam(external_code="ENG-1")
        factories.make_schedule(exam=self.exam)
        self.device = factories.make_device()

    def challenge(self, pinfl="30000000000001"):
        return session_service.lookup_candidate(
            pinfl=pinfl, exam=self.exam, device=self.device,
            zone=self.device.computer.zone, **factories.machine_of(self.device),
        )["challenge"]

    def fail_attempt(self, image=None):
        return session_service.record_entry_face_failure(
            challenge=self.challenge(), score=17, image=image,
            device=self.device, computer=self.device.computer,
        )

    def test_empty_url_enqueues_nothing(self):
        with mock.patch.object(tasks.push_face_result, "delay") as delay, \
                self.captureOnCommitCallbacks(execute=True):
            self.fail_attempt()
        delay.assert_not_called()

    def test_failed_and_passed_attempts_are_enqueued(self):
        self.exam.face_result_url = FACE_URL
        self.exam.save(update_fields=["face_result_url"])
        with mock.patch.object(tasks.push_face_result, "delay") as delay, \
                self.captureOnCommitCallbacks(execute=True):
            failed = self.fail_attempt()
            session = session_service.verify_initial_face(
                challenge=self.challenge(), embedding=[0.1] * 512, score=88,
                device=self.device, computer=self.device.computer,
            )
        passed = FaceVerificationLog.objects.get(session=session)
        self.assertEqual(
            [call.args for call in delay.call_args_list], [(failed["id"],), (passed.pk,)]
        )

    def test_payload_carries_photo_pinfl_and_score(self):
        self.exam.face_result_url = FACE_URL
        self.exam.save(update_fields=["face_result_url"])
        exam_services.set_site_header(self.exam, "X-Api-Key: k1")
        self.exam.save(update_fields=["site_header_encrypted"])
        image = jpeg()
        log_id = self.fail_attempt(image=image)["id"]

        with mock.patch.object(exam_site, "post_json", return_value=exam_site.PUSH_SENT) as post:
            self.assertEqual(platform_push.send_face_result(log_id), exam_site.PUSH_SENT)

        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["url"], FACE_URL)
        self.assertEqual(kwargs["site_header"], "X-Api-Key: k1")
        payload = kwargs["payload"]
        self.assertEqual(payload["type"], "face_result")
        self.assertEqual(payload["id"], log_id)
        self.assertEqual(payload["imie"], "30000000000001")
        self.assertFalse(payload["passed"])
        self.assertEqual(payload["score"], 17)
        self.assertEqual(payload["exam_code"], "ENG-1")
        self.assertIsNone(payload["session_id"])
        prefix = "data:image/jpeg;base64,"
        self.assertTrue(payload["image_base64"].startswith(prefix))
        self.assertEqual(base64.b64decode(payload["image_base64"][len(prefix):]), image)

    def test_missing_image_still_sends_result(self):
        self.exam.face_result_url = FACE_URL
        self.exam.save(update_fields=["face_result_url"])
        log_id = self.fail_attempt()["id"]
        with mock.patch.object(exam_site, "post_json", return_value=exam_site.PUSH_SENT) as post:
            platform_push.send_face_result(log_id)
        self.assertEqual(post.call_args.kwargs["payload"]["image_base64"], "")

    def test_url_cleared_before_task_runs(self):
        log_id = self.fail_attempt()["id"]
        with mock.patch.object(exam_site, "post_json") as post:
            self.assertEqual(platform_push.send_face_result(log_id), "skipped")
        post.assert_not_called()


class ScreenshotPushTests(RedisStateMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.session = factories.make_session()
        self.exam = self.session.exam

    def store(self, color="red", question_id="q1"):
        return screenshot_service.screenshot_store(
            session=self.session,
            upload=SimpleUploadedFile("s.jpg", jpeg(color), content_type="image/jpeg"),
            captured_at=timezone.now(), question_id=question_id, question_number=3,
        )

    def test_empty_url_enqueues_nothing(self):
        shot = self.store()
        with mock.patch.object(tasks.push_screenshot, "delay") as delay, \
                self.captureOnCommitCallbacks(execute=True):
            platform_push.schedule_fs_screenshot(shot, exam_id=self.exam.pk)
        delay.assert_not_called()

    def test_fs_screenshot_payload(self):
        self.exam.screenshot_url = SHOT_URL
        self.exam.save(update_fields=["screenshot_url"])
        shot = self.store()
        with mock.patch.object(tasks.push_screenshot, "delay") as delay, \
                self.captureOnCommitCallbacks(execute=True):
            platform_push.schedule_fs_screenshot(shot, exam_id=self.exam.pk)
        source, ref = delay.call_args.args
        # Navbatda rasm YO'Q — faqat ID va hash.
        self.assertEqual(ref, {"id": shot.pk, "content_hash": shot.content_hash})

        with mock.patch.object(exam_site, "post_json", return_value=exam_site.PUSH_SENT) as post:
            self.assertEqual(platform_push.send_screenshot(source, ref), exam_site.PUSH_SENT)
        payload = post.call_args.kwargs["payload"]
        self.assertEqual(post.call_args.kwargs["url"], SHOT_URL)
        self.assertEqual(payload["type"], "screenshot")
        self.assertEqual(payload["id"], f"fs:{shot.pk}")
        self.assertEqual(payload["session_id"], str(self.session.public_id))
        self.assertEqual((payload["q_id"], payload["q_n"]), ("q1", 3))
        self.assertTrue(payload["image_base64"].startswith("data:image/jpeg;base64,"))

    def test_replaced_question_shot_is_not_sent(self):
        """Javob o'zgardi — eski kadr yuborilmaydi, yangisining o'z vazifasi bor."""
        self.exam.screenshot_url = SHOT_URL
        self.exam.save(update_fields=["screenshot_url"])
        old = self.store("red")
        stale = {"id": old.pk, "content_hash": old.content_hash}
        self.store("blue")
        with mock.patch.object(exam_site, "post_json") as post:
            self.assertEqual(platform_push.send_screenshot(platform_push.SOURCE_FS, stale), "skipped")
        post.assert_not_called()

    def test_deleted_file_is_skipped(self):
        self.exam.screenshot_url = SHOT_URL
        self.exam.save(update_fields=["screenshot_url"])
        shot = self.store()
        get_screenshot_storage().delete(shot.file_path)
        with mock.patch.object(exam_site, "post_json") as post:
            outcome = platform_push.send_screenshot(
                platform_push.SOURCE_FS, {"id": shot.pk, "content_hash": shot.content_hash}
            )
        self.assertEqual(outcome, "skipped")
        post.assert_not_called()

    def test_s3_screenshot_enqueued_with_metadata(self):
        self.exam.screenshot_url = SHOT_URL
        self.exam.save(update_fields=["screenshot_url"])
        captured = timezone.now()
        with mock.patch.object(tasks.push_screenshot, "delay") as delay, \
                self.captureOnCommitCallbacks(execute=True):
            platform_push.schedule_s3_screenshot(
                self.session, object_key="2026/k.jpg", captured_at=captured, question_id="7",
            )
        source, ref = delay.call_args.args
        self.assertEqual(source, platform_push.SOURCE_S3)
        self.assertEqual(ref["object_key"], "2026/k.jpg")
        self.assertEqual(ref["session_id"], self.session.pk)

        with mock.patch("apps.common.storage.read_object", return_value=jpeg()), \
                mock.patch.object(exam_site, "post_json", return_value=exam_site.PUSH_SENT) as post:
            platform_push.send_screenshot(source, ref)
        payload = post.call_args.kwargs["payload"]
        self.assertEqual(payload["id"], "s3:2026/k.jpg")
        self.assertEqual(payload["captured_at"], captured.isoformat())


class TaskRetryTests(TestCase):
    def test_retry_then_give_up(self):
        with mock.patch.object(platform_push, "send_face_result", return_value=exam_site.PUSH_RETRY):
            with self.assertRaises(Retry):
                tasks.push_face_result.apply(args=(1,), throw=True)
            task = tasks.push_face_result
            task.push_request(retries=tasks.MAX_RETRIES)
            try:
                with self.assertLogs("apps.integrations.tasks", "ERROR"):
                    self.assertEqual(task.run(1), "failed")
            finally:
                task.pop_request()

    def test_rejected_is_not_retried(self):
        with mock.patch.object(platform_push, "send_screenshot", return_value=exam_site.PUSH_REJECTED):
            result = tasks.push_screenshot.apply(args=("fs", {"id": 1}), throw=True)
        self.assertEqual(result.result, exam_site.PUSH_REJECTED)
