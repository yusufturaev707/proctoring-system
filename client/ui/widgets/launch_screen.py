"""
"Test ochilmoqda" ekrani — yuz tasdig'idan test platformasi chizilguncha.

NIMA UCHUN KERAK. Shu oraliqda ketma-ket: serverda kuzatuv ochiladi
(`proctoring/start/`), Chromium ishga tushadi (birinchi profil/sahifa —
UI thread'ida 0.4-1.5 s), kamera kuzatuvga topshiriladi va platforma
yuklanadi. Ilgari qoplama birinchi qadamdan keyin yopilardi va talabgor
3-4 soniya BO'SH ekranga qarab turardi - "dastur qotdi" degan taassurot.
Endi ekran platformaning BIRINCHI MUVAFFAQIYATLI yuklanishigacha turadi
va har qadam ko'rinadi; oxirgi qadamda progress sahifaning haqiqiy
yuklanish foizini ko'rsatadi.

MD3: to'liq ekran `surface_bright` fon, markazda `surface_container_lowest`
karta (28 px), qadamlar ro'yxati va "linear progress indicator" (4 px,
yumaloq uchli, trek - `primary_container`). Yo'qolishi - 220 ms fade.

BUTUNLAY QPainter BILAN. Global uslubdagi `QWidget { background }`
qoidasi bola vidjetlarga fon berib, kartani to'rtburchak qilib
qo'yardi (`exam_webview_page._build_floating_bar` izohi); bitta
`paintEvent` esa animatsiyani arzon qiladi - u asosiy thread band
bo'lgan qisqa lahzalardan keyin darhol davom etadi.

Sahifa uni brauzer USTIDA ushlaydi; sichqoncha bosishlari yutiladi -
talabgor yarim yuklangan sahifani bosa olmasligi kerak.
"""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QRectF, Qt, QTimer, QVariantAnimation
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QWidget

from ui.styles import COLORS

#: Qadamlar - `ExamWebViewPage` ularni tartib bilan o'tkazadi.
STEP_PROCTORING = 0
STEP_BROWSER = 1
STEP_PLATFORM = 2
#: (jarayonda, bajarildi) - bajarilgan qadam o'tgan zamonda o'qiladi.
STEPS = (
    ("Kuzatuv ishga tushirilmoqda", "Kuzatuv ishga tushirildi"),
    ("Xavfsiz brauzer tayyorlanmoqda", "Xavfsiz brauzer tayyor"),
    ("Test platformasi yuklanmoqda", "Test platformasi ochildi"),
)

_CARD_MAX_W = 520
_CARD_RADIUS = 28.0
_TICK_MS = 16
#: Shu vaqtdan keyin izoh "sekin ochilmoqda" ga almashadi.
_SLOW_AFTER_MS = 12_000
#: Xavfsizlik chegarasi: ekran hech qachon abadiy qolmaydi. Odatda
#: undan oldin Chromium o'zi xato beradi va sahifaning xato ekrani
#: ochiladi.
_GIVE_UP_MS = 45_000
_FADE_MS = 220

_HINT = "Iltimos, kuting. Klaviatura va sichqonchaga tegmang."
_SLOW_HINT = ("Sahifa odatdagidan sekin ochilmoqda — internet aloqasi sust "
              "bo'lishi mumkin. Kuting, ochilmasa xabar chiqadi.")


def _color(key: str, alpha: int = 255) -> QColor:
    color = QColor(COLORS[key])
    color.setAlpha(alpha)
    return color


class LaunchScreen(QWidget):
    """`begin()` -> `advance()` ... -> `set_progress()` -> `finish()` / `dismiss()`."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.hide()
        self._subtitle = ""
        self._active = STEP_PROCTORING
        self._progress = -1  # -1 - noaniq (indeterminate)
        self._phase = 0
        self._opacity = 1.0
        self._hint = _HINT
        self._geometry: dict | None = None
        self._static: QPixmap | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._tick)

        self._slow = QTimer(self)
        self._slow.setSingleShot(True)
        self._slow.timeout.connect(self._on_slow)

        self._give_up = QTimer(self)
        self._give_up.setSingleShot(True)
        self._give_up.timeout.connect(self.finish)

        self._fade = QVariantAnimation(self)
        self._fade.setDuration(_FADE_MS)
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.valueChanged.connect(self._on_fade)
        self._fade.finished.connect(self._hide_now)

        try:
            from ui.widgets.brand import logo_pixmap

            self._logo = logo_pixmap(40, dpr=self.devicePixelRatioF())
        except Exception:  # noqa: BLE001 - logotip bezak
            self._logo = None

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------
    @property
    def is_active(self) -> bool:
        return self.isVisible() and self._fade.state() != QVariantAnimation.State.Running

    def begin(self, subtitle: str = "") -> None:
        self._fade.stop()
        self._subtitle = subtitle
        self._active = STEP_PROCTORING
        self._progress = -1
        self._opacity = 1.0
        self._hint = _HINT
        self._static = None
        if self.parentWidget() is not None:
            self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self._timer.start()
        self._slow.start(_SLOW_AFTER_MS)
        self._give_up.start(_GIVE_UP_MS)

    def advance(self, step: int) -> None:
        """
        Keyingi qadam. DARHOL chiziladi (`repaint`): chaqiruvchi odatda
        shundan keyin UI thread'ini bir lahza band qiladi (Chromium,
        kamera) va oddiy `update()` o'sha ish tugaguncha kechikardi.
        """
        if not self.isVisible():
            return
        self._active = max(self._active, step)
        self._progress = -1
        self.repaint()

    def set_progress(self, percent: int) -> None:
        if not self.isVisible() or self._active != STEP_PLATFORM:
            return
        percent = max(0, min(100, int(percent)))
        # Faqat oldinga: yo'naltirish (redirect) yangi yuklanishni
        # 0 dan boshlaydi va chiziq orqaga sakrab "qayta boshlandi"
        # degan noto'g'ri signal berardi.
        if percent > self._progress:
            self._progress = percent
            self.update(self._layout()["dynamic"])

    def finish(self) -> None:
        """Hammasi tayyor - silliq yo'qoladi."""
        if not self.isVisible() or self._fade.state() == QVariantAnimation.State.Running:
            return
        self._active = len(STEPS)
        self._progress = 100
        self._stop_timers()
        self._fade.start()

    def dismiss(self) -> None:
        """Darhol yopiladi - xato ekrani yoki boshqa sahifa o'rnini oladi."""
        self._fade.stop()
        self._hide_now()

    # ------------------------------------------------------------------
    def _stop_timers(self) -> None:
        self._slow.stop()
        self._give_up.stop()

    def _hide_now(self) -> None:
        self._stop_timers()
        self._timer.stop()
        self._opacity = 1.0
        self.hide()

    def _on_fade(self, value) -> None:
        self._opacity = float(value)
        self.update()

    def _on_slow(self) -> None:
        self._hint = _SLOW_HINT
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 1) % 100_000
        self.update(self._layout()["dynamic"])

    # ------------------------------------------------------------------
    # Chizish
    # ------------------------------------------------------------------
    # Ikki qatlam: STATIK (fon, soya, karta, logotip, sarlavha, izoh) bir
    # marta `QPixmap` ga chiziladi; har kadrda faqat DINAMIK qism -
    # qadamlar va progress (`_dynamic` maydoni, `update(rect)`). Butun
    # ekranni 60 kadr/s qayta chizish 1080p da ~6.5 ms/kadr edi va u
    # Chromium bilan BITTA thread'da - sahifa yuklanishini sekinlatardi.
    def _layout(self) -> dict:
        key = (self.width(), self.height(), self._hint)
        if self._geometry is not None and self._geometry["key"] == key:
            return self._geometry
        card_w = float(min(_CARD_MAX_W, self.width() - 48))
        pad = 32.0
        logo_h = 40.0 if self._logo is not None and not self._logo.isNull() else 0.0
        row_h = 40.0
        hint_font = self._font(13)
        hint_h = float(QFontMetrics(hint_font).boundingRect(
            0, 0, int(card_w - pad * 2), 1000, int(Qt.TextFlag.TextWordWrap), self._hint
        ).height())
        card_h = (pad + (logo_h + 18 if logo_h else 0) + 30 + 6 + 22 + 22
                  + row_h * len(STEPS) + 18 + 4 + 18 + hint_h + pad)
        card = QRectF((self.width() - card_w) / 2, (self.height() - card_h) / 2, card_w, card_h)
        x, width = card.left() + pad, card.width() - pad * 2
        y = card.top() + pad
        logo_y = y
        y += logo_h + 18 if logo_h else 0
        title_y = y
        y += 30 + 6
        subtitle_y = y
        y += 22 + 22
        steps_y = y
        y += row_h * len(STEPS) + 18
        bar = QRectF(x, y, width, 4)
        y += 4 + 18
        self._geometry = {
            "key": key, "card": card, "x": x, "width": width, "logo_h": logo_h,
            "logo_y": logo_y, "title_y": title_y, "subtitle_y": subtitle_y,
            "steps_y": steps_y, "row_h": row_h, "bar": bar,
            "hint": QRectF(x, y, width, hint_h), "hint_font": hint_font,
            "dynamic": QRectF(x - 4, steps_y, width + 8, bar.bottom() - steps_y + 4).toAlignedRect(),
        }
        self._static = None
        return self._geometry

    def _static_layer(self, geo: dict) -> QPixmap:
        dpr = self.devicePixelRatioF()
        if self._static is not None and self._static.devicePixelRatio() == dpr:
            return self._static
        pixmap = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(_color("surface_bright"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        card, x, width = geo["card"], geo["x"], geo["width"]

        # MD3 elevation 2: yumshoq soya - ko'p yupqa shaffof qatlam
        # (bir nechta qalin qatlam pastda qattiq chiziq bo'lib qolardi).
        painter.setPen(Qt.PenStyle.NoPen)
        for spread in range(1, 17):
            painter.setBrush(QColor(16, 32, 20, 2))
            painter.drawRoundedRect(card.adjusted(-spread, -spread + 4, spread, spread + 4),
                                    _CARD_RADIUS + spread, _CARD_RADIUS + spread)
        painter.setBrush(_color("surface_container_lowest"))
        painter.drawRoundedRect(card, _CARD_RADIUS, _CARD_RADIUS)

        if geo["logo_h"]:
            logo_h = geo["logo_h"]
            logo_w = logo_h * self._logo.width() / max(1, self._logo.height())
            painter.drawPixmap(QRectF(card.center().x() - logo_w / 2, geo["logo_y"], logo_w, logo_h),
                               self._logo, QRectF(self._logo.rect()))

        painter.setFont(self._font(22, QFont.Weight.Bold))
        painter.setPen(_color("on_surface"))
        painter.drawText(QRectF(x, geo["title_y"], width, 30),
                         int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                         "Test ochilmoqda")
        if self._subtitle:
            font = self._font(14)
            painter.setFont(font)
            painter.setPen(_color("on_surface_variant"))
            text = QFontMetrics(font).elidedText(self._subtitle, Qt.TextElideMode.ElideRight, int(width))
            painter.drawText(QRectF(x, geo["subtitle_y"], width, 22),
                             int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter), text)

        painter.setFont(geo["hint_font"])
        painter.setPen(_color("outline"))
        painter.drawText(geo["hint"], int(Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap),
                         self._hint)
        painter.end()
        self._static = pixmap
        return pixmap

    def paintEvent(self, event) -> None:
        geo = self._layout()
        painter = QPainter(self)
        painter.setOpacity(self._opacity)
        painter.drawPixmap(0, 0, self._static_layer(geo))
        if not event.rect().intersects(geo["dynamic"]):
            painter.end()
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        # Karta foni dinamik maydon ostida qayta - eski kadr izi qolmasin.
        painter.fillRect(geo["dynamic"], _color("surface_container_lowest"))
        y = geo["steps_y"]
        for index, (active_label, done_label) in enumerate(STEPS):
            label = done_label if index < self._active else active_label
            self._draw_step(painter, QRectF(geo["x"], y, geo["width"], geo["row_h"]), index, label)
            y += geo["row_h"]
        self._draw_progress(painter, geo["bar"])
        painter.end()

    def _draw_step(self, painter: QPainter, row: QRectF, index: int, label: str) -> None:
        size = 22.0
        icon = QRectF(row.left() + 4, row.center().y() - size / 2, size, size)
        if index < self._active:
            # Bajarildi: to'ldirilgan doira + oq belgi.
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_color("primary"))
            painter.drawEllipse(icon)
            pen = QPen(_color("on_primary"), 2.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath()
            path.moveTo(icon.left() + size * 0.28, icon.top() + size * 0.52)
            path.lineTo(icon.left() + size * 0.44, icon.top() + size * 0.68)
            path.lineTo(icon.left() + size * 0.73, icon.top() + size * 0.36)
            painter.drawPath(path)
            text_color, weight = _color("on_surface_variant"), QFont.Weight.Normal
        elif index == self._active:
            # Joriy: MD3 "circular progress" - trek + aylanayotgan yoy.
            ring = icon.adjusted(2, 2, -2, -2)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(_color("primary_container"), 3))
            painter.drawEllipse(ring)
            pen = QPen(_color("primary"), 3)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawArc(ring, int(-(self._phase * 9 % 360) * 16), int(110 * 16))
            text_color, weight = _color("on_surface"), QFont.Weight.DemiBold
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(_color("outline_variant"), 2))
            painter.drawEllipse(icon.adjusted(2, 2, -2, -2))
            text_color, weight = _color("outline"), QFont.Weight.Normal

        painter.setFont(self._font(15, weight))
        painter.setPen(text_color)
        text_rect = QRectF(icon.right() + 14, row.top(), row.width() - size - 18, row.height())
        if index == STEP_PLATFORM and index == self._active and self._progress >= 0:
            label = "{} — {}%".format(label, self._progress)
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), label)

    def _draw_progress(self, painter: QPainter, track: QRectF) -> None:
        radius = track.height() / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_color("primary_container"))
        painter.drawRoundedRect(track, radius, radius)
        painter.setBrush(_color("primary"))

        if self._progress >= 0 or self._active >= len(STEPS):
            # Aniq: qadamlar ulushi + oxirgi qadam ichida sahifa foizi.
            share = 1.0 / len(STEPS)
            done = min(self._active, len(STEPS)) * share
            if self._active == STEP_PLATFORM:
                done += share * max(0, self._progress) / 100.0
            fill = QRectF(track.left(), track.top(), track.width() * min(1.0, done), track.height())
            if fill.width() > 0:
                painter.drawRoundedRect(fill, radius, radius)
            return

        # Noaniq: bo'lak trek bo'ylab yuguradi (MD3 indeterminate).
        period = 110
        t = (self._phase % period) / period
        eased = QEasingCurve(QEasingCurve.Type.InOutCubic).valueForProgress(t)
        seg = track.width() * 0.32
        left = track.left() - seg + (track.width() + seg) * eased
        start = max(track.left(), left)
        end = min(track.right(), left + seg)
        if end > start:
            painter.drawRoundedRect(QRectF(start, track.top(), end - start, track.height()), radius, radius)

    @staticmethod
    def _font(pixel_size: int, weight=QFont.Weight.Normal) -> QFont:
        font = QFont()
        font.setFamilies(["Segoe UI", "Inter", "Roboto"])
        font.setPixelSize(pixel_size)
        font.setWeight(weight)
        return font

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._geometry = None
        self._static = None

    def mousePressEvent(self, event) -> None:
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        event.accept()
