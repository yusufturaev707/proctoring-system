"""
Kadrlarning halqa buferi — hodisadan OLDINGI lahzalar.

MUAMMO. Hodisa tasdiqlanganda (temporal qatlam uni 5 kadr va 1.2
soniyadan keyin ochadi) eng qimmatli lahzalar ALLAQACHON O'TIB
KETGAN bo'ladi: telefonni cho'ntakdan chiqarish harakati, unga
qo'l cho'zish, ekrandan uzoqlashish. Faqat hodisa lahzasidan
boshlab yozish bu harakatlarni butunlay yo'qotardi va dalil
"telefon stolda yotibdi" degan kadrdan iborat bo'lardi.

YECHIM. Kadrlar doimiy ravishda halqa buferda saqlanadi va hodisa
tasdiqlanganda undagi TARIX klipga yoziladi.

XOTIRA HISOBI. Bu bufer imtihon mashinasidagi eng katta xotira
iste'molchisi bo'lishi mumkin, shuning uchun u qat'iy cheklangan:

    720p BGR kadr = 1280 x 720 x 3 = ~2.6 MB
    5 soniya x 6 FPS = 30 kadr = ~79 MB

79 MB 4 GB li mashinada juda ko'p. Shuning uchun ikkita chora:

  1. kadrlar KICHRAYTIRILADI (standart 640 px kenglik) - dalil
     uchun bu yetarli va xotira 4 barobar kamayadi;
  2. bufer FPS bo'yicha siyraklashtiriladi - har kadr emas,
     sekundiga `capture_fps` tasi saqlanadi.

    640x360 x 5 s x 6 FPS = ~20 MB

Bu chegara `max_frames` bilan qat'iy ushlanadi: `deque(maxlen=...)`
eng eskisini o'zi tashlaydi va bufer hech qachon o'smaydi.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

#: Bufer kadrlarining maksimal kengligi (piksel).
#:
#: Dalil sifatida 640 px yetarli: telefon, kitob va ikkinchi odam
#: bu o'lchamda aniq ko'rinadi. Asl kadr (1080p) esa xotirani
#: 9 barobar ko'p yeydi va klip hajmini ham o'shancha oshiradi.
_MAX_WIDTH = 640


@dataclass
class BufferedFrame:
    """Buferdagi bitta kadr."""

    frame: np.ndarray
    timestamp: float


class FrameRingBuffer:
    """
    Oxirgi N soniyaning kadrlari.

    Thread'lar orasida ISHLATILMAYDI: pipeline uni bitta thread'da
    to'ldiradi va o'sha thread'da o'qiydi. Qulf qo'shish har kadrda
    keraksiz xarajat bo'lardi - agar kelajakda boshqa thread'dan
    o'qish kerak bo'lsa, `snapshot()` nusxa qaytaradi va u
    yetarli himoya.
    """

    def __init__(self, *, seconds: float = 5.0, capture_fps: int = 6) -> None:
        self._seconds = max(1.0, float(seconds))
        self._capture_fps = max(1, int(capture_fps))
        self._interval = 1.0 / self._capture_fps
        self._frames: deque = deque(maxlen=self._max_frames)
        self._last_captured = 0.0

    @property
    def _max_frames(self) -> int:
        # +2 zaxira: FPS bir tekis emas va oxirgi soniya kesilib
        # qolmasligi kerak.
        return int(self._seconds * self._capture_fps) + 2

    # ------------------------------------------------------------------
    def configure(self, *, seconds: float, capture_fps: int) -> None:
        """Siyosat o'zgarganda (`evidence.clip_seconds`)."""
        self._seconds = max(1.0, float(seconds))
        self._capture_fps = max(1, int(capture_fps))
        self._interval = 1.0 / self._capture_fps
        self._frames = deque(self._frames, maxlen=self._max_frames)

    def clear(self) -> None:
        self._frames.clear()
        self._last_captured = 0.0

    @property
    def count(self) -> int:
        return len(self._frames)

    @property
    def memory_mb(self) -> float:
        """Buferning taxminiy hajmi — diagnostika uchun."""
        if not self._frames:
            return 0.0
        return len(self._frames) * self._frames[0].frame.nbytes / (1024 ** 2)

    # ------------------------------------------------------------------
    def push(self, frame: np.ndarray, *, now: Optional[float] = None) -> bool:
        """
        Kadrni buferga qo'yadi (siyraklashtirish bilan).

        `False` — kadr o'tkazib yuborildi (interval hali tugamagan).
        Bu NORMAL holat va u xotirani cheklashning asosiy vositasi:
        30 FPS oqimdan 6 FPS saqlanadi.
        """
        if frame is None:
            return False
        now = now if now is not None else time.monotonic()
        # 5% BAG'RIKENGLIK. Kamera aynan bufer chastotasida kadr
        # bersa (6 FPS kamera, 6 FPS bufer - eng keng tarqalgan
        # holat), qat'iy `<` taqqoslash suzuvchi nuqta xatosi
        # tufayli kadrlarning YARMINI tashlab yuborardi va klip
        # ikki barobar siyrak chiqardi.
        if now - self._last_captured < self._interval * 0.95:
            return False

        self._last_captured = now
        self._frames.append(BufferedFrame(frame=self._shrink(frame), timestamp=now))
        return True

    def window(self, *, since: float, until: Optional[float] = None) -> list:
        """
        Berilgan oynadagi kadrlar.

        `since` hodisaning BOSHLANISH vaqti - temporal qatlam uni
        shart birinchi ko'ringan paytga qo'yadi, tasdiqlangan
        paytga emas.
        """
        until = until if until is not None else time.monotonic()
        return [
            item for item in self._frames if since <= item.timestamp <= until
        ]

    def latest(self) -> Optional[BufferedFrame]:
        return self._frames[-1] if self._frames else None

    def snapshot(self) -> list:
        return list(self._frames)

    # ------------------------------------------------------------------
    @staticmethod
    def _shrink(frame: np.ndarray) -> np.ndarray:
        """
        Kadrni buferga kichraytirib qo'yadi.

        NUSXA MAJBURIY (kichraytirish bo'lmaganda ham): kamera
        oqimi massivni qayta ishlatishi mumkin va bufer o'sha
        xotiraga referens ushlab qolsa, eski kadrlar yangisi
        bilan JIMGINA almashib ketardi - klipda bir xil tasvir
        takrorlanardi.
        """
        height, width = frame.shape[:2]
        if width <= _MAX_WIDTH:
            return frame.copy()

        import cv2

        scale = _MAX_WIDTH / float(width)
        return cv2.resize(
            frame,
            (_MAX_WIDTH, max(1, int(round(height * scale)))),
            interpolation=cv2.INTER_AREA,
        )
