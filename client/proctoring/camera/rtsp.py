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
        if capture is None or not capture.isOpened():
            if capture is not None:
                try:
                    capture.release()
                except Exception:
                    pass
            return self._fail(
                "RTSP oqimi ochilmadi: {}".format(safe_url(url))
            )

        try:
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            log.debug("RTSP: CAP_PROP_BUFFERSIZE qo'llab-quvvatlanmadi", exc_info=True)

        self._capture = capture
        self.info.width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        self.info.height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        self.info.declared_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)

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

        with _FFMPEG_LOCK:
            previous = os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS")
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = options
            try:
                return cv2.VideoCapture(url, cv2.CAP_FFMPEG)
            except Exception as exc:
                log.warning("RTSP ochishda istisno: %s", str(exc)[:200])
                return None
            finally:
                if previous is None:
                    os.environ.pop("OPENCV_FFMPEG_CAPTURE_OPTIONS", None)
                else:
                    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = previous

    def read(self) -> Optional[np.ndarray]:
        if self._capture is None:
            return None
        ok, frame = self._capture.read()
        return frame if ok else None

    def close(self) -> None:
        capture, self._capture = self._capture, None
        if capture is None:
            return
        try:
            capture.release()
        except Exception:
            log.debug("RTSP oqimini yopishda xato", exc_info=True)
