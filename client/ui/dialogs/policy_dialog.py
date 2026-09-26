"""
Imtihon sozlamasiga moslik dialogi.

"Davom etish" bosilganda tanlangan imtihonning profili serverdan
olinadi va ish o'rni holati bilan solishtiriladi
(`proctoring/policy.py`). Natija shu dialogda ko'rsatiladi.

NIMA UCHUN MODAL, XABAR QATORI EMAS. Xabar qatori (`MessageBar`) bitta
qatorlik matn uchun va uni o'qimasdan o'tib ketish mumkin. Bu yerda
esa bir nechta sabab bo'lishi mumkin va ularning har biri operatorning
HARAKATINI talab qiladi (kamerani ulash, virtual qurilmani o'chirish).
Modal oqimni to'xtatadi va aynan shu kerak: aks holda operator
talabgorni chaqirib, keyingi qadamda tuzatib bo'lmaydigan holatga
tushardi.

IKKI REJIM VA ULARNING FARQI SHAKLDA KO'RINADI:

    to'siq bor    - qizil nishon, yagona "Tushunarli" tugmasi.
                    Davom etish YO'Q va uni chetlab o'tish yo'li
                    ko'rsatilmaydi ham.
    faqat ogohl.  - sariq nishon, [Bekor qilish][Davom etish].
                    Qaror operatorniki.

Uchinchi holat (muammo yo'q) dialogsiz o'tadi - operatorni bekorga
to'xtatmaslik kerak.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QPushButton,
)

from ui.dialogs.base import CardDialog, apply_font as _apply_font
from ui.styles import COLORS, outlined_button_style, surface_container_style
from ui.widgets.indicators import StateBadge


class IssueRow(QFrame):
    """Bitta sabab: sarlavha + tushuntirish."""

    def __init__(self, issue, index: int, parent=None) -> None:
        super().__init__(parent)
        name = "issueRow{}".format(index)
        self.setObjectName(name)
        self.setStyleSheet(
            surface_container_style(name, tone="error" if issue.blocking else "low")
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 11, 14, 11)
        root.setSpacing(3)

        title = QLabel(issue.title)
        _apply_font(
            title,
            14,
            bold=True,
            extra="color: {};".format(
                COLORS["error"] if issue.blocking else COLORS["text"]
            ),
        )
        title.setWordWrap(True)
        root.addWidget(title)

        if issue.detail:
            detail = QLabel(issue.detail)
            detail.setWordWrap(True)
            _apply_font(detail, 13, extra="color: {};".format(COLORS["text_secondary"]))
            root.addWidget(detail)


class PolicyDialog(CardDialog):
    """Sozlamaga moslik natijasi."""

    def __init__(self, parent=None, *, exam_name: str = "", setting_name: str = "",
                 issues=None) -> None:
        super().__init__(
            parent,
            title="Imtihon sozlamasi",
            card_width=560,
            padding=(32, 26, 32, 24),
        )
        self._issues = list(issues or [])
        self._blocking = [item for item in self._issues if item.blocking]
        self._exam_name = exam_name
        self._setting_name = setting_name

        self._setup_ui()

    @property
    def has_blocking(self) -> bool:
        return bool(self._blocking)

    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        # Qobiq (karta, soya, chetlar) `CardDialog` da.
        layout = self.body

        badge_row = QHBoxLayout()
        badge_row.addStretch()
        badge = StateBadge(size=64)
        badge.set_state("error" if self.has_blocking else "warning")
        badge_row.addWidget(badge)
        badge_row.addStretch()
        layout.addLayout(badge_row)
        layout.addSpacing(14)

        title = QLabel(
            "Imtihonni boshlab bo'lmaydi"
            if self.has_blocking
            else "Ish o'rni to'liq tayyor emas"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Uzun sarlavha ikki qatorga o'tsin: shrift topilmagan yoki
        # boshqa tilga tarjima qilingan holatda u kartadan chiqib
        # ketardi va chetlari kesilardi.
        title.setWordWrap(True)
        _apply_font(title, 20, bold=True, extra="color: {};".format(COLORS["text"]))
        layout.addWidget(title)
        layout.addSpacing(6)

        # Qaysi imtihon va QAYSI PROFIL tekshirilgani aytiladi.
        # Usiz operator "nega bu yerda talab qilinyapti, qo'shni
        # mashinada esa yo'q?" degan savolga javob topolmasdi -
        # javob odatda profilda: imtihonga boshqa sozlama
        # biriktirilgan.
        parts = [part for part in (self._exam_name, self._setting_name) if part]
        subtitle = QLabel(" · ".join(parts) if parts else "Sozlama tekshirildi")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        _apply_font(subtitle, 13, extra="color: {};".format(COLORS["text_secondary"]))
        layout.addWidget(subtitle)
        layout.addSpacing(20)

        # To'siqlar BIRINCHI: ular harakat talab qiladi,
        # ogohlantirishlar esa faqat ma'lumot.
        for index, issue in enumerate(self._blocking + [
            item for item in self._issues if not item.blocking
        ]):
            if index:
                layout.addSpacing(8)
            layout.addWidget(IssueRow(issue, index))

        layout.addSpacing(22)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)

        if self.has_blocking:
            # Davom etish tugmasi UMUMAN ko'rsatilmaydi. O'chirilgan
            # tugma "yo'l bor, lekin yopiq" degan taassurot beradi va
            # operator uni bosishga urinib vaqt yo'qotadi.
            close_btn = QPushButton("Tushunarli")
            close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            close_btn.setStyleSheet(outlined_button_style(44, "neutral"))
            close_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            close_btn.setDefault(True)
            close_btn.clicked.connect(self.reject)
            buttons.addWidget(close_btn, 1)
        else:
            cancel_btn = QPushButton("Bekor qilish")
            cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            cancel_btn.setStyleSheet(outlined_button_style(44, "neutral"))
            cancel_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            cancel_btn.clicked.connect(self.reject)
            buttons.addWidget(cancel_btn, 1)

            confirm_btn = QPushButton("Baribir davom etish")
            confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            confirm_btn.setStyleSheet(outlined_button_style(44, "primary"))
            confirm_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            confirm_btn.setDefault(True)
            confirm_btn.clicked.connect(self.accept)
            buttons.addWidget(confirm_btn, 1)

        layout.addLayout(buttons)
        # Sabablar ro'yxatidagi matnlar o'raladi va ularning haqiqiy
        # balandligi faqat shu yerda ma'lum bo'ladi
        # (`CardDialog.refit` izohi).
        self.refit()

    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:
        parent = self.parent()
        if parent is not None:
            geometry = parent.geometry()
            self.move(
                geometry.x() + (geometry.width() - self.width()) // 2,
                geometry.y() + (geometry.height() - self.height()) // 2,
            )
        super().showEvent(event)
