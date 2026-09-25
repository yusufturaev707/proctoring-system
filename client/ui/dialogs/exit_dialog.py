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
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
)

from services.repositories import ProctoringRepository
from services.workers import ApiWorker, WorkerHolder
from ui.dialogs.base import CardDialog, apply_font as _apply_font
from ui.styles import COLORS, outlined_button_style, tonal_button_style
from ui.widgets.indicators import MessageBar, StateBadge

log = logging.getLogger(__name__)


class ExitDialog(CardDialog):
    """
    Chiqishni tasdiqlaydi va parolni SERVERDA tekshiradi.

    IKKI CHIQISH YO'LI. Ctrl+Q ni bosgan operator ko'pincha dasturdan
    chiqmoqchi EMAS - u noto'g'ri sahifaga o'tib qolgan va orqaga
    qaytmoqchi. Ilgari dialogda faqat parol maydoni bor edi va
    yagona yo'l "Bekor qilish" bo'lardi; sahifada orqaga qaytish
    tugmasi bo'lmasa (masalan imtihon tanlash ekranida), operator
    tuzoqqa tushardi.

    Shuning uchun `back_label` berilganda dialog ikkita yo'l
    taklif qiladi:

        Orqaga qaytish  - xavfsiz, tez-tez kerak bo'ladigan amal;
                          parol SO'RALMAYDI, chunki dastur ochiq
                          qoladi va kiosk buzilmaydi.
        Chiqish         - dasturni yopadi, parol MAJBURIY.

    Birinchisi tepada va tonal (MD3 "filled tonal") - u tavsiya
    etiladigan amal. Ikkinchisi pastda, parol maydonining ostida:
    shakl o'zi "bu boshqa, jiddiyroq yo'l" deb turadi.
    """

    #: `exec()` qaytaradigan uchinchi natija.
    #:
    #: `Accepted`/`Rejected` ikkitasi yetmaydi: "chiqishga ruxsat
    #: berildi" va "bekor qilindi" dan tashqari uchinchi ma'no bor -
    #: "chiqmayman, lekin oldingi sahifaga o't". Uni `Rejected` ga
    #: qo'shib yuborish chaqiruvchidan qo'shimcha bayroq o'qishni
    #: talab qilardi va u albatta unutilardi.
    BACK = 2

    def __init__(self, parent=None, *, staff_name: str = "",
                 repo: ProctoringRepository | None = None,
                 back_label: str = "", warning: str = "") -> None:
        # Kenglik 560, 440 emas: "orqaga qaytish" tugmasi to'liq
        # kenglikda turadi va uning matni chaqiruvchidan keladi
        # ("Talabgor ma'lumotlariga qaytish" — 484 px). Tor kartada
        # Qt uni siqib, matnni kesib qo'yardi va ustundagi
        # maydonlarni ham buzardi (`CardDialog.refit` izohi).
        super().__init__(parent, title="Chiqish", card_width=560)
        self._staff_name = staff_name
        self._back_label = back_label
        self._warning = warning
        self._repo = repo or ProctoringRepository()
        self._workers = WorkerHolder()
        self._busy = False
        #: Server "bu viloyatda parol sozlanmagan" dedi - dialog
        #: tasdiqlash rejimiga o'tadi.
        self._unconfigured = False

        self._setup_ui()

    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        # Qobiq (karta, soya, chetlar) `CardDialog` da — bu yerda
        # faqat mazmun.
        layout = self.body

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

        # Chiqishning OQIBATI oldindan aytiladi: imtihon sahifasida u
        # talabgorning sessiyasini yakunlaydi va buni parol kiritib
        # bo'lgandan keyin bilish kech.
        if self._warning:
            layout.addSpacing(14)
            warning = QLabel(self._warning)
            warning.setWordWrap(True)
            warning.setAlignment(Qt.AlignmentFlag.AlignCenter)
            _apply_font(
                warning, 13, bold=True,
                extra="color: {}; background: {}; border-radius: 12px; padding: 10px 14px;".format(
                    COLORS["error"], COLORS["error_soft"]
                ),
            )
            layout.addWidget(warning)

        # --- Xavfsiz yo'l: orqaga qaytish ------------------------------
        if self._back_label:
            layout.addSpacing(20)
            self.back_btn = QPushButton(self._back_label)
            self.back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.back_btn.setStyleSheet(tonal_button_style(46))
            self.back_btn.clicked.connect(lambda: self.done(self.BACK))
            layout.addWidget(self.back_btn)

            hint = QLabel("yoki dasturdan butunlay chiqish uchun parolni kiriting")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint.setWordWrap(True)
            _apply_font(hint, 13, extra="color: {};".format(COLORS["text_muted"]))
            layout.addSpacing(14)
            layout.addWidget(hint)
            layout.addSpacing(10)
        else:
            self.back_btn = None
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
        self.refit()

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
            self.refit()
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
            self.refit()
            log.error("Viloyat uchun chiqish paroli sozlanmagan")
            return

        self._badge.set_state("error")
        self.password_input.clear()
        self.password_input.setFocus()
        self.message.show_message(message or "Parol noto'g'ri")
        # Server xabari uzun bo'lishi mumkin (ikki-uch qator) —
        # dialog o'sishi kerak, aks holda matn tugmalar ustiga
        # chiqib qolardi.
        self.refit()
        log.warning("Chiqish rad etildi (%s): %s", code or "-", message)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.confirm_btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(not busy)
        if self.back_btn is not None:
            # Parol tekshirilayotganda orqaga qaytish ham bloklanadi:
            # dialog yopilsa, javob kelganda u allaqachon yo'q
            # obyektga signal yuborardi.
            self.back_btn.setEnabled(not busy)
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
