"""
Mashina identifikatori serverga qanday ketadi.

Qo'riqlanadigan shartnoma (server: `devices.services.verify_machine`,
`exams.bookings.resolve_candidate_seat`):

  1. handshake va JSHSHIR tekshiruvida `machine_uuid` HAR DOIM bor -
     usiz server eski MAC qoidasiga tushadi;
  2. apparat izi `muid:<UUID>` - prefiks server bilan kelishilgan
     (`FINGERPRINT_UUID_PREFIX`), MAC'ga bog'liq emas.
"""

import unittest
from unittest import mock

from services import repositories
from services import system_info

UUID = "4C4C4544-0038-4A10-805A-C7C04F4B3A01"


class _FakeApi:
    def __init__(self):
        self.calls = []

    def post(self, path, json_body=None, **kwargs):
        self.calls.append((path, json_body))
        return {}


class MachineIdentityPayloadTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(system_info, "machine_uuid", return_value=UUID)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name, value in (("public_ip", ""), ("info_pc", {})):
            patcher = mock.patch.object(system_info, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.api = _FakeApi()
        self.repo = repositories.ProctoringRepository(api=self.api)

    def test_fingerprint_is_machine_uuid(self):
        self.assertEqual(system_info.hardware_fingerprint(), "muid:" + UUID)

    def test_handshake_always_sends_uuid(self):
        self.repo.handshake(app_version="1.0", machine={"mac": "2C:F0:5D:77:BB:EB", "ip": "10.0.0.5"})
        _path, body = self.api.calls[-1]
        self.assertEqual(body["machine_uuid"], UUID)
        self.assertEqual(body["mac_address"], "2C:F0:5D:77:BB:EB")
        self.assertEqual(body["hardware_fingerprint"], "muid:" + UUID)

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
