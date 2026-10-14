"""
Erkin joylashuv (imtihon profilida `is_booking` o'chiq) - client ko'rinishi.

Qaror serverda; client'dan ikki narsa talab qilinadi:

  1. natija kartasi joy hali BAND EMASligini aytadi (`auto_assign`) -
     "JOY TASDIQLANDI" operatorni joy allaqachon olingan deb o'ylatardi;
  2. yangi rad kodlari oddiy xabar qatoriga emas, stol kartasiga
     tushadi va kartada talabgorning joyi emas, BU KOMPYUTER turadi.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from PyQt6.QtWidgets import QApplication

from services.app_state import AppState, Candidate
from ui.pages.candidate_page import CandidatePage
from ui.widgets.seat_notice import SEAT_CODES, SeatNotice

SEAT = {"computer_id": 5, "number": 12, "label": "№12 · INV-012", "zone_name": "1-bino"}
FREE_CODES = (
    "computer_not_in_schedule",
    "computer_out_of_service",
    "computer_busy",
    "candidate_already_finished",
)


class _QtCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])


class SeatNoticeFreeCodesTests(_QtCase):
    def test_free_seating_codes_use_the_seat_card(self):
        for code in FREE_CODES:
            with self.subTest(code=code):
                self.assertIn(code, SEAT_CODES)

    def test_card_shows_this_computer_without_direction(self):
        notice = SeatNotice()
        self.addCleanup(notice.deleteLater)
        notice.show_problem("computer_busy", "«№12» band", {"current": SEAT})

        self.assertFalse(notice.current.isHidden())
        self.assertTrue(notice.arrow.isHidden())
        self.assertTrue(notice.target.isHidden())
        self.assertEqual(notice.current.number.text(), "№12")
        self.assertIn("boshqa talabgorga", notice.title.text())

    def test_unknown_machine_has_no_tile(self):
        notice = SeatNotice()
        self.addCleanup(notice.deleteLater)
        notice.show_problem("computer_not_in_schedule", "ro'yxatda yo'q", {"current": None})
        self.assertTrue(notice.current.isHidden())
        self.assertTrue(notice.target.isHidden())


class CandidateSeatCaptionTests(_QtCase):
    def setUp(self):
        state = AppState()
        state.selected_exam = SimpleNamespace(id=7, name="Test")
        self.page = CandidatePage(state, mock.Mock())
        self.addCleanup(self.page.deleteLater)

    def _apply(self, seat):
        self.page._apply_seat(Candidate.from_api({"candidate": {}, "seat": seat}))

    def test_free_seat_is_not_called_confirmed(self):
        self._apply({**SEAT, "auto_assign": True})
        self.assertIn("BIRIKTIRILADI", self.page.seat_caption.text())
        self.assertIn("Erkin joylashuv", self.page.seat_panel.toolTip())

    def test_booked_seat_keeps_confirmed_caption(self):
        self._apply({**SEAT, "auto_assign": True})
        self._apply(SEAT)
        self.assertEqual(self.page.seat_caption.text(), "JOY TASDIQLANDI")
        self.assertNotIn("Erkin", self.page.seat_panel.toolTip())


if __name__ == "__main__":
    unittest.main()
