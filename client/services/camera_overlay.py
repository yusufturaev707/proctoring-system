"""
Skrinshotga KAMERA kadrini qo'shish - pastki burchaklarda kichik ramka.

NIMA UCHUN. Skrinshot ekranda NIMA bo'lganini ko'rsatadi, lekin
"o'sha paytda kompyuter oldida KIM o'tirgan edi?" degan savolni ochiq
qoldiradi - apellyatsiyada esa aynan shu savol beriladi. Ekran
yozuvida bu savolga PiP allaqachon javob beradi
(`screen_recorder._compose`); skrinshotda ham xuddi shunday bo'lishi
kerak, chunki proktor imtihon DAVOMIDA faqat skrinshotni ko'radi -
yozuv mashinada qoladi.

RAMKALAR EKRAN USTIGA EMAS, OSTIGA QO'SHILGAN TASMAGA chiziladi.
Birinchi variant ekranning ustiga chizardi va sinovda javob
variantlarining ikkitasini butunlay yopib qo'ydi: test
platformalarida pastki qism (variantlar, "Keyingi" tugmasi, savollar
ro'yxati) eng zich joy. Tasma bilan ekran tasviri BIR PIKSEL ham
yopilmaydi - bu shartni joylashuvni sozlab emas, tuzilish bilan
ta'minlaydi. Narxi: rasm ~20% balandroq va JPEG ~10% og'irroq.

JOYLASHUV ROLGA BOG'LIQ va u qat'iy:

    primary   (yuz kamerasi)  -> pastki O'NG burchak
    secondary (xona / stol)   -> pastki CHAP burchak

O'ng burchak ekran yozuvidagi PiP bilan bir xil: proktor ikkala
dalilda ham yuzni bir joyda qidiradi. Ikkinchi kamera faqat u
HAQIQATAN ochiq bo'lsa chiziladi (AI kuzatuv yoqilganda).

KAMERA OCHIQ, LEKIN KADR YO'Q YOKI ESKIRGAN bo'lsa ramka baribir
chiziladi - "Kamera kadri yo'q" yozuvi bilan. Kadr yo'qligi ham
dalil (kamera uzilgan yoki yopilgan); ramkani jimgina tashlab ketish
uni "kamera ishlatilmaydigan o'rnatish" bilan aralashtirardi.
Eskirgan kadrni qo'yish esa bundan ham yomon - u o'tgan daqiqadagi
odamni hozirgi ekran bilan birga ko'rsatardi.

Tasma o'rtasida olish VAQTI turadi: rasm paneldan yuklab olinib,
kontekstsiz (xat, bayonnoma ilovasi) ko'rilganda ham o'z vaqtini
aytadi.

Ramka talabgorning ekraniga CHIZILMAYDI - faqat kodlanayotgan rasmga.
Ekrandagi element unga kuzatuv qayerga qaratilganini ko'rsatardi.

Fon thread'ida ishlaydi: `QImage` va `QPainter` (`QPixmap` dan farqli)
GUI thread'iga bog'lanmagan.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable, Optional

import numpy as np
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen

log = logging.getLogger(__name__)

#: Ramka kengligining chegaralari (px). Pastki chegara - yuz hali
#: tanib olinadigan eng kichik o'lcham; yuqorisi - keng (ikki
#: monitorli) skrinshotda ulush ramkani keraksiz kattalashtirmasligi
#: uchun.
_MIN_WIDTH = 96
_MAX_WIDTH = 240
#: Portret kamera ramkasi tasmani cho'zib yubormasligi kerak.
_MAX_HEIGHT = 180
_RADIUS = 6.0
_BORDER = 2.0

_STRIP_COLOR = QColor(32, 33, 36)
_STRIP_LINE = QColor(255, 255, 255, 40)
_PLACEHOLDER_COLOR = QColor(60, 64, 67)
_TEXT_COLOR = QColor(255, 255, 255, 190)

_PLACEHOLDER_TEXT = "Kamera kadri yo'q"


def overlay_cameras(image: QImage, slots: Iterable, *, ratio: float,
                    captured_at: Optional[datetime] = None) -> QImage:
    """
    Rasm ostiga kamera tasmasini qo'shadi va YANGI rasm qaytaradi.

    `slots` - `(rol, kadr)` juftliklari; kadr `None` bo'lsa ramka
    "kadr yo'q" yozuvi bilan chiziladi. Bo'sh ro'yxat - rasm
    o'zgarishsiz qaytadi (kamera umuman ishlatilmayapti) va tasma
    ham qo'shilmaydi.

    Xato hech qachon skrinshotni to'xtatmaydi: tasmani chizib
    bo'lmasa, ekran tasviri o'zi ketadi - u baribir asosiy dalil.
    """
    slots = [(role, frame) for role, frame in (slots or []) if role]
    if not slots or image.isNull():
        return image

    try:
        return _compose(image, slots, ratio, captured_at or datetime.now())
    except Exception:
        log.warning("Kamera tasmasini chizib bo'lmadi - skrinshot tasmasiz", exc_info=True)
        return image


def _compose(image: QImage, slots: list, ratio: float, captured_at: datetime) -> QImage:
    width = image.width()
    pictures = [(role, _to_qimage(frame) if frame is not None else None) for role, frame in slots]

    box_w = max(_MIN_WIDTH, min(_MAX_WIDTH, int(round(width * max(0.05, ratio)))))
    boxes = []
    for role, picture in pictures:
        aspect = (picture.height() / picture.width()) if picture is not None else 3 / 4
        w, h = box_w, int(round(box_w * aspect))
        if h > _MAX_HEIGHT:
            h = _MAX_HEIGHT
            w = int(round(h / aspect))
        boxes.append((role, picture, w, h))

    margin = max(6, int(round(width * 0.008)))
    strip_h = max(h for _, _, _, h in boxes) + 2 * margin

    canvas = QImage(width, image.height() + strip_h, QImage.Format.Format_RGB32)
    canvas.fill(_STRIP_COLOR)
    painter = QPainter(canvas)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(0, 0, image)
        top = image.height()
        # Ekran va tasma orasidagi ingichka chiziq: tasma test
        # sahifasining qismi emasligi birinchi qarashda ko'rinsin.
        painter.fillRect(0, top, width, 1, _STRIP_LINE)

        for role, picture, w, h in boxes:
            x = width - margin - w if role == "primary" else margin
            y = top + (strip_h - h) // 2
            _draw_box(painter, QRectF(x, y, w, h), picture)

        _draw_timestamp(painter, QRectF(0, top, width, strip_h), captured_at, box_w + 2 * margin)
    finally:
        # `QPainter` yopilmasa rasm qulflangan qoladi va uni kodlab
        # bo'lmaydi (`grab_screens` dagi bilan bir xil sabab).
        painter.end()
    return canvas


def _draw_box(painter: QPainter, rect: QRectF, picture: Optional[QImage]) -> None:
    path = QPainterPath()
    path.addRoundedRect(rect, _RADIUS, _RADIUS)
    painter.save()
    painter.setClipPath(path)
    if picture is not None:
        painter.drawImage(rect, picture)
    else:
        painter.fillRect(rect, _PLACEHOLDER_COLOR)
        font = QFont()
        font.setPixelSize(max(9, int(rect.width() / 14)))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(_TEXT_COLOR)
        # O'RALADI: tor ramkada bir qatorga sig'masa matn chetdan
        # chiqib, qo'shni tasvir ustiga tushardi.
        painter.drawText(
            rect.adjusted(6, 6, -6, -6),
            int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
            _PLACEHOLDER_TEXT,
        )
    painter.restore()

    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(255, 255, 255, 220), _BORDER))
    painter.drawRoundedRect(rect, _RADIUS, _RADIUS)


def _draw_timestamp(painter: QPainter, strip: QRectF, captured_at: datetime, side: int) -> None:
    """Olish vaqti - tasmaning o'rtasida, ramkalar orasida."""
    middle = strip.adjusted(side, 0, -side, 0)
    if middle.width() < 80:
        return
    font = QFont()
    font.setPixelSize(max(10, min(16, int(strip.height() / 7))))
    painter.setFont(font)
    painter.setPen(_TEXT_COLOR)
    painter.drawText(
        middle,
        int(Qt.AlignmentFlag.AlignCenter),
        captured_at.strftime("%Y-%m-%d %H:%M:%S"),
    )


def _to_qimage(frame: np.ndarray) -> Optional[QImage]:
    """
    OpenCV kadri (BGR yoki kulrang) -> mustaqil `QImage`.

    `.copy()` SHART: `QImage` massiv xotirasiga ishora qiladi, kamera
    thread'i esa keyingi kadrni yangi massivga yozadi va eskisi
    garbage collector'ga ketadi. Nusxasiz rasm bo'shatilgan xotiradan
    chizilardi.
    """
    if not isinstance(frame, np.ndarray) or frame.size == 0 or frame.dtype != np.uint8:
        return None
    frame = np.ascontiguousarray(frame)
    if frame.ndim == 2:
        height, width = frame.shape
        fmt = QImage.Format.Format_Grayscale8
    elif frame.ndim == 3 and frame.shape[2] == 3:
        height, width = frame.shape[:2]
        fmt = QImage.Format.Format_BGR888
    else:
        return None
    return QImage(frame.data, width, height, int(frame.strides[0]), fmt).copy()
