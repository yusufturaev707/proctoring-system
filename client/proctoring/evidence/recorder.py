"""
Dalil yozuvchi: kadr + video klip -> serverga.

OQIM. Hodisa tasdiqlanganda:

    halqa bufer  ->  kadr (JPEG)   ->  yuklash
                 ->  klip (MP4)    ->  yuklash

Ikkalasi ham ALOHIDA yuklanadi: kadr kichik (~100 KB) va u
darhol yetib boradi, klip esa katta (~1-3 MB) va sekin tarmoqda
uzoq ketishi mumkin. Ularni bitta so'rovga qo'shish kadrni ham
klip tezligiga bog'lab qo'yardi - proktor ekranida esa aynan
kadr birinchi kerak.

DISKKA YOZISH - ONGLI ISTISNO. `screen_capture.py` da "diskka
yozmaymiz" qoidasi bor va uning sababi to'g'ri: skrinshot
talabgorning ekrani va u mashinada iz qoldirmasligi kerak. Klip
esa boshqa: u hodisaga bog'langan va uni qayta yig'ib bo'lmaydi.
Tarmoq uzilganda klipni RAM'da ushlab turish 4 GB li mashinani
o'ldirardi (bir necha klip = o'nlab MB), shuning uchun u
vaqtinchalik faylga yoziladi va yuborilgach DARHOL o'chiriladi.

`cv2.VideoWriter` ISHLATILADI, `av`/`ffmpeg-python` EMAS: OpenCV
allaqachon bog'liqlikda va u `mp4v` kodekini o'zi olib yuradi.
Yangi paket bundle'ga o'nlab megabayt qo'shardi.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

#: JPEG sifati. 80 - dalil uchun yetarli va hajm ~2 barobar kichik.
_JPEG_QUALITY = 80

#: Klip kodeki. `mp4v` OpenCV bilan birga keladi va serverdagi
#: sehrli baytlar tekshiruvidan (`ftyp`) o'tadi.
_FOURCC = "mp4v"

#: Bir vaqtda navbatda turadigan dalillar soni.
#:
#: Tarmoq uzilganda ular to'planadi. Chegarasiz bu diskni
#: to'ldirardi; chegara oshsa ENG ESKISI tashlanadi - yangi
#: hodisa eskisidan muhimroq, chunki u hali tekshirilmagan.
_MAX_PENDING = 8


@dataclass
class PendingEvidence:
    """Yuborilishni kutayotgan dalil."""

    kind: str                       # frame | clip
    data: Optional[bytes] = None    # kadr uchun (RAM'da)
    path: str = ""                  # klip uchun (vaqtinchalik fayl)
    event_type: str = ""
    camera_role: str = ""
    confidence: int = 0
    duration_ms: int = 0
    captured_at: str = ""
    boxes: list = field(default_factory=list)

    def cleanup(self) -> None:
        """Vaqtinchalik faylni o'chiradi (yuborilgan yoki tashlangan)."""
        if not self.path:
            return
        try:
            os.unlink(self.path)
        except OSError:
            log.debug("Vaqtinchalik klipni o'chirib bo'lmadi: %s", self.path)
        finally:
            self.path = ""


class EvidenceRecorder:
    """
    Hodisadan dalil yasaydi va navbatga qo'yadi.

    YUBORISH BU YERDA EMAS: u tarmoq amali va `ApiWorker` orqali
    fon thread'ida bajariladi. Bu sinf faqat FAYL yasaydi va
    navbatni boshqaradi - shu tufayli uni tarmoqsiz sinash mumkin.
    """

    def __init__(self, buffer, *, policy: Optional[dict] = None) -> None:
        self._buffer = buffer
        self._enabled = False
        self._clip_seconds = 5.0
        self._min_severity = 2
        self._pending: list = []
        self._dropped = 0
        self.configure(policy or {})

    # ------------------------------------------------------------------
    def configure(self, policy: dict) -> None:
        evidence = (policy or {}).get("evidence") or {}
        self._enabled = bool(evidence.get("enabled", False))
        self._clip_seconds = float(evidence.get("clip_seconds", 5) or 5)
        self._min_severity = int(evidence.get("min_severity", 2) or 0)

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def pending(self) -> list:
        return list(self._pending)

    @property
    def dropped(self) -> int:
        return self._dropped

    def clear(self) -> None:
        """Sessiya yakuni — navbat va vaqtinchalik fayllar tozalanadi."""
        for item in self._pending:
            item.cleanup()
        self._pending.clear()
        self._dropped = 0

    # ------------------------------------------------------------------
    def capture(self, event, *, started_at: Optional[float] = None,
                now: Optional[float] = None) -> list:
        """
        Hodisa uchun dalil yasaydi va navbatga qo'yadi.

        Qaytadi: yangi qo'shilgan dalillar (yuborish uchun).
        Bo'sh ro'yxat — dalil kerak emas yoki yasab bo'lmadi.
        """
        if not self._enabled:
            return []
        if int(getattr(event, "severity", 0)) < self._min_severity:
            # Har bir kichik hodisa uchun klip yozish diskni ham,
            # tarmoqni ham bekorga yeydi. Chegara siyosatda.
            return []

        now = now if now is not None else time.monotonic()
        started_at = started_at if started_at is not None else now - self._clip_seconds

        created: list = []
        frame_item = self._make_frame(event, now)
        if frame_item is not None:
            created.append(frame_item)

        clip_item = self._make_clip(event, started_at, now)
        if clip_item is not None:
            created.append(clip_item)

        for item in created:
            self._enqueue(item)
        return created

    def done(self, item: PendingEvidence) -> None:
        """Yuborildi — navbatdan olib tashlanadi va fayl o'chiriladi."""
        if item in self._pending:
            self._pending.remove(item)
        item.cleanup()

    def requeue(self, item: PendingEvidence) -> None:
        """
        Yuborilmadi — navbatga QAYTARILADI.

        Fayl saqlanadi: uni qayta yasab bo'lmaydi, chunki halqa
        bufer allaqachon yangi kadrlar bilan to'lgan.
        """
        if item not in self._pending:
            self._enqueue(item)

    # ------------------------------------------------------------------
    def _enqueue(self, item: PendingEvidence) -> None:
        self._pending.append(item)
        while len(self._pending) > _MAX_PENDING:
            # ENG ESKISI tashlanadi: yangi hodisa muhimroq, chunki
            # u hali tekshirilmagan. Eskisi esa ehtimol allaqachon
            # yuborilgan hodisaning takrori.
            dropped = self._pending.pop(0)
            dropped.cleanup()
            self._dropped += 1
            log.warning(
                "Dalil navbati to'ldi — eng eskisi tashlandi (jami %s)",
                self._dropped,
            )

    def _make_frame(self, event, now: float) -> Optional[PendingEvidence]:
        """Hodisa lahzasidagi kadr (JPEG)."""
        latest = self._buffer.latest()
        if latest is None:
            return None

        import cv2

        ok, encoded = cv2.imencode(
            ".jpg", latest.frame, [int(cv2.IMWRITE_JPEG_QUALITY), _JPEG_QUALITY]
        )
        if not ok:
            log.warning("Dalil kadrini kodlab bo'lmadi")
            return None

        return PendingEvidence(
            kind="frame",
            data=encoded.tobytes(),
            event_type=getattr(event, "type", ""),
            camera_role=getattr(event, "camera_role", ""),
            confidence=int(getattr(event, "confidence", 0) or 0),
            captured_at=_iso(now),
            boxes=_boxes_of(event),
        )

    def _make_clip(self, event, started_at: float, now: float) -> Optional[PendingEvidence]:
        """
        Hodisadan OLDINGI va keyingi kadrlardan video.

        Oyna hodisaning boshlanish vaqtidan boshlanadi, tasdiqlangan
        paytdan emas: eng qimmatli harakat (telefonni chiqarish)
        aynan o'sha oraliqda bo'ladi.
        """
        frames = self._buffer.window(since=started_at - self._clip_seconds, until=now)
        if len(frames) < 2:
            # Bitta kadrdan video yasashning ma'nosi yo'q - kadr
            # allaqachon alohida yuborilgan.
            return None

        import cv2

        height, width = frames[0].frame.shape[:2]
        span = max(0.1, frames[-1].timestamp - frames[0].timestamp)
        fps = max(1.0, min(30.0, len(frames) / span))

        handle, path = tempfile.mkstemp(suffix=".mp4", prefix="evidence-")
        os.close(handle)

        writer = cv2.VideoWriter(
            path, cv2.VideoWriter_fourcc(*_FOURCC), fps, (width, height)
        )
        if not writer.isOpened():
            log.warning("Video yozuvchi ochilmadi (kodek %s)", _FOURCC)
            _unlink(path)
            return None

        try:
            for item in frames:
                # Barcha kadrlar BIR XIL o'lchamda bo'lishi shart:
                # kamera rezolyutsiyani o'zgartirsa (ba'zi drayverlar
                # avtoekspozitsiyada shunday qiladi), `write` jimgina
                # kadrni tashlab yuboradi va klip qisqarib qoladi.
                frame = item.frame
                if frame.shape[:2] != (height, width):
                    frame = cv2.resize(frame, (width, height))
                writer.write(frame)
        finally:
            writer.release()

        if not os.path.exists(path) or os.path.getsize(path) == 0:
            log.warning("Klip bo'sh chiqdi — tashlab yuborildi")
            _unlink(path)
            return None

        return PendingEvidence(
            kind="clip",
            path=path,
            event_type=getattr(event, "type", ""),
            camera_role=getattr(event, "camera_role", ""),
            confidence=int(getattr(event, "confidence", 0) or 0),
            duration_ms=int(span * 1000),
            captured_at=_iso(frames[0].timestamp),
            boxes=_boxes_of(event),
        )


# --------------------------------------------------------------------------
def _iso(monotonic_value: float) -> str:
    """
    Monotonik vaqtni ISO sanaga o'giradi.

    Halqa bufer MONOTONIK soatni ishlatadi (u orqaga ketmaydi va
    NTP tuzatishidan ta'sirlanmaydi), server esa haqiqiy sanani
    kutadi. O'girish shu yerda, bitta joyda: hodisa vaqti va dalil
    vaqti ajralib ketmasligi kerak.
    """
    from datetime import datetime, timezone as dt_timezone

    offset = time.time() - time.monotonic()
    return datetime.fromtimestamp(
        monotonic_value + offset, tz=dt_timezone.utc
    ).isoformat()


def _boxes_of(event) -> list:
    """
    Dalil kadrida belgilanadigan narsalar — `behavior_analyzer._mark`.

    Kadrning O'ZIGA CHIZILMAYDI: JPEG toza qoladi va belgilar panelda
    rasm USTIDA chiziladi. Apellyatsiyada dalil — asl kadr; unga
    kuydirilgan ramka tasvirning bir qismini yopardi va "rasm
    o'zgartirilgan" degan e'tirozga yo'l ochardi.

    Koordinatalar kadrga NISBATAN (0..1). Ilgari piksel yuborilardi va
    u detektor kadrida (masalan 2688x1520) edi, dalil kadri esa 640 px
    — panelda ramkani to'g'ri joyga qo'yishning imkoni yo'q edi.
    """
    payload = getattr(event, "payload", None) or {}
    marks = payload.get("marks") or []
    return [dict(item) for item in marks if isinstance(item, dict) and item.get("box")][:20]


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
