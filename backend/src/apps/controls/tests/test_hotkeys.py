"""
Tezkor tugma kodi: server client TANIYDIGAN kodnigina saqlaydi.

Client tanimagan kodni bloklamaydi (faqat log) — panelda "bloklangan"
ko'rinib, imtihonda ochiq qolardi. Lug'at client'dan nusxa, shuning
uchun nusxa client manbasi bilan solishtiriladi (`ClientParityTests`).
"""

import ast
from pathlib import Path
from unittest import skipUnless

from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.controls import hotkeys
from apps.controls.models import HotKeyboardKey, RdpObject
from apps.proctoring.tests import factories

CLIENT_LOCKDOWN = Path(__file__).resolve().parents[5] / "client" / "services" / "lockdown.py"


class CleanHotkeyTests(SimpleTestCase):
    def test_canonical_form(self):
        self.assertEqual(hotkeys.clean_hotkey(" Ctrl + Shift+I "), "ctrl+shift+i")
        self.assertEqual(hotkeys.clean_hotkey("PrintScreen"), "print screen")
        self.assertEqual(hotkeys.clean_hotkey("alt+PgUp"), "alt+page up")
        self.assertEqual(hotkeys.clean_hotkey("left alt+num 5"), "left alt+num 5")
        self.assertEqual(hotkeys.clean_hotkey("win"), "win")

    def test_rejects_what_client_ignores(self):
        for code in ("pageup", "leftalt+tab", "ctrl+foo", "ctrl+a+b", "alt+alt", "", "Ctrl+Q"):
            with self.subTest(code=code), self.assertRaises(ValueError):
                hotkeys.clean_hotkey(code)


@skipUnless(CLIENT_LOCKDOWN.exists(), "client manbasi yo'q")
class ClientParityTests(SimpleTestCase):
    """Server lug'ati client `lockdown.py` dagidan farq qilmasin."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.literals = {}
        tree = ast.parse(CLIENT_LOCKDOWN.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                try:
                    cls.literals[node.targets[0].id] = ast.literal_eval(node.value)
                except ValueError:
                    continue

    def test_aliases(self):
        self.assertEqual(self.literals["_KEY_ALIASES"], hotkeys.KEY_ALIASES)

    def test_modifiers(self):
        self.assertEqual(set(self.literals["_MODIFIER_VKS"]), set(hotkeys.MODIFIERS))

    def test_named_keys(self):
        named = set(self.literals["_NAMED_VKS"])
        named |= {f"num {i}" for i in range(10)} | {f"f{i}" for i in range(1, 25)}
        self.assertEqual(named, set(hotkeys.NAMED_KEYS))


class HotkeyApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(
            factories.make_user(permissions=["controls.manage", "controls.view"])
        )
        self.url = reverse("hotkey-list")

    def test_saves_canonical_code(self):
        response = self.client.post(self.url, {"name": "Page Up", "code": "Alt + PgUp"}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(HotKeyboardKey.objects.get().code, "alt+page up")

    def test_unknown_key_rejected(self):
        response = self.client.post(self.url, {"name": "X", "code": "alt+pageup"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(HotKeyboardKey.objects.exists())

    def test_alias_duplicate_rejected(self):
        HotKeyboardKey.objects.create(name="PrtSc", code="print screen")
        response = self.client.post(self.url, {"name": "PrtSc 2", "code": "printscreen"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_edit_keeps_own_code(self):
        key = HotKeyboardKey.objects.create(name="Alt+Tab", code="alt+tab")
        response = self.client.patch(
            reverse("hotkey-detail", args=[key.pk]),
            {"name": "Oyna almashtirish", "code": "Alt+Tab"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)

    def test_lists_profiles(self):
        key = HotKeyboardKey.objects.create(name="Alt+Tab", code="alt+tab")
        default = factories.make_setting(is_active=True, name="Standart")
        default.hotkeys.add(key)
        removed = factories.make_setting(name="Eski")
        removed.hotkeys.add(key)
        removed.delete()  # soft — ro'yxatda ko'rinmasligi kerak
        HotKeyboardKey.objects.create(name="Win", code="win")

        rows = {row["code"]: row for row in self.client.get(self.url).json()["data"]["results"]}
        self.assertEqual(
            rows["alt+tab"]["profiles"], [{"id": default.pk, "name": "Standart", "is_default": True}]
        )
        self.assertEqual(rows["win"]["profiles"], [])


class RdpObjectProfilesTests(TestCase):
    def test_lists_profiles(self):
        client = APIClient()
        client.force_authenticate(factories.make_user(permissions=["controls.view"]))
        anydesk = RdpObject.objects.create(name="AnyDesk", code="anydesk")
        factories.make_setting(name="Matematika").rdp_objects.add(anydesk)

        rows = client.get(reverse("rdp-object-list")).json()["data"]["results"]
        self.assertEqual([item["name"] for item in rows[0]["profiles"]], ["Matematika"])


class RdpObjectSignsTests(TestCase):
    """Belgisiz qoida client'da hech narsani tutmaydi — saqlanmaydi."""

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(
            factories.make_user(permissions=["controls.manage", "controls.view"])
        )

    def test_rule_without_signs_rejected(self):
        response = self.client.post(
            reverse("rdp-object-list"), {"name": "Bo'sh", "code": "empty"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("process_names", response.json()["error"]["details"])

    def test_patch_cannot_clear_last_sign(self):
        rule = RdpObject.objects.create(name="AnyDesk", code="anydesk", ports=[7070])
        url = reverse("rdp-object-detail", args=[rule.pk])
        self.assertEqual(self.client.patch(url, {"ports": []}, format="json").status_code, 400)
        response = self.client.patch(url, {"name": "AnyDesk 8"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
