"""
Administrator MAC'ni (yoki UUID'ni) yangilaganda qurilma etaloni ham ko'chadi.

Holat: monoblok Wi-Fi'ga o'tdi, administrator panelda MAC'ni yangiladi.
Mashina tekshiruvi darhol `ok`, lekin etalon eski MAC'li izda qolardi va
HAR handshake auditga `fingerprint_changed` yozardi — haqiqiy klon shu
shovqin ichida yo'qolardi.
"""

from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.devices import services
from apps.devices.admin import ComputerAdmin
from apps.devices.models import Computer, DeviceToken
from apps.proctoring.models import AuditLog
from apps.proctoring.tests import factories
from apps.proctoring.tests.test_client_api import bearer

#: Shu mashinaning Wi-Fi adapteri.
WIFI_MAC = "3C:91:80:11:22:33"


class RebaselineServiceTests(TestCase):
    def setUp(self):
        self.computer = factories.make_computer()
        self.old_uuid = self.computer.machine_uuid
        self.old_mac = self.computer.mac_address
        self.device = factories.make_device(
            computer=self.computer,
            hardware_fingerprint=services.fingerprint_for(self.old_uuid, self.old_mac),
        )

    def change_mac(self, mac=WIFI_MAC):
        self.computer.mac_address = mac
        self.computer.save(update_fields=["mac_address"])
        return services.rebaseline_fingerprints(
            self.computer, old_uuid=self.old_uuid, old_mac=self.old_mac
        )

    def test_genuine_device_moves_to_new_pair(self):
        moved = self.change_mac()

        self.device.refresh_from_db()
        self.assertEqual(moved, [self.device.device_id])
        self.assertEqual(
            self.device.hardware_fingerprint, services.fingerprint_for(self.old_uuid, WIFI_MAC)
        )

    def test_next_handshake_has_no_anomaly(self):
        """Asosiy natija: Wi-Fi MAC bilan kelgan handshake endi shovqin bermaydi."""
        self.change_mac()
        self.device.refresh_from_db()

        anomalies = services.record_handshake(
            self.device,
            hardware_fingerprint=services.fingerprint_for(self.old_uuid, WIFI_MAC),
            reported_machine_uuid=self.old_uuid,
            reported_mac=WIFI_MAC,
        )

        self.assertEqual(anomalies, [])

    def test_without_rebaseline_handshake_reports_anomaly(self):
        """Tuzatishsiz holat — shu test yuqoridagisining ma'nosini ko'rsatadi."""
        self.computer.mac_address = WIFI_MAC
        self.computer.save(update_fields=["mac_address"])

        anomalies = services.record_handshake(
            self.device,
            hardware_fingerprint=services.fingerprint_for(self.old_uuid, WIFI_MAC),
            reported_machine_uuid=self.old_uuid,
            reported_mac=WIFI_MAC,
        )

        self.assertEqual([item["kind"] for item in anomalies], ["fingerprint_changed"])

    def test_suspicious_device_keeps_its_anomaly(self):
        """Etaloni eski juftlikka teng bo'lmagan qurilma — tegilmaydi."""
        foreign = factories.make_device(
            computer=self.computer, hardware_fingerprint="muid:SOME-OTHER-BOARD|mac:AA:00:00:00:00:01"
        )

        moved = self.change_mac()

        foreign.refresh_from_db()
        self.assertNotIn(foreign.device_id, moved)
        self.assertEqual(foreign.hardware_fingerprint, "muid:SOME-OTHER-BOARD|mac:AA:00:00:00:00:01")

    def test_revoked_device_is_untouched(self):
        DeviceToken.objects.filter(pk=self.device.pk).update(status=DeviceToken.Status.REVOKED)

        self.assertEqual(self.change_mac(), [])

    def test_legacy_uuid_only_fingerprint_is_upgraded(self):
        """MAC'siz eski yozuv: etalon `muid:<UUID>` edi, MAC kiritilgach — juftlikka."""
        legacy = factories.make_computer(mac_address="")
        uuid = legacy.machine_uuid
        device = factories.make_device(
            computer=legacy, hardware_fingerprint=services.fingerprint_for(uuid, "")
        )
        legacy.mac_address = WIFI_MAC
        legacy.save(update_fields=["mac_address"])

        moved = services.rebaseline_fingerprints(legacy, old_uuid=uuid, old_mac="")

        device.refresh_from_db()
        self.assertEqual(moved, [device.device_id])
        self.assertEqual(device.hardware_fingerprint, services.fingerprint_for(uuid, WIFI_MAC))

    def test_nothing_happens_without_change_or_uuid(self):
        self.assertEqual(self.change_mac(self.old_mac), [])
        no_uuid = factories.make_computer(machine_uuid=None)
        self.assertEqual(
            services.rebaseline_fingerprints(no_uuid, old_uuid="", old_mac=no_uuid.mac_address), []
        )


class RebaselineEntryPointTests(TestCase):
    """Panel (`PATCH computers/{id}/`) va Django admin — bir xil qoida."""

    def setUp(self):
        self.computer = factories.make_computer()
        self.old_uuid = self.computer.machine_uuid
        self.device = factories.make_device(
            computer=self.computer,
            hardware_fingerprint=services.fingerprint_for(
                self.old_uuid, self.computer.mac_address
            ),
        )
        self.expected = services.fingerprint_for(self.old_uuid, WIFI_MAC)

    def test_panel_update_rebaselines_and_audits(self):
        user = factories.make_user(permissions=["devices.view", "devices.manage"])

        response = APIClient().patch(
            reverse("computer-detail", args=[self.computer.pk]),
            {"mac_address": WIFI_MAC},
            format="json",
            HTTP_AUTHORIZATION=bearer(user),
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.device.refresh_from_db()
        self.assertEqual(self.device.hardware_fingerprint, self.expected)
        audit = AuditLog.objects.filter(
            object_type="Computer", object_id=str(self.computer.pk), action="update"
        ).latest("id")
        self.assertEqual(audit.meta["fingerprint_rebaselined"], [self.device.device_id])

    def test_panel_update_of_other_fields_changes_nothing(self):
        user = factories.make_user(permissions=["devices.view", "devices.manage"])
        before = self.device.hardware_fingerprint

        response = APIClient().patch(
            reverse("computer-detail", args=[self.computer.pk]),
            {"number": 777},
            format="json",
            HTTP_AUTHORIZATION=bearer(user),
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.device.refresh_from_db()
        self.assertEqual(self.device.hardware_fingerprint, before)

    def test_django_admin_save_rebaselines(self):
        class _Form:
            initial = {
                "machine_uuid": self.computer.machine_uuid,
                "mac_address": self.computer.mac_address,
            }

        request = RequestFactory().post("/admin/")
        request.user = factories.make_user(is_superuser=True, is_staff=True)
        obj = Computer.objects.get(pk=self.computer.pk)
        obj.mac_address = WIFI_MAC

        ComputerAdmin(Computer, AdminSite()).save_model(request, obj, _Form(), change=True)

        self.device.refresh_from_db()
        self.assertEqual(self.device.hardware_fingerprint, self.expected)
