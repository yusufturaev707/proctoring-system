"""
AI kuzatuvni imtihon sessiyasiga ULAYDIGAN qatlam.

CHEGARA. `proctoring/` paketi tarmoqni ham, sessiyani ham bilmaydi
(`proctoring/__init__.py` dagi shartnoma): u kadrdan xulosa
chiqaradi va hodisa TAKLIF qiladi. Sessiya, tokenlar va yuklash esa
`services/` da. Bu ikkisi bir joyda yashasa, AI qismini tarmoqsiz
sinash imkonsiz bo'lardi va har bir model o'zgarishi sessiya
mantiqiga tegib ketardi.

Supervisor aynan shu ikkisi orasidagi ko'prik:

    CameraManager -> ProctoringPipeline -> [hodisa]  -> SessionMonitor
                                        -> [dalil]   -> evidence/upload/

APPARAT PROFILI SHU YERDA TANLANADI, pipeline'da emas. Sabab: profil
serverga ham yuboriladi (`proctoring/start/` dagi `ai_profile`) va u
sessiya ma'lumoti - qaysi mashinada qanday chegaralar bilan
kuzatilgani bayonnomada qolishi kerak.

TO'XTATISH TARTIBI MUHIM: avval pipeline, keyin kameralar. Teskarisida
sikl yopilgan oqimdan kadr so'rab, har iteratsiyada xato yozardi.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from core.bundle_paths import resource_root
from services import local_archive, net_policy
from services.workers import ApiWorker, WorkerHolder

log = logging.getLogger(__name__)

#: Bir vaqtda yuborilayotgan dalillar soni.
#:
#: Har dalil alohida HTTP so'rov va ular multipart bilan ketadi.
#: Chegarasiz bir nechta klip (har biri ~2 MB) bir vaqtda tarmoqni
#: egallab, hodisa flush'ini va heartbeat'ni kechiktirardi - ya'ni
#: dalil sessiyaning o'zini "yo'qolgan" qilib ko'rsatardi.
_MAX_PARALLEL_UPLOADS = 2

#: Yuborilmagan dalil KADRLARI qayta urinish navbati (RAM'da, ~150 KB
#: dan). To'lsa eng eskisi tushadi — u mahalliy arxivda baribir bor.
_MAX_RETRY_ITEMS = 20

#: Dalil yuklash xatosidan keyingi kutish (soniya): 15 -> 30 ... 300,
#: jitter bilan. Ilgari qayta urinish umuman yo'q edi (kadr faqat
#: yozuvchi navbatida qolib ketardi).
_RETRY_BASE_S = 15.0
_RETRY_CAP_S = 300.0


class ProctoringSupervisor(QObject):
    """
    Kuzatuv sessiyasini boshqaradi.

    Sahifa faqat `start()` va `stop()` ni biladi; qolgan hammasi shu
    yerda. Shu tufayli AI qismini butunlay o'chirish (siyosatda
    `enabled=false`) sahifaga hech qanday shart qo'shmaydi.
    """

    #: `(tur, jiddiylik, payload)` — sessiya buferiga.
    event_ready = pyqtSignal(str, int, dict)
    #: `(ball, daraja)` — ekrandagi nishon uchun.
    risk_changed = pyqtSignal(int, str)
    #: Kuzatuv holati o'zgardi (modul o'chdi, kamera yo'qoldi).
    status_changed = pyqtSignal(str)

    def __init__(self, repo, parent=None) -> None:
        super().__init__(parent)
        self._repo = repo
        self._workers = WorkerHolder()
        self._manager = None
        self._pipeline = None
        self._profile = None
        self._queue: list = []
        #: Dalil yig'ish oynasi ochiqmi (`set_capture_enabled`).
        self._capture_enabled = True
        #: Sessiyaning `public_id` si - klip qaydi token bekor
        #: bo'lgandan keyin ham to'g'ri sessiyaga tushishi uchun.
        self._session_id = ""
        self._inflight = 0
        self._active = False
        #: Kamera rollarining oxirgi holati — "tiklandi" hodisasini
        #: faqat HAQIQIY uzilishdan keyin chiqarish uchun.
        self._camera_state: dict = {}
        #: Tarmoq xatosi bilan qaytgan kadrlar — backoff'dan keyin navbatga.
        self._retry_items: list = []
        self._retry_backoff = net_policy.Backoff(base=_RETRY_BASE_S, cap=_RETRY_CAP_S)
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._on_retry_timer)

    # ------------------------------------------------------------------
    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def profile_name(self) -> str:
        """Tanlangan apparat profili — serverga yuboriladi."""
        return getattr(self._profile, "name", "")

    def detect_profile(self, *, override: str = ""):
        """
        Apparatni aniqlaydi va profil tanlaydi.

        `proctoring/start/` dan OLDIN chaqiriladi: profil nomi
        sessiyaga yoziladi. Aniqlash sekin (ONNX Runtime provayderlar
        ro'yxatini o'qiydi), lekin u SESSIYA BOSHIDA bir marta
        bo'ladi.
        """
        from proctoring.hardware.gpu_detector import hardware_probe
        from proctoring.hardware.performance_profile import select_profile

        # Aniqlash dastur ishga tushganda boshlangan va odatda
        # allaqachon tayyor. Bu yerda kutish MUMKIN (sessiya
        # boshlanmoqda, operator baribir kutmoqda) - lekin cheklangan:
        # `nvidia-smi` osilib qolsa imtihon boshlanishi to'xtab
        # qolmasligi kerak, apparatsiz esa eng past profil tanlanadi.
        info = hardware_probe.resolve(timeout=5.0)
        self._profile = select_profile(info, override=override or "")
        log.info(
            "Apparat profili: %s (%s)", self._profile.name, info.gpu_name or "CPU"
        )
        return self._profile

    # ------------------------------------------------------------------
    def start(self, *, config: dict, layout, before_open=None,
              session_id: str = "") -> bool:
        """
        Kuzatuvni ishga tushiradi.

        `False` — kuzatuv YOQILMAGAN yoki ishlaydigan kamera yo'q.
        Bu XATO EMAS: siyosat AI ni o'chirgan bo'lishi mumkin va
        imtihon baribir davom etadi. Kamera talab qilingan holatni
        server allaqachon `proctoring/start/` da rad etgan.

        `before_open` — kameralar OCHILISHIDAN oldin chaqiriladigan
        funksiya. U bitta aniq ish uchun: FaceID sahifasidan kelgan
        `CameraWorker` ni bo'shatish. Windows'da bitta qurilmani ikki
        jarayon ocholmaydi va tartib teskari bo'lsa, kuzatuv oqimi
        "kamera band" xatosiga tushib, qayta ulanish kutishida bir
        necha soniya yo'qotardi — imtihonning eng boshida.

        Chaqiruvchi uni O'ZI bo'shata olmaydi: siyosat AI ni
        o'chirgan bo'lsa kamera FaceID ishchisida QOLISHI kerak
        (davriy tekshiruv uni ishlatadi), va buni faqat shu metod
        biladi.
        """
        # Yangi sessiya - yangi dalil oynasi. Oldingi talabgorda
        # vaqt tugab yopilgan bo'lishi mumkin va u holat keyingisiga
        # o'tib ketmasligi kerak.
        self._capture_enabled = True
        self._session_id = session_id or ""

        policy = (config or {}).get("proctoring") or {}
        if not policy.get("enabled"):
            # QAYERDA yoqilishi ham yoziladi: YOLO kaliti imtihon
            # profilida (`Setting`), bosh kalit esa boshqa bo'limda
            # (`ProctoringPolicy`) va faqat birinchisini yoqib, AI
            # "ishlamayapti" deb qidirish oson - aynan shunday bo'lgan.
            log.info(
                "AI kuzatuv o'chirilgan: imtihon profilida kuzatuv siyosati "
                "yo'q yoki yoqilmagan (panel: «AI kuzatuv -> Kuzatuv siyosati»). "
                "YOLO, nigoh va kamera kliplari ishlamaydi"
            )
            return False

        usable = list(getattr(layout, "usable", []) or [])
        if not usable:
            log.warning("Ishlaydigan kamera yo'q — AI kuzatuv boshlanmadi")
            return False

        if self._profile is None:
            self.detect_profile(override=policy.get("gpu_profile") or "")

        if before_open is not None:
            before_open()
        self._start_cameras(layout, usable)
        self._start_pipeline(config, policy)
        self._active = True
        return True

    def _start_cameras(self, layout, usable: list) -> None:
        from proctoring.camera import CameraManager

        self._manager = CameraManager(self)
        self._manager.configure(
            layout.as_slots(),
            # IP kamera kredensiali SHU YERDA so'raladi va hech
            # qayerda saqlanmaydi: manager uni oqim ochilayotganda
            # chaqiradi va natijani tashlab yuboradi.
            stream_url_provider=self._repo.camera_stream,
        )
        # Ulanish `start()` dan OLDIN: birinchi holat o'zgarishi
        # (ochilish muvaffaqiyatsizligi ham) hodisa oqimiga tushishi
        # kerak, aks holda sessiya boshidagi nosozlik ko'rinmasdi.
        self._manager.state_changed.connect(self._on_camera_state)
        # `preview_fps` UI uchun emas: bu yerda hech kim kadrni
        # ko'rmaydi. Kamera oqimining o'z tezligi qoladi va pipeline
        # undan kerakligicha oladi.
        self._manager.start([camera.role for camera in usable], preview_fps=15)

    def _start_pipeline(self, config: dict, policy: dict) -> None:
        from proctoring.pipeline import ProctoringPipeline
        from services.face_engine import score_to_cosine

        # YUZ CHEGARASI IMTIHON PROFILIDAN, AI siyosatidan EMAS.
        # `ProctoringPolicy` da bunday qiymat yo'q va bo'lmasligi ham
        # kerak: chegara `Setting.faceid_min_score_exam` da va server
        # davriy tekshiruvda aynan o'shani qo'llaydi. Ikki joyda ikki
        # qiymat bo'lsa, AI qatlami "mos kelmadi" hodisasini serverdan
        # boshqa chegarada chiqarardi.
        face_config = (config or {}).get("face") or {}
        self._pipeline = ProctoringPipeline(
            self._manager,
            policy=policy,
            profile=self._profile,
            models_root=resource_root() / "models",
            detection=config.get("detection") or {},
            face_threshold=score_to_cosine(face_config.get("min_score_exam")),
            parent=self,
        )
        self._pipeline.event_ready.connect(self.event_ready)
        self._pipeline.risk_changed.connect(self.risk_changed)
        self._pipeline.evidence_ready.connect(self._enqueue_evidence)
        self._pipeline.module_failed.connect(self._on_module_failed)
        self._pipeline.stats_ready.connect(self._on_stats)
        self._pipeline.start_pipeline()

    def set_reference(self, embedding) -> None:
        """FaceID bosqichidagi etalon — shaxs moduliga."""
        if self._pipeline is not None:
            self._pipeline.set_reference(embedding)

    @property
    def identity_ready(self) -> bool:
        """Shaxs moduli ishlayaptimi (model yuklangan va yoqilgan)."""
        if self._pipeline is None:
            return False
        return bool(self._pipeline.identity_ready)

    @property
    def latest_identity(self) -> tuple:
        """Oxirgi yuz natijasi: `(embedding, yuzlar_soni)`."""
        if self._pipeline is None:
            return (None, 0)
        return self._pipeline.latest_identity

    def latest_frame(self, role: str = "primary"):
        """
        Oxirgi kadr - davriy FaceID ning dalil rasmi uchun.

        Kuzatuv ishlayotganda kamera SHU YERDA (bitta qurilmani ikki
        jarayon ocholmaydi), ya'ni sahifa kadrni boshqa yo'l bilan
        ololmaydi.

        Rol topilmasa ikkinchisiga o'tiladi: bitta kamerali
        mashinada u `primary` bo'lishi shart emas (`roles.py`
        zaxira qoidasi faqat IP kamera bo'lgan holatni ham
        qamraydi).
        """
        if self._manager is None:
            return None
        for candidate in (role, "primary", "secondary"):
            frame, _timestamp = self._manager.latest_frame(candidate) or (None, 0.0)
            if frame is not None:
                return frame
        return None

    def camera_slots(self, max_age_s: float) -> list:
        """
        Ochiq kameralar va ularning YANGI kadri - skrinshot ramkasi uchun.

        `latest_frame` dan farqi: rol ALMASHTIRILMAYDI. U yerda savol
        "istalgan kadr bormi?", bu yerda esa "qaysi burchakka nima
        chiziladi?" - yuz kamerasining kadri xona kamerasi burchagiga
        tushib qolmasligi kerak.

        Kamera ochiq, lekin kadr `max_age_s` dan eski bo'lsa - `None`
        (ramka "kadr yo'q" bilan chiziladi). Kadr NUSXALANMAYDI:
        oqim har `read()` da yangi massiv yozadi (`CameraStream`).
        """
        if self._manager is None:
            return []
        now = time.monotonic()
        slots = []
        for role in ("primary", "secondary"):
            stream = self._manager.stream(role)
            if stream is None:
                continue
            frame, taken_at = stream.latest_frame()
            fresh = frame is not None and now - taken_at <= max_age_s
            slots.append((role, frame if fresh else None))
        return slots

    def set_server_risk(self, score: Optional[int]) -> None:
        if self._pipeline is not None:
            self._pipeline.set_server_risk(score)

    # ------------------------------------------------------------------
    def stop(self) -> None:
        """
        To'xtatadi: AVVAL pipeline, KEYIN kameralar.

        Teskarisida sikl yopilgan oqimdan kadr so'rab, har
        iteratsiyada xato yozardi va to'xtash o'nlab soniyaga
        cho'zilardi.
        """
        self._active = False
        if self._pipeline is not None:
            self._pipeline.stop_pipeline()
            self._pipeline = None
        if self._manager is not None:
            self._manager.shutdown()
            self._manager = None
        # Yuborilmagan dalillar TASHLANADI: sessiya tugadi va ularni
        # bog'laydigan hodisa allaqachon yozilgan. Ularni ushlab
        # turish dasturning yopilishini kechiktirardi.
        self._queue.clear()
        self._retry_timer.stop()
        self._retry_items.clear()
        self._retry_backoff.success()
        self._workers.wait_all(4_000)

    # ------------------------------------------------------------------
    # Dalil yuklash
    # ------------------------------------------------------------------
    def set_capture_enabled(self, enabled: bool) -> None:
        """
        Dalil YIG'ISHNI yoqadi/o'chiradi (kuzatuvni emas).

        Testga ajratilgan vaqt tugaganda chaqiriladi: talabgor
        javoblarini topshirgan, ekranda platformaning yakuniy
        sahifasi turibdi va undan klip yig'ishning ma'nosi yo'q -
        disk esa o'sib boraveradi. Hodisalar, FaceID va risk
        bahosi AVVALGIDEK ishlaydi: sessiya hali ochiq va proktor
        uni ko'rib turishi kerak.
        """
        self._capture_enabled = bool(enabled)

    def _enqueue_evidence(self, item) -> None:
        if not self._capture_enabled:
            # Oyna yopilgan: dalil qabul qilinmaydi, lekin
            # vaqtinchalik fayl TOZALANADI - aks holda u diskda
            # qolib ketardi.
            self._release(item)
            return
        self._queue.append(item)
        self._pump()

    def _pump(self) -> None:
        """
        Navbatni bo'shatadi. KADR va KLIP ikki xil yo'ldan ketadi.

        KADR (~150 KB) serverga YUKLANADI: u proktor ekranida
        hodisa yonida turadi va unga imtihon DAVOMIDA kerak.

        KLIP (~1-3 MB, hodisa sayin) mashinada QOLADI va serverga
        faqat uning manzili boradi. Sabab ko'lamda: 500 mashinali
        bino kuniga ~5 GB klip yig'adi va uni yuklash kanalni ham,
        server diskini ham yeb qo'yadi - holbuki klip real vaqtda
        deyarli hech qachon ko'rilmaydi, u apellyatsiya hujjati.
        Proktorga kerak bo'lgan "hozir nima bo'ldi?" degan javobni
        KADR beradi.
        """
        while self._queue and self._inflight < _MAX_PARALLEL_UPLOADS:
            item = self._queue.pop(0)
            data = self._payload_of(item)
            if not data:
                # Fayl o'qilmadi yoki bo'sh - qayta urinishning
                # ma'nosi yo'q, u faqat navbatni bloklardi.
                self._release(item)
                continue

            if item.kind == "clip":
                self._keep_clip(item, data)
                continue

            # MAHALLIY ARXIV: nusxa YUBORISHDAN OLDIN yoziladi -
            # tarmoq uzilsa yoki dastur yopilsa ham dalil
            # mashinada qoladi.
            local_archive.save_frame(data, extension="jpg", prefix="evidence")

            self._inflight += 1
            worker = ApiWorker(
                self._repo.upload_evidence,
                kind=item.kind,
                data=data,
                captured_at=item.captured_at,
                event_type=item.event_type,
                camera_role=item.camera_role,
                confidence=item.confidence,
                duration_ms=item.duration_ms,
                boxes=item.boxes,
                parent=self,
            )
            worker.succeeded.connect(
                lambda _result, evidence=item: self._on_uploaded(evidence)
            )
            worker.failed_error.connect(
                lambda exc, evidence=item: self._on_upload_failed(evidence, exc)
            )
            self._workers.run(worker)

    def _keep_clip(self, item, data: bytes) -> None:
        """
        Klipni mashinada qoldiradi va serverga MANZILINI yuboradi.

        Tartib muhim: avval fayl, keyin qayd. Teskarisida panelda
        mavjud bo'lmagan faylga ishora qiluvchi yozuv paydo
        bo'lardi - `evidence.py` dagi "avval fayl, keyin qator"
        qoidasining o'zi.

        YOZIB BO'LMASA QAYD HAM QILINMAYDI: manzilsiz yozuv
        proktorni yo'q faylni qidirishga yuborardi. Bu holatda
        hodisaning o'zi baribir yozilgan - dalil klipi
        qo'shimcha, hodisaning sharti emas.
        """
        path = local_archive.save_frame(data, extension="mp4", prefix="clip")
        if not path:
            log.warning("Klipni arxivga yozib bo'lmadi - qayd etilmaydi")
            self._release(item)
            return

        self._inflight += 1
        worker = ApiWorker(
            self._repo.register_recording,
            kind="clip",
            local_path=path,
            captured_at=item.captured_at,
            size_bytes=len(data),
            duration_ms=item.duration_ms,
            event_type=item.event_type,
            camera_role=item.camera_role,
            confidence=item.confidence,
            # Klip chetlashtirishdan KEYIN ham yetib kelishi mumkin
            # (navbatda turgan edi) - token o'shanda bekor bo'ladi.
            session_id=self._session_id,
            parent=self,
        )
        worker.succeeded.connect(
            lambda _result, evidence=item: self._finish(evidence, sent=True)
        )
        # QAYTA URINILMAYDI. Fayl allaqachon mashinada va u
        # yo'qolmaydi; qayd esa qulaylik - proktor uni topishi
        # uchun. Navbatni shu sabab bilan ushlab turish esa
        # keyingi dalillarni kechiktirardi.
        worker.failed.connect(
            lambda message, code, evidence=item: self._on_register_failed(
                evidence, message, code
            )
        )
        self._workers.run(worker)

    def _on_register_failed(self, item, message: str, code: str) -> None:
        log.warning(
            "Klip qayd etilmadi (%s): %s - fayl mashinada qoldi", code or "-", message
        )
        self._finish(item, sent=True)

    @staticmethod
    def _payload_of(item) -> bytes:
        """Kadr RAM'da, klip vaqtinchalik faylda."""
        if item.data:
            return item.data
        if not item.path:
            return b""
        try:
            with open(item.path, "rb") as handle:
                return handle.read()
        except OSError:
            log.warning("Dalil faylini o'qib bo'lmadi: %s", item.path)
            return b""

    def _release(self, item) -> None:
        """Dalil bilan ish tugadi — vaqtinchalik fayl o'chiriladi."""
        if self._pipeline is not None:
            self._pipeline.evidence_sent(item)

    def _finish(self, item, *, sent: bool) -> None:
        self._inflight = max(0, self._inflight - 1)
        if self._pipeline is not None:
            if sent:
                self._pipeline.evidence_sent(item)
            else:
                self._pipeline.evidence_failed(item)
        self._pump()

    def _on_uploaded(self, item) -> None:
        self._retry_backoff.success()
        self._finish(item, sent=True)

    def _on_upload_failed(self, item, exc) -> None:
        code = getattr(exc, "code", "") or ""
        status = int(getattr(exc, "status", 0) or 0)
        message = getattr(exc, "message", "") or str(exc)
        if code in ("session_not_found", "session_forbidden") or not self._active:
            # Sessiya yopilgan — qayta urinishning ma'nosi yo'q; kadr
            # mahalliy arxivda bor.
            log.warning("Dalil yuborilmadi (%s) - sessiya yopilgan", code or "-")
            self._finish(item, sent=True)
            return
        if net_policy.is_poison_payload(status):
            # Server kadrni o'zini rad etdi — takror ham shunday tugaydi.
            log.error("Dalil server tomonidan rad etildi (%s %s) - tashlandi", status, code or "-")
            self._finish(item, sent=True)
            return
        # QAYTA URINISH BACKOFF BILAN: darhol takrorlash uzilgan
        # tarmoqda cheksiz sikl bo'lardi, qat'iy oraliq esa butun
        # binoni bir ritmda serverga urardi.
        delay = self._retry_backoff.failure(getattr(exc, "retry_after", None))
        log.warning(
            "Dalil yuborilmadi (%s): %s - %.0f s dan keyin qayta", code or "-", message, delay
        )
        if item not in self._retry_items:
            self._retry_items.append(item)
            while len(self._retry_items) > _MAX_RETRY_ITEMS:
                self._retry_items.pop(0)
        if not self._retry_timer.isActive():
            self._retry_timer.start(int(delay * 1000))
        # `sent=False`: yozuvchi faylni ushlab turadi (qayta yasab bo'lmaydi).
        self._finish(item, sent=False)

    def _on_retry_timer(self) -> None:
        if not self._active or not self._retry_items:
            return
        items, self._retry_items = self._retry_items, []
        for item in items:
            if item not in self._queue:
                self._queue.append(item)
        self._pump()

    # ------------------------------------------------------------------
    def _on_module_failed(self, module: str, reason: str) -> None:
        self.status_changed.emit("{}: {}".format(module, reason))

    def _on_camera_state(self, role: str, state: str) -> None:
        """
        Kamera holati — HODISA.

        Kuzatuvning nosozligi bayonnomada bo'shliq qoldiradi va uni
        "hech narsa bo'lmagan" deb o'qish mumkin. Shuning uchun
        yo'qolish ham, tiklanish ham yoziladi.
        """
        previous = self._camera_state.get(role, "")
        self._camera_state[role] = state

        if state == "failed":
            self.event_ready.emit("camera_lost", 3, {"camera_role": role})
        elif state in ("degraded", "reconnecting"):
            self.event_ready.emit(
                "camera_degraded", 2, {"camera_role": role, "reason": state}
            )
        elif state == "online" and previous in ("failed", "reconnecting", "degraded"):
            # Faqat HAQIQIY uzilishdan keyin. Sessiya boshidagi
            # birinchi ochilish ham "tiklandi" bo'lib chiqsa,
            # bayonnomada hech qachon bo'lmagan uzilish paydo
            # bo'lardi.
            self.event_ready.emit("camera_reconnected", 1, {"camera_role": role})

    def _on_stats(self, stats: dict) -> None:
        log.debug("Kuzatuv holati: %s", stats)
