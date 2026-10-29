from django.test import SimpleTestCase

from apps.bba import identity
from apps.bba.tests.fakes import SNAPSHOT


class IdentityTests(SimpleTestCase):
    def test_placeholders_are_not_ids(self):
        for value in ("System Serial Number", "To be filled by O.E.M.", "000000000000",
                      "FFFF-FFFF", " none ", "{00000000-0000-0000-0000-000000000000}", ""):
            with self.subTest(value=value):
                self.assertEqual(identity.clean_id(value), "")
        self.assertEqual(identity.clean_id(" 250861367400312 "), "250861367400312")

    def test_mac_forms_are_canonical(self):
        for value in ("C4-62-37-01-DE-1A", "c4:62:37:01:de:1a", "C4623701DE1A"):
            with self.subTest(value=value):
                self.assertEqual(identity.canonical_mac(value), "C4:62:37:01:DE:1A")
        self.assertEqual(identity.canonical_mac("00-00-00-00-00-00"), "")
        self.assertEqual(identity.canonical_mac("C4-62-37"), "")

    def test_extract_from_console_snapshot(self):
        ids = identity.extract(SNAPSHOT)
        # Bizning kanonik shakl: katta harf (handshake bilan bir xil).
        self.assertEqual(ids["system_uuid"], "124023EC-FFF9-9177-3E7D-30C5991853A1")
        # Faqat JISMONIY adapterlar — WSL'ning virtual adapteri kirmaydi.
        self.assertEqual(ids["macs"], ["C4:62:37:01:DE:1A", "30:C5:99:18:53:A1"])
        # Client yuboradigan MAC — shlyuzli faol adapter.
        self.assertEqual(ids["primary_mac"], "30:C5:99:18:53:A1")
        self.assertEqual(ids["baseboard_serial"], "250861367400312")
        self.assertTrue(ids["tpm_ek_hash"].startswith("8FCBAF1F"))

    def test_ip_for_mac(self):
        self.assertEqual(identity.ip_for_mac(SNAPSHOT, "30:c5:99:18:53:a1"), "192.168.0.57")
        self.assertEqual(identity.ip_for_mac(SNAPSHOT, "C4-62-37-01-DE-1A"), "")  # adapter NetworkConfig'da yo'q
        apipa = {"NetworkConfig": [{"mac": "30-C5-99-18-53-A1", "addrs": ["169.254.3.4/16"]}]}
        self.assertEqual(identity.ip_for_mac(apipa, "30-C5-99-18-53-A1"), "")
        self.assertEqual(identity.extract(SNAPSHOT)["primary_ip"], "192.168.0.57")

    def test_old_agent_without_ids_uses_network_config(self):
        snapshot = {key: value for key, value in SNAPSHOT.items() if key != "Hardware"}
        ids = identity.extract(snapshot)
        self.assertEqual(ids["system_uuid"], "")
        self.assertEqual(ids["macs"], ["30:C5:99:18:53:A1", "00:15:5D:01:02:03"])

    def test_empty_snapshot(self):
        self.assertEqual(identity.extract(None)["macs"], [])
