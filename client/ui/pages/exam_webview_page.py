"""
5-SAHIFA - Xavfsiz WebView.

Tashqi test platformasi shu yerda ochiladi. Uchta qatlam bir vaqtda
ishlaydi:

  1. QULF   - domen allowlist, yangi oyna/yuklab olish/kontekst menyu
              taqiqi, off-the-record profil (kesh va cookie diskka
              yozilmaydi va keyingi talabgorga o'tmaydi).
  2. NAZORAT- heartbeat, hodisalar buferi, davriy FaceID.
  3. YAKUN  - sessiyani tugatish va keyingi talabgorga qaytish.

HAVOLANI SERVER BERADI. Client tashqi platformaga o'zi murojaat
qilmaydi va uning kredensialini bilmaydi: JSHSHIR tekshiruvida
backend platformadan `test_link` ni oladi, uni sessiyaga
shifrlab yozadi va `exam/access/` da tayyor holda qaytaradi
(`integrations/exam_site.py`). Bu yerda qoladigan ish bitta -
o'sha havolani ochish.

Token havolaning ICHIDA va uni platformaning o'zi shunday
beradi. URL brauzer tarixida qolishi xavfi o'z kuchida, lekin
uni kamaytirish endi platforma tomonida (havola bir martalik
bo'lishi kerak); biz tomondan himoya - `off_the_record` profil,
ya'ni tarix va cookie diskka umuman yozilmaydi.
"""

from __future__ import annotations

import logging
import time
from typing import Optional
from urllib.parse import urlparse

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
    QWebEngineUrlRequestInterceptor,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from config import CAMERA_FRAME_MAX_AGE_S, FACE_MATCH_THRESHOLD
from services import local_archive, runtime_settings
from services.app_state import AppState
from services.camera_worker import CameraWorker, encode_jpeg, retire_camera
from services.face_engine import FaceEngine, similarity_score
from services.device_watch import DeviceWatcher
from services.lockdown import lockdown
from services.monitoring import SessionMonitor
from services.proctoring_supervisor import ProctoringSupervisor
from services.realtime import ProctorChannel
from services.repositories import ProctoringRepository
from services.screen_capture import ScreenshotService
from services.screen_recorder import ScreenRecorder
from services.workers import ApiWorker, WorkerHolder
from ui.dialogs.finish_dialog import FinishDialog
from ui.widgets.icons import GlyphButton, StatusDot
from ui.widgets.indicators import BusyOverlay, Snackbar

log = logging.getLogger(__name__)

#: Suzuvchi panelning ekran chetidan masofasi (px).
#:
#: Kichik: panel platformaning kontentini imkon qadar kam yopishi
#: kerak, lekin chetga yopishib qolgan tugmani bosish ham qiyin.
_BAR_MARGIN = 18

#: Dasturdan chiqishda sessiyani yakunlash so'rovlarining timeout'i (s).
#: Umumiy `API_TIMEOUT` (30 s) bu yerda juda uzun: oyna allaqachon
#: yashirilgan va operator dastur yopilishini kutyapti. Server javob
#: bermasa sessiyani `close_stale_sessions` baribir yopadi.
_EXIT_REQUEST_TIMEOUT_S = 4.0


class DomainAllowlistInterceptor(QWebEngineUrlRequestInterceptor):
    """
    Faqat ruxsat etilgan domenlarga so'rov qo'yadi.

    Ro'yxat backenddan keladi va u `Exam.site_url` domenidan
    hisoblanadi (`Exam.get_allowed_domains`) - ya'ni administrator
    manzilni o'zgartirsa, allowlist o'zi ergashadi va client
    build'ini yangilash shart emas. Ilgari domenlar alohida
    ro'yxatda ham saqlanardi; u `site_url` bilan birga
    yangilanmasa, imtihon oq ekranda ochilardi.

    Ro'yxat bo'sh bo'lsa hech narsa bloklanmaydi - bu holat
    backendda ham "tekshiruv o'chirilgan" degani.
    """

    def __init__(self, allowed: list, on_blocked=None) -> None:
        super().__init__()
        self._allowed = [domain.lower().strip() for domain in allowed if domain]
        self._on_blocked = on_blocked

    def interceptRequest(self, info) -> None:
        if not self._allowed:
            return
        host = (info.requestUrl().host() or "").lower()
        if not host:
            # `data:`, `blob:`, `about:` - host yo'q. Ular sahifaning o'z
            # ichki resurslari, tashqi manzil emas.
            return
        for domain in self._allowed:
            if host == domain or host.endswith("." + domain):
                return
        info.block(True)
        if self._on_blocked is not None:
            self._on_blocked(host)


class LockedWebPage(QWebEnginePage):
    """Yangi oyna ochmaydigan, dialoglarni rad etadigan sahifa."""

    def __init__(self, profile: QWebEngineProfile, parent=None) -> None:
        super().__init__(profile, parent)

    def createWindow(self, _type):
        # `target="_blank"` va `window.open` - yangi oyna proktorlik
        # nazoratidan tashqarida bo'lardi.
        log.info("Yangi oyna so'rovi bloklandi")
        return None

    def javaScriptConfirm(self, _url, _message) -> bool:
        return False

    def certificateError(self, error) -> bool:
        # Sertifikat xatosi - MITM belgisi bo'lishi mumkin. Imtihon
        # muhitida uni "davom etish" bilan o'tkazib yuborish mumkin emas.
        log.error("Sertifikat xatosi: %s", error.description())
        return False


class ExamWebViewPage(QWidget):
    """Imtihon oynasi."""

    #: Server javobi (`seat_released`, `seat`) yoki `{"error": ...}` -
    #: talabgor sahifasi operatorga joy bo'shaganini aytadi.
    session_finished = pyqtSignal(dict)
    session_lost = pyqtSignal(str)
    #: Kuzatuv boshlanmadi - imtihon OCHILMADI.
    #
    # `session_lost` dan ATAYLAB ajratilgan: u sessiya yakunlangani
    # (yoki chetlashtirilgani) haqida, bu esa sessiya TIRIK, lekin
    # imtihon boshlanmadi degani. Operator kamerani tuzatib qayta
    # urinishi mumkin, sessiya esa o'z o'rnida qoladi.
    session_blocked = pyqtSignal(str, str)  # (kod, xabar)

    def __init__(self, state: AppState, repo: ProctoringRepository, parent=None) -> None:
        super().__init__(parent)
        self._state = state
        self._repo = repo
        self._workers = WorkerHolder()
        #: Test platformasi ochilgan va sessiya hali yakunlanmagan.
        self._exam_open = False
        #: Test sahifasi ochilgan payt (monoton soat) — yakunlash
        #: dialogida "test qancha davom etdi" degan qator uchun.
        self._opened_at: Optional[float] = None
        self._monitor = SessionMonitor(repo, parent=self)
        self._monitor.session_lost.connect(self._on_session_lost)
        self._monitor.network_changed.connect(self._on_network_changed)

        # Skrinshot xizmati ALOHIDA: uning taymeri, buferi va yuklash
        # yo'li hodisalar oqimidan mustaqil. Ular bir obyektga
        # birlashtirilsa, skrinshotning sekin yuklanishi hodisalar
        # flush'ini ham ushlab qolardi.
        self._screenshots = ScreenshotService(repo, parent=self)
        self._screenshots.sent.connect(self._on_screenshot_sent)
        self._screenshots.failed.connect(self._on_screenshot_failed)

        # Proktor buyruqlari. Bu TEZLIK qatlami: u uzilsa ham imtihon
        # to'xtamaydi va sessiyaning yakunlangani heartbeat orqali
        # baribir bilinadi (`services/realtime.py` docstring'iga qarang).
        self._channel = ProctorChannel(parent=self)
        self._channel.online.connect(self._on_channel_state)
        self._channel.warning.connect(self._on_proctor_warning)
        self._channel.terminated.connect(self._on_proctor_terminate)
        self._channel.resumed.connect(self._on_proctor_resume)

        # Qurilma kuzatuvi: oyna fokusi, to'liq ekran, monitorlar, RDP
        # va bloklangan tugmalar. U hodisalarni faqat CHIQARADI -
        # buferga yozish shu yerda, bitta joyda.
        self._watcher = DeviceWatcher(parent=self)
        self._watcher.detected.connect(self._on_device_event)

        # AI kuzatuv. U kamerani, modellarni va dalilni O'ZI
        # boshqaradi; sahifa faqat hodisa oqimini oladi. Siyosatda
        # o'chirilgan bo'lsa `start()` `False` qaytaradi va imtihon
        # o'zgarishsiz davom etadi.
        # EKRAN YOZUVI. Test sahifasi ochilgandan yakunigacha ishlaydi
        # va fayl MASHINADA qoladi - serverga faqat manzili boradi
        # (`services/screen_recorder.py`).
        self._recorder = ScreenRecorder(self)
        #: Yozuv/skrinshot/klip TO'XTAYDIGAN vaqt.
        #
        # Testga ajratilgan vaqt tugagach kuzatuvning o'zi davom
        # etadi (heartbeat, hodisalar, FaceID), lekin DALIL
        # YIG'ILMAYDI: talabgor javoblarini topshirgan, ekranda
        # esa platformaning yakuniy sahifasi turadi va uni soatlab
        # yozib borishning ma'nosi yo'q - fayl esa soatiga ~120 MB
        # o'sadi.
        self._capture_deadline = QTimer(self)
        self._capture_deadline.setSingleShot(True)
        self._capture_deadline.timeout.connect(self._on_capture_deadline)

        self._supervisor = ProctoringSupervisor(repo, parent=self)
        self._supervisor.event_ready.connect(self._on_device_event)
        self._supervisor.status_changed.connect(self._on_proctoring_status)
        self._supervisor.risk_changed.connect(self._on_risk_changed)

        #: Suzuvchi paneldagi nuqtaning tooltip'i uchun holat.
        #
        # Ilgari bu qiymatlar sarlavhadagi to'rtta nishonda turardi.
        # Sarlavha olib tashlandi, lekin MA'LUMOT yo'qolmadi: u
        # operator so'raganda (sichqonchani nuqta ustiga olib
        # borganda) ko'rinadi. Doimiy ko'rsatib turish esa talabgor
        # ekranida keraksiz shovqin edi - u bu raqamlarga hech
        # qachon qaramaydi.
        self._status = {
            "network": "Aloqa bor",
            "face": "FaceID: kutilmoqda",
            "shots": "Skrinshot: -",
            "record": "Yozuv: -",
            "risk": "Kuzatuv: -",
        }
        self._camera: Optional[CameraWorker] = None
        #: `proctoring/start/` javobini kutayotgan kirish ma'lumoti.
        self._pending_access: Optional[dict] = None
        self._pending_camera: Optional[CameraWorker] = None
        self._last_embedding = None
        self._last_faces = 0
        #: Oxirgi kadr (`CameraWorker` yo'li) - dalil rasmi uchun.
        self._last_frame = None
        #: U qachon kelgan (`time.monotonic`) - skrinshot ramkasiga
        #: eskirgan kadr tushmasligi uchun.
        self._last_frame_at = 0.0
        #: Client bajargan solishtirishlar soni (JAMI) va oxirgi
        #: xabardan keyingi MUVAFFAQIYATLI tekshiruvlar soni.
        #
        # Birinchisi heartbeat bilan ketadi (`face_checks`), ikkinchisi
        # muvaffaqiyatsizlik xabari bilan: serverga faqat xatolar
        # boradi, ya'ni "ketma-ket" qoidasini u boshqa yo'l bilan
        # bila olmaydi.
        self._face_checks = 0
        self._passed_since_last = 0
        self._interceptor: Optional[DomainAllowlistInterceptor] = None
        self._profile: Optional[QWebEngineProfile] = None

        self._face_timer = QTimer(self)
        self._face_timer.setInterval(runtime_settings.fallback("face.interval"))
        self._face_timer.timeout.connect(self._run_face_check)

        self._setup_ui()

    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        """
        SAHIFADA FAQAT BROWSER. Sarlavha yo'q.

        Ilgari tepada 58 px li panel turardi: talabgor ismi, imtihon
        nomi va to'rtta holat nishoni (FaceID, skrinshot, kuzatuv,
        aloqa). U ikki narsani buzardi:

          * test platformasi o'z sahifasini to'liq ekranga
            mo'ljallab chizadi va 58 px yo'qolishi uning o'z
            sarlavhasini yoki tugmalarini pastga surib, ba'zi
            platformalarda scroll paydo qilardi;
          * panel talabgorga QARATILGAN edi, holbuki undagi
            ma'lumot operator uchun. Talabgor imtihon davomida
            unga qarab o'tirardi.

        O'rniga suzuvchi panel: aloqa nuqtasi va ikkita ikonka
        brauzer USTIDA turadi va atigi ~150 px joy egallaydi.
        Qolgan holatlar (FaceID, skrinshot, kuzatuv) yo'qolmadi -
        ular nuqtaning tooltip'iga ko'chdi.
        """
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.web_view = QWebEngineView()
        self.web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        root.addWidget(self.web_view, 1)

        self._build_floating_bar()
        self.overlay = BusyOverlay(self)

        # XABAR SUZADI, LAYOUTDA EMAS. Ilgari bu yerda `MessageBar`
        # turardi va u ko'ringanda BUTUN test sahifasini pastga
        # surardi; xabarni hech kim tozalamagani uchun sahifa shu
        # holatda qolib ketardi. Snackbar esa brauzer ustida
        # chiziladi va o'zi yo'qoladi.
        self.message = Snackbar(self)

        # Ogohlantirish dialogi KERAK BO'LGANDA yaratiladi: uning
        # otasi asosiy OYNA bo'lishi kerak (dialog ekran markazida
        # ochiladi), sahifa qurilayotgan paytda esa u hali
        # `QStackedWidget` ga qo'shilmagan va `window()` sahifaning
        # o'zini qaytaradi.
        self._warning = None

    def _build_floating_bar(self) -> None:
        """
        Brauzer ustidagi suzuvchi panel (MD3 elevated surface).

        PASTKI O'NG BURCHAKDA. Tepa qism platformaning o'z
        sarlavhasi va tugmalari uchun ochiq qolishi kerak; pastki
        o'ng burchak esa veb-sahifalarda deyarli har doim bo'sh
        bo'ladi. Bu MD3 dagi FAB o'rni ham.

        Panel LAYOUTDA EMAS - u sahifaning bevosita bolasi va
        `resizeEvent` da joylashtiriladi. Layoutda bo'lsa u
        brauzerdan joy olardi, ya'ni "to'liq ochilsin" talabi
        bajarilmasdi.
        """
        # Panel — dizayn tizimidagi KARTA (`QFrame[role="card"]`).
        #
        # O'z uslubini yozish mumkin edi, lekin global jadvaldagi
        # `QWidget { background-color: ... }` qoidasi u bilan
        # birlashib, burchaklarni to'rtburchak qilib qoldirardi.
        # Karta selektori esa `QFrame` ga tegishli va u butun
        # ilovada allaqachon shu tarzda chiziladi - panel qolgan
        # kartalar bilan bir oilada bo'ladi.
        self._bar = QFrame(self)
        self._bar.setProperty("role", "card")
        layout = QHBoxLayout(self._bar)
        layout.setContentsMargins(14, 6, 8, 6)
        layout.setSpacing(4)

        self.status_dot = StatusDot(12)
        layout.addWidget(self.status_dot, 0, Qt.AlignmentFlag.AlignVCenter)

        self.problem_btn = GlyphButton(
            "warning", size=38, tooltip="Texnik muammo haqida xabar berish"
        )
        self.problem_btn.clicked.connect(self._on_technical_problem)
        layout.addWidget(self.problem_btn)

        # YAKUNLASH TUGMASI QOLDIRILDI. U sessiyani to'g'ri yopadigan
        # YAGONA yo'l: usiz sessiya ochiq qolib, faqat
        # `close_stale_sessions` bilan 15 daqiqadan keyin yig'ilardi
        # va o'sha vaqt ichida talabgor boshqa mashinada qayta kira
        # olmasdi (`MainWindow._back_action` izohi).
        self.finish_btn = GlyphButton(
            "power", size=38, tone="danger", tooltip="Imtihonni yakunlash"
        )
        self.finish_btn.clicked.connect(self._on_finish_clicked)
        layout.addWidget(self.finish_btn)

        self._bar.adjustSize()
        self._update_status_tooltip()

    def _update_status_tooltip(self) -> None:
        """
        Nuqtaning tooltip'i: barcha holatlar bitta joyda.

        Tartib ahamiyat bo'yicha: avval aloqa (usiz qolganlari
        ma'nosiz), keyin nazorat qatlamlari.
        """
        lines = [
            self._status.get("network", ""),
            self._status.get("face", ""),
            self._status.get("shots", ""),
            self._status.get("record", ""),
            self._status.get("risk", ""),
        ]
        candidate = self._status.get("candidate")
        if candidate:
            lines.insert(0, "{} — {}".format(candidate, self._status.get("exam", "")))
        tooltip = "\n".join(line for line in lines if line)
        self.status_dot.setToolTip(tooltip)
        self._bar.setToolTip(tooltip)

    def _place_floating_bar(self) -> None:
        """
        Panelni pastki o'ng burchakka qo'yadi.

        `raise_()` HAR SAFAR: `QWebEngineView` o'z oynasini
        boshqaradi va sahifa qayta yuklanganda u panelni bosib
        qolishi mumkin.
        """
        self._bar.adjustSize()
        margin = _BAR_MARGIN
        self._bar.move(
            self.width() - self._bar.width() - margin,
            self.height() - self._bar.height() - margin,
        )
        self._bar.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.overlay.setGeometry(self.rect())
        self._place_floating_bar()
        self.message.reposition()
        # Qoplama paneldan YUQORIDA qoladi: kutish ekrani butun
        # sahifani yopishi kerak va uning ustidan chiqib turgan tugma
        # "bosish mumkin" degan yolg'on signal berardi.
        self.overlay.raise_()
        self.message.raise_()

    def showEvent(self, event) -> None:
        """
        Ko'rsatilganda panel QAYTA joylashtiriladi.

        `QStackedWidget` sahifani YASHIRIN holida o'lchamga
        keltiradi va o'shanda `resizeEvent` allaqachon o'tib
        ketgan bo'lishi mumkin. Ko'rsatilgandan keyin o'lcham
        o'zgarmasa, panel boshlang'ich (0, 0) nuqtasida - ya'ni
        chap yuqorida, platformaning sarlavhasi ustida qolardi.
        """
        super().showEvent(event)
        self._place_floating_bar()

    # ------------------------------------------------------------------
    # Ishga tushirish
    # ------------------------------------------------------------------
    def start(self, access: dict, camera: Optional[CameraWorker] = None) -> None:
        """
        Imtihonni ochadi.

        BIRINCHI ISH - kuzatuvni ishga tushirish (`proctoring/start/`).
        U server tomonda kamera tekshiruvini majburlaydi va rad
        etishi mumkin. Rad javobi WebView OCHILGUNCHA kelishi shart:
        talabgor testni bir marta ko'rgach, uni "boshlanmadi" deb
        e'lon qilish mumkin emas - platformada urinish allaqachon
        ochilgan bo'ladi.

        Qolgan tayyorgarlik (profil, kamera, nazorat) start
        muvaffaqiyatli bo'lgach bajariladi.
        """
        self.overlay.start("Kuzatuv ishga tushirilmoqda...")
        self._pending_access = access
        self._pending_camera = camera
        self._arm_local_archive()

        # Apparat profili SHU YERDA aniqlanadi va u fon thread'ida
        # bo'lishi shart: ONNX Runtime importi va provayderlar
        # ro'yxatini o'qish sekundgacha vaqt oladi va UI thread'da
        # oyna muzlab qolardi.
        worker = ApiWorker(self._begin_proctoring, parent=self)
        worker.succeeded.connect(self._on_proctoring_started)
        worker.failed.connect(self._on_proctoring_refused)
        self._workers.run(worker)

    def _arm_local_archive(self) -> None:
        """
        Mahalliy arxivga sessiya kontekstini beradi.

        SHU YERDA, chunki bu nuqtada hamma narsa ma'lum: imtihon va
        uning turi, ochilgan sessiya, operator kiritgan JSHSHIR va
        mashinaning MAC manzili. Kontekstsiz arxiv umuman
        yozmaydi - nomsiz fayl "kimningdir kadri" bo'lib qolardi
        (`services/local_archive.py`).
        """
        state = self._state
        exam = state.selected_exam
        session = state.session
        local_archive.set_context(
            exam_type=exam.exam_type_name if exam else "",
            exam=exam.name if exam else "",
            session_id=session.public_id if session else "",
            pinfl=state.pinfl,
            mac=(state.machine or {}).get("mac", ""),
        )

    # ------------------------------------------------------------------
    # Ekran yozuvi
    # ------------------------------------------------------------------
    def _start_recording(self) -> None:
        """
        Ekran yozuvini boshlaydi va dalil oynasini ochadi.

        FON THREAD'IDA ishlaydi (kodlash), GUI thread'ida esa
        sekundiga bitta kadr olinadi (~15 ms) - test sahifasi buni
        sezmaydi.

        Yozuv IMTIHON PROFILIDA o'chirilgan bo'lsa (`capture.screen_record`,
        panelda "Ekranni yozish"; zaxira - `.env` `SCREEN_RECORD_ENABLED`)
        qolgan hammasi avvalgidek ishlayveradi: yozuv kuzatuvning
        sharti emas, qo'shimcha dalil. Ilgari panel maydoni umuman
        o'qilmasdi va yozuvni faqat `.env` hal qilardi.
        """
        self._arm_capture_deadline()
        if not runtime_settings.get(self._state.config, "capture.screen_record"):
            log.info("Ekran yozuvi imtihon profilida o'chirilgan")
            return

        folder = local_archive.current_folder()
        if not folder:
            # Arxiv o'chirilgan yoki disk topilmadi. Yozuvni
            # vaqtinchalik katalogga yozish mumkin emas: u 360 MB
            # va tizim diskini to'ldirardi.
            log.info("Mahalliy arxiv yo'q - ekran yozuvi olinmaydi")
            return

        import os

        path = os.path.join(folder, "screen.mp4")
        if self._recorder.start(
            path, camera_provider=self._recording_frame, config=self._state.config
        ):
            self._status["record"] = "Yozuv: ketyapti"
            self._update_status_tooltip()

    def _recording_frame(self):
        """
        Ekran yozuviga qo'yiladigan KAMERA kadri.

        Kadr ishlab turgan manbadan olinadi va u ikki xil bo'lishi
        mumkin: AI kuzatuv yoqilgan bo'lsa kamera SUPERVISOR da
        (bitta qurilmani ikki jarayon ocholmaydi), aks holda
        FaceID sahifasidan kelgan `CameraWorker` da. Ikkalasi ham
        bir xil taqsimotdan quriladi, ya'ni yozuvga tushadigan
        tasvir operator tekshiruv sahifasida ko'rgan kameraning
        O'ZI - veb-kamera bo'ladimi, IP kamera bo'ladimi.

        `None` XATO EMAS: kamera qayta ulanayotgan bo'lishi mumkin
        va o'sha kadrlarda yozuv PiP siz davom etadi.
        """
        if self._supervisor.is_active:
            return self._supervisor.latest_frame()
        return self._last_frame

    def _arm_capture_deadline(self) -> None:
        """
        Dalil yig'ish oynasini TESTGA AJRATILGAN VAQTGA bog'laydi.

        Vaqt PLATFORMADAN keladi (`Candidate.duration_minutes`) va u
        sessiyaga muzlatilgan - ya'ni "talabgorga qancha vaqt
        berilgan" degan savolga javob bitta joydan.

        VAQT KELMAGAN BO'LSA CHEKLOV QO'YILMAYDI. Platforma
        `duration_time` ni bermasligi mumkin (`CLAUDE.md`: u keyin
        qo'shilgan maydon) va o'shanda yozuvni ixtiyoriy raqamga
        bog'lash uni imtihon o'rtasida jimgina to'xtatardi. Yakun
        baribir bor - "Imtihonni yakunlash" tugmasi.
        """
        candidate = self._state.candidate
        minutes = int(getattr(candidate, "duration_minutes", 0) or 0)
        if minutes <= 0:
            self._capture_deadline.stop()
            log.info("Testga ajratilgan vaqt noma'lum - yozuv yakungacha davom etadi")
            return
        self._capture_deadline.start(minutes * 60 * 1000)
        log.info("Dalil yig'ish oynasi: %s daqiqa", minutes)

    def _on_capture_deadline(self) -> None:
        """Ajratilgan vaqt tugadi — dalil yig'ish to'xtaydi."""
        log.info("Testga ajratilgan vaqt tugadi - dalil yig'ish to'xtatildi")
        self._stop_capture()
        self._status["record"] = "Yozuv: vaqt tugadi"
        self._update_status_tooltip()

    def _stop_capture(self, *, register: bool = True):
        """
        Yozuv, skrinshot va klip yig'ishni to'xtatadi.

        Yakunlangan yozuvni QAYTARADI (bo'lmasa `None`).
        `register=False` - manzilni chaqiruvchi o'zi yuboradi: imtihon
        yakunida u `session/finish/` bilan BITTA fon chaqiruvida va
        undan OLDIN ketishi shart (`finish` ga qarang).

        KUZATUVNING O'ZI TO'XTAMAYDI: heartbeat, hodisalar va
        davriy FaceID davom etadi. Sessiya hali ochiq va proktor
        uni ko'rib turishi kerak - to'xtaydigan narsa faqat
        DALIL YIG'ISH.

        TAKRORIY CHAQIRUV XAVFSIZ: bu yerga uch yo'ldan kelinadi
        (vaqt tugadi, talabgor yakunladi, sahifa yopildi) va
        ularning tartibi kafolatlanmagan.
        """
        self._capture_deadline.stop()
        self._screenshots.stop()
        self._supervisor.set_capture_enabled(False)
        result = self._recorder.stop()
        if not result.ok:
            return None
        if register:
            self._register_recording(result)
        return result

    def _recording_fields(self, result) -> dict:
        """
        `client/recordings/` so'rovining tanasi - ikki yo'l uchun bitta.

        UI THREAD'IDA va sessiya holati tozalanishidan OLDIN
        chaqiriladi: `session_id` shu yerda olinadi va keyin fon
        so'rovi ketguncha `AppState.session` allaqachon `None`
        bo'lishi mumkin (chetlashtirish yo'li).
        """
        from datetime import datetime, timezone

        session = self._state.session
        return {
            "session_id": getattr(session, "public_id", "") or "",
            "kind": "screen",
            "local_path": result.path,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "size_bytes": result.size_bytes,
            "duration_ms": result.duration_ms,
            "width": result.width,
            "height": result.height,
            "frames": result.frames,
            "frames_dropped": result.dropped,
        }

    def _register_recording(self, result) -> None:
        """
        Yozuv manzilini serverga yuboradi (fayl EMAS).

        FON THREAD'IDA va javob KUTILMAYDI: bu imtihon yakunining
        yo'lida turadi va tarmoq sekinligi talabgorni ekran
        oldida ushlab turmasligi kerak. Xato bo'lsa fayl baribir
        mashinada qoladi - qayd faqat proktor uni topishi uchun.
        """
        worker = ApiWorker(
            self._repo.register_recording,
            parent=self,
            **self._recording_fields(result),
        )
        worker.failed.connect(
            lambda message, code: log.warning(
                "Ekran yozuvi qayd etilmadi (%s): %s - fayl mashinada qoldi",
                code or "-", message,
            )
        )
        self._workers.run(worker)

    def _begin_proctoring(self) -> dict:
        """
        Profilni aniqlaydi va serverda kuzatuvni ochadi.

        Ikkisi BITTA fon chaqiruvida: profil nomi so'rovning o'zida
        ketadi (`ai_profile`) va u sessiyaga yoziladi - qaysi
        mashinada qanday chegaralar bilan kuzatilgani bayonnomada
        qolishi kerak.
        """
        policy = (self._state.config or {}).get("proctoring") or {}
        profile = self._supervisor.detect_profile(
            override=policy.get("gpu_profile") or ""
        )
        self._state.ai_profile = profile.name
        return self._repo.proctoring_start(ai_profile=profile.name)

    def _on_proctoring_started(self, result) -> None:
        self.overlay.stop()
        log.info(
            "Kuzatuv faollashdi (kamera tekshiruvi: %s)",
            ((result or {}).get("camera_check") or {}).get("status", "-"),
        )
        access, self._pending_access = self._pending_access or {}, None
        camera, self._pending_camera = self._pending_camera, None
        self._begin(access, camera)

    def _on_proctoring_refused(self, message: str, code: str) -> None:
        """
        Server kuzatuvni boshlashni RAD ETDI.

        Sabab odatda kamera tekshiruvida: o'tkazilmagan
        (`camera_check_required`) yoki talablarga mos kelmagan
        (`camera_check_failed`). Ikkalasida ham operator imtihon
        tanlash ekraniga qaytib, kamerani tuzatishi kerak.
        """
        self.overlay.stop()
        self._pending_access = None
        self._release_pending_camera()
        log.warning("Kuzatuv boshlanmadi (%s): %s", code or "-", message)
        self.session_blocked.emit(code or "proctoring_refused", message)

    def _release_pending_camera(self) -> None:
        """
        FaceID sahifasidan kelgan, lekin hali ishlatilmagan kamerani
        TO'XTATADI.

        Referensni shunchaki `None` qilish YETARLI EMAS va aynan shu
        xato dasturni qulatgan: worker ishlashda davom etadi va
        kamerani band qilib turadi, keyingi sahifa (imtihon tanlash
        ekranidagi kamera aniqlash) o'sha qurilmani ochganda uning
        sikli uziladi va thread tugagan zahoti jarayon `0xC0000409`
        bilan yopiladi. Kamerani FaceID sahifasiga QAYTARMAYMIZ:
        rad javobidan keyin operator odatda kamerani almashtiradi
        yoki tekshiradi va u baribir qaytadan ochilishi kerak.
        """
        camera, self._pending_camera = self._pending_camera, None
        if camera is not None:
            retire_camera(camera)

    def _begin(self, access: dict, camera: Optional[CameraWorker]) -> None:
        candidate = self._state.candidate
        exam = self._state.selected_exam
        self.message.clear_message()
        # Hisoblagich HAR TALABGOR uchun noldan boshlanadi - aks holda
        # tooltip'da oldingi sessiyaning soni qolib, operator
        # skrinshot olinayotgan deb o'ylardi.
        self._status.update(
            {
                "candidate": candidate.display_name if candidate else "-",
                "exam": exam.name if exam else "",
                "face": "FaceID: kutilmoqda",
                "shots": "Skrinshot: -",
                "record": "Yozuv: -",
                "risk": "Kuzatuv: -",
            }
        )
        self._update_status_tooltip()
        # Oldingi talabgorga qaratilgan ogohlantirish keyingisining
        # ekranida qolib ketmasligi kerak.
        if self._warning is not None:
            self._warning.dismiss()
        self.message.clear_message()

        policy = access.get("webview_policy") or {}
        self._configure_profile(policy)
        self._open_platform(access)

        # AI kuzatuv KAMERANI EGALLAYDI. Bitta qurilmani ikki
        # jarayon ocha olmaydi, shuning uchun eski `CameraWorker`
        # (FaceID sahifasidan kelgan) bu holatda bo'shatiladi va
        # davriy tekshiruv pipeline natijasidan oziqlanadi.
        # ETALON `AppState` DAN. Ilgari bu yerda sahifaning o'z
        # `_last_embedding` i turardi va u shu paytda HAR DOIM `None`
        # bo'lardi: u faqat kamera signali ulangandan keyin
        # to'ladi, signal esa quyida ulanadi. Natijada AI qatlami
        # etalonsiz ishlab, `face_mismatch` hodisasi hech qachon
        # tug'ilmasdi.
        reference = self._state.face_reference
        if reference is None:
            log.warning("Yuz etaloni yo'q - davriy FaceID o'tkazib yuboriladi")

        # KAMERA AVVAL BO'SHATILADI, keyin kuzatuv oqimi ochadi
        # (`before_open`). Teskari tartibda ikkala tomon bitta
        # qurilmani ushlab, oqim "kamera band" xatosi bilan qayta
        # ulanish kutishiga tushardi.
        if self._supervisor.start(
            config=self._state.config,
            layout=self._state.cameras,
            session_id=getattr(self._state.session, "public_id", "") or "",
            before_open=lambda: self._release_camera(camera),
        ):
            self._supervisor.set_reference(reference)
        else:
            self._attach_camera(camera)

        self._monitor.start(self._state.config)
        self._report_startup_threats()
        self._face_checks = 0
        self._passed_since_last = 0
        # ORALIQ IMTIHON PROFILIDAN (`face.interval`, soniyada).
        # Ilgari bu yerda 60 s qadab qo'yilgan edi va u serverdagi
        # sozlama bilan jimgina ziddiyatda edi. Endi solishtirish
        # clientda va tarmoqqa faqat xatolar chiqadi, ya'ni serverda
        # ko'rsatilgan tezlikda tekshirish arzon.
        self._face_timer.setInterval(
            runtime_settings.get(self._state.config, "face.interval")
        )
        self._face_timer.start()
        # Sozlama handshake'dan keladi: interval, sifat, kenglik va
        # dedup chegarasi imtihonga biriktirilgan profilga bog'liq.
        self._screenshots.start(
            self._state.config, camera_provider=self._screenshot_cameras
        )
        self._start_recording()

        session = self._state.session
        self._channel.start(session.token if session else "")

        # `self.window()` - sahifa emas, uni o'z ichiga olgan
        # `MainWindow`: to'liq ekran holati o'sha yerda.
        self._watcher.start(self._state.config, window=self.window())
        # Bloklangan tugma bosilgani hodisa oqimiga tushadi. Observer
        # SESSIYA davomida qo'yiladi va yakunda olib tashlanadi:
        # qulflashning o'zi dastur bo'yicha ishlaydi (login sahifasida
        # ham), lekin hodisa yozadigan sessiya faqat shu yerda bor.
        lockdown.set_observer(self._watcher.report_blocked_key)

    def _configure_profile(self, policy: dict) -> None:
        """
        Har sessiya uchun YANGI off-the-record profil.

        Sabab: oldingi talabgorning cookie va sessiyasi keyingisiga
        o'tib qolmasligi kerak. Off-the-record profil diskka hech narsa
        yozmaydi, ya'ni imtihondan keyin mashinada iz qolmaydi.
        """
        profile = QWebEngineProfile(self)
        profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies
        )

        allowed = policy.get("allowed_domains") or []
        self._interceptor = DomainAllowlistInterceptor(allowed, self._on_blocked_host)
        profile.setUrlRequestInterceptor(self._interceptor)

        if policy.get("block_downloads", True):
            profile.downloadRequested.connect(self._on_download_requested)

        page = LockedWebPage(profile, self)
        settings = page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ScreenCaptureEnabled, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PdfViewerEnabled, False)

        # Profil Python tomonda referenssiz qolsa yig'ib yuboriladi va
        # sahifa "Render process terminated" bilan qulaydi.
        self._profile = profile
        self.web_view.setPage(page)

    def _open_platform(self, access: dict) -> None:
        """
        Platformaning tayyor havolasini ochadi (`data.test_link`).

        CLIENT PLATFORMAGA O'ZI MUROJAAT QILMAYDI. Havolani ham,
        undagi tokenni ham server tayyorlab beradi: u JSHSHIR
        tekshiruvida platformadan olingan va sessiyaga muzlatilgan
        (`integrations/exam_site.py`). Bu yerda hech qanday
        kredensial yo'q — shuning uchun so'rovga qo'shiladigan
        sarlavha ham yo'q.

        `delivery` faqat SHARTNOMANI tekshirish uchun o'qiladi:
        server "url" dan boshqa qiymat yuborsa, demak u boshqa
        platforma bilan ishlaydi va bu client uni ocholmaydi —
        jimgina bo'sh sahifa ko'rsatishdan ko'ra buni aytgan
        ma'qul.
        """
        login_url = access.get("login_url") or ""
        delivery = (access.get("delivery") or "url").lower()
        # Shu nuqtadan talabgor testni ko'radi va sessiya "ochiq
        # imtihon" hisoblanadi: sahifadan qanday chiqilmasin, u
        # serverda YAKUNLANISHI kerak (`finish_on_exit`).
        self._exam_open = True
        self._opened_at = time.monotonic()

        if not login_url:
            self.message.show_message("Test havolasi berilmadi", "error")
            return

        if delivery != "url":
            log.error("Kutilmagan `delivery` qiymati: %s", delivery)
            self.message.show_message(
                "Server test havolasini kutilmagan shaklda yubordi — "
                "administratorga murojaat qiling",
                "error",
            )
            return

        # LOG'GA MANZIL YOZILMAYDI: havola ichida bir martalik token
        # bor va log fayli imtihon mashinasida qoladi.
        log.info("Test platformasi ochilmoqda: %s", urlparse(login_url).hostname or "-")
        self.web_view.load(QUrl(login_url))

    # ------------------------------------------------------------------
    # Nazorat
    # ------------------------------------------------------------------
    def _on_device_event(self, event_type: str, severity: int, payload: dict) -> None:
        """Kuzatuvchi chiqargan hodisani buferga qo'yadi."""
        self._monitor.push_event(event_type, severity=severity, payload=payload)

    def _attach_camera(self, camera: Optional[CameraWorker]) -> None:
        """4-sahifadan kelgan kamerani davriy tekshiruvga ulaydi."""
        self._camera = camera
        if camera is not None:
            camera.frame_ready.connect(self._on_camera_frame)
            camera.face_result.connect(self._on_face_result)
            camera.camera_error.connect(self._on_camera_error)

    def _on_camera_frame(self, frame) -> None:
        """
        Oxirgi kadrni eslab qoladi - muvaffaqiyatsiz tekshiruvga
        biriktiriladigan rasm shundan olinadi.

        Nusxa OLINMAYDI: `CameraWorker` allaqachon `frame.copy()`
        emit qiladi, bu yerda esa faqat havola saqlanadi (bitta kadr
        ~900 KB va u keyingi kadr kelganda bo'shaydi).
        """
        self._last_frame = frame
        self._last_frame_at = time.monotonic()

    def _screenshot_cameras(self) -> list:
        """
        Skrinshotga qo'yiladigan kamera kadrlari: `[(rol, kadr | None)]`.

        Manba ekran yozuvidagi bilan bir xil (`_recording_frame`): AI
        kuzatuv yoqilgan bo'lsa kameralar supervisor'da (u ikkinchi
        kamerani ham beradi), aks holda FaceID ishchisida - faqat yuz
        kamerasi. Ishchi umuman yo'q bo'lsa ro'yxat bo'sh: kamera
        ishlatilmayapti va ramka chizilmaydi.
        """
        if self._supervisor.is_active:
            return self._supervisor.camera_slots(CAMERA_FRAME_MAX_AGE_S)
        if self._camera is None:
            return []
        fresh = (
            self._last_frame is not None
            and time.monotonic() - self._last_frame_at <= CAMERA_FRAME_MAX_AGE_S
        )
        return [("primary", self._last_frame if fresh else None)]

    def _release_camera(self, camera: Optional[CameraWorker]) -> None:
        """
        Eski kamera ishchisini yopadi (AI kuzatuv uni almashtirdi).

        Yopmasdan qoldirish qurilmani band qilib turardi va
        `CameraManager` uni ocholmasdi - kuzatuv esa jimgina
        ishlamay qolardi.
        """
        self._camera = None
        if camera is not None:
            retire_camera(camera)

    def _on_proctoring_status(self, message: str) -> None:
        """Modul o'chdi yoki kamera holati o'zgardi."""
        log.warning("Kuzatuv holati: %s", message)

    def _on_risk_changed(self, score: int, level: str) -> None:
        self._status["risk"] = "Kuzatuv: {} ({})".format(score, level)
        self._update_status_tooltip()

    def _on_camera_error(self, message: str) -> None:
        """
        Kamera yo'qoldi yoki ochilmadi.

        `camera_blocked` dan ATAYLAB farqlanmaydi: kabel uzilgani,
        drayver yiqilgani va ob'ektiv yopilgani `cv2` darajasida bir xil
        ko'rinadi. Sabab `payload` da qoladi va qarorni proktor chiqaradi.
        """
        log.warning("Kamera xatosi: %s", message)
        self._monitor.push_event(
            "camera_lost", severity=3, payload={"reason": message[:300]}
        )

    def _on_face_result(self, result: dict) -> None:
        """
        Kadr natijasi eslab qolinadi, lekin DARHOL yuborilmaydi.

        Har kadr uchun so'rov yuborish daqiqasiga ~600 so'rov degani va
        `client_ingest` chegarasini bir zumda yeb qo'yadi. Taymer esa
        siyosatdagi oraliqda bir marta solishtiradi.
        """
        state = result.get("state")
        if state == "ok":
            self._last_embedding = result.get("embedding")
            self._last_faces = 1
        elif state == "none":
            self._last_embedding = None
            self._last_faces = 0
            self._monitor.push_event("face_not_found", severity=2)
        elif state == "multiple":
            self._last_embedding = None
            self._last_faces = len(result.get("bboxes") or []) or 2
            self._monitor.push_event("multiple_faces", severity=3)
        else:
            # "far" - yuz bor, lekin juda uzoq. Embedding ishonchsiz
            # (ArcFace uni 112x112 ga cho'zadi), shuning uchun u
            # solishtirishga BERILMAYDI, lekin "yuz yo'q" ham emas.
            self._last_embedding = None
            self._last_faces = 1

    def _current_face(self) -> tuple:
        """
        Solishtirish uchun oxirgi natija: `(embedding, yuzlar_soni)`.

        AI kuzatuv ishlayotganda kamera unda va yuz modeli ham unda
        yuklangan. Ikkinchi modelni ochish xotirani ikki barobar yeb,
        hech qanday yangi ma'lumot bermasdi.
        """
        if self._supervisor.is_active:
            embedding, faces = self._supervisor.latest_identity
            return embedding, int(faces or 0)
        return self._last_embedding, int(self._last_faces or 0)

    def _face_frame(self) -> Optional[bytes]:
        """
        Muvaffaqiyatsiz tekshiruvga biriktiriladigan JONLI KADR.

        Kadr manbai kuzatuv rejimiga bog'liq: AI ishlayotganda u
        kamerani egallagan bo'ladi va kadr `CameraManager` dan
        olinadi, aks holda `CameraWorker` signalidan.

        Kadr bo'lmasa `None` - xabar rasmsiz ketadi. Rasm dalil,
        to'siq emas.
        """
        frame = None
        if self._supervisor.is_active:
            frame = self._supervisor.latest_frame()
        if frame is None:
            frame = self._last_frame
        if frame is None:
            return None
        try:
            return encode_jpeg(frame) or None
        except Exception:
            log.warning("Kadrni JPEG ga o'girib bo'lmadi", exc_info=True)
            return None

    def _report_startup_threats(self) -> None:
        """
        Ishga tushishdagi tozalash natijasini hodisa oqimiga qo'shadi.

        NIMA UCHUN SHU YERDA, tozalashning o'sha paytida emas. Tozalash
        dastur ochilishi bilan, Qt yaratilishidan ham oldin bajariladi
        (`main._sweep_threats`) — o'sha paytda na sessiya, na hodisa
        buferi mavjud. Hodisa esa sessiyaga bog'lanishi shart, aks
        holda u bayonnomada hech qayerga tushmasdi.

        YOPILGAN DASTUR HAM YOZILADI. "AnyDesk topildi va yopildi"
        imtihonga ta'sir qilmagan, lekin bayonnomaning qismi:
        mashinada masofaviy boshqaruv o'rnatilgani tekshiruv
        komissiyasi uchun ma'lumot bo'lib qoladi.

        BIR MARTA: hisobot o'qilgandan keyin tozalanadi. Sessiya qayta
        boshlansa (operator kamerani tuzatib qayta urdi), o'sha eski
        topilmalarni ikkinchi marta yozish hodisa oqimida dublikat
        berardi.
        """
        from services import threat_scanner

        report = threat_scanner.last_report()
        if report is None:
            return
        for event_type, severity, payload in report.events():
            self._monitor.push_event(event_type, severity=severity, payload=payload)
        threat_scanner.remember(None)

    def _run_face_check(self) -> None:
        """
        Davriy FaceID - SOLISHTIRISH SHU YERDA.

        Etalon `AppState.face_reference` da (kirishda tasdiqlangan
        kadrning vektori), jonli vektor esa kuzatuv oqimidan. Ikkalasi
        ham RAM'da, ya'ni tekshiruv tarmoqqa umuman chiqmaydi.

        SERVERGA FAQAT MUVAFFAQIYATSIZ NATIJA BORADI. Muvaffaqiyatli
        tekshiruvlar soni heartbeat bilan ketadi - o'sha son bo'lmasa,
        panelda "0 tekshiruv" ko'rinib, kuzatuv ishlamagandek
        tuyulardi.
        """
        if not self._monitor.is_active:
            return

        reference = self._state.face_reference
        if reference is None:
            # Etalonsiz solishtirib bo'lmaydi. XABAR HAM YUBORILMAYDI:
            # "mos kelmadi" deb yozish aybsiz talabgorni etalon
            # yo'qligi uchun chetlashtirardi.
            return

        if self._supervisor.is_active and not self._supervisor.identity_ready:
            # Kuzatuv ishlayapti, lekin yuz moduli yo'q (model
            # topilmadi yoki siyosat o'chirgan). U holda natija HAR
            # DOIM "yuz yo'q" bo'lardi va bir necha daqiqada aybsiz
            # talabgor chetlashtirilardi. Nosozlik allaqachon
            # `proctoring_degraded` hodisasida qayd etilgan.
            return

        if not self._supervisor.is_active and self._camera is None:
            # Kamera umuman yo'q: na AI kuzatuvi, na `CameraWorker`.
            # "Yuz topilmadi" deb xabar qilish talabgorni USKUNA
            # nosozligi uchun chetlashtirardi. Kameraning yo'qligi
            # `camera_lost` hodisasi bilan qayd etilgan va qaror
            # siyosatda (`camera_lost_action`).
            return

        embedding, faces = self._current_face()
        self._face_checks += 1
        self._monitor.set_face_checks(self._face_checks)

        threshold = self._face_threshold()
        score = 0
        if embedding is not None and faces == 1:
            score = FaceEngine.compare(reference, embedding)

        if score >= threshold and faces == 1:
            self._passed_since_last += 1
            self._status["face"] = "FaceID: mos ({}%)".format(score)
            self._update_status_tooltip()
            return

        self._report_face_failure(score=score, faces=faces)

    def _face_threshold(self) -> int:
        """
        Test davomidagi chegara - IMTIHON PROFILIDAN.

        `min_score_exam` kirishdagi `min_score_initial` dan farq
        qilishi mumkin va bu normal: kirishda pasport rasmi bilan
        solishtiriladi (sifat past), test davomida esa o'sha
        kameradagi kadr bilan (sifat yuqori).
        """
        face_config = (self._state.config or {}).get("face") or {}
        try:
            return int(face_config.get("min_score_exam"))
        except (TypeError, ValueError):
            return similarity_score(FACE_MATCH_THRESHOLD)

    def _report_face_failure(self, *, score: int, faces: int) -> None:
        """Muvaffaqiyatsiz tekshiruv: ball, kadr va oradagi muvaffaqiyatlar."""
        passed_since_last = self._passed_since_last
        self._passed_since_last = 0

        worker = ApiWorker(
            self._repo.periodic_face,
            score=int(score),
            faces_detected=int(faces),
            image=self._face_frame(),
            passed_since_last=int(passed_since_last),
            parent=self,
        )
        worker.succeeded.connect(self._on_periodic_result)
        worker.failed.connect(lambda message, code: log.info("Davriy FaceID: %s", message))
        self._workers.run(worker)

    def _on_periodic_result(self, result) -> None:
        """
        Natija faqat HOLAT QATORIGA yoziladi — imtihon to'xtamaydi.

        Ilgari server `terminated` qaytarardi va client sessiyani
        yopardi. Endi ketma-ket muvaffaqiyatsizliklar chegarasi faqat
        panelga xabar beradi (kritik hodisa), qarorni esa proktor
        qabul qiladi: yorug'lik o'zgarishi yoki ko'zoynak tufayli
        ketma-ket uchta past ball butun imtihonni bekor qilishi
        mumkin emas.

        Chetlashtirish yo'li YO'QOLMAYDI — u proktordan keladi va
        boshqa kanal orqali ishlaydi (`_on_proctor_terminate`,
        heartbeat javobidagi `should_stop`).
        """
        data = result or {}
        fail_count = int(data.get("fail_count") or 0)
        max_fail = int(data.get("max_fail") or 0)

        if data.get("limit_reached"):
            # Operator uchun ham ko'rinsin: bu holat proktorning
            # aralashuvini talab qiladi.
            log.warning(
                "FaceID chegarasiga yetildi (%s/%s) — proktorga xabar berildi",
                fail_count, max_fail,
            )
            self._status["face"] = "FaceID: mos emas ({}/{}) — proktorga xabar berildi".format(
                fail_count, max_fail
            )
        else:
            self._status["face"] = "FaceID: mos emas ({}/{})".format(fail_count, max_fail)
        self._update_status_tooltip()

    def _on_network_changed(self, online: bool) -> None:
        # Nuqta YASHIL -> tinch, QIZIL -> pulsatsiya bilan. Aloqa
        # yo'qligi e'tibor talab qiladi: hodisalar yuborilmayapti,
        # ya'ni dalil real vaqtda yig'ilmayapti.
        self.status_dot.set_online(online)
        self._status["network"] = "Aloqa bor" if online else "Aloqa yo'q"
        self._update_status_tooltip()
        # Uzilish hodisa oqimida ham qoladi. Bu bayonnoma uchun muhim:
        # uzilish paytida skrinshot va hodisalarda bo'shliq bo'ladi va
        # uning SABABI yozilmasa, bo'shliq nazoratning nosozligiday
        # ko'rinadi. Hodisa uzilishdan KEYIN yuboriladi (bufer bilan),
        # ya'ni u o'zi ham o'sha bo'shliqning ichida turadi.
        self._monitor.push_event(
            "network_restored" if online else "network_lost",
            severity=0 if online else 2,
        )
        if not online:
            self.message.show_message(
                "Server bilan aloqa yo'q. Hodisalar buferda saqlanmoqda.", "warning"
            )
        else:
            self.message.clear_message()

    def _on_screenshot_sent(self, total: int) -> None:
        self._status["shots"] = "Skrinshot: {}".format(total)
        self._update_status_tooltip()

    def _on_screenshot_failed(self, message: str) -> None:
        # Xabar `MessageBar` ga CHIQARILMAYDI: u tarmoq holati uchun
        # band va skrinshot xatosi odatda o'sha uzilishning natijasi -
        # ikkita bir xil ogohlantirish operatorni chalg'itadi. Nishon
        # esa ko'rinib turadi.
        pending = self._screenshots.pending
        self._status["shots"] = (
            "Skrinshot: navbatda {}".format(pending) if pending else "Skrinshot: xato"
        )
        self._update_status_tooltip()
        log.info("Skrinshot xatosi: %s", message)

    # ------------------------------------------------------------------
    # Proktor buyruqlari (WebSocket)
    # ------------------------------------------------------------------
    def _on_channel_state(self, online: bool) -> None:
        """
        Kanal holati OPERATORGA ko'rsatilmaydi.

        Suzuvchi paneldagi nuqta tarmoq holatini bildiradi va u heartbeat
        natijasiga tayanadi - haqiqiy kafolat o'sha yerda. WebSocket
        uzilishi esa ko'pincha o'tkinchi (proksi idle timeout) va uni
        ekranga chiqarish operatorni bekorga tashvishga soladi.
        """
        log.info("Proktor kanali: %s", "ulandi" if online else "uzildi")

    def _warning_dialog(self):
        """
        Ogohlantirish dialogi - BITTA nusxa, kerak bo'lganda.

        Ota - asosiy OYNA: dialog ekran markazida ochilishi va
        butun dasturni modal qilib qulflashi kerak. Nusxa
        saqlanadi, chunki keyingi ogohlantirish avvalgisini
        ALMASHTIRADI (ikkita modal bir-birining ustida ochilsa,
        pastdagisi umuman o'qilmasdi).
        """
        if self._warning is None:
            from ui.dialogs.warning_dialog import WarningDialog

            self._warning = WarningDialog(self.window())
        return self._warning

    def _on_proctor_warning(self, message: str, severity: int) -> None:
        timeout = 5
        try:
            timeout = int(
                ((self._state.config or {}).get("face") or {}).get("warning_timeout", 5)
            )
        except (TypeError, ValueError):
            pass
        # JURNALGA HAM YOZILADI. "Yubordim, lekin ko'rinmadi" degan
        # shikoyatda birinchi savol - xabar mashinaga YETIB KELDIMI;
        # usiz javob faqat taxmin bo'lardi.
        log.info("Proktor ogohlantirdi (jiddiylik %s): %s", severity, message)
        self._warning_dialog().show_warning(message, severity, timeout)
        # Ogohlantirish hodisa oqimida ham qoladi: proktor uni yuborgani
        # serverda audit'da bor, lekin talabgorning mashinasi uni
        # HAQIQATDAN ham ko'rsatgani faqat shu yozuvdan bilinadi.
        self._monitor.push_event(
            "proctor_warning",
            severity=2,
            payload={"message": message[:500], "shown": True},
        )

    def _on_proctor_terminate(self, reason: str) -> None:
        """
        Proktor sessiyani to'xtatdi - DARHOL.

        Heartbeat ham buni `should_stop` orqali aytadi, lekin keyingi
        tsiklda (30 s gacha). Chetlashtirilgan talabgor shuncha vaqt
        test ustida ishlab turishi mumkin emas.
        """
        log.warning("Proktor sessiyani to'xtatdi: %s", reason or "-")
        self._warning_dialog().show_warning(
            reason or "Sessiya proktor tomonidan to'xtatildi", 4, timeout_s=0
        )
        self.stop()
        self.session_lost.emit("terminated")

    def _extend_capture(self, minutes: int) -> None:
        """
        Qo'shimcha vaqt berilganda dalil oynasi ham uzayadi.

        Aks holda proktor 30 daqiqa qo'shib bergan bo'lardi-yu,
        o'sha 30 daqiqa yozuvsiz o'tardi - ya'ni aynan
        "nima uchun qo'shimcha vaqt berildi?" degan savol
        tug'ilgan oraliqda dalil bo'lmasdi.
        """
        minutes = int(minutes or 0)
        if minutes <= 0 or not self._capture_deadline.isActive():
            return
        remaining = self._capture_deadline.remainingTime()
        self._capture_deadline.start(max(0, remaining) + minutes * 60 * 1000)
        log.info("Dalil oynasi %s daqiqaga uzaytirildi", minutes)

    def _on_proctor_resume(self, overtime_minutes: int) -> None:
        if self._warning is not None:
            self._warning.dismiss()
        self._extend_capture(overtime_minutes)
        self.message.show_message(
            "Imtihon davom ettirildi (+{} daqiqa)".format(overtime_minutes)
            if overtime_minutes
            else "Imtihon davom ettirildi",
            "success",
        )

    def _on_blocked_host(self, host: str) -> None:
        # Interceptor boshqa thread'dan chaqiriladi - bu yerda faqat
        # buferga yozamiz, UI'ga tegmaymiz.
        self._monitor.push_event("navigation_blocked", severity=2, payload={"host": host})

    def _on_download_requested(self, item) -> None:
        item.cancel()
        self._monitor.push_event("client_anomaly", severity=2, payload={"kind": "download"})

    # ------------------------------------------------------------------
    # Yakunlash
    # ------------------------------------------------------------------
    def _on_technical_problem(self) -> None:
        """
        Muammo turi va tavsifi — MD3 dialogida.

        Ilgari bu yerda `QInputDialog` turardi: u tizim uslubida
        chizilar (kiosk oynasining ustida begona kulrang oyna) va
        turni umuman so'ramasdi — client har doim `other` yuborardi.
        """
        from PyQt6.QtWidgets import QDialog

        from ui.dialogs.technical_problem_dialog import TechnicalProblemDialog

        # Ota — OYNA, sahifa emas: dialog ekran markazida ochilishi
        # va butun dasturni modal qilib qulflashi kerak.
        dialog = TechnicalProblemDialog(self.window())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        worker = ApiWorker(
            self._repo.report_technical_problem,
            kind=dialog.kind,
            description=dialog.description,
            parent=self,
        )
        worker.succeeded.connect(
            lambda _: self.message.show_message("Muammo qayd etildi", "success")
        )
        worker.failed.connect(lambda message, code: self.message.show_message(message, "error"))
        self._workers.run(worker)

    def _on_finish_clicked(self) -> None:
        candidate = self._state.candidate
        device = self._state.device
        # Ota — OYNA: dialog ekran markazida ochiladi va butun dasturni
        # modal qiladi (`_on_technical_problem` dagi bilan bir xil).
        dialog = FinishDialog(
            self.window(),
            candidate_name=candidate.display_name if candidate else "",
            # Ism bo'lmasa `display_name` JSHSHIR'ning o'zi — ikki marta
            # yozilmaydi.
            masked_pinfl=(
                candidate.masked_pinfl if candidate and candidate.full_name else ""
            ),
            seat=device.computer_label or device.inventory_code,
            elapsed_s=(
                time.monotonic() - self._opened_at if self._opened_at is not None else None
            ),
        )
        if dialog.exec() != FinishDialog.DialogCode.Accepted:
            return
        # `completed` FAQAT SHU YERDA: talabgor testni o'zi yakunladi va
        # server kompyuter bronini keyingi talabgor uchun bo'shatadi.
        # Dasturdan chiqish (`finish_on_exit`) joyni band qoldiradi.
        self.finish(reason="Operator yakunladi", completed=True)

    def finish(self, *, reason: str = "", completed: bool = False) -> None:
        """
        Imtihonni yakunlaydi.

        DALIL YIG'ISH YAKUNDAN OLDIN TO'XTAYDI va yozuv manzili
        `session/finish/` dan OLDIN, u bilan bitta fon chaqiruvida
        yuboriladi. Ilgari yozuv `stop()` da, ya'ni server sessiyani
        yopgandan KEYIN qayd etilardi: `client/recordings/` sessiya
        tokenini talab qiladi va u yakunda bekor bo'ladi - so'rov 404
        (`session_not_found`) olar, fayl mashinada qolar, panelda esa
        «Mashinadagi yozuvlar» doim bo'sh turardi. Ikki alohida fon
        chaqiruvi ham yetmasdi: ularning tartibi kafolatlanmagan.
        """
        self._exam_open = False
        self.overlay.start("Yakunlanmoqda...")
        recording = self._stop_capture(register=False)
        fields = self._recording_fields(recording) if recording is not None else None
        worker = ApiWorker(
            self._finish_with_recording, fields, reason, None, completed, parent=self
        )
        worker.succeeded.connect(
            lambda result: self._after_finish(result if isinstance(result, dict) else {})
        )
        # Server javob bermasa ham client oqimi to'xtaydi: sessiyani
        # `close_stale_sessions` baribir yopadi (heartbeat kelmaydi).
        # Joy esa bo'shamaydi - operator buni bilishi kerak.
        worker.failed.connect(
            lambda message, code: self._after_finish({"error": message or "Server javob bermadi"})
        )
        self._workers.run(worker)

    @property
    def has_open_exam(self) -> bool:
        """Test platformasi ochilgan va sessiya hali yakunlanmagan."""
        return self._exam_open

    def finish_on_exit(self, reason: str) -> Optional[ApiWorker]:
        """
        Dasturdan chiqishda OCHIQ imtihonni serverda yakunlaydi.

        Ilgari chiqish faqat mahalliy tozalash qilardi (`stop()`):
        token unutilar, sessiya esa serverda `in_progress` bo'lib
        qolar va uni `close_stale_sessions` ~15 daqiqadan keyin
        yig'ardi. Shu vaqt ichida talabgor boshqa mashinada qayta
        kira olmasdi, proktor esa "faol" sessiyani ko'rib turardi -
        holbuki mashinada hech kim yo'q.

        "Imtihonni yakunlash" bilan BIR XIL yo'l (`_finish_with_recording`):
        avval ekran yozuvi manzili, keyin yakun. Farqi ikkita:
        tasdiq so'ralmaydi (chiqish dialogi oqibatni allaqachon
        aytgan) va har so'rov QISQA timeout bilan - server javob
        bermasa operator yarim daqiqa yopilmayotgan oynani kutmasligi
        kerak. Bu holda sessiyani baribir `close_stale_sessions` yopadi.

        Qaytadi: ishga tushgan worker (chaqiruvchi uni chegaralangan
        vaqt kutadi) yoki `None` - yakunlanadigan narsa yo'q.
        """
        if not self._exam_open:
            return None
        self._exam_open = False
        log.info("Dasturdan chiqilmoqda - ochiq sessiya yakunlanadi (%s)", reason)
        recording = self._stop_capture(register=False)
        fields = self._recording_fields(recording) if recording is not None else None
        worker = ApiWorker(
            self._finish_with_recording, fields, reason, _EXIT_REQUEST_TIMEOUT_S, parent=self
        )
        worker.succeeded.connect(lambda _: log.info("Sessiya chiqishda yakunlandi"))
        worker.failed.connect(
            lambda message, code: log.warning(
                "Chiqishda sessiya yakunlanmadi (%s): %s - uni server yopadi",
                code or "-", message,
            )
        )
        self._workers.run(worker)
        return worker

    def _finish_with_recording(self, fields: Optional[dict], reason: str,
                               timeout: Optional[float] = None, completed: bool = False):
        """FON THREAD'IDA: avval yozuv manzili, keyin yakun."""
        if fields is not None:
            try:
                self._repo.register_recording(**fields, timeout=timeout)
            except Exception as exc:
                # Yakunni TO'SMAYDI: fayl baribir mashinada qoladi va
                # u sessiya papkasida (`<sessiya>_<jshshir>_<mac>/`)
                # topiladi - qayd faqat proktor uni paneldan topishi
                # uchun.
                log.warning(
                    "Ekran yozuvi qayd etilmadi: %s - fayl mashinada qoldi (%s)",
                    exc, fields.get("local_path", ""),
                )
        return self._repo.finish_session(reason=reason, completed=completed, timeout=timeout)

    def _after_finish(self, result: dict) -> None:
        self.overlay.stop()
        self.stop()
        self.session_finished.emit(result)

    def _on_session_lost(self, reason: str) -> None:
        self.stop()
        self.session_lost.emit(reason)

    # ------------------------------------------------------------------
    def stop(self) -> None:
        """Nazoratni to'xtatadi va WebView'ni tozalaydi."""
        self._exam_open = False
        self._notify_proctoring_stop()
        self._face_timer.stop()
        # Kanal BIRINCHI yopiladi: aks holda sessiya yakunlangach
        # kelgan buyruq allaqachon to'xtagan sahifani qo'zg'atadi.
        self._channel.stop()
        # Observer kuzatuvchidan OLDIN olib tashlanadi: hook thread'i
        # to'xtagan obyektga hodisa yuborib qolmasin.
        lockdown.set_observer(None)
        self._watcher.stop()
        # Skrinshot xizmati sessiya tokeni bekor qilinishidan OLDIN
        # to'xtatiladi: u yakunda qolgan kadrlarni va commit'larni
        # yuborishga urinadi, tokensiz esa ular 401 oladi. Ekran
        # yozuvi ham shu yerda yakunlanadi va uning manzili ham
        # tokensiz yuborilmasdi.
        self._stop_capture()
        # AI kuzatuv MONITORDAN OLDIN to'xtaydi: u yakunda ochiq
        # hodisalarni yopadi va ular buferga tushishi kerak.
        # Monitordan keyin to'xtatilsa, "telefon ko'rindi" yozuvi
        # davomiyliksiz qolardi.
        self._supervisor.stop()
        self._monitor.stop()
        # Arxiv konteksti TOZALANADI: keyingi talabgorning kadrlari
        # oldingisining papkasiga tushib qolmasligi kerak.
        local_archive.clear_context()
        # Kuzatuv javobi hali kelmagan bo'lsa (masalan, shu paytda
        # hisobdan chiqildi), kamera "kutilayotgan" holatda turibdi
        # va u ham to'xtatilishi kerak.
        self._release_pending_camera()

        if self._camera is not None:
            for signal, slot in (
                (self._camera.frame_ready, self._on_camera_frame),
                (self._camera.face_result, self._on_face_result),
                (self._camera.camera_error, self._on_camera_error),
            ):
                try:
                    signal.disconnect(slot)
                except TypeError:
                    # Ulanmagan signal - kamera bu sessiyada
                    # biriktirilmagan bo'lishi mumkin.
                    pass
            retire_camera(self._camera)
            self._camera = None

        # Sahifani bo'sh holatga o'tkazamiz: aks holda tugagan sessiya
        # ekranda ko'rinib turadi va keyingi talabgor uni ko'radi.
        self.web_view.setUrl(QUrl("about:blank"))
        self._last_embedding = None
        self._last_faces = 0
        # Kadr havolasi ham bo'shatiladi: keyingi talabgorning
        # sessiyasida oldingisining rasmi dalil bo'lib ketmasligi kerak.
        self._last_frame = None
        self._last_frame_at = 0.0
        self._face_checks = 0
        self._passed_since_last = 0

        from services.api_client import ApiClient

        ApiClient().set_session_token(None)

    def _notify_proctoring_stop(self) -> None:
        """
        Kuzatuv holatini serverda yakunlaydi.

        BEST-EFFORT va sessiya tokeni hali bekor qilinmagan paytda
        yuboriladi (`stop()` ning boshida). Javob kutilmaydi:
        server holatni `session/finish/` da ham, yakunlash
        vazifasida ham baribir yopadi - bu chaqiruv faqat uni
        ERTAROQ va aniqroq qiladi.
        """
        if self._pending_access is not None:
            # Kuzatuv umuman boshlanmagan (start rad etilgan).
            return
        session = self._state.session
        if session is None or not session.token:
            return
        worker = ApiWorker(self._repo.proctoring_stop, reason="client stop", parent=self)
        worker.failed.connect(
            lambda message, code: log.info("Kuzatuvni yakunlash: %s", message)
        )
        self._workers.run(worker)

    def shutdown(self) -> None:
        self.stop()
        self._screenshots.shutdown()
        self._workers.wait_all()
