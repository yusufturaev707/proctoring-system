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
from proctoring.camera.liveness import DEAD_STREAM_MESSAGE, FrameLiveness
from proctoring.camera.liveness import applies as liveness_applies

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

#: Qayta ulanish kechikishlari (soniya), oxirgisi takrorlanadi.
#:
#: FaceID ishchisi faqat LOKAL/rol kamerasini ochadi va operator
#: kamera oldida turadi: kabel qayta ulangach 30 s kutish (kuzatuv
#: oqimidagi IP kamera qatori) "dastur kamerani ko'rmayapti" degan
#: taassurot berardi. Urinish arzon — qurilma yo'q bo'lsa DirectShow
#: darhol rad etadi.
_BACKOFF_S = (1, 2, 3, 5)

#: Ketma-ket shuncha bo'sh kadrdan keyin kamera "yo'qolgan" (~1 s).
_EMPTY_FRAMES_BEFORE_LOST = 30

#: Qurilma hali tizimdami - shu oraliqda (s); `manager._PRESENCE_CHECK_S`.
_PRESENCE_CHECK_S = 2.0

#: Kadr sifati chegaralari (`assess_quality`). Ular faqat OPERATORGA
#: MASLAHAT tanlaydi ("yorug'lik yetarli emas"), qarorga ta'sir
#: qilmaydi — shuning uchun taxminiy qiymatlar yetarli.
#:
#: Yorqinlik — luma o'rtachasi (0..255): 45 dan past kadrda
#: InsightFace yuzni ko'pincha umuman topmaydi, 230 dan yuqorisi —
#: ortiqcha yoritilgan (deraza orqada, yuz "oqarib" ketgan).
_DARK_LUMA = 45
_BRIGHT_LUMA = 230
#: Yuz qirqimidagi Laplas dispersiyasi (112 px kenglikka keltirilgan
#: kulrang tasvir). O'tkir yuzda odatda 100+, harakatdan xiralashganda
#: 20 dan past tushadi.
_BLUR_VARIANCE = 20.0


def assess_quality(frame, bbox=None) -> list:
    """
    Kadr (yoki yuz qirqimi) sifati: `["dark" | "bright" | "blurry"]`.

    SOF FUNKSIYA va istisno TASHLAMAYDI — sifat faqat maslahat, uning
    xatosi tekshiruvni to'xtatmasligi kerak. `bbox` berilsa yorqinlik
    va xiralik YUZ ustida o'lchanadi: fon (oq devor, qorong'i xona)
    yuz qanday ko'rinishini aytmaydi.
    """
    issues: list = []
    try:
        import cv2

        if frame is None or getattr(frame, "ndim", 0) != 3:
            return issues
        region = frame
        if bbox is not None:
            height, width = frame.shape[:2]
            x1, y1, x2, y2 = [int(value) for value in bbox[:4]]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(width, x2), min(height, y2)
            if x2 - x1 >= 8 and y2 - y1 >= 8:
                region = frame[y1:y2, x1:x2]
        # Yorqinlik siyrak tanlanma bo'yicha: aniqlik emas, kattalik
        # tartibi kerak (`camera/measure.py:_brightness` bilan bir xil).
        sample = region[::4, ::4]
        luma = float(
            (sample[:, :, 0] * 0.114 + sample[:, :, 1] * 0.587 + sample[:, :, 2] * 0.299).mean()
        )
        if luma < _DARK_LUMA:
            issues.append("dark")
        elif luma > _BRIGHT_LUMA:
            issues.append("bright")
        if bbox is not None and region is not frame:
            gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
            scale = 112.0 / max(1, gray.shape[1])
            gray = cv2.resize(gray, None, fx=scale, fy=scale)
            if float(cv2.Laplacian(gray, cv2.CV_64F).var()) < _BLUR_VARIANCE:
                issues.append("blurry")
    except Exception:
        log.debug("Kadr sifatini baholab bo'lmadi", exc_info=True)
    return issues


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
                                   (uzilish boshiga BIR MARTA, sabab
                                   o'zgarsa yana; ishchi TO'XTAMAYDI)
        camera_restored()        - uzilishdan keyin kadrlar qaytdi

    `face_result` tarkibi:
        state: "none" | "far" | "multiple" | "ok"
        bboxes: list                   (solishtirilayotgan yuz;
                                        "ok" da BITTA element)
        ignored: list                  (fon deb chetlatilgan yuzlar)
        total: int                     (kadrdagi umumiy son)
        embedding: np.ndarray | None   (faqat state == "ok")
        det_score: float
        quality: list                  ("dark" | "bright" | "blurry",
                                        faqat maslahat uchun)
    """

    frame_ready = pyqtSignal(object)
    face_result = pyqtSignal(dict)
    camera_error = pyqtSignal(str)
    camera_restored = pyqtSignal()

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
        from proctoring.camera.factory import guarded

        # Manba VAQT CHEGARASI bilan (`camera/guard.py`): osilgan
        # `read()` ishchini qotirmasin va `retire_camera` UI thread'ida
        # uzoq kutmasin. `source_for_role` bergani allaqachon o'ralgan.
        self._source = guarded(source or self._fallback_source(camera_index))
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
        #: Hozir uzilish bormi va oxirgi aytilgan sabab — xabar
        #: uzilish boshida BIR MARTA chiqadi (va sabab o'zgarganda).
        #: Har urinishda chiqarish imtihon sahifasida bir xil
        #: `camera_lost` hodisalarini yog'dirardi.
        self._outage = False
        self._reported_error = ""
        #: Uyqudan uyg'onish — ulanishni yopib darhol qayta ochish.
        self._reconnect_requested = False
        #: Detektsiya xatolari soni — log'ni har kadrda to'ldirmaslik uchun.
        self._detect_errors = 0
        try:
            from core.system_events import system_events

            system_events().power_resumed.connect(self.request_reconnect)
        except Exception:
            # Modul bo'lmasa qayta ulanish baribir bo'sh kadrlar
            # orqali ishlaydi — faqat sekinroq.
            log.debug("power_resumed signaliga ulanib bo'lmadi", exc_info=True)
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
        Bayroq qo'yamiz va sikl o'zi chiqadi. Osilgan `open()`/`read()`
        kutishi ham darhol uziladi (`GuardedSource.abort`).
        """
        self._running = False
        abort = getattr(self._source, "abort", None)
        if abort is not None:
            try:
                abort()
            except Exception:
                log.debug("Kamera abort xatosi", exc_info=True)

    def request_reconnect(self) -> None:
        """Ulanishni yopib, darhol qayta ochish (uyqudan uyg'onish)."""
        if self._running:
            log.info("Kamera qayta ulanadi (uyqudan uyg'onish)")
            self._reconnect_requested = True

    def run(self) -> None:
        # `start()` dan keyin darhol `stop()` chaqirilgan bo'lishi mumkin -
        # unda kamerani umuman ochmaymiz.
        if not self._running:
            return

        source = self._source
        if source is None:
            self._report_error("Yuz kamerasi topilmadi.")
            return

        # UZILISH ISHCHINI TO'XTATMAYDI. Ilgari kamera ochilmasa yoki
        # kadr kelmay qolsa `run()` tugardi va sahifa qayta ochmaguncha
        # kamera o'lik qolardi: imtihon paytida USB kabel bir soniya
        # chiqib ketsa, davriy FaceID imtihon oxirigacha ishlamasdi.
        # Endi ishchi qisqa oraliqlar bilan (`_BACKOFF_S`) qayta
        # ulanadi va kadr qaytgach `camera_restored` beradi.
        #
        # Kutilmagan istisno ham siklni o'ldirmaydi — tutilmagan xato
        # thread'ni jimgina tugatardi va sahifada oxirgi kadr qotib
        # qolardi.
        attempt = 0
        try:
            while self._running:
                try:
                    attempt = self._cycle(source, attempt)
                except Exception as exc:
                    log.exception("Kamera ishchisida kutilmagan xato")
                    self._report_error("Kamera xatosi: {}".format(str(exc)[:120]))
                    self._close(source)
                    if not self._sleep_backoff(attempt):
                        break
                    attempt += 1
        finally:
            # Har qanday chiqish yo'lida yopiladi - aks holda kamera
            # band qolib, keyingi sahifa (yoki kuzatuv oqimi) uni
            # umuman ocholmaydi.
            self._close(source)
            log.info("Kamera yopildi: %s", source.info.label)

    def _cycle(self, source, attempt: int) -> int:
        """Bitta "ochish -> o'qish -> uzilish" aylanishi. Keyingi `attempt`."""
        self._reconnect_requested = False
        if not source.open():
            self._report_error(source.last_error or "Kamera ochilmadi.")
            if not self._sleep_backoff(attempt):
                return attempt
            return attempt + 1

        log.info("Kamera ochildi: %s", source.info.label)
        reason = self._read_loop(source)
        self._close(source)
        if reason == "dead":
            # O'lik oqim (`liveness.py`): yopilgandan keyin keyingi ochilish
            # usuli (`WebcamSource.recover_dead_stream`), kechikish O'SADI.
            from proctoring.camera.manager import _recover

            step = _recover(source)
            if step:
                log.warning("Kamera: o'lik oqim - keyingi urinish: %s", step)
            if not self._sleep_backoff(attempt):
                return attempt
            return attempt + 1
        if self._running and not self._reconnect_requested:
            self._sleep_backoff(0)
        return 0

    def _read_loop(self, source) -> str:
        """Kadrlar sikli. Qaytadi: "dead" - o'lik oqim, "" - boshqa sabab."""
        frame_index = 0
        failures = 0
        last_presence = time.monotonic()
        liveness = FrameLiveness() if liveness_applies(source) else None
        while self._running:
            if self._reconnect_requested:
                return ""
            now = time.monotonic()
            if now - last_presence >= _PRESENCE_CHECK_S:
                last_presence = now
                # USB sug'urilganda DirectShow kadr qaytaraverishi mumkin -
                # bo'sh kadrlar qoidasi buni ko'rmaydi (`WebcamSource.is_present`).
                if source.is_present() is False:
                    self._report_error(_explain_lost(source))
                    return ""
            frame = source.read()
            read_s = time.monotonic() - now
            if frame is None:
                failures += 1
                # Bitta o'tkazib yuborilgan kadr normal holat (USB
                # uzilishi). Ketma-ket 30 tasi esa kamera yo'qolgani.
                if failures >= _EMPTY_FRAMES_BEFORE_LOST:
                    self._report_error(_explain_lost(source))
                    return ""
                time.sleep(0.03)
                continue

            failures = 0
            if liveness is not None:
                state = liveness.observe(frame, read_s, time.monotonic())
                summary = liveness.report(time.monotonic())
                if summary:
                    log.info("Kamera oqimi (%s): %s", source.info.label, summary)
                if state == "dead":
                    self._report_error(DEAD_STREAM_MESSAGE)
                    return "dead"
                if state != "live":
                    continue  # qora/qotgan bufer - "tiklandi" ham, kadr ham emas
            if self._outage:
                self._outage = False
                self._reported_error = ""
                log.info("Kamera tiklandi: %s", source.info.label)
                self.camera_restored.emit()
            self.frame_ready.emit(frame.copy())
            frame_index += 1

            if self._detect and frame_index % max(1, DETECT_EVERY_NTH_FRAME) == 0:
                self._process(frame)

    def _report_error(self, message: str) -> None:
        """Uzilish haqida xabar — boshida bir marta, sabab o'zgarsa yana."""
        self._outage = True
        if message == self._reported_error:
            return
        self._reported_error = message
        log.warning("Kamera: %s", message)
        self.camera_error.emit(message)

    def _sleep_backoff(self, attempt: int) -> bool:
        """
        Qayta urinishdan oldingi kutish. `False` — to'xtatish so'raldi.

        Kichik bo'laklarda: `stop()` va uyg'onish so'rovi darhol sezilsin.
        """
        delay = _BACKOFF_S[min(attempt, len(_BACKOFF_S) - 1)]
        deadline = time.monotonic() + delay
        while self._running and time.monotonic() < deadline:
            if self._reconnect_requested:
                break
            self.msleep(100)
        return self._running

    @staticmethod
    def _close(source) -> None:
        try:
            source.close()
        except Exception:
            log.debug("Kamerani yopishda xato", exc_info=True)

    # ------------------------------------------------------------------
    def _process(self, frame: np.ndarray) -> None:
        engine = self._ensure_engine()
        if engine is None or not engine.is_ready:
            return
        try:
            faces = engine.detect(frame)
        except Exception:
            # Log THROTTLE qilinadi: xato odatda har kadrda
            # takrorlanadi (masalan GPU uyqudan keyin yo'qolgan) va
            # har 300 ms da to'liq traceback log faylini to'ldirardi.
            # GPU'dan CPU'ga o'tishni dvigatelning o'zi hal qiladi
            # (`FaceEngine._run`).
            self._detect_errors += 1
            if self._detect_errors == 1 or self._detect_errors % 100 == 0:
                log.exception("Detektsiya xatosi (%s-marta)", self._detect_errors)
            return
        self._detect_errors = 0

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
        # SIFAT — faqat maslahat: yuz bo'lsa uning ustida, yuz
        # topilmasa butun kadr bo'yicha ("qorong'i — shuning uchun
        # topilmadi"). Qarorga ta'sir qilmaydi.
        if state in ("ok", "none"):
            payload["quality"] = assess_quality(
                frame, main["bbox"] if main is not None else None
            )
        else:
            payload["quality"] = []
        self.face_result.emit(payload)

    def _ensure_engine(self):
        if self._engine is None:
            from services.face_engine import FaceEngine

            self._engine = FaceEngine()
        return self._engine


def _explain_lost(source) -> str:
    """Kadr kelmay qo'ydi — sabab (`camera/manager.py:_explain_lost`)."""
    try:
        from proctoring.camera.manager import _explain_lost as explain

        return explain(source)
    except Exception:
        log.debug("Uzilish sababi aniqlanmadi", exc_info=True)
        return "Kameradan kadr kelmayapti. Qayta ulanish avtomatik davom etadi."


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
