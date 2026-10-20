"""
Kamera tekshiruvi muddati: JSHSHIR sahifasida OLDINDAN aytiladi.

Server natijani OXIRGI tekshiruvdan 4 soat saqlaydi va uni faqat
`proctoring/start/` da talab qiladi. "Yakunlash" dan keyin oqim
JSHSHIR sahifasiga qaytadi va kamera sahifasini chetlab o'tadi -
ilgari muddat tugagani talabgor yuzdan o'tib bo'lgach
`camera_check_required` bo'lib chiqardi.

Qo'riqlanadigan narsalar:

  1. muddat `expires_in` dan monoton soatda hisoblanadi; eski server
     (maydonsiz) - noma'lum, hech narsa to'silmaydi;
  2. muddat talabgor oqimi bilan TOZALANMAYDI (`reset_flow`);
  3. muddati o'tgan yoki tugayotgan tekshiruvda qidiruv YUBORILMAYDI;
  4. siyosat tekshiruvni talab qilmasa - to'silmaydi.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from PyQt6.QtWidgets import QApplication

from proctoring.camera.roles import CameraLayout
from proctoring.policy import camera_check_required, check_readiness
from services.app_state import AppState
from ui.pages import candidate_page as module
from ui.pages.candidate_page import CandidatePage

PINFL = "12345678901234"


def _config(check_required=True, primary_required=True) -> dict:
    return {
        "proctoring": {
            "camera": {"check_required": check_required, "primary_required": primary_required},
            "modules": {},
        }
    }


class AppStateExpiryTests(unittest.TestCase):
    def test_left_counts_down_from_expires_in(self):
        state = AppState()
        with mock.patch("services.app_state.time.monotonic", return_value=100.0):
            state.note_camera_check({"expires_in": 14400})
        with mock.patch("services.app_state.time.monotonic", return_value=3700.0):
            self.assertEqual(state.camera_check_left(), 14400 - 3600)

    def test_old_server_means_unknown(self):
        state = AppState()
        state.note_camera_check({"can_start": True})
        self.assertIsNone(state.camera_check_left())

    def test_not_stored_on_server_is_already_expired(self):
        state = AppState()
        state.note_camera_check({"expires_in": 0})
        self.assertLessEqual(state.camera_check_left(), 0)

    def test_survives_candidate_reset(self):
        state = AppState()
        state.note_camera_check({"expires_in": 600})
        state.reset_flow()
        self.assertIsNotNone(state.camera_check_left())


class PolicyTests(unittest.TestCase):
    def test_required_only_when_server_and_policy_need_it(self):
        self.assertTrue(camera_check_required(_config()))
        self.assertFalse(camera_check_required(_config(check_required=False)))
        self.assertFalse(camera_check_required(_config(primary_required=False)))
        self.assertFalse(camera_check_required({}))

    def test_expired_check_has_own_title_and_blocks(self):
        issues = check_readiness(
            config=_config(), layout=CameraLayout(), check_result={}, check_expired=True
        )
        issue = next(i for i in issues if i.title == "Kamera tekshiruvi muddati tugagan")
        self.assertTrue(issue.blocking)


class CandidatePageGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.state = AppState()
        self.state.config = _config()
        self.state.selected_exam = SimpleNamespace(id=7, name="Test")
        self.repo = mock.Mock()
        self.page = CandidatePage(self.state, self.repo)
        self.page.pinfl_input.setText(PINFL)
        self.addCleanup(self.page.deleteLater)

    def _lookup(self):
        with mock.patch.object(module, "ApiWorker") as worker:
            self.page._on_lookup()
        return worker

    def test_expired_check_blocks_lookup(self):
        self.state.note_camera_check({"expires_in": 0})
        worker = self._lookup()
        worker.assert_not_called()
        self.assertIn("muddati tugagan", self.page.message.text())
        self.assertIn("Ctrl+Q", self.page.message.text())

    def test_check_expiring_soon_blocks_lookup(self):
        self.state.note_camera_check({"expires_in": module._CHECK_MARGIN_S - 60})
        worker = self._lookup()
        worker.assert_not_called()
        self.assertIn("daqiqadan keyin tugaydi", self.page.message.text())

    def test_fresh_check_lets_lookup_through(self):
        self.state.note_camera_check({"expires_in": 4 * 3600})
        self._lookup().assert_called_once()

    def test_lookup_locked_while_result_is_shown(self):
        """Natija ko'rinib turganda «TEKSHIRISH» o'chiq; raqam o'zgarsa — natija yo'qoladi."""
        self.state.note_camera_check({"expires_in": 4 * 3600})
        self.page._on_found({"masked_pinfl": "1234******1234", "test_link_ready": True})
        self.assertFalse(self.page.result_card.isHidden())
        self.assertFalse(self.page.lookup_btn.isEnabled())
        # Enter ham o'sha qoidada — takroriy so'rov ketmaydi.
        self._lookup().assert_not_called()

        self.page.pinfl_input.setText(PINFL[:-1] + "9")
        self.assertTrue(self.page.result_card.isHidden())
        self.assertTrue(self.page.lookup_btn.isEnabled())

    def test_unknown_expiry_is_not_blocked(self):
        self._lookup().assert_called_once()

    def test_policy_without_check_is_not_blocked(self):
        self.state.config = _config(check_required=False)
        self.state.note_camera_check({"expires_in": 0})
        self._lookup().assert_called_once()

    def test_finish_notice_keeps_seat_message_and_adds_warning(self):
        self.state.note_camera_check({"expires_in": 0})
        self.page.show_finish_notice({"seat_released": True, "seat": {"label": "№12"}})
        text = self.page.message.text()
        self.assertIn("№12", text)
        self.assertIn("muddati tugagan", text)


if __name__ == "__main__":
    unittest.main()
