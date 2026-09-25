"""
Mashinada qolgan yozuvlarni qayd etish (`client/recordings/`).

FAYL KELMAYDI va testlar aynan shu shartnomani qo'riqlaydi: ekran
yozuvi ~360 MB, kamera klipi hodisa sayin yig'iladi va ularni
yuklash 500 mashinali binoda kuniga yuzlab gigabayt degani.
Serverga faqat manzil keladi.
"""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.common.tests.utils import RedisStateMixin
from apps.proctoring.models import ExamSession, LocalRecording
from apps.proctoring.tests import factories
from apps.proctoring.tests.test_client_api import bearer


class _RecordingApiBase(RedisStateMixin, TestCase):
    """Umumiy tayyorgarlik - testlarsiz, aks holda meros oluvchi ularni qayta ishga tushirardi."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.url = reverse("client-recordings")
        self.device = factories.make_device()
        self.session = factories.make_session(device=self.device)
        self.operator = factories.make_user(permissions=["client.operate"])

        from apps.proctoring.services import session as session_service

        self.raw_token = session_service.issue_session_token(self.session)
        self.auth = bearer(self.operator)

    def _post(self, payload):
        return self.client.post(
            self.url,
            payload,
            format="json",
            HTTP_AUTHORIZATION=self.auth,
            HTTP_X_DEVICE_ID=self.device.device_id,
            HTTP_X_PROCTORING_SESSION=self.raw_token,
        )

    def _payload(self, **overrides):
        payload = {
            "kind": "screen",
            "local_path": r"D:\ProctoringArchive\Milliy\Matematika\2026-09-22\S1\screen.mp4",
            "captured_at": "2026-09-22T09:00:00Z",
            "size_bytes": 377_487_360,
            "duration_ms": 10_800_000,
            "width": 1280,
            "height": 720,
            "frames": 10_800,
        }
        payload.update(overrides)
        return payload



class LocalRecordingEndpointTests(_RecordingApiBase):
    def test_registers_screen_recording(self):
        response = self._post(self._payload())
        self.assertEqual(response.status_code, 201, response.content)

        recording = LocalRecording.objects.get(session=self.session)
        self.assertEqual(recording.kind, "screen")
        self.assertEqual(recording.size_bytes, 377_487_360)
        self.assertEqual(recording.frames, 10_800)
        # Qurilma yozuvdan MUSTAQIL topiladi: yozuv sessiyadan
        # uzoqroq yashaydi va "qaysi mashinada" degan javob
        # qatorning o'zida qolishi kerak.
        self.assertEqual(recording.device_id, self.device.device_id)

    def test_repeated_registration_updates_instead_of_duplicating(self):
        """
        TAKRORIY SO'ROV IKKINCHI QATOR YARATMAYDI.

        Client tarmoq xatosida qayta uradi va ikkinchi urinishdagi
        hajm birinchisinikidan farq qilishi mumkin (fayl yopilgan).
        Ikkita qator panelda "ikkita video bor" bo'lib ko'rinardi.
        """
        self._post(self._payload(size_bytes=1000))
        response = self._post(self._payload(size_bytes=2000))
        self.assertEqual(response.status_code, 201, response.content)

        recordings = LocalRecording.objects.filter(session=self.session)
        self.assertEqual(recordings.count(), 1)
        self.assertEqual(recordings.first().size_bytes, 2000)

    def test_clip_keeps_event_context(self):
        response = self._post(
            self._payload(
                kind="clip",
                local_path=r"D:\ProctoringArchive\Milliy\Matematika\2026-09-22\S1\clip_00001.mp4",
                event_type="phone_detected",
                camera_role="secondary",
                confidence=94,
            )
        )
        self.assertEqual(response.status_code, 201, response.content)

        recording = LocalRecording.objects.get(kind="clip")
        self.assertEqual(recording.event_type, "phone_detected")
        self.assertEqual(recording.camera_role, "secondary")
        self.assertEqual(recording.confidence, 94)

    def test_rejects_non_video_path(self):
        """
        Rasm bu endpointga tushmaydi.

        Skrinshot va dalil kadri AVVALGIDEK yuklanadi (ular kichik
        va proktorga real vaqtda kerak). Yo'lni bu yerda qabul
        qilish "qaysi rasm qayerda?" degan ikkinchi javobni
        yaratardi.
        """
        response = self._post(self._payload(local_path=r"D:\arxiv\shot_00001.jpg"))
        self.assertEqual(response.status_code, 400)

    def test_requires_session_token(self):
        """
        Sessiya tokenisiz yozuv qayd etilmaydi.

        `404` (`400` emas): bu `SessionRequiredView` ning umumiy
        shartnomasi - tokensiz so'rov uchun sessiya TOPILMAYDI va
        javob boshqa endpointlardagi bilan bir xil bo'lishi kerak.
        """
        response = self.client.post(
            self.url,
            self._payload(),
            format="json",
            HTTP_AUTHORIZATION=self.auth,
            HTTP_X_DEVICE_ID=self.device.device_id,
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("session", response.content.decode().lower())

    def test_detail_endpoint_exposes_recordings(self):
        """Panel yozuvni sessiya tafsilotida ko'radi."""
        self._post(self._payload())

        staff = factories.make_user(permissions=["sessions.view"])
        response = self.client.get(
            reverse("session-detail", args=[self.session.pk]),
            HTTP_AUTHORIZATION=bearer(staff),
        )
        self.assertEqual(response.status_code, 200, response.content)
        recordings = response.json()["data"]["local_recordings"]
        self.assertEqual(len(recordings), 1)
        self.assertEqual(recordings[0]["kind"], "screen")
        self.assertEqual(recordings[0]["size_mb"], 360.0)
        # `file://` ko'rinishi panelda nusxalash uchun.
        self.assertTrue(recordings[0]["file_url"].startswith("file:///"))


class LateRecordingRegistrationTests(_RecordingApiBase):
    """
    Token BEKOR BO'LGANDAN keyingi qayd - chetlashtirilgan sessiya.

    Proktor chetlashtirganda token client bilmagan holda o'chadi,
    ekran yozuvi esa aynan o'shanda yakunlanadi. Token o'rnini
    sessiyaning `public_id` si, O'SHA qurilma va qisqa vaqt oynasi
    bosadi (`recordings.session_without_token`).
    """

    def _post_without_token(self, payload, device=None):
        return self.client.post(
            self.url,
            payload,
            format="json",
            HTTP_AUTHORIZATION=self.auth,
            HTTP_X_DEVICE_ID=(device or self.device).device_id,
        )

    def _end_session(self, *, status=ExamSession.Status.TERMINATED, ago=timedelta(seconds=5)):
        ExamSession.objects.filter(pk=self.session.pk).update(
            status=status, finished_at=timezone.now() - ago
        )

    # ------------------------------------------------------------------
    def test_terminated_session_accepts_recording_by_public_id(self):
        self._end_session()
        response = self._post_without_token(
            self._payload(session_id=str(self.session.public_id))
        )
        self.assertEqual(response.status_code, 201, response.content)
        recording = LocalRecording.objects.get(session=self.session)
        self.assertEqual(recording.device_id, self.device.device_id)

    def test_expired_and_finished_sessions_are_covered_too(self):
        """Server yopgan sessiya ham xuddi shunday: token client bilmasdan o'chadi."""
        self._end_session(status=ExamSession.Status.EXPIRED)
        response = self._post_without_token(
            self._payload(session_id=str(self.session.public_id))
        )
        self.assertEqual(response.status_code, 201, response.content)

    @override_settings(PROCTORING={"RECORDING_LATE_REGISTER_SECONDS": 60})
    def test_window_closes_after_setting(self):
        """
        Oyna CHEKLANGAN: client manzilni yakundan bir necha soniya
        keyin yuboradi, cheksiz oyna esa har qanday eski sessiyaga
        istalgan paytda yozuv qo'shishga yo'l ochardi.
        """
        self._end_session(ago=timedelta(minutes=5))
        response = self._post_without_token(
            self._payload(session_id=str(self.session.public_id))
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(LocalRecording.objects.exists())

    def test_other_device_cannot_attach_recording(self):
        """
        Boshqa mashina birovning sessiyasiga yozuv qo'sha olmaydi -
        tokensiz yo'lda yagona bog'lovchi aynan qurilma.
        """
        self._end_session()
        stranger = factories.make_device()
        response = self._post_without_token(
            self._payload(session_id=str(self.session.public_id)), device=stranger
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(LocalRecording.objects.exists())

    def test_live_session_without_token_is_accepted(self):
        """
        Operator imtihon o'rtasida hisobdan chiqdi: client tokenni
        tozaladi, sessiya esa serverda hali tirik. Qurilma unga
        baribir egalik qiladi va vaqt oynasi bu yerda qo'llanmaydi.
        """
        response = self._post_without_token(
            self._payload(session_id=str(self.session.public_id))
        )
        self.assertEqual(response.status_code, 201, response.content)

    def test_token_and_public_id_must_match(self):
        """
        Ikkalasi kelsa MOS bo'lishi shart: aks holda tirik sessiya
        tokeni bilan boshqa sessiyaga yozuv qo'shish mumkin bo'lardi.
        """
        other = factories.make_session(device=self.device)
        response = self._post(self._payload(session_id=str(other.public_id)))
        self.assertEqual(response.status_code, 404)
        self.assertFalse(LocalRecording.objects.exists())

    def test_stale_token_does_not_block_late_registration(self):
        """
        HAQIQIY HOLAT: client chetlashtirishdan xabar topguncha so'rov
        hali ESKI token bilan ketadi. Qat'iy autentifikatsiya uni
        view'ga yetkazmasdan rad etardi va tokensiz yo'l hech qachon
        ishlamasdi (`LenientSessionTokenAuthentication`).
        """
        self._end_session()
        response = self._post(self._payload(session_id=str(self.session.public_id)))
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(LocalRecording.objects.filter(session=self.session).exists())

    def test_stale_token_without_public_id_is_still_rejected(self):
        """Eski token O'ZI hech narsani ochmaydi - sessiya faqat `session_id` bilan topiladi."""
        self._end_session()
        response = self._post(self._payload())
        self.assertEqual(response.status_code, 404)
        self.assertFalse(LocalRecording.objects.exists())
