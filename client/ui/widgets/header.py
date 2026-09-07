"""
Sahifa sarlavhasi - login'dan keyingi barcha sahifalarda bir xil.

Operator har doim uchta narsani ko'rib turishi kerak: qaysi bosqichda
turgani, qaysi binoda ishlayotgani va kim sifatida kirgani. Bu blok
sahifalar orasida ko'chirilmasligi uchun alohida vidjet.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ui.styles import COLORS, badge_style


class StepBadge(QLabel):
    """Bosqich raqami: 1/4, 2/4 ..."""

    def __init__(self, step: int, total: int, parent=None) -> None:
        super().__init__("{} / {}".format(step, total), parent)
        self.setStyleSheet(badge_style("info"))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(24)


class PageHeader(QWidget):
    """Sarlavha + kontekst + chiqish tugmasi."""

    logout_requested = pyqtSignal()
    back_requested = pyqtSignal()

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        *,
        step: int = 0,
        total_steps: int = 4,
        show_back: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(12)

        if show_back:
            self.back_btn = QPushButton("< Orqaga")
            self.back_btn.setProperty("variant", "ghost")
            self.back_btn.setFixedWidth(130)
            self.back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.back_btn.clicked.connect(self.back_requested.emit)
            top.addWidget(self.back_btn)
        else:
            self.back_btn = None

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_label = QLabel(title)
        title_label.setProperty("role", "title")
        title_box.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setProperty("role", "subtitle")
            title_box.addWidget(subtitle_label)
        top.addLayout(title_box)

        top.addStretch()

        if step:
            top.addWidget(StepBadge(step, total_steps))

        self.context_label = QLabel("")
        self.context_label.setStyleSheet(badge_style("muted"))
        self.context_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.context_label.setFixedHeight(24)
        top.addWidget(self.context_label)

        self.logout_btn = QPushButton("Chiqish")
        self.logout_btn.setProperty("variant", "ghost")
        self.logout_btn.setFixedWidth(120)
        self.logout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.logout_btn.clicked.connect(self.logout_requested.emit)
        top.addWidget(self.logout_btn)

        root.addLayout(top)

        divider = QFrame()
        divider.setProperty("role", "divider")
        divider.setFixedHeight(1)
        divider.setStyleSheet("background-color: {};".format(COLORS["border"]))
        root.addWidget(divider)

    def set_context(self, text: str) -> None:
        """O'ng yuqoridagi kontekst: "1-bino - operator Ali"."""
        self.context_label.setText(text)
        self.context_label.setVisible(bool(text))
