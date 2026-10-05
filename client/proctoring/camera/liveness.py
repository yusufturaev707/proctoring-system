"""
Kamera "ochiq", lekin tasvir yo'q - o'lik oqimni aniqlash.

AMALDA TOPILGAN (noutbuk, USB kamera): kabel sug'urilib qayta ulangach
kamera qayta ochildi ("Veb-kamera ochildi"), lekin DirectShow YANGI KADR
BERMADI - `read()` har safar ~1 s kutib (drayver ichki muddati) bo'sh
QORA buferni `True` bilan qaytardi. "Ketma-ket bo'sh kadr" qoidasi buni
ko'rmaydi (kadr `None` emas): FaceID "yuz yo'q", skrinshotda qora tasvir,
imtihon oxirigacha.

BELGI - IKKALASI BIRGA, `window_s` davomida uzluksiz:
  * kadr "yangi emas": butunlay nol yoki oldingisi bilan AYNAN bir xil
    (tirik sensorda shovqin bor - qo'shni kadrlar baytma-bayt mos kelmaydi);
  * o'qish SEKIN (`slow_read_s`): kadr kelmayapti, drayver kutib qaytyapti.

Faqat birinchisi yetmaydi: yopib qo'yilgan kamera ham to'liq qora (nol)
kadr beradi, lekin o'z tezligida - u ishlayapti, uni qayta ochish
"kamera yopilgan" ni "kamera yo'qoldi" ga aylantirardi.

Faqat LOKAL, virtual bo'lmagan kamera (`applies`): virtual kamera (OBS)
statik sahnada bir xil kadr beradi, IP kamera esa o'z timeout'i bilan.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

#: Kadrdan namuna qadami - 1280x720 da 160x90 nuqta (arzon, shovqinni ko'radi).
_STEP = 8

DEAD_STREAM_MESSAGE = (
    "Kameradan tasvir kelmayapti (qora kadr) — kamera qayta ochilmoqda."
)


def applies(source) -> bool:
    info = getattr(source, "info", None)
    return bool(info) and info.source == "local" and not info.is_virtual


class FrameLiveness:
    """`observe` -> "live" | "suspect" | "dead"."""

    def __init__(self, *, window_s: float = 5.0, slow_read_s: float = 0.5,
                 report_after_s: float = 3.0) -> None:
        self._window = float(window_s)
        self._slow = float(slow_read_s)
        self._report_after = float(report_after_s)
        self.reset()

    def reset(self) -> None:
        self._previous: Optional[np.ndarray] = None
        self._stale_since: Optional[float] = None
        self._started: Optional[float] = None
        self._frames = 0
        self._stale = 0
        self._luma = 0.0
        self._read = 0.0
        self._reported = False

    def observe(self, frame: np.ndarray, read_s: float, now: float) -> str:
        sample = frame[::_STEP, ::_STEP]
        stale = not sample.any() or (
            self._previous is not None
            and self._previous.shape == sample.shape
            and np.array_equal(self._previous, sample)
        )
        self._previous = sample.copy()

        if self._started is None:
            self._started = now
        self._frames += 1
        self._stale += int(stale)
        self._luma += float(sample.mean())
        self._read += float(read_s)

        if not stale or read_s < self._slow:
            self._stale_since = None
            return "live"
        if self._stale_since is None:
            self._stale_since = now
        return "dead" if now - self._stale_since >= self._window else "suspect"

    def report(self, now: float) -> str:
        """
        Ochilishdan keyingi birinchi soniyalar xulosasi - BIR MARTA (log uchun).

        Keyingi nosozlikni log'dan tushunish uchun: tirik oqimda
        yorqinlik > 0, o'qish ~30 ms, "yangi emas" kadrlar ~0.
        """
        if self._reported or self._started is None or now - self._started < self._report_after:
            return ""
        self._reported = True
        count = max(1, self._frames)
        return "{} kadr / {:.1f} s, o'rtacha yorqinlik {:.0f}, o'qish {:.0f} ms, yangi emas {}".format(
            self._frames, now - self._started, self._luma / count,
            1000.0 * self._read / count, self._stale,
        )
