"""
Kamera oqimi - alohida thread.

`cv2.VideoCapture.read()` bloklovchi chaqiruv: UI thread'da bo'lsa oyna
har kadrda qotadi. Shuning uchun butun sikl QThread ichida, UI'ga esa
faqat tayyor kadr va natija signal bilan uzatiladi.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from config import CAMERA_INDEX, DETECT_EVERY_NTH_FRAME, FRAME_HEIGHT, FRAME_WIDTH, MIN_FACE_WIDTH_PX

log = logging.getLogger(__name__)


class CameraWorker(QThread):
    """
    Kadrlarni o'qiydi va yuzni aniqlaydi.

    Signallar:
        frame_ready(np.ndarray)  - har bir kadr (BGR), oldindan ko'rish uchun
        face_result(dict)        - detektsiya natijasi (pastga qarang)
        camera_error(str)        - kamera ochilmadi / kadr o'qilmadi

    `face_result` tarkibi:
        state: "none" | "far" | "multiple" | "ok"
        bboxes: list
        embedding: np.ndarray | None   (faqat state == "ok")
        det_score: float
    """

    frame_ready = pyqtSignal(object)
    face_result = pyqtSignal(dict)
    camera_error = pyqtSignal(str)

    def __init__(self, camera_index: int = CAMERA_INDEX, parent=None) -> None:
        super().__init__(parent)
        self._camera_index = camera_index
        # `True` bilan boshlanadi va FAQAT `stop()` uni o'chiradi.
        #
        # Ilgari u `False` edi va `run()` ichida `True` ga o'rnatilardi.
        # Bu poyga (race) berardi: `start()` dan keyin darhol `stop()`
        # chaqirilsa (operator FaceID sahifasini ochib, o'sha zahoti
        # orqaga bossa), `run()` bayroqni qaytadan `True` qilib qo'yardi
        # va sikl HECH QACHON to'xtamasdi.
        self._running = True
        self._engine = None

    def stop(self) -> None:
        """
        To'xtatish so'rovi.

        `terminate()` ISHLATILMAYDI: u kamera deskriptorini ochiq
        qoldiradi va Windows'da qurilma keyingi safar umuman ochilmaydi.
        Bayroq qo'yamiz va sikl o'zi chiqadi.
        """
        self._running = False

    def run(self) -> None:
        import cv2

        # `start()` dan keyin darhol `stop()` chaqirilgan bo'lishi mumkin -
        # unda kamerani umuman ochmaymiz.
        if not self._running:
            return

        # CAP_DSHOW - Windows'da MSMF backend'iga nisbatan ancha tez
        # ochiladi. Shu mashinada o'lchandi: DSHOW 0.8 s, MSMF 6.9 s.
        capture = cv2.VideoCapture(self._camera_index, cv2.CAP_DSHOW)
        if not capture.isOpened():
            self.camera_error.emit(
                "Kamera ochilmadi (indeks {}). Boshqa dastur band qilgan "
                "bo'lishi mumkin.".format(self._camera_index)
            )
            return

        try:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

            frame_index = 0
            failures = 0

            while self._running:
                ok, frame = capture.read()
                if not ok:
                    failures += 1
                    # Bitta o'tkazib yuborilgan kadr normal holat (USB
                    # uzilishi). Ketma-ket 30 tasi esa kamera yo'qolgani.
                    if failures > 30:
                        self.camera_error.emit("Kameradan kadr kelmayapti.")
                        break
                    time.sleep(0.03)
                    continue

                failures = 0
                self.frame_ready.emit(frame.copy())
                frame_index += 1

                if frame_index % max(1, DETECT_EVERY_NTH_FRAME) == 0:
                    self._process(frame)
        finally:
            # Har qanday chiqish yo'lida release - aks holda kamera band
            # qolib, dastur qayta ishga tushganda ochilmaydi.
            try:
                capture.release()
            except Exception:
                pass
            log.info("Kamera yopildi (indeks %s)", self._camera_index)

    # ------------------------------------------------------------------
    def _process(self, frame: np.ndarray) -> None:
        engine = self._ensure_engine()
        if engine is None or not engine.is_ready:
            return
        try:
            faces = engine.detect(frame)
        except Exception:
            log.exception("Detektsiya xatosi")
            return

        if not faces:
            self.face_result.emit({"state": "none", "bboxes": [], "embedding": None})
            return

        bboxes = [face["bbox"] for face in faces]

        if len(faces) > 1:
            # Kadrda ikkinchi odam - bu proktorlikda alohida hodisa.
            # Solishtirish qilinmaydi: kim tekshirilayotgani noaniq.
            self.face_result.emit(
                {"state": "multiple", "bboxes": bboxes, "embedding": None}
            )
            return

        face = faces[0]
        width = face["bbox"][2] - face["bbox"][0]
        if MIN_FACE_WIDTH_PX > 0 and width < MIN_FACE_WIDTH_PX:
            # Uzoqdagi yuz - ArcFace uni 112x112 ga cho'zadi va o'xshashlik
            # sun'iy ravishda pasayadi. Yolg'on "mos emas" berish o'rniga
            # operatordan yaqinroq turishni so'raymiz.
            self.face_result.emit({"state": "far", "bboxes": bboxes, "embedding": None})
            return

        self.face_result.emit(
            {
                "state": "ok",
                "bboxes": bboxes,
                "embedding": face["embedding"],
                "det_score": face["det_score"],
            }
        )

    def _ensure_engine(self):
        if self._engine is None:
            from services.face_engine import FaceEngine

            self._engine = FaceEngine()
        return self._engine


#: Tugashini kutib bo'lmagan kamera thread'lari.
#
#: `cv2.VideoCapture(...)` konstruktori BLOKLOVCHI: kamera band yoki
#: mavjud bo'lmasa, DirectShow bir necha soniya ushlab turadi va bu paytda
#: `stop()` bayrog'i o'qilmaydi. Agar shunday thread ob'ekti yo'q qilinsa,
#: Qt "QThread: Destroyed while thread is still running" bilan BUTUN
#: DASTURNI qulatadi. Shuning uchun tugamagan worker shu ro'yxatda
#: saqlanadi va yopilishda oxirgi marta kutiladi.
_RETIRED: list = []


def retire_camera(worker: Optional[CameraWorker], timeout_ms: int = 8000) -> bool:
    """
    Kamerani to'xtatadi va tugashini kutadi.

    `True` - tugadi. `False` - hali ishlayapti, lekin referens ushlab
    qolindi (`_RETIRED`), ya'ni u yo'q qilinmaydi va dastur qulamaydi.
    """
    if worker is None:
        return True
    worker.stop()
    if worker.wait(timeout_ms):
        worker.deleteLater()
        return True

    log.warning("Kamera thread'i %s ms ichida tugamadi - kutish davom etadi", timeout_ms)
    if worker not in _RETIRED:
        _RETIRED.append(worker)
        worker.finished.connect(lambda: _RETIRED.remove(worker) if worker in _RETIRED else None)
    return False


def await_retired_cameras(timeout_ms: int = 10000) -> None:
    """Dastur yopilishidan oldin oxirgi kutish."""
    for worker in list(_RETIRED):
        if worker.isRunning() and not worker.wait(timeout_ms):
            # Oxirgi chora: jarayon baribir tugayapti, lekin ishlab
            # turgan thread'ni yo'q qilish qulash demak.
            log.error("Kamera thread'i to'xtamadi - terminate")
            worker.terminate()
            worker.wait(2000)


def encode_jpeg(frame: np.ndarray, bbox: Optional[list] = None, quality: int = 85) -> bytes:
    """Kadrni (yoki yuz qirqimini) JPEG baytlarga aylantiradi."""
    import cv2

    image = frame
    if bbox is not None:
        height, width = frame.shape[:2]
        x1, y1, x2, y2 = bbox
        pad_x = int((x2 - x1) * 0.25)
        pad_y = int((y2 - y1) * 0.25)
        image = frame[
            max(0, y1 - pad_y) : min(height, y2 + pad_y),
            max(0, x1 - pad_x) : min(width, x2 + pad_x),
        ]
    ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buffer.tobytes() if ok else b""
