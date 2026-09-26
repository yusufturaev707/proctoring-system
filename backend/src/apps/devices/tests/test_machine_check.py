"""
Mashina tekshiruvi: client aytgan MAC bazadagi ro'yxatga mos keladimi.

NIMA UCHUN BU TEKSHIRUV UMUMAN BOR. `X-Device-ID` mashinani emas,
client NUSXASINI belgilaydi: u diskda fayl bo'lib yotadi va mashina
obrazi ko'chirilganda (imtihon markazlarida odatiy amaliyot) u ham
ko'chadi. O'shanda o'nlab mashina bitta `device_id` bilan ishlaydi
va barcha sessiyalar bitta kompyuterga yoziladi — dashboard
"1-xona, 1-kompyuter" deb turgan paytda talabgor boshqa xonada
o'tiradi.

Testlar SHU HOLATLARNI qamrab oladi, chunki ularning har biri
boshqa xabar va boshqa tuzatish yo'lini talab qiladi.
"""

from django.test import TestCase

from apps.devices import services
from apps.devices.models import Computer
from apps.proctoring.tests import factories


class VerifyMachineTests(TestCase):
    def setUp(self):
        self.zone = factories.make_zone()
        self.computer = factories.make_computer(
            zone=self.zone, mac_address="AA:BB:CC:DD:EE:01"
        )
        self.device = factories.make_device(computer=self.computer)

    def test_matching_mac_passes(self):
        result = services.verify_machine(self.device, mac_address="AA:BB:CC:DD:EE:01")

        self.assertEqual(result["status"], services.MACHINE_OK)
        self.assertEqual(result["computer_code"], self.computer.inventory_code)
        # Muvaffaqiyatda xabar BO'SH: ko'rsatadigan narsa yo'q va
        # bo'sh bo'lmagan matn client'da bekorga chiqib turardi.
        self.assertEqual(result["message"], "")

    def test_mac_is_normalized_before_comparison(self):
        """
        Format farqi nomuvofiqlik EMAS.

        Windows `getmac` chiziqcha bilan qaytaradi
        (`AA-BB-CC-DD-EE-01`), administrator esa panelga ikki nuqta
        bilan kiritadi. Solishtirishdan oldin normallashtirilmasa,
        to'g'ri ro'yxatga olingan mashina ham rad etilardi.
        """
        result = services.verify_machine(self.device, mac_address="aa-bb-cc-dd-ee-01")

        self.assertEqual(result["status"], services.MACHINE_OK)

    def test_unknown_mac_in_zone_is_not_found(self):
        result = services.verify_machine(self.device, mac_address="AA:BB:CC:DD:EE:99")

        self.assertEqual(result["status"], services.MACHINE_NOT_FOUND)
        self.assertIn("AA:BB:CC:DD:EE:99", result["message"])
        # Xabar QAYSI bino qidirilganini aytadi: operator uni
        # administratorga aynan shu ko'rinishda yetkazadi.
        self.assertIn(self.zone.name, result["message"])

    def test_not_found_message_names_the_expected_mac(self):
        """
        Xabar KUTILGAN qiymatni ham aytadi.

        Eng ko'p uchraydigan sabab — mashina ro'yxatga OLINGAN,
        lekin yozuvdagi MAC boshqa (xato kiritilgan yoki tarmoq
        kartasi almashtirilgan). Usiz administrator "men bu
        mashinani qo'shganman-ku" deb qolardi va farq qilayotgan
        ikki qiymatni bazadan qo'lda qidirishga majbur bo'lardi.
        """
        result = services.verify_machine(self.device, mac_address="AA:BB:CC:DD:EE:99")

        self.assertEqual(result["expected_mac"], "AA:BB:CC:DD:EE:01")
        self.assertIn("AA:BB:CC:DD:EE:01", result["message"])
        self.assertIn(self.computer.inventory_code, result["message"])

    def test_mac_of_another_computer_is_mismatch(self):
        """
        Qurilma boshqa mashinaga ko'chirilgan.

        `not_found` dan AJRATILADI va bu operator uchun muhim:
        u yerda administrator kompyuterni QO'SHISHI kerak, bu yerda
        esa mavjud kompyuterga qurilmani QAYTA BIRIKTIRISHI. Bitta
        umumiy xabar noto'g'ri harakatga olib borardi.
        """
        other = factories.make_computer(zone=self.zone, mac_address="AA:BB:CC:DD:EE:02")

        result = services.verify_machine(self.device, mac_address="AA:BB:CC:DD:EE:02")

        self.assertEqual(result["status"], services.MACHINE_MISMATCH)
        self.assertEqual(result["computer_code"], other.inventory_code)
        self.assertIn(self.computer.inventory_code, result["message"])
        self.assertIn(other.inventory_code, result["message"])

    def test_same_mac_in_another_zone_is_not_found(self):
        """
        Qidiruv ko'lami — BINO.

        Boshqa binodagi kompyuter bazada bor, lekin uning jadvali,
        kameralari va proktori boshqa. U yerda ochilgan sessiya
        butun hisobotni buzardi.
        """
        other_zone = factories.make_zone()
        factories.make_computer(zone=other_zone, mac_address="AA:BB:CC:DD:EE:03")

        result = services.verify_machine(self.device, mac_address="AA:BB:CC:DD:EE:03")

        self.assertEqual(result["status"], services.MACHINE_NOT_FOUND)

    def test_deleted_computer_does_not_match(self):
        """Hisobdan chiqarilgan kompyuter MAC'ni band qilib qolmaydi."""
        removed = factories.make_computer(zone=self.zone, mac_address="AA:BB:CC:DD:EE:04")
        removed.delete()

        result = services.verify_machine(self.device, mac_address="AA:BB:CC:DD:EE:04")

        self.assertEqual(result["status"], services.MACHINE_NOT_FOUND)

    def test_inactive_computer_is_blocked(self):
        self.computer.is_active = False
        self.computer.save(update_fields=["is_active"])

        result = services.verify_machine(self.device, mac_address="AA:BB:CC:DD:EE:01")

        self.assertEqual(result["status"], services.MACHINE_INACTIVE)

    def test_missing_mac_is_unknown(self):
        """
        Eski client MAC yubormaydi.

        Bu XATO EMAS — natija "noma'lum" bo'ladi va uni to'siqqa
        aylantirish qarori sozlamada (`REQUIRE_MAC_MATCH`).
        """
        result = services.verify_machine(self.device, mac_address="")

        self.assertEqual(result["status"], services.MACHINE_UNKNOWN)

    def test_malformed_mac_is_unknown(self):
        result = services.verify_machine(self.device, mac_address="not-a-mac")

        self.assertEqual(result["status"], services.MACHINE_UNKNOWN)
        self.assertEqual(result["mac_address"], "")

    def test_no_device_at_all(self):
        """
        Qurilmasiz so'rov: bino ham, kompyuter ham noma'lum.

        `REQUIRE_DEVICE_ID=false` bilan (lokal ishlab chiqish) yoki
        `X-Device-ID` yuborilmaganda shu holat yuzaga keladi. MAC
        bo'yicha qidirish bu yerda MA'NOSIZ: qidiruv ko'lami yo'q
        va mos kelgan kompyuter boshqa viloyatda bo'lishi mumkin.
        """
        result = services.verify_machine(None, mac_address="AA:BB:CC:DD:EE:01")

        self.assertEqual(result["status"], services.MACHINE_NO_COMPUTER)

    def test_verdict_does_not_write_anything(self):
        """
        Tekshiruv FAQAT SOLISHTIRADI.

        Client aytgan MAC bilan `Computer.mac_address` ni yangilash
        butun tekshiruvni ma'nosiz qilardi: har qanday mashina
        birinchi handshake'da o'zini "ro'yxatga olingan" holga
        keltirib olardi.
        """
        services.verify_machine(self.device, mac_address="AA:BB:CC:DD:EE:77")

        self.computer.refresh_from_db()
        self.assertEqual(self.computer.mac_address, "AA:BB:CC:DD:EE:01")
        self.assertFalse(
            Computer.objects.filter(mac_address="AA:BB:CC:DD:EE:77").exists()
        )


class VerifyMachineUuidTests(TestCase):
    """
    Asosiy yo'l - Machine UUID. MAC o'zgarsa ham mashina tanilishi,
    UUID'siz eski yozuv esa MAC orqali BIR MARTA bog'lanishi kerak.
    """

    UUID = "4C4C4544-0038-4A10-805A-C7C04F4B3A21"

    def setUp(self):
        self.zone = factories.make_zone()
        self.computer = factories.make_computer(
            zone=self.zone, machine_uuid=self.UUID, mac_address="AA:BB:CC:DD:EE:21"
        )
        self.device = factories.make_device(computer=self.computer)

    def test_uuid_match_passes_even_if_mac_changed(self):
        result = services.verify_machine(
            self.device, machine_uuid=self.UUID.lower(), mac_address="11:22:33:44:55:66"
        )
        self.assertEqual((result["status"], result["basis"]), (services.MACHINE_OK, "uuid"))

    def test_foreign_uuid_is_not_found_even_if_mac_matches(self):
        """UUID berilgan bo'lsa MAC hal qilmaydi - MAC endi identifikator emas."""
        result = services.verify_machine(
            self.device, machine_uuid="4C4C4544-0038-4A10-805A-C7C04F4B3A99",
            mac_address="AA:BB:CC:DD:EE:21",
        )
        self.assertEqual(result["status"], services.MACHINE_NOT_FOUND)
        self.assertIn(self.UUID, result["message"])
        self.computer.refresh_from_db()
        self.assertEqual(self.computer.machine_uuid, self.UUID)

    def test_uuid_of_another_computer_is_mismatch(self):
        other = factories.make_computer(zone=self.zone)
        result = services.verify_machine(self.device, machine_uuid=other.machine_uuid)
        self.assertEqual(result["status"], services.MACHINE_MISMATCH)
        self.assertEqual(result["computer_code"], other.inventory_code)

    def test_legacy_record_is_bound_once_by_matching_mac(self):
        legacy = factories.make_computer(
            zone=self.zone, machine_uuid=None, mac_address="AA:BB:CC:DD:EE:22"
        )
        device = factories.make_device(computer=legacy)
        uuid = "4C4C4544-0038-4A10-805A-C7C04F4B3A22"

        result = services.verify_machine(device, machine_uuid=uuid, mac_address="aa-bb-cc-dd-ee-22")

        self.assertEqual(result["status"], services.MACHINE_OK)
        self.assertTrue(result["bound"])
        legacy.refresh_from_db()
        self.assertEqual(legacy.machine_uuid, uuid)
        # Ikkinchi marta - oddiy moslik, qayta bog'lash emas.
        again = services.verify_machine(device, machine_uuid=uuid, mac_address="")
        self.assertEqual((again["status"], again["bound"]), (services.MACHINE_OK, False))

    def test_legacy_record_is_not_bound_when_mac_differs(self):
        legacy = factories.make_computer(
            zone=self.zone, machine_uuid=None, mac_address="AA:BB:CC:DD:EE:23"
        )
        device = factories.make_device(computer=legacy)

        result = services.verify_machine(
            device, machine_uuid="4C4C4544-0038-4A10-805A-C7C04F4B3A23",
            mac_address="AA:BB:CC:DD:EE:77",
        )

        self.assertEqual(result["status"], services.MACHINE_NOT_FOUND)
        legacy.refresh_from_db()
        self.assertIsNone(legacy.machine_uuid)

    def test_uuid_taken_elsewhere_is_not_bound(self):
        """Bitta UUID ikki yozuvda bo'lolmaydi - band bo'lsa bog'lanmaydi."""
        legacy = factories.make_computer(
            zone=self.zone, machine_uuid=None, mac_address="AA:BB:CC:DD:EE:24"
        )
        device = factories.make_device(computer=legacy)

        result = services.verify_machine(
            device, machine_uuid=self.UUID, mac_address="AA:BB:CC:DD:EE:24"
        )

        self.assertEqual(result["status"], services.MACHINE_MISMATCH)
        legacy.refresh_from_db()
        self.assertIsNone(legacy.machine_uuid)

    def test_resolve_computer_prefers_uuid(self):
        found = services.resolve_computer(
            machine_uuid=self.UUID, mac_address="00:00:00:00:00:01"
        )
        self.assertEqual(found, self.computer)


class FingerprintUpgradeTests(TestCase):
    """Apparat izi MAC formatidan UUID formatiga o'tishi soxta anomaliya bermaydi."""

    def setUp(self):
        self.device = factories.make_device(
            hardware_fingerprint="AA:BB:CC:DD:EE:31|PC-31|Windows|AMD64"
        )

    def test_same_machine_upgrades_silently(self):
        anomalies = services.record_handshake(
            self.device, hardware_fingerprint="muid:4C4C4544-0038-4A10-805A-C7C04F4B3A31",
            reported_mac="aa-bb-cc-dd-ee-31",
        )
        self.assertEqual([a["kind"] for a in anomalies], [])
        self.device.refresh_from_db()
        self.assertEqual(self.device.hardware_fingerprint, "muid:4C4C4544-0038-4A10-805A-C7C04F4B3A31")

    def test_other_machine_is_still_an_anomaly(self):
        anomalies = services.record_handshake(
            self.device, hardware_fingerprint="muid:4C4C4544-0038-4A10-805A-C7C04F4B3A32",
            reported_mac="AA:BB:CC:DD:EE:99",
        )
        self.assertIn("fingerprint_changed", [a["kind"] for a in anomalies])
        self.device.refresh_from_db()
        self.assertTrue(self.device.hardware_fingerprint.startswith("AA:BB"))
