"""
Sozlama profili API'si: RDP dasturlari va tezkor tugmalarni TANLASH.

Bu ikkala ro'yxat panelda tanlanadi (`Settings.jsx`), lekin ular
oddiy maydon emas — M2M. Shuning uchun ikkita narsa himoyalanadi:

  1. PATCH ro'yxatni ALMASHTIRADI (qo'shmaydi va yo'qotmaydi);
  2. tanlov client konfiguratsiyasiga aynan shu tarzda yetadi —
     tugmalar `code` bo'yicha, RDP esa JARAYON NOMLARI bo'yicha.

Ikkinchisi muhim: panel `RdpObject` nomini ko'rsatadi ("AnyDesk"),
client esa jarayon nomlarini qidiradi (`AnyDesk.exe`). Bu ikki
ko'rinish orasidagi bog'lanish `get_client_config` da va u
buzilganda panel to'g'ri ko'rinib, client hech nima qidirmasdi.
"""

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.controls import services
from apps.controls.models import CocoObject, CocoObjectGroup, HotKeyboardKey, RdpObject
from apps.proctoring.tests import factories


class SettingReferenceSelectionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient()
        self.staff = factories.make_user(
            permissions=["controls.manage", "controls.view"], is_staff=True
        )
        self.client.force_authenticate(self.staff)

        self.setting = factories.make_setting(is_active=True)
        self.anydesk = RdpObject.objects.create(
            name="AnyDesk", code="anydesk", process_names=["AnyDesk.exe"]
        )
        self.teamviewer = RdpObject.objects.create(
            name="TeamViewer", code="teamviewer", process_names=["TeamViewer.exe"]
        )
        self.alt_tab = HotKeyboardKey.objects.create(name="Alt+Tab", code="alt+tab")
        self.win = HotKeyboardKey.objects.create(name="Win", code="win")
        self.url = reverse("setting-detail", args=[self.setting.pk])

    def test_patch_replaces_the_selection(self):
        response = self.client.patch(
            self.url,
            {
                "rdp_objects": [self.anydesk.pk, self.teamviewer.pk],
                "hotkeys": [self.alt_tab.pk],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)

        self.setting.refresh_from_db()
        self.assertEqual(self.setting.rdp_objects.count(), 2)
        self.assertEqual(
            list(self.setting.hotkeys.values_list("code", flat=True)), ["alt+tab"]
        )

        # Ikkinchi PATCH — ALMASHTIRISH, qo'shish emas.
        self.client.patch(self.url, {"hotkeys": [self.win.pk]}, format="json")
        self.setting.refresh_from_db()
        self.assertEqual(
            list(self.setting.hotkeys.values_list("code", flat=True)), ["win"]
        )

    def test_selection_reaches_the_client_config(self):
        self.client.patch(
            self.url,
            {
                "rdp_objects": [self.anydesk.pk],
                "hotkeys": [self.alt_tab.pk, self.win.pk],
                "is_enable_rdp_detect": True,
            },
            format="json",
        )
        cache.clear()

        config = services.get_client_config()
        # Client JARAYON nomlarini oladi, panel esa dastur nomini
        # ko'rsatadi — bog'lanish shu yerda.
        self.assertEqual(config["rdp"]["processes"], ["AnyDesk.exe"])
        self.assertEqual(sorted(config["hotkeys"]), ["alt+tab", "win"])

    def test_inactive_entries_are_not_sent_to_the_client(self):
        """
        Nofaol yozuv tanlangan bo'lsa ham clientga BORMAYDI.

        Panel uni ro'yxatda "nofaol" deb ko'rsatadi — yashirish
        "tanladim, lekin ishlamayapti" holatini tushuntirib
        bo'lmaydigan qilardi.
        """
        HotKeyboardKey.objects.filter(pk=self.win.pk).update(is_active=False)
        self.client.patch(
            self.url, {"hotkeys": [self.alt_tab.pk, self.win.pk]}, format="json"
        )
        cache.clear()

        config = services.get_client_config()
        self.assertEqual(config["hotkeys"], ["alt+tab"])

    def test_detect_classes_selection(self):
        """
        Kuzatiladigan obyektlar ham panelda tanlanadi.

        Client ularni `detection.classes` sifatida oladi va YOLO
        FAQAT shularni qidiradi — bo'sh ro'yxat "model ishlaydi,
        lekin hech nima topmaydi" degani.
        """
        # `CocoObject.code` — COCO klass INDEKSI (butun son), nom emas:
        # 67 = cell phone, 73 = book.
        group = CocoObjectGroup.objects.create(
            name="Aloqa vositalari", code="communication"
        )
        phone = CocoObject.objects.create(
            name="Telefon", code=67, group=group, severity=3
        )
        book = CocoObject.objects.create(name="Kitob", code=73, group=group)

        response = self.client.patch(
            self.url,
            {"detect_classes": [phone.pk, book.pk], "is_enable_detect": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        cache.clear()

        config = services.get_client_config()
        self.assertEqual(
            sorted(item["code"] for item in config["detection"]["classes"]), [67, 73]
        )
        self.assertEqual(
            {item["name"] for item in config["detection"]["classes"]},
            {"Telefon", "Kitob"},
        )

    def test_detail_block_is_read_only(self):
        """
        `*_detail` faqat O'QISH uchun: panel uni yubormaydi
        (`stripReadOnly`), yuborilsa ham e'tiborsiz qoladi.
        """
        response = self.client.patch(
            self.url,
            {"hotkeys": [self.alt_tab.pk], "hotkeys_detail": [{"id": 999, "name": "X"}]},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            [item["code"] for item in response.json()["data"]["hotkeys_detail"]],
            ["alt+tab"],
        )
