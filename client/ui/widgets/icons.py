"""
Chiziladigan ikonkalar.

NIMA UCHUN SHRIFT GLIFI EMAS. Unicode belgilari (⟳, ↻, ⭯) Windows'ning
barcha o'rnatishlarida mavjud emas: ular "Segoe UI Symbol" ga tegishli
va u ba'zi tizim tasvirlarida (Windows LTSC, minimal o'rnatish)
bo'lmasligi mumkin. Glif topilmasa Qt uning o'rniga BO'SH KVADRAT
chizadi - operator uchun bu "bosiladigan narsami yoki nosozlikmi?"
degan savol, ya'ni eng yomon holat.

NIMA UCHUN RASM FAYLI HAM EMAS. Loyihada ikonka resurslari yo'q va
ularni qo'shish PyInstaller paketiga yangi bog'liqlik (`.qrc` yoki
`--add-data`) kiritadi. Bitta ikonka uchun bu ortiqcha.

Chizilgan ikonka uchala muammoni ham yopadi: u har doim chiziladi,
istalgan o'lchamda tiniq qoladi (vektor) va hech qanday faylga
bog'liq emas.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QPushButton, QWidget

from ui.styles import COLORS

#: Ikonka tugmasi uchun uslub (o'lcham bilan formatlanadi).
#:
#: O'LCHAM AYNAN SHU YERDA ham beriladi, `setFixedSize` bilan birga.
#: Sabab Qt uslub jadvalining ustunligida: global qoidadagi
#: `QPushButton { padding: 12px 26px; min-height: 44px }` widget'ning
#: minimal o'lchamini BOSIB KETADI va tugma layoutda 88x68 joy
#: so'raydi. Uni shunchaki `min-*: 0` bilan bekor qilish esa teskari
#: tomonga og'diradi: o'shanda minimal o'lcham NOL bo'lib qoladi va
#: layout tugmani nuqta balandligiga (22 px) qadar siqib qo'yadi.
#: Aniq qiymat ikkala chekkani ham yopadi.
_ICON_BUTTON_QSS = """
    QPushButton {{
        background: transparent;
        border: none;
        padding: 0;
        margin: 0;
        min-width: {size}px;
        min-height: {size}px;
        max-width: {size}px;
        max-height: {size}px;
    }}
"""

#: Aylanish tezligi (gradus / kadr) va kadr oralig'i (ms).
#:
#: 60 FPS da 6 gradus - bir aylanish ~1 soniya. Bu "ishlayapti" degan
#: signal uchun yetarli va ko'zni charchatmaydi.
_SPIN_STEP = 6
_SPIN_INTERVAL_MS = 16


class RefreshButton(QPushButton):
    """
    Dumaloq "yangilash" tugmasi (MD3 standard icon button).

    Yuklanish paytida ikonka AYLANADI. Bu matnli holatning o'rnini
    bosadi: ilgari tugma matni "Yangilanmoqda..." ga o'zgarardi va u
    tugmaga sig'masdi (Qt uni qisqartirib yuborardi). Aylanish esa
    joy talab qilmaydi va u universal tushuniladigan signal.
    """

    def __init__(self, size: int = 40, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Yangilash")
        # Ramka va fon `paintEvent` da chiziladi - uslub jadvalidagi
        # standart `QPushButton` qoidasi (yashil to'ldirish) bu yerda
        # keraksiz.
        #
        # `padding` va `min-*` ham NOLGA tushiriladi: global uslub
        # jadvalidagi `QPushButton { padding: 12px 26px; min-height:
        # 44px }` ikonka tugmasining `sizeHint` ini 88x68 ga
        # shishiradi va layout o'sha o'lchamga joy ajratadi -
        # `setFixedSize` ko'rinishni to'g'rilaydi, lekin atrofida
        # bo'sh joy qolib ketadi.
        self.setStyleSheet(_ICON_BUTTON_QSS.format(size=size))

        self._angle = 0
        self._busy = False
        self._timer = QTimer(self)
        self._timer.setInterval(_SPIN_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------
    def set_busy(self, busy: bool) -> None:
        if busy == self._busy:
            return
        self._busy = busy
        self.setEnabled(not busy)
        if busy:
            self._timer.start()
        else:
            self._timer.stop()
            self._angle = 0
        self.update()

    @property
    def is_busy(self) -> bool:
        return self._busy

    def _tick(self) -> None:
        # Manfiy: soat strelkasi yo'nalishida aylanadi. Qt burchaklari
        # soat strelkasiga TESKARI hisoblanadi, "yangilash" ikonkasi esa
        # hamma joyda soat yo'nalishida aylanadi.
        self._angle = (self._angle - _SPIN_STEP) % 360
        self.update()

    # ------------------------------------------------------------------
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        side = min(self.width(), self.height())
        center = QPointF(self.width() / 2, self.height() / 2)

        # --- Holat foni (MD3 state layer) ---
        if not self.isEnabled():
            color = QColor(COLORS["text_muted"])
        elif self.isDown():
            color = QColor(COLORS["on_primary"])
            painter.setBrush(QColor(COLORS["primary"]))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(center, side / 2, side / 2)
        elif self.underMouse():
            color = QColor(COLORS["primary_dark"])
            painter.setBrush(QColor(COLORS["primary_soft"]))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(center, side / 2, side / 2)
        else:
            color = QColor(COLORS["text_secondary"])

        # Yuklanish paytida ikonka urg'uli rangda: aylanishning o'zi
        # ko'rinmasligi mumkin (sekin mashinada kadrlar tushib qoladi),
        # rang esa har doim ko'rinadi.
        if self._busy:
            color = QColor(COLORS["primary"])

        self._draw_glyph(painter, center, side * 0.30, color)
        painter.end()

    def _draw_glyph(self, painter: QPainter, center: QPointF, radius: float, color: QColor) -> None:
        """
        Ochiq halqa + uchidagi strelka.

        Halqa 270 gradus: to'liq aylana "yuklanmoqda" indikatoriga
        o'xshab qolardi va strelka uchun joy qolmasdi.
        """
        start_deg = 55 + self._angle
        span_deg = 270

        pen = QPen(color, max(2.0, radius * 0.26))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # `drawArc` 1/16 gradus birligida ishlaydi.
        painter.drawArc(
            QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2),
            int(start_deg * 16),
            int(span_deg * 16),
        )

        # Strelka yoyning OXIRIDA va uning urinma yo'nalishida.
        #
        # Qt'da y pastga o'sadi, burchak esa soat strelkasiga teskari:
        #     P(t) = (cx + r*cos t, cy - r*sin t)
        # Demak t ortgan sari yo'nalish (-sin t, -cos t) bo'ladi.
        end = math.radians(start_deg + span_deg)
        tip_dir = QPointF(-math.sin(end), -math.cos(end))
        normal = QPointF(tip_dir.y(), -tip_dir.x())
        point = QPointF(
            center.x() + radius * math.cos(end),
            center.y() - radius * math.sin(end),
        )

        head = radius * 0.62
        arrow = QPolygonF(
            [
                QPointF(point.x() + tip_dir.x() * head, point.y() + tip_dir.y() * head),
                QPointF(
                    point.x() - tip_dir.x() * head * 0.35 + normal.x() * head * 0.72,
                    point.y() - tip_dir.y() * head * 0.35 + normal.y() * head * 0.72,
                ),
                QPointF(
                    point.x() - tip_dir.x() * head * 0.35 - normal.x() * head * 0.72,
                    point.y() - tip_dir.y() * head * 0.35 - normal.y() * head * 0.72,
                ),
            ]
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(arrow)

    # ------------------------------------------------------------------
    def enterEvent(self, event) -> None:
        # `underMouse()` o'zgarishi avtomatik qayta chizishni
        # QO'ZG'ATMAYDI - fon holati qo'lda yangilanadi.
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.update()
        super().leaveEvent(event)


#: Puls animatsiyasi: halqa shuncha ms davomida kengayib so'nadi.
#:
#: 1.4 s - yurak urishiga yaqin va u "tirik, lekin shoshilinch emas"
#: degan signal beradi. Tezroq puls imtihon ekranida bezovta qiladi:
#: talabgor butun imtihon davomida shu ekranga qaraydi.
_PULSE_PERIOD_MS = 1400
_PULSE_INTERVAL_MS = 40


class StatusDot(QWidget):
    """
    Aloqa holati - kichik nuqta.

    NIMA UCHUN MATN EMAS. Bu belgi imtihon sahifasining USTIDA
    turadi va u yerda har bir piksel platformaga tegishli. "Aloqa
    bor" degan yozuv doimiy ravishda joy egallardi, holbuki u
    99% vaqt bir xil narsani aytadi.

    ANIMATSIYA FAQAT QIZIL HOLATDA. Doimiy pulsatsiya diqqatni
    talab qiladi va u faqat haqiqatan e'tibor kerak bo'lganda
    o'rinli: aloqa yo'q - hodisalar yuborilmayapti, ya'ni dalil
    yig'ilmayapti. Yashil holat esa tinch turadi - "hammasi
    joyida" degan xabar ko'zni tortmasligi kerak.

    Tafsilot TOOLTIP'da: FaceID, skrinshot va kuzatuv holati
    ilgari sarlavhada alohida nishonlar edi. Ular yo'qolmadi -
    ekrandan olib tashlandi va shu yerga ko'chdi.
    """

    def __init__(self, size: int = 14, parent=None) -> None:
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size + 10, size + 10)
        self._online = True
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(_PULSE_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

    def set_online(self, online: bool) -> None:
        if online == self._online:
            return
        self._online = online
        if online:
            self._timer.stop()
            self._phase = 0.0
        else:
            self._timer.start()
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + _PULSE_INTERVAL_MS / _PULSE_PERIOD_MS) % 1.0
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(self.width() / 2, self.height() / 2)
        radius = self._size / 2
        color = QColor(COLORS["primary"] if self._online else COLORS["error"])

        # Kengayib so'nuvchi halqa - "puls".
        if not self._online:
            halo = QColor(color)
            halo.setAlphaF(max(0.0, 0.45 * (1.0 - self._phase)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(halo)
            painter.drawEllipse(center, radius + self._phase * 5, radius + self._phase * 5)

        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, radius, radius)
        painter.end()


class GlyphButton(QPushButton):
    """
    Dumaloq ikonka tugmasi - chizilgan glif bilan.

    `RefreshButton` bilan bir xil sababdan chizilgan, shrift glifi
    emas: Unicode belgisi tizim tasvirida bo'lmasa Qt bo'sh kvadrat
    chizadi va operator "bu tugmami yoki nosozlikmi?" degan savol
    bilan qoladi (modul docstring'iga qarang).
    """

    #: Chizish qoidalari: nom -> chizuvchi metod.
    GLYPHS = ("warning", "power")

    def __init__(self, glyph: str, *, size: int = 40, tone: str = "neutral",
                 tooltip: str = "", parent=None) -> None:
        super().__init__(parent)
        self._glyph = glyph if glyph in self.GLYPHS else "warning"
        self._tone = tone
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)
        self.setStyleSheet(_ICON_BUTTON_QSS.format(size=size))

    # ------------------------------------------------------------------
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height())
        center = QPointF(self.width() / 2, self.height() / 2)

        accent = COLORS["error"] if self._tone == "danger" else COLORS["text_secondary"]
        soft = COLORS["error_soft"] if self._tone == "danger" else COLORS["surface_alt"]

        # MD3 "state layer": fon faqat hover/bosishda paydo bo'ladi.
        if self.isDown() or self.underMouse():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(soft))
            painter.drawEllipse(center, side / 2, side / 2)

        color = QColor(accent)
        if self.isDown():
            color = QColor(COLORS["error"] if self._tone == "danger" else COLORS["text"])

        if self._glyph == "power":
            self._draw_power(painter, center, side * 0.28, color)
        else:
            self._draw_warning(painter, center, side * 0.30, color)
        painter.end()

    @staticmethod
    def _draw_warning(painter: QPainter, center: QPointF, radius: float, color: QColor) -> None:
        """Uchburchak + undov belgisi."""
        triangle = QPolygonF(
            [
                QPointF(center.x(), center.y() - radius),
                QPointF(center.x() + radius, center.y() + radius * 0.78),
                QPointF(center.x() - radius, center.y() + radius * 0.78),
            ]
        )
        pen = QPen(color, max(1.6, radius * 0.22))
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolygon(triangle)

        painter.drawLine(
            QPointF(center.x(), center.y() - radius * 0.26),
            QPointF(center.x(), center.y() + radius * 0.20),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(center.x(), center.y() + radius * 0.48), radius * 0.11, radius * 0.11)

    @staticmethod
    def _draw_power(painter: QPainter, center: QPointF, radius: float, color: QColor) -> None:
        """Yakunlash: ochiq halqa + tepadagi chiziq (power belgisi)."""
        pen = QPen(color, max(1.6, radius * 0.24))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        rect = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
        # Qt burchagi 1/16 gradusda; 300 gradus yoy, tepasi ochiq.
        painter.drawArc(rect, int(-60 * 16), int(300 * 16))
        painter.drawLine(
            QPointF(center.x(), center.y() - radius * 1.15),
            QPointF(center.x(), center.y() - radius * 0.10),
        )

    # ------------------------------------------------------------------
    def enterEvent(self, event) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.update()
        super().leaveEvent(event)
