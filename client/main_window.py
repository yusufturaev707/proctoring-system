"""
Asosiy oyna - sahifalar orasidagi navigatsiya va umumiy hayot sikli.

Sahifalar bir-birini BILMAYDI: har biri signal chiqaradi, MainWindow
esa holatni yangilab keyingisini ochadi. Shu tufayli oqimni o'zgartirish
(masalan yangi bosqich qo'shish) faqat shu faylga tegadi.

Oqim tarmoq tekshiruvidan (preflight) BOSHLANADI: kompyuter ruxsat
etilgan imtihon markazidan ulanmayotgan bo'lsa, login formasi umuman
ko'rsatilmaydi. Bu qulaylik to'sig'i, himoya emas - haqiqiy tekshiruv
har bir client so'rovida serverda ishlaydi.

Sahifalar `QStackedWidget` da, lekin login'dan keyingilari LAZY
yuklanadi: birinchi ekran darhol ochilishi kerak, qolganlari esa
o'sha paytda kerak emas.

KIOSK REJIMI (`KIOSK_MODE`) uchta narsani birga yoqadi va ular
bir-birisiz ma'nosiz:

  * oyna ramkasiz, doim ustda va to'liq ekranda - "yonidan chiqib
    ketish" mumkin emas;
  * tezkor tugmalar bloklanadi (`services/lockdown.py`) - siyosat
    serverdan keladi va login'dan OLDIN qo'llanadi;
  * `closeEvent` ruxsatsiz yopilishni RAD ETADI - Alt+F4 bloklangan
    bo'lsa ham, dasturni tashqaridan yopish signali kelishi mumkin.

Uchinchisi eng muhimi: klaviatura bloklash - to'siq, `closeEvent` esa
qoida. Birinchisi chetlab o'tilishi mumkin, ikkinchisi yo'q.
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import QEventLoop, Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
)

from config import APP_NAME, BLOCKED_HOTKEYS, FULLSCREEN, KIOSK_MODE
from services.api_client import ApiClient
from services.app_state import AppState
from services.auth_service import AuthService
from services import system_info
from services.camera_worker import await_retired_cameras
from services.face_engine import FaceEngineLoader
from services import runtime_settings
from services.lockdown import lockdown, resolve_hotkeys
from services.repositories import ProctoringRepository
from services.workers import ApiWorker, WorkerHolder
from ui.dialogs.exit_dialog import ExitDialog
from ui.widgets.language_bar import LanguageBar
from ui.pages.login_page import LoginPage
from ui.pages.preflight_page import PreflightPage

log = logging.getLogger(__name__)

#: Suzuvchi elementlarning ekran chetidan masofasi (px).
#:
#: Imtihon oynasidagi panel bilan AYNAN bir xil
#: (`exam_webview_page._BAR_MARGIN`): ikkala burchakdagi element
#: bir chiziqda turgani ko'zga tartibli ko'rinadi.
_FLOATING_MARGIN = 18


class MainWindow(QMainWindow):
    """Oqim: preflight -> login -> imtihon -> talabgor -> FaceID -> WebView."""

    PAGE_PREFLIGHT = 0
    PAGE_LOGIN = 1
    PAGE_EXAM = 2
    PAGE_CANDIDATE = 3
    PAGE_FACEID = 4
    PAGE_WEBVIEW = 5

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1180, 760)

        # Kiosk oyna bayroqlari KONSTRUKTORDA qo'yiladi: `setWindowFlags`
        # ko'rsatilgan oynada uni qayta yaratadi (Windows'da ko'z
        # qisishi ko'rinadi va fokus yo'qoladi).
        if KIOSK_MODE:
            self.setWindowFlags(
                self.windowFlags()
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
            )

        #: Chiqishga ruxsat berildimi (parol tekshiruvidan o'tdimi).
        self._exit_allowed = not KIOSK_MODE
        self._exit_dialog_open = False
        #: Login sahifasiga yetib borildimi.
        #:
        #: Chiqish qoidasi shu chegarada o'zgaradi: preflight ekranida
        #: parol so'ralmaydi (u yerda hali na sessiya, na talabgor bor -
        #: mashinani yopish oddiy amal), login sahifasidan boshlab esa
        #: parol MAJBURIY.
        self._passed_preflight = not KIOSK_MODE
        #: Yopilish boshlandi - takroriy `closeEvent` ni to'sish uchun.
        self._closing = False
        # OS seansi yakunlanganda (Windows o'chirilishi, hisobdan
        # chiqish) Qt `closeEvent` ni kafolatlamaydi - kiosk rejimida
        # u baribir rad etilardi. `aboutToQuit` esa har qanday chiqishda
        # keladi va ochiq imtihon shu yerda ham yakunlanadi.
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._on_about_to_quit)

        self._state = AppState()
        self._auth = AuthService(self._state)
        self._auth.auth_expired.connect(self._on_auth_expired)
        self._repo = ProctoringRepository()

        # "Client ishlab turibdi" signali. Login'dan keyin boshlanadi,
        # chiqishda to'xtaydi (`_on_login_success` / `_on_logout`).
        #
        # OYNA DARAJASIDA, sahifada emas: signal butun oqim davomida,
        # sahifadan qat'i nazar ketishi kerak - operator imtihon
        # tanlash ekranida yarim soat turishi ham normal holat.
        self._presence_timer = QTimer(self)
        self._presence_timer.timeout.connect(self._send_presence)
        # Worker'lar HOLDER'da: referenssiz `QThread` yig'ilib
        # ketsa dastur "Destroyed while thread is still running"
        # bilan qulaydi (`services/workers.py`).
        self._workers = WorkerHolder()
        self._presence_busy = False

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        # addWidget tartibi PAGE_* indekslariga MOS bo'lishi shart.
        self._preflight_page = PreflightPage()
        self._preflight_page.passed.connect(self._on_preflight_passed)
        self._preflight_page.exit_requested.connect(self.request_exit)
        self._stack.addWidget(self._preflight_page)

        self._login_page = LoginPage(self._auth)
        self._login_page.login_success.connect(self._on_login_success)
        self._stack.addWidget(self._login_page)

        self._exam_page = None
        self._candidate_page = None
        self._faceid_page = None
        self._webview_page = None

        # KLAVIATURA TILI - BARCHA SAHIFALARDA.
        #
        # Vidjet sahifalarga emas, OYNAGA qo'yiladi va u
        # `QStackedWidget` ustida suzadi. Har sahifaga alohida
        # qo'shish oltita nusxa degani bo'lardi va ular albatta
        # ajralib ketardi (biri boshqa joyda, biri boshqa
        # o'lchamda); bu yerda esa tanlov oqimning qaysi
        # bosqichida bo'lishidan qat'i nazar bir xil joyda turadi.
        #
        # Nima uchun umuman kerak: kiosk rejimida vazifalar paneli
        # yashiringan va `alt+shift` server ro'yxati bo'yicha
        # bloklangan bo'lishi mumkin - o'shanda tilni almashtirishning
        # boshqa yo'li qolmaydi (`services/keyboard_layout.py`).
        self._language_bar = LanguageBar(self)
        self._language_bar.raise_()
        # Sahifa almashganda panel YANGI sahifaning ustiga
        # ko'tariladi: `QStackedWidget` joriy vidjetni ko'rsatganda
        # u z-tartibida tepaga chiqadi va panel uning ostida qolib
        # ketardi.
        self._stack.currentChanged.connect(lambda _index: self._place_language_bar())

        # Public IP fon rejimida oldindan olinadi. Bu YAGONA tashqi
        # tarmoq so'rovi; login oqimida sinxron chaqirilsa, sekin
        # internetda operator har kirishda bir necha soniya kutardi.
        system_info.public_ip_resolver.prefetch()

        # Apparat ham SHU YERDA boshlanadi va shu sababdan: aniqlash
        # `nvidia-smi` ni chaqiradi (~200-800 ms) va natija ikki
        # joyda kerak - handshake (login paytida) va kuzatuv
        # boshlanishi. Login oqimida sinxron chaqirilsa, operator
        # har kirishda o'sha vaqtni kutardi.
        #
        # Xato yutiladi: AI qatlami bo'lmasa ham imtihon oqimi
        # to'liq ishlashi kerak.
        try:
            from proctoring.hardware import hardware_probe

            hardware_probe.prefetch()
        except Exception:
            log.debug("Apparat aniqlash boshlanmadi", exc_info=True)

        # Model login formasi bilan PARALLEL yuklanadi - operator
        # login/parol yozguncha u odatda tayyor bo'ladi.
        self._model_loader = FaceEngineLoader()
        self._model_loader.progress.connect(
            lambda text: self._login_page.set_model_status(text)
        )
        self._model_loader.finished_loading.connect(self._on_model_loaded)
        self._model_loader.start()

    # ------------------------------------------------------------------
    # Sahifalarni kech yuklash
    # ------------------------------------------------------------------
    def _ensure_pages(self) -> None:
        if self._exam_page is not None:
            return

        from ui.pages.candidate_page import CandidatePage
        from ui.pages.exam_select_page import ExamSelectPage
        from ui.pages.exam_webview_page import ExamWebViewPage
        from ui.pages.faceid_page import FaceIDPage

        # addWidget tartibi PAGE_* indekslariga MOS bo'lishi shart.
        self._exam_page = ExamSelectPage(self._state, self._repo, self._auth)
        self._exam_page.exam_selected.connect(self._on_exam_selected)
        self._exam_page.logout_requested.connect(self._on_logout)
        self._stack.addWidget(self._exam_page)

        self._candidate_page = CandidatePage(self._state, self._repo)
        self._candidate_page.candidate_ready.connect(self._on_candidate_ready)
        self._candidate_page.back_requested.connect(self._go_to_exam)
        self._candidate_page.logout_requested.connect(self._on_logout)
        self._stack.addWidget(self._candidate_page)

        self._faceid_page = FaceIDPage(self._state, self._repo)
        self._faceid_page.access_granted.connect(self._on_access_granted)
        self._faceid_page.back_requested.connect(self._go_to_candidate)
        self._faceid_page.camera_check_requested.connect(
            lambda: self._go_to_exam(hold_session=True)
        )
        self._faceid_page.logout_requested.connect(self._on_logout)
        self._stack.addWidget(self._faceid_page)

        self._webview_page = ExamWebViewPage(self._state, self._repo)
        self._webview_page.session_finished.connect(self._on_session_finished)
        self._webview_page.session_lost.connect(self._on_session_lost)
        self._webview_page.session_blocked.connect(self._on_session_blocked)
        self._stack.addWidget(self._webview_page)

    # ------------------------------------------------------------------
    # Oqim
    # ------------------------------------------------------------------
    def _on_preflight_passed(self, result) -> None:
        """
        Tarmoq tasdiqlandi - login formasi ochiladi.

        Preflight sahifasiga QAYTISH yo'li yo'q: tekshiruv ishga
        tushishda bir marta bo'ladi va uni takrorlash operatorga hech
        narsa bermaydi (IP o'zgarsa, keyingi so'rov serverda baribir
        rad etiladi).
        """
        # Qulflash login formasidan OLDIN qo'llanadi: aynan shu ekranda
        # kompyuter eng ochiq holatda turadi - operator hali kirmagan,
        # lekin mashina allaqachon talabgor oldida.
        self._apply_lockdown((result or {}).get("hotkeys") or [])
        self._passed_preflight = True
        self._login_page.set_network_info(result or {})
        self._stack.setCurrentIndex(self.PAGE_LOGIN)
        self._login_page.username_input.setFocus()

    def _on_model_loaded(self, success: bool, message: str) -> None:
        self._login_page.set_model_status(message, ready=success, failed=not success)
        self._model_loader = None
        if not success:
            log.error("Model yuklanmadi: %s", message)

    def _on_login_success(self, _staff) -> None:
        # Handshake bino uchun ALOHIDA sozlama qaytargan bo'lishi
        # mumkin (`config.hotkeys`), shuning uchun ro'yxat qayta
        # qo'llanadi. `lockdown.apply` almashtiradi, ustiga qo'shmaydi.
        self._apply_lockdown(self._state.config.get("hotkeys") or [])
        self._ensure_pages()
        self._go_to_exam()
        # Oraliqni SERVER aytadi (`network.presence_interval`): u
        # serverdagi presence TTL'iga bog'langan va imtihon profiliga
        # emas - shuning uchun handshake'dagi global profildan bir marta
        # o'qiladi. `.env` dagi `PRESENCE_PING_MS` - zaxira.
        self._presence_timer.start(
            runtime_settings.get(self._state.config, "network.presence_interval")
        )
        # Birinchi signal DARHOL: operator kirgan zahoti panelda
        # mashina "online" bo'lib ko'rinishi kerak, keyingi
        # signalgacha kutish (45 s) esa "kirdi, lekin ko'rinmadi"
        # degan holatni yaratardi.
        self._send_presence()

    def _send_presence(self) -> None:
        """
        Serverga "tirikman" deydi. XATO YUTILADI.

        Signal FON thread'ida: tarmoq sekin bo'lsa UI thread'da
        so'rov oynani muzlatib qo'yardi va operator buni "dastur
        osilib qoldi" deb tushunardi.

        Javob ham, xatosi ham ekranga chiqmaydi: bu diagnostika
        signali, uning muvaffaqiyatsizligi operatorning ishiga
        ta'sir qilmaydi (haqiqiy uzilishni sessiya heartbeat'i
        ko'rsatadi).
        """
        if self._auth.staff is None or self._presence_busy:
            # Oldingi signal hali ketmagan: tarmoq sekin bo'lsa
            # navbat yig'ilib, har bir signal keyingisini kutib
            # turadigan zanjir hosil bo'lardi.
            return

        in_exam = self._stack.currentIndex() == self.PAGE_WEBVIEW
        self._presence_busy = True
        worker = ApiWorker(self._repo.presence, in_exam=in_exam)
        worker.succeeded.connect(lambda _payload: self._presence_done())
        worker.failed.connect(lambda message, code: self._presence_done(message, code))
        self._workers.run(worker)

    def _presence_done(self, message: str = "", code: str = "") -> None:
        self._presence_busy = False
        if message:
            log.debug("Presence yuborilmadi (%s): %s", code or "-", message)

    def _apply_lockdown(self, hotkeys: Optional[list]) -> None:
        """
        Server ro'yxatini qo'llaydi; BO'SH bo'lsa `.env` standarti qoladi.

        Qoida va uning sababi `lockdown.resolve_hotkeys` da. Bu yerda
        faqat bitta narsa muhim: har chaqiruv TO'LIQ ro'yxatni beradi
        (`lockdown.apply` almashtiradi), ya'ni server bo'sh ro'yxat
        bergan bosqichda standart QAYTA qo'llanadi - oldingi bosqichning
        server ro'yxati "yopishib" qolmaydi.
        """
        if not KIOSK_MODE:
            log.info("Kiosk rejimi o'chirilgan - tugmalar bloklanmaydi")
            return
        hotkeys = resolve_hotkeys(hotkeys, BLOCKED_HOTKEYS)
        blocked = lockdown.apply(hotkeys)
        if hotkeys and not blocked:
            # Bu jimgina o'tib ketmasligi kerak: siyosat bor, lekin u
            # qo'llanmagan - mashina himoyasiz deb hisoblanadi.
            log.error(
                "Tezkor tugmalar bloklanmadi (siyosatda %s ta bor). "
                "Kompyuter qulflanmagan holatda ishlayapti.", len(hotkeys)
            )

    def _go_to_exam(self, *, hold_session: bool = False) -> None:
        """
        Imtihon tanlash (va kamera tekshiruvi) sahifasi.

        `hold_session` - kuzatuv kamera tekshiruvi tufayli rad etilgan
        va operator kamerani tekshirishga ketdi. Talabgor oqimi va
        ochiq sessiya SAQLANADI: `_on_exam_selected` o'sha imtihon
        tanlansa FaceID sahifasiga qaytaradi va imtihon qayta ochiladi.
        Tozalansa, sessiya serverda ochiq qolar, talabgor esa qulf
        (`lock_candidate`) tufayli ~15 daqiqa qayta kira olmasdi.
        """
        # FaceID sahifasidan qaytilsa kamera ochiq qolmasligi kerak.
        if self._faceid_page is not None:
            self._faceid_page.cleanup()
        if not hold_session:
            self._state.reset_flow()
        self._exam_page.refresh()
        self._stack.setCurrentIndex(self.PAGE_EXAM)

    def _on_exam_selected(self, _exam) -> None:
        # Imtihon profili endi `AppState.config` da (sahifa uni
        # "Davom etish" bosilganda yukladi). Tezkor tugmalar ro'yxati
        # profilga bog'liq, shuning uchun QULFLASH QAYTA QO'LLANADI.
        #
        # Usiz jimgina nomuvofiqlik qolardi: dastur global profil
        # bo'yicha bloklangan tugmalar bilan ishlar, server esa
        # imtihon profilini kutardi - masalan chet tili imtihonida
        # taqiqlangan kombinatsiya ochiq qolardi.
        #
        # `lockdown.apply` almashtiradi, ustiga qo'shmaydi.
        self._apply_lockdown(self._state.config.get("hotkeys") or [])
        held = self._state.session
        if held is not None and self._state.candidate is not None:
            if held.exam_id == getattr(_exam, "id", None):
                # Kamera tekshiruvidan qaytildi (`_go_to_exam(hold_session=True)`).
                # Tekshiruv sahifasining preview'i kamerani BAND qilib
                # turadi - FaceID uni ochishidan oldin bo'shatiladi
                # (`_go_to_candidate` dagi bilan bir xil sabab).
                self._exam_page.stop_preview()
                self._stack.setCurrentIndex(self.PAGE_FACEID)
                self._faceid_page.resume_start()
                return
            # Boshqa imtihon tanlandi - ochiq sessiya endi hech kimga
            # kerak emas va u serverda yopiladi (bron saqlanadi:
            # `completed` yo'q).
            self._close_held_session()
        self._go_to_candidate()

    def _close_held_session(self) -> None:
        log.info("Ochiq sessiya yopilmoqda: operator boshqa imtihonni tanladi")
        worker = ApiWorker(
            self._repo.finish_session, reason="Imtihon boshlanmadi (imtihon almashtirildi)"
        )
        worker.failed.connect(
            lambda message, code: log.warning("Sessiya yopilmadi (%s): %s", code or "-", message)
        )
        # Token so'rov FON thread'ida yig'ilganda o'qiladi - shuning
        # uchun u javobdan KEYIN tozalanadi, hozir emas.
        worker.finished.connect(lambda: ApiClient().set_session_token(None))
        self._workers.run(worker)
        self._state.reset_flow()

    def _go_to_candidate(self) -> None:
        if self._faceid_page is not None:
            self._faceid_page.cleanup()
        # Imtihon sahifasidagi oldindan ko'rish kamerani BAND qilib
        # turadi. Uni bo'shatmasdan FaceID sahifasiga o'tsak, u
        # o'sha qurilmani ocholmaydi ("Kamera ochilmadi (indeks 0)") -
        # Windows'da kamera bir vaqtda bitta jarayonga beriladi.
        if self._exam_page is not None:
            self._exam_page.stop_preview()
        self._candidate_page.refresh()
        self._stack.setCurrentIndex(self.PAGE_CANDIDATE)

    def _on_candidate_ready(self, _candidate) -> None:
        self._faceid_page.start()
        self._stack.setCurrentIndex(self.PAGE_FACEID)

    def _on_access_granted(self, access: dict) -> None:
        # Kamera FaceID sahifasidan WebView sahifasiga UZATILADI: uni
        # yopib qayta ochish Windows'da bir necha soniya oladi va shu
        # vaqt ichida talabgor kuzatuvsiz qoladi.
        camera = self._faceid_page.take_camera()
        self._webview_page.start(access, camera=camera)
        self._stack.setCurrentIndex(self.PAGE_WEBVIEW)

    def _on_session_finished(self, result: dict) -> None:
        self._state.reset_flow()
        self._go_to_candidate()
        # Xabar sahifa TOZALANGANDAN keyin (`refresh` xabar qatorini
        # tozalaydi). Operator keyingi talabgorni shu yerda kutadi va
        # "stol bo'shadimi?" degan savolga javob aynan shu yerda kerak.
        self._candidate_page.show_finish_notice(result or {})

    def _on_session_blocked(self, code: str, message: str) -> None:
        """
        Kuzatuv boshlanmadi - imtihon OCHILMADI.

        Sessiya TIRIK qoladi va bu ataylab: operator kamerani
        tuzatib, FaceID sahifasidan qayta "Boshlash" ni bosishi
        mumkin. Sessiyani yopish uni qaytadan yaratishga majbur
        qilardi - talabgorni yana JSHSHIR bilan qidirish, yana yuz
        tekshiruvi, yana shaxs tasdig'i.

        Shuning uchun FaceID sahifasiga qaytamiz: u oqimdagi eng
        yaqin nuqta bo'lib, undan "Boshlash" qayta bosiladi.
        """
        log.warning("Imtihon ochilmadi (%s): %s", code or "-", message)
        QMessageBox.warning(
            self,
            "Kuzatuv boshlanmadi",
            "{}\n\nYuz tasdig'i saqlanadi — qayta tekshirish kerak emas. "
            "Kamerani tekshirib, imtihonni qayta boshlang.".format(
                message or "Sabab noma'lum"
            ),
        )
        self._go_to_faceid()

    def _go_to_faceid(self) -> None:
        """FaceID sahifasiga qaytish - kamera qaytadan ochiladi."""
        if self._faceid_page is None:
            self._go_to_candidate()
            return
        self._faceid_page.restart_matching()
        self._stack.setCurrentIndex(self.PAGE_FACEID)

    def _on_session_lost(self, reason: str) -> None:
        QMessageBox.warning(
            self,
            "Sessiya yakunlandi",
            "Sessiya serverda yakunlandi ({}). Keyingi talabgorga o'tishingiz "
            "mumkin.".format(reason or "-"),
        )
        self._state.reset_flow()
        self._go_to_candidate()

    # ------------------------------------------------------------------
    def _on_logout(self) -> None:
        if self._webview_page is not None:
            self._webview_page.stop()
        if self._faceid_page is not None:
            self._faceid_page.cleanup()
        # Signal TO'XTAYDI: chiqib ketgan mashina panelda "online"
        # bo'lib qolsa, proktor uni ishlayapti deb hisoblardi.
        # Redis kaliti TTL bilan o'zi so'nadi (~100 s).
        self._presence_timer.stop()
        self._auth.logout()
        self._login_page.reset()
        self._stack.setCurrentIndex(self.PAGE_LOGIN)

    def _on_auth_expired(self) -> None:
        """
        Refresh ham yaroqsiz.

        Bu signal fon thread'idan ham kelishi mumkin - Qt uni UI
        thread'ga o'zi marshal qiladi. Login sahifasida turgan bo'lsak
        hech narsa qilmaymiz (takroriy chaqiruv).
        """
        if self._stack.currentIndex() == self.PAGE_LOGIN:
            return
        log.info("Sessiya muddati tugadi - login sahifasiga qaytarilmoqda")
        # Xodim endi tizimda emas - "client ishlab turibdi" signali
        # ham to'xtaydi (panelda mashina TTL bo'yicha so'nadi).
        self._presence_timer.stop()
        if self._webview_page is not None:
            self._webview_page.stop()
        if self._faceid_page is not None:
            self._faceid_page.cleanup()
        self._auth.logout()
        self._login_page.reset("Sessiya muddati tugadi. Qaytadan kiring.")
        self._stack.setCurrentIndex(self.PAGE_LOGIN)

    # ------------------------------------------------------------------
    # Chiqish
    # ------------------------------------------------------------------
    def request_exit(self) -> None:
        """
        Chiqishni so'raydi - yagona ruxsat etilgan yo'l.

        Parol HAR DOIM so'raladi. Xodim tizimga kirgan bo'lsa, u o'z
        parolini kiritadi; kirmagan bo'lsa (preflight va login
        ekranlari) - viloyatning chiqish paroli. Ikkalasini ham
        server tekshiradi, client farqni bilmaydi.

        Ilgari login qilinmagan ekranlarda parol umuman so'ralmasdi va
        bu ochiq bo'shliq edi: talabgor login formasida qolgan
        mashinani yopib, ish stoliga chiqib ketishi mumkin edi.
        """
        if self._exit_dialog_open or self._closing:
            return
        if not KIOSK_MODE or not self._passed_preflight:
            # Login sahifasigacha - parolsiz. Bu bo'shliq emas: bu
            # ekranlarda dastur hali hech narsa ochmagan va yopilishi
            # bilan hech kim hech narsa yutmaydi. Parol so'rash esa
            # aksincha zarar: tarmoq tekshiruvidan o'tolmagan mashinada
            # operator kalitni ham bilmasligi mumkin va u yerda
            # osilib qolardi.
            self._exit_allowed = True
            self.close()
            return

        staff = self._auth.staff
        back = self._back_action()
        warning = ""
        if self._webview_page is not None and self._webview_page.has_open_exam:
            warning = (
                "Imtihon davom etmoqda. Chiqish talabgorning sessiyasini "
                "YAKUNLAYDI va u testga qayta kira olmaydi."
            )
        self._exit_dialog_open = True
        try:
            dialog = ExitDialog(
                self,
                staff_name=getattr(staff, "full_name", "") or getattr(staff, "username", ""),
                repo=self._repo,
                back_label=back[0] if back else "",
                warning=warning,
            )
            result = dialog.exec()
        finally:
            self._exit_dialog_open = False

        if back is not None and result == ExitDialog.BACK:
            # Dastur OCHIQ qoladi - kiosk buzilmaydi va parol
            # so'ralmaydi. Bu shunchaki navigatsiya.
            back[1]()
            return

        if result == QDialog.DialogCode.Accepted:
            self._exit_allowed = True
            self.close()

    def _back_action(self):
        """
        Joriy sahifadan "orqaga" qayerga borish mumkin.

        `(yorliq, funksiya)` yoki `None`. Ro'yxat SHU YERDA, chunki
        oqim tartibini faqat `MainWindow` biladi - sahifalar
        bir-birini bilmaydi (modul docstring'iga qarang).

        IMTIHON OYNASIDA ORQAGA YO'Q va bu ataylab. U yerda TIRIK
        sessiya bor: server tomonda token ochiq, heartbeat ketyapti,
        talabgor test ustida ishlayapti. "Orqaga" bilan undan jimgina
        chiqib ketish sessiyani yopilmagan holda qoldirardi va uni
        faqat `close_stale_sessions` 15 daqiqadan keyin yig'ib
        olardi - bu vaqt ichida talabgor boshqa mashinada qayta
        kira olmaydi. Sessiyani yakunlashning to'g'ri yo'li bitta:
        "Imtihonni yakunlash" tugmasi.

        Preflight va login ekranlarida ham `None`: u yerda orqaga
        qaytadigan joy yo'q.
        """
        index = self._stack.currentIndex()

        if index == self.PAGE_EXAM:
            # Oldingi qadam - login ekrani, ya'ni hisobdan chiqish.
            # Sarlavhadagi "Chiqish" tugmasi aynan shuni qiladi, lekin
            # operator Ctrl+Q ni bosganda u tugmani qidirmasligi kerak.
            return ("Hisobdan chiqib, login sahifasiga qaytish", self._on_logout)
        if index == self.PAGE_CANDIDATE:
            return ("Imtihon tanlashga qaytish", self._go_to_exam)
        if index == self.PAGE_FACEID:
            return ("Talabgor ma'lumotlariga qaytish", self._go_to_candidate)
        return None

    def closeEvent(self, event) -> None:
        """
        Yopilish: oyna DARHOL yo'qoladi, tozalash esa ortda qoladi.

        Ilgari bu yerda ketma-ket `wait()` chaqiruvlari turardi va ular
        UI thread'ini bloklardi: model yuklovchi uchun 30 s, har bir
        sahifa uchun 35 s. Operator "Chiqish" ni bosgach ekran muzlab
        qolardi va u dasturni "osilib qoldi" deb hisoblardi - eng yomon
        holatda quvvatdan uzardi.

        Endi tartib teskari: avval `hide()`, keyin tozalash. Operator
        uchun dastur o'sha zahoti yopiladi; thread'lar esa ko'rinmas
        holda, hodisa sikli aylanib turgan holda tugatiladi.

        Kutish BARIBIR kerak: ishlab turgan QThread yo'q qilinsa, Qt
        "Destroyed while thread is still running" bilan dasturni
        qulatadi. Lekin endi u ko'rinmaydi va chegaralangan.

        Kiosk rejimida ruxsatsiz yopilish RAD ETILADI. Alt+F4 hook
        bilan bloklangan bo'lsa ham, yopish signali boshqa yo'ldan
        kelishi mumkin (vazifalar paneli, `WM_CLOSE`, Qt'ning o'zi) -
        u yerda hook umuman qatnashmaydi. Shuning uchun bu tekshiruv
        klaviatura blokidan MUSTAQIL ishlaydi.
        """
        if not self._exit_allowed:
            event.ignore()
            log.info("Yopish so'raldi - ruxsat tekshirilmoqda")
            # Dialog SHU YERDA ochilmaydi: `closeEvent` ichidan modal
            # oyna ochish va undan `close()` chaqirish - ichma-ich
            # yopilish. Qt bunda tashqi hodisani allaqachon rad etgan
            # bo'ladi va ichkarisi ishlamaydi. Navbatga qo'yamiz, ya'ni
            # dialog joriy hodisa tugagach ochiladi.
            QTimer.singleShot(0, self.request_exit)
            return

        if self._closing:
            # Tozalash allaqachon ketyapti - ikkinchi marta boshlamaymiz.
            event.accept()
            return
        self._closing = True

        # Operator uchun dastur SHU YERDA yopiladi.
        self.hide()
        self._pump()

        self._shutdown()
        event.accept()

    # ------------------------------------------------------------------
    @staticmethod
    def _pump() -> None:
        """
        Hodisa navbatini aylantiradi.

        Kutish orasida chaqiriladi: shu tufayli oyna haqiqatan ham
        yo'qoladi va OS dasturni "javob bermayapti" deb belgilamaydi
        (Windows buni 5 soniyadan keyin qiladi va oynani oqartirib
        qo'yadi - aynan operator ko'rmasligi kerak bo'lgan manzara).
        """
        app = QApplication.instance()
        if app is not None:
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)

    def _await(self, thread, *, total_ms: int, label: str) -> None:
        """
        Thread tugashini KICHIK bo'laklarda kutadi.

        Bitta uzun `wait()` o'rniga bo'laklar - chunki har bo'lak
        orasida hodisa navbati aylanadi. Belgilangan vaqtda tugamasa
        `terminate()`: jarayon baribir yakunlanyapti, ishlab turgan
        thread bilan chiqish esa qulash demak.
        """
        if thread is None or not thread.isRunning():
            return
        slice_ms = 250
        for _ in range(max(1, total_ms // slice_ms)):
            if thread.wait(slice_ms):
                return
            self._pump()
        log.warning("%s tugamadi (%s ms) - terminate", label, total_ms)
        thread.terminate()
        thread.wait(1000)

    def _on_about_to_quit(self) -> None:
        """Ilova tugayapti - `closeEvent` o'tmagan bo'lsa, tozalash shu yerda."""
        if self._closing:
            return
        self._closing = True
        log.info("Ilova yakunlanmoqda (OS seansi) - tozalash")
        self._shutdown()

    def _shutdown(self) -> None:
        """Barcha fon ishlarini tugatadi. Oyna allaqachon yashiringan."""
        # Signal taymeri BIRINCHI to'xtaydi: yopilish paytida yangi
        # so'rov ochish tozalashni cho'zardi.
        self._presence_timer.stop()

        # OCHIQ IMTIHON undan keyin DARHOL yakunlanadi - sessiya tokeni
        # va tarmoq mijozi hali tirik. Sahifalarni tozalash (`stop()`)
        # faqat mahalliy ish: token unutiladi, sessiya esa serverda
        # `in_progress` bo'lib qolardi va uni `close_stale_sessions`
        # ~15 daqiqadan keyin yig'ardi. Kutish CHEGARALANGAN (ikki
        # so'rov x `_EXIT_REQUEST_TIMEOUT_S`): server javob bermasa
        # dastur baribir yopiladi.
        if self._webview_page is not None:
            worker = self._webview_page.finish_on_exit("Dasturdan chiqildi (yakunlanmagan)")
            self._await(worker, total_ms=10_000, label="Sessiyani yakunlash")

        self._workers.wait_all(3_000)

        # Model yuklovchi eng uzun ishlaydi (CPU'da ~5-15 s). Uni
        # to'liq kutish shart emas: natijasi endi hech kimga kerak
        # emas, kerak bo'lgani - thread'ning tugashi.
        self._await(self._model_loader, total_ms=6000, label="Model yuklovchi")
        self._model_loader = None

        for page in (
            self._preflight_page,
            self._login_page,
            # Imtihon sahifasi ham ro'yxatda: unda endi kamera oqimi
            # va fon worker'lari bor. Ilgari u tozalanmasdi, chunki
            # sof forma edi.
            self._exam_page,
            self._candidate_page,
            self._faceid_page,
            self._webview_page,
        ):
            if page is None or not hasattr(page, "shutdown"):
                continue
            try:
                page.shutdown()
            except Exception:
                # Bitta sahifaning tozalanmagani qolganlarini
                # to'xtatmasligi kerak - aks holda kamera thread'i
                # ochiq qolib, dastur qulash bilan tugardi.
                log.exception("Sahifani tozalashda xato: %s", type(page).__name__)
            self._pump()

        # Kamera thread'i `cv2.VideoCapture` konstruktorida osilib qolgan
        # bo'lishi mumkin (kamera band). U tugamaguncha yo'q qilinmasligi
        # shart - aks holda Qt butun dasturni qulatadi.
        try:
            await_retired_cameras(5000)
        except Exception:
            log.exception("Kamera thread'larini tugatishda xato")

        # Qulflash SO'NGGI bo'lib bo'shatiladi: undan oldin tugmalar
        # ochilib qolishi mumkin emas.
        try:
            lockdown.release()
        finally:
            ApiClient().close()
        log.info("Dastur yopildi")

    # ------------------------------------------------------------------
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_language_bar()

    def _place_language_bar(self) -> None:
        """
        Til panelini pastki CHAP burchakka qo'yadi.

        `getattr` MAJBURIY: `setMinimumSize` konstruktorning
        BOSHIDA chaqiriladi va u `resizeEvent` ni qo'zg'atadi -
        o'sha paytda panel hali yaratilmagan bo'ladi.
        """
        bar = getattr(self, "_language_bar", None)
        if bar is None or not bar.isVisibleTo(self):
            return
        bar.adjustSize()
        bar.move(_FLOATING_MARGIN, self.height() - bar.height() - _FLOATING_MARGIN)
        bar.raise_()

    def show_start(self) -> None:
        # QULF OYNA KO'RINISHIDAN OLDIN va `.env` standarti bilan
        # (`BLOCKED_HOTKEYS`). Ilgari birinchi qulf preflight javobidan
        # keyin qo'yilardi: so'rov ketib-kelguncha (server javob
        # bermasa - umuman) mashina talabgor oldida Alt+Tab va Win
        # ochiq holda turardi. Server ro'yxati kelgach u buni
        # almashtiradi (`_on_preflight_passed`).
        self._apply_lockdown(None)
        if FULLSCREEN:
            self.showFullScreen()
        else:
            self.showMaximized()

        # Ctrl+Q - chiqishning KO'RINMAYDIGAN yo'li. Har sahifada
        # "Chiqish" tugmasi yo'q (masalan imtihon davomida), operator
        # esa dasturni qonuniy ravishda yopa olishi kerak. Parol
        # baribir so'raladi, ya'ni bu chetlab o'tish emas.
        self._exit_shortcut = QShortcut(QKeySequence("Ctrl+Q"), self)
        self._exit_shortcut.activated.connect(self.request_exit)

        # Tekshiruv oyna KO'RINGANDAN keyin boshlanadi: aks holda
        # birinchi kadrda bo'sh oyna turadi va operator "dastur
        # ochilmadi" deb o'ylaydi.
        self._preflight_page.start()
