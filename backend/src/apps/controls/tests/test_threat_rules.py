"""
`RdpObject` -> client konfiguratsiyasi.

Eng muhim tekshiruv - `rules` VA `processes` ning BIRGA ketishi.
Ikkalasi bir xil ma'lumotni ikki shaklda beradi va ularning har biri
boshqa o'quvchi uchun:

    processes -> ESKI client. U faqat fayl nomini biladi va qayta
                 nomlangan binarni ko'rmaydi.
    rules     -> YANGI client. Imzo, `OriginalFilename`, xizmat nomi
                 va port bo'yicha qidiradi, ya'ni `AnyDesk.exe` ni
                 qayta nomlash yordam bermaydi.

Birinchisini olib tashlash yangilanmagan mashinalarda aniqlashni
butunlay o'chirardi, ikkinchisini qo'shmaslik esa butun himoyani
fayl nomi darajasida qoldirardi.
"""

from django.core.cache import cache
from django.test import TestCase

from apps.controls import services
from apps.controls.models import RdpObject
from apps.proctoring.tests import factories


class RdpConfigTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def _setting_with(self, **kwargs):
        obj = RdpObject.objects.create(**kwargs)
        setting = factories.make_setting(is_active=True)
        setting.rdp_objects.set([obj])
        return setting, obj

    def test_rules_carry_rename_proof_signals(self):
        """Qayta nomlashga chidamli belgilar client'ga YETADI."""
        self._setting_with(
            name="AnyDesk",
            code="anydesk",
            category=RdpObject.Category.REMOTE,
            process_names=["AnyDesk.exe"],
            publishers=["AnyDesk Software GmbH"],
            original_filenames=["AnyDesk.exe"],
            service_names=["AnyDesk"],
            ports=[7070],
        )
        rdp = services.get_client_config()["rdp"]

        self.assertEqual(len(rdp["rules"]), 1)
        rule = rdp["rules"][0]
        self.assertEqual(rule["code"], "anydesk")
        self.assertEqual(rule["publishers"], ["AnyDesk Software GmbH"])
        self.assertEqual(rule["originals"], ["AnyDesk.exe"])
        self.assertEqual(rule["services"], ["AnyDesk"])
        self.assertEqual(rule["ports"], [7070])
        # Eski client uchun nomlar AVVALGIDEK alohida ro'yxatda.
        self.assertEqual(rdp["processes"], ["AnyDesk.exe"])

    def test_category_drives_event_type(self):
        """Toifa hodisa turini belgilaydi — `vm` uchun `vm_detected`."""
        self._setting_with(
            name="VirtualBox",
            code="virtualbox",
            category=RdpObject.Category.VM,
            process_names=["VBoxSVC.exe"],
        )
        rule = services.get_client_config()["rdp"]["rules"][0]
        self.assertEqual(rule["category"], "vm")

    def test_blocking_is_opt_in(self):
        """
        `is_blocking` STANDART `False`.

        Panelga ixtiyoriy qiymat yozilishi mumkin - shu jumladan
        muassasaning o'z dasturiga to'g'ri keladigani. Bunday yozuv
        butun imtihonni bloklab qo'ymasligi kerak.
        """
        _setting, obj = self._setting_with(
            name="Ichki agent", code="internal", process_names=["agent.exe"]
        )
        self.assertFalse(obj.is_blocking)
        self.assertFalse(services.get_client_config()["rdp"]["rules"][0]["blocking"])

        obj.is_blocking = True
        obj.save(update_fields=["is_blocking"])
        cache.clear()
        self.assertTrue(services.get_client_config()["rdp"]["rules"][0]["blocking"])

    def test_inactive_object_is_excluded(self):
        """Nofaol yozuv ikkala ro'yxatdan ham chiqib ketadi."""
        _setting, obj = self._setting_with(
            name="AnyDesk", code="anydesk", process_names=["AnyDesk.exe"]
        )
        obj.is_active = False
        obj.save(update_fields=["is_active"])
        cache.clear()

        rdp = services.get_client_config()["rdp"]
        self.assertEqual(rdp["rules"], [])
        self.assertEqual(rdp["processes"], [])

    def test_defaults_keep_detection_enabled(self):
        """
        Sozlama umuman yo'q bo'lsa aniqlash YOQILGAN qoladi.

        Ro'yxatning bo'shligi "himoya yo'q" degani emas: client'da
        ichki katalog bor va u serverdan mustaqil ishlaydi.
        """
        rdp = services.get_client_config()["rdp"]
        self.assertTrue(rdp["enabled"])
        self.assertEqual(rdp["rules"], [])
        self.assertEqual(rdp["processes"], [])
