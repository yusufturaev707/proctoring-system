"""
Kamera oqimi - alohida thread.

`CameraSource.read()` bloklovchi chaqiruv: UI thread'da bo'lsa oyna
har kadrda qotadi. Shuning uchun butun sikl QThread ichida, UI'ga esa
faqat tayyor kadr va natija signal bilan uzatiladi.

QURILMANI O'ZI OCHMAYDI. Manba tashqaridan beriladi
(`proctoring/camera/factory.py`) va u AYNAN tekshiruv sahifasida
tanlangan taqsimotdan quriladi (`AppState.cameras`). Ilgari bu yerda
`cv2.VideoCapture(CAMERA_INDEX)` turardi va oqibati jimgina edi:
operator yuz kamerasini almashtirsa ham FaceID eski indeksni ochar,
ya'ni shaxs tekshiruvi STOLGA qaragan kameradan ketardi. Model esa
"yuz topilmadi" deb xabar berardi va sabab kamera tanlovida ekani
hech qayerdan ko'rinmasdi.

`CameraStream` (kuzatuv oqimi) bilan farqi: u qayta ulanish va FPS
o'lchash bilan shug'ullanadi, bu esa YUZ ANIQLASH bilan. Ikkalasi bir
xil manbani ishlatadi, lekin vazifasi boshqa - shuning uchun ular
alohida.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from config import CAMERA_INDEX, DETECT_EVERY_NTH_FRAME, MIN_FACE_WIDTH_PX

log = logging.getLogger(__name__)

#: Ikkinchi yuz ASOSIYSINING shuncha ulushidan KATTA bo'lsa —
#: "kadrda bir nechta odam", aks holda u fon deb e'tiborsiz
#: qoldiriladi.
#:
#: NIMA UCHUN O'LCHAM BO'YICHA. Yuz kengligi masofaga TESKARI
#: proporsional: kamera oldida o'tirgan talabgor ~60 sm da, orqa
#: qatordagi odam ~150 sm da — nisbat ~0.4. Yonida turgan odam
#: (~80 sm) esa ~0.75 beradi va u AYNAN shubhali holat: suflyor
#: talabgorga egilib turadi. Shuning uchun 0.7 — "orqadagi odam"
#: bilan "yonidagi odam" orasidagi chegara.
#:
#: Qat'iy piksel chegarasi bu ishni bajara olmasdi: u kameraning
#: ko'rish burchagiga va rezolyutsiyasiga bog'liq, nisbat esa
#: ikkalasidan ham mustaqil.
_DOMINANCE_RATIO = 0.7


def _face_width(face: dict) -> int:
    bbox = face["bbox"]
    return int(bbox[2] - bbox[0])


def select_candidate_face(faces: list) -> tuple:
    """
    Kadrdagi yuzlardan TALABGORNIKINI tanlaydi.

    Qaytaradi: `(holat, asosiy yuz | None, e'tiborsiz qoldirilganlar)`.

    MUAMMO. Imtihon zalida kadrga talabgordan boshqa odamlar ham
    tushadi: orqa qatordagi talabgorlar, o'tib ketayotgan operator,
    eshik oldidagi navbat. Ilgari bunday kadr `multiple` bo'lib,
    solishtirish UMUMAN bajarilmasdi va ikkala seriya ham uzilardi —
    ya'ni zalda o'tirgan talabgor tasdiqdan o'ta olmasdi va operator
    uning sababini ekrandan topa olmasdi.

    QOIDA AI QATLAMIDAGI BILAN BIR XIL
    (`proctoring/identity/face_identity.py`: "eng katta yuz —
    asosiy, uzoqdagi odam talabgorning o'rnini egallamasligi
    kerak"). Ikki joyda ikki xil javob bo'lsa, FaceID bir odamni,
    kuzatuv boshqasini "talabgor" deb hisoblardi.

    Uch bosqich va ularning tartibi muhim:

      1. UZOQDAGILAR tushib qoladi (`MIN_FACE_WIDTH_PX`). Bu
         chegara allaqachon bor edi va ma'nosi o'zgarmadi — ArcFace
         kichik yuzni 112x112 ga cho'zadi va ball sun'iy pasayadi.
         Endi u HAR BIR yuzga qo'llanadi, faqat yolg'iz qolganiga
         emas;
      2. eng kattasi ASOSIY deb olinadi — u kameraga eng yaqin
         odam, ya'ni kompyuter oldida o'tirgan talabgor;
      3. qolganlaridan biri undan sezilarli kichik bo'lmasa
         (`_DOMINANCE_RATIO`) — bu haqiqatan HAL QILIB BO'LMAYDIGAN
         holat: ikki odam bir xil masofada turibdi va qaysi biri
         talabgor ekani noma'lum. Shunda `multiple` qaytadi va
         hech kim solishtirilmaydi.

    Uchinchi qadamsiz tanlash XAVFLI bo'lardi: talabgor orqaga
    suriladi, suflyor kameraga yaqinroq egiladi va tizim AYNAN
    SUFLYORNI "talabgor" deb solishtirib, uni ham rad etardi —
    lekin sababi "mos kelmadi" bo'lib ko'rinardi.
    """
    if not faces:
        return "none", None, []

    ordered = sorted(faces, key=_face_width, reverse=True)
    near = (
        [face for face in ordered if _face_width(face) >= MIN_FACE_WIDTH_PX]
        if MIN_FACE_WIDTH_PX > 0
        else list(ordered)
    )
    if not near:
        # Yuz bor, lekin hammasi juda uzoqda. Bu "yuz yo'q" emas:
        # operatorga aytiladigan gap boshqa — "yaqinroq keling".
        return "far", None, ordered

    main = near[0]
    limit = _face_width(main) * _DOMINANCE_RATIO
    if any(_face_width(face) >= limit for face in near[1:]):
        return "multiple", None, []

    return "ok", main, [face for face in ordered if face is not main]


def source_for_role(layout, role: str = "primary", *, stream_url_provider=None):
    """
    Taqsimotdagi ROL uchun kadr manbai. `None` — ishlaydigan kamera yo'q.

    Bu funksiya `AppState.cameras` va kamerani ochish orasidagi
    YAGONA ko'prik. Sahifalar rolni so'raydi ("yuz kamerasi"),
    indeksni emas — indeks operator tanloviga qarab o'zgaradi
    (`roles.reassign`) va uni sahifalarda takrorlash o'sha tanlovni
    jimgina bekor qilardi.

    `stream_url_provider` — IP kamera uchun kredensial so'raydigan
    funksiya (`ProctoringRepository.camera_stream`). Berilmasa IP
    kamera ochilmaydi.
    """
    from proctoring.camera.base import CameraSpec
    from proctoring.camera.factory import build_source

    camera = layout.get(role) if layout is not None else None
    if camera is None or not camera.available:
        return None

    return build_source(
        CameraSpec.from_api(role, camera.as_slot()),
        stream_url_provider=stream_url_provider,
    )


class CameraWorker(QThread):
    """
    Kadrlarni o'qiydi va yuzni aniqlaydi.

    Signallar:
        frame_ready(np.ndarray)  - har bir kadr (BGR), oldindan ko'rish uchun
        face_result(dict)        - detektsiya natijasi (pastga qarang)
        camera_error(str)        - kamera ochilmadi / kadr o'qilmadi

    `face_result` tarkibi:
        state: "none" | "far" | "multiple" | "ok"
        bboxes: list                   (solishtirilayotgan yuz;
                                        "ok" da BITTA element)
        ignored: list                  (fon deb chetlatilgan yuzlar)
        total: int                     (kadrdagi umumiy son)
        embedding: np.ndarray | None   (faqat state == "ok")
        det_score: float
    """

    frame_ready = pyqtSignal(object)
    face_result = pyqtSignal(dict)
    camera_error = pyqtSignal(str)

    def __init__(self, source=None, *, camera_index: Optional[int] = None,
                 detect: bool = True, parent=None) -> None:
        """
        `source` — tayyor `CameraSource` (`source_for_role` bergan).

        Berilmasa ZAXIRA yo'l ishlaydi: `camera_index` yoki
        `CAMERA_INDEX` bo'yicha lokal kamera. U faqat taqsimot hali
        aniqlanmagan holat uchun (dev'da sahifani to'g'ridan-to'g'ri
        ochish) — odatdagi oqimda manba har doim rol bo'yicha keladi.
        """
        super().__init__(parent)
        self._source = source or self._fallback_source(camera_index)
        # `True` bilan boshlanadi va FAQAT `stop()` uni o'chiradi.
        #
        # Ilgari u `False` edi va `run()` ichida `True` ga o'rnatilardi.
        # Bu poyga (race) berardi: `start()` dan keyin darhol `stop()`
        # chaqirilsa (operator FaceID sahifasini ochib, o'sha zahoti
        # orqaga bossa), `run()` bayroqni qaytadan `True` qilib qo'yardi
        # va sikl HECH QACHON to'xtamasdi.
        self._running = True
        self._engine = None
        #: Yuz aniqlash yoqilganmi (`set_detection_enabled`).
        #
        # O'chiq bo'lsa kadrlar oqib turaveradi (oldindan ko'rish
        # ishlaydi), lekin model UMUMAN chaqirilmaydi va
        # `face_result` chiqmaydi. FaceID sahifasi shu bilan
        # talabgorga yuzini oval ichiga joylash uchun vaqt beradi:
        # natijani sahifada e'tiborsiz qoldirish yetmasdi - GPU
        # baribir band bo'lardi va sanoq tugashi bilan navbatda
        # turgan eski natija "birinchi kadr" bo'lib kelardi.
        #
        # Oddiy `bool`: yozish ham, o'qish ham GIL ostida atomik va
        # sikl uni har kadrda qayta o'qiydi.
        self._detect = bool(detect)
        # Registrdan chiqarish ASOSIY thread'da bajariladi: qabul
        # qiluvchi - shu obyekt va u asosiy thread'da yashaydi, ya'ni
        # ulanish navbatli (queued). Oxirgi referens aynan shu yerda,
        # thread tugagandan KEYIN tushadi.
        self.finished.connect(self._forget)

    def start(self, *args, **kwargs) -> None:
        """
        Ishga tushiradi va workerni `_LIVE` registriga yozadi.

        Registr - xavfsizlik to'ri. Ishlab turgan workerning oxirgi
        referensi tushib qolsa, PyQt uni ishlashda davom ettiradi,
        lekin thread O'ZI tugagan zahoti obyektni yo'q qiladi va
        jarayon `0xC0000409` bilan yiqiladi - Python istisnosi ham,
        log'da qator ham qolmaydi. Aynan shunday bo'lgan: kuzatuv
        rad etilganda FaceID kamerasi egasiz qoldi, operator
        imtihon sahifasiga qaytdi, kameralar qayta aniqlanganda
        qurilma band bo'lib, egasiz workerning sikli uzildi va
        dastur yopildi.

        Registr kamerani BO'SHATMAYDI - bu hali ham
        `retire_camera` ning ishi. U faqat unutilgan workerni
        dasturni qulatadigan holga kelishidan saqlaydi.
        """
        _LIVE.add(self)
        super().start(*args, **kwargs)

    def _forget(self) -> None:
        _LIVE.discard(self)

    @staticmethod
    def _fallback_source(camera_index: Optional[int]):
        from proctoring.camera.webcam import WebcamSource

        index = CAMERA_INDEX if camera_index is None else int(camera_index)
        log.warning(
            "Kamera taqsimoti berilmadi — zaxira indeks ishlatilmoqda (#%s)", index
        )
        return WebcamSource(index, role="primary")

    @property
    def label(self) -> str:
        """Ochilgan kameraning nomi — log va xabarlar uchun."""
        return getattr(getattr(self._source, "info", None), "label", "")

    def set_detection_enabled(self, enabled: bool) -> None:
        """Yuz aniqlashni yoqadi/o'chiradi - kamera to'xtamaydi."""
        self._detect = bool(enabled)

    @property
    def detection_enabled(self) -> bool:
        return self._detect

    def stop(self) -> None:
        """
        To'xtatish so'rovi.

        `terminate()` ISHLATILMAYDI: u kamera deskriptorini ochiq
        qoldiradi va Windows'da qurilma keyingi safar umuman ochilmaydi.
        Bayroq qo'yamiz va sikl o'zi chiqadi.
        """
        self._running = False

    def run(self) -> None:
        # `start()` dan keyin darhol `stop()` chaqirilgan bo'lishi mumkin -
        # unda kamerani umuman ochmaymiz.
        if not self._running:
            return

        source = self._source
        if source is None or not source.open():
            self.camera_error.emit(
                (getattr(source, "last_error", "") if source else "")
                or "Kamera ochilmadi."
            )
            return

        log.info("Kamera ochildi: %s", source.info.label)
        try:
            frame_index = 0
            failures = 0

            while self._running:
                frame = source.read()
                if frame is None:
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

                if self._detect and frame_index % max(1, DETECT_EVERY_NTH_FRAME) == 0:
                    self._process(frame)
        finally:
            # Har qanday chiqish yo'lida yopiladi - aks holda kamera
            # band qolib, keyingi sahifa (yoki kuzatuv oqimi) uni
            # umuman ocholmaydi.
            try:
                source.close()
            except Exception:
                log.debug("Kamerani yopishda xato", exc_info=True)
            log.info("Kamera yopildi: %s", source.info.label)

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

        state, main, ignored = select_candidate_face(faces)

        # KOORDINATALAR EKRANGA CHIZILMAYDI: FaceID sahifasida yuz
        # ramkasi yo'q, holatni oval rangi ko'rsatadi
        # (`CameraView`). Ular natijada qoladi - asosiy yuz va fonda
        # chetlatilganlari ALOHIDA, ya'ni tanlov qoidasining
        # (`select_candidate_face`) natijasi diagnostika va testda
        # tekshiriladigan bo'lib qoladi.
        payload = {
            "state": state,
            "bboxes": [main["bbox"]] if main is not None else [
                face["bbox"] for face in faces
            ],
            "ignored": [face["bbox"] for face in ignored],
            # Kadrdagi UMUMIY son - diagnostika uchun. Serverga
            # yuboriladigan `faces_detected` bundan MUSTAQIL va u
            # har doim 1: server "aynan bitta yuz ko'rindimi?" deb
            # emas, "qaror nechta yuz ustida qabul qilindi?" deb
            # so'raydi (`session.verify_initial_face`).
            "total": len(faces),
            "embedding": main["embedding"] if main is not None else None,
        }
        if main is not None:
            payload["det_score"] = main["det_score"]
        self.face_result.emit(payload)

    def _ensure_engine(self):
        if self._engine is None:
            from services.face_engine import FaceEngine

            self._engine = FaceEngine()
        return self._engine


#: Ishga tushirilgan va hali tugamagan barcha workerlar
#: (`CameraWorker.start` ga qarang). Ular egasiz qolsa ham shu yerda
#: referens turadi va thread tugagach ASOSIY thread'da chiqariladi.
_LIVE: set = set()


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
