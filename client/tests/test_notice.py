"""
JSHSHIR sahifasidagi MD3 xabar bloki (`ui/widgets/notice.py`).

Qo'riqlanadi: `MessageBar` bilan bir xil imzo (sahifa kodi va boshqa
testlar unga tayanadi), bo'sh matn blokni yashiradi, bron blokida
kataklarsiz kod ortiqcha bo'shliq qoldirmaydi.
"""

import unittest

from PyQt6.QtWidgets import QApplication

from ui.widgets.notice import Notice
from ui.widgets.seat_notice import SeatNotice


class NoticeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _notice(self, cls=Notice):
        widget = cls()
        self.addCleanup(widget.deleteLater)
        return widget

    def test_message_with_title(self):
        notice = self._notice()
        notice.show_message("JSHSHIR ni tekshiring.", "warning", title="Talabgor topilmadi")

        self.assertFalse(notice.isHidden())
        self.assertEqual(notice.kind(), "warning")
        self.assertEqual(notice.text(), "Talabgor topilmadi\nJSHSHIR ni tekshiring.")
        self.assertTrue(notice.detail.isHidden())

    def test_message_without_title_hides_title_row(self):
        notice = self._notice()
        notice.show_message("Avval imtihonni tanlang")
        self.assertTrue(notice.title.isHidden())
        self.assertEqual(notice.kind(), "error")

    def test_empty_message_clears(self):
        notice = self._notice()
        notice.show_message("x")
        notice.show_message("")
        self.assertTrue(notice.isHidden())
        self.assertEqual(notice.text(), "")

    def test_unknown_kind_falls_back_to_error(self):
        notice = self._notice()
        notice.show_notice("nonsense", "Sarlavha")
        self.assertEqual(notice.kind(), "error")

    def test_seat_code_without_tiles_hides_tile_row(self):
        notice = self._notice(SeatNotice)
        notice.show_problem("seat_not_booked", "Biriktirilmagan", None)
        self.assertTrue(notice.tiles.isHidden())
        self.assertIn("Biriktirilmagan", notice.text())

    def test_unknown_seat_code_does_not_repeat_server_text(self):
        notice = self._notice(SeatNotice)
        notice.show_problem("future_code", "Server matni", None)
        self.assertEqual(notice.text(), "Server matni")


if __name__ == "__main__":
    unittest.main()
