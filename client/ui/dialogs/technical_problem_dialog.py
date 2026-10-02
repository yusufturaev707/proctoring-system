"""
Texnik muammo haqida xabar berish dialogi.

ILGARI BU `QInputDialog.getText` EDI va u ikki narsani yo'qotardi:

  * KO'RINISH. Qt'ning standart dialogi tizim uslubida chiziladi —
    imtihon oynasi ramkasiz, yumaloq va yashil, uning ustida esa
    kulrang Windows dialogi paydo bo'lardi. Kiosk rejimida bu
    "boshqa dastur ochildi" degan taassurot beradi;
  * MA'LUMOT. Server besh xil muammo turini qabul qiladi (elektr,
    tarmoq, uskuna, dastur, boshqa) va panelda ular bo'yicha
    filtrlash mumkin. Client esa HAR DOIM `other` yuborardi — ya'ni
    tur maydoni bor edi, lekin unda hech qachon foydali qiymat
    bo'lmasdi.

TUR CHIP'LAR BILAN tanlanadi, ochiladigan ro'yxat bilan emas: beshta
variant bir qarashda ko'rinadi va tanlash bitta bosishda bo'ladi.
Elektr o'chganda operatorning vaqti yo'q — ro'yxatni ochib, aylantirib,
tanlash uch harakat degani.

"Boshqa" OLDINDAN TANLANGAN: xabar yuborish yo'li hech qachon
"avval turini tanlang" degan to'siqqa uchramaydi, aniqlashtirish esa
ixtiyoriy qoladi (avvalgi xulq ham shunday edi).

TIL ALMASHTIRGICH BU YERDA YO'Q. U asosiy oynada, `QStackedWidget`
ustida suzib turadi (`ui/widgets/language_bar.py`) va modal ochilganda
ham ekranda ko'rinadi — dialogga ikkinchi nusxasini qo'yish bir
ekranda ikkita bir xil tugma degani bo'lardi va operator qaysi biri
ishlayotganini o'ylab qolardi.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTextEdit,
)

from ui.dialogs.base import CardDialog, apply_font
from ui.styles import (
    COLORS,
    chip_style,
    outlined_button_style,
    primary_button_style,
)
from ui.widgets.indicators import MessageBar, StateBadge

#: Server qabul qiladigan turlar (`TechnicalProblemReportSerializer`).
#: Tartib ehtimollik bo'yicha: elektr va tarmoq eng ko'p uchraydi.
KINDS = (
    ("power", "Elektr"),
    ("network", "Tarmoq"),
    ("hardware", "Uskuna"),
    ("software", "Dastur"),
    ("other", "Boshqa"),
)

#: Backend chegarasi (`description = CharField(max_length=1000)`).
_MAX_LENGTH = 1000


class TechnicalProblemDialog(CardDialog):
    """
    Muammo turi va tavsifi. Serverga YUBORMAYDI.

    Dialog faqat ma'lumot yig'adi, so'rovni chaqiruvchi sahifa
    yuboradi (`exam_webview_page`). Sabab: sahifada allaqachon
    xabar satri, worker va sessiya konteksti bor — ikkinchi nusxa
    yozish ularni ikki joyda saqlash degani bo'lardi.
    """

    def __init__(self, parent=None) -> None:
        # Kenglik 520: chip panjarasi (3 ustun) va ikkita tugma shu
        # kenglikda erkin joylashadi. Tor kartada Qt ustunni siqib,
        # maydonlarni bir-birining ustiga chizib qo'yardi.
        super().__init__(parent, title="Texnik muammo", card_width=520)
        self._kind = "other"
        self._chips: dict = {}
        self._setup_ui()

    # ------------------------------------------------------------------
    @property
    def kind(self) -> str:
        return self._kind

    @property
    def description(self) -> str:
        return self.text_input.toPlainText().strip()[:_MAX_LENGTH]

    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        layout = self.body

        badge_row = QHBoxLayout()
        badge_row.addStretch()
        badge = StateBadge(size=64)
        badge.set_state("warning")
        badge_row.addWidget(badge)
        badge_row.addStretch()
        layout.addLayout(badge_row)
        layout.addSpacing(14)

        title = QLabel("Texnik muammo")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        apply_font(title, 21, bold=True, extra="color: {};".format(COLORS["text"]))
        layout.addWidget(title)
        layout.addSpacing(6)

        subtitle = QLabel(
            "Turini tanlang va qisqacha yozing — proktor xabarni darhol ko'radi."
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        apply_font(subtitle, 14, extra="color: {};".format(COLORS["text_secondary"]))
        layout.addWidget(subtitle)

        # --- Tur: MD3 filter chip'lar ---------------------------------
        #
        # PANJARA (3 ustun), bitta qator EMAS. Beshta chip bir qatorda
        # ~480 px talab qiladi va kartaga (410 px ichki kenglik)
        # sig'maydi: Qt o'shanda butun ustunni siqib, maydonlarni
        # bir-birining USTIGA chizib qo'yardi — xabar satri matn
        # maydonining ichida turardi. Panjara kengligi esa matn
        # uzunligiga bog'liq emas.
        layout.addSpacing(18)
        chips_grid = QGridLayout()
        chips_grid.setContentsMargins(0, 0, 0, 0)
        chips_grid.setHorizontalSpacing(8)
        chips_grid.setVerticalSpacing(8)
        for index, (code, label) in enumerate(KINDS):
            chip = QPushButton(label)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            chip.clicked.connect(lambda _checked=False, value=code: self._select(value))
            self._chips[code] = chip
            chips_grid.addWidget(chip, index // 3, index % 3)
        layout.addLayout(chips_grid)
        self._paint_chips()

        # --- Tavsif ----------------------------------------------------
        layout.addSpacing(16)
        self.text_input = QTextEdit()
        self.text_input.setPlaceholderText(
            "Masalan: monitor o'chib qoldi, tarmoq uzildi, kamera ishlamayapti…"
        )
        # Balandlik QAT'IY: matn kiritilganda maydon o'sib, tugmalarni
        # pastga surib yuborardi va operator bosayotgan tugmasini
        # yo'qotardi (`camera_panel` dagi oldindan ko'rish bilan bir
        # xil sabab).
        self.text_input.setFixedHeight(92)
        self.text_input.setStyleSheet(
            """
            QTextEdit {{
                background-color: {surface};
                border: 1px solid {outline_variant};
                border-radius: 12px;
                padding: 10px 12px;
                font-size: 14px;
                color: {text};
            }}
            QTextEdit:hover {{
                border-color: {outline};
            }}
            QTextEdit:focus {{
                border: 2px solid {primary};
                padding: 9px 11px;
            }}
            """.format(**COLORS)
        )
        layout.addWidget(self.text_input)

        self.message = MessageBar()
        layout.addSpacing(10)
        layout.addWidget(self.message)

        # --- Amallar ---------------------------------------------------
        layout.addSpacing(16)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)

        cancel_btn = QPushButton("Bekor qilish")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(outlined_button_style(44, "neutral"))
        cancel_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn, 1)

        self.send_btn = QPushButton("Yuborish")
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # ASOSIY AMAL TO'LDIRILGAN (MD3 "filled button"). Dasturning
        # qolgan qismida ham oldinga olib boradigan amal to'ldirilgan
        # yashil tugma ("TEKSHIRISH", "Tasdiqlash") — konturli
        # tugma esa ikkinchi darajali. Ikkalasini konturli qilish
        # "qaysi biri asosiy?" degan savolni operatorga qoldirardi.
        self.send_btn.setStyleSheet(primary_button_style(44))
        self.send_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.send_btn.setDefault(True)
        self.send_btn.clicked.connect(self._on_send)
        buttons.addWidget(self.send_btn, 1)

        layout.addLayout(buttons)
        self.text_input.setFocus()
        # O'raladigan matnlar layout'ga haqiqiy balandligini aytsin
        # (`CardDialog.refit` izohi).
        self.refit()

    # ------------------------------------------------------------------
    def _select(self, code: str) -> None:
        self._kind = code
        self._paint_chips()

    def _paint_chips(self) -> None:
        """
        MD3 filter chip: tanlangani ✓ belgisi bilan.

        Tanlov faqat RANG bilan ko'rsatilmaydi (`chip_style` izohi):
        belgi rang ajratolmaydigan operator uchun ham tanlovni aytadi.
        Matn `KINDS` dan qayta yoziladi - belgi yorliqqa yopishib qolmaydi.
        """
        labels = dict(KINDS)
        for value, chip in self._chips.items():
            selected = value == self._kind
            chip.setText(("✓  " if selected else "") + labels[value])
            chip.setStyleSheet(chip_style(selected=selected))

    def _on_send(self) -> None:
        if not self.description:
            # Tur o'zi yetarli emas: proktor ekranida "Uskuna" degan
            # yozuv nima buzilganini aytmaydi va u operatorga qayta
            # qo'ng'iroq qilishга majbur bo'lardi.
            self.message.show_message("Muammoni qisqacha yozing")
            # Xabar satri paydo bo'ldi — dialog balandligi o'zgaradi.
            self.refit()
            self.text_input.setFocus()
            return
        self.accept()
