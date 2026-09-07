"""
3-SAHIFA - JSHSHIR bo'yicha talabgorni tekshirish.

Backend `/client/candidate/lookup/` tanlangan imtihonning tashqi
platformadagi kodi bo'yicha ntest'ga boradi va javobni qaytaradi.

Bu tizimdagi ENG NOZIK endpoint: JSHSHIR strukturasi ma'lum, ya'ni
chegarasiz u fuqarolar ismini qidirish servisiga aylanadi. Shuning
uchun backendda ikki xil throttle bor va client ularni hurmat qiladi:
so'rov ketayotganda tugma bloklanadi, 429 javobi esa alohida
ko'rsatiladi ("biroz kutib qayta urining").

Javobda `session_token` client'ga BERILMAYDI - u FaceID va operator
tasdig'idan keyin, 5-sahifada `exam/access/` orqali olinadi. Sabab
backend `issue_exam_access` docstring'ida: bu qaytib bo'lmaydigan
nuqta va undan oldin shaxs tasdiqlanishi shart.
"""

from __future__ import annotations

import base64
import binascii
import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from services.app_state import AppState, Candidate
from services.repositories import ProctoringRepository
from services.workers import ApiWorker, WorkerHolder
from ui.styles import badge_style, primary_button_style
from ui.widgets.camera_view import PhotoView
from ui.widgets.header import PageHeader
from ui.widgets.indicators import BusyOverlay, Card, MessageBar

log = logging.getLogger(__name__)

PINFL_LENGTH = 14


class CandidatePage(QWidget):
    """Talabgorni JSHSHIR bo'yicha topish."""

    candidate_ready = pyqtSignal(object)  # Candidate
    back_requested = pyqtSignal()
    logout_requested = pyqtSignal()

    def __init__(self, state: AppState, repo: ProctoringRepository, parent=None) -> None:
        super().__init__(parent)
        self._state = state
        self._repo = repo
        self._workers = WorkerHolder()
        self._setup_ui()

    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 32, 48, 36)
        root.setSpacing(22)

        self.header = PageHeader(
            "Talabgorni tekshirish",
            "JSHSHIR kiriting - ma'lumot test platformasidan olinadi",
            step=2,
            show_back=True,
        )
        self.header.logout_requested.connect(self.logout_requested.emit)
        self.header.back_requested.connect(self.back_requested.emit)
        root.addWidget(self.header)

        body = QHBoxLayout()
        body.setSpacing(22)

        # --- Chap: JSHSHIR formasi ---
        form_card = Card("JSHSHIR")
        hint = QLabel("14 xonali raqam")
        hint.setProperty("role", "caption")
        form_card.body.addWidget(hint)

        self.pinfl_input = QLineEdit()
        self.pinfl_input.setPlaceholderText("00000000000000")
        self.pinfl_input.setMaxLength(PINFL_LENGTH)
        self.pinfl_input.setFixedHeight(56)
        self.pinfl_input.setStyleSheet("font-size: 22px; letter-spacing: 3px;")
        self.pinfl_input.textChanged.connect(self._on_pinfl_changed)
        self.pinfl_input.returnPressed.connect(self._on_lookup)
        form_card.body.addWidget(self.pinfl_input)

        self.lookup_btn = QPushButton("TEKSHIRISH")
        self.lookup_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lookup_btn.setStyleSheet(primary_button_style(52))
        self.lookup_btn.setEnabled(False)
        self.lookup_btn.clicked.connect(self._on_lookup)
        form_card.body.addWidget(self.lookup_btn)

        self.message = MessageBar()
        form_card.body.addWidget(self.message)
        form_card.body.addStretch()
        body.addWidget(form_card, 2)

        # --- O'ng: topilgan talabgor ---
        self.result_card = Card("Talabgor")
        result_row = QHBoxLayout()
        result_row.setSpacing(20)

        self.photo = PhotoView()
        result_row.addWidget(self.photo, 0, Qt.AlignmentFlag.AlignTop)

        fields = QGridLayout()
        fields.setVerticalSpacing(10)
        fields.setHorizontalSpacing(14)
        self._value_labels = {}
        for row, (key, caption) in enumerate(
            [
                ("full_name", "F.I.Sh."),
                ("masked_pinfl", "JSHSHIR"),
                ("external_candidate_id", "Tashqi ID"),
                ("platform_status", "Platforma holati"),
            ]
        ):
            caption_label = QLabel(caption)
            caption_label.setProperty("role", "field")
            value_label = QLabel("-")
            value_label.setProperty("role", "value")
            value_label.setWordWrap(True)
            fields.addWidget(caption_label, row, 0)
            fields.addWidget(value_label, row, 1)
            self._value_labels[key] = value_label

        self.reference_badge = QLabel("")
        self.reference_badge.setFixedHeight(24)
        fields.addWidget(self.reference_badge, 4, 1)

        result_row.addLayout(fields, 1)
        self.result_card.body.addLayout(result_row)

        self.next_btn = QPushButton("YUZNI TEKSHIRISHGA O'TISH")
        self.next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_btn.setStyleSheet(primary_button_style(52))
        self.next_btn.clicked.connect(self._on_next)
        self.result_card.body.addSpacing(6)
        self.result_card.body.addWidget(self.next_btn)
        self.result_card.body.addStretch()

        body.addWidget(self.result_card, 3)
        root.addLayout(body)

        self.result_card.setVisible(False)
        self.overlay = BusyOverlay(self)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.overlay.setGeometry(self.rect())

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """Yangi talabgor uchun sahifani tozalaydi."""
        exam = self._state.selected_exam
        staff = self._state.staff
        self.header.set_context(
            "{} - {}".format(
                exam.name if exam else "-", staff.full_name if staff else ""
            )
        )
        self.pinfl_input.clear()
        self.message.clear_message()
        self.result_card.setVisible(False)
        self.pinfl_input.setFocus()

    # ------------------------------------------------------------------
    def _on_pinfl_changed(self, text: str) -> None:
        # Faqat raqam: klaviaturadan tasodifiy belgi tushsa, so'rov
        # backendgacha bormaydi va throttle byudjeti isrof bo'lmaydi.
        digits = "".join(char for char in text if char.isdigit())
        if digits != text:
            self.pinfl_input.blockSignals(True)
            self.pinfl_input.setText(digits)
            self.pinfl_input.blockSignals(False)
        self.lookup_btn.setEnabled(len(digits) == PINFL_LENGTH)

    def _on_lookup(self) -> None:
        pinfl = self.pinfl_input.text().strip()
        exam = self._state.selected_exam
        if len(pinfl) != PINFL_LENGTH:
            self.message.show_message("JSHSHIR 14 xonali bo'lishi kerak")
            return
        if exam is None:
            self.message.show_message("Avval imtihonni tanlang")
            return

        self._state.reset_flow()
        self.result_card.setVisible(False)
        self.message.clear_message()
        self.overlay.start("Test platformasidan so'ralmoqda...")
        self.lookup_btn.setEnabled(False)

        worker = ApiWorker(
            self._repo.lookup_candidate, pinfl=pinfl, exam_id=exam.id, parent=self
        )
        worker.succeeded.connect(self._on_found)
        worker.failed.connect(self._on_failed)
        self._workers.run(worker)

    def _on_found(self, payload) -> None:
        self.overlay.stop()
        self.lookup_btn.setEnabled(True)

        candidate = Candidate.from_api(payload or {})
        self._state.candidate = candidate

        self._value_labels["full_name"].setText(candidate.full_name or "-")
        self._value_labels["masked_pinfl"].setText(candidate.masked_pinfl or "-")
        self._value_labels["external_candidate_id"].setText(
            candidate.external_candidate_id or "-"
        )
        self._value_labels["platform_status"].setText(candidate.platform_status or "-")

        has_photo = self._load_photo(candidate)
        if has_photo:
            self.reference_badge.setText("Hujjat rasmi mavjud")
            self.reference_badge.setStyleSheet(badge_style("success"))
        else:
            # Etalonsiz oqim to'xtamaydi: FaceID bu holatda yuzni QAYD
            # etadi (enrollment), shaxs tasdig'i esa operatorning hujjat
            # tekshiruvi zimmasida qoladi - backend mantig'i ham shunday.
            self.reference_badge.setText("Hujjat rasmi yo'q - operator tasdiqlaydi")
            self.reference_badge.setStyleSheet(badge_style("warning"))

        self.result_card.setVisible(True)
        self.message.show_message("Talabgor topildi", "success")

    def _load_photo(self, candidate: Candidate) -> bool:
        if not candidate.photo_base64:
            self.photo.set_image_bytes(b"")
            return False
        try:
            raw = base64.b64decode(candidate.photo_base64, validate=False)
        except (binascii.Error, ValueError):
            log.warning("Etalon rasm base64 emas")
            self.photo.set_image_bytes(b"")
            return False
        return self.photo.set_image_bytes(raw)

    def _on_failed(self, message: str, code: str) -> None:
        self.overlay.stop()
        self.lookup_btn.setEnabled(True)
        self.result_card.setVisible(False)

        # `candidate_not_eligible` - normal ish holati, xato emas:
        # talabgor shu testga ro'yxatdan o'tmagan.
        if code == "candidate_not_eligible":
            self.message.show_message("Test topshirish mumkin emas", "warning")
            return
        self.message.show_message(message, "error")

    def _on_next(self) -> None:
        if self._state.candidate is None:
            return
        self.candidate_ready.emit(self._state.candidate)

    def shutdown(self) -> None:
        self._workers.wait_all()
