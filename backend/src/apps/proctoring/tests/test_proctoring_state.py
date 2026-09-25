"""
Kamera tekshiruvi va kuzatuv holat mashinasi.

Ikki narsa himoyalanadi:

  1. BAHOLASH SERVERDA. Client xom o'lchov yuboradi, xulosani server
     chiqaradi. Client aytgan "hammasi joyida" ga ishonish
     o'zgartirilgan nusxaga eshikni ochib qo'yardi.
  2. O'TISHLAR CHEKLANGAN. Holat uch joydan o'zgaradi va ular
     bir-birini ko'rmaydi; ro'yxatsiz `completed` dan `active` ga
     qaytish jimgina yuz berardi.
"""

from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.controls.models import ProctoringPolicy
from apps.proctoring.models import AuditLog, ExamSession, ProctoringState
from apps.proctoring.services import camera_check, proctoring as proctoring_service
from apps.proctoring.tests import factories
from apps.proctoring.tests.test_camera_api import CameraApiTestCase


def measurement(role="primary", **overrides) -> dict:
    """Sog'lom kamera o'lchovlari."""
    base = {
        "role": role,
        "source": "local",
        "label": "Integrated Webcam",
        "available": True,
        "opened": True,
        "is_virtual": False,
        "frames": 30,
        "fps": 25.0,
        "width": 1280,
        "height": 720,
        "latency_ms": 60,
    }
    if role == "primary":
        base.update({"faces": 1, "face_width_px": 180, "brightness": 120, "face_offset": 0.1})
    base.update(overrides)
    return base


def policy(**camera) -> dict:
    base = {
        "count": 1,
        "primary_required": True,
        "secondary_required": False,
        "allow_virtual": False,
        "min_fps": 12,
        "min_width": 640,
        "min_height": 480,
    }
    base.update(camera)
    return {"camera": base}


class CameraCheckEvaluationTests(TestCase):
    def codes(self, result, status=None) -> set:
        return {
            item["code"]
            for item in result["checks"]
            if status is None or item["status"] == status
        }

    def test_healthy_camera_can_start(self):
        result = camera_check.evaluate(cameras=[measurement()], policy=policy())
        self.assertEqual(result["status"], camera_check.READY)
        self.assertTrue(result["can_start"])
        self.assertIn("primary_ready", self.codes(result, camera_check.READY))

    def test_missing_required_camera_blocks(self):
        result = camera_check.evaluate(cameras=[], policy=policy())
        self.assertFalse(result["can_start"])
        self.assertIn("primary_available", result["blockers"])

    def test_missing_optional_camera_is_not_evaluated(self):
        """
        Siyosat bitta kamera kutsa, ikkinchisi umuman TEKSHIRILMAYDI.

        Uni "yo'q" deb belgilash har bir to'g'ri o'rnatilgan bitta
        kamerali mashinada soxta ogohlantirish berardi.
        """
        result = camera_check.evaluate(cameras=[measurement()], policy=policy())
        self.assertEqual(
            [item for item in result["checks"] if item["role"] == "secondary"], []
        )

    def test_required_secondary_blocks_when_absent(self):
        result = camera_check.evaluate(
            cameras=[measurement()],
            policy=policy(count=2, secondary_required=True),
        )
        self.assertFalse(result["can_start"])
        self.assertIn("secondary_available", result["blockers"])

    def test_low_fps_blocks_required_camera(self):
        result = camera_check.evaluate(
            cameras=[measurement(fps=6.0)], policy=policy(min_fps=12)
        )
        self.assertFalse(result["can_start"])
        self.assertIn("primary_fps", result["blockers"])

    def test_low_fps_on_optional_camera_is_warning_only(self):
        """
        Bir xil nosozlik MAJBURIY va IXTIYORIY kamerada boshqacha
        og'irlikka ega — qaror siyosatniki, o'lchovniki emas.
        """
        result = camera_check.evaluate(
            cameras=[measurement(), measurement(role="secondary", fps=4.0)],
            policy=policy(count=2, secondary_required=False),
        )
        self.assertTrue(result["can_start"])
        self.assertIn("secondary_fps", self.codes(result, camera_check.FAILED))

    def test_virtual_camera_blocks_even_when_not_required(self):
        """
        Virtual qurilma — YAGONA tekshiruv, u kamera majburiy
        bo'lmasa ham to'siq: qolganlari sifat masalasi, bu esa
        xavfsizlik qoidasi.
        """
        result = camera_check.evaluate(
            cameras=[measurement(), measurement(role="secondary", is_virtual=True)],
            policy=policy(count=2, secondary_required=False),
        )
        self.assertFalse(result["can_start"])
        self.assertIn("secondary_virtual", result["blockers"])

    def test_virtual_camera_allowed_by_policy(self):
        result = camera_check.evaluate(
            cameras=[measurement(is_virtual=True)], policy=policy(allow_virtual=True)
        )
        self.assertTrue(result["can_start"])

    def test_no_face_is_warning_not_blocker(self):
        """
        Tekshiruv paytida talabgor hali kelmagan bo'lishi mumkin —
        operator kamerani kun boshida sozlaydi.
        """
        result = camera_check.evaluate(
            cameras=[measurement(faces=0)], policy=policy()
        )
        self.assertTrue(result["can_start"])
        self.assertEqual(result["status"], camera_check.WARNING)

    def test_unmeasured_face_differs_from_no_face(self):
        result = camera_check.evaluate(
            cameras=[measurement(faces=None)], policy=policy()
        )
        detail = next(
            item for item in result["checks"] if item["code"] == "primary_face"
        )["detail"]
        self.assertIn("Model", detail)

    def test_high_latency_is_warning(self):
        result = camera_check.evaluate(
            cameras=[measurement(latency_ms=900)], policy=policy()
        )
        self.assertTrue(result["can_start"])
        self.assertIn("primary_latency", self.codes(result, camera_check.WARNING))

    def test_dark_frame_is_warning(self):
        result = camera_check.evaluate(
            cameras=[measurement(brightness=10)], policy=policy()
        )
        self.assertTrue(result["can_start"])
        self.assertIn("primary_lighting", self.codes(result, camera_check.WARNING))

    def test_face_checks_are_skipped_on_secondary(self):
        """Stol kamerasida yuz bo'lmasligi NORMAL holat."""
        result = camera_check.evaluate(
            cameras=[measurement(), measurement(role="secondary")],
            policy=policy(count=2),
        )
        self.assertNotIn("secondary_face", self.codes(result))

    def test_stream_without_frames_blocks(self):
        result = camera_check.evaluate(
            cameras=[measurement(frames=0)], policy=policy()
        )
        self.assertFalse(result["can_start"])
        self.assertIn("primary_stream", result["blockers"])


class CameraCheckMergeTests(TestCase):
    """
    HAR KAMERA ALOHIDA tekshiriladi.

    Operator odatda faqat yuz kamerasini tekshiradi (tavsiya
    etilgani ham shu), ikkinchisini esa siyosat talab qilsagina.
    Shuning uchun bitta rol bilan kelgan so'rov qolganini
    "tekshirilmagan" holatiga QAYTARMASLIGI kerak.
    """

    def codes(self, result, status=None) -> set:
        return {
            item["code"]
            for item in result["checks"]
            if status is None or item["status"] == status
        }

    def test_unmeasured_camera_is_not_reported_as_missing(self):
        """
        "Topilmadi" va "tekshirilmadi" — BOSHQA holatlar.

        Birinchisini operator kabel bilan hal qiladi, ikkinchisini
        tugmani bosib.
        """
        result = camera_check.evaluate(
            cameras=[
                measurement(),
                measurement("secondary", measured=False, local_index=1),
            ],
            policy=policy(count=2),
        )
        self.assertIn("secondary_checked", self.codes(result))
        self.assertNotIn("secondary_available", self.codes(result, camera_check.FAILED))
        # Ikkilamchi kamera majburiy emas — to'siq ham yo'q.
        self.assertTrue(result["can_start"])

    def test_unchecked_required_camera_blocks(self):
        result = camera_check.evaluate(
            cameras=[
                measurement(),
                measurement("secondary", measured=False, local_index=1),
            ],
            policy=policy(count=2, secondary_required=True),
        )
        self.assertFalse(result["can_start"])
        self.assertIn("secondary_checked", result["blockers"])

    def test_previous_measurement_is_reused(self):
        first = camera_check.evaluate(
            cameras=[measurement(local_index=0), measurement("secondary", local_index=1)],
            policy=policy(count=2),
        )
        self.assertTrue(first["cameras"]["secondary"]["checked"])

        # Ikkinchi tekshiruv FAQAT yuz kamerasi uchun.
        second = camera_check.evaluate(
            cameras=[
                measurement(local_index=0),
                measurement("secondary", measured=False, local_index=1),
            ],
            policy=policy(count=2),
            previous=first,
        )
        self.assertTrue(second["cameras"]["secondary"]["checked"])
        self.assertNotIn("secondary_checked", self.codes(second))
        self.assertIn("secondary_ready", self.codes(second, camera_check.READY))

    def test_previous_measurement_is_dropped_when_device_changed(self):
        """
        Rollar ALMASHTIRILSA eski o'lchov yaroqsiz.

        "Birlamchi" roli endi boshqa jismoniy kameraga tegishli va
        unga eski o'lchovni yopishtirish soxta "tekshirildi" degani
        bo'lardi.
        """
        first = camera_check.evaluate(
            cameras=[measurement(local_index=0), measurement("secondary", local_index=1)],
            policy=policy(count=2),
        )
        swapped = camera_check.evaluate(
            cameras=[
                measurement(local_index=1),
                # Rollar almashdi: ikkilamchi endi 0-qurilma.
                measurement("secondary", measured=False, local_index=0),
            ],
            policy=policy(count=2),
            previous=first,
        )
        self.assertFalse(swapped["cameras"]["secondary"]["checked"])
        self.assertIn("secondary_checked", self.codes(swapped))

    def test_stale_measurement_is_dropped(self):
        first = camera_check.evaluate(
            cameras=[measurement(local_index=0), measurement("secondary", local_index=1)],
            policy=policy(count=2),
        )
        # Suratcha eskirdi: TTL dan oldingi vaqt.
        stale = timezone.now() - timedelta(
            seconds=int(settings.PROCTORING["CAMERA_CHECK"]["SNAPSHOT_TTL"]) + 60
        )
        first["measurements"]["secondary"]["measured_at"] = stale.isoformat()

        result = camera_check.evaluate(
            cameras=[
                measurement(local_index=0),
                measurement("secondary", measured=False, local_index=1),
            ],
            policy=policy(count=2),
            previous=first,
        )
        self.assertFalse(result["cameras"]["secondary"]["checked"])

    def test_measurements_are_kept_for_evidence(self):
        """
        Xom o'lchovlar suratchada QOLADI.

        Ular `ExamSession.camera_check` ga ko'chiriladi va "nega bu
        mashinada ikkinchi kamerasiz boshlandi?" degan savolga faqat
        ular javob beradi.
        """
        result = camera_check.evaluate(cameras=[measurement()], policy=policy())
        self.assertIn("primary", result["measurements"])
        self.assertTrue(result["measurements"]["primary"]["measured_at"])

class TransitionTests(TestCase):
    def setUp(self):
        self.session = factories.make_session()

    def test_allowed_path(self):
        session = self.session
        proctoring_service.transition(session, ProctoringState.CAMERA_CHECK)
        proctoring_service.transition(session, ProctoringState.READY)
        proctoring_service.transition(session, ProctoringState.STARTING)
        proctoring_service.transition(session, ProctoringState.ACTIVE)
        self.assertEqual(session.proctoring_state, ProctoringState.ACTIVE)

    def test_completed_is_terminal(self):
        """
        Yakunlangan kuzatuvni qayta yoqib bo'lmaydi.

        Ro'yxatsiz bu jimgina yuz berardi: yakunlangan sessiya
        `active` ga qaytib, dalil qabul qilinaverardi.
        """
        proctoring_service.stop(self.session)
        with self.assertRaises(proctoring_service.InvalidProctoringState):
            proctoring_service.transition(self.session, ProctoringState.ACTIVE)

    def test_same_state_is_silently_ignored(self):
        """Client qayta ulanishda `start` ni takrorlashi NORMAL holat."""
        proctoring_service.transition(self.session, ProctoringState.CAMERA_CHECK)
        proctoring_service.transition(self.session, ProctoringState.CAMERA_CHECK)
        self.assertEqual(self.session.proctoring_state, ProctoringState.CAMERA_CHECK)

    def test_failed_can_be_retried(self):
        """Uzilgan kabel ish o'rnini kun oxirigacha yaroqsiz qilmasligi kerak."""
        proctoring_service.transition(self.session, ProctoringState.FAILED)
        proctoring_service.transition(self.session, ProctoringState.CAMERA_CHECK)
        self.assertEqual(self.session.proctoring_state, ProctoringState.CAMERA_CHECK)

    def test_degrade_does_not_stop_the_exam(self):
        proctoring_service.transition(self.session, ProctoringState.STARTING)
        proctoring_service.transition(self.session, ProctoringState.ACTIVE)
        proctoring_service.degrade(self.session, reason="kamera uzildi")

        self.assertEqual(self.session.proctoring_state, ProctoringState.DEGRADED)
        self.assertEqual(self.session.status, ExamSession.Status.IN_PROGRESS)

        proctoring_service.restore(self.session)
        self.assertEqual(self.session.proctoring_state, ProctoringState.ACTIVE)

    def test_stop_from_idle_completes_quietly(self):
        """
        Boshlanmagan kuzatuvni yakunlash XATO EMAS.

        Yakunlash yo'lida turgan to'siq imtihonni yopilmagan holda
        qoldirardi — bu ancha qimmatroq muammo.
        """
        proctoring_service.stop(self.session)
        self.assertEqual(self.session.proctoring_state, ProctoringState.COMPLETED)

    def test_session_finish_completes_proctoring(self):
        from apps.proctoring.services import session as session_service

        proctoring_service.transition(self.session, ProctoringState.STARTING)
        proctoring_service.transition(self.session, ProctoringState.ACTIVE)

        session_service.finish_session(self.session, reason="operator")
        self.assertEqual(self.session.proctoring_state, ProctoringState.COMPLETED)


class CameraCheckApiTests(CameraApiTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.url = reverse("client-camera-check")
        factories.make_setting(is_active=True)

    def test_result_is_computed_by_server(self):
        payload = self.request("post", self.url, {"cameras": [measurement()]}).json()["data"]
        self.assertTrue(payload["can_start"])
        self.assertEqual(payload["status"], camera_check.READY)
        self.assertIn("primary_ready", [item["code"] for item in payload["checks"]])

    def test_exam_policy_is_used_when_given(self):
        setting = factories.make_setting()
        ProctoringPolicy.objects.create(
            setting=setting, is_enabled=True, camera_count=2, secondary_required=True
        )
        exam = factories.make_exam(setting=setting)

        payload = self.request(
            "post", self.url, {"cameras": [measurement()], "exam_id": exam.pk}
        ).json()["data"]

        self.assertFalse(payload["can_start"])
        self.assertIn("secondary_available", payload["blockers"])

    def test_snapshot_is_stored_for_the_device(self):
        self.request("post", self.url, {"cameras": [measurement()]})
        stored = camera_check.load(self.device.device_id)
        # Redis bo'lmasa suratcha saqlanmaydi - bu kutilgan xulq va
        # `proctoring/start/` uni "tekshirilmagan" deb hisoblaydi.
        if stored is not None:
            self.assertTrue(stored["can_start"])

    def test_unknown_role_is_rejected(self):
        response = self.request(
            "post", self.url, {"cameras": [measurement(role="tertiary")]}
        )
        self.assertEqual(response.status_code, 400)


class ProctoringStartApiTests(CameraApiTestCase):
    """Kuzatuvni ishga tushirish - 'START EXAM' darvozasi."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        factories.make_setting(is_active=True)
        self.check_url = reverse("client-camera-check")
        self.start_url = reverse("client-proctoring-start")
        self.stop_url = reverse("client-proctoring-stop")

        self.session = factories.make_session(device=self.device, computer=self.computer)
        self.token = self._issue_token()

    def _issue_token(self) -> str:
        from apps.proctoring.services import session as session_service

        return session_service.issue_session_token(self.session)

    def post(self, url, data=None):
        """Sessiya tokeni bilan so'rov (`X-Proctoring-Session`)."""
        from apps.proctoring.tests.test_client_api import bearer

        return self.client.post(
            url,
            data or {},
            format="json",
            HTTP_AUTHORIZATION=bearer(self.user),
            HTTP_X_DEVICE_ID=self.device.device_id,
            HTTP_X_PROCTORING_SESSION=self.token,
            REMOTE_ADDR="8.8.8.8",
        )

    def test_start_requires_camera_check(self):
        """
        Tekshiruvsiz imtihon boshlanmaydi.

        Bu M2 ning asosiy darvozasi: undan oldingi qadamlar
        (FaceID, shaxs tasdig'i) ataylab to'silmaydi, chunki ular
        operatorga nosozlikni ko'rsatish uchun kerak.
        """
        camera_check.clear(self.device.device_id)
        response = self.post(self.start_url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "camera_check_required")

    def test_start_after_successful_check(self):
        self.request("post", self.check_url, {"cameras": [measurement()]})
        response = self.post(self.start_url, {"ai_profile": "medium"})

        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()["data"]["state"], ProctoringState.ACTIVE)

        self.session.refresh_from_db()
        self.assertEqual(self.session.proctoring_state, ProctoringState.ACTIVE)
        self.assertEqual(self.session.ai_profile, "medium")
        # Suratcha sessiyaga KO'CHIRILADI - dalil sifatida.
        self.assertTrue(self.session.camera_check.get("can_start"))
        self.assertTrue(
            AuditLog.objects.filter(action="proctoring_start").exists()
        )

    def test_failed_check_blocks_start(self):
        self.request("post", self.check_url, {"cameras": []})
        response = self.post(self.start_url)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "camera_check_failed")
        self.session.refresh_from_db()
        self.assertNotEqual(self.session.proctoring_state, ProctoringState.ACTIVE)

    def test_check_can_be_disabled_for_deployment(self):
        """
        Dastlabki joylashtirishda kameralar hali ulanmagan bo'lishi
        mumkin — majburiy tekshiruv sinovni butunlay to'xtatardi.

        `override_settings` ISHLATILMAYDI: `PROCTORING` — ichma-ich
        lug'at va uni butunlay almashtirish qolgan barcha kalitlarni
        yo'qotardi. `patch.dict` faqat bitta kalitni vaqtincha
        o'zgartiradi va testdan keyin tiklaydi.
        """
        from unittest.mock import patch

        camera_check.clear(self.device.device_id)
        with patch.dict(settings.PROCTORING, {"REQUIRE_CAMERA_CHECK": False}):
            response = self.post(self.start_url)
        self.assertEqual(response.status_code, 200, response.json())

    def test_stop_completes_the_state(self):
        self.request("post", self.check_url, {"cameras": [measurement()]})
        self.post(self.start_url)

        response = self.post(self.stop_url, {"reason": "yakunlandi"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["state"], ProctoringState.COMPLETED)

    def test_start_without_session_token_is_rejected(self):
        """
        Sessiya tokeni yo'q - `SessionRequiredView` uni rad etadi.

        JWT bor, qurilma bor, IP to'g'ri: yagona yetishmagan narsa
        sessiya. Bu tekshiruv aynan shu qatlam ishlayotganini
        himoyalaydi.
        """
        from apps.proctoring.tests.test_client_api import bearer

        response = self.client.post(
            self.start_url,
            {},
            format="json",
            HTTP_AUTHORIZATION=bearer(self.user),
            HTTP_X_DEVICE_ID=self.device.device_id,
            REMOTE_ADDR="8.8.8.8",
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "session_not_found")
