"""
Kamera oldindan ko'rish vidjeti.

Kadr `CameraWorker` dan numpy massiv (BGR) sifatida keladi. Bu yerda u
QImage'ga aylantiriladi va ustiga yuz OVALI hamda holat chiziladi.

YUZ ATROFIGA TO'RTBURCHAK RAMKA CHIZILMAYDI. Holatni oval rangi
aytadi (yashil - mos, qizil - mos emas, sariq - yaqinroq keling),
o'xshashlik foizi esa oval tepasida turadi. Ramka yuz bilan birga
sakrab yurar va talabgorning e'tiborini ovalga emas, o'ziga tortardi;
oval esa JOYIDA turadi va "qayerda bo'lishim kerak" degan savolga
javob berishda davom etadi.

MUHIM: `QImage` ma'lumot buferiga referens ushlaydi, nusxa OLMAYDI.
Massiv Python tomonda yo'q qilinsa, rasm buzilgan piksellar bilan
chiziladi yoki dastur qulaydi - shuning uchun `.copy()` majburiy.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
from PyQt6.QtCore import QElapsedTimer, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QLabel, QSizePolicy

from ui.styles import COLORS, preview_surface_style

#: Hujjat rasmi burchaklarining radiusi. Karta radiusidan (22)
#: KICHIKROQ: ichma-ich yumaloq shakllarda ichkarisi kichikroq
#: radius olishi kerak, aks holda ramka bilan rasm orasidagi
#: masofa burchaklarda ko'rinib qoladi.
_PHOTO_RADIUS = 14

#: Aniqlash natijasining "yaroqlilik muddati" (ms).
#:
#: Holat aniqlashdan keladi va u kadrlardan SEKINROQ yangilanadi
#: (`DETECT_EVERY_NTH_FRAME`, aniqlashning o'zi ~50-200 ms). Oradagi
#: kadrlarda oxirgi holat qayta chiziladi - bu normal.
#:
#: Lekin aniqlash BUTUNLAY to'xtasa (model xatosi, oqim uzilishi,
#: sahifa boshqa holatga o'tishi), yashil oval jonli kadr ustida
#: abadiy qolib, "hammasi joyida" degan eskirgan xabarni berardi.
#: Muddat o'tgach oval neytral holatga qaytadi.
_DETECTION_TTL_MS = 500

#: YUZ OVALI - kadrga nisbatan ulushlar.
#:
#: Balandlik kadr balandligining 72% i, kenglik esa balandlikning
#: 76% i: odam boshining (peshonadan iyakkacha, quloqlar bilan)
#: taxminiy nisbati. Oval kadr markazidan biroz YUQORIDA (47%):
#: kamera monitor tepasida turadi va o'tirgan odamning yuzi kadrning
#: yuqori yarmiga tushadi - aniq markazdagi oval talabgorni
#: pastga egilishga majbur qilardi.
#:
#: 72% dan kattasi tavsiya etilmaydi: ovalning tepasida ko'rsatma,
#: pastida sanoq raqami turadi va ular kadrdan chiqib ketardi.
#:
#: Bu o'lcham aniqlash chegarasiga MOS: 1280x720 kadrda oval ~390 px
#: keng va unga to'g'ri joylashgan yuzning bbox'i ~290 px -
#: `MIN_FACE_WIDTH_PX` (110) dan ancha katta, ya'ni ovalga mos
#: kelgan odam "Yaqinroq keling" olmaydi. Kichikroq yuz ham
#: (odam ovalni to'liq to'ldirmasa) chegaradan o'tadi.
_GUIDE_HEIGHT = 0.72
_GUIDE_ASPECT = 0.76
_GUIDE_CENTER_Y = 0.47

#: Holat -> (ramka rangi, matn)
_STATE_STYLE = {
    "ok": (COLORS["primary_light"], ""),
    "match": (COLORS["primary"], "Mos keldi"),
    "none": (COLORS["text_muted"], "Yuz topilmadi"),
    "far": (COLORS["warning"], "Yaqinroq keling"),
    "multiple": (COLORS["error"], "Kadrda bir nechta odam"),
    "mismatch": (COLORS["error"], "Mos kelmadi"),
}


class CameraView(QLabel):
    """Video oqimi + yuz ramkasi + holat matni."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Minimal o'lcham 4:3 - kameralar shu nisbatda kadr beradi.
        # Vidjet undan KATTA bo'lishi mumkin va o'shanda kadr
        # markazda, yon tomonlarida esa o'sha to'q yuza qoladi
        # (video pleyer kabi) - bu "sig'maydigan" emas, "to'ldirilgan"
        # ko'rinish beradi.
        self.setMinimumSize(480, 360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Yuza `camera_panel` dagi oldindan ko'rish bilan AYNAN bir
        # xil (`preview_surface_style`): ikkala ekranda ham kamera
        # bir xil ko'rinishi kerak, aks holda operator ularni ikki
        # xil narsa deb qabul qiladi.
        self.setStyleSheet(preview_surface_style())
        self.setText("Kamera ishga tushmoqda...")
        self._frame: Optional[np.ndarray] = None
        self._state = "none"
        self._score: Optional[int] = None
        self._detected_at = QElapsedTimer()
        #: Yuz ovali: `None` - yo'q, `"countdown"` - sanoq (fon
        #: xiralashgan, progress yoyi), `"hint"` - tekshiruv davomida
        #: xira yo'naltiruvchi chiziq.
        self._guide: Optional[str] = None
        self._guide_clock = QElapsedTimer()
        self._guide_ms = 0

    # ------------------------------------------------------------------
    def set_frame(self, frame: np.ndarray) -> None:
        self._frame = frame
        self._render()

    def set_detection(self, state: str, score: Optional[int] = None) -> None:
        """
        Aniqlash natijasi: holat (oval rangi, pastdagi matn) va ball.

        Yuz KOORDINATALARI qabul qilinmaydi va bu ataylab: ekranda
        yuz ramkasi yo'q (modul docstring'i). Fondagi odamlar ham
        belgilanmaydi - kadrda bir nechta odam bo'lsa, buni pastdagi
        "Kadrda bir nechta odam" yozuvi va qizil oval aytadi.
        """
        self._state = state
        self._score = score
        self._detected_at.restart()
        self._render()

    def start_guide(self, duration_ms: int) -> None:
        """
        Sanoqni boshlaydi: oval + xiralashgan fon + qolgan soniyalar.

        Vaqtni VIDJETNING O'ZI hisoblaydi (`QElapsedTimer`) va har
        kadrda qayta chizadi - alohida animatsiya taymeri kerak emas:
        kamera sekundiga 15-30 kadr beradi va progress yoyi shu
        tezlikda silliq yuradi. O'tishning o'zini (aniqlashni yoqish)
        esa sahifa boshqaradi - vidjet faqat ko'rsatadi.
        """
        self._guide = "countdown"
        self._guide_ms = max(1, int(duration_ms))
        self._guide_clock.restart()
        # Oldingi urinishning holati (masalan qizil oval) sanoqdan
        # keyin bir lahza ham ko'rinmasligi kerak.
        self._detected_at.invalidate()
        self._render()

    def end_guide(self, *, keep_hint: bool = True) -> None:
        """
        Sanoq tugadi. Oval XIRA chiziq bo'lib QOLADI (`keep_hint`).

        Talabgor tekshiruv davomida ham qayerda turishi kerakligini
        ko'rib turishi kerak: oval butunlay yo'qolsa, u sanoq
        tugashi bilan "bo'ldi" deb qimirlab ketardi - tekshiruv esa
        aynan shu paytda boshlanadi.
        """
        self._guide = "hint" if keep_hint else None
        self._render()

    @property
    def guide_active(self) -> bool:
        return self._guide == "countdown"

    @property
    def _detection_fresh(self) -> bool:
        """Holat hali haqiqatni ko'rsatayaptimi (`_DETECTION_TTL_MS`)."""
        return (
            self._detected_at.isValid()
            and self._detected_at.elapsed() <= _DETECTION_TTL_MS
        )

    def clear_view(self) -> None:
        self._frame = None
        self._guide = None
        self.setText("Kamera o'chirilgan")

    def resizeEvent(self, event) -> None:
        """
        O'lcham o'zgarganda oxirgi kadr QAYTA chiziladi.

        Kadr `self.size()` bo'yicha masshtablanadi, ya'ni vidjet
        kattalashganda eski (kichik) rasm o'z o'lchamida qolib
        ketardi va yon tomonlarida keng qora yo'lak paydo
        bo'lardi. Jonli oqimda buni keyingi kadr tuzatadi, lekin
        oqim to'xtaganda yoki oyna endigina ochilganda rasm shu
        holida turib qolardi.
        """
        super().resizeEvent(event)
        if self._frame is not None:
            self._render()

    # ------------------------------------------------------------------
    def _render(self) -> None:
        if self._frame is None:
            return
        frame = self._frame
        height, width = frame.shape[:2]

        # BGR (OpenCV) -> RGB (Qt). `.copy()` haqida modul docstring'iga qarang.
        rgb = frame[:, :, ::-1].copy()
        image = QImage(rgb.data, width, height, 3 * width, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(image).scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._guide == "countdown":
            # SANOQ PAYTIDA FAQAT OVAL: aniqlash o'chiq, ball va
            # holat matni yo'q - talabgor bitta narsaga qaraydi.
            self._paint_countdown(painter, pixmap.width(), pixmap.height())
            painter.end()
            self.setPixmap(pixmap)
            return
        fresh = self._detection_fresh
        color_hex, hint = _STATE_STYLE.get(self._state, _STATE_STYLE["none"])
        color = QColor(color_hex)

        if self._guide == "hint":
            # "Yuz yo'q" va eskirgan natija - NEYTRAL oval: rang
            # berish "nimadir baholandi" degan xabar bo'lardi.
            active = fresh and self._state != "none"
            self._paint_oval_status(
                painter, pixmap.width(), pixmap.height(), color if active else None
            )
            if (
                active
                and self._score is not None
                and self._state in ("ok", "match", "mismatch")
            ):
                self._paint_score(painter, pixmap.width(), pixmap.height(), color)

        if hint and fresh:
            box = QRectF(12, pixmap.height() - 46, pixmap.width() - 24, 34)
            painter.setPen(Qt.PenStyle.NoPen)
            fill = QColor(color)
            fill.setAlpha(220)
            painter.setBrush(fill)
            painter.drawRoundedRect(box, 10, 10)
            painter.setPen(QColor("#FFFFFF"))
            painter.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
            painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), hint)

        painter.end()
        self.setPixmap(pixmap)

    # ------------------------------------------------------------------
    # Yuz ovali
    # ------------------------------------------------------------------
    @staticmethod
    def _oval_rect(width: int, height: int) -> QRectF:
        oval_h = height * _GUIDE_HEIGHT
        oval_w = oval_h * _GUIDE_ASPECT
        center_y = height * _GUIDE_CENTER_Y
        return QRectF((width - oval_w) / 2, center_y - oval_h / 2, oval_w, oval_h)

    def _paint_oval_status(self, painter: QPainter, width: int, height: int,
                           color: Optional[QColor]) -> None:
        """
        Tekshiruv davomidagi oval - HOLAT KO'RSATKICHI.

        `color` bo'lmasa (yuz yo'q yoki natija eskirgan) - xira uzuq
        chiziq: faqat "qayerda turish kerak" degan yo'naltiruvchi.
        Rang bo'lsa - to'liq chiziq o'sha rangda: ramka o'rniga endi
        aynan oval "mos keldi / mos kelmadi / yaqinroq keling" deydi.
        """
        oval = self._oval_rect(width, height)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if color is None:
            painter.setPen(QPen(QColor(255, 255, 255, 120), 2, Qt.PenStyle.DashLine))
        else:
            painter.setPen(QPen(color, max(3.0, width / 260)))
        painter.drawEllipse(oval)

    def _paint_score(self, painter: QPainter, width: int, height: int,
                     color: QColor) -> None:
        """O'xshashlik foizi - oval tepasida, holat rangidagi pill."""
        oval = self._oval_rect(width, height)
        font = QFont("Segoe UI")
        font.setPixelSize(max(12, int(height / 34)))
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        text = "O'xshashlik {}%".format(self._score)
        pill_h = font.pixelSize() * 2.1
        pill_w = painter.fontMetrics().horizontalAdvance(text) + pill_h * 1.1
        top = max(8.0, oval.top() - pill_h - max(8.0, height * 0.02))
        pill = QRectF((width - pill_w) / 2, top, pill_w, pill_h)
        fill = QColor(color)
        fill.setAlpha(235)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(pill, pill_h / 2, pill_h / 2)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), text)

    def _paint_countdown(self, painter: QPainter, width: int, height: int) -> None:
        """
        Sanoq: xiralashgan fon, oval, progress yoyi, raqam, ko'rsatma.

        Material Design 3 tamoyillari bo'yicha:

        * FON XIRALASHADI (scrim), oval ichi esa TOZA qoladi - ko'z
          o'z-o'zidan yorug' joyga, ya'ni yuz turishi kerak bo'lgan
          joyga boradi. Bu matndan tezroq tushuniladi.
        * Oval chizig'i - aniq (determinate) progress ko'rsatkichi:
          yoy tepadan soat yo'nalishida to'ladi va qancha qolganini
          raqamsiz ham aytadi.
        * Raqam oval ICHIDA EMAS, pastida - yuzni yopmasligi kerak.
          Ko'rsatma esa tepada, "pill" shaklidagi yuzada.
        """
        elapsed = self._guide_clock.elapsed() if self._guide_clock.isValid() else 0
        progress = min(1.0, elapsed / self._guide_ms)
        remaining = max(1, -(-(self._guide_ms - elapsed) // 1000))

        oval = self._oval_rect(width, height)
        accent = QColor(COLORS["primary_light"])

        # Scrim - oval tashqarisi.
        scrim = QPainterPath()
        scrim.setFillRule(Qt.FillRule.OddEvenFill)
        scrim.addRect(QRectF(0, 0, width, height))
        scrim.addEllipse(oval)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 125))
        painter.drawPath(scrim)

        # Trek (to'liq oval) va progress yoyi.
        stroke = max(3.0, width / 260)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 150), stroke))
        painter.drawEllipse(oval)
        if progress > 0:
            pen = QPen(accent, stroke + 1.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            # Qt burchaklari 1/16 gradusda, 0 - soat 3 da, musbat -
            # soat mili TESKARISI. Tepadan (90°) soat yo'nalishida.
            painter.drawArc(oval, 90 * 16, -int(progress * 360 * 16))

        # Ko'rsatma - tepada, pill.
        font = QFont("Segoe UI")
        font.setPixelSize(max(13, int(height / 30)))
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        text = "Yuzingizni oval ichiga joylang"
        text_w = painter.fontMetrics().horizontalAdvance(text)
        pill_h = font.pixelSize() * 2.3
        pill_w = text_w + pill_h * 1.2
        pill_top = max(10.0, oval.top() - pill_h - max(10.0, height * 0.025))
        pill = QRectF((width - pill_w) / 2, pill_top, pill_w, pill_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(20, 22, 26, 200))
        painter.drawRoundedRect(pill, pill_h / 2, pill_h / 2)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), text)

        # Sanoq raqami - oval ostida, aylana (MD3 "primary container").
        diameter = max(44.0, height * 0.105)
        gap = max(8.0, height * 0.02)
        top = min(oval.bottom() + gap, height - diameter - 8)
        circle = QRectF((width - diameter) / 2, top, diameter, diameter)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawEllipse(circle)
        number = QFont("Segoe UI")
        number.setPixelSize(int(diameter * 0.52))
        number.setWeight(QFont.Weight.Bold)
        painter.setFont(number)
        painter.setPen(QColor(COLORS["primary_deep"]))
        painter.drawText(circle, int(Qt.AlignmentFlag.AlignCenter), str(remaining))


class PhotoView(QLabel):
    """
    Etalon (pasport) rasmi. Rasm bo'lmasa - tushuntiruvchi placeholder.

    O'lcham SOZLANADI, lekin nisbat 3:4 saqlanadi - hujjat rasmi
    shu nisbatda keladi va boshqa nisbatda ramka ichida bo'sh
    yo'laklar paydo bo'ladi. FaceID ekranida rasm KATTA (operator
    uni jonli kadr bilan solishtiradi), talabgorni qidirish
    ekranida esa KICHIK: u yerda rasm tasdiq emas, "to'g'ri odam
    topildimi?" degan tez qarash uchun.
    """

    def __init__(self, parent=None, *, width: int = 220, height: int = 280) -> None:
        super().__init__(parent)
        # XOM RASM SAQLANADI. O'lcham ish paytida o'zgarishi mumkin
        # (`set_size`) va o'shanda rasm QAYTA chiziladi: bir marta
        # kichraytirilgan piksel xaritasini kattalashtirish uni
        # xiralashtirardi, holbuki bu aynan solishtiriladigan rasm.
        self._source = QPixmap()
        self.setFixedSize(width, height)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self._apply_placeholder("Hujjat rasmi\nyuklanmagan")

    def set_size(self, width: int, height: int) -> None:
        """
        Ramka o'lchamini o'zgartiradi (nisbatni CHAQIRUVCHI saqlaydi).

        Kerak, chunki past ekranda (1366x768) qat'iy 264x352 ramka
        yon ustunga sig'masdi: Qt yetishmagan joyni matn
        maydonlaridan "o'g'irlab", ism yorlig'ini rasmning USTIGA
        chizib qo'yardi.
        """
        if (width, height) == (self.width(), self.height()):
            return
        self.setFixedSize(width, height)
        if not self._source.isNull():
            self.setPixmap(self._rounded(self._source))

    def _apply_placeholder(self, text: str) -> None:
        self.setStyleSheet(
            "background-color: {}; border: 1px dashed {}; border-radius: {}px; "
            "color: {}; font-size: 13px;".format(
                COLORS["surface_alt"], COLORS["border_strong"], _PHOTO_RADIUS,
                COLORS["text_muted"],
            )
        )
        self.setText(text)

    def set_image_bytes(self, raw: bytes) -> bool:
        pixmap = QPixmap()
        if not raw or not pixmap.loadFromData(raw):
            self._source = QPixmap()
            self._apply_placeholder("Hujjat rasmi\nyuklanmagan")
            return False
        self._source = pixmap
        self.setStyleSheet(
            "background-color: {}; border: 1px solid {}; border-radius: {}px;".format(
                COLORS["surface"], COLORS["border"], _PHOTO_RADIUS
            )
        )
        self.setPixmap(self._rounded(pixmap))
        return True

    def _rounded(self, pixmap: QPixmap) -> QPixmap:
        """
        Rasmni yumaloq burchakli ramkaga joylaydi.

        CSS `border-radius` PIKSEL XARITASIGA TA'SIR QILMAYDI: u
        faqat vidjetning fonini va ramkasini yumaloqlaydi, rasm esa
        uning ustidan to'g'ri burchakli bo'lib chiziladi. Natijada
        yumaloq kartalar orasida bitta o'tkir to'rtburchak paydo
        bo'ladi va u ko'zga darhol tashlanadi.

        Rasm KESILMAYDI (`KeepAspectRatio`): hujjat rasmini
        to'ldirish uchun kengaytirish yuzning bir qismini ramkadan
        chiqarib yuborishi mumkin - aynan shu rasm keyingi sahifada
        solishtirish uchun ishlatiladi.
        """
        scaled = pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        canvas = QPixmap(self.size())
        canvas.fill(Qt.GlobalColor.transparent)

        # NIQOB orqali, `setClipPath` bilan EMAS: Qt'da kesish
        # (clipping) tekislanmaydi (antialiasing qo'llanmaydi) va
        # burchaklar zinapoyasimon chiqadi - 14 px radiusda bu ko'zga
        # tashlanadi. Niqob esa oddiy chizilgan shakl, ya'ni u
        # tekislanadi; `SourceIn` rejimi rasmni faqat o'sha shakl
        # ichida qoldiradi.
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#FFFFFF"))
        path = QPainterPath()
        path.addRoundedRect(QRectF(canvas.rect()), _PHOTO_RADIUS, _PHOTO_RADIUS)
        painter.drawPath(path)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.drawPixmap(
            (canvas.width() - scaled.width()) // 2,
            (canvas.height() - scaled.height()) // 2,
            scaled,
        )
        painter.end()
        return canvas
