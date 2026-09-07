"""
4-SAHIFA - FaceID tekshiruvi.

Oqim:
  1. Kamera ochiladi (alohida thread).
  2. Pasport rasmidan etalon embedding olinadi (bu ham fon thread'ida -
     InsightFace chaqiruvi ~200 ms, UI thread'da qilinsa oyna sakraydi).
  3. Har kadr uchun cosine similarity hisoblanadi.
  4. Ketma-ket `FACE_MATCH_STREAK` kadr chegaradan yuqori bo'lsa -
     tasdiqlangan. Bitta kadr yetarli emas: bitta muvaffaqiyatli rakurs
     tasodif bo'lishi mumkin, ketma-ketlik esa yo'q.
  5. Backendga `face/verify/` yuboriladi -> sessiya ochiladi.
  6. Darhol `exam/access/` sinaladi. `identity_not_confirmed` qaytsa -
     operator hujjat ma'lumotini kiritadi va tasdiqlaydi.

Etalon rasm bo'lmasa (tashqi platforma bermagan), solishtirish o'rniga
ENROLLMENT rejimi ishlaydi: yuz sifatli aniqlangani yetarli, qaror esa
operatorning hujjat tekshiruviga qoladi. Bu backend mantig'i bilan bir
xil - `has_reference_face=False` holati.
"""

from __future__ import annotations

import base64
import binascii
import logging
from typing import Optional

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config import FACE_MATCH_STREAK
from services.app_state import AppState, ProctoringSession
from services.camera_worker import CameraWorker, retire_camera
from services.face_engine import FaceEngine, cosine_to_percent
from services.repositories import ProctoringRepository
from services.workers import ApiWorker, WorkerHolder
from ui.styles import COLORS, badge_style, primary_button_style
from ui.widgets.camera_view import CameraView, PhotoView
from ui.widgets.header import PageHeader
from ui.widgets.indicators import BusyOverlay, Card, MessageBar

log = logging.getLogger(__name__)

DOCUMENT_TYPES = [
    ("passport", "Pasport"),
    ("id_card", "ID karta"),
    ("birth_certificate", "Tug'ilganlik guvohnomasi"),
    ("driver_license", "Haydovchilik guvohnomasi"),
    ("other", "Boshqa"),
]


class FaceIDPage(QWidget):
    """Yuzni real vaqtda solishtirish va sessiyani ochish."""

    #: Imtihonga kirish ma'lumoti tayyor (`exam/access/` javobi).
    access_granted = pyqtSignal(object)
    back_requested = pyqtSignal()
    logout_requested = pyqtSignal()

    def __init__(self, state: AppState, repo: ProctoringRepository, parent=None) -> None:
        super().__init__(parent)
        self._state = state
        self._repo = repo
        self._workers = WorkerHolder()
        self._camera: Optional[CameraWorker] = None
        self._engine = FaceEngine()

        self._reference: Optional[np.ndarray] = None
        self._reference_ready = False
        self._streak = 0
        self._best_score = 0
        self._verifying = False
        self._verified = False
        self._last_embedding: Optional[np.ndarray] = None

        self._setup_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 32, 48, 36)
        root.setSpacing(22)

        self.header = PageHeader(
            "Yuzni tekshirish",
            "Talabgor kameraga qarasin",
            step=3,
            show_back=True,
        )
        self.header.logout_requested.connect(self.logout_requested.emit)
        self.header.back_requested.connect(self.back_requested.emit)
        root.addWidget(self.header)

        body = QHBoxLayout()
        body.setSpacing(22)

        # --- Chap: kamera ---
        camera_card = Card()
        self.camera_view = CameraView()
        camera_card.body.addWidget(self.camera_view)

        status_row = QHBoxLayout()
        self.state_badge = QLabel("Kamera ishga tushmoqda")
        self.state_badge.setStyleSheet(badge_style("muted"))
        self.state_badge.setFixedHeight(24)
        self.score_label = QLabel("O'xshashlik: -")
        self.score_label.setProperty("role", "caption")
        status_row.addWidget(self.state_badge)
        status_row.addStretch()
        status_row.addWidget(self.score_label)
        camera_card.body.addLayout(status_row)
        body.addWidget(camera_card, 3)

        # --- O'ng: talabgor va tasdiq ---
        side = QVBoxLayout()
        side.setSpacing(18)

        candidate_card = Card("Talabgor")
        row = QHBoxLayout()
        row.setSpacing(16)
        self.photo = PhotoView()
        self.photo.setFixedSize(150, 190)
        row.addWidget(self.photo, 0, Qt.AlignmentFlag.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(4)
        self.name_label = QLabel("-")
        self.name_label.setProperty("role", "value")
        self.name_label.setWordWrap(True)
        self.pinfl_label = QLabel("-")
        self.pinfl_label.setProperty("role", "caption")
        self.mode_badge = QLabel("")
        self.mode_badge.setFixedHeight(24)
        info.addWidget(self.name_label)
        info.addWidget(self.pinfl_label)
        info.addSpacing(6)
        info.addWidget(self.mode_badge)
        info.addStretch()
        row.addLayout(info, 1)
        candidate_card.body.addLayout(row)
        side.addWidget(candidate_card)

        # Hujjat tasdig'i - faqat backend so'raganda ko'rinadi.
        self.identity_card = Card("Shaxsni tasdiqlash")
        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        grid.setHorizontalSpacing(12)

        type_label = QLabel("Hujjat turi")
        type_label.setProperty("role", "field")
        self.document_type = QComboBox()
        for value, caption in DOCUMENT_TYPES:
            self.document_type.addItem(caption, value)

        number_label = QLabel("Hujjat raqami")
        number_label.setProperty("role", "field")
        self.document_number = QLineEdit()
        self.document_number.setPlaceholderText("AA1234567")

        grid.addWidget(type_label, 0, 0)
        grid.addWidget(self.document_type, 1, 0)
        grid.addWidget(number_label, 0, 1)
        grid.addWidget(self.document_number, 1, 1)
        self.identity_card.body.addLayout(grid)

        buttons = QHBoxLayout()
        self.reject_btn = QPushButton("Rad etish")
        self.reject_btn.setProperty("variant", "danger")
        self.reject_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reject_btn.clicked.connect(self._on_reject)
        self.confirm_btn = QPushButton("Tasdiqlash va boshlash")
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_btn.setStyleSheet(primary_button_style(48))
        self.confirm_btn.clicked.connect(self._on_confirm_identity)
        buttons.addWidget(self.reject_btn)
        buttons.addWidget(self.confirm_btn, 1)
        self.identity_card.body.addLayout(buttons)
        self.identity_card.setVisible(False)
        side.addWidget(self.identity_card)

        self.message = MessageBar()
        side.addWidget(self.message)

        self.retry_btn = QPushButton("Qaytadan urinish")
        self.retry_btn.setProperty("variant", "ghost")
        self.retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.retry_btn.clicked.connect(self.restart_matching)
        self.retry_btn.setVisible(False)
        side.addWidget(self.retry_btn)
        side.addStretch()

        body.addLayout(side, 2)
        root.addLayout(body)

        self.overlay = BusyOverlay(self)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.overlay.setGeometry(self.rect())

    # ------------------------------------------------------------------
    # Hayot sikli
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Sahifaga kirilganda: kamera + etalon."""
        candidate = self._state.candidate
        staff = self._state.staff
        if candidate is None:
            return

        self.header.set_context(
            "{} - {}".format(
                self._state.selected_exam.name if self._state.selected_exam else "-",
                staff.full_name if staff else "",
            )
        )
        self.name_label.setText(candidate.full_name or "-")
        self.pinfl_label.setText(candidate.masked_pinfl or "-")
        self._load_photo(candidate.photo_base64)

        self._reset_matching_state()
        self.identity_card.setVisible(False)
        self.retry_btn.setVisible(False)
        self.message.clear_message()

        if not self._engine.is_ready:
            self.message.show_message(
                "Yuz aniqlash modeli hali yuklanmoqda. Bir necha soniya kuting.",
                "warning",
            )

        self._start_camera()
        self._prepare_reference(candidate.photo_base64)

    def cleanup(self) -> None:
        """Kamerani to'xtatadi. Sahifadan chiqishda MAJBURIY."""
        retire_camera(self._camera)
        self._camera = None
        self.camera_view.clear_view()

    def take_camera(self) -> Optional[CameraWorker]:
        """
        Kamerani keyingi sahifaga UZATADI (davriy FaceID uchun).

        Kamerani yopib qayta ochish Windows'da 2-4 soniya oladi va shu
        vaqt ichida talabgor kuzatuvsiz qoladi. Shuning uchun worker
        to'xtatilmaydi - egalik WebView sahifasiga o'tadi.
        """
        camera = self._camera
        if camera is not None:
            try:
                camera.frame_ready.disconnect(self._on_frame)
                camera.face_result.disconnect(self._on_face)
                camera.camera_error.disconnect(self._on_camera_error)
            except TypeError:
                pass
        self._camera = None
        return camera

    def _start_camera(self) -> None:
        if self._camera is not None:
            return
        # PARENT BERILMAYDI: Qt ota-obyekt yo'q qilinganda bolalarini ham
        # yo'q qiladi, ishlab turgan QThread yo'q qilinsa esa dastur
        # qulaydi. Egalik Python referensi orqali boshqariladi
        # (`retire_camera` ga qarang).
        self._camera = CameraWorker()
        self._camera.frame_ready.connect(self._on_frame)
        self._camera.face_result.connect(self._on_face)
        self._camera.camera_error.connect(self._on_camera_error)
        self._camera.start()

    # ------------------------------------------------------------------
    # Etalon
    # ------------------------------------------------------------------
    def _load_photo(self, photo_base64: str) -> None:
        if not photo_base64:
            self.photo.set_image_bytes(b"")
            return
        try:
            self.photo.set_image_bytes(base64.b64decode(photo_base64, validate=False))
        except (binascii.Error, ValueError):
            self.photo.set_image_bytes(b"")

    def _prepare_reference(self, photo_base64: str) -> None:
        """Etalon embedding - fon thread'ida (model chaqiruvi bloklovchi)."""
        self._reference = None
        self._reference_ready = False
        if not photo_base64:
            self._reference_ready = True
            self._set_mode_badge(False)
            return

        self._set_mode_badge(None)
        worker = ApiWorker(self._engine.embed_base64, photo_base64, parent=self)
        worker.succeeded.connect(self._on_reference_ready)
        worker.failed.connect(lambda message, code: self._on_reference_ready(None))
        self._workers.run(worker)

    def _on_reference_ready(self, embedding) -> None:
        self._reference = embedding if isinstance(embedding, np.ndarray) else None
        self._reference_ready = True
        self._set_mode_badge(self._reference is not None)
        if self._reference is None:
            self.message.show_message(
                "Hujjat rasmidan yuz olinmadi - tekshiruv operator zimmasida.",
                "warning",
            )

    def _set_mode_badge(self, has_reference: Optional[bool]) -> None:
        if has_reference is None:
            self.mode_badge.setText("Etalon tayyorlanmoqda...")
            self.mode_badge.setStyleSheet(badge_style("muted"))
        elif has_reference:
            self.mode_badge.setText("Hujjat rasmi bilan solishtiriladi")
            self.mode_badge.setStyleSheet(badge_style("info"))
        else:
            self.mode_badge.setText("Etalonsiz rejim - yuz qayd etiladi")
            self.mode_badge.setStyleSheet(badge_style("warning"))

    # ------------------------------------------------------------------
    # Kadr oqimi
    # ------------------------------------------------------------------
    def _on_frame(self, frame) -> None:
        self.camera_view.set_frame(frame)

    def _on_camera_error(self, message: str) -> None:
        self.message.show_message(message, "error")
        self.state_badge.setText("Kamera xatosi")
        self.state_badge.setStyleSheet(badge_style("error"))

    def _on_face(self, result: dict) -> None:
        if self._verifying or self._verified:
            return

        state = result.get("state")
        bboxes = result.get("bboxes") or []

        if state != "ok":
            self._streak = 0
            self.camera_view.set_detection(state, bboxes)
            self._update_state_badge(state)
            return

        embedding = result.get("embedding")
        self._last_embedding = embedding

        if not self._reference_ready:
            self.camera_view.set_detection("ok", bboxes)
            self._update_state_badge("waiting_reference")
            return

        if self._reference is None:
            # Enrollment: solishtirish yo'q, sifatli kadr yetarli.
            self._streak += 1
            self.camera_view.set_detection("ok", bboxes)
            self._update_state_badge("enroll")
            if self._streak >= FACE_MATCH_STREAK:
                self._submit_face(embedding, score=None)
            return

        matched, similarity = self._engine.matches(self._reference, embedding)
        score = cosine_to_percent(similarity)
        self._best_score = max(self._best_score, score)
        self.score_label.setText("O'xshashlik: {}%".format(score))

        if matched:
            self._streak += 1
            self.camera_view.set_detection("match", bboxes, score)
            self._update_state_badge("match")
            if self._streak >= FACE_MATCH_STREAK:
                self._submit_face(embedding, score=score)
        else:
            self._streak = 0
            self.camera_view.set_detection("mismatch", bboxes, score)
            self._update_state_badge("mismatch")

    def _update_state_badge(self, state: str) -> None:
        mapping = {
            "none": ("Yuz topilmadi", "muted"),
            "far": ("Yaqinroq keling", "warning"),
            "multiple": ("Kadrda bir nechta odam", "error"),
            "mismatch": ("Mos kelmadi ({}/{})".format(self._streak, FACE_MATCH_STREAK), "error"),
            "match": ("Mos keldi ({}/{})".format(self._streak, FACE_MATCH_STREAK), "success"),
            "enroll": ("Yuz qayd etilmoqda ({}/{})".format(self._streak, FACE_MATCH_STREAK), "info"),
            "waiting_reference": ("Etalon kutilmoqda", "muted"),
        }
        text, kind = mapping.get(state, ("Kutilmoqda", "muted"))
        self.state_badge.setText(text)
        self.state_badge.setStyleSheet(badge_style(kind))

    # ------------------------------------------------------------------
    # Backend
    # ------------------------------------------------------------------
    def _submit_face(self, embedding, score: Optional[int]) -> None:
        candidate = self._state.candidate
        if candidate is None or self._verifying:
            return
        self._verifying = True
        self.overlay.start("Sessiya ochilmoqda...")

        worker = ApiWorker(
            self._repo.verify_face,
            challenge=candidate.challenge,
            embedding=[float(value) for value in embedding],
            score=score,
            faces_detected=1,
            parent=self,
        )
        worker.succeeded.connect(self._on_session_created)
        worker.failed.connect(self._on_verify_failed)
        self._workers.run(worker)

    def _on_session_created(self, payload) -> None:
        session = ProctoringSession.from_api(payload or {})
        self._state.session = session
        self._verified = True

        # Sessiya tokeni endi HAR SO'ROVGA qo'shiladi - `exam/access/`,
        # heartbeat va hodisalar aynan shu bilan ishlaydi.
        from services.api_client import ApiClient

        ApiClient().set_session_token(session.token)

        self.message.show_message("Tasdiqlandi", "success")
        self.state_badge.setText("Tasdiqlandi")
        self.state_badge.setStyleSheet(badge_style("success"))

        # Shaxs tasdig'i talab qilinmasa - to'g'ridan-to'g'ri imtihonga.
        # Talab qilinsa, backend `identity_not_confirmed` qaytaradi va
        # o'shanda hujjat formasi ochiladi.
        self._request_access()

    def _on_verify_failed(self, message: str, code: str) -> None:
        self._verifying = False
        self._streak = 0
        self.overlay.stop()
        self.message.show_message(message, "error")
        self.retry_btn.setVisible(True)
        log.info("FaceID rad etildi (%s): %s", code or "-", message)

    def _request_access(self) -> None:
        self.overlay.start("Imtihon ochilmoqda...")
        worker = ApiWorker(self._repo.exam_access, parent=self)
        worker.succeeded.connect(self._on_access_granted)
        worker.failed.connect(self._on_access_failed)
        self._workers.run(worker)

    def _on_access_granted(self, payload) -> None:
        self.overlay.stop()
        self._state.exam_access = payload or {}
        self.access_granted.emit(self._state.exam_access)

    def _on_access_failed(self, message: str, code: str) -> None:
        self.overlay.stop()
        self._verifying = False
        if code == "identity_not_confirmed":
            # Kutilgan holat: operator hujjatni tekshirishi kerak.
            self.identity_card.setVisible(True)
            self.document_number.setFocus()
            self.message.show_message(
                "Yuz tasdiqlandi. Endi hujjatni tekshirib tasdiqlang.", "info"
            )
            return
        self.message.show_message(message, "error")
        self.retry_btn.setVisible(True)

    # ------------------------------------------------------------------
    # Operator qarori
    # ------------------------------------------------------------------
    def _on_confirm_identity(self) -> None:
        number = self.document_number.text().strip()
        if not number:
            self.message.show_message("Hujjat raqamini kiriting")
            return
        self.overlay.start("Tasdiqlanmoqda...")
        worker = ApiWorker(
            self._repo.confirm_identity,
            document_type=self.document_type.currentData(),
            document_number=number,
            parent=self,
        )
        worker.succeeded.connect(lambda _: self._on_identity_confirmed())
        worker.failed.connect(self._on_identity_failed)
        self._workers.run(worker)

    def _on_identity_confirmed(self) -> None:
        if self._state.session is not None:
            self._state.session.identity_confirmed = True
        self.identity_card.setVisible(False)
        self._request_access()

    def _on_identity_failed(self, message: str, code: str) -> None:
        self.overlay.stop()
        self.message.show_message(message, "error")

    def _on_reject(self) -> None:
        self.overlay.start("Rad etilmoqda...")
        worker = ApiWorker(
            self._repo.reject_identity,
            reason="Hujjat talabgorga mos kelmadi",
            parent=self,
        )
        worker.succeeded.connect(lambda _: self._on_rejected())
        worker.failed.connect(self._on_identity_failed)
        self._workers.run(worker)

    def _on_rejected(self) -> None:
        self.overlay.stop()
        self.identity_card.setVisible(False)
        self.message.show_message(
            "Shaxs tasdiqlanmadi - sessiya chetlashtirildi.", "error"
        )
        self.retry_btn.setText("Yangi talabgor")
        self.retry_btn.setVisible(True)
        # Sessiya tokeni endi yaroqsiz - keyingi so'rovlarga qo'shilmasin.
        from services.api_client import ApiClient

        ApiClient().set_session_token(None)

    # ------------------------------------------------------------------
    def restart_matching(self) -> None:
        """Qaytadan urinish: holat tozalanadi, kamera ishlab turaveradi."""
        if self._state.session is not None and not self._verified:
            self._state.session = None
        if self.retry_btn.text() == "Yangi talabgor":
            self.retry_btn.setText("Qaytadan urinish")
            self.back_requested.emit()
            return
        self._reset_matching_state()
        self.message.clear_message()
        self.retry_btn.setVisible(False)

    def _reset_matching_state(self) -> None:
        self._streak = 0
        self._best_score = 0
        self._verifying = False
        self._verified = False
        self._last_embedding = None
        self.score_label.setText("O'xshashlik: -")
        self.state_badge.setText("Kutilmoqda")
        self.state_badge.setStyleSheet(badge_style("muted"))

    def shutdown(self) -> None:
        self.cleanup()
        self._workers.wait_all()
