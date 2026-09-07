"""
Desktop client API yuzasi (`/api/v1/client/...`).

Bu yerdagi testlar HTTP darajasida: javob konverti, status kodlari va
autentifikatsiya qatlamlari. Ular admin API'dan ataylab ajratilgan
yuzani himoya qiladi - u yerda boshqa auth, boshqa throttling va
boshqa xavf profili.
"""

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.common.tests.utils import RedisStateMixin
from apps.controls.models import AllowedPublicIp, ClientExitPassword
from apps.proctoring.models import AuditLog
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
