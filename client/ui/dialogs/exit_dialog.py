"""
Dasturdan chiqish dialogi.

Kiosk rejimida dasturni yopishning YAGONA yo'li shu dialog: oyna
ramkasiz, doim ustda va Alt+F4 bloklangan, `closeEvent` esa ruxsatsiz
yopilishni rad etadi.

PAROL DOIM SO'RALADI va server ikki xil kalitni qabul qiladi:

  * xodimning O'Z paroli (tizimga kirgan bo'lsa) - eng yaxshi holat:
    audit iziga ism yoziladi va bu umumiy sir emas;
  * VILOYATNING chiqish paroli (`controls.ClientExitPassword`) - dastur
    login sahifasida turganda yagona yo'l, chunki o'sha paytda hech
    qanday xodim tizimda yo'q.

Client bu farqni bilmaydi va bilishi shart emas: bitta maydon, bitta
so'rov. Qaysi kalit ishlagani serverda hal qilinadi va audit'ga
yoziladi - shu tarzda "kim yopdi" savoli javobsiz qolmaydi.

Referens loyihada (`safebrowserv1`) parol serverdan kelib client
xotirasida turardi va butun respublika uchun bitta edi. Bu yerda
solishtirish HAR DOIM serverda: client parolni na saqlaydi, na
biladi, ya'ni dastur xotirasini o'qish bilan uni olib bo'lmaydi.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from services.repositories import ProctoringRepository
from services.workers import ApiWorker, WorkerHolder
from ui.styles import COLORS, outlined_button_style
from ui.widgets.indicators import MessageBar, StateBadge

log = logging.getLogger(__name__)


def _apply_font(widget, size: int, *, bold: bool = False, extra: str = "") -> None:
    """
    Shrift ikki joyda: uslubda (chizish) va `setFont` da (o'lcham).

    `GLOBAL_STYLESHEET` da `QWidget { font-size: 15px }` qoidasi bor va
    Qt'da uslub `setFont` dan ustun turadi; uslubdagi `font-size` esa
    `sizeHint` ga har doim ham yetib bormaydi va matn kesiladi.
    Ikkalasi ham kerak (`ui/pages/preflight_page.py` dagi bilan bir xil).
    """
    font = QFont()
    font.setFamilies(["Segoe UI", "Inter", "Roboto"])
    font.setPixelSize(size)
    font.setWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
    widget.setFont(font)
    widget.setStyleSheet(
        "font-size: {}px; font-weight: {}; background: transparent; {}".format(
            size, 700 if bold else 400, extra
        )
    )
    widget.setMinimumHeight(QFontMetrics(font).height() + 2)


class ExitDialog(QDialog):
    """Chiqishni tasdiqlaydi va parolni SERVERDA tekshiradi."""

    def __init__(self, parent=None, *, staff_name: str = "",
                 repo: ProctoringRepository | None = None) -> None:
        super().__init__(parent)
        self._staff_name = staff_name
        self._repo = repo or ProctoringRepository()
        self._workers = WorkerHolder()
        self._busy = False
        #: Server "bu viloyatda parol sozlanmagan" dedi - dialog
        #: tasdiqlash rejimiga o'tadi.
        self._unconfigured = False

        self.setWindowTitle("Chiqish")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        # Ramkasiz + doim ustda: asosiy oyna ham shunday va dialog
        # undan ORQADA qolib ketmasligi kerak - operator "dastur
        # osilib qoldi" deb o'ylardi.
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(440)
        self._setup_ui()

    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("exitCard")
        # MD3 shape scale: dialog uchun "extra large" (28 px).
        card.setStyleSheet(
            """
            QFrame#exitCard {
                background-color: %s;
                border-radius: 28px;
                border: 1px solid %s;
            }
            """
            % (COLORS["surface"], COLORS["border"])
        )
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(56)
        shadow.setOffset(0, 16)
        shadow.setColor(QColor(0, 0, 0, 120))
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(34, 28, 34, 24)
        layout.setSpacing(0)

        # --- MD3 tonal nishon ------------------------------------------
        badge_row = QHBoxLayout()
        badge_row.addStretch()
        self._badge = StateBadge(size=68)
        self._badge.set_state("warning")
        badge_row.addWidget(self._badge)
        badge_row.addStretch()
        layout.addLayout(badge_row)
        layout.addSpacing(16)

        title = QLabel("Dasturdan chiqish")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _apply_font(title, 21, bold=True, extra="color: {};".format(COLORS["text"]))
        layout.addWidget(title)
        layout.addSpacing(6)

        # Kim sifatida chiqilayotgani AYTILADI: xodim kirgan bo'lsa,
        # u o'z parolini kutadi; kirmagan bo'lsa - viloyat parolini.
        # Bu farqni yashirish operatorni "qaysi parolni yozay?" degan
        # savol bilan qoldirardi.
        subtitle = QLabel(
            "{} sifatida chiqasiz — o'z parolingizni kiriting.".format(self._staff_name)
            if self._staff_name
            else "Tizimga kirilmagan — viloyatning chiqish parolini kiriting."
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        _apply_font(subtitle, 14, extra="color: {};".format(COLORS["text_secondary"]))
        self._subtitle = subtitle
        layout.addWidget(subtitle)
        layout.addSpacing(20)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Parol")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setFixedHeight(50)
        # Markazga tekislanmaydi: Qt markazlashtirilgan `QLineEdit` da
        # fokus paytida placeholder'ni chizmaydi va maydon bo'sh
        # kvadratga aylanib qoladi. Qolgan formalar ham chapga
        # tekislangan - bir xil bo'lgani yaxshi.
        self.password_input.returnPressed.connect(self._on_confirm)
        layout.addWidget(self.password_input)

        self.message = MessageBar()
        layout.addSpacing(12)
        layout.addWidget(self.message)

        # --- Amallar: preflight ekrani bilan BIR XIL shakl -------------
        layout.addSpacing(18)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)

        self.cancel_btn = QPushButton("Bekor qilish")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.setStyleSheet(outlined_button_style(44, "neutral"))
        self.cancel_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_btn, 1)

        self.confirm_btn = QPushButton("Chiqish")
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_btn.setStyleSheet(outlined_button_style(44, "primary"))
        self.confirm_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.confirm_btn.setDefault(True)
        self.confirm_btn.clicked.connect(self._on_confirm)
        buttons.addWidget(self.confirm_btn, 1)

        layout.addLayout(buttons)

    # ------------------------------------------------------------------
    def _on_confirm(self) -> None:
        if self._busy:
            return
        # Parol sozlanmagan holat: server shunday deb javob bergan va
        # dialog tasdiqlashga aylangan. Qayta so'rov yubormaymiz -
        # javob o'zgarmaydi.
        if self._unconfigured:
            log.warning("Chiqish parolsiz bajarildi - viloyatda parol sozlanmagan")
            self.accept()
            return

        password = self.password_input.text()
        if not password:
            self.message.show_message("Parolni kiriting")
            return

        # Tekshiruv SERVERDA: parol client'da na saqlanadi, na
        # solishtiriladi. Shuning uchun u fon thread'ida ketadi - aks
        # holda dialog so'rov davomida muzlab qolardi.
        self._set_busy(True)
        worker = ApiWorker(self._repo.verify_exit, password=password, parent=self)
        worker.succeeded.connect(self._on_verified)
        worker.failed.connect(self._on_rejected)
        self._workers.run(worker)

    def _on_verified(self, result) -> None:
        self._set_busy(False)
        log.info("Chiqishga ruxsat berildi (%s)", (result or {}).get("method") or "-")
        self.accept()

    def _on_rejected(self, message: str, code: str) -> None:
        self._set_busy(False)

        if code == "exit_password_not_configured":
            # Sozlash bosqichidagi bo'shliq, operatorning xatosi emas.
            # Dialog tasdiqlash rejimiga o'tadi: mashina qulflanib
            # qolmaydi, lekin nima yetishmayotgani ekranda aytiladi.
            self._unconfigured = True
            self._badge.set_state("warning")
            self.password_input.hide()
            self._subtitle.setText(
                "Bu viloyat uchun chiqish paroli sozlanmagan. "
                "Administratorga xabar bering."
            )
            self.message.show_message("Parolsiz chiqishga ruxsat berildi", "warning")
            self.confirm_btn.setText("Baribir chiqish")
            log.error("Viloyat uchun chiqish paroli sozlanmagan")
            return

        self._badge.set_state("error")
        self.password_input.clear()
        self.password_input.setFocus()
        self.message.show_message(message or "Parol noto'g'ri")
        log.warning("Chiqish rad etildi (%s): %s", code or "-", message)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.confirm_btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(not busy)
        self.password_input.setEnabled(not busy)
        self.confirm_btn.setText(
            "Tekshirilmoqda..." if busy
            else ("Baribir chiqish" if self._unconfigured else "Chiqish")
        )
        if busy:
            self._badge.set_state("loading")
            self.message.clear_message()

    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:
        parent = self.parent()
        if parent is not None:
            geometry = parent.geometry()
            self.move(
                geometry.x() + (geometry.width() - self.width()) // 2,
                geometry.y() + (geometry.height() - self.height()) // 2,
            )
        self.password_input.clear()
        self.password_input.setFocus()
        super().showEvent(event)

    def reject(self) -> None:
        # So'rov ketayotganda bekor qilish worker'ni yetim qoldiradi.
        if self._busy:
            return
        super().reject()

    def done(self, result: int) -> None:
        self._workers.wait_all(10_000)
        super().done(result)
