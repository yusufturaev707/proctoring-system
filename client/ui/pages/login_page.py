"""
1-SAHIFA - Login.

Ikki narsa PARALLEL ketadi:
  * operator login/parol kiritadi;
  * fon thread'ida InsightFace modeli yuklanadi (~5-15 s CPU'da).

Shuning uchun model holati formani BLOKLAMAYDI - u faqat pastki chap
burchakdagi indikatorda ko'rinadi. Model faqat 4-sahifada (FaceID)
kerak, o'sha yergacha u deyarli har doim tayyor bo'ladi.

Login muvaffaqiyatli bo'lgach shu yerdayoq `handshake` chaqiriladi:
usiz kompyuter qaysi binoda ekani, qanday kameralar biriktirilgani va
bugun qanday imtihonlar borligi noma'lum.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from config import APP_VERSION
from services.app_state import Staff
from services.auth_service import AuthService
from services.workers import ApiWorker, WorkerHolder
from ui.styles import COLORS, primary_button_style
from ui.widgets.backdrop import BrandBackdrop
from ui.widgets.indicators import MessageBar, StatusPill

log = logging.getLogger(__name__)


class LoginPage(BrandBackdrop):
    """Kirish sahifasi."""

    #: (staff) - login VA handshake muvaffaqiyatli tugadi.
    login_success = pyqtSignal(object)

    def __init__(self, auth: AuthService, parent=None) -> None:
        super().__init__(parent)
        self._auth = auth
        self._workers = WorkerHolder()
        self._busy = False
        self._setup_ui()

    # ------------------------------------------------------------------
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Indikator layout'ga kirmaydi - u burchakka "yopishtirilgan".
        pill = self._status_pill
        pill.setGeometry(24, self.height() - pill.height() - 24, 260, pill.height())
        button = self._model_retry_btn
        button.setGeometry(
            24 + 260 + 8, self.height() - pill.height() - 24,
            button.sizeHint().width(), pill.height(),
        )

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # "Chiqish" TUGMASI YO'Q va bu ataylab.
        #
        # Login sahifasidan boshlab dasturdan chiqishning yagona yo'li -
        # Ctrl+Q va parol. Ko'rinadigan tugma bu yerda ikki jihatdan
        # zarar: u talabgorga "chiqish mumkin" degan taklif beradi va
        # tasodifan bosilishi mumkin. Klaviatura kombinatsiyasi esa
        # ataylab qilingan harakat.
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 22, 28, 0)
        top_bar.addStretch()
        outer.addLayout(top_bar)
        outer.addStretch()

        # Logotip KARTA USTIDA, uning ichida emas: karta — forma, belgi
        # esa butun ekranniki. Balandlik oynaga qarab o'zgaradi
        # (`BrandBackdrop.resizeEvent`).
        outer.addWidget(self.make_logo(), alignment=Qt.AlignmentFlag.AlignCenter)
        outer.addSpacing(26)

        card = QFrame()
        card.setObjectName("loginCard")
        card.setFixedWidth(460)
        # MD3: ramkasiz, 28 px ("extra large") - dialoglar bilan bir shakl.
        card.setStyleSheet(
            """
            QFrame#loginCard {
                background-color: %s;
                border-radius: 28px;
                border: none;
            }
            """
            % COLORS["surface_container_lowest"]
        )
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(70)
        shadow.setOffset(0, 18)
        shadow.setColor(QColor(0, 0, 0, 150))
        card.setGraphicsEffect(shadow)
        self._card = card

        layout = QVBoxLayout(card)
        layout.setContentsMargins(42, 38, 42, 30)
        layout.setSpacing(0)

        mark = QLabel("PROCTORING")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        mark.setStyleSheet(
            "color: {}; letter-spacing: 3px; background: transparent;".format(COLORS["primary"])
        )
        layout.addWidget(mark)
        layout.addSpacing(6)

        title = QLabel("Imtihon nazorati")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        # O'lcham USLUBDA ham: global `QWidget { font-size: 15px }` qoidasi
        # `setFont` dan ustun va sarlavha oddiy matn o'lchamiga tushib
        # qolardi (`dialogs.base.apply_font` izohi).
        title.setStyleSheet(
            "color: {}; background: transparent; font-size: 26px; font-weight: 700;".format(
                COLORS["text"]
            )
        )
        layout.addWidget(title)
        layout.addSpacing(4)

        subtitle = QLabel("Operator ish o'rni")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(
            "color: {}; background: transparent; font-size: 14px;".format(COLORS["text_secondary"])
        )
        layout.addWidget(subtitle)
        layout.addSpacing(26)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Foydalanuvchi nomi")
        self.username_input.setFixedHeight(52)
        layout.addWidget(self.username_input)
        layout.addSpacing(12)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Parol")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setFixedHeight(52)
        layout.addWidget(self.password_input)
        layout.addSpacing(20)

        self.login_btn = QPushButton("KIRISH")
        self.login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_btn.setStyleSheet(primary_button_style(52))
        self.login_btn.clicked.connect(self._on_login)
        layout.addWidget(self.login_btn)
        layout.addSpacing(14)

        self.message = MessageBar()
        layout.addWidget(self.message)

        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)
        outer.addSpacing(12)

        version = QLabel("v{}".format(APP_VERSION))
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version.setStyleSheet("color: rgba(255,255,255,0.45); background: transparent;")
        # Yagona chiqish yo'li ko'rinmas bo'lib qolmasligi kerak:
        # tugma olib tashlangani bilan operator uni qayerdadir
        # o'qigan bo'lishi shart.
        outer.addWidget(version, alignment=Qt.AlignmentFlag.AlignCenter)

        # Preflight aniqlagan bino/manzil. Login'dan OLDIN ma'lum
        # bo'ladi, shuning uchun shu yerda ko'rsatiladi: noto'g'ri bino
        # biriktirilgani imtihon boshlangunga qadar sezilishi kerak.
        self._network_label = QLabel("")
        self._network_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._network_label.setStyleSheet(
            "color: rgba(255,255,255,0.55); background: transparent; font-size: 12px;"
        )
        self._network_label.hide()
        outer.addWidget(self._network_label, alignment=Qt.AlignmentFlag.AlignCenter)
        outer.addStretch()

        self._status_pill = StatusPill(self)
        self._status_pill.raise_()

        # Model yuklanmasa — QAYTA URINISH shu yerda, login'dan oldin.
        # Operator muammoni talabgor kelmasdan ko'radi va hal qiladi
        # (masalan boshqa dasturlarni yopib, xotira bo'shatib).
        # Tugmasiz yagona yo'l dasturni qayta ishga tushirish edi.
        self._model_retry_btn = QPushButton("Qayta yuklash", self)
        self._model_retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._model_retry_btn.setStyleSheet(
            "QPushButton { color: white; background: rgba(255,255,255,0.14);"
            " border: 1px solid rgba(255,255,255,0.35); border-radius: 17px;"
            " padding: 0 14px; font-weight: 600; }"
            "QPushButton:hover { background: rgba(255,255,255,0.24); }"
        )
        self._model_retry_btn.clicked.connect(self._on_model_retry)
        self._model_retry_btn.hide()

        # Enter bilan o'tish: login -> parol -> kirish.
        self.username_input.returnPressed.connect(self.password_input.setFocus)
        self.password_input.returnPressed.connect(self._on_login)

    # ------------------------------------------------------------------
    # Tarmoq holati (preflight natijasi)
    # ------------------------------------------------------------------
    def set_network_info(self, result: dict) -> None:
        """Preflight qaytargan bino va tashqi manzilni ko'rsatadi."""
        parts = []
        zone = (result or {}).get("zone") or {}
        region = (result or {}).get("region") or {}
        if zone.get("name"):
            parts.append(zone["name"])
        if region.get("name"):
            parts.append(region["name"])
        # if (result or {}).get("public_ip"):
        #     parts.append(result["public_ip"])
        text = "  ·  ".join(parts)
        self._network_label.setText(text)
        self._network_label.setVisible(bool(text))

    # ------------------------------------------------------------------
    # Model holati (MainWindow'dan)
    # ------------------------------------------------------------------
    def set_model_status(self, text: str, *, ready: bool = False, failed: bool = False) -> None:
        if failed:
            # SABAB ko'rinadi: "fayl topilmadi", "buzilgan", "xotira
            # yetmadi", "DLL yuklanmadi" — har biriga boshqa chora.
            # To'liq matn tooltip'da (indikator tor).
            title = "Model yuklanmadi"
            try:
                from services.face_engine import FaceEngine

                problem = FaceEngine().problem
                if problem is not None:
                    title = problem.title
            except Exception:
                log.debug("Model xatosi sababi o'qilmadi", exc_info=True)
            self._status_pill.set_state("error", title)
            self._status_pill.setToolTip(text or title)
            self._model_retry_btn.show()
            self._model_retry_btn.raise_()
        elif ready:
            self._status_pill.set_state("ready", "Tizim tayyor")
            self._status_pill.setToolTip(text or "")
            self._model_retry_btn.hide()
        else:
            self._status_pill.set_state("loading", text or "Tizim tayyorlanmoqda...")
            self._status_pill.setToolTip("")
            self._model_retry_btn.hide()

    def _on_model_retry(self) -> None:
        """Modelni qayta yuklash (`face_engine.start_model_loading`)."""
        from services.face_engine import start_model_loading

        self._model_retry_btn.hide()
        try:
            loader = start_model_loading()
        except Exception:
            log.exception("Modelni qayta yuklashni boshlab bo'lmadi")
            self._model_retry_btn.show()
            return
        if loader is None:
            self.set_model_status("", ready=True)
            return
        self.set_model_status("Model qayta yuklanmoqda...")
        loader.progress.connect(lambda message: self.set_model_status(message))
        loader.finished_loading.connect(
            lambda success, message: self.set_model_status(
                message, ready=success, failed=not success
            )
        )

    # ------------------------------------------------------------------
    # Login oqimi
    # ------------------------------------------------------------------
    def _on_login(self) -> None:
        if self._busy:
            return
        username = self.username_input.text().strip()
        password = self.password_input.text()
        if not username or not password:
            self.message.show_message("Login va parolni kiriting")
            return

        self._set_busy(True, "Tekshirilmoqda...")
        worker = ApiWorker(self._login_flow, username, password, parent=self)
        worker.succeeded.connect(self._on_success)
        worker.failed.connect(self._on_failed)
        self._workers.run(worker)

    def _login_flow(self, username: str, password: str) -> Staff:
        """
        Fon thread'ida bajariladigan ketma-ketlik.

        Login va handshake BITTA vazifada: ular alohida bo'lsa, oraliqda
        "kirdim, lekin imtihon ro'yxati yo'q" degan yarim holat paydo
        bo'ladi va uni UI'da alohida ishlash kerak bo'lardi.
        """
        staff = self._auth.login(username, password)
        self._auth.handshake()
        return staff

    def _on_success(self, staff) -> None:
        self._set_busy(False)
        device = self._auth.state.device
        if not device.is_active:
            # Qurilma PENDING/REVOKED - backend baribir hech narsaga
            # ruxsat bermaydi, shuning uchun oqimni shu yerda to'xtatamiz.
            self.message.show_message(
                "Qurilma tasdiqlanmagan (holat: {}). Administrator "
                "tasdiqlashini kuting.".format(device.status),
                "warning",
            )
            return
        self.password_input.clear()
        self.message.clear_message()
        self.login_success.emit(staff)

    def _on_failed(self, message: str, code: str) -> None:
        self._set_busy(False)
        kind = "warning" if code in ("device_not_registered", "throttled") else "error"
        self.message.show_message(message, kind)
        log.info("Login muvaffaqiyatsiz (%s): %s", code or "-", message)

    def _set_busy(self, busy: bool, text: str = "") -> None:
        self._busy = busy
        self.login_btn.setEnabled(not busy)
        self.username_input.setEnabled(not busy)
        self.password_input.setEnabled(not busy)
        self.login_btn.setText(text if busy else "KIRISH")
        if busy:
            self.message.clear_message()

    # ------------------------------------------------------------------
    def reset(self, message: str = "") -> None:
        """Logout'dan keyin sahifani tozalaydi."""
        self.username_input.clear()
        self.password_input.clear()
        self._set_busy(False)
        if message:
            self.message.show_message(message, "warning")
        else:
            self.message.clear_message()
        self.username_input.setFocus()

    def shutdown(self) -> None:
        self._workers.wait_all()
