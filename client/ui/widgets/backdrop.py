"""
Brend foni - yashil gradient + suzuvchi zarrachalar.

Ajratib olingan, chunki uni ikki sahifa ishlatadi: tarmoq tekshiruvi va
login. Ular ketma-ket ochiladi, ya'ni fon FARQ QILSA operator ekran
"sakraganini" ko'radi. Nusxa ko'chirilgan `paintEvent` esa vaqt o'tib
ikkiga ajralib ketardi.

Animatsiya ataylab arzon: 48 ta zarracha va sekundiga ~30 kadr. Bu
sahifalar imtihon markazidagi eng zaif kompyuterda ham ochiladi, fon
esa CPU'ni model yuklashdan tortib olmasligi kerak.
"""

from __future__ import annotations

import math
import random

from PyQt6.QtCore import QPointF, QTimer, Qt
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QRadialGradient
from PyQt6.QtWidgets import QWidget

from ui.styles import COLORS


class _Particle:
    """Fon animatsiyasi uchun zarracha (referens loyihadagi yondashuv)."""

    def __init__(self, width: float, height: float) -> None:
        self.x = random.uniform(0, width)
        self.y = random.uniform(0, height)
        self.radius = random.uniform(2, 5)
        self.opacity = random.uniform(0.06, 0.20)
        self.dx = random.uniform(-0.25, 0.25)
        self.dy = random.uniform(-0.45, -0.08)

    def update(self, width: float, height: float) -> None:
        self.x += self.dx
        self.y += self.dy
        if self.y < -10:
            self.y = height + 10
            self.x = random.uniform(0, width)
        if self.x < -10:
            self.x = width + 10
        elif self.x > width + 10:
            self.x = -10


class BrandBackdrop(QWidget):
    """Gradient fonli sahifa asosi. Tarkibni voris klass qo'shadi."""

    PARTICLE_COUNT = 48

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._particles = [_Particle(1920, 1080) for _ in range(self.PARTICLE_COUNT)]
        self._phase = 0.0
        self._backdrop_timer = QTimer(self)
        self._backdrop_timer.timeout.connect(self._tick)
        self._backdrop_timer.start(33)

    def _tick(self) -> None:
        # Ko'rinmayotgan sahifani qayta chizish - bekorga sarflangan CPU.
        # Sahifalar `QStackedWidget` da yashaydi, ya'ni faqat bittasi
        # ko'rinadi.
        if not self.isVisible():
            return
        self._phase += 0.004
        width, height = max(self.width(), 1), max(self.height(), 1)
        for particle in self._particles:
            particle.update(width, height)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()

        # Chuqur yashil gradient - brend rangi. Sekin "nafas olish"
        # effekti uchun burchak sinus bilan siljitiladi.
        offset = math.sin(self._phase) * 0.15
        gradient = QLinearGradient(0, 0, width * (0.6 + offset), height)
        gradient.setColorAt(0.0, QColor("#052E22"))
        gradient.setColorAt(0.35, QColor(COLORS["primary_deep"]))
        gradient.setColorAt(0.7, QColor(COLORS["primary_dark"]))
        gradient.setColorAt(1.0, QColor("#04241B"))
        painter.fillRect(self.rect(), gradient)

        pulse = 0.7 + 0.3 * math.sin(self._phase * 2)
        glow = QRadialGradient(width * 0.5, height * 0.42, max(width, height) * 0.5)
        glow.setColorAt(0.0, QColor(34, 197, 94, int(46 * pulse)))
        glow.setColorAt(0.55, QColor(21, 128, 61, int(22 * pulse)))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(self.rect(), glow)

        painter.setPen(Qt.PenStyle.NoPen)
        for particle in self._particles:
            painter.setBrush(QColor(255, 255, 255, int(255 * particle.opacity)))
            painter.drawEllipse(QPointF(particle.x, particle.y), particle.radius, particle.radius)
        painter.end()
