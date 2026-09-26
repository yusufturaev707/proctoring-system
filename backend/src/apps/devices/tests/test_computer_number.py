"""
Kompyuter RAQAMI — xonadagi tartib raqami.

`inventory_code` dan boshqa savolga javob beradi: kod
buxgalteriya uchun va mashina almashtirilganda o'zgaradi, raqam
esa XONADAGI O'RIN uchun va o'sha joyda qoladi. Operator va
talabgor aynan raqam bilan ishlaydi ("12-kompyuterga o'ting").
"""

from django.db.utils import IntegrityError
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.devices.models import Computer
from apps.proctoring.tests import factories
from apps.proctoring.tests.test_client_api import bearer


class ComputerNumberModelTests(TestCase):
    def setUp(self):
        self.zone = factories.make_zone()

    def test_number_is_optional(self):
        """
        Raqamsiz mashina QABUL QILINADI.

        Hamma markazda ham mashinalar raqamlanmagan va majburiy
        qilish mavjud yozuvlarni migratsiyada to'ldirishga majbur
        qilardi — to'g'ri javobni esa faqat o'sha markaz biladi.
        """
        computer = factories.make_computer(zone=self.zone, number=None)
        self.assertIsNone(computer.number)
        # Nom raqamsiz ham ma'noli bo'lishi kerak: "№None" yozuvi
        # hech narsani anglatmasdi.
        self.assertEqual(computer.label, computer.inventory_code)

    def test_label_puts_number_first(self):
        computer = factories.make_computer(zone=self.zone, number=12)
        self.assertTrue(computer.label.startswith("№12 · "))

    def test_number_unique_within_zone(self):
        factories.make_computer(zone=self.zone, number=12)
        with self.assertRaises(IntegrityError):
            factories.make_computer(zone=self.zone, number=12)

    def test_same_number_allowed_in_other_zone(self):
        """
        "12-kompyuter" HAR BINODA bor va bu normal holat.

        Raqamni tizim bo'ylab unikal qilish ikkinchi binoni
        13-raqamdan boshlashga majbur qilardi.
        """
        other = factories.make_zone()
        factories.make_computer(zone=self.zone, number=12)
        computer = factories.make_computer(zone=other, number=12)
        self.assertEqual(computer.number, 12)

    def test_deleted_computer_frees_the_number(self):
        """
        Hisobdan chiqarilgan mashina raqamni band qilib qolmaydi.

        Eski mashina o'rniga yangisini o'sha raqam bilan qo'yish
        odatiy hol — stol o'z joyida qoladi.
        """
        first = factories.make_computer(zone=self.zone, number=12)
        first.delete()
        second = factories.make_computer(zone=self.zone, number=12)
        self.assertEqual(Computer.objects.alive().filter(number=12).count(), 1)
        self.assertNotEqual(first.pk, second.pk)


class ComputerNumberApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.zone = factories.make_zone()
        self.staff = factories.make_user(permissions=["devices.manage", "devices.view"])
        self.auth = bearer(self.staff)

    def test_create_with_number(self):
        response = self.client.post(
            reverse("computer-list"),
            {
                "zone": self.zone.pk,
                "number": 7,
                "inventory_code": "PC-TEST-7",
                "machine_uuid": "4C4C4544-0038-4A10-805A-C7C04F4B3A07",
                "ip_address": "192.168.55.7",
                "mac_address": "AA:BB:CC:11:22:33",
            },
            format="json",
            HTTP_AUTHORIZATION=self.auth,
        )
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()["data"]
        self.assertEqual(data["number"], 7)
        self.assertEqual(data["label"], "№7 · PC-TEST-7")

    def test_rejects_zero(self):
        """
        `0` QABUL QILINMAYDI: "0-kompyuter" degan o'rin yo'q.

        Bo'sh maydon o'rniga tushgan nol jimgina yolg'on raqam
        yaratardi va ro'yxatda birinchi bo'lib turardi.
        """
        response = self.client.post(
            reverse("computer-list"),
            {
                "zone": self.zone.pk,
                "number": 0,
                "inventory_code": "PC-TEST-0",
                "machine_uuid": "4C4C4544-0038-4A10-805A-C7C04F4B3A08",
                "ip_address": "192.168.55.8",
                "mac_address": "AA:BB:CC:11:22:34",
            },
            format="json",
            HTTP_AUTHORIZATION=self.auth,
        )
        self.assertEqual(response.status_code, 400)

    def test_duplicate_number_gives_readable_error(self):
        factories.make_computer(zone=self.zone, number=9)
        response = self.client.post(
            reverse("computer-list"),
            {
                "zone": self.zone.pk,
                "number": 9,
                "inventory_code": "PC-TEST-9",
                "machine_uuid": "4C4C4544-0038-4A10-805A-C7C04F4B3A09",
                "ip_address": "192.168.55.9",
                "mac_address": "AA:BB:CC:11:22:35",
            },
            format="json",
            HTTP_AUTHORIZATION=self.auth,
        )
        # `409 Conflict` (`400` emas): bu DB cheklovi buzilgani va
        # loyiha uni alohida kod bilan qaytaradi - serializer
        # tekshiruvidan (400) farqlash uchun.
        self.assertEqual(response.status_code, 409)
        # Xato matni CHEKLOV NOMIDAN emas, odam tilida
        # (`common/exceptions.py` dagi lug'at).
        self.assertIn("raqamli kompyuter", response.content.decode())


class ComputerMachineUuidApiTests(TestCase):
    """Panel formasi: UUID asosiy, kanonik shaklda, unikal; MAC ixtiyoriy."""

    def setUp(self):
        self.client = APIClient()
        self.zone = factories.make_zone()
        self.user = factories.make_user(permissions=["devices.view", "devices.manage"])
        self.auth = bearer(self.user)
        self.seq = 0

    def create(self, **payload):
        self.seq += 1
        return self.client.post(
            reverse("computer-list"),
            {"zone": self.zone.pk, "number": 100 + self.seq,
             "inventory_code": "PC-UUID-{}".format(self.seq), **payload},
            format="json",
            HTTP_AUTHORIZATION=self.auth,
        )

    def test_uuid_required_and_canonical_mac_optional(self):
        self.assertEqual(self.create().status_code, 400)
        response = self.create(machine_uuid="{4c4c4544-0038-4a10-805a-c7c04f4b3a11}")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["data"]["machine_uuid"], "4C4C4544-0038-4A10-805A-C7C04F4B3A11")
        self.assertEqual(response.json()["data"]["mac_address"], "")

    def test_duplicate_and_placeholder_rejected(self):
        factories.make_computer(zone=self.zone, machine_uuid="4C4C4544-0038-4A10-805A-C7C04F4B3A12")
        duplicate = self.create(machine_uuid="4c4c4544-0038-4a10-805a-c7c04f4b3a12")
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("machine_uuid", duplicate.json()["error"]["details"])
        placeholder = self.create(machine_uuid="03000200-0400-0500-0006-000700080009")
        self.assertEqual(placeholder.status_code, 400)

    def test_two_computers_without_mac_do_not_collide(self):
        self.assertEqual(self.create(machine_uuid="4C4C4544-0038-4A10-805A-C7C04F4B3A13").status_code, 201)
        second = self.client.post(
            reverse("computer-list"),
            {"zone": self.zone.pk, "number": 150, "inventory_code": "PC-UUID-B",
             "machine_uuid": "4C4C4544-0038-4A10-805A-C7C04F4B3A14", "mac_address": ""},
            format="json",
            HTTP_AUTHORIZATION=self.auth,
        )
        self.assertEqual(second.status_code, 201, second.content)

    def test_legacy_computer_can_be_edited_without_uuid(self):
        legacy = factories.make_computer(zone=self.zone, machine_uuid=None)
        response = self.client.patch(
            reverse("computer-detail", args=[legacy.pk]), {"number": 55},
            format="json", HTTP_AUTHORIZATION=self.auth,
        )
        self.assertEqual(response.status_code, 200, response.content)
