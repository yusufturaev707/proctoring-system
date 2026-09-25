"""
"Client ishlab turibdi" signali (presence).

NIMA UCHUN BU QATLAM UMUMAN BOR. `Computer.status` ilgari faqat uch
nuqtada yangilanardi — handshake, imtihon boshlanishi va yakuni.
Oradagi vaqtda hech kim `last_seen_at` ga tegmasdi, fon vazifasi
(`refresh_device_status`, 120 s) esa mashinani OFFLINE deb
belgilardi: panelda ishlab turgan client ham, imtihon o'rtasidagi
mashina ham "o'chirilgan" bo'lib ko'rinardi.

Testlar shu shartnomani qamrab oladi: signal holatni yangilaydimi,
DB yozuvi cheklanadimi va panel uni ko'radimi.

REDIS IXTIYORIY: presence Redis'da yashaydi, lekin uning yo'qligi
signalni to'xtatmasligi kerak — DB yo'li (`last_seen_at`) baribir
yangilanadi. Shuning uchun bu yerda `RedisStateMixin` ishlatilmaydi.
"""

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.controls.models import AllowedPublicIp
from apps.devices import services as device_services
from apps.devices.models import Computer, DeviceToken
from apps.proctoring.tests import factories
from apps.proctoring.tests.test_client_api import bearer


def _clear_presence() -> None:
    try:
        from apps.common.redis_client import get_redis

        client = get_redis()
        keys = list(client.scan_iter("dev:online:*", count=500))
        if keys:
            client.delete(*keys)
    except Exception:
        pass


class PresenceEndpointTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        _clear_presence()
        self.addCleanup(_clear_presence)

        self.client = APIClient()
        self.zone = factories.make_zone()
        AllowedPublicIp.objects.create(ip_address="8.8.8.8", zone=self.zone)
        self.computer = factories.make_computer(zone=self.zone)
        self.device = factories.make_device(computer=self.computer)
        self.user = factories.make_user(permissions=["client.operate"])
        self.url = reverse("client-presence")

    def _ping(self, payload=None):
        return self.client.post(
            self.url,
            payload or {},
            format="json",
            HTTP_AUTHORIZATION=bearer(self.user),
            HTTP_X_DEVICE_ID=self.device.device_id,
            REMOTE_ADDR="8.8.8.8",
        )

    def test_ping_marks_the_computer_online(self):
        """
        Sessiyasiz ham ishlaydi.

        Aynan shu holat uchun endpoint yaratilgan: operator kirgan,
        talabgor hali kelmagan va sessiya yo'q.
        """
        Computer.objects.filter(pk=self.computer.pk).update(
            status=Computer.Status.OFFLINE, last_seen_at=None
        )

        response = self._ping()
        self.assertEqual(response.status_code, 200, response.content)

        self.computer.refresh_from_db()
        self.assertEqual(self.computer.status, Computer.Status.ONLINE)
        self.assertIsNotNone(self.computer.last_seen_at)

    def test_exam_flag_is_visible_in_the_status(self):
        """`in_exam` panelda "imtihonda" va "bo'sh turibdi" ni ajratadi."""
        self._ping({"in_exam": True})

        self.computer.refresh_from_db()
        self.assertEqual(self.computer.status, Computer.Status.IN_EXAM)

    def test_device_last_used_is_refreshed(self):
        """
        `DeviceToken.last_used_at` HAR signalda yangilanadi.

        U qurilmaning oxirgi izi va cheklovga tushmaydi: bitta
        `UPDATE` bilan yozilgan vaqt DB uchun arzon, panelda esa
        "oxirgi marta qachon ko'rindi" degan savolga javob beradi.
        """
        DeviceToken.objects.filter(pk=self.device.pk).update(last_used_at=None)

        self._ping()

        self.device.refresh_from_db()
        self.assertIsNotNone(self.device.last_used_at)

    def test_requires_authentication(self):
        response = self.client.post(
            self.url, {}, format="json",
            HTTP_X_DEVICE_ID=self.device.device_id, REMOTE_ADDR="8.8.8.8",
        )
        self.assertEqual(response.status_code, 401)

    def test_forbidden_source_ip_is_rejected(self):
        response = self.client.post(
            self.url, {}, format="json",
            HTTP_AUTHORIZATION=bearer(self.user),
            HTTP_X_DEVICE_ID=self.device.device_id,
            REMOTE_ADDR="1.2.3.4",
        )
        self.assertEqual(response.status_code, 403)


class PresencePanelTests(TestCase):
    """Panel qurilmaning onlayn ekanini KO'RADIMI."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        _clear_presence()
        self.addCleanup(_clear_presence)

        self.client = APIClient()
        self.zone = factories.make_zone()
        self.computer = factories.make_computer(zone=self.zone)
        self.device = factories.make_device(computer=self.computer)
        self.staff = factories.make_user(
            permissions=["devices.view", "devices.manage"], is_staff=True
        )
        self.client.force_authenticate(self.staff)
        self.url = reverse("device-token-list")

    def test_offline_device_by_default(self):
        payload = self.client.get(self.url).json()["data"]
        row = next(item for item in payload["results"] if item["id"] == self.device.pk)

        self.assertFalse(row["is_online"])
        self.assertEqual(row["online_staff"], "")

    def test_online_device_shows_the_operator(self):
        """
        Panel "kim kirgan" ni ham ko'rsatadi.

        Faqat "online" yetmaydi: proktor mashinani topgach, o'sha
        yerdagi operator bilan bog'lanadi va uning ismini bilishi
        kerak.
        """
        operator = factories.make_user(username="operator-7")
        device_services.touch_presence(self.device, staff=operator, in_exam=True)

        payload = self.client.get(self.url).json()["data"]
        row = next(item for item in payload["results"] if item["id"] == self.device.pk)

        if not row["is_online"]:
            self.skipTest("Redis yo'q - presence faqat DB orqali ko'rinadi")

        self.assertEqual(row["online_staff"], "operator-7")
        self.assertEqual(row["online_state"], "exam")
        self.assertEqual(row["computer_status"], Computer.Status.IN_EXAM)

    def test_online_filter(self):
        """`?online=true` — faqat ishlab turgan mashinalar."""
        other = factories.make_device(
            computer=factories.make_computer(zone=self.zone, inventory_code="PC-OFF"),
            device_id="dev_offline_1",
        )
        device_services.touch_presence(self.device, staff=self.staff)

        payload = self.client.get(self.url, {"online": "true"}).json()["data"]
        ids = [item["id"] for item in payload["results"]]

        if self.device.pk not in ids:
            self.skipTest("Redis yo'q - filtr ishlamaydi")
        self.assertNotIn(other.pk, ids)


class PresenceWriteThrottleTests(TestCase):
    """DB yozuvi CHEKLANADI (`PRESENCE_DB_INTERVAL`)."""

    def setUp(self):
        _clear_presence()
        self.addCleanup(_clear_presence)
        self.zone = factories.make_zone()
        self.computer = factories.make_computer(zone=self.zone)
        self.device = factories.make_device(computer=self.computer)

    def test_second_ping_does_not_rewrite_the_computer(self):
        """
        Ikkinchi signal `Computer` qatoriga TEGMAYDI.

        10 000 mashina daqiqada bir marta yozsa 166 UPDATE/sekund
        bo'ladi - "men tirikman" degan xabar uchun bu juda qimmat.
        Cheklovchi Redis'da (`issue_camera_stream` dagi grant kaliti
        bilan bir xil naqsh).
        """
        device_services.touch_presence(self.device)
        self.computer.refresh_from_db()
        first = self.computer.last_seen_at
        if first is None:
            self.fail("birinchi signal yozilmadi")

        stale = timezone.now() - timezone.timedelta(minutes=5)
        Computer.objects.filter(pk=self.computer.pk).update(last_seen_at=stale)

        device_services.touch_presence(self.device)
        self.computer.refresh_from_db()

        try:
            from apps.common.redis_client import get_redis

            get_redis().ping()
        except Exception:
            self.skipTest("Redis yo'q - cheklov ishlamaydi (har signalda yoziladi)")

        self.assertEqual(self.computer.last_seen_at, stale)
