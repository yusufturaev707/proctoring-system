"""
Kompyuter identifikatori - (Machine UUID, MAC) JUFTLIGI.

Arzon platalarda SMBIOS UUID bir partiyada bir xil bo'ladi: UUID bir
xil, MAC boshqa ikki mashina - ikki BOSHQA kompyuter. Qoida bitta
joyda (`services.find_computer_by_identity`); bu testlar uni har bir
iste'molchida tekshiradi: model, handshake, ro'yxatdan o'tish, apparat
izi, MAC'siz eski yozuvlar va audit buyrug'i.
"""

from io import StringIO

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.devices import services
from apps.devices.models import Computer, DeviceToken
from apps.proctoring.models import AuditLog
from apps.proctoring.tests import factories

UUID = "4C4C4544-0038-4A10-805A-C7C04F4B3A41"
MAC_A = "2C:F0:5D:77:BB:0A"
MAC_B = "2C:F0:5D:77:BB:0B"
FOREIGN_MAC = "00:E0:4C:68:01:02"


class PairConstraintTests(TestCase):
    def setUp(self):
        self.zone = factories.make_zone()

    def test_same_uuid_different_mac_are_two_computers(self):
        factories.make_computer(zone=self.zone, machine_uuid=UUID, mac_address=MAC_A)
        factories.make_computer(zone=self.zone, machine_uuid=UUID, mac_address=MAC_B)
        self.assertEqual(Computer.objects.filter(machine_uuid=UUID).count(), 2)

    def test_same_pair_is_rejected_by_the_database(self):
        factories.make_computer(zone=self.zone, machine_uuid=UUID, mac_address=MAC_A)
        with self.assertRaises(IntegrityError), transaction.atomic():
            factories.make_computer(zone=self.zone, machine_uuid=UUID, mac_address=MAC_A)

    def test_deleted_computer_frees_the_pair(self):
        old = factories.make_computer(zone=self.zone, machine_uuid=UUID, mac_address=MAC_A)
        old.delete()
        factories.make_computer(zone=self.zone, machine_uuid=UUID, mac_address=MAC_A)


class VerifyMachinePairTests(TestCase):
    """Handshake jadvalining har qatori (`verify_machine`)."""

    def setUp(self):
        self.zone = factories.make_zone()
        self.computer = factories.make_computer(zone=self.zone, machine_uuid=UUID, mac_address=MAC_A)
        self.device = factories.make_device(computer=self.computer)

    def verify(self, mac, *, uuid=UUID, device=None):
        return services.verify_machine(device or self.device, machine_uuid=uuid, mac_address=mac)

    def test_exact_pair_is_ok(self):
        result = self.verify(MAC_A)
        self.assertEqual((result["status"], result["legacy_no_mac"]), (services.MACHINE_OK, False))

    def test_mac_is_normalized(self):
        """`getmac` chiziqcha va kichik harf beradi - bu farq EMAS."""
        self.assertEqual(self.verify("2c-f0-5d-77-bb-0a")["status"], services.MACHINE_OK)

    def test_pair_of_another_computer_is_mismatch(self):
        """Bir xil UUID'li qo'shni mashina - boshqa kompyuter, nomlari xabarda."""
        sibling = factories.make_computer(zone=self.zone, machine_uuid=UUID, mac_address=MAC_B)

        result = self.verify(MAC_B)

        self.assertEqual(result["status"], services.MACHINE_MISMATCH)
        self.assertEqual(result["computer_code"], sibling.inventory_code)
        self.assertIn(self.computer.label, result["message"])
        self.assertIn(sibling.label, result["message"])

    def test_same_uuid_unknown_mac_is_not_found_with_both_macs(self):
        result = self.verify(FOREIGN_MAC)

        self.assertEqual(result["status"], services.MACHINE_NOT_FOUND)
        self.assertEqual(result["expected_mac"], MAC_A)
        self.assertEqual(result["mac_address"], FOREIGN_MAC)
        self.assertIn(MAC_A.lower(), result["message"])
        self.assertIn(FOREIGN_MAC.lower(), result["message"])

    def test_missing_mac_is_not_found(self):
        """Maydonni bo'sh yoki buzuq yuborib tekshiruvni chetlab o'tib bo'lmaydi."""
        for mac in ("", "not-a-mac"):
            with self.subTest(mac=mac):
                result = self.verify(mac)
                self.assertEqual(result["status"], services.MACHINE_NOT_FOUND)
                self.assertIn("MAC aniqlanmadi", result["message"])

    def test_legacy_client_without_uuid_uses_mac_rule(self):
        ok = services.verify_machine(self.device, mac_address="2c-f0-5d-77-bb-0a")
        self.assertEqual((ok["status"], ok["basis"]), (services.MACHINE_OK, "mac"))
        other = services.verify_machine(self.device, mac_address=FOREIGN_MAC)
        self.assertEqual(other["status"], services.MACHINE_NOT_FOUND)

    def test_inactive_wins(self):
        """Hisobdan chiqarilgan - juftlik mos bo'lsa ham, MAC farq qilsa ham."""
        Computer.objects.filter(pk=self.computer.pk).update(is_active=False)
        self.device.refresh_from_db()
        for mac in (MAC_A, FOREIGN_MAC):
            with self.subTest(mac=mac):
                self.assertEqual(self.verify(mac)["status"], services.MACHINE_INACTIVE)

    def test_bind_path_writes_uuid_once(self):
        legacy = factories.make_computer(zone=self.zone, machine_uuid=None, mac_address=MAC_B)
        device = factories.make_device(computer=legacy)

        result = self.verify("2c-f0-5d-77-bb-0b", device=device)

        self.assertEqual((result["status"], result["bound"]), (services.MACHINE_OK, True))
        legacy.refresh_from_db()
        # UUID boshqa yozuvda (boshqa MAC bilan) band bo'lsa ham - bu
        # juftlik yangi, ya'ni boshqa mashina.
        self.assertEqual((legacy.machine_uuid, legacy.mac_address), (UUID, MAC_B))

    def test_verdict_never_writes_mac_or_audit(self):
        before = AuditLog.objects.count()
        self.verify(FOREIGN_MAC)
        self.computer.refresh_from_db()
        self.assertEqual(self.computer.mac_address, MAC_A)
        self.assertEqual(AuditLog.objects.count(), before)


class LegacyRecordWithoutMacTests(TestCase):
    """O'tish davri: MAC'siz eski yozuv faqat UUID bilan, shu UUID yolg'iz bo'lsa."""

    def setUp(self):
        self.zone = factories.make_zone()
        self.legacy = factories.make_computer(zone=self.zone, machine_uuid=UUID, mac_address="")
        self.device = factories.make_device(computer=self.legacy)

    def test_single_legacy_record_matches_by_uuid_with_flag_and_warning(self):
        self.assertEqual(services.find_computer_by_identity(self.zone.pk, UUID, MAC_A), self.legacy)
        with self.assertLogs("apps.devices.services", level="WARNING") as logs:
            result = services.verify_machine(self.device, machine_uuid=UUID, mac_address=MAC_A)
        self.assertEqual((result["status"], result["legacy_no_mac"]), (services.MACHINE_OK, True))
        self.assertIn("MAC'siz eski yozuv", logs.output[0])

    def test_second_record_with_same_uuid_stops_the_match(self):
        """MAC'li qo'shni qo'shildi - UUID endi mashinani ajratmaydi."""
        factories.make_computer(zone=self.zone, machine_uuid=UUID, mac_address=MAC_B)

        self.assertIsNone(services.find_computer_by_identity(self.zone.pk, UUID, MAC_A))
        result = services.verify_machine(self.device, machine_uuid=UUID, mac_address=MAC_A)

        self.assertEqual(result["status"], services.MACHINE_NOT_FOUND)
        self.assertIn("MAC manzilni", result["message"])


class RegisterPairTests(TestCase):
    """`devices/register/` - "o'sha mashinami" qarori juftlik bo'yicha."""

    def setUp(self):
        self.client = APIClient()
        self.zone = factories.make_zone()
        self.pc_a = factories.make_computer(zone=self.zone, machine_uuid=UUID, mac_address=MAC_A)
        self.device_a = factories.make_device(
            computer=self.pc_a, hardware_fingerprint="muid:" + UUID
        )

    def register(self, mac):
        return self.client.post(
            reverse("device-register"),
            {
                "machine_uuid": UUID,
                "mac_address": mac,
                "hardware_fingerprint": services.fingerprint_for(UUID, mac),
                "app_version": "1.0.0",
            },
            format="json",
            REMOTE_ADDR="8.8.8.8",
        )

    def test_second_machine_with_same_uuid_does_not_take_first_device_id(self):
        pc_b = factories.make_computer(zone=self.zone, machine_uuid=UUID, mac_address=MAC_B)

        response = self.register(MAC_B)

        self.assertEqual(response.status_code, 201, response.content)
        device_id = response.json()["data"]["device_id"]
        self.assertNotEqual(device_id, self.device_a.device_id)
        self.assertEqual(DeviceToken.objects.get(device_id=device_id).computer, pc_b)

    def test_unlisted_sibling_is_not_found_rather_than_first_machine(self):
        response = self.register(MAC_B)
        self.assertEqual(response.status_code, 404, response.content)
        self.assertNotIn(self.device_a.device_id, response.content.decode())

    def test_same_machine_gets_its_device_id_back(self):
        """Juftlik mos - izi hali eski `muid:<UUID>` bo'lsa ham o'sha mashina."""
        response = self.register("2c-f0-5d-77-bb-0a")
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["error"]["details"]["device_id"], self.device_a.device_id)


class FingerprintPairTests(TestCase):
    """Iz formati: `muid:<UUID>` -> `muid:<UUID>|mac:<MAC>`."""

    def setUp(self):
        self.computer = factories.make_computer(machine_uuid=UUID, mac_address=MAC_A)
        self.device = factories.make_device(computer=self.computer, hardware_fingerprint="muid:" + UUID)

    def test_format_matches_client(self):
        self.assertEqual(services.fingerprint_for(UUID.lower(), "2c-f0-5d-77-bb-0a"), f"muid:{UUID}|mac:{MAC_A}")
        self.assertEqual(services.fingerprint_for(UUID, ""), "muid:" + UUID)

    def test_upgrade_with_record_mac_is_silent(self):
        new = f"muid:{UUID}|mac:{MAC_A}"
        anomalies = services.record_handshake(self.device, hardware_fingerprint=new, reported_mac=MAC_A)
        self.assertEqual(anomalies, [])
        self.device.refresh_from_db()
        self.assertEqual(self.device.hardware_fingerprint, new)

    def test_upgrade_with_other_mac_is_an_anomaly(self):
        """UUID mos, lekin MAC yozuvdagidan boshqa - bir partiyadagi boshqa mashina."""
        anomalies = services.record_handshake(
            self.device, hardware_fingerprint=f"muid:{UUID}|mac:{MAC_B}", reported_mac=MAC_B
        )
        self.assertEqual([a["kind"] for a in anomalies], ["fingerprint_changed"])
        self.device.refresh_from_db()
        self.assertEqual(self.device.hardware_fingerprint, "muid:" + UUID)

    def test_oldest_mac_format_still_upgrades(self):
        """`MAC|host|OS|arch` -> yangi format: avvalgi o'tish buzilmagan."""
        DeviceToken.objects.filter(pk=self.device.pk).update(
            hardware_fingerprint=f"{MAC_A}|PC-41|Windows|AMD64"
        )
        self.device.refresh_from_db()
        anomalies = services.record_handshake(
            self.device, hardware_fingerprint=f"muid:{UUID}|mac:{MAC_A}", reported_mac="2c-f0-5d-77-bb-0a"
        )
        self.assertEqual(anomalies, [])

    def test_same_uuid_siblings_no_longer_share_a_fingerprint(self):
        self.assertFalse(
            services.fingerprint_matches(f"muid:{UUID}|mac:{MAC_A}", f"muid:{UUID}|mac:{MAC_B}", MAC_B, MAC_A)
        )


class ReportedMacTests(TestCase):
    """`record_handshake` mashina aytgan MAC'ni saqlaydi (audit va panel uchun)."""

    def setUp(self):
        self.device = factories.make_device()

    def test_reported_mac_is_normalized_and_saved(self):
        services.record_handshake(self.device, reported_mac="2c-f0-5d-77-bb-eb")
        self.device.refresh_from_db()
        self.assertEqual(self.device.reported_mac, "2C:F0:5D:77:BB:EB")

    def test_empty_or_invalid_mac_keeps_previous_value(self):
        DeviceToken.objects.filter(pk=self.device.pk).update(reported_mac="2C:F0:5D:77:BB:EB")
        self.device.refresh_from_db()
        for mac in ("", "not-a-mac"):
            services.record_handshake(self.device, reported_mac=mac)
        self.device.refresh_from_db()
        self.assertEqual(self.device.reported_mac, "2C:F0:5D:77:BB:EB")


class AuditMachineIdentityCommandTests(TestCase):
    """Buyruq uch ro'yxatni beradi va HECH NARSA yozmaydi."""

    def setUp(self):
        self.zone = factories.make_zone()
        self.good = factories.make_computer(zone=self.zone, mac_address="AA:BB:CC:00:00:01")
        factories.make_device(computer=self.good, reported_mac="AA:BB:CC:00:00:01")
        self.changed = factories.make_computer(zone=self.zone, mac_address="AA:BB:CC:00:00:02")
        factories.make_device(computer=self.changed, reported_mac=FOREIGN_MAC)
        self.no_mac = factories.make_computer(zone=self.zone, mac_address="")
        self.twin_a = factories.make_computer(zone=self.zone, machine_uuid=UUID, mac_address=MAC_A)
        self.twin_b = factories.make_computer(zone=self.zone, machine_uuid=UUID, mac_address=MAC_B)

    def run_command(self, *args):
        out = StringIO()
        call_command("audit_machine_identity", *args, stdout=out)
        return out.getvalue()

    def snapshot(self):
        return (
            list(DeviceToken.objects.order_by("pk").values_list("pk", "reported_mac", "last_used_at")),
            list(Computer.objects.order_by("pk").values_list("pk", "mac_address", "machine_uuid", "updated_at")),
        )

    def test_reports_all_three_lists_and_writes_nothing(self):
        before = self.snapshot()

        output = self.run_command()

        self.assertIn(self.no_mac.inventory_code, output)
        self.assertIn(self.twin_a.inventory_code, output)
        self.assertIn(self.twin_b.inventory_code, output)
        self.assertIn(self.changed.inventory_code, output)
        self.assertIn(FOREIGN_MAC, output)
        self.assertNotIn(self.good.inventory_code, output)
        self.assertIn("MAC'siz: 1 ta; bir xil UUID'li guruh: 1 ta; mashina aytgan MAC "
                      "yozuvdagidan farq qiladi: 1 ta", output)
        self.assertEqual(self.snapshot(), before)

    def test_zone_filter(self):
        output = self.run_command("--zone", str(factories.make_zone().pk))
        self.assertIn("MAC'siz: 0 ta; bir xil UUID'li guruh: 0 ta", output)
