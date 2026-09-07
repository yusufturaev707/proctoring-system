"""
Kirish nuqtasi.

Ishga tushish tartibi referens loyihadagidek: avval log va muhit
(og'ir importlardan OLDIN), keyin Qt, oxirida oyna.

`INSIGHTFACE_ROOT` ni import zanjiridan oldin qo'yish shart -
`insightface.utils.download` va `model_zoo` shu env var'ga qaraydi va
uni kech qo'ysak, model `~/.insightface` ga yuklab olinadi.
"""

from __future__ import annotations

import os
import sys
import types

from core.bundle_paths import resource_root
from core.logging_setup import setup_logging

os.environ.setdefault("INSIGHTFACE_ROOT", str(resource_root()))

# `insightface/app/__init__.py` ichida `from .mask_renderer import *` bor.
# mask_renderer modul darajasida albumentations va face3d ni import qiladi
# (~50 MB + Cython). `FaceAnalysis` uchun ular KERAK EMAS, lekin import
# baribir bajariladi. Stub bilan zanjirni kesamiz: bundle kichrayadi va
# frozen rejimdagi ModuleNotFound xatolari yo'qoladi.
_stub = types.ModuleType("insightface.app.mask_renderer")
_stub.MaskRenderer = type("MaskRenderer", (), {})
sys.modules.setdefault("insightface.app.mask_renderer", _stub)

log = setup_logging()


def main() -> int:
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QApplication

    from config import APP_NAME, APP_VERSION
    from main_window import MainWindow
    from ui.styles import GLOBAL_STYLESHEET

    # QtWebEngine QApplication'dan OLDIN e'lon qilinishi shart. Aks holda
    # `QtWebEngineWidgets` importi "must be imported ... before a
    # QCoreApplication instance is created" bilan yiqiladi. Modulni shu
    # yerda import qilish ham yechim, lekin u butun engine'ni (~150 MB)
    # darhol yuklaydi; bayroq esa buni WebView sahifasi ochilgunga qadar
    # kechiktiradi.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

    # `sys.argv` MAJBURIY, bo'sh ro'yxat EMAS. Chromium `argv[0]` dan
    # dastur nomini oladi; usiz WebEngine "base::CommandLine cannot be
    # properly initialized" deb butun jarayonni qulatadi (0xC0000409).
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(GLOBAL_STYLESHEET)

    window = MainWindow()
    window.show_start()
    log.info("%s v%s ishga tushdi", APP_NAME, APP_VERSION)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
