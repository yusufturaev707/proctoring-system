"""
O'z-o'zini tekshirish natijasi: "muammo va yechim".

DASTURNI YOPMAYDI va HECH NARSANI TO'SMAYDI (`core/self_check.py` izohi):
"Davom etish" har doim bor. Oyna `exec()` siz (`show()`) - tekshiruv
fon thread'ida qayta ishlaganda ham UI javob beradi.

Har muammo alohida qatorda: NIMA bo'ldi (sarlavha) va NIMA QILISH KERAK
(yechim). Operator texnik emas - "xato 0x80070005" unga hech narsa
aytmaydi, "antivirus faylni karantinga olgan, dastur katalogini
istisnoga qo'shing" esa aytadi.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.dialogs.base import CardDialog, apply_font
from ui.styles import COLORS, outlined_button_style, primary_button_style, surface_container_style
from ui.widgets.indicators import StateBadge

#: Ro'yxat maydonining eng katta balandligi: 1366x768 ekranda tugmalar
#: ko'rinib qolishi kerak.
_LIST_MAX_HEIGHT = 380


class _ProblemRow(QFrame):
    def __init__(self, problem, index: int, parent=None) -> None:
        super().__init__(parent)
        name = "selfCheckRow{}".format(index)
        self.setObjectName(name)
        is_error = problem.severity == "error"
        self.setStyleSheet(surface_container_style(name, tone="error" if is_error else "low"))
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 11, 14, 11)
        root.setSpacing(4)

        title = QLabel(problem.title)
        title.setWordWrap(True)
        apply_font(title, 14, bold=True, extra="color: {};".format(
            COLORS["error"] if is_error else COLORS["text"]))
        root.addWidget(title)

        solution = QLabel("Yechim: " + problem.solution)
        solution.setWordWrap(True)
        apply_font(solution, 13, extra="color: {};".format(COLORS["text_secondary"]))
        root.addWidget(solution)


class SelfCheckDialog(CardDialog):
    """Muammolar ro'yxati + "Qayta tekshirish" + "Davom etish"."""

    recheck_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent, title="Tizim tekshiruvi", card_width=600,
                         padding=(32, 26, 32, 24))
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
        layout.addSpacing(12)

        self.title_label = QLabel("Kompyuterda muammolar topildi")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setWordWrap(True)
        apply_font(self.title_label, 20, bold=True)
        layout.addWidget(self.title_label)
        layout.addSpacing(6)

        self.subtitle = QLabel("")
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle.setWordWrap(True)
        apply_font(self.subtitle, 13, extra="color: {};".format(COLORS["text_secondary"]))
        layout.addWidget(self.subtitle)
        layout.addSpacing(16)

        self._list_host = QWidget()
        self._list_host.setStyleSheet("background: transparent;")
        self._list = QVBoxLayout(self._list_host)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(8)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self._scroll.setWidget(self._list_host)
        layout.addWidget(self._scroll)

        layout.addSpacing(18)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.recheck_btn = QPushButton("Qayta tekshirish")
        self.recheck_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.recheck_btn.setStyleSheet(outlined_button_style(44, "primary"))
        self.recheck_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.recheck_btn.clicked.connect(self._on_recheck)
        buttons.addWidget(self.recheck_btn, 1)

        self.continue_btn = QPushButton("Davom etish")
        self.continue_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.continue_btn.setStyleSheet(primary_button_style(44))
        self.continue_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.continue_btn.setDefault(True)
        self.continue_btn.clicked.connect(self.hide)
        buttons.addWidget(self.continue_btn, 1)
        layout.addLayout(buttons)

    # ------------------------------------------------------------------
    def _on_recheck(self) -> None:
        self.set_checking(True)
        self.recheck_requested.emit()

    def set_checking(self, busy: bool) -> None:
        self.recheck_btn.setEnabled(not busy)
        self.recheck_btn.setText("Tekshirilmoqda..." if busy else "Qayta tekshirish")
        if busy:
            self.badge.set_state("loading")

    def show_report(self, report) -> None:
        """Natijani ko'rsatadi (ochiq oynani yangilaydi)."""
        self.set_checking(False)
        while self._list.count():
            item = self._list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        problems = sorted(report.problems, key=lambda p: 0 if p.severity == "error" else 1)
        if not problems:
            self.badge.set_state("ready")
            self.title_label.setText("Muammolar bartaraf etildi")
            self.subtitle.setText("Barcha tekshiruvlardan o'tildi. Davom etishingiz mumkin.")
        else:
            has_errors = any(p.severity == "error" for p in problems)
            self.badge.set_state("error" if has_errors else "warning")
            self.title_label.setText("Kompyuterda muammolar topildi")
            self.subtitle.setText(
                "{} ta muammo. Dastur ishlashda davom etadi, lekin quyidagilarni "
                "imtihondan OLDIN tuzating.".format(len(problems))
            )
        for index, problem in enumerate(problems):
            self._list.addWidget(_ProblemRow(problem, index))
        self._list.addStretch(1)

        self.refit()
        # Ro'yxat balandligi mazmunga qarab, lekin chegaradan oshmaydi.
        hint = self._list_host.sizeHint().height()
        self._scroll.setFixedHeight(max(60, min(_LIST_MAX_HEIGHT, hint)))
        self.adjustSize()
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
