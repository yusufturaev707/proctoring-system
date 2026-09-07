"""
Ruxsat etilgan IP'lar ro'yxati.

Eng muhim savol — **ro'yxat bo'sh bo'lganda nima bo'ladi**. Bu joyda
xato qilish jimgina sodir bo'ladi: administrator yagona yozuvni nofaol
qilsa yoki o'chirsa, "hech kim kira olmaydi" o'rniga "hamma kiraveradi"
bo'lib qolishi mumkin va buni hech kim sezmaydi.

`REQUIRE_ALLOWED_IP` (standart `true`) aynan shuni hal qiladi.
"""

from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.controls import services
from apps.controls.models import AllowedPublicIp
from apps.regions.models import Region, Zone


def with_proctoring(**overrides):
    """`PROCTORING` lug'atining bir qismini almashtiradi."""
    from django.conf import settings

    return override_settings(PROCTORING={**settings.PROCTORING, **overrides})


class AllowlistTestCase(TestCase):
    def setUp(self):
        # Ro'yxat keshlanadi (`IP_CACHE_KEY`) — har testdan oldin
        # tozalanmasa, testlar bir-birining ro'yxatini ko'radi.
        cache.clear()
        self.addCleanup(cache.clear)
        self.region = Region.objects.create(name="Toshkent", dtm_id=1, vm_number=1)
        self.zone = Zone.objects.create(region=self.region, name="1-bino", number=1)
        self.other_zone = Zone.objects.create(region=self.region, name="2-bino", number=2)


class IsIpAllowedTests(AllowlistTestCase):
    def test_listed_ip_is_allowed(self):
        AllowedPublicIp.objects.create(ip_address="203.0.113.10")
        self.assertTrue(services.is_ip_allowed("203.0.113.10"))

    def test_unlisted_ip_is_denied(self):
        AllowedPublicIp.objects.create(ip_address="203.0.113.10")
        self.assertFalse(services.is_ip_allowed("203.0.113.11"))

    def test_inactive_row_is_denied(self):
        """Nofaol yozuv ro'yxatda YO'Q hisoblanadi."""
        AllowedPublicIp.objects.create(ip_address="203.0.113.10", is_active=False)
        AllowedPublicIp.objects.create(ip_address="203.0.113.20")
        self.assertFalse(services.is_ip_allowed("203.0.113.10"))

    def test_zone_bound_ip_rejects_other_zone(self):
        """
        Binoga biriktirilgan IP faqat o'sha binoning mashinalariga.

        Boshqa binoning kompyuteri o'sha manzildan chiqsa - bu
        konfiguratsiya xatosi va u sessiyani noto'g'ri binoga
        yozib qo'yardi.
        """
        AllowedPublicIp.objects.create(ip_address="203.0.113.10", zone=self.zone)
        self.assertTrue(services.is_ip_allowed("203.0.113.10", self.zone.pk))
        self.assertFalse(services.is_ip_allowed("203.0.113.10", self.other_zone.pk))

    def test_global_ip_allows_any_zone(self):
        """`zone=NULL` — barcha binolar uchun."""
        AllowedPublicIp.objects.create(ip_address="203.0.113.10", zone=None)
        self.assertTrue(services.is_ip_allowed("203.0.113.10", self.zone.pk))
        self.assertTrue(services.is_ip_allowed("203.0.113.10", self.other_zone.pk))

    # --- Bo'sh ro'yxat: eng muhim ikki holat -----------------------
    @with_proctoring(REQUIRE_ALLOWED_IP=True)
    def test_empty_list_denies_everyone_by_default(self):
        """
        Bo'sh ro'yxat = "hali hech kimga ruxsat berilmagan".

        Bu XAVFSIZ talqin va standart. Aks holda yagona yozuvni
        o'chirish butun cheklovni jimgina olib tashlardi.
        """
        self.assertFalse(services.is_ip_allowed("203.0.113.10"))

    @with_proctoring(REQUIRE_ALLOWED_IP=False)
    def test_empty_list_allows_everyone_in_soft_mode(self):
        """Yumshoq rejim: bo'sh ro'yxat = tekshiruv o'chirilgan."""
        self.assertTrue(services.is_ip_allowed("203.0.113.10"))

    @with_proctoring(REQUIRE_ALLOWED_IP=False)
    def test_soft_mode_still_enforces_non_empty_list(self):
        """
        Yumshoqlik FAQAT bo'sh ro'yxatga tegishli.

        Ro'yxatda yozuv paydo bo'lishi bilan tekshiruv qat'iy ishlaydi.
        """
        AllowedPublicIp.objects.create(ip_address="203.0.113.10")
        self.assertFalse(services.is_ip_allowed("203.0.113.99"))

    def test_cache_is_invalidated(self):
        self.assertFalse(services.is_ip_allowed("203.0.113.10"))
        AllowedPublicIp.objects.create(ip_address="203.0.113.10")
        # Kesh hali eski holatni ushlab turadi.
        services.invalidate_ip_cache()
        self.assertTrue(services.is_ip_allowed("203.0.113.10"))


class NetworkPreflightTests(AllowlistTestCase):
    """
    Preflight qarori FAQAT client aytgan `public_ip` bo'yicha chiqadi.

    Server ko'rgan manzil (`observed_ip`) tekshiruvda QATNASHMAYDI:
    server bino ichida turganda u faqat LAN manzilni ko'radi. Bu
    qulaylik to'sig'i, himoya emas — haqiqiy tekshiruv har bir client
    so'rovida `check_source_ip` da.
    """

    def test_allows_listed_public_ip(self):
        AllowedPublicIp.objects.create(ip_address="203.0.113.10", zone=self.zone)
        result = services.network_preflight(
            public_ip="203.0.113.10", observed_ip="192.168.1.5"
        )
        self.assertTrue(result["allowed"])
        self.assertFalse(result["allowlist_empty"])
        self.assertEqual(result["zone"], {"id": self.zone.pk, "name": "1-bino"})
        self.assertEqual(result["region"]["name"], "Toshkent")
        # Server ko'rgan manzil qarorga ta'sir qilmaydi, lekin javobda
        # qoladi — administrator farqni ko'rishi uchun.
        self.assertIs(result["matches_observed"], False)

    def test_observed_ip_alone_is_not_enough(self):
        """
        HUJUM/XATO: server ko'rgan manzil ro'yxatda, client aytgani yo'q.

        Qaror `public_ip` bo'yicha chiqadi, ya'ni bu RAD etiladi.
        """
        AllowedPublicIp.objects.create(ip_address="192.168.1.5")
        result = services.network_preflight(
            public_ip="203.0.113.99", observed_ip="192.168.1.5"
        )
        self.assertFalse(result["allowed"])

    def test_missing_public_ip_is_denied(self):
        AllowedPublicIp.objects.create(ip_address="203.0.113.10")
        result = services.network_preflight(public_ip="", observed_ip="203.0.113.10")
        self.assertFalse(result["allowed"])
        self.assertIsNone(result["matches_observed"])

    @with_proctoring(REQUIRE_ALLOWED_IP=True)
    def test_empty_list_reports_reason_separately(self):
        """
        "Sizning manzilingiz ro'yxatda yo'q" va "ro'yxat umuman bo'sh"
        BOSHQA-BOSHQA holatlar.

        Ikkinchisi administrator xatosi; uni operatorga "IP'ingiz
        noto'g'ri" deb ko'rsatish nosozlikni soatlab qidirishga olib
        keladi.
        """
        result = services.network_preflight(public_ip="203.0.113.10")
        self.assertFalse(result["allowed"])
        self.assertTrue(result["allowlist_empty"])

    def test_zone_is_not_reported_for_deleted_zone(self):
        """
        Yumshoq o'chirilgan bino ko'rsatilmaydi.

        Operator "qaysi bino sifatida tanildim?" degan savolga
        hisobdan chiqarilgan bino nomini olmasligi kerak.
        """
        AllowedPublicIp.objects.create(ip_address="203.0.113.10", zone=self.zone)
        self.zone.delete()  # SoftDeleteModel — `deleted_at` qo'yiladi
        result = services.network_preflight(public_ip="203.0.113.10")
        self.assertTrue(result["allowed"])
        self.assertIsNone(result["zone"])

    def test_matches_observed_true(self):
        AllowedPublicIp.objects.create(ip_address="203.0.113.10")
        result = services.network_preflight(
            public_ip="203.0.113.10", observed_ip="203.0.113.10"
        )
        self.assertIs(result["matches_observed"], True)
