"""
Client'dan chiqish paroli — viloyat bo'yicha.

Ikki xususiyat tekshiriladi:
  * parol HASH ko'rinishida saqlanadi va API uni hech qachon
    qaytarmaydi;
  * "parol noto'g'ri" va "parol sozlanmagan" holatlari AJRATILADI —
    ikkinchisida kiosk rejimidagi mashina qulflanib qolmasligi kerak.
"""

from django.test import TestCase

from apps.controls import services
from apps.controls.models import ClientExitPassword
from apps.regions.models import Region


class ExitPasswordModelTests(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Toshkent", dtm_id=1, vm_number=1)

    def test_password_is_stored_hashed(self):
        row = ClientExitPassword(region=self.region)
        row.set_password("maxfiy-parol")
        row.save()

        self.assertNotEqual(row.password, "maxfiy-parol")
        self.assertNotIn("maxfiy-parol", row.password)
        # Django hash formati: `algoritm$...`
        self.assertIn("$", row.password)

    def test_check_password(self):
        row = ClientExitPassword(region=self.region)
        row.set_password("maxfiy-parol")
        row.save()

        self.assertTrue(row.check_password("maxfiy-parol"))
        self.assertFalse(row.check_password("boshqa"))

    def test_blank_password_never_matches(self):
        """Bo'sh parol bilan chiqib bo'lmaydi."""
        row = ClientExitPassword(region=self.region)
        row.set_password("parol")
        row.save()
        self.assertFalse(row.check_password(""))
        self.assertFalse(row.check_password(None))


class VerifyExitPasswordTests(TestCase):
    def setUp(self):
        self.toshkent = Region.objects.create(name="Toshkent", dtm_id=1, vm_number=1)
        self.samarqand = Region.objects.create(name="Samarqand", dtm_id=2, vm_number=2)
        self._create(self.toshkent, "toshkent-paroli")
        self._create(self.samarqand, "samarqand-paroli")

    @staticmethod
    def _create(region, raw, is_active=True):
        row = ClientExitPassword(region=region, is_active=is_active)
        row.set_password(raw)
        row.save()
        return row

    def test_matches_within_region(self):
        row = services.verify_exit_password(
            "toshkent-paroli", region_id=self.toshkent.pk
        )
        self.assertIsNotNone(row)
        self.assertEqual(row.region_id, self.toshkent.pk)

    def test_other_region_password_is_rejected_when_region_known(self):
        """
        Viloyat ma'lum bo'lsa - FAQAT o'sha viloyatning paroli.

        Aynan shu narsa parollarni viloyat bo'yicha ajratishning
        ma'nosi: bir hududdan sizib chiqqan parol boshqasini ochmaydi.
        """
        self.assertIsNone(
            services.verify_exit_password(
                "samarqand-paroli", region_id=self.toshkent.pk
            )
        )

    def test_unknown_region_falls_back_to_any_password(self):
        """
        Viloyat aniqlanmaganda tekshiruv "biror viloyatning paroli"
        darajasiga tushadi.

        Bu ONGLI kelishuv: muqobili mashinani umuman yopib
        bo'lmaydigan holatda qoldirish (viloyat aynan eng kerakli
        paytda - preflight rad etgan ekranda - noma'lum bo'ladi).
        """
        row = services.verify_exit_password("samarqand-paroli", region_id=None)
        self.assertIsNotNone(row)
        self.assertEqual(row.region_id, self.samarqand.pk)

    def test_inactive_password_is_rejected(self):
        row = ClientExitPassword.objects.get(region=self.toshkent)
        row.is_active = False
        row.save(update_fields=["is_active"])
        self.assertIsNone(
            services.verify_exit_password("toshkent-paroli", region_id=self.toshkent.pk)
        )

    def test_wrong_password_returns_none(self):
        self.assertIsNone(
            services.verify_exit_password("xato", region_id=self.toshkent.pk)
        )

    def test_empty_password_returns_none_without_db_hit(self):
        self.assertIsNone(services.verify_exit_password("", region_id=None))

    def test_checks_every_candidate(self):
        """
        Birinchi moslikda TO'XTAMAYDI.

        Erta `return` javob vaqti orqali "nechanchi viloyatning paroli"
        ekanini oshkor qilardi. Bu yerda kuzatiladigan xulq —
        birinchi viloyatning paroli ham, oxirgisiniki ham topilishi.
        """
        for raw, region in (
            ("toshkent-paroli", self.toshkent),
            ("samarqand-paroli", self.samarqand),
        ):
            with self.subTest(region=region.name):
                row = services.verify_exit_password(raw, region_id=None)
                self.assertEqual(row.region_id, region.pk)


class HasExitPasswordTests(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Toshkent", dtm_id=1, vm_number=1)

    def test_false_when_not_configured(self):
        """
        Sozlanmagan holat "noto'g'ri parol" DAN farq qiladi.

        Client bu javobni tasdiqlash dialogiga aylantiradi: sozlanmagan
        tizim mashinani qulflab qo'ymasligi kerak.
        """
        self.assertFalse(services.has_exit_password(region_id=self.region.pk))

    def test_true_when_configured(self):
        row = ClientExitPassword(region=self.region)
        row.set_password("x")
        row.save()
        self.assertTrue(services.has_exit_password(region_id=self.region.pk))

    def test_inactive_does_not_count(self):
        row = ClientExitPassword(region=self.region, is_active=False)
        row.set_password("x")
        row.save()
        self.assertFalse(services.has_exit_password(region_id=self.region.pk))
