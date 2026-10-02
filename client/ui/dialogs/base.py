"""
Modal dialoglarning umumiy qobig'i (MD3 "dialog" konteyneri).

UCHINCHI NUSXA YOZILMADI. Chiqish dialogi va siyosat dialogi bir xil
qobiqni takrorlardi (ramkasiz oyna, shaffof fon, yumaloq karta,
soya, shrift yordamchisi), texnik muammo dialogi esa uchinchisi
bo'lardi. Ular albatta ajralib ketardi — birinchi belgisi allaqachon
bor edi: ikkalasida karta ichki chetlari boshqacha.

SOYA UCHUN JOY QOLDIRILADI (`SHADOW_MARGIN`) va bu ko'rinadigan
xatoni tuzatadi. Ilgari tashqi layout chetlari NOL edi, ya'ni
`QGraphicsDropShadowEffect` chizadigan joy yo'q edi: 56 px blur
vidjet ramkasiga siqilib, kartaning atrofida yumshoq soya o'rniga
QATTIQ QORA CHIZIQ paydo bo'lardi — ekranda u "modalning ramkasi"
bo'lib ko'rinardi.

Shaffoflik ikki qavatli: `WA_TranslucentBackground` (oyna sathi) va
`QDialog { background: transparent }` (uslub). Ikkinchisi kerak,
chunki global uslubda `QWidget { background-color: … }` qoidasi bor
va u dialogga ham tegishli — mavzu o'zgarganda u yana to'rtburchak
bo'lib chiqib qolardi.
"""

from __future__ import annotations

import ctypes
import logging
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QLabel,
    QVBoxLayout,
)

from ui.styles import COLORS

log = logging.getLogger(__name__)

#: MD3 shape scale: dialog uchun "extra large".
CARD_RADIUS = 28

#: Soya uchun karta atrofida qoldiriladigan joy (px).
#:
#: Blur radiusidan (56) kichik: soya markazdan tarqalganda chetga
#: yetguncha deyarli ko'rinmas bo'ladi, 32 px esa uni kesmaydi va
#: ayni paytda dialogni ekranda bekorga kattalashtirmaydi.
SHADOW_MARGIN = 32


#: DWM oyna atributlari (`dwmapi.h`).
#:
#: WINDOWS 11 HAR BIR TOP-LEVEL OYNAGA RAMKA CHIZADI va u
#: `FramelessWindowHint` bilan ham qoladi: kompozitor uni oyna
#: tashqarisida, Qt bilmagan holda chizadi. Shaffof dialogda bu
#: KO'RINADIGAN NOSOZLIK berardi - karta atrofida, undan 32 px
#: narida (soya uchun qoldirilgan joy) yumaloq to'rtburchak paydo
#: bo'lardi va ekranda u "modalning ortida ochilgan boshqa oyna"
#: bo'lib ko'rinardi.
#:
#: Ilgari u ko'zga tashlanmasdi: tashqi chetlar nol bo'lgani uchun
#: ramka kartaning o'z chegarasiga tushardi.
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWA_BORDER_COLOR = 34
_DWMWCP_DONOTROUND = 1
_DWMWA_COLOR_NONE = 0xFFFFFFFE


def strip_native_frame(widget) -> None:
    """
    Windows chizadigan ramka va yumaloq burchakni o'chiradi.

    XATO YUTILADI: bu KO'RINISH tuzatishi va u ishlamagani dasturni
    to'xtatishi mumkin emas. Windows 10 da atributlar umuman yo'q
    (`DwmSetWindowAttribute` xato kod qaytaradi), boshqa OS'da esa
    `dwmapi` kutubxonasining o'zi yo'q - ikkala holatda ham dialog
    avvalgidek ochilaveradi.
    """
    if sys.platform != "win32":
        return
    try:
        # `winId()` oynani NATIV qiladi: usiz HWND hali mavjud emas.
        handle = int(widget.winId())
        dwm = ctypes.windll.dwmapi
        color = ctypes.c_uint(_DWMWA_COLOR_NONE)
        dwm.DwmSetWindowAttribute(
            handle, _DWMWA_BORDER_COLOR, ctypes.byref(color), ctypes.sizeof(color)
        )
        corner = ctypes.c_int(_DWMWCP_DONOTROUND)
        dwm.DwmSetWindowAttribute(
            handle,
            _DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(corner),
            ctypes.sizeof(corner),
        )
    except Exception:  # noqa: BLE001 - ko'rinish tuzatishi, to'siq emas
        log.debug("Oyna ramkasini o'chirib bo'lmadi", exc_info=True)


def apply_font(widget, size: int, *, bold: bool = False, extra: str = "") -> None:
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


class CardDialog(QDialog):
    """
    Yumaloq kartali modal.

    Merosxo'r faqat MAZMUN bilan shug'ullanadi va uni `self.body`
    layout'iga qo'yadi — oyna bayroqlari, soya va chetlar bu yerda.

    `card_width` — KARTANING kengligi, dialogniki emas: dialog undan
    soya chetlari qadar kengroq bo'ladi. Chaqiruvchi ekranda
    ko'rinadigan o'lchamni beradi, ichki hisob-kitob esa bu yerda
    qoladi.
    """

    def __init__(
        self,
        parent=None,
        *,
        title: str = "",
        card_width: int = 440,
        padding: tuple = (34, 28, 34, 24),
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
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
        self.setStyleSheet("QDialog { background: transparent; }")
        self._card_width = card_width
        self.setFixedWidth(card_width + 2 * SHADOW_MARGIN)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            SHADOW_MARGIN, SHADOW_MARGIN, SHADOW_MARGIN, SHADOW_MARGIN
        )

        self.card = QFrame()
        self.card.setObjectName("dialogCard")
        # MD3 dialog: RAMKASIZ, 28 px, sirt - eng yorug' konteyner (ichki
        # bloklar `surface_container_low` - ular TON bilan ajraladi).
        # Ilgari 1 px kulrang ramka bor edi va ichki bloklarning
        # ramkalari bilan birga ichma-ich chegaralar hosil qilardi.
        self.card.setStyleSheet(
            """
            QFrame#dialogCard {
                background-color: %s;
                border-radius: %spx;
                border: none;
            }
            """
            % (COLORS["surface_container_lowest"], CARD_RADIUS)
        )
        # MD3 elevation 3: keng va yumshoq soya. Ilgari 120 alfali qora
        # soya kartaning pastida qattiq dog' bo'lib ko'rinardi.
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(16, 32, 20, 70))
        self.card.setGraphicsEffect(shadow)
        outer.addWidget(self.card)

        self.body = QVBoxLayout(self.card)
        self.body.setContentsMargins(*padding)
        self.body.setSpacing(0)

    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:
        """
        Nativ ramkani KO'RSATILGANDA o'chiradi.

        Konstruktorda emas: HWND oyna ekranga chiqqanda yaratiladi va
        Qt uni qayta yaratishi mumkin (masalan bayroqlar
        o'zgarganda), ya'ni atribut har ochilishda qayta qo'yilishi
        kerak.
        """
        super().showEvent(event)
        strip_native_frame(self)

    @property
    def content_width(self) -> int:
        """Karta ichidagi foydali kenglik (chetlar ayirilgan)."""
        margins = self.body.contentsMargins()
        return self._card_width - margins.left() - margins.right()

    def refit(self) -> None:
        """
        Mazmun o'zgargach dialogni QAYTA O'LCHAYDI.

        O'RALADIGAN MATN TUZOG'I. `QLabel` uch qatorga o'ralganda ham
        layout'ga BIR QATORLIK minimal balandlik beradi
        (`heightForWidth` size policy'da yoqilmagan bo'lsa). Natijada
        dialog o'zini kerakligidan ~30 px past qilib o'lchaydi, Qt esa
        yetishmagan joyni ustundagi maydonlardan "o'g'irlaydi" —
        ekranda xabar satri matn maydonining USTIGA chizilib qoladi.

        Shuning uchun har bir o'raladigan yorliqning minimal
        balandligi HAQIQIY qiymatga (`heightForWidth`) o'rnatiladi.
        Kenglik allaqachon ma'lum bo'lsa o'shanikidan olinadi:
        ichma-ich kartalardagi yorliq (masalan `IssueRow`) tor
        bo'ladi va karta kengligidan hisoblash balandlikni kam
        ko'rsatardi.

        Xabar satri paydo bo'lganda ham chaqirilishi SHART: uning
        matni ish paytida o'zgaradi.
        """
        for label in self.card.findChildren(QLabel):
            if not label.wordWrap():
                continue
            policy = label.sizePolicy()
            policy.setHeightForWidth(True)
            label.setSizePolicy(policy)
            width = label.width() or self.content_width
            # Bo'sh yorliqda (masalan yashirin `MessageBar`) `heightForWidth`
            # -1 qaytaradi va Qt "Negative sizes (0,-1)" ogohlantirishini
            # beradi - manfiy qiymat 0 ga tushiriladi.
            label.setMinimumHeight(max(0, label.heightForWidth(max(1, width))))
        self.body.invalidate()
        self.adjustSize()
