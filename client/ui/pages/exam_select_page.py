"""
2-SAHIFA - Test turi va testni tanlash.

Ro'yxat backenddan handshake bilan keladi (`AppState.exams`), shuning
uchun bu sahifada tarmoq chaqiruvi YO'Q - tanlov darhol ishlaydi.

Ikki select zanjirli: tur tanlanmaguncha ikkinchisi bo'sh. Sabab
admin paneldagi bilan bir xil (`camerasOfZone`): mumkin bo'lmagan
kombinatsiyani umuman ko'rsatmaslik, keyin xato bermaslik.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from services.app_state import AppState, ExamOption
from ui.styles import COLORS, badge_style, primary_button_style
from ui.widgets.header import PageHeader
from ui.widgets.indicators import Card, MessageBar


class ExamSelectPage(QWidget):
    """Imtihon tanlash."""

    exam_selected = pyqtSignal(object)  # ExamOption
    logout_requested = pyqtSignal()

    def __init__(self, state: AppState, parent=None) -> None:
        super().__init__(parent)
        self._state = state
        self._setup_ui()

    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 32, 48, 36)
        root.setSpacing(22)

        self.header = PageHeader(
            "Imtihonni tanlang",
            "Talabgor topshiradigan test turi va testni belgilang",
            step=1,
        )
        self.header.logout_requested.connect(self.logout_requested.emit)
        root.addWidget(self.header)

        body = QHBoxLayout()
        body.setSpacing(22)

        # --- Chap: tanlov formasi ---
        form_card = Card("Test ma'lumotlari")
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)

        type_label = QLabel("Test turi")
        type_label.setProperty("role", "field")
        self.type_combo = QComboBox()
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)

        exam_label = QLabel("Test")
        exam_label.setProperty("role", "field")
        self.exam_combo = QComboBox()
        self.exam_combo.currentIndexChanged.connect(self._on_exam_changed)

        grid.addWidget(type_label, 0, 0)
        grid.addWidget(self.type_combo, 1, 0)
        grid.addWidget(exam_label, 0, 1)
        grid.addWidget(self.exam_combo, 1, 1)
        form_card.body.addLayout(grid)

        self.message = MessageBar()
        form_card.body.addWidget(self.message)

        self.continue_btn = QPushButton("DAVOM ETISH")
        self.continue_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.continue_btn.setStyleSheet(primary_button_style(52))
        self.continue_btn.clicked.connect(self._on_continue)
        form_card.body.addSpacing(6)
        form_card.body.addWidget(self.continue_btn)
        form_card.body.addStretch()

        body.addWidget(form_card, 3)

        # --- O'ng: ish o'rni holati ---
        info_card = Card("Ish o'rni")
        self.workstation_label = QLabel("-")
        self.workstation_label.setProperty("role", "value")
        self.zone_label = QLabel("-")
        self.zone_label.setProperty("role", "caption")
        info_card.body.addWidget(self.workstation_label)
        info_card.body.addWidget(self.zone_label)

        cameras_title = QLabel("Kuzatuv kameralari")
        cameras_title.setProperty("role", "field")
        info_card.body.addSpacing(8)
        info_card.body.addWidget(cameras_title)

        self.cameras_box = QVBoxLayout()
        self.cameras_box.setSpacing(6)
        info_card.body.addLayout(self.cameras_box)
        info_card.body.addStretch()

        body.addWidget(info_card, 2)
        root.addLayout(body)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """Handshake'dan keyin chaqiriladi - ro'yxatlarni to'ldiradi."""
        staff = self._state.staff
        device = self._state.device

        self.header.set_context(
            "{} - {}".format(device.zone_name or "bino noma'lum",
                             staff.full_name if staff else "")
        )
        self.workstation_label.setText(device.inventory_code or "Kompyuter aniqlanmadi")
        self.zone_label.setText(
            "{} - {}".format(
                device.zone_name or "-",
                staff.region_name if staff and staff.region_name else "",
            ).strip(" -")
        )
        self._render_cameras()

        self.type_combo.blockSignals(True)
        self.type_combo.clear()
        types = self._state.exam_types()
        if not types:
            self.type_combo.addItem("Bugun uchun imtihon yo'q", None)
            self.type_combo.setEnabled(False)
            self.exam_combo.setEnabled(False)
            self.continue_btn.setEnabled(False)
            self.message.show_message(
                "Bugungi sanaga imtihon jadvali tuzilmagan yoki barcha "
                "imtihonlar yopiq.",
                "warning",
            )
        else:
            self.type_combo.setEnabled(True)
            self.exam_combo.setEnabled(True)
            for type_id, type_name in types:
                self.type_combo.addItem(type_name, type_id)
            self.message.clear_message()
        self.type_combo.blockSignals(False)
        self._on_type_changed()

    def _render_cameras(self) -> None:
        while self.cameras_box.count():
            item = self.cameras_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        cameras = self._state.device.cameras
        if not cameras:
            empty = QLabel("Bu kompyuterga kamera biriktirilmagan")
            empty.setProperty("role", "caption")
            self.cameras_box.addWidget(empty)
            return

        for camera in cameras:
            row = QHBoxLayout()
            name = QLabel("{} ({})".format(camera.get("name", "-"), camera.get("ip_address", "-")))
            name.setStyleSheet("font-size: 13px; color: {};".format(COLORS["text_secondary"]))
            status = QLabel("Onlayn" if camera.get("status") == "online" else "Oflayn")
            status.setStyleSheet(
                badge_style("success" if camera.get("status") == "online" else "error")
            )
            status.setFixedHeight(22)
            row.addWidget(name)
            row.addStretch()
            row.addWidget(status)
            container = QWidget()
            container.setLayout(row)
            self.cameras_box.addWidget(container)

    # ------------------------------------------------------------------
    def _on_type_changed(self) -> None:
        type_id = self.type_combo.currentData()
        self.exam_combo.blockSignals(True)
        self.exam_combo.clear()
        exams = self._state.exams_of_type(type_id)
        for exam in exams:
            # Yopiq imtihon ham ko'rsatiladi, lekin tanlab bo'lmaydi -
            # operator "nega ro'yxatda yo'q" deb qidirmasligi uchun.
            suffix = "" if exam.is_open else "  (kirish oynasi yopiq)"
            self.exam_combo.addItem(exam.name + suffix, exam)
        self.exam_combo.blockSignals(False)
        self._on_exam_changed()

    def _on_exam_changed(self) -> None:
        exam = self.exam_combo.currentData()
        is_open = bool(exam and exam.is_open)
        self.continue_btn.setEnabled(is_open)
        if exam and not exam.is_open:
            self.message.show_message(
                "Bu imtihonning kirish oynasi hozir yopiq.", "warning"
            )
        elif exam:
            self.message.clear_message()

    def _on_continue(self) -> None:
        exam: ExamOption = self.exam_combo.currentData()
        if exam is None:
            self.message.show_message("Testni tanlang")
            return
        self._state.selected_exam = exam
        self.exam_selected.emit(exam)
