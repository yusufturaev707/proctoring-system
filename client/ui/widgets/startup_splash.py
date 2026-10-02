"""
Ishga tushish oynasi (splash) — QApplication paydo bo'lgan zahoti.

NIMA UCHUN. Asosiy oyna bir necha soniyadan keyin chiqadi: boshqa
dasturlarni yopish, tahdid skaneri va og'ir modullar (kamera, WebEngine)
shu vaqtni oladi. Ilgari bu soniyalarda ekranda HECH NARSA yo'q edi va
xodim "dastur ochilmadi" deb belgini qayta-qayta bosardi. Ikkinchi
nusxani mutex baribir to'xtatadi (`core/single_instance.py`), lekin
bosishning o'zi to'xtashi uchun dastur darhol "ishga tushyapman" deb
ko'rinishi kerak.

YENGIL: faqat QtWidgets va `ui.styles` / `ui.widgets.brand` - og'ir
modullarni import qilmaydi, aks holda splash o'zi kech chiqardi.

Hodisa sikli hali YO'Q (`app.exec()` dan oldin): chaqiruvchi har bosqich
orasida `set_text()` chaqiradi, u `processEvents()` bilan qayta chizadi.
Shuning uchun animatsiyali "spinner" yo'q - u baribir qotib turardi;
o'rniga har bosqichda to'ladigan chiziq.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from ui.styles import COLORS

_CARD_WIDTH = 420
_SHADOW = 32


class StartupSplash(QWidget):
    """Markazdagi MD3 kartasi: logotip, nom, bosqich matni, progress."""

    def __init__(self, app_name: str, version: str = "", *, steps: int = 5) -> None:
        super().__init__(None)
        # Ramkasiz + doim ustda + vazifalar panelida alohida tugmasiz
        # (`Tool`): kiosk'da ham, oddiy rejimda ham asosiy oynadan
        # oldin ko'rinadi va keyin izsiz yo'qoladi.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        # Asosiy oyna bilan BIR XIL sarlavha EMAS: ikkinchi nusxa
        # (`single_instance._find_main_window`) oldinga chiqarish uchun
        # asosiy oynani sarlavhasi bo'yicha qidiradi.
        self.setWindowTitle(app_name + " — yuklanmoqda")
        self._steps = max(1, steps)
        self._done = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(_SHADOW, _SHADOW, _SHADOW, _SHADOW)

        card = QFrame(self)
        card.setObjectName("splashCard")
        card.setFixedWidth(_CARD_WIDTH)
        card.setStyleSheet(
            "QFrame#splashCard {{ background-color: {}; border: none; border-radius: 28px; }}".format(
                COLORS["surface_container_lowest"]
            )
        )
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(16, 32, 20, 90))
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(36, 32, 36, 28)
        layout.setSpacing(10)

        try:
            from ui.widgets.brand import BrandLogo

            layout.addWidget(BrandLogo(52), 0, Qt.AlignmentFlag.AlignHCenter)
        except Exception:  # noqa: BLE001 - logotip bezak, to'siq emas
            pass

        title = QLabel(app_name)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            "font-size: 20px; font-weight: 700; background: transparent; color: {};".format(
                COLORS["on_surface"]
            )
        )
        layout.addWidget(title)

        self._text = QLabel("Dastur ishga tushmoqda…")
        self._text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._text.setWordWrap(True)
        self._text.setStyleSheet(
            "font-size: 14px; background: transparent; color: {};".format(
                COLORS["on_surface_variant"]
            )
        )
        layout.addWidget(self._text)
        layout.addSpacing(6)

        self._bar = QProgressBar()
        self._bar.setRange(0, self._steps)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(4)
        layout.addWidget(self._bar)

        if version:
            caption = QLabel("v{}".format(version))
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caption.setStyleSheet(
                "font-size: 12px; background: transparent; color: {};".format(COLORS["outline"])
            )
            layout.addWidget(caption)

        self.adjustSize()
        screen = QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(area.center() - self.rect().center())

    def set_text(self, text: str) -> None:
        """Keyingi bosqich: matn + chiziq bir pog'ona, darhol qayta chiziladi."""
        self._done = min(self._steps, self._done + 1)
        self._text.setText(text)
        self._bar.setValue(self._done)
        QApplication.processEvents()
