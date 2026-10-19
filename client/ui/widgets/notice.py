"""
MD3 "tonal" xabar bloki — ikonka, sarlavha, matn va (ixtiyoriy) qo'shimcha.

NIMA UCHUN `MessageBar` EMAS. U bitta markazlashtirilgan matnli yorliq:
ikki-uch qatorli server xabari o'rtaga tekislanib "zinapoya" bo'lib
o'qilardi, sarlavha va ikonka yo'q edi, ya'ni operator rangdan boshqa
hech narsadan "xatomi yoki shunchaki ma'lumotmi" ni ajrata olmasdi.
Bron xatolari esa ALOHIDA oq kartada, boshqa uslubda chiqardi - bitta
sahifada bitta savolga (JSHSHIR nega o'tmadi?) ikki xil ko'rinish.

MD3 qoidasi bo'yicha bitta komponent:

    * fon — jiddiylik konteyneri (`error_container`, `warning_container`,
      `tertiary_container`, `primary_container`), RAMKASIZ, 16 px radius;
    * chapda chizilgan ikonka (shrift glifi emas — `icons.py` docstring'i);
    * sarlavha (nima bo'ldi) va matn (nima qilish kerak) CHAPGA
      tekislangan — ko'p qatorli matn shunday o'qiladi;
    * `extra` — sarlavha ostidagi joy (masalan stol kataklari,
      `seat_notice.py`);
    * `detail` — server matni, eng pastda va kichik: u DALIL
      (administrator bilan gaplashganda aynan shu aytiladi).

`show_message` / `clear_message` / `text` — `MessageBar` bilan bir xil
imzo: sahifa kodi va testlar o'zgarmaydi.

IXCHAM SHAKL (`compact=True`) — forma ichidagi javob uchun (JSHSHIR
sahifasi): to'liq shakl 28 px ikonka va keng chetlari bilan bir qatorli
xabarni ham ~76 px blokka aylantirib, natijani ekrandan pastga surardi.
Ixchamda ikonka 20 px, chetlar va shrift bir pog'ona kichik, server
matni (`detail`) esa blok ostida emas, TOOLTIP'da — u administrator
uchun dalil, operator har safar o'qiydigan matn emas.
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ui.styles import COLORS

#: Jiddiylik -> (konteyner foni, konteynerdagi matn, urg'u/ikonka rangi).
TONES = {
    "error": (COLORS["error_container"], COLORS["on_error_container"], COLORS["error"]),
    "warning": (COLORS["warning_container"], COLORS["on_warning_container"], COLORS["warning"]),
    "info": (COLORS["tertiary_container"], COLORS["on_tertiary_container"], COLORS["accent"]),
    "success": (COLORS["primary_container"], COLORS["on_primary_container"], COLORS["primary_dark"]),
}

_ICON_SIZE = 28

#: Shakl o'lchamlari: (chetlar, oraliq, ikonka, ustun tepasi, ustun
#: oralig'i, sarlavha / matn / tafsilot shrifti, radius). Ustun tepasi
#: birinchi qatorni ikonka o'qiga tushiradi.
_METRICS = {
    False: ((16, 14, 18, 16), 14, _ICON_SIZE, 4, 4, 15, 14, 12, 16),
    True: ((12, 9, 14, 10), 10, 20, 1, 1, 14, 13, 12, 12),
}


class NoticeIcon(QWidget):
    """
    Jiddiylik ikonkasi: urg'u rangidagi shakl ichida oq belgi.

    Ogohlantirish — uchburchak, qolganlari — doira: rang ko'rmaydigan
    operator ham shakldan farqlaydi (MD3 "warning" / "error" / "info").
    """

    def __init__(self, parent=None, *, size: int = _ICON_SIZE) -> None:
        super().__init__(parent)
        self._kind = "error"
        self._size = size
        self.setFixedSize(size, size)

    def set_kind(self, kind: str) -> None:
        self._kind = kind if kind in TONES else "error"
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(self._size, self._size)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Belgi 28 px to'r uchun chizilgan — boshqa o'lchamda miqyoslanadi.
        painter.scale(self._size / _ICON_SIZE, self._size / _ICON_SIZE)
        accent = QColor(TONES[self._kind][2])
        size = float(_ICON_SIZE)
        c = size / 2

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        if self._kind == "warning":
            # Burchaklari yumaloq uchburchak: to'g'ri chiziqli uchburchak
            # 28 px da "qirrali" va boshqa ikonkalardan begona ko'rinardi.
            path = QPainterPath()
            top, left, right, bottom = QPointF(c, 2.5), QPointF(1.5, size - 3), QPointF(size - 1.5, size - 3), size - 3
            path.moveTo(top)
            path.lineTo(right)
            path.lineTo(left)
            path.closeSubpath()
            pen = QPen(accent, 3.0)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPath(path)
            painter.setPen(Qt.PenStyle.NoPen)
            glyph_top, glyph_bottom = 10.5, bottom - 7.5
        else:
            painter.drawEllipse(QRectF(0, 0, size, size))
            glyph_top, glyph_bottom = 7.5, size - 11.0

        white = QColor("#FFFFFF")
        pen = QPen(white, 2.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if self._kind == "success":
            painter.drawPolyline(
                QPointF(8.0, 14.5), QPointF(12.3, 18.8), QPointF(20.0, 10.0)
            )
        elif self._kind == "info":
            # "i": nuqta tepada, chiziq pastda.
            painter.drawLine(QPointF(c, 12.5), QPointF(c, 20.0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(white)
            painter.drawEllipse(QPointF(c, 8.3), 1.7, 1.7)
        else:
            # "!": chiziq tepada, nuqta pastda.
            painter.drawLine(QPointF(c, glyph_top), QPointF(c, glyph_bottom))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(white)
            painter.drawEllipse(QPointF(c, glyph_bottom + 4.3), 1.7, 1.7)
        painter.end()


def _invalidate_tree(layout) -> None:
    layout.invalidate()
    for index in range(layout.count()):
        child = layout.itemAt(index).layout()
        if child is not None:
            _invalidate_tree(child)


def _wrapped(style: str) -> QLabel:
    label = QLabel("")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    # Uslubda `padding` bo'lsa Qt matnga avtomatik chekinish qo'shadi va
    # u sarlavhadan bir necha piksel o'ngga siljiydi - hammasi bir chiziqda.
    label.setIndent(0)
    # O'raladigan yorliq layout'ga haqiqiy kenglikdagi balandligini
    # aytishi uchun (`MessageBar._fit` dagi muammo shu bilan yopiladi).
    policy = label.sizePolicy()
    policy.setHeightForWidth(True)
    policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
    label.setSizePolicy(policy)
    label.setStyleSheet(style)
    return label


class Notice(QFrame):
    """Bitta MD3 xabar bloki (modul izohiga qarang). Bo'sh bo'lsa yashirin."""

    def __init__(self, parent=None, *, compact: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("notice")
        self._kind = "error"
        self._compact = bool(compact)
        (margins, gap, icon, column_top, column_gap,
         self._title_px, self._body_px, self._detail_px, self._radius) = _METRICS[self._compact]

        row = QHBoxLayout(self)
        row.setContentsMargins(*margins)
        row.setSpacing(gap)

        self.icon = NoticeIcon(size=icon)
        row.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)

        column = QVBoxLayout()
        # Birinchi qator (sarlavha yoki bitta jumlali matn) ikonka bilan
        # bir o'qda turishi uchun: usiz bir qatorli xabar ikonkadan
        # yuqorida "osilib" qolardi.
        column.setContentsMargins(0, column_top, 0, 0)
        column.setSpacing(column_gap)
        self.title = _wrapped("")
        column.addWidget(self.title)
        self.body = _wrapped("")
        column.addWidget(self.body)

        #: Qo'shimcha mazmun joyi (stol kataklari va h.k.).
        # Chetsiz: bo'sh qolganda ham margin blok ostida ortiqcha bo'shliq
        # qoldirardi. Mazmun o'z chetini o'zi beradi (`SeatNotice.tiles`).
        self.extra = QVBoxLayout()
        self.extra.setContentsMargins(0, 0, 0, 0)
        self.extra.setSpacing(0)
        column.addLayout(self.extra)

        self.detail = _wrapped("")
        self.detail.setContentsMargins(0, 4, 0, 0)
        column.addWidget(self.detail)
        row.addLayout(column, 1)
        self.hide()

    # ------------------------------------------------------------------
    def show_notice(self, kind: str, title: str = "", text: str = "", detail: str = "") -> None:
        self._kind = kind if kind in TONES else "error"
        background, on_color, _accent = TONES[self._kind]
        self.setStyleSheet(
            "QFrame#notice {{ background-color: {}; border: none; border-radius: {}px; }}".format(
                background, self._radius
            )
        )
        self.icon.set_kind(self._kind)
        self.title.setStyleSheet(
            "font-size: {}px; font-weight: 700; background: transparent; color: {};".format(
                self._title_px, on_color)
        )
        self.body.setStyleSheet(
            "font-size: {}px; font-weight: 500; background: transparent; color: {};".format(
                self._body_px, on_color)
        )
        # Server matni — o'sha rangda, lekin kichik va yengil: dalil,
        # asosiy o'qiladigan narsa emas. Ixcham shaklda — tooltip'da.
        self.detail.setStyleSheet(
            "font-size: {}px; background: transparent; color: {};".format(self._detail_px, on_color)
        )
        if self._compact:
            self.setToolTip(detail or "")
            detail = ""
        for label, value in ((self.title, title), (self.body, text), (self.detail, detail)):
            label.setText(value or "")
            label.setVisible(bool(value))
        self.show()
        self._fit()

    def show_message(self, text: str, kind: str = "error", title: str = "") -> None:
        """`MessageBar.show_message` bilan bir xil (+ ixtiyoriy sarlavha)."""
        if not text and not title:
            self.clear_message()
            return
        self.show_notice(kind, title, text)

    def clear_message(self) -> None:
        for label in (self.title, self.body, self.detail):
            label.setText("")
        self.setToolTip("")
        self.setMinimumHeight(0)
        self.hide()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        """
        Minimal balandlik = haqiqiy kenglikdagi mazmun balandligi.

        O'raladigan yorliqli blokni ba'zi konteynerlar (qat'iy kenglikli
        login kartasi, dialog) bir qatorlik balandlikda joylashtiradi va
        oxirgi qator KESILADI - login'da aynan "IP manzil: ..." qatori
        (operator administratorga aytadigan raqam) yo'qolardi.
        `MessageBar._fit` dagi yechimning o'zi, blok darajasida.
        """
        if self.isHidden():
            return
        # Uslub jadvalidagi shrift (14/15 px) yorliqqa POLISH paytida
        # qo'llanadi. Undan oldingi o'lchov standart shrift bilan bo'ladi
        # va layout keshida qoladi - natijada blok goh kesilgan, goh
        # ortiqcha bo'sh chiqardi. Avval polish, keyin keshni tozalash.
        for label in (self.title, self.body, self.detail):
            label.ensurePolished()
        # ICHKI layout'lar ham: `invalidate()` faqat o'z keshini tozalaydi,
        # ustun/`extra` esa eski `heightForWidth` ni qaytarardi — kataklar
        # yashirilgandan keyin blok oldingi balandlikda, ichi bo'sh qolardi.
        _invalidate_tree(self.layout())
        width = self.width()
        if width <= 1 and self.parentWidget() is not None:
            # Hali joylashtirilmagan: ota kenglikdan (chetlarsiz) taxmin.
            width = self.parentWidget().contentsRect().width()
        needed = self.layout().heightForWidth(max(1, width))
        # -1 — o'lchanmagan; `setMinimumHeight(-1)` Qt ogohlantirishi beradi.
        if needed > 0 and needed != self.minimumHeight():
            self.setMinimumHeight(needed)

    def kind(self) -> str:
        return self._kind

    def text(self) -> str:
        """Xabar matni (sarlavha, matn, tafsilot) — testlar va log uchun."""
        parts = [label.text() for label in (self.title, self.body, self.detail) if label.text()]
        if self._compact and self.toolTip():
            parts.append(self.toolTip())
        return "\n".join(parts)
