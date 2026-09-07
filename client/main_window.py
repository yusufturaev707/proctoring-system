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

from PyQt6.QtCore import QEventLoop, Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
)

from config import APP_NAME, FULLSCREEN, KIOSK_MODE
from services.api_client import ApiClient
from services.app_state import AppState
from services.auth_service import AuthService
from services import system_info
from services.camera_worker import await_retired_cameras
from services.face_engine import FaceEngineLoader
from services.lockdown import lockdown
from services.repositories import ProctoringRepository
from ui.dialogs.exit_dialog import ExitDialog
from ui.pages.login_page import LoginPage
from ui.pages.preflight_page import PreflightPage

log = logging.getLogger(__name__)


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

        self._state = AppState()
        self._auth = AuthService(self._state)
        self._auth.auth_expired.connect(self._on_auth_expired)
        self._repo = ProctoringRepository()

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

        # Public IP fon rejimida oldindan olinadi. Bu YAGONA tashqi
        # tarmoq so'rovi; login oqimida sinxron chaqirilsa, sekin
        # internetda operator har kirishda bir necha soniya kutardi.
        system_info.public_ip_resolver.prefetch()

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
        self._exam_page = ExamSelectPage(self._state)
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
        self._faceid_page.logout_requested.connect(self._on_logout)
        self._stack.addWidget(self._faceid_page)

        self._webview_page = ExamWebViewPage(self._state, self._repo)
        self._webview_page.session_finished.connect(self._on_session_finished)
        self._webview_page.session_lost.connect(self._on_session_lost)
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

    def _apply_lockdown(self, hotkeys: list) -> None:
        if not KIOSK_MODE:
            log.info("Kiosk rejimi o'chirilgan - tugmalar bloklanmaydi")
            return
        blocked = lockdown.apply(hotkeys)
        if hotkeys and not blocked:
            # Bu jimgina o'tib ketmasligi kerak: siyosat bor, lekin u
            # qo'llanmagan - mashina himoyasiz deb hisoblanadi.
            log.error(
                "Tezkor tugmalar bloklanmadi (siyosatda %s ta bor). "
                "Kompyuter qulflanmagan holatda ishlayapti.", len(hotkeys)
            )

    def _go_to_exam(self) -> None:
        # FaceID sahifasidan qaytilsa kamera ochiq qolmasligi kerak.
        if self._faceid_page is not None:
            self._faceid_page.cleanup()
        self._state.reset_flow()
        self._exam_page.refresh()
        self._stack.setCurrentIndex(self.PAGE_EXAM)

    def _on_exam_selected(self, _exam) -> None:
        self._go_to_candidate()

    def _go_to_candidate(self) -> None:
        if self._faceid_page is not None:
            self._faceid_page.cleanup()
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

    def _on_session_finished(self) -> None:
        self._state.reset_flow()
        self._go_to_candidate()

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
        self._exit_dialog_open = True
        try:
            dialog = ExitDialog(
                self,
                staff_name=getattr(staff, "full_name", "") or getattr(staff, "username", ""),
                repo=self._repo,
            )
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
        finally:
            self._exit_dialog_open = False

        if accepted:
            self._exit_allowed = True
            self.close()

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

    def _shutdown(self) -> None:
        """Barcha fon ishlarini tugatadi. Oyna allaqachon yashiringan."""
        # Model yuklovchi eng uzun ishlaydi (CPU'da ~5-15 s). Uni
        # to'liq kutish shart emas: natijasi endi hech kimga kerak
        # emas, kerak bo'lgani - thread'ning tugashi.
        self._await(self._model_loader, total_ms=6000, label="Model yuklovchi")
        self._model_loader = None

        for page in (
            self._preflight_page,
            self._login_page,
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
    def show_start(self) -> None:
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
