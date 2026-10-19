"""
"Test sahifasini qayta yuklash" tasdig'i.

NIMA UCHUN KERAK. Test platformasi ba'zan qotib qoladi (oq ekran,
tugma javob bermaydi), lekin xato bermaydi — o'shanda xato ekrani va
uning «Qayta yuklash» tugmasi chiqmaydi. Kioskda F5 ham, manzil satri
ham yo'q, brauzer menyusi esa ataylab o'chirilgan
(`exam_webview_page`, `NoContextMenu`: unda «Back» bor — talabgor
platformaning oldingi sahifalariga qaytib ketardi).

NIMA UCHUN TASDIQ. Panel talabgor oldida turadi va tugma tasodifan
bosilishi mumkin. Belgilangan javoblar platformada saqlanadi, lekin
yozilayotgan va hali yuborilmagan javob yo'qolishi mumkin — oqibat
tugmadan OLDIN aytiladi. Xavfsiz amal («Testga qaytish») fokusda:
Enter tasodifan sahifani qayta yuklamasin.
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from ui.dialogs.base import CardDialog, apply_font
from ui.styles import COLORS, primary_button_style, tonal_button_style
from ui.widgets.icons import draw_refresh


class _RefreshBadge(QWidget):
    """MD3 tonal nishon: imtihon panelidagi tugmaning O'ZI belgisi."""

    def __init__(self, size: int = 64, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = self.width()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLORS["primary_container"]))
        painter.drawRoundedRect(0, 0, size, size, size * 0.28, size * 0.28)
        draw_refresh(
            painter, QPointF(size / 2, size / 2), size * 0.22,
            QColor(COLORS["on_primary_container"]),
        )
        painter.end()


class ReloadDialog(CardDialog):
    """Qayta yuklashni tasdiqlaydi. `exec()` -> `Accepted` = qayta yuklash."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent, title="Sahifani qayta yuklash", card_width=480,
                         padding=(32, 30, 32, 26))
        layout = self.body

        badge_row = QHBoxLayout()
        badge_row.addStretch()
        badge_row.addWidget(_RefreshBadge(64))
        badge_row.addStretch()
        layout.addLayout(badge_row)
        layout.addSpacing(16)

        title = QLabel("Test sahifasini qayta yuklaysizmi?")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        apply_font(title, 22, bold=True, extra="color: {};".format(COLORS["text"]))
        layout.addWidget(title)
        layout.addSpacing(6)

        subtitle = QLabel(
            "Sahifa qotib qolgan yoki to‘liq ochilmagan bo‘lsa. Imtihon "
            "vaqti to‘xtamaydi."
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        apply_font(subtitle, 14, extra="color: {};".format(COLORS["text_secondary"]))
        layout.addWidget(subtitle)
        layout.addSpacing(16)

        note = QLabel(
            "Belgilangan javoblar test platformasida saqlangan. Hozir yozilayotgan, "
            "hali yuborilmagan javob yo‘qolishi mumkin."
        )
        note.setWordWrap(True)
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        apply_font(
            note, 13,
            extra="color: {}; background: {}; border-radius: 12px; padding: 10px 14px;".format(
                COLORS["text_secondary"], COLORS["surface_alt"]
            ),
        )
        layout.addWidget(note)
        layout.addSpacing(22)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.back_btn = QPushButton("Testga qaytish")
        self.back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_btn.setStyleSheet(tonal_button_style(48))
        self.back_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.back_btn.clicked.connect(self.reject)
        buttons.addWidget(self.back_btn, 1)

        self.reload_btn = QPushButton("Qayta yuklash")
        self.reload_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reload_btn.setStyleSheet(primary_button_style(48))
        self.reload_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.reload_btn.setAutoDefault(False)
        self.reload_btn.clicked.connect(self.accept)
        buttons.addWidget(self.reload_btn, 1)
        layout.addLayout(buttons)

        self.back_btn.setDefault(True)
        self.back_btn.setFocus()
        self.refit()
