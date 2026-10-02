"""
Holat indikatorlari: status pill, busy overlay va xabar qatori.

Ular "kutish" holatini har xil miqyosda ko'rsatadi:
    StatusPill      - fon jarayoni (model yuklanmoqda), oqimni to'smaydi
    BusyOverlay     - sahifani to'sadi (API so'rovi ketyapti)
    MessageBar      - natija/xato matni (LAYOUTDA turadi)
    Snackbar        - o'tkinchi xabar, layoutga tegmaydi va o'zi yo'qoladi

Proktorning ARALASHUVI bu yerda emas: u alohida oyna
(`ui/dialogs/warning_dialog.py`). Sabab o'sha faylning izohida -
sahifaning bolasi bo'lgan qoplama `QWebEngineView` ustida
ko'rinmay qolishi mumkin edi.
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

    #: Indikator ranglari - `inverse_surface` (to'q) fonda o'qiladigan MD3
    #: "dark" tonlari (`SNACKBAR_ACCENTS` bilan bir oila).
    STATES = {
        "loading": "#FFB870",
        "ready": "#8DD9A2",
        "error": "#FFB4AB",
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

        # MD3 "inverse" konteyner: to'q neytral fon + och matn. Ilgari fon
        # holat rangining 12% i edi va login sahifasining to'q yashil
        # fonida to'q sariq matn deyarli o'qilmasdi.
        background = QColor(COLORS["inverse_surface"])
        background.setAlpha(235)
        painter.setBrush(QBrush(background))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(0, 0, width, height), height / 2, height / 2)

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

        painter.setPen(QColor(COLORS["inverse_on_surface"]))
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
        # Eng past jiddiylik: "xato" emas, "e'tibor bering".
        "info": (COLORS["accent"], COLORS["info_soft"], "alert"),
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
    """
    Xato/muvaffaqiyat xabari. Bo'sh bo'lsa joy egallamaydi.

    BALANDLIGINI O'ZI HISOBLAYDI (`_fit`). O'raladigan `QLabel` layout'ga
    BIR QATORLIK balandlik aytadi: login kartasida uch qatorli xabar
    ("Tashqi IP manzilga ruxsat yo'q...") 50 px ga siqilib, yarmi
    ko'rinmay qolardi - operator nima qilishni o'qiy olmasdi. Endi
    minimal balandlik haqiqiy kenglikdagi `heightForWidth` ga teng va
    karta xabar sig'guncha o'sadi.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.hide()

    def show_message(self, text: str, kind: str = "error") -> None:
        if not text:
            self.clear_message()
            return
        self.setText(text)
        self.setStyleSheet(message_style(kind))
        self.show()
        self._fit()

    def clear_message(self) -> None:
        self.setText("")
        self.setMinimumHeight(0)
        self.hide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Kenglik layout'da aniqlangach - balandlik shu kenglik bo'yicha.
        self._fit()

    def _fit(self) -> None:
        if not self.text():
            return
        width = self.width()
        if width <= 1 and self.parentWidget() is not None:
            # Hali joylashtirilmagan: ota kenglikdan (chetlarsiz) taxmin.
            width = self.parentWidget().contentsRect().width()
        needed = self.heightForWidth(max(1, width))
        # `heightForWidth` bo'sh/o'lchanmagan yorliqda -1 qaytaradi -
        # `setMinimumHeight(-1)` Qt'da "Negative sizes" ogohlantirishi.
        if needed > 0 and needed != self.minimumHeight():
            self.setMinimumHeight(needed)


#: Snackbar jiddiylik urg'usi - chap chetdagi chiziq rangi.
#:
#: MD3 snackbar BITTA rangda (`inverse_surface`): test sahifasi ustida
#: u har qanday fonda o'qiladi va sahifaning o'z ranglari bilan
#: aralashmaydi. Ilgari xato - och qizil, muvaffaqiyat - och yashil fon
#: edi va oq test sahifasi ustida xabar deyarli ko'rinmasdi. Jiddiylik
#: endi chap chetdagi rangli chiziq bilan - to'q fonda o'qiladigan
#: MD3 "dark" tonlari.
SNACKBAR_ACCENTS = {
    "error": "#FFB4AB",
    "success": "#8DD9A2",
    "warning": "#FFB870",
    "info": "#82D3E0",
}


class Snackbar(QFrame):
    """
    Suzuvchi o'tkinchi xabar (MD3 snackbar). LAYOUTGA TEGMAYDI.

    NIMA UCHUN `MessageBar` YETMAYDI. U layoutning qismi, ya'ni
    ko'ringanda ostidagi hamma narsani PASTGA suradi. Imtihon
    sahifasida ostida `QWebEngineView` turadi va natija ko'rinadigan
    nosozlik edi: "Muammo qayd etildi" degan xabar butun test
    sahifasini pastga surar, xabar esa hech qachon yo'qolmasdi
    (uni hech kim tozalamasdi) — talabgor test oxirigacha siljigan
    sahifa bilan ishlardi.

    Shuning uchun ikki qoida:

      * vidjet ota vidjetning BEVOSITA bolasi va `reposition()` bilan
        joylashtiriladi (layoutda emas);
      * xabar O'ZI yo'qoladi. Muddat jiddiylikka qarab: muvaffaqiyat
        tez, xato uzoq — lekin baribir chekli, chunki ekranda abadiy
        qoladigan xabar birinchi daqiqadan keyin ko'rinmas bo'lib
        qoladi.
    """

    #: Jiddiylik -> qancha ko'rinadi (ms). `0` - o'zi yopilmaydi.
    TIMEOUTS = {"success": 4000, "info": 5000, "warning": 8000, "error": 12000}

    #: Ota vidjet chetidan masofa.
    MARGIN = 18

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("snackbar")
        self._label = QLabel(self)
        self._label.setWordWrap(True)
        box = QVBoxLayout(self)
        box.setContentsMargins(18, 12, 18, 12)
        box.addWidget(self._label)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.clear_message)
        self.hide()

    def show_message(self, text: str, kind: str = "error") -> None:
        if not text:
            self.clear_message()
            return
        self._label.setText(text)
        accent = SNACKBAR_ACCENTS.get(kind, SNACKBAR_ACCENTS["error"])
        # Fon KONTEYNERDA, matn rangi YORLIQDA: `QFrame#snackbar`
        # selektori bolalarga tushmaydi va yorliq rangsiz qolardi.
        self.setStyleSheet(
            """
            QFrame#snackbar {{
                background-color: {bg};
                border: none;
                border-left: 4px solid {accent};
                border-radius: 8px;
            }}
            """.format(bg=COLORS["inverse_surface"], accent=accent)
        )
        self._label.setStyleSheet(
            "color: {}; font-size: 14px; font-weight: 600; "
            "background: transparent; border: none;".format(COLORS["inverse_on_surface"])
        )
        self.reposition()
        self.raise_()
        self.show()
        timeout = self.TIMEOUTS.get(kind, 8000)
        self._timer.stop()
        if timeout:
            self._timer.start(timeout)

    def clear_message(self) -> None:
        self._timer.stop()
        self._label.setText("")
        self.hide()

    def mousePressEvent(self, event) -> None:
        """Bosilganda yopiladi - kutish shart emas."""
        self.clear_message()
        event.accept()

    def reposition(self) -> None:
        """
        Ota vidjetning PASTKI-CHAP burchagiga qo'yadi.

        Pastda: tepa qism test platformasining o'z sarlavhasi uchun
        ochiq qolishi kerak. Chapda: pastki o'ng burchakda suzuvchi
        boshqaruv paneli turadi (`exam_webview_page`) va ular
        bir-birining ustiga tushmasligi kerak.
        """
        parent = self.parentWidget()
        if parent is None:
            return
        width = min(560, max(320, int(parent.width() * 0.5)))
        self.setFixedWidth(width)
        self.adjustSize()
        self.move(
            self.MARGIN, max(self.MARGIN, parent.height() - self.height() - self.MARGIN)
        )


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
