"""
Imtihon panelidagi «Test sahifasini qayta yuklash» tugmasi.

Qo'riqlanadigan narsalar:

  1. tasdiqsiz hech narsa bo'lmaydi (tugma talabgor oldida turadi);
  2. joriy sahifa xato ekranidagi bilan BIR XIL yo'l bilan qayta ochiladi
     (`_reload_page`, GET) — brauzer `Reload` amali emas;
  3. xato ekrani ochiq bo'lsa uning o'z manzili ishlatiladi;
  4. imtihon yopiq yoki qayta yuklash navbatda bo'lsa — hech narsa.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QApplication

from ui.pages import exam_webview_page as page_module
from ui.pages.exam_webview_page import ExamWebViewPage
from ui.widgets.icons import GlyphButton

CURRENT = "https://test.uz/exam/question/7"


def _page(*, exam_open=True, error_visible=False, timer_active=False):
    page = SimpleNamespace(
        _exam_open=exam_open,
        _modal_dialog=None,
        web_view=SimpleNamespace(url=lambda: QUrl(CURRENT)),
        _reload_timer=mock.Mock(isActive=mock.Mock(return_value=timer_active)),
        _error_panel=mock.Mock(isVisible=mock.Mock(return_value=error_visible)),
        _on_error_retry=mock.Mock(),
        _usable=ExamWebViewPage._usable,
        _retry_url=QUrl(),
        window=lambda: None,
    )
    page._run_dialog = lambda dialog: ExamWebViewPage._run_dialog(page, dialog)
    return page


def _click(page, *, accepted=True):
    result = (
        page_module.ReloadDialog.DialogCode.Accepted
        if accepted
        else page_module.ReloadDialog.DialogCode.Rejected
    )
    with mock.patch.object(page_module.ReloadDialog, "__init__", return_value=None), \
            mock.patch.object(page_module.ReloadDialog, "exec", return_value=result) as exec_:
        ExamWebViewPage._on_reload_clicked(page)
    return exec_


class ManualReloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_confirmed_reload_reopens_current_page(self):
        page = _page()
        _click(page)
        self.assertEqual(page._retry_url.toString(), CURRENT)
        page._reload_timer.start.assert_called_once_with(0)

    def test_cancel_does_nothing(self):
        page = _page()
        _click(page, accepted=False)
        page._reload_timer.start.assert_not_called()
        self.assertTrue(page._retry_url.isEmpty())

    def test_error_screen_keeps_its_own_target(self):
        page = _page(error_visible=True)
        _click(page)
        page._on_error_retry.assert_called_once_with()
        page._reload_timer.start.assert_not_called()

    def test_closed_exam_or_pending_reload_asks_nothing(self):
        for page in (_page(exam_open=False), _page(timer_active=True)):
            with self.subTest(exam_open=page._exam_open):
                exec_ = _click(page)
                exec_.assert_not_called()
                page._reload_timer.start.assert_not_called()

    def test_refresh_glyph_exists(self):
        """Noma'lum glif jimgina «warning» ga tushardi."""
        self.assertIn("refresh", GlyphButton.GLYPHS)
        self.assertEqual(GlyphButton("refresh")._glyph, "refresh")


if __name__ == "__main__":
    unittest.main()
