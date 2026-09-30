"""
Bloklamaydigan xabar oynasi - `QMessageBox` o'rniga.

`QMessageBox.warning()` ichida `exec()` bor: u chaqiruvchi kodni xabar
yopilguncha to'xtatadi va operator oynani ochiq qoldirsa, undan keyingi
qadam (masalan FaceID sahifasiga qaytish) ham kutib turardi. Bu yerda
faqat `show()`: chaqiruvchi o'z ishini darhol davom ettiradi, xabar esa
ustida turadi.

BITTA NUSXA qayta ishlatiladi (`show_notice` ochiq oynani YANGILAYDI):
ketma-ket kelgan xabarlar bir-birining ustiga uyilmaydi - aks holda
takrorlanuvchi xatoda ekran o'nlab oynaga to'lardi.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton

from ui.dialogs.base import CardDialog, apply_font
from ui.styles import COLORS, primary_button_style
from ui.widgets.indicators import StateBadge

_KIND_COLOR = {"info": "accent", "warning": "warning", "error": "error"}


class NoticeDialog(CardDialog):
    """Sarlavha + matn + ixtiyoriy texnik satr + "Tushunarli"."""

    def __init__(self, parent=None, *, modal: bool = True) -> None:
        super().__init__(parent, title="Xabar", card_width=540)
        if not modal:
            # Imtihon yoki ish oqimini TO'SMAYDI: kiritish asosiy oynaga
            # o'tishda davom etadi, xabar esa yon tomonda ko'rinib turadi.
            self.setWindowModality(Qt.WindowModality.NonModal)
        self._auto_close = QTimer(self)
        self._auto_close.setSingleShot(True)
        self._auto_close.timeout.connect(self.hide)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = self.body

        badge_row = QHBoxLayout()
        badge_row.addStretch()
        self.badge = StateBadge(size=60)
        self.badge.set_state("warning")
        badge_row.addWidget(self.badge)
        badge_row.addStretch()
        layout.addLayout(badge_row)
        layout.addSpacing(14)

        self.title_label = QLabel("")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setWordWrap(True)
        apply_font(self.title_label, 20, bold=True)
        layout.addWidget(self.title_label)
        layout.addSpacing(8)

        self.text_label = QLabel("")
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text_label.setWordWrap(True)
        apply_font(self.text_label, 15, extra="color: {};".format(COLORS["text"]))
        layout.addWidget(self.text_label)

        layout.addSpacing(8)
        self.detail_label = QLabel("")
        self.detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_label.setWordWrap(True)
        apply_font(self.detail_label, 12, extra="color: {};".format(COLORS["text_muted"]))
        layout.addWidget(self.detail_label)

        layout.addSpacing(18)
        self.ok_btn = QPushButton("Tushunarli")
        self.ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ok_btn.setStyleSheet(primary_button_style(46))
        self.ok_btn.clicked.connect(self.hide)
        layout.addWidget(self.ok_btn)

    # ------------------------------------------------------------------
    def show_notice(self, title: str, text: str, *, kind: str = "warning",
                    detail: str = "", auto_close_s: int = 0) -> None:
        """Ko'rsatadi yoki ochiq oynani YANGILAYDI. Hech qachon bloklamaydi."""
        state = {"info": "info", "warning": "warning", "error": "error"}.get(kind, "warning")
        self.badge.set_state(state)
        self.title_label.setText(title or "Xabar")
        apply_font(
            self.title_label, 20, bold=True,
            extra="color: {};".format(COLORS[_KIND_COLOR.get(kind, "warning")]),
        )
        self.text_label.setText(text or "")
        self.detail_label.setText(detail or "")
        self.detail_label.setVisible(bool(detail))
        self._auto_close.stop()
        if auto_close_s and auto_close_s > 0:
            self._auto_close.start(int(auto_close_s) * 1000)
        self.refit()
        self.show()
        self.raise_()

    def showEvent(self, event) -> None:
        parent = self.parent()
        if parent is not None:
            geometry = parent.geometry()
            self.move(
                geometry.x() + (geometry.width() - self.width()) // 2,
                geometry.y() + (geometry.height() - self.height()) // 2,
            )
        super().showEvent(event)
