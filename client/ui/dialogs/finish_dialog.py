"""
"Imtihonni yakunlash" tasdig'i.

Ilgari bu `QMessageBox.question` edi: tizim uslubidagi kulrang oyna,
"Yes/No" tugmalari va bitta qator matn. Kiosk oynasining ustida u
begona dastur oynasidek ko'rinardi (`CLAUDE.md`: "QInputDialog/
QMessageBox ISHLATILMAYDI") va eng muhim savolga — "KIMNING imtihoni
yakunlanyapti?" — javob bermasdi.

Bu amal QAYTARIB BO'LMAYDIGAN yagona tugma: sessiya serverda yopiladi
va talabgor testga qayta kira olmaydi. Shuning uchun dialog uch narsani
bir qarashda ko'rsatadi:

    kim       - talabgor ismi, niqoblangan JSHSHIR va kompyuter raqami
                (operator ko'pincha qo'shni mashinada turib bosadi);
    qancha    - test qancha davom etgani ("2 daqiqa" — ehtimol xato);
    oqibat    - qizil tonal blokda, tugmadan OLDIN.

Xavfsiz amal ("Testga qaytish") FOKUSDA: Enter tasodifan imtihonni
yakunlab yubormasligi kerak. Yakunlash — to'ldirilgan qizil tugma,
dasturdagi yagona shunday tugma (`danger_button_style`).
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from ui.dialogs.base import CardDialog, apply_font
from ui.styles import COLORS, danger_button_style, surface_container_style, tonal_button_style
from ui.widgets.icons import GlyphButton


def format_elapsed(seconds: Optional[float]) -> str:
    """`4380` -> "1 soat 13 daqiqa"; bir daqiqadan kam -> "1 daqiqadan kam"."""
    if seconds is None:
        return ""
    minutes = int(seconds // 60)
    if minutes < 1:
        return "1 daqiqadan kam"
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return "{} soat {} daqiqa".format(hours, minutes)
    if hours:
        return "{} soat".format(hours)
    return "{} daqiqa".format(minutes)


class _PowerBadge(QWidget):
    """MD3 tonal nishon: xato konteyneri ichida "o'chirish" belgisi."""

    def __init__(self, size: int = 64, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = self.width()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLORS["error_soft"]))
        painter.drawRoundedRect(0, 0, size, size, size * 0.28, size * 0.28)
        # Belgi imtihon panelidagi "Yakunlash" tugmasining O'ZI — operator
        # qaysi tugmani bosganini dialogda ham taniydi.
        GlyphButton._draw_power(
            painter, QPointF(size / 2, size / 2), size * 0.22, QColor(COLORS["error"])
        )
        painter.end()


class FinishDialog(CardDialog):
    """Imtihonni yakunlashni tasdiqlaydi. `exec()` -> `Accepted` = yakunlash."""

    def __init__(
        self,
        parent=None,
        *,
        candidate_name: str = "",
        masked_pinfl: str = "",
        seat: str = "",
        elapsed_s: Optional[float] = None,
    ) -> None:
        super().__init__(parent, title="Imtihonni yakunlash", card_width=500,
                         padding=(32, 30, 32, 26))
        layout = self.body

        badge_row = QHBoxLayout()
        badge_row.addStretch()
        badge_row.addWidget(_PowerBadge(64))
        badge_row.addStretch()
        layout.addLayout(badge_row)
        layout.addSpacing(16)

        title = QLabel("Imtihonni yakunlaysizmi?")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        apply_font(title, 22, bold=True, extra="color: {};".format(COLORS["text"]))
        layout.addWidget(title)
        layout.addSpacing(6)

        subtitle = QLabel(
            "Test sahifasi yopiladi, kuzatuv va ekran yozuvi to‘xtaydi. "
            "Kompyuter keyingi talabgor uchun bo‘shatiladi."
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        apply_font(subtitle, 14, extra="color: {};".format(COLORS["text_secondary"]))
        layout.addWidget(subtitle)
        layout.addSpacing(18)

        rows = [
            ("Talabgor", candidate_name),
            ("JSHSHIR", masked_pinfl),
            ("Kompyuter", seat),
            ("Test davomiyligi", format_elapsed(elapsed_s)),
        ]
        rows = [(caption, value) for caption, value in rows if value]
        if rows:
            layout.addWidget(self._summary(rows))
            layout.addSpacing(14)

        warning = QLabel("Talabgor testga QAYTA KIRA OLMAYDI — bu amalni qaytarib bo‘lmaydi.")
        warning.setWordWrap(True)
        warning.setAlignment(Qt.AlignmentFlag.AlignCenter)
        apply_font(
            warning, 13, bold=True,
            extra="color: {}; background: {}; border-radius: 12px; padding: 10px 14px;".format(
                COLORS["on_error_container"], COLORS["error_container"]
            ),
        )
        layout.addWidget(warning)
        layout.addSpacing(22)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.back_btn = QPushButton("Testga qaytish")
        self.back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_btn.setStyleSheet(tonal_button_style(48))
        self.back_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.back_btn.clicked.connect(self.reject)
        buttons.addWidget(self.back_btn, 1)

        self.finish_btn = QPushButton("Yakunlash")
        self.finish_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.finish_btn.setStyleSheet(danger_button_style(48))
        self.finish_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.finish_btn.setAutoDefault(False)
        self.finish_btn.clicked.connect(self.accept)
        buttons.addWidget(self.finish_btn, 1)
        layout.addLayout(buttons)

        self.back_btn.setDefault(True)
        self.refit()

    @staticmethod
    def _summary(rows) -> QFrame:
        """Kim va qancha — ikki ustunli "surface container" blok."""
        frame = QFrame()
        frame.setObjectName("finishSummary")
        frame.setStyleSheet(surface_container_style("finishSummary"))
        grid = QGridLayout(frame)
        grid.setContentsMargins(18, 14, 18, 14)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        for row, (caption, value) in enumerate(rows):
            key = QLabel(caption)
            apply_font(key, 13, extra="color: {};".format(COLORS["text_secondary"]))
            grid.addWidget(key, row, 0, Qt.AlignmentFlag.AlignLeft)
            text = QLabel(value)
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            apply_font(text, 14, bold=True, extra="color: {};".format(COLORS["text"]))
            grid.addWidget(text, row, 1, Qt.AlignmentFlag.AlignRight)
        grid.setColumnStretch(1, 1)
        return frame

    def showEvent(self, event) -> None:
        parent = self.parent()
        if parent is not None:
            geometry = parent.window().geometry()
            self.move(
                geometry.x() + (geometry.width() - self.width()) // 2,
                geometry.y() + (geometry.height() - self.height()) // 2,
            )
        super().showEvent(event)
        self.back_btn.setFocus()
