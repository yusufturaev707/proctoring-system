"""
Qat'iy rejim (`REQUIRE_MACHINE_MAC=true`): UUID mos kelgan mashinada MAC
ham yozuvdagiga mos bo'lishi shart.

Har holat alohida, chunki ularning har biri boshqa tuzatishga olib
boradi: MAC farqi - yozuvni yangilash yoki ortiqcha adapterni o'chirish,
UUID farqi - avvalgidek qayta biriktirish.
"""

from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase

from apps.devices import services
from apps.devices.models import Computer, DeviceToken
from apps.proctoring.models import AuditLog
from apps.proctoring.tests import factories


class RequireMachineMacTests(TestCase):
    UUID = "4C4C4544-0038-4A10-805A-C7C04F4B3A41"
    MAC = "2C:F0:5D:77:BB:EB"

    def setUp(self):
        self.zone = factories.make_zone()
        self.computer = factories.make_computer(
            zone=self.zone, machine_uuid=self.UUID, mac_address=self.MAC
        )
        self.device = factories.make_device(computer=self.computer)
        patcher = patch.dict(settings.PROCTORING, {"REQUIRE_MACHINE_MAC": True})
        patcher.start()
        self.addCleanup(patcher.stop)

    def verify(self, mac, *, device=None, uuid=None):
        return services.verify_machine(
            device or self.device, machine_uuid=uuid or self.UUID, mac_address=mac
        )

    def test_uuid_and_mac_match(self):
        result = self.verify(self.MAC)
        self.assertEqual(result["status"], services.MACHINE_OK)
        self.assertEqual(result["message"], "")

    def test_mac_is_normalized_before_comparison(self):
        """`getmac` chiziqcha va kichik harf beradi - bu farq EMAS."""
        result = self.verify("2c-f0-5d-77-bb-eb")
        self.assertEqual(result["status"], services.MACHINE_OK)

    def test_other_mac_is_mac_mismatch(self):
        result = self.verify("00-E0-4C-68-01-02")

        self.assertEqual(result["status"], services.MACHINE_MAC_MISMATCH)
        self.assertEqual(result["expected_mac"], self.MAC)
        self.assertEqual(result["mac_address"], "00:E0:4C:68:01:02")
        self.assertEqual(result["computer_code"], self.computer.inventory_code)
        # Xabar IKKALA qiymatni bir xil shaklda aytadi - administrator
        # farqni bazadan qidirmaydi.
        self.assertIn("2c:f0:5d:77:bb:eb", result["message"])
        self.assertIn("00:e0:4c:68:01:02", result["message"])
        self.assertIn(self.computer.label, result["message"])

    def test_missing_mac_is_mac_mismatch(self):
        """Maydonni bo'sh yuborish qat'iy rejimni chetlab o'tmaydi."""
        for mac in ("", "not-a-mac"):
            with self.subTest(mac=mac):
                result = self.verify(mac)
                self.assertEqual(result["status"], services.MACHINE_MAC_MISMATCH)
                self.assertIn("MAC aniqlanmadi", result["message"])

    def test_record_without_mac_passes_on_uuid_alone(self):
        """MAC'ni administrator kiritadi; kiritilmagan bo'lsa faqat UUID."""
        Computer.objects.filter(pk=self.computer.pk).update(mac_address="")
        self.device.refresh_from_db()

        result = self.verify("00:E0:4C:68:01:02")

        self.assertEqual(result["status"], services.MACHINE_OK)
        self.computer.refresh_from_db()
        # Client MAC'ni HECH QACHON yozmaydi.
        self.assertEqual(self.computer.mac_address, "")

    def test_inactive_wins_over_mac(self):
        """Hisobdan chiqarilgan kompyuterda MAC'ni tuzatish foyda bermaydi."""
        Computer.objects.filter(pk=self.computer.pk).update(is_active=False)
        self.device.refresh_from_db()

        result = self.verify("00:E0:4C:68:01:02")

        self.assertEqual(result["status"], services.MACHINE_INACTIVE)

    def test_bound_path_is_ok(self):
        """Bog'lash MAC mosligiga tayanadi - MAC ta'rifga ko'ra mos."""
        legacy = factories.make_computer(
            zone=self.zone, machine_uuid=None, mac_address="AA:BB:CC:DD:EE:42"
        )
        device = factories.make_device(computer=legacy)

        result = self.verify(
            "aa-bb-cc-dd-ee-42", device=device, uuid="4C4C4544-0038-4A10-805A-C7C04F4B3A42"
        )

        self.assertEqual((result["status"], result["bound"]), (services.MACHINE_OK, True))

    def test_foreign_uuid_is_unchanged(self):
        other = factories.make_computer(zone=self.zone)
        self.assertEqual(
            self.verify(self.MAC, uuid=other.machine_uuid)["status"], services.MACHINE_MISMATCH
        )
        self.assertEqual(
            self.verify(self.MAC, uuid="4C4C4544-0038-4A10-805A-C7C04F4B3A99")["status"],
            services.MACHINE_NOT_FOUND,
        )

    def test_legacy_client_is_unchanged(self):
        """UUID yubormaydigan eski client - avvalgidek `_verify_by_mac`."""
        ok = services.verify_machine(self.device, mac_address="2c-f0-5d-77-bb-eb")
        self.assertEqual((ok["status"], ok["basis"]), (services.MACHINE_OK, "mac"))
        other = services.verify_machine(self.device, mac_address="00:E0:4C:68:01:02")
        self.assertEqual(other["status"], services.MACHINE_NOT_FOUND)

    def test_default_setting_keeps_old_behaviour(self):
        """Standart `false` - mavjud o'rnatishlar administrator yoqmaguncha o'zgarmaydi."""
        with patch.dict(settings.PROCTORING, {"REQUIRE_MACHINE_MAC": False}):
            for mac in ("00:E0:4C:68:01:02", ""):
                with self.subTest(mac=mac):
                    self.assertEqual(self.verify(mac)["status"], services.MACHINE_OK)

    def test_verdict_does_not_write_audit(self):
        """Operator "Yangilash" ni ketma-ket bosadi - rad etish jurnalni to'ldirmaydi."""
        before = AuditLog.objects.count()
        self.verify("00:E0:4C:68:01:02")
        self.assertEqual(AuditLog.objects.count(), before)


class DefaultSettingTests(TestCase):
    def test_setting_is_pinned_off_in_tests(self):
        """`.env` dagi qiymat testlarga o'tmaydi (`settings/test.py` mahkamlaydi)."""
        self.assertIs(settings.PROCTORING["REQUIRE_MACHINE_MAC"], False)


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


class AuditMachineMacsCommandTests(TestCase):
    """Buyruq qat'iy rejimda to'siladiganlarni aytadi va HECH NARSA yozmaydi."""

    def setUp(self):
        self.zone = factories.make_zone()
        self.good = factories.make_computer(zone=self.zone, mac_address="AA:BB:CC:00:00:01")
        factories.make_device(computer=self.good, reported_mac="AA:BB:CC:00:00:01")
        self.changed = factories.make_computer(zone=self.zone, mac_address="AA:BB:CC:00:00:02")
        factories.make_device(computer=self.changed, reported_mac="00:E0:4C:68:01:02")
        self.silent = factories.make_computer(zone=self.zone, mac_address="AA:BB:CC:00:00:03")
        factories.make_device(computer=self.silent)
        # MAC'siz yozuv faqat UUID bilan o'tadi - ro'yxatga tushmaydi.
        self.no_mac = factories.make_computer(zone=self.zone, mac_address="")
        factories.make_device(computer=self.no_mac, reported_mac="00:E0:4C:68:01:09")

    def run_command(self, *args):
        out = StringIO()
        call_command("audit_machine_macs", *args, stdout=out)
        return out.getvalue()

    def snapshot(self):
        return (
            list(DeviceToken.objects.order_by("pk").values_list("pk", "reported_mac", "last_used_at")),
            list(Computer.objects.order_by("pk").values_list("pk", "mac_address", "updated_at")),
        )

    def test_lists_only_computers_that_would_be_blocked(self):
        before = self.snapshot()

        output = self.run_command()

        self.assertIn(self.changed.inventory_code, output)
        self.assertIn("00:E0:4C:68:01:02", output)
        self.assertIn(self.silent.inventory_code, output)
        self.assertNotIn(self.good.inventory_code, output)
        self.assertNotIn(self.no_mac.inventory_code, output)
        self.assertIn("2 ta kompyuter to'siladi", output)
        self.assertIn("1 tasi hali MAC aytmagan", output)
        self.assertEqual(self.snapshot(), before)

    def test_zone_filter(self):
        output = self.run_command("--zone", str(factories.make_zone().pk))
        self.assertIn("0 ta kompyuter to'siladi", output)
