"""
Brend: logotip va ish o'rni raqami (sarlavhada va imtihon sahifasida).

LOGO FAYL SIFATIDA (`resources/images/logo.png`), `icons.py` dagidek
chizilgan emas: u muassasa belgisi va uni almashtirish kod o'zgarishi
bo'lmasligi kerak — faylni almashtirish kifoya. PyInstaller paketida
`--add-data "resources;resources"` shart (`client/README.md`).

FAYL YO'Q BO'LSA DASTUR TO'XTAMAYDI: logotip ko'rinishi, imtihonning
sharti emas. Vidjet o'zini yashiradi va log'da bitta ogohlantirish
qoladi — ekranda bo'sh ramka yoki "rasm topilmadi" belgisi chiqmaydi.

RASM BIR MARTA O'QILADI va har o'lcham/rang uchun alohida keshlanadi:
login sahifasi logotipni har `resizeEvent` da qayta o'lchaydi va har
safar diskdan o'qish oynani cho'zishni sekinlashtirardi.
"""

from __future__ import annotations

import logging
import math
from functools import lru_cache
from typing import Optional

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from core.bundle_paths import resource_path
from ui.styles import COLORS

log = logging.getLogger(__name__)

LOGO_PATH = resource_path("resources/images/logo.png")


@lru_cache(maxsize=1)
def _source() -> Optional[QImage]:
    image = QImage(str(LOGO_PATH))
    if image.isNull():
        log.warning("Logotip topilmadi yoki o'qilmadi: %s", LOGO_PATH)
        return None
    return image


@lru_cache(maxsize=16)
def _scaled(height_px: int, tint: str) -> Optional[QImage]:
    source = _source()
    if source is None or height_px <= 0:
        return None
    image = source.scaledToHeight(height_px, Qt.TransformationMode.SmoothTransformation)
    if tint:
        # Shakl SAQLANADI, rang almashadi: `SourceIn` faqat logotip
        # piksellari ustiga bo'yaydi. To'q yashil fon ustida asl to'q
        # rangli logotip ko'rinmay qolardi.
        image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        painter = QPainter(image)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(image.rect(), QColor(tint))
        painter.end()
    return image


def logo_pixmap(height: int, *, tint: str = "", dpr: float = 1.0) -> QPixmap:
    """
    Berilgan MANTIQIY balandlikdagi logotip.

    `dpr` — ekran masshtabi (125%, 150%). Rasm FIZIK piksellarda
    o'lchanadi, aks holda yuqori DPI ekranda Qt uni yana cho'zib,
    chetlari xira chiqardi.
    """
    image = _scaled(max(1, round(height * dpr)), tint or "")
    if image is None:
        return QPixmap()
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


class BrandLogo(QLabel):
    """
    Logotip vidjeti. `tint` — bir rangli ko'rinish (masalan oq, to'q fonda).

    Balandlik tashqaridan o'zgartiriladi (`set_logo_height`) —
    login sahifasi uni oyna balandligiga moslaydi.
    """

    def __init__(self, height: int = 40, *, tint: str = "", parent=None) -> None:
        super().__init__(parent)
        self._height = height
        self._tint = tint
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background: transparent;")
        self.setAccessibleName("Logotip")
        self._hidden_for_missing = False
        self._render()

    def set_logo_height(self, height: int) -> None:
        if height != self._height:
            self._height = height
            self._render()

    def _render(self) -> None:
        pixmap = logo_pixmap(self._height, tint=self._tint, dpr=self.devicePixelRatioF())
        # `setVisible(True)` CHAQIRILMAYDI: `__init__` da vidjetning
        # otasi hali yo'q va Qt uni ALOHIDA OYNA qilib ochardi - ishga
        # tushishda ekranning chap yuqorisida kichik oyna miltillab
        # turardi (har logotip uchun ~70 ms nativ oyna). Ko'rinish
        # otadan meros qoladi; faylsiz holatda yashiriladi, fayl
        # topilganda esa faqat O'ZIMIZ yashirgan bo'lsak qaytariladi.
        if pixmap.isNull():
            self._hidden_for_missing = True
            self.hide()
        elif self._hidden_for_missing:
            self._hidden_for_missing = False
            if self.parentWidget() is not None:
                self.show()
        self.setPixmap(pixmap)
        if not pixmap.isNull():
            self.setFixedSize(pixmap.deviceIndependentSize().toSize())

    def showEvent(self, event) -> None:
        # Oyna boshqa masshtabli monitorga ko'chgan bo'lishi mumkin —
        # DPR faqat ko'rsatilganda aniq ma'lum.
        super().showEvent(event)
        self._render()


class SeatBadge(QFrame):
    """
    Ish o'rni raqami — sarlavhaning ENG KO'ZGA TASHLANADIGAN elementi.

    Operator va talabgor mashinani AYNAN SHU raqam bilan ataydi ("12-
    kompyuterga o'ting") va u stolga yozilgan. Ilgari raqam kontekst
    kataklaridan biri edi — MAC va IP bilan bir xil o'lchamda, ya'ni
    texnik ma'lumot orasida yo'qolib ketardi. Bron tekshiruvida client
    "talabgor №12 ga biriktirilgan" deganda operator shu raqamga
    qaraydi.

    MD3 "primary container": to'ldirilgan tonal fon, yirik raqam va
    ustida kichik yorliq. Raqam bo'lmasa inventar kodi; kompyuter umuman
    biriktirilmagan bo'lsa nishon YASHIRINADI — "—" belgisi "raqam yo'q"
    degan yolg'on xabar bo'lardi.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("seatBadge")
        self.setStyleSheet(
            """
            QFrame#seatBadge {{
                background-color: {bg};
                border: none;
                border-radius: 16px;
            }}
            """.format(bg=COLORS["primary_container"])
        )
        box = QVBoxLayout(self)
        box.setContentsMargins(18, 6, 18, 7)
        box.setSpacing(0)

        caption = QLabel("KOMPYUTER")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caption.setStyleSheet(
            "font-size: 10px; font-weight: 800; letter-spacing: 1.2px; "
            "background: transparent; color: {};".format(COLORS["on_primary_container"])
        )
        box.addWidget(caption)

        self._value = QLabel("—")
        self._value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._value.setStyleSheet(
            "font-size: 24px; font-weight: 800; background: transparent; "
            "color: {};".format(COLORS["primary_deep"])
        )
        box.addWidget(self._value)
        self.hide()

    def set_seat(self, number: Optional[int], label: str = "", *, code: str = "") -> None:
        """`number` — xonadagi raqam; `label` — serverdagi to'liq nom (tooltip)."""
        text = "№{}".format(number) if number else (code or "")
        self._value.setText(text)
        self.setToolTip(label or text)
        self.setVisible(bool(text))


class FloatingSeatTag(QWidget):
    """
    Imtihon sahifasidagi kompyuter raqami — pastki CHAP burchakda suzadi.

    Imtihon sahifasida sarlavha yo'q (butun ekran testniki), ya'ni
    `SeatBadge` ham yo'q. Nazoratchi zalda "12-kompyuter" ni shu raqam
    bilan qidiradi: u ekranga uzoqdan qaraydi va raqam stol yorlig'idan
    ko'ra tezroq ko'zga tashlanishi kerak.

    YASHIL YARIM SHAFFOF KAPSULA, OQ MATN VA OQ CHIZIQ: test sahifasi oq
    ham, to'q ham bo'lishi mumkin. Kulrang/qora kapsula to'q sahifada
    ko'rinmay qolardi; brend yashili ikkalasida ajraladi, oq chiziq esa
    chegarani to'q fonda ham chizadi. Ostidagi matn fon orqali ko'rinadi. Pastki chap — o'ngda
    amallar tugmasi (`ExamActionMenu`), tepa qism platformaning sarlavhasi
    va taymeri uchun ochiq.

    SICHQONCHA UCHUN SHAFFOF (`WA_TransparentForMouseEvents`): kapsula
    ostidagi test tugmasi bosilishi kerak. Shu sababli tooltip yo'q.
    Bola vidjet va uslub jadvali yo'q — hammasi bitta `paintEvent` da
    (`exam_menu` dagi sabab: global uslub shaffof fonni buzardi).
    """

    #: Ota vidjet chetidan masofa (`ExamActionMenu` tugmasi bilan bir xil).
    MARGIN = 18
    #: Fon shaffofligi (0..1): raqam o'qiladi, ostidagi matn ko'rinadi.
    _FILL_ALPHA = 0.78
    _RING_ALPHA = 0.55
    _PAD_X = 16
    _PAD_Y = 7
    _CAPTION_PX = 10
    _VALUE_PX = 26

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._text = ""
        self._caption_font = QFont()
        self._caption_font.setPixelSize(self._CAPTION_PX)
        self._caption_font.setWeight(QFont.Weight.ExtraBold)
        self._caption_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.4)
        self._value_font = QFont()
        self._value_font.setPixelSize(self._VALUE_PX)
        self._value_font.setWeight(QFont.Weight.ExtraBold)
        # Otasiz vidjetda `show()` chaqirilmaydi (CLAUDE.md, tuzoqlar).
        self.hide()

    @property
    def text(self) -> str:
        return self._text

    def set_seat(self, number: Optional[int], *, code: str = "") -> None:
        """`SeatBadge.set_seat` qoidasi: raqam, bo'lmasa inventar kodi, aks holda yashirin."""
        self._text = "№{}".format(number) if number else (code or "")
        if not self._text:
            self.hide()
            return
        self.reposition()
        if self.parentWidget() is not None:
            self.show()
            self.raise_()
        self.update()

    def reposition(self) -> None:
        caption = QFontMetricsF(self._caption_font)
        value = QFontMetricsF(self._value_font)
        width = max(caption.horizontalAdvance(_SEAT_CAPTION), value.horizontalAdvance(self._text))
        size = QSize(
            math.ceil(width) + 2 * self._PAD_X,
            math.ceil(caption.height() + value.height()) + 2 * self._PAD_Y,
        )
        parent = self.parentWidget()
        y = (parent.height() - self.MARGIN - size.height()) if parent is not None else 0
        self.setGeometry(self.MARGIN, max(0, y), size.width(), size.height())

    def paintEvent(self, _event) -> None:
        if not self._text:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        fill = QColor(COLORS["primary_dark"])
        fill.setAlphaF(self._FILL_ALPHA)
        ring = QColor(255, 255, 255)
        ring.setAlphaF(self._RING_ALPHA)
        painter.setPen(QPen(ring, 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 16, 16)

        caption = QFontMetricsF(self._caption_font)
        top = rect.top() + self._PAD_Y
        caption_rect = QRectF(rect.left(), top, rect.width(), caption.height())
        painter.setFont(self._caption_font)
        painter.setPen(QColor(255, 255, 255, 200))
        painter.drawText(caption_rect, Qt.AlignmentFlag.AlignCenter, _SEAT_CAPTION)

        value_rect = QRectF(rect.left(), caption_rect.bottom(), rect.width(),
                            rect.bottom() - self._PAD_Y - caption_rect.bottom())
        painter.setFont(self._value_font)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(value_rect, Qt.AlignmentFlag.AlignCenter, self._text)
        painter.end()


_SEAT_CAPTION = "KOMPYUTER"
