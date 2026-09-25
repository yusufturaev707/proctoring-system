"""
Desktop client API yuzasi (`/api/v1/client/...`).

Bu yerdagi testlar HTTP darajasida: javob konverti, status kodlari va
autentifikatsiya qatlamlari. Ular admin API'dan ataylab ajratilgan
yuzani himoya qiladi - u yerda boshqa auth, boshqa throttling va
boshqa xavf profili.
"""

import io
import json
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.common.tests.utils import RedisStateMixin
from PIL import Image

from apps.controls.models import AllowedPublicIp, ClientExitPassword
from apps.proctoring.models import AuditLog, ExamSession, FaceVerificationLog
from apps.proctoring.tests import factories


def bearer(user) -> str:
    """
    HAQIQIY JWT.

    `APIClient.force_authenticate` bu yerda YARAMAYDI: u view'ning
    `authentication_classes` ro'yxatini `ForcedAuthentication` bilan
    BUTUNLAY almashtiradi. Client yuzasi esa yon ta'sirli
    autentifikatorlarga tayanadi — `DeviceResolution` va
    `SessionTokenAuthentication` `None` qaytaradi va faqat
    `request.device` / `request.exam_session` ni to'ldiradi. Ular
    ishga tushmasa, sessiya tokeni bilan kelgan so'rov ham
    "sessiya yo'q" bo'lib qoladi.
    """
    from rest_framework_simplejwt.tokens import AccessToken

    return f"Bearer {AccessToken.for_user(user)}"


class PreflightTests(TestCase):
    """
    Ishga tushishdagi tarmoq tekshiruvi — OCHIQ endpoint.

    U hech narsani ochmaydi: client so'rov yuborgan manzilni allaqachon
    biladi, biz faqat "shu manzil ro'yxatdami" degan javobni beramiz.
    """

    def setUp(self):
        # Ruxsat etilgan IP'lar ro'yxati keshlanadi (`IP_CACHE_KEY`,
        # 300 s). Tozalanmasa testlar bir-birining ro'yxatini ko'radi
        # va tartibga bog'liq bo'lib qoladi.
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient()
        self.url = reverse("client-preflight")

    def test_allowed_ip_returns_hotkeys(self):
        """
        Ruxsat berilganda qulflash siyosati ham qaytadi.

        U login'dan OLDIN qo'llanadi: aynan o'sha ekranda kompyuter eng
        ochiq holatda turadi — operator hali kirmagan, lekin mashina
        allaqachon talabgor oldida.
        """
        from apps.controls.models import HotKeyboardKey

        zone = factories.make_zone()
        AllowedPublicIp.objects.create(ip_address="203.0.113.10", zone=zone)
        setting = factories.make_setting(is_active=True)
        key = HotKeyboardKey.objects.create(name="Alt+Tab", code="alt+tab")
        setting.hotkeys.set([key])

        response = self.client.post(self.url, {"public_ip": "203.0.113.10"}, format="json")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertTrue(data["allowed"])
        self.assertEqual(data["hotkeys"], ["alt+tab"])
        self.assertEqual(data["zone"]["name"], zone.name)

    def test_denied_ip_returns_403_with_details(self):
        """
        Rad etishda AYNAN qaysi manzil rad etilgani qaytadi.

        Operator shu raqamni administratorga aytadi — shuning uchun
        konvert bu yerda qo'lda yig'iladi (`IpNotAllowed` istisnosi
        `details` ni yo'qotadi).
        """
        AllowedPublicIp.objects.create(ip_address="203.0.113.10")

        response = self.client.post(self.url, {"public_ip": "198.51.100.1"}, format="json")

        self.assertEqual(response.status_code, 403)
        error = response.json()["error"]
        self.assertEqual(error["code"], "ip_not_allowed")
        self.assertEqual(error["details"]["public_ip"], "198.51.100.1")
        self.assertFalse(error["details"]["allowlist_empty"])

    def test_empty_allowlist_is_reported_separately(self):
        """
        Bo'sh ro'yxat - ADMINISTRATOR xatosi, operatorniki emas.

        Uni "IP'ingiz noto'g'ri" deb ko'rsatish nosozlikni soatlab
        qidirishga olib keladi.
        """
        response = self.client.post(self.url, {"public_ip": "203.0.113.10"}, format="json")

        self.assertEqual(response.status_code, 403)
        self.assertTrue(response.json()["error"]["details"]["allowlist_empty"])

    def test_requires_no_authentication(self):
        """
        Preflight login'dan OLDIN chaqiriladi.

        Unda hali na JWT, na `device_id` bor — endpoint ochiq bo'lishi
        SHART, aks holda noto'g'ri tarmoqdagi operator avval login
        qilishga majbur bo'lardi.
        """
        AllowedPublicIp.objects.create(ip_address="203.0.113.10")
        response = self.client.post(self.url, {"public_ip": "203.0.113.10"}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_invalid_ip_is_rejected_by_serializer(self):
        response = self.client.post(self.url, {"public_ip": "umuman-ip-emas"}, format="json")
        self.assertEqual(response.status_code, 400)


class AccessAttemptTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient()
        self.url = reverse("client-access-attempt")

    def test_logs_attempt_and_returns_202(self):
        """
        202: yozib olindi, lekin client uchun hech nimani o'zgartirmaydi.

        Client bu javobni kutmaydi ham — jurnalga yozish oqimni
        to'xtatmasligi kerak.
        """
        with self.assertLogs("client_access", level="INFO") as logs:
            response = self.client.post(
                self.url,
                {
                    "mac_address": "AA:BB:CC:DD:EE:FF",
                    "ip_address": "192.168.1.5",
                    "public_ip": "203.0.113.10",
                    "hostname": "PC-01",
                    "entered_login": False,
                },
                format="json",
            )

        self.assertEqual(response.status_code, 202)
        self.assertIn("KIRISH URINISHI", logs.output[0])
        self.assertIn("AA:BB:CC:DD:EE:FF", logs.output[0])

    def test_disagreement_between_client_and_server_is_flagged(self):
        """
        Server o'z xulosasini QAYTADAN hisoblaydi.

        Client "login ochildi" desa-yu server "ruxsat yo'q" desa - bu
        alohida signal: yo client eskirgan, yo o'zgartirilgan.
        """
        with self.assertLogs("client_access", level="INFO") as logs:
            self.client.post(
                self.url,
                {"public_ip": "198.51.100.1", "entered_login": True},
                format="json",
            )
        self.assertTrue(any("ZIDLIK" in line for line in logs.output))

    def test_invalid_mac_is_rejected(self):
        """
        MAC formati tekshiriladi - u jurnalda IZLASH kaliti.

        Buzilgan qiymat keyin hech qachon topilmaydi.
        """
        response = self.client.post(
            self.url, {"mac_address": "mac-emas"}, format="json"
        )
        self.assertEqual(response.status_code, 400)


class ExitVerifyTests(TestCase):
    """
    Chiqish paroli — endpoint AUTENTIFIKATSIYA TALAB QILMAYDI.

    Bu bo'shliq emas: u hech narsa ochmaydi va faqat "parol to'g'rimi"
    degan javobni qaytaradi. Login sahifasida hech qanday xodim yo'q,
    mashinani esa qonuniy yopish kerak bo'lishi mumkin.
    """

    def setUp(self):
        self.client = APIClient()
        self.url = reverse("client-exit-verify")
        self.region = factories.make_region()
        self.zone = factories.make_zone(region=self.region)
        self.computer = factories.make_computer(zone=self.zone)
        self.device = factories.make_device(computer=self.computer)

    def _set_password(self, raw):
        row = ClientExitPassword(region=self.region)
        row.set_password(raw)
        row.save()
        return row

    def test_region_password_allows_exit(self):
        self._set_password("chiqish-paroli")
        response = self.client.post(
            self.url,
            {"password": "chiqish-paroli"},
            format="json",
            HTTP_X_DEVICE_ID=self.device.device_id,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["method"], "region")

    def test_staff_password_allows_exit_and_names_the_person(self):
        """
        Xodim o'z paroli bilan chiqsa - audit izida ISMI qoladi.

        Bu eng yaxshi holat: viloyat paroli faqat "qaysi viloyatning
        kaliti ishlatilgani" ni aytadi.
        """
        user = factories.make_user(permissions=[])
        user.set_password("xodim-paroli")
        user.save()

        response = self.client.post(
            self.url,
            {"password": "xodim-paroli"},
            format="json",
            HTTP_AUTHORIZATION=bearer(user),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["method"], "staff")
        entry = AuditLog.objects.get(action="client_exit")
        self.assertEqual(entry.actor_id, user.pk)
        self.assertEqual(entry.meta["method"], "staff")

    def test_wrong_password_is_rejected(self):
        self._set_password("to'g'ri")
        response = self.client.post(self.url, {"password": "xato"}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "exit_password_invalid")

    def test_unconfigured_password_has_its_own_code(self):
        """
        "Sozlanmagan" va "noto'g'ri" - BOSHQA holatlar.

        Client birinchisini tasdiqlash dialogiga aylantiradi: kiosk
        rejimida chiqishning boshqa yo'li yo'q va sozlanmagan tizim
        mashinani QULFLAB qo'ymasligi kerak.
        """
        response = self.client.post(self.url, {"password": "nimadir"}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["error"]["code"], "exit_password_not_configured"
        )

    def test_unknown_device_does_not_block_exit(self):
        """
        Noma'lum qurilma bilan ham chiqish mumkin.

        `DeviceResolution` bu yerda ATAYLAB ishlatilmaydi: u
        tasdiqlanmagan qurilmada istisno tashlardi, holbuki aynan
        shunday mashinani yopish kerak bo'ladi.
        """
        self._set_password("parol")
        response = self.client.post(
            self.url,
            {"password": "parol"},
            format="json",
            HTTP_X_DEVICE_ID="umuman-mavjud-emas",
        )
        self.assertEqual(response.status_code, 200)

    def test_audit_records_the_method(self):
        self._set_password("parol")
        self.client.post(
            self.url,
            {"password": "parol"},
            format="json",
            HTTP_X_DEVICE_ID=self.device.device_id,
        )
        entry = AuditLog.objects.get(action="client_exit")
        self.assertEqual(entry.meta["method"], "region")
        self.assertEqual(entry.meta["region"], self.region.name)


class FaceEndpointTests(RedisStateMixin, TestCase):
    """
    Kirishdagi FaceID yuzasi: MOSLIK va MOS KELMASLIK.

    Ikkalasi ham serverga boradi, lekin natijasi butunlay boshqacha:
    birinchisi sessiya ochadi, ikkinchisi faqat yozuv qoldiradi va
    `challenge` ni sarflamaydi.
    """

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.exam = factories.make_exam()
        self.schedule = factories.make_schedule(exam=self.exam)
        self.device = factories.make_device()
        self.computer = self.device.computer
        self.operator = factories.make_user(permissions=["client.operate"])
        self.auth = bearer(self.operator)
        # Manba IP ro'yxatda bo'lishi shart: `FaceVerifyView`
        # `check_source_ip` dan o'tadi. `8.8.8.8` HAQIQIY ommaviy
        # manzil - RFC 5737 diapazonlarini Python xususiy deb biladi.
        AllowedPublicIp.objects.create(ip_address="8.8.8.8", zone=self.computer.zone)
        cache.clear()
        self.addCleanup(cache.clear)

        from apps.proctoring.services import session as session_service

        self.challenge = session_service.lookup_candidate(
            pinfl="30000000000001",
            exam=self.exam,
            device=self.device,
            zone=self.computer.zone,
        )["challenge"]

    @staticmethod
    def _image() -> SimpleUploadedFile:
        buffer = io.BytesIO()
        Image.new("RGB", (160, 120), "red").save(buffer, format="JPEG")
        return SimpleUploadedFile("face.jpg", buffer.getvalue(), content_type="image/jpeg")

    def _post(self, url_name, payload, *, multipart=False):
        return self.client.post(
            reverse(url_name),
            payload,
            format="multipart" if multipart else "json",
            HTTP_AUTHORIZATION=self.auth,
            HTTP_X_DEVICE_ID=self.device.device_id,
            REMOTE_ADDR="8.8.8.8",
        )

    def test_verify_accepts_multipart_with_image(self):
        """
        Vektor multipart'da JSON SATR sifatida keladi.

        `multipart/form-data` ichma-ich strukturani ko'tarmaydi - 512
        float alohida maydon bo'lib kelardi.
        """
        response = self._post(
            "client-face-verify",
            {
                "challenge": self.challenge,
                "embedding": json.dumps([0.1] * 512),
                "score": "88",
                "faces_detected": "1",
                "image": self._image(),
            },
            multipart=True,
        )

        self.assertEqual(response.status_code, 201, response.content)
        log = FaceVerificationLog.objects.get()
        self.assertEqual(log.score, 88)
        self.assertTrue(log.image_path)

    def test_verify_refuses_score_below_threshold(self):
        response = self._post(
            "client-face-verify",
            {
                "challenge": self.challenge,
                "embedding": [0.1] * 512,
                "score": 12,
                "faces_detected": 1,
            },
        )
        # 403: bu ruxsat masalasi, "noto'g'ri so'rov" emas -
        # `FaceVerificationFailed` shu bilan qaytadi.
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "face_verification_failed")
        self.assertFalse(ExamSession.objects.exists())

    def test_attempt_records_failure_without_session(self):
        response = self._post(
            "client-face-attempt",
            {
                "challenge": self.challenge,
                "score": "31",
                "faces_detected": "1",
                "image": self._image(),
            },
            multipart=True,
        )

        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()["data"]
        self.assertEqual(data["attempts"], 1)

        log = FaceVerificationLog.objects.get()
        self.assertIsNone(log.session_id)
        self.assertFalse(log.passed)
        self.assertTrue(log.image_path)
        self.assertFalse(ExamSession.objects.exists())

    def test_attempt_keeps_the_challenge_alive(self):
        """Muvaffaqiyatsiz urinishdan keyin ham sessiya ochilishi mumkin."""
        self._post(
            "client-face-attempt",
            {"challenge": self.challenge, "score": 31, "faces_detected": 1},
        )
        response = self._post(
            "client-face-verify",
            {
                "challenge": self.challenge,
                "embedding": [0.1] * 512,
                "score": 92,
                "faces_detected": 1,
            },
        )
        self.assertEqual(response.status_code, 201, response.content)


class PeriodicFaceEndpointTests(RedisStateMixin, TestCase):
    """Test davomidagi tekshiruv - faqat muvaffaqiyatsiz natija keladi."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.url = reverse("client-face-periodic")
        self.device = factories.make_device()
        self.session = factories.make_session(device=self.device)
        self.operator = factories.make_user(permissions=["client.operate"])

        from apps.proctoring.services import session as session_service

        self.raw_token = session_service.issue_session_token(self.session)
        self.auth = bearer(self.operator)

    def _post(self, payload, *, multipart=False):
        return self.client.post(
            self.url,
            payload,
            format="multipart" if multipart else "json",
            HTTP_AUTHORIZATION=self.auth,
            HTTP_X_DEVICE_ID=self.device.device_id,
            HTTP_X_PROCTORING_SESSION=self.raw_token,
        )

    def test_embedding_is_not_accepted_anymore(self):
        """
        `embedding` maydoni YO'Q: server solishtirmaydi.

        Uni jimgina qabul qilish "kim solishtiryapti?" degan savolni
        ochiq qoldirardi. Serializer uni e'tiborsiz qoldiradi, ball
        esa MAJBURIY.
        """
        response = self._post({"faces_detected": 1, "embedding": [0.1] * 512})
        self.assertEqual(response.status_code, 400)

    def test_failed_check_stores_image_and_counts(self):
        buffer = io.BytesIO()
        Image.new("RGB", (160, 120), "blue").save(buffer, format="JPEG")
        response = self._post(
            {
                "score": "10",
                "faces_detected": "1",
                "passed_since_last": "5",
                "image": SimpleUploadedFile(
                    "face.jpg", buffer.getvalue(), content_type="image/jpeg"
                ),
            },
            multipart=True,
        )

        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()["data"]
        self.assertFalse(data["passed"])
        self.assertEqual(data["fail_count"], 1)

        log = FaceVerificationLog.objects.get()
        self.assertEqual(log.stage, FaceVerificationLog.Stage.PERIODIC)
        self.assertEqual(log.source, FaceVerificationLog.Source.CLIENT)
        self.assertTrue(log.image_path)

    def test_heartbeat_carries_the_check_counter(self):
        """
        `face_checks` ni CLIENT yozadi.

        Serverga faqat xatolar keladi, ya'ni jami tekshiruvlar sonini
        u ko'ra olmaydi. Qiymat heartbeat orqali Redis hash'iga
        tushadi va write-behind uni `face_check_count` ga ko'chiradi.
        """
        response = self.client.post(
            reverse("client-heartbeat"),
            {"face_checks": 42, "network_ok": True},
            format="json",
            HTTP_AUTHORIZATION=self.auth,
            HTTP_X_DEVICE_ID=self.device.device_id,
            HTTP_X_PROCTORING_SESSION=self.raw_token,
        )
        self.assertEqual(response.status_code, 200)

        from apps.proctoring.services import state as session_state

        state = session_state.get_state(self.session.pk)
        self.assertEqual(int(state["face_checks"]), 42)

class EventBatchTests(RedisStateMixin, TestCase):
    """Hodisa oqimi — sessiya tokeni talab qilinadigan yuza."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.url = reverse("client-events")
        self.device = factories.make_device()
        self.session = factories.make_session(device=self.device)
        self.operator = factories.make_user(permissions=["client.operate"])

        from apps.proctoring.services import session as session_service

        self.raw_token = session_service.issue_session_token(self.session)
        self.auth = bearer(self.operator)

    def _post(self, events, token=None):
        # `occurred_at` majburiy (`EventItemSerializer`): client uni har
        # doim yuboradi va u partitsiyani tanlaydi.
        moment = timezone.now().isoformat()
        events = [{"occurred_at": moment, **event} for event in events]
        return self.client.post(
            self.url,
            {"events": events},
            format="json",
            HTTP_AUTHORIZATION=self.auth,
            HTTP_X_DEVICE_ID=self.device.device_id,
            HTTP_X_PROCTORING_SESSION=token or self.raw_token,
        )

    def test_accepts_batch_with_202(self):
        """
        202 Accepted — hodisalar navbatga olindi, DB'ga hali yozilmadi.

        Client javobni kutmasligi kerak, shuning uchun bu to'g'ri kod.
        """
        response = self._post(
            [
                {"type": "window_blur", "severity": 2},
                {"type": "hotkey_blocked", "severity": 1, "payload": {"key": "alt+tab"}},
            ]
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["data"]["accepted"], 2)

    def test_rejects_missing_session_token(self):
        response = self.client.post(
            self.url,
            {
                "events": [
                    {
                        "type": "window_blur",
                        "severity": 1,
                        "occurred_at": timezone.now().isoformat(),
                    }
                ]
            },
            format="json",
            HTTP_AUTHORIZATION=self.auth,
            HTTP_X_DEVICE_ID=self.device.device_id,
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "session_not_found")

    def test_rejects_unknown_session_token(self):
        response = self._post(
            [{"type": "window_blur", "severity": 1}], token="soxta-token"
        )
        self.assertEqual(response.status_code, 404)

    def test_requires_client_operate_permission(self):
        self.auth = bearer(factories.make_user(permissions=[]))
        response = self._post([{"type": "window_blur", "severity": 1}])
        self.assertEqual(response.status_code, 403)

    def test_terminated_session_token_stops_working(self):
        """
        Chetlashtirish DARHOL kuchga kiradi.

        Token Redis'dan o'chadi va keyingi so'rov rad etiladi — bu
        opaque token tanlashning butun sababi.
        """
        from apps.proctoring.services import session as session_service

        session_service.terminate_session(self.session, reason="sinov")
        response = self._post([{"type": "window_blur", "severity": 1}])
        self.assertEqual(response.status_code, 404)


class HandshakeHardwareTests(TestCase):
    """
    Handshake apparat haqida nima yozadi.

    Bu yagona kanal: alohida "hardware report" endpointi YO'Q va
    bo'lmasligi ham kerak - apparat har handshake'da baribir
    xabar qilinadi, ikkinchi endpoint esa faqat ikkinchi
    autentifikatsiya yuzasini ochardi.
    """

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

        self.client = APIClient()
        self.zone = factories.make_zone()
        AllowedPublicIp.objects.create(ip_address="8.8.8.8", zone=self.zone)
        self.computer = factories.make_computer(zone=self.zone)
        self.device = factories.make_device(computer=self.computer)
        self.user = factories.make_user(permissions=["client.operate"])
        self.url = reverse("client-handshake")

    def post(self, payload):
        return self.client.post(
            self.url,
            payload,
            format="json",
            HTTP_AUTHORIZATION=bearer(self.user),
            HTTP_X_DEVICE_ID=self.device.device_id,
            REMOTE_ADDR="8.8.8.8",
        )

    def test_records_gpu_and_profile(self):
        response = self.post(
            {
                "app_version": "1.0.0",
                "gpu_name": "NVIDIA GeForce GTX 1660 SUPER",
                "performance_profile": "medium",
            }
        )

        self.assertEqual(response.status_code, 200)
        self.device.refresh_from_db()
        self.assertEqual(self.device.gpu_name, "NVIDIA GeForce GTX 1660 SUPER")
        self.assertEqual(self.device.performance_profile, "medium")

    def test_accepts_minimal_profile(self):
        """
        `minimal` — client'dagi eng past profil.

        Ro'yxatdan tushib qolsa, aynan eng zaif mashinalarning
        handshake'i 400 olardi va ular umuman ishga tusha
        olmasdi - ya'ni xato eng yomon joyda chiqardi.
        """
        response = self.post({"app_version": "1.0.0", "performance_profile": "minimal"})

        self.assertEqual(response.status_code, 200)
        self.device.refresh_from_db()
        self.assertEqual(self.device.performance_profile, "minimal")

    def test_rejects_unknown_profile(self):
        response = self.post({"app_version": "1.0.0", "performance_profile": "turbo"})

        self.assertEqual(response.status_code, 400)

    def test_missing_hardware_keeps_previous_values(self):
        """
        Eski client (yoki apparat hali aniqlanmagan) mavjud
        qiymatni O'CHIRMAYDI.

        Aniqlash fon thread'ida ketadi va birinchi handshake'ga
        ulgurmasligi mumkin. Bo'sh qiymat yozilsa, panel bir
        marta aniqlangan mashinani "GPU yo'q" deb ko'rsatardi.
        """
        self.device.gpu_name = "NVIDIA RTX 3060"
        self.device.performance_profile = "high"
        self.device.save(update_fields=["gpu_name", "performance_profile"])

        response = self.post({"app_version": "1.0.0"})

        self.assertEqual(response.status_code, 200)
        self.device.refresh_from_db()
        self.assertEqual(self.device.gpu_name, "NVIDIA RTX 3060")
        self.assertEqual(self.device.performance_profile, "high")

    def test_info_pc_is_refreshed(self):
        """
        Tafsilot `Computer.info_pc` ga tushadi.

        Ro'yxatdan o'tish BIR MARTA bo'ladi va o'shandagi tavsif
        eskiradi: RAM qo'shiladi, drayver o'rnatiladi. "Nega bu
        mashinada kuzatuv sekin?" degan savolga javob aynan shu
        yerda.
        """
        self.computer.info_pc = {"os": "Windows-10", "hardware": {}}
        self.computer.save(update_fields=["info_pc"])

        response = self.post(
            {
                "app_version": "1.0.0",
                "info_pc": {
                    "os": "Windows-11",
                    "hardware": {"gpu_warning": "onnxruntime CPU nashri"},
                },
            }
        )

        self.assertEqual(response.status_code, 200)
        self.computer.refresh_from_db()
        self.assertEqual(self.computer.info_pc["os"], "Windows-11")
        self.assertEqual(
            self.computer.info_pc["hardware"]["gpu_warning"], "onnxruntime CPU nashri"
        )

    def test_empty_info_pc_keeps_previous(self):
        self.computer.info_pc = {"os": "Windows-10"}
        self.computer.save(update_fields=["info_pc"])

        response = self.post({"app_version": "1.0.0"})

        self.assertEqual(response.status_code, 200)
        self.computer.refresh_from_db()
        self.assertEqual(self.computer.info_pc, {"os": "Windows-10"})


class HandshakeMachineTests(TestCase):
    """
    Handshake javobidagi `machine` bloki.

    Bu yagona kanal: mashina tekshiruvi natijasi handshake bergan
    kontekstga (bino, kompyuter) bog'liq va alohida endpoint ikkala
    javobning bir-biriga mos kelishini kafolatlay olmasdi —
    oradagi soniyalarda administrator kompyuterni ko'chirishi
    mumkin.
    """

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

        self.client = APIClient()
        self.zone = factories.make_zone()
        AllowedPublicIp.objects.create(ip_address="8.8.8.8", zone=self.zone)
        self.computer = factories.make_computer(
            zone=self.zone, mac_address="AA:BB:CC:DD:EE:10"
        )
        self.device = factories.make_device(computer=self.computer)
        self.user = factories.make_user(permissions=["client.operate"])
        self.url = reverse("client-handshake")

    def post(self, payload):
        return self.client.post(
            self.url,
            payload,
            format="json",
            HTTP_AUTHORIZATION=bearer(self.user),
            HTTP_X_DEVICE_ID=self.device.device_id,
            REMOTE_ADDR="8.8.8.8",
        )

    def machine(self, payload):
        response = self.post(payload)
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]["machine"]

    def test_matching_mac_is_allowed(self):
        machine = self.machine({"app_version": "1.0.0", "mac_address": "AA:BB:CC:DD:EE:10"})

        self.assertEqual(machine["status"], "ok")
        self.assertTrue(machine["allowed"])

    def test_unknown_mac_blocks_by_default(self):
        """
        `REQUIRE_MAC_MATCH` standart qiymati — `true`.

        Ya'ni ro'yxatda yo'q mashina imtihonni BOSHLAY OLMAYDI.
        Sabab client'da emas, shu yerda: qaror serverniki va uni
        client tomonda hisoblash ikkita qoidani yaratardi.
        """
        machine = self.machine({"app_version": "1.0.0", "mac_address": "AA:BB:CC:DD:EE:99"})

        self.assertEqual(machine["status"], "not_found")
        self.assertFalse(machine["allowed"])
        self.assertIn(self.zone.name, machine["message"])

    def test_missing_mac_also_blocks(self):
        """
        MAC yubormaslik tekshiruvni CHETLAB O'TMAYDI.

        Aks holda uni o'chirish uchun maydonni bo'sh qoldirish
        yetarli bo'lardi. Eski client'lar uchun yo'l —
        `REQUIRE_MAC_MATCH=false`.
        """
        machine = self.machine({"app_version": "1.0.0"})

        self.assertEqual(machine["status"], "unknown")
        self.assertFalse(machine["allowed"])

    def test_setting_downgrades_block_to_warning(self):
        """
        `REQUIRE_MAC_MATCH=false` — natija qaytadi, lekin to'smaydi.

        Dastlabki joylashtirishda inventarizatsiya hali to'liq
        bo'lmasligi mumkin va majburiy tekshiruv butun markazni
        to'xtatardi.
        """
        with patch.dict(settings.PROCTORING, {"REQUIRE_MAC_MATCH": False}):
            machine = self.machine(
                {"app_version": "1.0.0", "mac_address": "AA:BB:CC:DD:EE:99"}
            )

        self.assertEqual(machine["status"], "not_found")
        self.assertTrue(machine["allowed"])

    def test_mac_is_never_written_to_computer(self):
        """Tekshiruv faqat solishtiradi — inventarizatsiyani o'zgartirmaydi."""
        self.post({"app_version": "1.0.0", "mac_address": "AA:BB:CC:DD:EE:99"})

        self.computer.refresh_from_db()
        self.assertEqual(self.computer.mac_address, "AA:BB:CC:DD:EE:10")

    def test_invalid_mac_is_rejected_by_length(self):
        """Serializer chegarasi: 17 belgidan uzun qiymat qabul qilinmaydi."""
        response = self.post({"app_version": "1.0.0", "mac_address": "A" * 40})

        self.assertEqual(response.status_code, 400)
