"""
AI kuzatuv pipeline'i — barcha modullarni BITTA sikl ostida yig'adi.

    kamera -> [shaxs | obyekt | poza | nigoh] -> belgilar
           -> temporal -> fusion -> ball -> hodisa + dalil

MODULLAR HAR KADRDA ISHLAMAYDI. Har birining o'z chastotasi bor va u
IKKI manbadan keladi: siyosat (`policy.fps`) qancha SO'RAGANI va
apparat profili qancha KO'TARA OLGANI. Pastrog'i yutadi -
`PerformanceProfile.limit_fps` shuni qiladi. Sabab oddiy: shaxs
tekshiruvi ~40 ms, obyekt aniqlash ~60 ms, poza ~50 ms oladi. Ularni
har kadrda 30 FPS bilan chaqirish sekundiga 4.5 soniyalik ish
degani - sikl orqada qolib, kadrlar navbatda to'planardi.

BITTA THREAD, NAVBAT YO'Q. Barcha inference shu thread'da ketma-ket
bajariladi va kadrlar buferlanmaydi: har iteratsiyada kameradan ENG
OXIRGI kadr olinadi. Orqada qolgan pipeline eski kadrlarni qayta
ishlashi mumkin emas - proktorlikda "10 soniya oldingi telefon"
haqidagi ogohlantirish foydasiz.

TARMOQ BU YERDA YO'Q (`proctoring/__init__.py` dagi shartnoma).
Pipeline hodisa va dalil TAKLIF qiladi, ularni signal orqali
uzatadi; yuborishni chaqiruvchi hal qiladi. Shu tufayli butun AI
qismini tarmoqsiz sinash mumkin va u sessiya mantiqini bilmaydi.

ROLLAR BO'YICHA TAQSIMOT. Ikkita kamera bo'lsa ish bo'linadi:

    primary   (yuz)     -> shaxs, nigoh
    secondary (obyekt)  -> obyekt, poza

Bitta kamera bo'lsa hammasi unda ishlaydi va bu SEZILARLI sekinroq -
o'sha kadrga to'rtta model qo'llanadi. Chastotalar shuning uchun
profil bilan cheklangan.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from proctoring.behavior.behavior_analyzer import BehaviorAnalyzer, FrameFeatures
from proctoring.behavior.event_fusion import EventFusion
from proctoring.evidence import EvidenceRecorder, FrameRingBuffer
from proctoring.identity.face_identity import FaceIdentity
from proctoring.scoring.risk_engine import RiskEngine

log = logging.getLogger(__name__)

#: Sikl kutish oralig'i (soniya).
#:
#: Kameralar 15-30 FPS beradi, eng tez modul esa 5 FPS ishlaydi.
#: Siklni kamera tezligida aylantirish protsessorni bo'sh
#: tekshiruvlarga sarflardi; 25 ms esa eng tez modulni ham
#: kechiktirmaydi (5 FPS = 200 ms).
_TICK = 0.025

#: Modellar `models/` katalogida (`client/models/README.md`).
_YOLO_DIR = "yolo"
_POSE_DIR = "pose"


class _Rate:
    """
    Modulning chastota chegarasi.

    `fps=0` — modul O'CHIRILGAN va `due()` hech qachon `True`
    qaytarmaydi. Bu holatni alohida bayroq bilan saqlash ikkita
    haqiqat manbai yaratardi.
    """

    def __init__(self, fps: int) -> None:
        self._interval = 0.0 if fps <= 0 else 1.0 / float(fps)
        self._enabled = fps > 0
        # `None`, `0.0` EMAS: monotonik soat noldan boshlanishi
        # mumkin va o'shanda birinchi chaqiruv "hali erta" deb
        # o'tkazib yuborilardi - modul sessiya boshida bir interval
        # kechikardi.
        self._last: Optional[float] = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def due(self, now: float) -> bool:
        if not self._enabled:
            return False
        if self._last is not None and now - self._last < self._interval:
            return False
        self._last = now
        return True


class ProctoringPipeline(QThread):
    """
    Kuzatuv sikli.

    `QThread` merosxo'ri: og'ir inference UI thread'ida bo'lishi
    mumkin emas - u interfeysni har kadrda 100+ ms qotirardi.

    "Ishlayapti" bayrog'i `start_pipeline()` da, CHAQIRUVCHI
    thread'da qo'yiladi. `run()` ichida qo'yilsa, `start()` dan
    keyin darhol `stop()` chaqirilgan holatda endigina boshlangan
    `run()` bayroqni qaytarib qo'yar va thread abadiy ishlardi
    (`device_watch._ProcessScanner` bilan bir xil tuzoq).
    """

    #: `(tur, jiddiylik, payload)` — `SessionMonitor.push_event` shakli.
    event_ready = pyqtSignal(str, int, dict)
    #: `PendingEvidence` — yuborilishi kerak bo'lgan dalil.
    evidence_ready = pyqtSignal(object)
    #: `(ball, daraja)`.
    risk_changed = pyqtSignal(int, str)
    #: Modul ishga tushmadi: `(modul, sabab)`.
    module_failed = pyqtSignal(str, str)
    #: Diagnostika: kechikishlar, chastota, buferlar.
    stats_ready = pyqtSignal(dict)

    def __init__(self, manager, *, policy: dict, profile, models_root,
                 detection: Optional[dict] = None,
                 face_threshold: Optional[float] = None, parent=None) -> None:
        super().__init__(parent)
        self._manager = manager
        self._policy = policy or {}
        self._profile = profile
        self._models_root = models_root
        self._detection = detection or {}
        #: Yuz mosligining cosine chegarasi - IMTIHON PROFILIDAN
        #: (`face.min_score_exam` -> cosine). `None` bo'lsa zaxira
        #: qiymat ishlatiladi (`_face_threshold`).
        self._face_threshold_cos = face_threshold

        self._running = False
        self._reference = None

        self._analyzer = BehaviorAnalyzer(self._policy)
        self._fusion = EventFusion(
            int((self._policy.get("fusion") or {}).get("window_ms", 3000))
        )
        self._risk = RiskEngine(self._policy)

        # Har rol uchun ALOHIDA bufer va yozuvchi: hodisa qaysi
        # kamerada ko'rilgan bo'lsa, dalil ham o'shanikidan olinadi.
        # Bitta umumiy bufer ikki kamerani aralashtirib, "telefon
        # stolda" hodisasiga yuz kadrini biriktirardi.
        clip_seconds = float(
            (self._policy.get("evidence") or {}).get("clip_seconds", 5) or 5
        )
        self._buffers = {
            role: FrameRingBuffer(seconds=clip_seconds, capture_fps=6)
            for role in ("primary", "secondary")
        }
        self._recorders = {
            role: EvidenceRecorder(buffer, policy=self._policy)
            for role, buffer in self._buffers.items()
        }

        self._identity: Optional[FaceIdentity] = None
        self._gaze = None
        self._detector = None
        self._tracker = None
        self._pose = None

        #: Oxirgi shaxs natijasi: `(embedding, yuzlar_soni)`.
        #
        # SIGNAL EMAS, oddiy atribut: davriy tekshiruv uni daqiqada
        # bir marta o'qiydi, shaxs moduli esa sekundiga 5 marta
        # ishlaydi. Har natijani signal bilan uzatish UI thread'ini
        # hech kim kutmaydigan xabar bilan to'ldirardi. Yozish
        # atomik (bitta nom bog'lash), shuning uchun qulf kerak emas.
        self._last_identity: tuple = (None, 0)

        self._rates: dict = {}
        self._latency: dict = {}
        self._frames = 0
        self._last_stats = 0.0

    # ------------------------------------------------------------------
    # Boshqaruv
    # ------------------------------------------------------------------
    def set_reference(self, embedding) -> None:
        """
        Etalon yuz (FaceID bosqichidan).

        Pipeline ishga tushgandan KEYIN ham chaqirilishi mumkin:
        davriy tekshiruv etalonni yangilashi mumkin.
        """
        self._reference = embedding
        if self._identity is not None:
            self._identity.set_reference(embedding)

    def start_pipeline(self) -> None:
        if self.isRunning():
            return
        self._running = True
        self.start()

    def stop_pipeline(self, *, timeout_ms: int = 8000) -> None:
        """
        Siklni to'xtatadi va OCHIQ hodisalarni yopadi.

        Yopish MAJBURIY: "telefon ko'rindi" hodisasi ochiq qolsa,
        uning davomiyligi hech qachon yozilmasdi va bayonnomada
        "boshlandi, tugamadi" degan yozuv qolardi.
        """
        self._running = False
        if not self.wait(timeout_ms):
            log.warning("Kuzatuv sikli vaqtida to'xtamadi")
        self._flush_open_events()
        for recorder in self._recorders.values():
            recorder.clear()

    @property
    def identity_ready(self) -> bool:
        """
        Shaxs moduli HAQIQATDA ishlayaptimi.

        Model topilmasa yoki siyosat modulni o'chirsa, `latest_identity`
        abadiy `(None, 0)` qaytaradi. Buni "yuz yo'q" deb o'qish
        talabgorni bir necha daqiqada chetlashtirardi - holbuki sabab
        uning xulqida emas, mashinada. Nosozlikning o'zi allaqachon
        `proctoring_degraded` hodisasi bilan qayd etilgan.
        """
        return self._identity is not None

    @property
    def latest_identity(self) -> tuple:
        """
        Oxirgi yuz natijasi — davriy FaceID uchun.

        Pipeline ishlaganda kamerani U egallaydi va eski
        `CameraWorker` ochilmaydi (bitta qurilmani ikki jarayon
        ocholmaydi). Shuning uchun davriy tekshiruvning etaloni ham
        shu yerdan olinadi - aks holda u sessiya davomida umuman
        ishlamasdi.
        """
        return self._last_identity

    @property
    def risk_state(self):
        return self._risk.state()

    def set_server_risk(self, score: Optional[int]) -> None:
        """Serverdagi haqiqiy ball (heartbeat javobidan)."""
        self._risk.set_server_score(score)

    # ------------------------------------------------------------------
    def run(self) -> None:  # noqa: D401 - QThread kirish nuqtasi
        self._load_modules()
        log.info(
            "Kuzatuv boshlandi: profil=%s modullar=%s",
            getattr(self._profile, "name", "?"),
            ",".join(name for name, rate in self._rates.items() if rate.enabled) or "-",
        )
        try:
            while self._running:
                started = time.monotonic()
                try:
                    self._tick(started)
                except Exception:
                    # Bitta kadrdagi xato butun kuzatuvni to'xtatmasligi
                    # kerak: imtihon davom etadi va keyingi kadr
                    # ehtimol muvaffaqiyatli bo'ladi.
                    log.exception("Kuzatuv siklida xato")
                elapsed = time.monotonic() - started
                if elapsed < _TICK:
                    self.msleep(int((_TICK - elapsed) * 1000))
        finally:
            self._close_modules()

    # ------------------------------------------------------------------
    # Modellar
    # ------------------------------------------------------------------
    def _load_modules(self) -> None:
        """
        Modellarni yuklaydi. BLOKLOVCHI va shu thread'da.

        Har bir modul MUSTAQIL: biri yuklanmasa qolganlari
        ishlayveradi va sabab `module_failed` orqali yuqoriga
        chiqadi. Modelsiz o'rnatishda ham imtihon o'tishi kerak
        (`models/README.md`).
        """
        modules = self._policy.get("modules") or {}
        fps = self._policy.get("fps") or {}
        profile = self._profile

        self._rates = {
            name: _Rate(profile.limit_fps(key, int(fps.get(name, 0) or 0)))
            if modules.get(name)
            else _Rate(0)
            for name, key in (
                ("identity", "identity"),
                ("objects", "object"),
                ("pose", "pose"),
                ("gaze", "gaze"),
            )
        }

        # Har yuklash o'z `try` ida: DLL'ni antivirus to'sgan, model
        # fayli buzilgan yoki GPU drayveri yiqilgan bo'lsa istisno
        # `run()` dan chiqib, thread'ni SIKLSIZ tugatardi - kuzatuv
        # jimgina to'xtab, `proctoring_degraded` ham chiqmasdi.
        if self._rates["identity"].enabled or self._rates["gaze"].enabled:
            try:
                self._identity = FaceIdentity()
                if self._reference is not None:
                    self._identity.set_reference(self._reference)
                ready = self._identity.is_ready
            except Exception as exc:
                log.exception("Yuz modulini yuklashda xato")
                ready = False
                reason = "Yuz modeli yuklanmadi ({})".format(type(exc).__name__)
            else:
                reason = "Yuz modeli yuklanmadi"
            if not ready:
                self._disable("identity", reason)
                self._disable("gaze", reason)
                self._identity = None

        if self._rates["gaze"].enabled:
            try:
                from proctoring.gaze.gaze_estimator import GazeEstimator

                self._gaze = GazeEstimator()
            except Exception as exc:
                log.exception("Nigoh modulini yuklashda xato")
                self._gaze = None
                self._disable("gaze", "Nigoh moduli yuklanmadi ({})".format(type(exc).__name__))

        if self._rates["objects"].enabled:
            try:
                self._load_detector()
            except Exception as exc:
                log.exception("Obyekt aniqlash modulini yuklashda xato")
                self._detector = None
                self._tracker = None
                self._disable("objects", "Model yuklanmadi ({})".format(type(exc).__name__))

        if self._rates["pose"].enabled:
            try:
                self._load_pose()
            except Exception as exc:
                log.exception("Poza modulini yuklashda xato")
                self._pose = None
                self._disable("pose", "Model yuklanmadi ({})".format(type(exc).__name__))

    def _load_detector(self) -> None:
        from proctoring.detection.yolo_detector import YoloDetector
        from proctoring.tracking.bytetrack import ByteTrack

        path = self._model_path(
            _YOLO_DIR, "yolov8{}.onnx".format(self._profile.model_suffix)
        )
        detector = YoloDetector(
            path,
            self._profile,
            classes=self._detection.get("classes") or None,
            confidence=float(self._detection.get("confidence") or 0.5),
        )
        if not detector.load():
            self._disable("objects", detector.error)
            return

        self._detector = detector
        # Kuzatuv o'chirilgan bo'lsa ham tracker ISHLATILADI:
        # temporal qatlam `track_id` ga tayanadi va usiz ikkita
        # telefon bitta hodisaga qo'shilib ketardi. Siyosatdagi
        # `tracking` bayrog'i faqat izlarni hodisada KO'RSATISHNI
        # boshqaradi.
        self._tracker = ByteTrack()

    def _load_pose(self) -> None:
        from proctoring.pose.pose_estimator import PoseEstimator

        path = self._model_path(
            _POSE_DIR, "yolov8{}-pose.onnx".format(self._profile.model_suffix)
        )
        estimator = PoseEstimator(path, self._profile)
        if not estimator.load():
            self._disable("pose", estimator.error)
            return
        self._pose = estimator

    def _model_path(self, folder: str, name: str):
        from pathlib import Path

        return Path(self._models_root) / folder / name

    def _disable(self, module: str, reason: str) -> None:
        rate = self._rates.get(module)
        if rate is not None:
            self._rates[module] = _Rate(0)
        log.warning("Modul o'chirildi: %s — %s", module, reason)
        self.module_failed.emit(module, reason or "Noma'lum sabab")
        # "Obyekt aniqlanmadi" va "obyekt aniqlash ishlamadi"
        # bayonnomada AJRATILISHI shart, aks holda modelsiz mashina
        # "toza imtihon" bo'lib ko'rinardi.
        self.event_ready.emit(
            "proctoring_degraded", 2, {"module": module, "reason": (reason or "")[:200]}
        )

    def _close_modules(self) -> None:
        for module in (self._detector, self._pose):
            if module is not None:
                try:
                    module.close()
                except Exception:
                    log.debug("Modulni yopishda xato", exc_info=True)

    # ------------------------------------------------------------------
    # Sikl
    # ------------------------------------------------------------------
    def _tick(self, now: float) -> None:
        frames = self._grab_frames()
        if not frames:
            return

        self._frames += 1
        for role, frame in frames.items():
            self._buffers[role].push(frame, now=now)

        face_role, object_role = self._roles(frames)

        events: list = []
        if face_role:
            events.extend(self._analyse_face(frames[face_role], face_role, now))
        if object_role:
            events.extend(self._analyse_objects(frames[object_role], object_role, now))

        for event in events:
            self._emit_event(event, now)

        for fused in self._fusion.evaluate(now=now):
            self._emit_fused(fused, now)

        self._maybe_stats(now)

    def _grab_frames(self) -> dict:
        """
        Har roldan ENG OXIRGI kadr.

        Eski kadrlar ATAYLAB tashlanadi: pipeline orqada qolsa,
        navbatni qayta ishlash kechikishni faqat oshirardi va
        ogohlantirish hodisadan o'nlab soniya keyin chiqardi.
        """
        frames = {}
        for role in ("primary", "secondary"):
            frame, _timestamp = self._manager.latest_frame(role) or (None, 0.0)
            if frame is not None:
                frames[role] = frame
        return frames

    @staticmethod
    def _roles(frames: dict) -> tuple:
        """
        Qaysi kadr qaysi ish uchun.

        Ikkinchi kamera yo'q bo'lsa hammasi birinchisiga tushadi -
        bu sekinroq, lekin kuzatuvsiz qolishdan yaxshiroq.
        """
        primary = "primary" if "primary" in frames else None
        secondary = "secondary" if "secondary" in frames else None
        if primary is None:
            # Faqat ikkilamchi kamera ishlayapti: yuz tekshiruvi
            # unda ishonchsiz (u odatda yon tomondan qaraydi),
            # lekin obyekt aniqlash to'liq ishlaydi.
            return None, secondary
        return primary, secondary or primary

    # ------------------------------------------------------------------
    def _analyse_face(self, frame, role: str, now: float) -> list:
        identity = None
        gaze = None

        if self._identity is not None and self._rates["identity"].due(now):
            identity = self._timed("identity", self._identity.analyse, frame)
            primary = identity.primary if identity is not None else None
            self._last_identity = (
                primary.embedding if primary is not None else None,
                identity.count if identity is not None else 0,
            )

        if (
            self._gaze is not None
            and identity is not None
            and identity.primary is not None
            and identity.primary.landmarks is not None
            and self._rates["gaze"].due(now)
        ):
            gaze = self._timed(
                "gaze", self._gaze.estimate, identity.primary.landmarks, frame.shape
            )

        if identity is None and gaze is None:
            return []

        height, width = frame.shape[:2]
        return self._analyzer.analyse(
            FrameFeatures(
                timestamp=now,
                camera_role=role,
                frame_width=width,
                frame_height=height,
                identity=identity,
                gaze=gaze,
                face_threshold=self._face_threshold(),
            )
        )

    def _analyse_objects(self, frame, role: str, now: float) -> list:
        tracks = None
        poses = None

        if self._detector is not None and self._rates["objects"].due(now):
            detections = self._timed("objects", self._detector.detect, frame) or []
            tracks = self._tracker.update([item.as_dict() for item in detections])

        if self._pose is not None and self._rates["pose"].due(now):
            poses = self._timed("pose", self._pose.estimate, frame) or []

        if tracks is None and poses is None:
            return []

        height, width = frame.shape[:2]
        return self._analyzer.analyse(
            FrameFeatures(
                timestamp=now,
                camera_role=role,
                frame_width=width,
                frame_height=height,
                tracks=tracks,
                poses=poses,
            )
        )

    def _face_threshold(self) -> float:
        """
        Yuz mosligining chegarasi (cosine).

        Qiymat SERVERDAN keladi: `Setting.faceid_min_score_exam`
        (0..100) supervisor'da cosine'ga o'giriladi. Ilgari bu yerda
        `FACE_MATCH_THRESHOLD` qadab qo'yilgan edi va u imtihon
        profilidagi chegara bilan jimgina ziddiyatda bo'lishi mumkin
        edi: server 85 bilan rad etardi, AI qatlami esa 71 da hech
        narsa ko'rmasdi.
        """
        if self._face_threshold_cos is None:
            from config import FACE_MATCH_THRESHOLD

            return float(FACE_MATCH_THRESHOLD)
        return float(self._face_threshold_cos)

    def _timed(self, module: str, func, *args):
        """Modulni chaqiradi va kechikishini yozadi (diagnostika)."""
        started = time.monotonic()
        try:
            return func(*args)
        finally:
            self._latency[module] = round((time.monotonic() - started) * 1000, 1)

    # ------------------------------------------------------------------
    # Chiqish
    # ------------------------------------------------------------------
    def _emit_event(self, event, now: float) -> None:
        payload = event.as_payload()
        if event.camera_role:
            payload.setdefault("camera_role", event.camera_role)

        self.event_ready.emit(event.type, int(event.severity), payload)
        self._fusion.feed(event, now=now)
        self._bump_risk(event.type, now)
        self._capture_evidence(event, now)

    def _emit_fused(self, fused, now: float) -> None:
        """
        Birlashtirilgan xulosa - ALOHIDA hodisa.

        U tarkibiy hodisalarni ALMASHTIRMAYDI: ular allaqachon
        yuborilgan va dalil zanjirida qolishi kerak. Fusion faqat
        "bularning yig'indisi bundan ham jiddiy" deydi.
        """
        self.event_ready.emit(fused.type, int(fused.severity), fused.as_payload())
        self._bump_risk(fused.type, now)

    def _bump_risk(self, event_type: str, now: float) -> None:
        state = self._risk.add(event_type, now=now)
        self.risk_changed.emit(int(state.display), state.level)

    def _capture_evidence(self, event, now: float) -> None:
        role = event.camera_role or "primary"
        recorder = self._recorders.get(role) or self._recorders["primary"]
        # Hodisa BOSHLANGAN payt: klip oynasi shundan orqaga
        # olinadi. Tasdiqlangan paytdan boshlansa, eng qimmatli
        # harakat (telefonni chiqarish) klipdan tashqarida qolardi.
        started_at = now - (int(event.duration_ms or 0) / 1000.0)
        for item in recorder.capture(event, started_at=started_at, now=now):
            self.evidence_ready.emit(item)

    def _flush_open_events(self) -> None:
        for event in self._analyzer.finish():
            if event is None:
                continue
            self.event_ready.emit(
                event.type, int(event.severity), event.as_payload()
            )

    def _maybe_stats(self, now: float) -> None:
        if now - self._last_stats < 10.0:
            return
        self._last_stats = now
        self.stats_ready.emit(
            {
                "frames": self._frames,
                "latency_ms": dict(self._latency),
                "buffers": {
                    role: round(buffer.memory_mb, 1)
                    for role, buffer in self._buffers.items()
                },
                "pending_evidence": sum(
                    len(recorder.pending) for recorder in self._recorders.values()
                ),
                "dropped_evidence": sum(
                    recorder.dropped for recorder in self._recorders.values()
                ),
                "risk": self._risk.state(now=now).display,
            }
        )

    # ------------------------------------------------------------------
    def evidence_sent(self, item) -> None:
        """Dalil yuborildi — vaqtinchalik fayl o'chiriladi."""
        for recorder in self._recorders.values():
            if item in recorder.pending:
                recorder.done(item)
                return

    def evidence_failed(self, item) -> None:
        """Yuborilmadi — navbatda qoladi va keyin qayta uriniladi."""
        role = item.camera_role or "primary"
        recorder = self._recorders.get(role) or self._recorders["primary"]
        recorder.requeue(item)
