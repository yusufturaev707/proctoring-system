"""
Holat indikatorlari: status pill, busy overlay va xabar qatori.

Uchalasi ham "kutish" holatini ko'rsatadi, lekin har xil miqyosda:
    StatusPill   - fon jarayoni (model yuklanmoqda), oqimni to'smaydi
    BusyOverlay  - sahifani to'sadi (API so'rovi ketyapti)
    MessageBar   - natija/xato matni
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from ui.styles import COLORS, message_style


class StatusPill(QWidget):
    """
    Kichik holat indikatori (aylanuvchi yoy / nuqta + matn).

    Referens loyihadagi yondashuv: model yuklanishi login formasini
    BLOKLAMAYDI, faqat burchakda holat ko'rinib turadi. Operator shu
    payt login/parol yozadi va model odatda undan oldin tayyor bo'ladi.
    """

    STATES = {
        "loading": COLORS["warning"],
        "ready": COLORS["primary"],
        "error": COLORS["error"],
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._state = "loading"
        self._label = "Tizim tayyorlanmoqda..."
        self._angle = 0
        self.setFixedHeight(34)
        self.setMinimumWidth(240)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(30)

    def set_state(self, state: str, label: str = "") -> None:
        self._state = state if state in self.STATES else "loading"
        if label:
            self._label = label
        self.update()

    def _tick(self) -> None:
        if self._state == "loading":
            self._angle = (self._angle + 9) % 360
            self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        color = QColor(self.STATES[self._state])

        background = QColor(color)
        background.setAlpha(30)
        border = QColor(color)
        border.setAlpha(90)
        painter.setBrush(QBrush(background))
        painter.setPen(QPen(border, 1))
        painter.drawRoundedRect(QRectF(0.5, 0.5, width - 1, height - 1), height / 2, height / 2)

        cx, cy, radius = 17.0, height / 2, 7.0
        if self._state == "loading":
            faint = QColor(color)
            faint.setAlpha(70)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(faint, 2.2))
            painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))
            pen = QPen(color, 2.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            # drawArc 1/16 gradus birligida ishlaydi.
            painter.drawArc(
                QRectF(cx - radius, cy - radius, radius * 2, radius * 2),
                int(-self._angle * 16),
                int(110 * 16),
            )
        else:
            halo = QColor(color)
            halo.setAlpha(60)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(halo))
            painter.drawEllipse(QRectF(cx - radius - 3, cy - radius - 3, (radius + 3) * 2, (radius + 3) * 2))
            painter.setBrush(QBrush(color))
            painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))

        painter.setPen(color.darker(135))
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        painter.drawText(
            QRectF(cx + radius + 10, 0, width - (cx + radius + 16), height),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self._label,
        )
        painter.end()


class StateBadge(QWidget):
    """
    Material Design 3 uslubidagi katta holat nishoni (tonal konteyner).

    `StatusPill` dan farqi miqyosda va vazifada: pill - fon jarayoni
    haqidagi kichik eslatma, badge esa sahifaning O'ZI nima holatda
    ekanini bir qarashda aytadi. Rang va belgi birga o'zgaradi -
    faqat rangga tayanish rang ajratolmaydigan operator uchun
    ma'lumotni yo'qotadi.
    """

    #: holat -> (rang, tonal fon, belgi)
    STATES = {
        "loading": (COLORS["primary"], COLORS["primary_soft"], "spinner"),
        "ready": (COLORS["primary"], COLORS["success_soft"], "check"),
        "error": (COLORS["error"], COLORS["error_soft"], "block"),
        "warning": (COLORS["warning"], COLORS["warning_soft"], "alert"),
    }

    def __init__(self, parent=None, size: int = 76) -> None:
        super().__init__(parent)
        self._state = "loading"
        self._angle = 0
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(28)

    def set_state(self, state: str) -> None:
        self._state = state if state in self.STATES else "loading"
        self.update()

    def _tick(self) -> None:
        # Faqat aylanayotgan holatda qayta chizamiz - qolgan holatlarda
        # rasm o'zgarmaydi va sekundiga 36 marta chizish bekor sarf.
        if self._state == "loading" and self.isVisible():
            self._angle = (self._angle + 8) % 360
            self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color_name, tonal_name, symbol = self.STATES[self._state]
        color = QColor(color_name)
        size = min(self.width(), self.height())
        box = QRectF(0.5, 0.5, size - 1, size - 1)

        # MD3 tonal konteyner: yumshoq fon + kuchli belgi.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(tonal_name)))
        painter.drawRoundedRect(box, size * 0.28, size * 0.28)

        center = size / 2
        radius = size * 0.26

        if symbol == "spinner":
            faint = QColor(color)
            faint.setAlpha(70)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(faint, 3.2))
            painter.drawEllipse(QRectF(center - radius, center - radius, radius * 2, radius * 2))
            pen = QPen(color, 3.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawArc(
                QRectF(center - radius, center - radius, radius * 2, radius * 2),
                int(-self._angle * 16),
                int(110 * 16),
            )
        elif symbol == "check":
            pen = QPen(color, 4.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPolyline(
                QPointF(center - radius * 0.75, center),
                QPointF(center - radius * 0.15, center + radius * 0.6),
                QPointF(center + radius * 0.8, center - radius * 0.6),
            )
        elif symbol == "block":
            # Aylana + diagonal chiziq: "kirish yo'q" belgisining
            # umumiy qabul qilingan shakli, tarjima talab qilmaydi.
            pen = QPen(color, 3.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(center - radius, center - radius, radius * 2, radius * 2))
            offset = radius * 0.7071
            painter.drawLine(
                QPointF(center - offset, center - offset),
                QPointF(center + offset, center + offset),
            )
        else:  # alert
            pen = QPen(color, 4.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(
                QPointF(center, center - radius * 0.85),
                QPointF(center, center + radius * 0.15),
            )
            painter.drawPoint(QPointF(center, center + radius * 0.72))
        painter.end()


class BusyOverlay(QWidget):
    """
    Sahifani to'suvchi spinner.

    API so'rovi ketayotganda ko'rsatiladi: operator nima bo'layotganini
    ko'radi va shu paytda tugmalarni qayta bosa olmaydi. Tugmalarni
    `setEnabled(False)` qilishning o'zi yetarli emas - sabab
    ko'rinmaydi va operator "osilib qoldi" deb o'ylaydi.
    """

    def __init__(self, parent=None, text: str = "Yuklanmoqda...") -> None:
        super().__init__(parent)
        self._angle = 0
        self._text = text
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.hide()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def start(self, text: str = "") -> None:
        if text:
            self._text = text
        if self.parent() is not None:
            self.setGeometry(self.parent().rect())
        self.raise_()
        self.show()
        self._timer.start(28)

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    @property
    def is_busy(self) -> bool:
        return self.isVisible()

    def _tick(self) -> None:
        self._angle = (self._angle + 10) % 360
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(15, 23, 42, 120))

        cx, cy = self.width() / 2, self.height() / 2 - 14
        radius = 22.0
        color = QColor(COLORS["primary_light"])

        faint = QColor(color)
        faint.setAlpha(70)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(faint, 4))
        painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))

        pen = QPen(color, 4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(
            QRectF(cx - radius, cy - radius, radius * 2, radius * 2),
            int(-self._angle * 16),
            int(100 * 16),
        )

        painter.setPen(QColor("#FFFFFF"))
        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        painter.drawText(
            QRectF(0, cy + radius + 12, self.width(), 30),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
            self._text,
        )
        painter.end()


class MessageBar(QLabel):
    """Xato/muvaffaqiyat xabari. Bo'sh bo'lsa joy egallamaydi."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hide()

    def show_message(self, text: str, kind: str = "error") -> None:
        if not text:
            self.clear_message()
            return
        self.setText(text)
        self.setStyleSheet(message_style(kind))
        self.show()

    def clear_message(self) -> None:
        self.setText("")
        self.hide()


class Card(QFrame):
    """
    Sarlavha + tarkibli oq karta (sahifalarda takrorlanadigan blok).

    QFrame (QWidget emas): global uslubdagi `QFrame[role="card"]`
    selektori faqat QFrame'ga tushadi.
    """

    def __init__(self, title: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setProperty("role", "card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)
        if title:
            label = QLabel(title)
            label.setProperty("role", "value")
            layout.addWidget(label)
        self.body = layout
