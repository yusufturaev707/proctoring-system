"""
IP kamera tasvirini panelda KO'RISH - server tomondagi o'quvchi.

BRAUZER RTSP NI O'YNATA OLMAYDI, shuning uchun oqimni server ochadi va
panelga JPEG kadrlar ketma-ketligini (MJPEG) bitta uzun HTTP javobda
yuboradi (`CameraViewSet.live`). Har kadr uchun alohida so'rov (ilgari
shunday edi) har safar autentifikatsiya, DB va Redis'dan o'tardi va
sekundiga 4 tadan ortiq kadr bermasdi - tasvir "qotib-qotib" ko'rinardi.

QOTISHNING ASL SABABI - DEKODLASH QUVVATI. O'lchangan (Hikvision,
HEVC 2688x1520, amalda ~22.5 kadr/s):

    1 thread dekodlash               ~28 kadr/s  (25% zaxira)
    + har kadrni BGR ga o'girish     ~16 ms/kadr -> ~20 kadr/s < kamera
    4 thread dekodlash (hozir)       ~38 kadr/s  (70% zaxira)

Kamera tezligidan sekin o'quvchida FFmpeg buferi to'lib boradi va
kechikish TO'XTOVSIZ o'sadi: bir daqiqada ~10 soniya - tasvir qotadi,
keyin sakraydi. Shuning uchun uch qaror:

  1. KO'P THREADLI DEKODLASH (`CAP_PROP_N_THREADS`). Kadr-thread
     rejimi 2-3 kadrlik (~100 ms) qo'shimcha kechikish beradi - 2 s
     byudjetda bu arzon narx.
  2. HAR KADRDA FAQAT `grab()`, rangga o'girish (`retrieve()`) esa
     FAQAT yuboriladigan kadrda (~12 kadr/s). 4MP kadrni har safar
     BGR ga o'girish o'quvchini kameradan sekin qilib qo'yardi.
  3. MIQYOSLASH VA JPEG ALOHIDA THREAD'DA (`_Encoder`): ular
     `grab()` siklini to'xtatmasligi kerak. Kodlovchi har doim ENG
     YANGI kadrni oladi, orqada qolsa oraliqdagilari tashlanadi.

KECHIKISH QO'RIQCHISI - kafolat, umid emas. Jonli chegarada `grab()`
tarmoqni kutadi (median ~47 ms), buferdan o'qiganda esa darhol
qaytadi (median ~0 ms). Oxirgi 20 ta `grab()` ning medianasi 12 ms
dan kam bo'lib, bu 1.5 s dan uzoq davom etsa - o'quvchi orqada
qolgan: oqim QAYTA OCHILADI va jonli chegaraga sakraydi. Kuchsiz
serverda bu uzilish beradi, lekin kechikish 2 s dan oshmaydi.

Har kamera uchun BITTA o'quvchi (jarayon ichida) va u barcha
ko'ruvchilarga umumiy. Hech kim ko'rmasa `_IDLE_SECONDS` dan keyin
yopiladi - ochiq RTSP ulanishi kameraning cheklangan ulanishlaridan
birini band qilib turardi.

OpenCV (`opencv-python-headless`) FAQAT SHU YERDA va dangasa import
qilinadi: u o'zi bilan FFmpeg olib keladi. ML yo'q, faqat dekodlash.
"""

from __future__ import annotations

import logging
import os
import statistics
import threading
import time
from collections import deque
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

#: So'rov bo'lmasa o'quvchi shuncha soniyadan keyin yopiladi.
_IDLE_SECONDS = 20.0
#: Panelga yuboriladigan kadr chastotasi. 12 - ko'z uchun silliq
#: harakat va tarmoq uchun ~1 MB/s (1280 px, sifat 78).
_OUTPUT_FPS = 12.0
#: Kadr kengligi - "aniq" tasvir uchun 1280 (4MP kameraning yuzlari
#: va ekranlari o'qiladi), to'liq 2688 esa trafikni 4 barobar oshirardi.
_MAX_WIDTH = 1280
_JPEG_QUALITY = 78
#: Birinchi kadrni kutish (ulanish + birinchi kalit-kadr).
_FIRST_FRAME_TIMEOUT = 8.0
_OPEN_TIMEOUT_MS = 5000
_READ_TIMEOUT_MS = 5000
#: Dekodlash thread'lari. Ko'prog'i deyarli foyda bermaydi va har
#: thread bir kadrlik kechikish qo'shadi.
_DECODE_THREADS = max(1, min(4, os.cpu_count() or 1))

#: Kechikish qo'riqchisi (modul docstring'i).
_BACKLOG_WINDOW = 20
_BACKLOG_GRAB_MS = 12.0
_BACKLOG_MAX_SECONDS = 1.5
#: Yangi kadr shuncha vaqt kelmasa oqim "to'xtagan" hisoblanadi.
_STALE_SECONDS = 3.0

_registry: dict = {}
_registry_lock = threading.Lock()
#: `OPENCV_FFMPEG_CAPTURE_OPTIONS` - JARAYON darajasidagi o'zgaruvchi.
#: Ikki o'quvchi bir vaqtda turli transport bilan ochilsa, biri
#: boshqasinikini olib qo'yardi - shuning uchun ochish ketma-ket.
_open_lock = threading.Lock()


class CameraUnavailable(Exception):
    """Kadr olib bo'lmadi - sababi odam tilida."""


class _Encoder(threading.Thread):
    """
    Miqyoslash + JPEG - `grab()` siklidan ALOHIDA.

    Pochta qutisi BITTA o'rinli: yangi kadr eskisining ustiga yoziladi.
    Kodlovchi orqada qolsa oraliqdagi kadrlar tashlanadi - panelga
    har doim ENG YANGI holat boradi, navbat hech qachon to'planmaydi.
    """

    def __init__(self, reader: "_Reader") -> None:
        super().__init__(name="camera-encode-{}".format(reader.camera_id), daemon=True)
        self._reader = reader
        self._slot = None
        self._ready = threading.Condition()

    def offer(self, frame, taken_at: float) -> None:
        with self._ready:
            self._slot = (frame, taken_at)
            self._ready.notify()

    def run(self) -> None:
        import cv2

        while self._reader.alive:
            with self._ready:
                if self._slot is None:
                    self._ready.wait(0.5)
                item, self._slot = self._slot, None
            if item is None:
                continue
            frame, taken_at = item
            height, width = frame.shape[:2]
            if width > _MAX_WIDTH:
                frame = cv2.resize(
                    frame, (_MAX_WIDTH, int(height * _MAX_WIDTH / width)),
                    interpolation=cv2.INTER_AREA,
                )
            ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY])
            if ok:
                self._reader.publish(buffer.tobytes(), taken_at)


class _Reader(threading.Thread):
    def __init__(self, camera_id: int, url: str, transport: str, signature: str) -> None:
        super().__init__(name="camera-live-{}".format(camera_id), daemon=True)
        self.camera_id = camera_id
        self.signature = signature
        self._url = url
        self._transport = transport or "tcp"
        self._frame_cond = threading.Condition()
        self._jpeg: Optional[bytes] = None
        self._jpeg_at = 0.0
        self._seq = 0
        self.error = ""
        self.reconnects = 0
        self.last_request = time.monotonic()
        self.alive = True
        self._encoder: Optional[_Encoder] = None

    # --- ko'ruvchilar uchun ------------------------------------------------
    def touch(self) -> None:
        self.last_request = time.monotonic()

    def latest(self) -> tuple:
        with self._frame_cond:
            return self._jpeg, self._jpeg_at, self._seq

    def wait_next(self, after_seq: int, timeout: float) -> tuple:
        """`after_seq` dan YANGI kadr kelguncha kutadi (yoki o'quvchi o'lguncha)."""
        with self._frame_cond:
            self._frame_cond.wait_for(
                lambda: self._seq > after_seq or not self.alive, timeout=timeout
            )
            return self._jpeg, self._jpeg_at, self._seq

    def publish(self, jpeg: bytes, taken_at: float) -> None:
        with self._frame_cond:
            self._jpeg = jpeg
            self._jpeg_at = taken_at
            self._seq += 1
            self._frame_cond.notify_all()

    # --- o'quvchi sikli ------------------------------------------------------
    def run(self) -> None:
        self._encoder = _Encoder(self)
        self._encoder.start()
        try:
            while self._idle_for() < _IDLE_SECONDS:
                if not self._session():
                    break
                self.reconnects += 1
        except Exception as exc:  # noqa: BLE001 - o'quvchi jarayonni yiqitmaydi
            logger.exception("Kamera o'quvchisida xato: camera=%s", self.camera_id)
            self.error = "Oqimni o'qib bo'lmadi: {}".format(str(exc)[:120])
        finally:
            self.alive = False
            with self._frame_cond:
                self._frame_cond.notify_all()
            with _registry_lock:
                if _registry.get(self.camera_id) is self:
                    _registry.pop(self.camera_id, None)
            logger.info(
                "Kamera o'quvchisi yopildi: camera=%s qayta ulanishlar=%s",
                self.camera_id, self.reconnects,
            )

    def _idle_for(self) -> float:
        return time.monotonic() - self.last_request

    def _open(self):
        import cv2

        with _open_lock:
            # `nobuffer`/`low_delay` - FFmpeg'ning kirish buferini
            # qisqartiradi: birinchi kadr tezroq, jonli chegara yaqinroq.
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
                "rtsp_transport;{}|fflags;nobuffer|flags;low_delay".format(self._transport)
            )
            return cv2.VideoCapture(
                self._url,
                cv2.CAP_FFMPEG,
                [
                    cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, _OPEN_TIMEOUT_MS,
                    cv2.CAP_PROP_READ_TIMEOUT_MSEC, _READ_TIMEOUT_MS,
                    cv2.CAP_PROP_N_THREADS, _DECODE_THREADS,
                ],
            )

    def _session(self) -> bool:
        """
        Bitta ulanish. `True` - qayta ulanish kerak (orqada qoldi),
        `False` - tugadi (ko'ruvchi yo'q yoki xato).
        """
        capture = self._open()
        try:
            if not capture.isOpened():
                self.error = "Oqim ochilmadi (tarmoq, login/parol yoki RTSP yo'li)"
                return False
            self.error = ""
            failures = 0
            grabs: deque = deque(maxlen=_BACKLOG_WINDOW)
            behind_since = 0.0
            # YUBORISH KAMERA RITMIDA: har N-kadr (kamera tezligi / 12).
            # "Oxirgi yuborishdan 83 ms o'tdimi?" qoidasi ~45 ms oraliqli
            # kadrlarda ko'pincha uchinchi kadrni kutib, ~8 kadr/s va
            # notekis oraliq berardi - ko'zga bu "tutilish" bo'lib
            # ko'rinadi. Kamera tezligi jonli chegaradagi `grab()`
            # oraliqlaridan o'lchanadi (e'lon qilingan FPS ko'pincha
            # yolg'on: bu kamera 25 deydi, amalda ~22.5 beradi).
            frame_index = 0
            last_grab_at = 0.0
            frame_interval = 1.0 / 25.0

            while self._idle_for() < _IDLE_SECONDS:
                started = time.monotonic()
                if not capture.grab():
                    failures += 1
                    if failures >= 3:
                        self.error = "Kameradan kadr kelmayapti"
                        return False
                    continue
                failures = 0
                now = time.monotonic()
                grabs.append((now - started) * 1000.0)
                if last_grab_at and not behind_since:
                    # EMA: bitta kechikkan paket tempni sakratmasin.
                    frame_interval += 0.05 * ((now - last_grab_at) - frame_interval)
                last_grab_at = now

                # --- kechikish qo'riqchisi ---
                if len(grabs) == _BACKLOG_WINDOW and statistics.median(grabs) < _BACKLOG_GRAB_MS:
                    behind_since = behind_since or now
                    if now - behind_since > _BACKLOG_MAX_SECONDS:
                        logger.warning(
                            "Kamera o'quvchisi orqada qoldi - jonli chegaraga qayta ulanish: camera=%s",
                            self.camera_id,
                        )
                        return True
                else:
                    behind_since = 0.0

                # Buferdan o'qilayotganda kadr ESKI - uni yubormaymiz,
                # faqat buferni bo'shatamiz.
                if behind_since:
                    continue
                frame_index += 1
                stride = max(1, round(1.0 / (max(frame_interval, 1e-3) * _OUTPUT_FPS)))
                if frame_index % stride:
                    continue
                ok, frame = capture.retrieve()
                if not ok or frame is None:
                    continue
                self._encoder.offer(frame, time.time())
            return False
        finally:
            capture.release()


def _reader_for(camera, url: str) -> _Reader:
    """
    Kameraning o'quvchisi - yo'q bo'lsa ochiladi.

    Kamera sozlamasi (manzil, login, transport) o'zgargan bo'lsa eski
    o'quvchi tashlanadi - aks holda tahrirdan keyin panel eski
    manzilning tasvirini ko'rsatib turardi.
    """
    import hashlib

    signature = hashlib.sha256("{}|{}".format(url, camera.transport).encode("utf-8")).hexdigest()
    with _registry_lock:
        reader = _registry.get(camera.pk)
        if reader is None or not reader.alive or reader.signature != signature:
            reader = _Reader(camera.pk, url, camera.transport, signature)
            _registry[camera.pk] = reader
            reader.start()
    reader.touch()
    return reader


def snapshot(camera, url: str) -> tuple:
    """Eng yangi kadr: `(jpeg_bytes, olingan_vaqt_unix)` - bitta kadr kerak bo'lganda."""
    reader = _reader_for(camera, url)
    jpeg, taken_at, seq = reader.latest()
    if jpeg is None:
        jpeg, taken_at, seq = reader.wait_next(0, _FIRST_FRAME_TIMEOUT)
    if jpeg is None:
        raise CameraUnavailable(
            reader.error or "Kamera javob bermadi ({} s)".format(int(_FIRST_FRAME_TIMEOUT))
        )
    return jpeg, taken_at


def open_stream(camera, url: str, *, max_seconds: float) -> Iterator[tuple]:
    """
    Kadrlar oqimi: `(jpeg, olingan_vaqt_unix)` - YANGI kadr kelishi bilan.

    Birinchi kadr SHU YERDA kutiladi (generator emas): kamera ochilmasa
    chaqiruvchi oddiy xato javobini qaytara oladi - bo'sh oqim panelda
    tushunarsiz "yuklanmoqda" bo'lib qolardi.

    Oqim `max_seconds` dan keyin tugaydi va panel darhol qayta ulanadi
    (o'quvchi issiq qoladi). Cheksiz so'rov gunicorn thread'ini abadiy
    band qilardi.
    """
    reader = _reader_for(camera, url)
    jpeg, taken_at, seq = reader.latest()
    if jpeg is None:
        jpeg, taken_at, seq = reader.wait_next(0, _FIRST_FRAME_TIMEOUT)
    if jpeg is None:
        raise CameraUnavailable(
            reader.error or "Kamera javob bermadi ({} s)".format(int(_FIRST_FRAME_TIMEOUT))
        )

    def frames():
        nonlocal jpeg, taken_at, seq
        deadline = time.monotonic() + max_seconds
        yield jpeg, taken_at
        while time.monotonic() < deadline and reader.alive:
            reader.touch()
            next_jpeg, next_at, next_seq = reader.wait_next(seq, _STALE_SECONDS)
            if next_seq == seq:
                # Kadr kelmadi - oqim to'xtagan. Uzilish panelga
                # ko'rinsin: u qayta ulanadi va xatoni ko'rsatadi.
                if not reader.alive:
                    break
                continue
            jpeg, taken_at, seq = next_jpeg, next_at, next_seq
            yield jpeg, taken_at

    return frames()


def active_readers() -> int:
    """Diagnostika va testlar uchun."""
    with _registry_lock:
        return sum(1 for reader in _registry.values() if reader.alive)
