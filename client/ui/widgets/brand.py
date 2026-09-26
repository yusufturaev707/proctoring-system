"""
Brend: logotip va ish o'rni raqami.

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
from functools import lru_cache
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout

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
        self._render()

    def set_logo_height(self, height: int) -> None:
        if height != self._height:
            self._height = height
            self._render()

    def _render(self) -> None:
        pixmap = logo_pixmap(self._height, tint=self._tint, dpr=self.devicePixelRatioF())
        self.setVisible(not pixmap.isNull())
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
                border: 1px solid {border};
                border-radius: 16px;
            }}
            """.format(bg=COLORS["primary_soft"], border="#BBF7D0")
        )
        box = QVBoxLayout(self)
        box.setContentsMargins(18, 6, 18, 7)
        box.setSpacing(0)

        caption = QLabel("KOMPYUTER")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caption.setStyleSheet(
            "font-size: 10px; font-weight: 800; letter-spacing: 1.2px; "
            "background: transparent; color: {};".format(COLORS["primary_dark"])
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
