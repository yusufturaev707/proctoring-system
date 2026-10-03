"""
Ishga tushishdagi oynalar.

Qo'riqlanadigan narsalar:

  1. nativ splash (`core/early_splash.py`) o'z thread'ida ochiladi,
     ikkinchi nusxa uni klassi bo'yicha topadi va `close()` thread'ni
     tugatadi;
  2. `BrandLogo` otasiz yaratilganda ALOHIDA OYNA bo'lib ochilmaydi -
     ilgari ishga tushishda ekranning chap yuqorisida miltillardi.
"""

import os
import sys
import unittest

from core import single_instance


@unittest.skipUnless(sys.platform == "win32", "Win32 oyna")
class EarlySplashTests(unittest.TestCase):
    def test_show_text_close(self):
        from core.early_splash import EarlySplash

        splash = EarlySplash("Proctoring Client", logo_path=os.path.join("resources", "images", "logo.png"))
        self.assertTrue(splash.show())
        try:
            self.assertTrue(single_instance._splash_visible())
            splash.set_text("Tizim tekshirilmoqda…")
        finally:
            splash.close()
        self.assertFalse(splash._thread.is_alive())
        self.assertFalse(single_instance._splash_visible())

    def test_missing_logo_still_shows(self):
        from core.early_splash import EarlySplash

        splash = EarlySplash("Proctoring Client", logo_path="yo'q.png")
        self.assertTrue(splash.show())
        splash.close()
        splash.close()  # takroriy chaqiruv xavfsiz


class BrandLogoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_parentless_logo_is_not_a_window(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QWidget

        from ui.widgets.brand import BrandLogo

        logo = BrandLogo(52)
        self.assertFalse(logo.isVisible())
        self.assertFalse(logo.testAttribute(Qt.WidgetAttribute.WA_WState_Created))

        host = QWidget()
        logo.setParent(host)
        host.show()
        try:
            self.assertTrue(logo.isVisible())  # otadan meros
        finally:
            host.close()


class LaunchScreenTests(unittest.TestCase):
    """"Test ochilmoqda" ekrani - yuz tasdig'idan platforma chizilguncha."""

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from PyQt6.QtWidgets import QWidget

        from ui.widgets.launch_screen import LaunchScreen

        self.host = QWidget()
        self.host.resize(1366, 768)
        self.host.show()
        self.screen = LaunchScreen(self.host)

    def tearDown(self):
        self.host.close()

    def test_flow_and_progress_only_forward(self):
        from ui.widgets import launch_screen as ls

        self.screen.begin("Talabgor · Matematika")
        self.assertTrue(self.screen.is_active)
        self.assertEqual(self.screen.geometry(), self.host.rect())
        self.screen.set_progress(50)  # platforma qadami emas - e'tiborsiz
        self.assertEqual(self.screen._progress, -1)

        self.screen.advance(ls.STEP_BROWSER)
        self.screen.advance(ls.STEP_PLATFORM)
        self.screen.set_progress(60)
        self.screen.set_progress(10)  # yo'naltirish - chiziq orqaga qaytmaydi
        self.assertEqual(self.screen._progress, 60)
        self.screen.grab()  # chizish xatosiz

    def test_finish_fades_out(self):
        from PyQt6.QtTest import QTest

        self.screen.begin()
        self.screen.finish()
        self.assertFalse(self.screen.is_active)
        # Birinchi chizish (shriftlar) vaqt olishi mumkin - holat kutiladi.
        for _ in range(60):
            if not self.screen.isVisible():
                break
            QTest.qWait(50)
        self.assertFalse(self.screen.isVisible())

    def test_dismiss_and_give_up(self):
        from ui.widgets import launch_screen as ls

        self.screen.begin()
        self.screen.dismiss()
        self.assertFalse(self.screen.isVisible())
        self.screen.advance(ls.STEP_PLATFORM)  # yopiq ekran - hech narsa
        self.assertFalse(self.screen.isVisible())
        # Xavfsizlik chegarasi bor - ekran abadiy qolmaydi.
        self.screen.begin()
        self.assertTrue(self.screen._give_up.isActive())
        self.screen.dismiss()
        self.assertFalse(self.screen._give_up.isActive())
