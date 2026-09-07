"""
Kamera oldindan ko'rish vidjeti.

Kadr `CameraWorker` dan numpy massiv (BGR) sifatida keladi. Bu yerda u
QImage'ga aylantiriladi va ustiga yuz ramkasi chiziladi.

MUHIM: `QImage` ma'lumot buferiga referens ushlaydi, nusxa OLMAYDI.
Massiv Python tomonda yo'q qilinsa, rasm buzilgan piksellar bilan
chiziladi yoki dastur qulaydi - shuning uchun `.copy()` majburiy.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QLabel

from ui.styles import COLORS

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
        self.setMinimumSize(560, 420)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            "background-color: #0F172A; border-radius: 18px; color: #94A3B8;"
        )
        self.setText("Kamera ishga tushmoqda...")
        self._frame: Optional[np.ndarray] = None
        self._bboxes: list = []
        self._state = "none"
        self._score: Optional[int] = None

    # ------------------------------------------------------------------
    def set_frame(self, frame: np.ndarray) -> None:
        self._frame = frame
        self._render()

    def set_detection(self, state: str, bboxes: list, score: Optional[int] = None) -> None:
        self._state = state
        self._bboxes = bboxes or []
        self._score = score
        self._render()

    def clear_view(self) -> None:
        self._frame = None
        self._bboxes = []
        self.setText("Kamera o'chirilgan")

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

        scale_x = pixmap.width() / width
        scale_y = pixmap.height() / height
        color_hex, hint = _STATE_STYLE.get(self._state, _STATE_STYLE["none"])
        color = QColor(color_hex)

        for bbox in self._bboxes:
            x1, y1, x2, y2 = bbox
            rect = QRectF(
                x1 * scale_x, y1 * scale_y, (x2 - x1) * scale_x, (y2 - y1) * scale_y
            )
            pen = QPen(color, 3)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, 10, 10)

            if self._score is not None and self._state in ("ok", "match", "mismatch"):
                badge = QRectF(rect.left(), max(0.0, rect.top() - 28), 96, 24)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawRoundedRect(badge, 8, 8)
                painter.setPen(QColor("#FFFFFF"))
                painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
                painter.drawText(
                    badge,
                    int(Qt.AlignmentFlag.AlignCenter),
                    "{}%".format(self._score),
                )

        if hint:
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


class PhotoView(QLabel):
    """Etalon (pasport) rasmi. Rasm bo'lmasa - tushuntiruvchi placeholder."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(220, 280)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self._apply_placeholder("Hujjat rasmi\nyuklanmagan")

    def _apply_placeholder(self, text: str) -> None:
        self.setStyleSheet(
            "background-color: {}; border: 1px dashed {}; border-radius: 14px; "
            "color: {}; font-size: 13px;".format(
                COLORS["surface_alt"], COLORS["border_strong"], COLORS["text_muted"]
            )
        )
        self.setText(text)

    def set_image_bytes(self, raw: bytes) -> bool:
        pixmap = QPixmap()
        if not raw or not pixmap.loadFromData(raw):
            self._apply_placeholder("Hujjat rasmi\nyuklanmagan")
            return False
        self.setStyleSheet(
            "background-color: {}; border: 1px solid {}; border-radius: 14px;".format(
                COLORS["surface"], COLORS["border"]
            )
        )
        self.setPixmap(
            pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        return True
