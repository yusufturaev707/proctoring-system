"""
IP kamera (RTSP, OpenCV + FFmpeg).

NIMA UCHUN `hikvision.py` EMAS. Vendor RTSP URL'ga TA'SIR QILMAYDI:
yo'lni administrator `Camera.rtsp_path` da belgilaydi, portni
`Camera.port`, transportni `Camera.transport`. Vendorga qarab yo'lni
"bilib olish" modeli birinchi nostandart proshivkada buziladi va xato
client tomonda "oqim ochilmadi" degan umumiy xabar bo'lib ko'rinadi —
ya'ni eng qiyin diagnostika qilinadigan turdagi nosozlik.

Shuning uchun bitta manba sinfi barcha vendorlarga xizmat qiladi.
Vendor-maxsus xatti-harakat (masalan ONVIF orqali qidirish) kerak
bo'lganda alohida sinf qo'shiladi.

KREDENSIAL XOTIRADA. URL parol bilan birga keladi va u diskka
YOZILMAYDI, log'ga CHIQMAYDI (`safe_url` ga qarang) va istisno
matnida ko'rinmaydi. Sessiya tugagach `close()` uni tozalaydi.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from typing import Optional

import numpy as np

from proctoring.camera.base import CameraInfo, CameraSource

log = logging.getLogger(__name__)

#: `rtsp://login:parol@host` dagi kredensial qismi.
_CREDENTIALS_RE = re.compile(r"//[^/@]*@")

#: FFmpeg parametrlari GLOBAL muhit o'zgaruvchisi orqali beriladi
#: (`OPENCV_FFMPEG_CAPTURE_OPTIONS`) — OpenCV'da boshqa yo'l yo'q.
#:
#: Ikkita kamera bir vaqtda ochilsa, ikkinchisi birinchisining
#: qiymatini bosib qo'yishi mumkin. Qulf shu poygani yopadi: o'zgaruvchi
#: qo'yiladi, `VideoCapture` yaratiladi va o'zgaruvchi tiklanadi —
#: hammasi bitta kritik bo'limda.
_FFMPEG_LOCK = threading.Lock()

#: RTSP ochish va kadr o'qish uchun vaqt chegarasi (ms). Kamera
#: o'chirilgan yoki tarmoq uzilgan bo'lsa FFmpeg shundan ortiq
#: kutmaydi. `GuardedSource` (`guard.py`) ikkinchi himoya qatlami:
#: uning chegarasi bulardan KATTA, ya'ni odatda FFmpeg o'zi qaytadi.
_OPEN_TIMEOUT_MS = 10000
_READ_TIMEOUT_MS = 5000


def safe_url(url: str) -> str:
    """Log va UI uchun: kredensialsiz manzil."""
    return _CREDENTIALS_RE.sub("//", url or "")


class RtspSource(CameraSource):
    """RTSP oqimi (Hikvision, Dahua, ONVIF-mos va boshqalar)."""

    def __init__(
        self,
        url_provider,
        *,
        role: str = "",
        label: str = "",
        address: str = "",
        transport: str = "tcp",
    ) -> None:
        """
        `url_provider` — URL QAYTARADIGAN FUNKSIYA, satr emas.

        Sabab: kredensial serverdan so'raladi va u qayta ulanishda
        qaytadan olinishi kerak bo'lishi mumkin (masalan client uni
        tashlab yuborgan yoki administrator kamera parolini
        almashtirgan). Satr sifatida uzatilsa, u obyekt umri
        davomida yashab qolardi va biz uni qachon tashlashni nazorat
        qila olmasdik.
        """
        super().__init__(
            CameraInfo(
                role=role,
                source="ip",
                label=label or "IP kamera",
                address=address,
                backend="ffmpeg",
            )
        )
        self._url_provider = url_provider
        self._transport = (transport or "tcp").lower()
        self._capture = None

    # ------------------------------------------------------------------
    def open(self) -> bool:
        import cv2

        self.close()

        try:
            url = self._url_provider()
        except Exception as exc:
            # Sabab matni kredensial o'z ichiga olmasligi kafolatlanmagan
            # (u tarmoq kutubxonasidan keladi), shuning uchun qisqartiramiz.
            return self._fail("Kamera manzilini olib bo'lmadi: {}".format(str(exc)[:120]))

        if not url:
            return self._fail("Server kamera manzilini bermadi")

        capture = self._open_capture(url)
        try:
            opened = capture is not None and capture.isOpened()
        except Exception:
            opened = False
        if not opened:
            if capture is not None:
                try:
                    capture.release()
                except Exception:
                    pass
            return self._fail(
                "IP kamera oqimi ochilmadi: {}. Kamera yoqilganini va "
                "tarmoqqa ulanganini tekshiring; qayta ulanish avtomatik "
                "davom etadi.".format(safe_url(url))
            )

        try:
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            log.debug("RTSP: CAP_PROP_BUFFERSIZE qo'llab-quvvatlanmadi", exc_info=True)

        self._capture = capture
        try:
            self.info.width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            self.info.height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            self.info.declared_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        except Exception:
            log.debug("RTSP xususiyatlari o'qilmadi", exc_info=True)

        log.info(
            "RTSP ochildi: %s (%s, %s) %s",
            self.info.label, safe_url(url), self._transport, self.info.resolution,
        )
        return True

    def _open_capture(self, url: str):
        """
        FFmpeg parametrlari bilan `VideoCapture`.

        `stimeout` (mikrosoniya) MAJBURIY: usiz kamera o'chirilgan
        bo'lsa `VideoCapture` konstruktori bir necha DAQIQA bloklanadi
        va thread `stop()` bayrog'ini o'qiy olmaydi — bu dastur
        yopilishida "QThread: Destroyed while thread is still running"
        bilan tugaydi.
        """
        import cv2

        options = "|".join(
            [
                "rtsp_transport;{}".format("udp" if self._transport == "udp" else "tcp"),
                # 5 soniya — kamera javob bermasa shuncha kutamiz.
                "stimeout;5000000",
                # Kadr buferini minimal ushlash: dalil uchun eski kadr
                # yaroqsiz.
                "fflags;nobuffer",
                "flags;low_delay",
            ]
        )

        # OpenCV'ning O'Z vaqt chegaralari (4.6+). `stimeout` FFmpeg
        # versiyasiga bog'liq: bundle'dagi avformat 58 (FFmpeg 4.4) uni
        # taniydi, FFmpeg 5+ esa uni olib tashlagan (u yerda `timeout`
        # boshqa ma'noga ega — 4.4 da u "tinglash" rejimini yoqardi,
        # shuning uchun uni bu yerga qo'shib bo'lmaydi). OpenCV
        # parametrlari esa uzish callback'i orqali ishlaydi va FFmpeg
        # versiyasidan MUSTAQIL — ochish ham, o'qish ham chegaralanadi.
        params = []
        if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
            params += [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, _OPEN_TIMEOUT_MS]
        if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
            params += [cv2.CAP_PROP_READ_TIMEOUT_MSEC, _READ_TIMEOUT_MS]

        with _FFMPEG_LOCK:
            previous = os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS")
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = options
            try:
                if params:
                    return cv2.VideoCapture(url, cv2.CAP_FFMPEG, params)
                return cv2.VideoCapture(url, cv2.CAP_FFMPEG)
            except Exception as exc:
                log.warning("RTSP ochishda istisno: %s", safe_url(str(exc))[:200])
                return None
            finally:
                if previous is None:
                    os.environ.pop("OPENCV_FFMPEG_CAPTURE_OPTIONS", None)
                else:
                    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = previous

    def read(self) -> Optional[np.ndarray]:
        if self._capture is None:
            return None
        try:
            ok, frame = self._capture.read()
        except Exception as exc:
            # Istisno matnida URL (kredensial bilan) bo'lishi mumkin —
            # faqat turi yoziladi.
            self._last_error = "RTSP kadr o'qishda xato ({})".format(type(exc).__name__)
            return None
        return frame if ok else None

    def close(self) -> None:
        capture, self._capture = self._capture, None
        if capture is None:
            return
        try:
            capture.release()
        except Exception:
            log.debug("RTSP oqimini yopishda xato", exc_info=True)
