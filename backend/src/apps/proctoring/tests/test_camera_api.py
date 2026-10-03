"""
Client kamera yuzasi: `camera/config/` va `camera/stream/`.

Eng nozik endpoint - `camera/stream/`: u RTSP kredensialini desktop
mashinasiga beradi. Uning har bir himoya qatlami shu yerda
tekshiriladi, chunki kredensialning O'ZI muddatsiz (kamera parolini
serverdan bekor qilib bo'lmaydi) va yagona haqiqiy chegara -
"kimga berilishi mumkin" degan qoida.
"""

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.controls.models import AllowedPublicIp, ProctoringPolicy
from apps.devices import services as device_services
from apps.devices.models import Camera
from apps.proctoring.models import AuditLog
from apps.proctoring.tests import factories
from apps.proctoring.tests.test_client_api import bearer


class CameraApiTestCase(TestCase):
    """Umumiy sozlash: ruxsat etilgan IP, qurilma va operator."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

        self.client = APIClient()
        self.zone = factories.make_zone()
        AllowedPublicIp.objects.create(ip_address="8.8.8.8", zone=self.zone)
        self.computer = factories.make_computer(zone=self.zone)
        self.device = factories.make_device(computer=self.computer)
        self.user = factories.make_user(permissions=["client.operate"])
        self._clear_grants()
        self.addCleanup(self._clear_grants)

    @staticmethod
    def _clear_grants() -> None:
        """
        Kamera ruxsati izlarini tozalaydi (Redis, 15 daqiqa TTL).

        `RedisStateMixin` ATAYLAB ishlatilmaydi: u Redis yo'q
        mashinada butun sinfni o'tkazib yuborardi, bu endpointlar
        esa Redis'siz ham ishlashi SHART - ruxsat izini yozib
        bo'lmagani kredensial berishni to'xtatmasligi kerak.

        Tozalash kerak, chunki `device_id` testlarda barqaror
        (`dev_test_1`) va oldingi yurishdan qolgan kalit "bu
        allaqachon berilgan" degan xulosaga olib keladi - o'shanda
        audit yozuvi yaratilmaydi va test sababsiz yiqiladi.
        """
        try:
            from apps.common.redis_client import get_redis

            client = get_redis()
            keys = list(client.scan_iter("cam:grant:*", count=500))
            if keys:
                client.delete(*keys)
        except Exception:
            # Redis yo'q - tozalanadigan holat ham yo'q.
            pass

    def request(self, method, url, data=None):
        return getattr(self.client, method)(
            url,
            data or {},
            format="json",
            HTTP_AUTHORIZATION=bearer(self.user),
            HTTP_X_DEVICE_ID=self.device.device_id,
            REMOTE_ADDR="8.8.8.8",
        )

    def make_camera(self, *, bind=True, **kwargs) -> Camera:
        """`bind` - panelda shu kompyuterga biriktirilgan (`Computer.cameras`)."""
        index = Camera.objects.count() + 1
        camera = Camera.objects.create(
            zone=kwargs.pop("zone", self.zone),
            **{
                "name": f"CAM-{index}",
                "ip_address": f"10.1.0.{index}",
                "mac_address": "AB:CD:EF:00:00:{:02X}".format(index),
                **kwargs,
            },
        )
        if bind:
            self.computer.cameras.add(camera)
        return camera


class CameraConfigTests(CameraApiTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("client-camera-config")

    def test_camera_list_is_always_present(self):
        """
        `cameras` kaliti HAR DOIM javobda bo'ladi.

        Kalitni umuman tushirib qoldirish client tomonda "eski
        server" va "binoda IP kamera yo'q" holatlarini
        aralashtirib yuborardi - birinchisi nosozlik, ikkinchisi
        mutlaqo normal konfiguratsiya (faqat veb-kamerali xona).
        """
        response = self.request("get", self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["cameras"], [])

    def test_zone_cameras_are_described_without_credentials(self):
        """
        Konfiguratsiya "qanday kameralar bor" ni aytadi.

        Parol bu yerda YO'Q va bo'lmasligi kerak: u har bir
        handshake'da tarqalib ketardi. Kredensial faqat
        `camera/stream/` orqali va faqat so'ralganda beriladi.
        """
        camera = self.make_camera(login="admin", vendor="hikvision", port=8554)
        device_services.set_camera_password(camera, "juda-maxfiy")
        camera.save()

        payload = self.request("get", self.url).json()["data"]
        rendered = str(payload)

        self.assertEqual([item["id"] for item in payload["cameras"]], [camera.pk])
        self.assertEqual(payload["cameras"][0]["port"], 8554)
        self.assertNotIn("juda-maxfiy", rendered)
        self.assertNotIn("password", rendered)
        self.assertNotIn("rtsp://", rendered)

    def test_cameras_from_other_buildings_are_not_listed(self):
        """
        Boshqa binodagi kamera bu xonani jismonan ko'rmaydi - bog'lanish
        qolgan bo'lsa ham (kamera keyin boshqa binoga ko'chirilgan).
        """
        other_zone = factories.make_zone()
        self.make_camera(name="Begona", zone=other_zone)

        payload = self.request("get", self.url).json()["data"]
        self.assertEqual(payload["cameras"], [])

    def test_unbound_building_cameras_are_not_listed(self):
        """
        DOIRA - KOMPYUTER. Binodagi biriktirilmagan kamera (yoki boshqa
        kompyuterniki) ro'yxatga tushmaydi; biriktirish yo'q - bo'sh
        ro'yxat, "binodagilarning hammasi" zaxirasi yo'q.
        """
        self.make_camera(name="Biriktirilmagan", bind=False)
        neighbour = factories.make_computer(zone=self.zone)
        neighbour.cameras.add(self.make_camera(name="Qo'shniniki", bind=False))

        payload = self.request("get", self.url).json()["data"]
        self.assertEqual(payload["cameras"], [])

        own = self.make_camera(name="O'ziniki")
        payload = self.request("get", self.url).json()["data"]
        self.assertEqual([item["id"] for item in payload["cameras"]], [own.pk])

    def test_exam_policy_overrides_global(self):
        setting = factories.make_setting()
        ProctoringPolicy.objects.create(setting=setting, is_enabled=True, camera_count=2)
        exam = factories.make_exam(setting=setting)
        factories.make_setting(is_active=True)  # global standart - siyosatsiz

        without = self.request("get", self.url).json()["data"]["policy"]
        self.assertFalse(without["enabled"])

        with_exam = self.request("get", f"{self.url}?exam={exam.pk}").json()["data"]["policy"]
        self.assertTrue(with_exam["enabled"])
        self.assertEqual(with_exam["camera"]["count"], 2)

    def test_forbidden_source_ip_is_rejected(self):
        """Kamera yuzasi ham umumiy IP chegarasidan o'tadi."""
        response = self.client.get(
            self.url,
            HTTP_AUTHORIZATION=bearer(self.user),
            HTTP_X_DEVICE_ID=self.device.device_id,
            REMOTE_ADDR="1.2.3.4",
        )
        self.assertEqual(response.status_code, 403)


class CameraStreamTests(CameraApiTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("client-camera-stream")

    def _ip_camera(self, zone=None, bind=True):
        camera = self.make_camera(login="admin", zone=zone or self.zone, bind=bind)
        device_services.set_camera_password(camera, "s3cret")
        camera.save()
        return camera

    def test_credentials_are_issued_for_a_camera_in_the_building(self):
        camera = self._ip_camera()
        response = self.request("post", self.url, {"camera_id": camera.pk})

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertIn("admin:s3cret@", data["url"])
        self.assertIn(camera.ip_address, data["url"])
        self.assertEqual(data["transport"], "tcp")
        self.assertGreater(data["ttl"], 0)

    def test_camera_from_another_building_is_rejected(self):
        """
        Bog'lanish qolgan, lekin kamera boshqa binoda - kalit berilmaydi.
        """
        other_zone = factories.make_zone()
        camera = self._ip_camera(zone=other_zone)
        response = self.request("post", self.url, {"camera_id": camera.pk})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "camera_not_available")

    def test_unbound_camera_in_the_building_is_rejected(self):
        """
        Bu himoyaning asosiy qatlami: ro'yxat bilan bir qoida. Aks holda
        buzilgan mashina binodagi har qanday kameraning kalitini
        `camera_id` ni sanab olardi.
        """
        camera = self._ip_camera(bind=False)
        response = self.request("post", self.url, {"camera_id": camera.pk})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "camera_not_available")
        self.assertFalse(AuditLog.objects.filter(action="camera_credential_issue").exists())

    def test_inactive_camera_is_rejected(self):
        """Nofaol kamera - hisobdan chiqarilgan uskuna, kaliti kerak emas."""
        camera = self._ip_camera()
        Camera.objects.filter(pk=camera.pk).update(is_active=False)

        response = self.request("post", self.url, {"camera_id": camera.pk})
        self.assertEqual(response.status_code, 404)

    def test_issuance_is_audited(self):
        """
        Kredensial berilishi jurnalga tushishi SHART.

        RTSP paroli kameraning ichida yashaydi va uni serverdan
        bekor qilib bo'lmaydi - ya'ni parol sizib chiqqan taqdirda
        "kim, qachon, qaysi mashinada oldi" degan savolga javob
        beradigan yagona manba shu yozuv.
        """
        camera = self._ip_camera()
        self.request("post", self.url, {"camera_id": camera.pk, "role": "secondary"})

        entry = AuditLog.objects.filter(action="camera_credential_issue").first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.object_id, str(camera.pk))
        self.assertEqual(entry.meta["device_id"], self.device.device_id)
        # Rol AUDIT uchun saqlanadi: ikkita kamerali mashinada
        # yozuvlarni ajratadigan yagona maydon.
        self.assertEqual(entry.meta["role"], "secondary")
        # Parol audit yozuvida ham bo'lmasligi kerak.
        self.assertNotIn("s3cret", str(entry.meta))

    def test_preview_role_for_unassigned_camera(self):
        """
        Tekshiruv sahifasida VAZIFASI HALI BERILMAGAN kamera ham ochiladi.

        Ikkita veb-kamerali mashinada binodagi IP kamera uchinchi
        qurilma bo'ladi: operator uni ko'rib turib vazifa berishi
        uchun oqim kerak. Rol audit'da `preview` bo'lib qoladi -
        "kuzatuvda ishlatildi" bilan aralashmasligi uchun.
        """
        camera = self._ip_camera()
        response = self.request("post", self.url, {"camera_id": camera.pk, "role": "preview"})
        self.assertEqual(response.status_code, 200, response.content)
        entry = AuditLog.objects.filter(action="camera_credential_issue").first()
        self.assertEqual(entry.meta["role"], "preview")

    def test_unknown_role_is_rejected(self):
        camera = self._ip_camera()
        response = self.request("post", self.url, {"camera_id": camera.pk, "role": "spare:dev:x"})
        self.assertEqual(response.status_code, 400)

    def test_missing_camera_id_is_a_validation_error(self):
        response = self.request("post", self.url, {"role": "primary"})
        self.assertEqual(response.status_code, 400)

    def test_requires_authentication(self):
        camera = self._ip_camera()
        response = self.client.post(
            self.url,
            {"camera_id": camera.pk},
            format="json",
            HTTP_X_DEVICE_ID=self.device.device_id,
            REMOTE_ADDR="8.8.8.8",
        )
        self.assertEqual(response.status_code, 401)


class ExamConfigTests(CameraApiTestCase):
    """
    Tanlangan imtihonning to'liq profili.

    Bu endpointning butun mavjudlik sababi handshake'dagi bo'shliq:
    u global standartni qaytaradi va imtihonning o'z profili
    (`Exam.setting`) client'ga HECH QACHON yetib bormasdi. Natijada
    server imtihon profilini ishlatar (`verify_periodic_face`), client
    esa global profilni - va farqni faqat log'dan topish mumkin edi.
    """

    def setUp(self):
        super().setUp()
        self.url = reverse("client-exam-config")

    def test_exam_setting_overrides_global(self):
        exam_setting = factories.make_setting(faceid_min_score_exam=85)
        exam = factories.make_exam(setting=exam_setting)
        factories.make_setting(is_active=True, faceid_min_score_exam=70)

        payload = self.request("get", f"{self.url}?exam={exam.pk}").json()["data"]

        self.assertEqual(payload["config"]["face"]["min_score_exam"], 85)
        self.assertEqual(payload["setting"]["id"], exam_setting.pk)
        self.assertTrue(payload["setting"]["is_exam_specific"])

    def test_exam_without_setting_falls_back_to_global(self):
        """
        Profilsiz imtihon global standartni oladi va JAVOBDA buni
        aytadi.

        `is_exam_specific=False` client uchun muhim: u shu bayroqni
        modalda ko'rsatadi va operator "nega bu yerda boshqa talab?"
        degan savolga javob topadi.
        """
        factories.make_setting(is_active=True, faceid_min_score_exam=70)
        exam = factories.make_exam()

        payload = self.request("get", f"{self.url}?exam={exam.pk}").json()["data"]

        self.assertEqual(payload["config"]["face"]["min_score_exam"], 70)
        self.assertFalse(payload["setting"]["is_exam_specific"])

    def test_proctoring_policy_is_included(self):
        setting = factories.make_setting()
        ProctoringPolicy.objects.create(
            setting=setting, is_enabled=True, camera_count=2, secondary_required=True
        )
        exam = factories.make_exam(setting=setting)

        policy = self.request("get", f"{self.url}?exam={exam.pk}").json()["data"]["config"][
            "proctoring"
        ]

        self.assertTrue(policy["enabled"])
        self.assertEqual(policy["camera"]["count"], 2)
        self.assertTrue(policy["camera"]["secondary_required"])

    def test_missing_exam_id_is_a_validation_error(self):
        self.assertEqual(self.request("get", self.url).status_code, 400)

    def test_unknown_exam_is_404(self):
        self.assertEqual(
            self.request("get", f"{self.url}?exam=999999").status_code, 404
        )

    def test_inactive_exam_is_404(self):
        """
        Nofaol imtihon client uchun MAVJUD EMAS.

        Admin panelida u ko'rinadi (administrator uni yoqishdan oldin
        profilini tekshirishi kerak), client yuzasida esa yo'q.
        """
        exam = factories.make_exam(is_active=False)
        self.assertEqual(
            self.request("get", f"{self.url}?exam={exam.pk}").status_code, 404
        )

    def test_forbidden_source_ip_is_rejected(self):
        exam = factories.make_exam()
        response = self.client.get(
            f"{self.url}?exam={exam.pk}",
            HTTP_AUTHORIZATION=bearer(self.user),
            HTTP_X_DEVICE_ID=self.device.device_id,
            REMOTE_ADDR="1.2.3.4",
        )
        self.assertEqual(response.status_code, 403)
