"""
Lokal veb-kamera (OpenCV + DirectShow).

Mavjud `services/camera_worker.py` da to'plangan ikkita amaliy
tajriba shu yerga ko'chirildi va ular tekshirilgan:

  * `CAP_DSHOW` Windows'da MSMF'dan ANCHA tez ochiladi (o'lchandi:
    0.8 s va 6.9 s). Imtihon oqimida bu farq sezilarli — operator
    har talabgor uchun kamerani qayta ochadi;
  * `release()` HAR QANDAY chiqish yo'lida chaqirilishi shart, aks
    holda Windows qurilmani band qoldiradi va keyingi ochish umuman
    ishlamaydi.
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

import numpy as np

from proctoring.camera.base import CameraInfo, CameraSource

log = logging.getLogger(__name__)


class WebcamSource(CameraSource):
    """USB yoki o'rnatilgan veb-kamera."""

    def __init__(
        self,
        index: int,
        *,
        role: str = "",
        width: int = 1280,
        height: int = 720,
        label: str = "",
        is_virtual: bool = False,
        device_path: str = "",
    ) -> None:
        super().__init__(
            CameraInfo(
                role=role,
                source="local",
                label=label or f"Veb-kamera #{index}",
                index=index,
                is_virtual=is_virtual,
                backend="dshow" if sys.platform == "win32" else "default",
            )
        )
        self._index = index
        #: DirectShow `DevicePath` — ochilmaganda sababni aniqlash uchun
        #: ("qurilma ro'yxatda bormi?", `diagnose.py`). Indeks
        #: qurilmalar qayta sanalganda siljiydi, yo'l esa yo'q.
        self._device_path = device_path or ""
        self._want_width = width
        self._want_height = height
        self._capture = None

    # ------------------------------------------------------------------
    def open(self) -> bool:
        import cv2

        self.close()

        if self._current_index() is None:
            return self._fail(self._explain(lost=False))

        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        capture = None
        try:
            capture = cv2.VideoCapture(self._index, backend)
            opened = capture.isOpened()
        except Exception as exc:
            # `cv2.error` drayver xatosida chiqadi (masalan qurilma
            # ochilish paytida sug'urildi). Istisno chaqiruvchining
            # siklini (qayta ulanish) buzmasligi kerak — oddiy
            # "ochilmadi" bo'lib qaytadi.
            log.warning("Kamerani ochishda istisno (indeks %s): %s", self._index, exc)
            opened = False
        if not opened:
            if capture is not None:
                try:
                    capture.release()
                except Exception:
                    pass
            return self._fail(self._explain(lost=False))

        try:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._want_width)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._want_height)
        except Exception:
            log.debug("Rezolyutsiya so'rovi qabul qilinmadi (indeks %s)", self._index)

        # MJPG SO'RALADI va u REZOLYUTSIYADAN KEYIN qo'yiladi.
        #
        # Sababi o'lchangan: DirectShow standart holatda siqilmagan
        # YUY2 formatini beradi va 1280x720 da bu USB kanaliga
        # sig'maydi — kamera 30 FPS e'lon qilib, amalda ~7 FPS
        # beradi. O'sha kameraning o'zi MJPG da 29 FPS ishlaydi
        # (bir xil mashinada: YUY2 7.5, MJPG 29.2).
        #
        # Bu server tomondagi "FPS past" xatosining eng ko'p
        # uchraydigan sababi edi va u ayblovni noto'g'ri joyga
        # yo'naltirardi: kamera ham, yorug'lik ham aybdor emas,
        # client noto'g'ri format so'ragan.
        #
        # TARTIB HAL QILUVCHI: FOURCC rezolyutsiyadan OLDIN
        # qo'yilsa, keyingi `CAP_PROP_FRAME_WIDTH` drayverni
        # standart formatga QAYTARADI va qiymat jimgina YUY2
        # bo'lib qoladi (o'lchandi: 7.1 FPS).
        #
        # Kamera MJPG ni qo'llab-quvvatlamasa `set()` shunchaki
        # ishlamaydi va eski format qoladi — bu xato emas, pastdagi
        # log o'sha holatni ko'rsatadi.
        try:
            capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        except Exception:
            log.debug("MJPG so'rovi qo'llab-quvvatlanmadi (indeks %s)", self._index)

        # Bufer 1 kadr: proktorlikda ESKI kadr yaroqsiz. Standart
        # buferda kadr bir necha yuz ms kechikadi va "hozir nima
        # bo'lyapti" degan savolga javob bermaydi.
        try:
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            # Ba'zi drayverlar bu xususiyatni qo'llab-quvvatlamaydi -
            # bu xato emas, faqat kechikish biroz kattaroq bo'ladi.
            log.debug("CAP_PROP_BUFFERSIZE qo'llab-quvvatlanmadi (indeks %s)", self._index)

        self._capture = capture
        # HAQIQIY qiymatlarni qurilmadan o'qiymiz: so'ralgan
        # rezolyutsiya berilmagan bo'lishi mumkin va tekshiruv
        # sahifasi so'ralganini emas, olinganini ko'rsatishi kerak.
        try:
            self.info.width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            self.info.height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            self.info.declared_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        except Exception:
            log.debug("Kamera xususiyatlari o'qilmadi (indeks %s)", self._index)

        # Format LOG'GA yoziladi: "FPS past" xatosini tekshirishda
        # birinchi savol aynan shu bo'ladi — kamera MJPG bermadimi?
        log.info(
            "Veb-kamera ochildi: indeks=%s %s @%.0f FPS, format=%s",
            self._index, self.info.resolution, self.info.declared_fps,
            self._fourcc(capture) or "?",
        )
        return True

    def _current_index(self) -> Optional[int]:
        """
        Qaysi indeks ochiladi — HAR OCHILISHDA qurilma yo'li bo'yicha.

        Indeks DirectShow sanog'idagi O'RIN: kamera uzilsa qolganlari
        siljiydi. `factory._resolve_index` uni faqat manba YARATILGANDA
        to'g'rilaydi, qayta ulanish esa shu obyektning `open()` ini
        chaqiradi. Eski indeks bilan noutbukda (ichki + USB kamera,
        USB #0) USB uzilganda ichki kamera #0 ga surilib OCHILARDI va
        "Kamera qayta ulandi" bo'lib, kuzatuv boshqa kamera bilan davom
        etardi.

        `None` — qurilma ro'yxatda yo'q, boshqalari bor: OCHILMAYDI
        (qayta ulanish sikli o'zini kutadi). Ro'yxat bo'sh bo'lsa eski
        indeks qoladi: bo'sh ro'yxat COM xatosi ham bo'lishi mumkin
        (`dshow.enumerate_devices`), kamera umuman yo'q bo'lsa esa
        `VideoCapture` baribir ochilmaydi.
        """
        if not self._device_path:
            return self._index
        from proctoring.camera.dshow import enumerate_devices

        devices = enumerate_devices()
        if not devices:
            return self._index
        for item in devices:
            if getattr(item, "device_path", "") != self._device_path:
                continue
            if item.index != self._index:
                log.warning(
                    "[%s] kamera indeksi siljigan (%s -> %s), qurilma yo'li bo'yicha "
                    "tuzatildi: %s",
                    self.info.role, self._index, item.index, self.info.label,
                )
                self._index = item.index
                self.info.index = item.index
            return self._index
        return None

    @staticmethod
    def _fourcc(capture) -> str:
        """Qurilma HAQIQATDA bergan piksel formati (`MJPG`, `YUY2`...)."""
        import cv2

        try:
            raw = int(capture.get(cv2.CAP_PROP_FOURCC))
        except Exception:
            return ""
        if raw <= 0:
            return ""
        return "".join(chr((raw >> (8 * shift)) & 0xFF) for shift in range(4)).strip()

    def _explain(self, *, lost: bool) -> str:
        """Operatorga tushunarli sabab (`diagnose.py`). Xato — umumiy matn."""
        try:
            from proctoring.camera.diagnose import explain_local_failure

            return explain_local_failure(self._index, self._device_path, lost=lost)
        except Exception:
            log.debug("Kamera nosozligi sababi aniqlanmadi", exc_info=True)
            return "Kamera ochilmadi (indeks {}).".format(self._index)

    def explain_lost(self) -> str:
        """Kadr kelmay qo'ydi — sababi (chaqiruvchi sikldan so'raydi)."""
        return self._explain(lost=True)

    def read(self) -> Optional[np.ndarray]:
        if self._capture is None:
            return None
        try:
            ok, frame = self._capture.read()
        except Exception as exc:
            # USB sug'urilganda ba'zi drayverlar `cv2.error` beradi.
            # Bu "kadr yo'q" — uzilishni ketma-ket bo'sh kadrlar
            # bo'yicha chaqiruvchi aniqlaydi.
            self._last_error = "Kadr o'qishda xato: {}".format(str(exc)[:120])
            return None
        return frame if ok else None

    def close(self) -> None:
        capture, self._capture = self._capture, None
        if capture is None:
            return
        try:
            capture.release()
        except Exception:
            log.debug("Kamerani yopishda xato (indeks %s)", self._index, exc_info=True)
