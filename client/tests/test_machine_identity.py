"""
Mashina identifikatori serverga qanday ketadi.

Qo'riqlanadigan shartnoma (server: `devices.services.verify_machine`,
`exams.bookings.resolve_candidate_seat`):

  1. handshake va JSHSHIR tekshiruvida `machine_uuid` HAR DOIM bor -
     usiz server eski MAC qoidasiga tushadi;
  2. apparat izi `muid:<UUID>|mac:<MAC>` - prefiks server bilan
     kelishilgan (`FINGERPRINT_UUID_PREFIX`); UUID bir partiyada
     takrorlanadi, shuning uchun iz (UUID, MAC) juftligi.
"""

import unittest
from unittest import mock

from services import repositories
from services import system_info

UUID = "4C4C4544-0038-4A10-805A-C7C04F4B3A01"
MAC = "2C:F0:5D:77:BB:EB"


class _FakeApi:
    def __init__(self):
        self.calls = []

    def post(self, path, json_body=None, **kwargs):
        self.calls.append((path, json_body))
        return {}


class MachineIdentityPayloadTests(unittest.TestCase):
    def setUp(self):
        for name, value in (
            ("machine_uuid", UUID), ("mac_address", MAC), ("public_ip", ""), ("info_pc", {}),
        ):
            patcher = mock.patch.object(system_info, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.api = _FakeApi()
        self.repo = repositories.ProctoringRepository(api=self.api)

    def test_fingerprint_is_uuid_and_mac_pair(self):
        self.assertEqual(system_info.hardware_fingerprint(), "muid:{}|mac:{}".format(UUID, MAC))

    def test_fingerprint_mac_is_canonical(self):
        """Server bilan AYNAN bir xil satr: katta harf, ikki nuqta."""
        self.assertEqual(
            system_info.hardware_fingerprint("2c-f0-5d-77-bb-eb"),
            "muid:{}|mac:{}".format(UUID, MAC),
        )

    def test_fingerprint_without_mac_keeps_legacy_shape(self):
        self.assertEqual(system_info.hardware_fingerprint(""), "muid:" + UUID)

    def test_same_uuid_different_mac_gives_different_fingerprints(self):
        """Bir partiyadagi ikki plata - ikki BOSHQA iz."""
        self.assertNotEqual(
            system_info.hardware_fingerprint("2C:F0:5D:77:BB:EB"),
            system_info.hardware_fingerprint("2C:F0:5D:77:BB:EC"),
        )

    def test_handshake_always_sends_uuid(self):
        other_mac = "00:E0:4C:68:01:02"
        self.repo.handshake(app_version="1.0", machine={"mac": other_mac, "ip": "10.0.0.5"})
        _path, body = self.api.calls[-1]
        self.assertEqual(body["machine_uuid"], UUID)
        self.assertEqual(body["mac_address"], other_mac)
        # Iz so'rovdagi MAC bilan bitta adapterdan.
        self.assertEqual(body["hardware_fingerprint"], "muid:{}|mac:{}".format(UUID, other_mac))

    def test_register_fingerprint_uses_the_sent_mac(self):
        body = system_info.snapshot()
        self.assertEqual(body["mac_address"], MAC)
        self.assertEqual(body["hardware_fingerprint"], "muid:{}|mac:{}".format(UUID, MAC))

    def test_handshake_prefers_measured_identity(self):
        other = "4C4C4544-0038-4A10-805A-C7C04F4B3A02"
        self.repo.handshake(app_version="1.0", machine={"machine_uuid": other})
        self.assertEqual(self.api.calls[-1][1]["machine_uuid"], other)

    def test_candidate_lookup_sends_uuid_even_without_state(self):
        self.repo.lookup_candidate(pinfl="31234567890123", exam_id=7)
        path, body = self.api.calls[-1]
        self.assertEqual(path, "/client/candidate/lookup/")
        self.assertEqual(body["machine_uuid"], UUID)
        self.assertNotIn("mac_address", body)


if __name__ == "__main__":
    unittest.main()
