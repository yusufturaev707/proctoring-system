"""
Ekran yozuvi — test sahifasi ochilgandan yakunigacha.

NIMA UCHUN SKRINSHOT YETMAYDI. Skrinshot har 10 soniyada olinadi,
ya'ni oradagi 9 soniya ko'rinmaydi: boshqa oynaga o'tib, javobni
ko'chirib, qaytib kelish aynan shu oraliqqa sig'adi. Yozuv esa
uzluksiz — apellyatsiyada "shu daqiqada ekranda nima bo'lgan?"
degan savolga faqat u javob beradi.

SERVERGA YUBORILMAYDI, FAQAT MANZILI. 3 soatlik yozuv ~0.5 GB;
500 mashinali bino kuniga yuzlab gigabayt degani va bu hech qanday
kanalga sig'maydi. Shuning uchun fayl mashinada qoladi
(`services/local_archive.py` dagi sessiya papkasida), serverga
esa uning yo'li, hajmi va davomiyligi boradi.

KADRDA UCH MANBA BIRLASHADI:

    ekran (asosiy monitor)  +  sichqoncha kursori  +  kamera (PiP)

PiP ataylab: yozuvda ekrandagi jarayon ko'rinadi, lekin "o'sha
paytda kompyuter oldida KIM o'tirgan edi?" degan savol ochiq
qolardi. Kursor ham ataylab: usiz "qaysi javob bosildi, qaysi
oynaga o'tildi" degan savolga yozuv javob bermasdi — ekran nusxasi
(Qt ham, GDI ham) kursorni o'zi chizmaydi.

TALABGOR PiP NI KO'RMAYDI. U ekranga chizilmaydi — birlashtirish
faqat kodlanayotgan kadrda, bizning jarayonimiz ichida bo'ladi.

BUTUN ISH BITTA FON THREAD'IDA (`_CaptureThread`) va bu asosiy
qaror. Ilgari ekran UI thread'ida olinardi (`QScreen.grabWindow`),
chunki Qt'da ekran nusxasi faqat shu yerdan mumkin. 1 FPS da bu
sezilmasdi, lekin yozuv "qotib-qotib" ko'rinardi. 5 FPS ga o'tish
uchun esa u yaroqsiz: bu mashinada bitta nusxa ~27 ms (eng ko'pi
55 ms), ya'ni har soniyaning ~14% ida UI thread band bo'lib, test
sahifasi (WebView) aynan talabgor javob yozayotganda tutilardi.

Shuning uchun ekran GDI orqali olinadi (`BitBlt`, `ctypes` — yangi
bog'liqliksiz): u istalgan thread'dan ishlaydi va DWM kompozitsiya
qilgan tayyor tasvirni beradi (WebView'ning GPU mazmuni ham).
GDI kontekstlari yozuv boshida BIR MARTA yaratiladi va har kadrda
qayta ishlatiladi.

VAQT JADVALI QAT'IY. Kadrlar monoton soat bo'yicha yoziladi: kadr
kechiksa (disk band, protsessor yuklangan), oldingi kadr TAKRORLANADI.
Aks holda 3 soatlik imtihon 2.5 soatlik videoga siqilib, "11:42 da
nima bo'lgan?" degan savolga yozuvdagi vaqt noto'g'ri javob berardi.
Takrorlangan kadrlar `dropped` da hisoblanadi.

KODEK `mp4v` va bu O'LCHAB tanlangan (60 s, haqiqiy ekran kadrlari
+ jonli kamera, 3 soatga hisob):

    mp4v 1 FPS 1280 (ilgari)   ~110 MB   matn PSNR 39.8 dB
    mp4v 5 FPS 1280            ~470 MB   matn PSNR 48.0 dB
    mp4v 5 FPS 1600 (hozir)    ~550 MB   tiniqroq matn
    MSMF H.264 5 FPS 1600     ~6100 MB   matn PSNR 41.7 dB

Windows'ning H.264 kodlovchisi OpenCV orqali bitreyt sozlamasini
QABUL QILMAYDI va o'zgarmas yuqori bitreytda yozadi — imtihon
mashinasi uchun yaroqsiz. `openh264` esa alohida DLL tarqatishni
talab qiladi. `mp4v` 5 FPS da 1 FPS dagidan TINIQROQ: ekran
o'zgarmagan kadrlarda kodlovchi tasvirni aniqlashtirib boradi.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
from PyQt6.QtCore import QObject, QThread, pyqtSignal

from services import runtime_settings

log = logging.getLogger(__name__)

#: Kodek — `evidence/recorder.py` dagi bilan AYNAN bir xil
#: (modul docstring'idagi o'lchovlarga qarang).
_FOURCC = "mp4v"

#: PiP ramkasining qalinligi va chetdan masofasi (piksel).
_PIP_BORDER = 2
_PIP_MARGIN = 12

#: Kechikishda bir iteratsiyada ko'pi bilan shuncha soniya takror
#: kadr yoziladi. Mashina uxlab qolsa yoki seans qulflansa bo'shliq
#: daqiqalab bo'lishi mumkin va uni bir zumda minglab kadr bilan
#: to'ldirish diskni bir necha soniya band qilardi. Undan uzun
#: bo'shliq yozuvda QISQARADI va log'da qayd etiladi.
_MAX_CATCHUP_SECONDS = 10.0


@dataclass
class RecordingResult:
    """Yozuv yakuni — serverga aynan shu ketadi."""

    path: str = ""
    size_bytes: int = 0
    duration_ms: int = 0
    frames: int = 0
    dropped: int = 0
    width: int = 0
    height: int = 0

    @property
    def ok(self) -> bool:
        return bool(self.path) and self.frames > 0


# --------------------------------------------------------------------------
# GDI ekran nusxasi (istalgan thread'dan)
# --------------------------------------------------------------------------
_SRCCOPY = 0x00CC0020
_CURSOR_SHOWING = 0x00000001
_DI_NORMAL = 0x0003


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
    ]


class _CURSORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
        ("hCursor", wintypes.HANDLE), ("ptScreenPos", wintypes.POINT),
    ]


class _ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD), ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP), ("hbmColor", wintypes.HBITMAP),
    ]


def _gdi():
    """
    `user32`/`gdi32` funksiyalari - `argtypes` BILAN.

    `restype` yetarli emas: usiz ctypes deskriptorni 32 bitli `int`
    deb uzatadi va 64 bitli tizimda chaqiruv `OverflowError` bilan
    yiqiladi (`CLAUDE.md`, "Tuzoqlar").
    """
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    signatures = [
        (user32.GetDC, wintypes.HDC, [wintypes.HWND]),
        (user32.ReleaseDC, ctypes.c_int, [wintypes.HWND, wintypes.HDC]),
        (user32.GetSystemMetrics, ctypes.c_int, [ctypes.c_int]),
        (user32.GetCursorInfo, wintypes.BOOL, [ctypes.POINTER(_CURSORINFO)]),
        (user32.GetIconInfo, wintypes.BOOL, [wintypes.HANDLE, ctypes.POINTER(_ICONINFO)]),
        (user32.DrawIconEx, wintypes.BOOL, [
            wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HANDLE, ctypes.c_int,
            ctypes.c_int, wintypes.UINT, wintypes.HBRUSH, wintypes.UINT,
        ]),
        (gdi32.CreateCompatibleDC, wintypes.HDC, [wintypes.HDC]),
        (gdi32.CreateCompatibleBitmap, wintypes.HBITMAP, [wintypes.HDC, ctypes.c_int, ctypes.c_int]),
        (gdi32.SelectObject, wintypes.HGDIOBJ, [wintypes.HDC, wintypes.HGDIOBJ]),
        (gdi32.BitBlt, wintypes.BOOL, [
            wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
        ]),
        (gdi32.GetDIBits, ctypes.c_int, [
            wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
            ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
        ]),
        (gdi32.DeleteObject, wintypes.BOOL, [wintypes.HGDIOBJ]),
        (gdi32.DeleteDC, wintypes.BOOL, [wintypes.HDC]),
    ]
    for fn, restype, argtypes in signatures:
        fn.restype, fn.argtypes = restype, argtypes
    return user32, gdi32


class ScreenGrabber:
    """
    Asosiy monitorning GDI nusxasi (+ kursor), BGR numpy.

    Kontekstlar QAYTA ishlatiladi: har kadrda `CreateCompatibleDC`/
    `CreateCompatibleBitmap` qilish vaqtning katta qismini olardi.
    Monitor o'lchami o'zgarsa (drayver qayta yuklandi) bitmap qayta
    yaratiladi. Obyekt BITTA thread'da ishlatiladi va `close()`
    shu thread'da chaqiriladi.

    Koordinatalar FIZIK pikselda: Qt jarayonni DPI'ga sezgir qilib
    ishga tushiradi, ya'ni 125% masshtabda ham to'liq 1920x1080 olinadi.
    """

    def __init__(self) -> None:
        self._user32, self._gdi32 = _gdi()
        self._screen_dc = None
        self._mem_dc = None
        self._bitmap = None
        self._old = None
        self._size = (0, 0)
        self._buffer: Optional[np.ndarray] = None
        #: `hCursor` -> (xHotspot, yHotspot). `GetIconInfo` har chaqiruvda
        #: ikkita bitmap yaratadi va ularni o'chirish shart - keshsiz bu
        #: sekundiga 5 marta keraksiz ish bo'lardi.
        self._hotspots: dict = {}

    def grab(self) -> Optional[np.ndarray]:
        width = self._user32.GetSystemMetrics(0)   # SM_CXSCREEN
        height = self._user32.GetSystemMetrics(1)  # SM_CYSCREEN
        if width <= 0 or height <= 0:
            return None
        if (width, height) != self._size:
            self._release()
            self._allocate(width, height)
        if not self._gdi32.BitBlt(
            self._mem_dc, 0, 0, width, height, self._screen_dc, 0, 0, _SRCCOPY
        ):
            return None
        self._draw_cursor()
        header = _BITMAPINFOHEADER(
            ctypes.sizeof(_BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0
        )
        lines = self._gdi32.GetDIBits(
            self._mem_dc, self._bitmap, 0, height,
            self._buffer.ctypes.data, ctypes.byref(header), 0,
        )
        if lines != height:
            return None
        # BGRA -> BGR. Nusxa emas, ko'rinish: chaqiruvchi uni darhol
        # miqyoslaydi (yangi massiv) va bufer keyingi kadrda qayta
        # to'ldiriladi.
        return self._buffer[:, :, :3]

    def _allocate(self, width: int, height: int) -> None:
        self._screen_dc = self._user32.GetDC(None)
        self._mem_dc = self._gdi32.CreateCompatibleDC(self._screen_dc)
        self._bitmap = self._gdi32.CreateCompatibleBitmap(self._screen_dc, width, height)
        self._old = self._gdi32.SelectObject(self._mem_dc, self._bitmap)
        self._buffer = np.empty((height, width, 4), np.uint8)
        self._size = (width, height)

    def _draw_cursor(self) -> None:
        info = _CURSORINFO()
        info.cbSize = ctypes.sizeof(_CURSORINFO)
        if not self._user32.GetCursorInfo(ctypes.byref(info)):
            return
        if not (info.flags & _CURSOR_SHOWING) or not info.hCursor:
            return
        handle = int(info.hCursor)
        hotspot = self._hotspots.get(handle)
        if hotspot is None:
            icon = _ICONINFO()
            if not self._user32.GetIconInfo(info.hCursor, ctypes.byref(icon)):
                return
            hotspot = (int(icon.xHotspot), int(icon.yHotspot))
            for bitmap in (icon.hbmMask, icon.hbmColor):
                if bitmap:
                    self._gdi32.DeleteObject(bitmap)
            self._hotspots[handle] = hotspot
        self._user32.DrawIconEx(
            self._mem_dc,
            info.ptScreenPos.x - hotspot[0],
            info.ptScreenPos.y - hotspot[1],
            info.hCursor, 0, 0, 0, None, _DI_NORMAL,
        )

    def _release(self) -> None:
        if self._mem_dc:
            if self._old:
                self._gdi32.SelectObject(self._mem_dc, self._old)
            self._gdi32.DeleteDC(self._mem_dc)
        if self._bitmap:
            self._gdi32.DeleteObject(self._bitmap)
        if self._screen_dc:
            self._user32.ReleaseDC(None, self._screen_dc)
        self._screen_dc = self._mem_dc = self._bitmap = self._old = None
        self._size = (0, 0)
        self._buffer = None

    def close(self) -> None:
        self._release()


def _output_size(width: int, height: int, max_width: int) -> tuple:
    """Yozuv o'lchami: `max_width` gacha, JUFT sonlar (kodek talabi)."""
    target = max_width if max_width and width > max_width else width
    out_h = int(round(height * target / width))
    return (target - target % 2, out_h - out_h % 2)


# --------------------------------------------------------------------------
# Yozuv thread'i
# --------------------------------------------------------------------------
class _CaptureThread(QThread):
    """
    Olish -> kursor -> miqyoslash -> PiP -> kodlash, qat'iy FPS bilan.

    `QThread` (oddiy `threading.Thread` emas): dasturdagi qolgan
    thread'lar bilan bir xil hayot siklida bo'lishi va yopilishda
    `wait()` bilan kutilishi kerak — tugamagan yozuvchi faylni
    buzilgan holda qoldirardi.
    """

    def __init__(self, path: str, size: tuple, fps: float, camera_provider,
                 pip_ratio: float, parent=None) -> None:
        super().__init__(parent)
        self._path = path
        self._size = size
        self._fps = max(0.5, float(fps))
        self._camera_provider = camera_provider
        self._pip_ratio = float(pip_ratio)
        # `True` KONSTRUKTORDA: `start()` dan keyin darhol `stop()`
        # chaqirilsa, `run()` bayroqni qaytarib qo'yib sikl abadiy
        # ishlardi (`CameraWorker` dagi bilan bir xil tuzoq).
        self._running = True
        self.frames = 0
        self.dropped = 0
        self.error = ""

    def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    def run(self) -> None:
        # Tayyorgarlik ham `try` ichida: `cv2` DLL'ini antivirus to'sgan,
        # disk to'la yoki GDI resursi tugagan bo'lsa istisno thread'dan
        # chiqib ketardi va `error` bo'sh qolardi - yozuv "ishlayapti"
        # bo'lib ko'rinardi.
        try:
            import cv2

            writer = cv2.VideoWriter(
                self._path, cv2.VideoWriter_fourcc(*_FOURCC), self._fps, self._size
            )
        except Exception:
            self.error = "VideoWriter ochilmadi"
            log.exception("Ekran yozuvini ochib bo'lmadi: %s", self._path)
            return
        if not writer.isOpened():
            self.error = "VideoWriter ochilmadi"
            log.error("Ekran yozuvini ochib bo'lmadi: %s", self._path)
            return

        try:
            grabber = ScreenGrabber()
        except Exception:
            self.error = "ekran nusxasi olinmadi"
            log.exception("Ekran nusxalovchisi yaratilmadi")
            try:
                writer.release()
            except Exception:
                log.debug("VideoWriter yopilmadi", exc_info=True)
            return
        interval = 1.0 / self._fps
        started = time.monotonic()
        last: Optional[np.ndarray] = None
        try:
            while self._running:
                frame = self._capture(grabber, cv2)
                if frame is not None:
                    last = frame
                if last is None:
                    time.sleep(interval)
                    continue

                # Shu paytgacha yozilgan bo'lishi KERAK bo'lgan kadrlar.
                due = int((time.monotonic() - started) * self._fps) + 1
                missing = due - self.frames
                if missing > 1:
                    cap = int(_MAX_CATCHUP_SECONDS * self._fps)
                    if missing - 1 > cap:
                        log.warning(
                            "Ekran yozuvida %.0f s bo'shliq - %s s gacha to'ldirildi",
                            (missing - 1) / self._fps, _MAX_CATCHUP_SECONDS,
                        )
                        # Bo'shliqning ortig'i "unutiladi": soat surilib,
                        # keyingi kadrlar yana joriy vaqtga bog'lanadi.
                        started += (missing - 1 - cap) / self._fps
                        missing = cap + 1
                    for _ in range(missing - 1):
                        writer.write(last)
                    self.dropped += missing - 1
                    self.frames += missing - 1
                if missing >= 1:
                    writer.write(last)
                    self.frames += 1

                next_at = started + self.frames / self._fps
                delay = next_at - time.monotonic()
                if delay > 0:
                    # Bo'lingan uyqu: `stop()` dan keyin yakun 50 ms dan
                    # ortiq kutmasligi kerak (imtihon yakunining yo'lida).
                    end = time.monotonic() + delay
                    while self._running and time.monotonic() < end:
                        time.sleep(min(0.05, end - time.monotonic()))
        except Exception:
            self.error = "yozuvda xato"
            log.exception("Ekran yozuvida xato")
        finally:
            grabber.close()
            try:
                writer.release()
            except Exception:
                log.debug("VideoWriter yopilmadi", exc_info=True)

    def _capture(self, grabber: ScreenGrabber, cv2) -> Optional[np.ndarray]:
        try:
            raw = grabber.grab()
        except Exception:
            log.debug("Ekran nusxasi olinmadi", exc_info=True)
            return None
        if raw is None:
            return None
        # INTER_AREA - kichraytirishda matn uchun eng tiniq usul.
        # Rezolyutsiya o'zgargan bo'lsa ham kadr BIRINCHI o'lchamga
        # keltiriladi: `VideoWriter` boshqa o'lchamdagi kadrni jimgina
        # tashlab yuborardi va yozuv o'sha joydan to'xtardi.
        if (raw.shape[1], raw.shape[0]) != self._size:
            frame = cv2.resize(raw, self._size, interpolation=cv2.INTER_AREA)
        else:
            frame = np.ascontiguousarray(raw)
        return self._compose(frame, cv2)

    def _compose(self, frame: np.ndarray, cv2) -> np.ndarray:
        """
        Ekran kadriga kamera tasvirini qo'yadi (O'NG YUQORI burchak).

        Yuqorida, pastda emas: test platformasining pastki qismi eng
        zich joy (javob variantlari, "Keyingi" tugmasi, savollar
        ro'yxati) va u yerdagi ramka yozuvdagi dalilning aynan shu
        qismini yopardi. Ramka KICHIK (`capture.record_pip_percent`,
        standart 12%) - yuzni tanish uchun yetarli, ekranni yopmaydi.

        Kamera kadri YO'Q bo'lsa ekran kadri o'zgarishsiz qoladi:
        kamera qayta ulanayotgan bo'lishi mumkin va yozuvning
        to'xtashi bundan ancha yomon.

        Provayder SHU THREAD'DAN chaqiriladi va u faqat O'QIYDI
        (sahifadagi oxirgi kadr havolasi yoki supervisor oqimi
        mutex ostida) - UI thread'ga murojaat yo'q.
        """
        if self._camera_provider is None:
            return frame
        try:
            camera = self._camera_provider()
        except Exception:
            log.debug("Kamera kadrini olib bo'lmadi", exc_info=True)
            return frame
        if camera is None or getattr(camera, "size", 0) == 0:
            return frame

        height, width = frame.shape[:2]
        pip_width = max(96, int(width * self._pip_ratio))
        scale = pip_width / camera.shape[1]
        pip_height = max(54, int(camera.shape[0] * scale))
        if pip_height >= height or pip_width >= width:
            return frame

        pip = cv2.resize(camera, (pip_width, pip_height), interpolation=cv2.INTER_AREA)
        x2 = width - _PIP_MARGIN
        y1 = _PIP_MARGIN
        x1, y2 = x2 - pip_width, y1 + pip_height

        frame[y1:y2, x1:x2] = pip
        # Oq ramka - PiP ekran mazmuni bilan qo'shilib ketmasligi
        # uchun. Ramkasiz to'q kadrda kamera tasviri "ekranning bir
        # qismi" bo'lib ko'rinardi.
        frame[y1 - _PIP_BORDER:y1, x1 - _PIP_BORDER:x2 + _PIP_BORDER] = 255
        frame[y2:y2 + _PIP_BORDER, x1 - _PIP_BORDER:x2 + _PIP_BORDER] = 255
        frame[y1 - _PIP_BORDER:y2 + _PIP_BORDER, x1 - _PIP_BORDER:x1] = 255
        frame[y1 - _PIP_BORDER:y2 + _PIP_BORDER, x2:x2 + _PIP_BORDER] = 255
        return frame


# --------------------------------------------------------------------------
# Tashqi interfeys
# --------------------------------------------------------------------------
class ScreenRecorder(QObject):
    """
    Ekran yozuvi. `start()` va `stop()` dan boshqa hech narsa kerak emas —
    chaqiruvchi (imtihon sahifasi) yozuvning ichki ishini bilmaydi.
    """

    #: Yozuv to'xtadi.
    finished = pyqtSignal(object)  # RecordingResult

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._thread: Optional[_CaptureThread] = None
        self._path = ""
        self._size: tuple = (0, 0)
        self._started_at = 0.0
        self._retired: list = []

    @property
    def is_active(self) -> bool:
        return self._thread is not None

    def start(
        self,
        path: str,
        *,
        camera_provider: Optional[Callable] = None,
        config: Optional[dict] = None,
    ) -> bool:
        """
        Yozuvni boshlaydi. `False` — boshlanmadi (sabab log'da).

        `camera_provider()` — joriy kamera kadrini (BGR numpy)
        qaytaradigan funksiya; `None` qaytarishi XATO EMAS.

        `config` — IMTIHON PROFILI (`AppState.config`): FPS, kenglik va
        PiP ulushi shundan (`capture.record_*`), zaxira — `.env`. Ular
        yozuv BOSHIDA bir marta o'qiladi va yozuv davomida
        o'zgarmaydi: `VideoWriter` oqim o'rtasida na FPS, na o'lcham
        o'zgarishini qabul qiladi.

        Kadr O'LCHAMI birinchi nusxadan olinadi va keyin
        O'ZGARMAYDI: `VideoWriter` oqim o'rtasida o'lcham
        o'zgarishini qabul qilmaydi.
        """
        if self._thread is not None:
            return False
        if sys.platform != "win32":
            log.warning("Ekran yozuvi faqat Windows'da (GDI) - o'tkazib yuborildi")
            return False

        # SINOV NUSXASI - bir marta, shu yerda: o'lchamni aniqlash va
        # yozuv umuman mumkinligini imtihon boshida bilish uchun.
        probe_grabber = ScreenGrabber()
        try:
            probe = probe_grabber.grab()
            probe = None if probe is None else probe.copy()
        except Exception:
            log.exception("Ekran kadrini olib bo'lmadi")
            probe = None
        finally:
            probe_grabber.close()
        if probe is None:
            log.error("Ekran kadrini olib bo'lmadi - yozuv boshlanmaydi")
            return False

        if not probe.any():
            # BUTUNLAY QORA KADR. Ekran o'chgan bo'lishi mumkin, lekin
            # ko'pincha sabab boshqa: qulflangan seans yoki ko'rinadigan
            # oynasi yo'q jarayon. Yozuv TO'XTATILMAYDI - ekran keyinroq
            # paydo bo'lishi mumkin, lekin log'da iz qolishi shart: aks
            # holda qop-qora fayl apellyatsiya kunida ochilardi.
            log.warning(
                "Ekran nusxasi qop-qora keldi (%s) - yozuv baribir boshlanadi", path
            )

        fps = runtime_settings.get(config, "capture.record_fps")
        max_width = runtime_settings.get(config, "capture.record_width")
        pip_ratio = runtime_settings.get(config, "capture.record_pip_percent")

        height, width = probe.shape[:2]
        self._size = _output_size(width, height, max_width)
        self._path = path
        self._started_at = time.monotonic()

        thread = _CaptureThread(
            path, self._size, fps, camera_provider, pip_ratio, parent=self
        )
        thread.start()
        self._thread = thread
        log.info(
            "Ekran yozuvi boshlandi: %s (%sx%s -> %sx%s, %.1f FPS, PiP %d%%)",
            path, width, height, self._size[0], self._size[1], fps, pip_ratio * 100,
        )
        return True

    def stop(self) -> RecordingResult:
        """
        Yozuvni yakunlaydi va natijani qaytaradi.

        TAKRORIY CHAQIRUV XAVFSIZ: sahifa yopilishi ham, imtihon
        yakunlanishi ham, vaqt tugashi ham shu yerga keladi va
        ularning tartibi kafolatlanmagan.
        """
        thread = self._thread
        self._thread = None
        if thread is None:
            return RecordingResult()

        thread.stop()
        # Kutish CHEKLANGAN: odatda ~50 ms (bo'lingan uyqu + faylni
        # yopish), cheksiz kutish esa imtihon yakunini osib qo'yardi.
        if not thread.wait(8000):
            log.warning("Ekran yozuvi thread'i tugamadi - kutish davom etadi")
            self._retired.append(thread)
            thread.finished.connect(
                lambda: self._retired.remove(thread) if thread in self._retired else None
            )

        result = RecordingResult(
            path=self._path,
            size_bytes=_file_size(self._path),
            duration_ms=int((time.monotonic() - self._started_at) * 1000),
            frames=thread.frames,
            dropped=thread.dropped,
            width=self._size[0],
            height=self._size[1],
        )
        log.info(
            "Ekran yozuvi yakunlandi: %s ta kadr (%s tasi takror), %.1f MB, %.1f daqiqa",
            result.frames, result.dropped,
            result.size_bytes / (1024 * 1024), result.duration_ms / 60000.0,
        )
        self.finished.emit(result)
        return result

    def shutdown(self) -> None:
        """Dastur yopilishidan oldingi oxirgi kutish."""
        self.stop()
        for thread in list(self._retired):
            if thread.isRunning() and not thread.wait(5000):
                log.error("Ekran yozuvi to'xtamadi - terminate")
                thread.terminate()
                thread.wait(2000)
        self._retired.clear()


def _file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0
