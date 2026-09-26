"""
Proktorning ogohlantirishi — talabgor ekranidagi modal.

ILGARI BU CHIZILGAN QOPLAMA EDI (`indicators.WarningOverlay`) va u
ikki sababdan almashtirildi:

  * KO'RINMASLIK. Qoplama — sahifaning oddiy bolasi, `QWebEngineView`
    esa o'z oynasini boshqaradi. Qaysi biri ustida chizilishi
    platformaga va drayverga bog'liq bo'lib qolardi: ba'zi
    mashinalarda ogohlantirish brauzer ostida qolib ketardi va
    proktor "yubordim, lekin talabgor ko'rmadi" degan holatga
    tushardi. Alohida OYNA (dialog) bunday savol qoldirmaydi —
    uni kompozitor har doim ustiga chizadi;
  * UMUMIY QOBIQ. Chizilgan karta dasturning qolgan dialoglaridan
    ajralib turardi (o'z shrifti, o'z burchagi, o'z rangi) va har
    o'zgarishda ikkinchi marta tuzatish kerak bo'lardi.

`exec()` ISHLATILMAYDI — faqat `show()`. Bu qoida o'zgarmadi va
sababi avvalgidek: `exec()` hodisa siklini bloklaydi, ya'ni
heartbeat, hodisa buferi va skrinshot taymerlari ogohlantirish
yopilgunga qadar TO'XTAB TURARDI. Aynan talabgor qoida buzgan
paytda nazoratni o'chirish — eng noto'g'ri xulq. Modallik esa
yo'qolmaydi: `CardDialog` oynani `ApplicationModal` qiladi va Qt
kiritishni o'zi to'sadi (bloklash kirish uchun, sikl uchun emas).

O'ZI YOPILADI (`Setting.warning_timeout`). Talabgor uni yopishi
uchun tugma bosishi SHART bo'lsa, u ogohlantirishni ochiq
qoldirib, "ekranim to'silib qoldi" deb bahona qila olardi.
Chetlashtirish xabari esa YOPILMAYDI (`timeout_s=0`) — u
imtihonning yakuni, o'tkinchi xabar emas.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton

from ui.dialogs.base import CardDialog, apply_font
from ui.styles import COLORS, primary_button_style
from ui.widgets.indicators import StateBadge

#: Jiddiylik -> (nishon holati, sarlavha, rang kaliti).
#:
#: Matn jiddiylikka qarab O'ZGARADI: bir xil "Ogohlantirish"
#: sarlavhasi bilan birinchi eslatma ham, oxirgi ogohlantirish ham
#: bir xil ko'rinardi va talabgor farqni sezmasdi.
LEVELS = {
    1: ("info", "Diqqat", "accent"),
    2: ("warning", "Ogohlantirish", "warning"),
    3: ("error", "Jiddiy ogohlantirish", "error"),
    4: ("error", "Oxirgi ogohlantirish", "error"),
}


class WarningDialog(CardDialog):
    """Proktor xabari. Bitta nusxa qayta ishlatiladi."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent, title="Ogohlantirish", card_width=560)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        # Sanoq ALOHIDA taymerda: u har soniyada matnni yangilaydi,
        # yopilish esa yuqoridagi bitta uzun taymerga qoladi —
        # sanoqni yopilish manbai qilish har soniyada bir marta
        # xatolik to'planishiga yo'l ochardi.
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._update_countdown)
        self._left = 0
        self._setup_ui()

    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        layout = self.body

        badge_row = QHBoxLayout()
        badge_row.addStretch()
        self.badge = StateBadge(size=68)
        self.badge.set_state("warning")
        badge_row.addWidget(self.badge)
        badge_row.addStretch()
        layout.addLayout(badge_row)
        layout.addSpacing(16)

        self.title_label = QLabel("Ogohlantirish")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        apply_font(self.title_label, 22, bold=True)
        layout.addWidget(self.title_label)
        layout.addSpacing(8)

        self.text_label = QLabel("")
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text_label.setWordWrap(True)
        apply_font(self.text_label, 16, extra="color: {};".format(COLORS["text"]))
        layout.addWidget(self.text_label)

        layout.addSpacing(14)
        self.countdown = QLabel("")
        self.countdown.setAlignment(Qt.AlignmentFlag.AlignCenter)
        apply_font(
            self.countdown, 13, extra="color: {};".format(COLORS["text_muted"])
        )
        layout.addWidget(self.countdown)

        layout.addSpacing(16)
        self.ok_btn = QPushButton("Tushundim")
        self.ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ok_btn.setStyleSheet(primary_button_style(48))
        self.ok_btn.clicked.connect(self.dismiss)
        layout.addWidget(self.ok_btn)

    # ------------------------------------------------------------------
    def show_warning(self, text: str, severity: int = 2, timeout_s: int = 5) -> None:
        """
        Xabarni ko'rsatadi (yoki ochiq turganini YANGILAYDI).

        Ikkinchi ogohlantirish birinchisini almashtiradi: ikkita
        modal bir-birining ustida ochilsa, talabgor pastdagisini
        umuman ko'rmasdi va proktor "ikki marta yubordim" degan
        holatga tushardi.
        """
        state, title, color = LEVELS.get(int(severity or 2), LEVELS[2])
        self.badge.set_state(state)
        self.title_label.setText(title)
        # `apply_font` uslubni TO'LIQ almashtiradi: rangni mavjud
        # satrga qo'shib borish har ogohlantirishda satrni
        # uzaytirardi.
        apply_font(
            self.title_label, 22, bold=True, extra="color: {};".format(COLORS[color])
        )
        self.text_label.setText(text or "Proktor ogohlantirdi")

        self._timer.stop()
        self._tick.stop()
        self._left = max(0, int(timeout_s or 0))
        if self._left:
            self._timer.start(self._left * 1000)
            self._tick.start(1000)
            self.countdown.setText("{} soniyadan keyin yopiladi".format(self._left))
            self.countdown.show()
            self.ok_btn.setText("Tushundim")
        else:
            # Yopilmaydigan xabar — sanoq ham, yolg'on umid ham yo'q.
            self.countdown.hide()
            self.ok_btn.setText("Yopish")

        # O'RALADIGAN MATN uzunligi har xabarda boshqacha
        # (`CardDialog.refit` izohi).
        self.refit()
        self.show()
        self.raise_()
        self.activateWindow()

    def dismiss(self) -> None:
        self._timer.stop()
        self._tick.stop()
        self.hide()

    # ------------------------------------------------------------------
    def _update_countdown(self) -> None:
        self._left = max(0, self._left - 1)
        if self._left <= 0:
            self._tick.stop()
            return
        self.countdown.setText("{} soniyadan keyin yopiladi".format(self._left))

    def keyPressEvent(self, event) -> None:
        """
        `Esc` YOPMAYDI.

        Ogohlantirishning butun ma'nosi — talabgorning diqqatini
        tortish. Tasodifiy bosilgan `Esc` uni o'qilmagan holda
        yo'qotardi va hodisa oqimida "ko'rsatildi" deb qolardi.
        """
        if event.key() == Qt.Key.Key_Escape:
            event.ignore()
            return
        super().keyPressEvent(event)
