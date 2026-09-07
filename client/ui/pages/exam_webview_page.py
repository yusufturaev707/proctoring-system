"""
5-SAHIFA - Xavfsiz WebView.

Tashqi test platformasi shu yerda ochiladi. Uchta qatlam bir vaqtda
ishlaydi:

  1. QULF   - domen allowlist, yangi oyna/yuklab olish/kontekst menyu
              taqiqi, off-the-record profil (kesh va cookie diskka
              yozilmaydi va keyingi talabgorga o'tmaydi).
  2. NAZORAT- heartbeat, hodisalar buferi, davriy FaceID.
  3. YAKUN  - sessiyani tugatish va keyingi talabgorga qaytish.

Token URL'ga QO'YILMAYDI: u brauzer tarixi, `Referer` header'i va nginx
access log orqali sizib chiqadi. Backend `delivery` maydonida qanday
uzatishni aytadi - `post` (form body) yoki `cookie`.
"""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urlencode, urlparse

from PyQt6.QtCore import QByteArray, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtWebEngineCore import (
    QWebEngineHttpRequest,
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
    QWebEngineUrlRequestInterceptor,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config import PERIODIC_FACE_INTERVAL_MS
from services.app_state import AppState
from services.camera_worker import CameraWorker, retire_camera
from services.monitoring import SessionMonitor
from services.repositories import ProctoringRepository
from services.screen_capture import ScreenshotService
from services.workers import ApiWorker, WorkerHolder
from ui.styles import COLORS, badge_style
from ui.widgets.indicators import BusyOverlay, MessageBar

log = logging.getLogger(__name__)


class DomainAllowlistInterceptor(QWebEngineUrlRequestInterceptor):
    """
    Faqat ruxsat etilgan domenlarga so'rov qo'yadi.

    Ro'yxat backenddan keladi (`Exam.allowed_domains`), ya'ni uni
    administrator boshqaradi va client build'ini yangilash shart emas.
    Ro'yxat bo'sh bo'lsa hech narsa bloklanmaydi - bu holat backendda
    ham "tekshiruv o'chirilgan" degani (`get_allowed_domains` site_url
    domenini qaytaradi).
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

    session_finished = pyqtSignal()
    session_lost = pyqtSignal(str)

    def __init__(self, state: AppState, repo: ProctoringRepository, parent=None) -> None:
        super().__init__(parent)
        self._state = state
        self._repo = repo
        self._workers = WorkerHolder()
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

        self._camera: Optional[CameraWorker] = None
        self._last_embedding = None
        self._interceptor: Optional[DomainAllowlistInterceptor] = None
        self._profile: Optional[QWebEngineProfile] = None

        self._face_timer = QTimer(self)
        self._face_timer.setInterval(PERIODIC_FACE_INTERVAL_MS)
        self._face_timer.timeout.connect(self._send_periodic_face)

        self._setup_ui()

    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = QWidget()
        bar.setFixedHeight(58)
        bar.setStyleSheet(
            "background-color: {}; border-bottom: 1px solid {};".format(
                COLORS["surface"], COLORS["border"]
            )
        )
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(20, 8, 20, 8)
        bar_layout.setSpacing(12)

        self.candidate_label = QLabel("-")
        self.candidate_label.setProperty("role", "value")
        bar_layout.addWidget(self.candidate_label)

        self.exam_label = QLabel("")
        self.exam_label.setProperty("role", "caption")
        bar_layout.addWidget(self.exam_label)
        bar_layout.addStretch()

        self.face_badge = QLabel("FaceID: kutilmoqda")
        self.face_badge.setStyleSheet(badge_style("muted"))
        self.face_badge.setFixedHeight(24)
        bar_layout.addWidget(self.face_badge)

        # Operator skrinshot olinayotganini KO'RISHI kerak: bu nazorat
        # ishlayotganining yagona ko'rinadigan belgisi va u ishlamay
        # qolsa, imtihon tugagandan keyin emas, o'sha payt bilinishi
        # kerak (dalilni keyin qayta yig'ib bo'lmaydi).
        self.shot_badge = QLabel("Skrinshot: -")
        self.shot_badge.setStyleSheet(badge_style("muted"))
        self.shot_badge.setFixedHeight(24)
        bar_layout.addWidget(self.shot_badge)

        self.network_badge = QLabel("Aloqa bor")
        self.network_badge.setStyleSheet(badge_style("success"))
        self.network_badge.setFixedHeight(24)
        bar_layout.addWidget(self.network_badge)

        self.problem_btn = QPushButton("Texnik muammo")
        self.problem_btn.setProperty("variant", "ghost")
        self.problem_btn.setFixedWidth(160)
        self.problem_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.problem_btn.clicked.connect(self._on_technical_problem)
        bar_layout.addWidget(self.problem_btn)

        self.finish_btn = QPushButton("Imtihonni yakunlash")
        self.finish_btn.setProperty("variant", "danger")
        self.finish_btn.setFixedWidth(200)
        self.finish_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.finish_btn.clicked.connect(self._on_finish_clicked)
        bar_layout.addWidget(self.finish_btn)

        root.addWidget(bar)

        self.message = MessageBar()
        self.message.setContentsMargins(20, 6, 20, 0)
        root.addWidget(self.message)

        self.web_view = QWebEngineView()
        self.web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        root.addWidget(self.web_view, 1)

        self.overlay = BusyOverlay(self)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.overlay.setGeometry(self.rect())

    # ------------------------------------------------------------------
    # Ishga tushirish
    # ------------------------------------------------------------------
    def start(self, access: dict, camera: Optional[CameraWorker] = None) -> None:
        candidate = self._state.candidate
        exam = self._state.selected_exam
        self.candidate_label.setText(candidate.full_name if candidate else "-")
        self.exam_label.setText(exam.name if exam else "")
        self.message.clear_message()
        # Hisoblagich HAR TALABGOR uchun noldan boshlanadi - aks holda
        # ekranda oldingi sessiyaning soni qolib, operator skrinshot
        # olinayotgan deb o'ylardi.
        self.shot_badge.setText("Skrinshot: -")
        self.shot_badge.setStyleSheet(badge_style("muted"))

        policy = access.get("webview_policy") or {}
        self._configure_profile(policy)
        self._open_platform(access)

        self._attach_camera(camera)
        self._monitor.start()
        self._face_timer.start()
        # Sozlama handshake'dan keladi: interval, sifat, kenglik va
        # dedup chegarasi imtihonga biriktirilgan profilga bog'liq.
        self._screenshots.start(self._state.config)

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
        login_url = access.get("login_url") or ""
        token = access.get("platform_session_token") or ""
        delivery = (access.get("delivery") or "post").lower()

        if not login_url:
            self.message.show_message("Test platformasi manzili berilmadi", "error")
            return

        if delivery == "cookie":
            # Cookie domen bo'yicha o'rnatiladi - platforma uni odatdagi
            # sessiya cookie'si sifatida o'qiydi.
            self._set_session_cookie(login_url, token)
            self.web_view.load(QUrl(login_url))
            return

        # `post` (standart): token so'rov TANASIDA ketadi, URL'da emas.
        request = QWebEngineHttpRequest(QUrl(login_url), QWebEngineHttpRequest.Method.Post)
        request.setHeader(
            QByteArray(b"Content-Type"),
            QByteArray(b"application/x-www-form-urlencoded"),
        )
        request.setPostData(QByteArray(urlencode({"session_token": token}).encode("utf-8")))
        self.web_view.load(request)

    def _set_session_cookie(self, login_url: str, token: str) -> None:
        from PyQt6.QtNetwork import QNetworkCookie

        host = urlparse(login_url).hostname or ""
        cookie = QNetworkCookie(QByteArray(b"session_token"), QByteArray(token.encode()))
        cookie.setDomain(host)
        cookie.setPath("/")
        cookie.setHttpOnly(True)
        cookie.setSecure(login_url.lower().startswith("https"))
        if self._profile is not None:
            self._profile.cookieStore().setCookie(cookie, QUrl(login_url))

    # ------------------------------------------------------------------
    # Nazorat
    # ------------------------------------------------------------------
    def _attach_camera(self, camera: Optional[CameraWorker]) -> None:
        """4-sahifadan kelgan kamerani davriy tekshiruvga ulaydi."""
        self._camera = camera
        if camera is not None:
            camera.face_result.connect(self._on_face_result)

    def _on_face_result(self, result: dict) -> None:
        """
        Kadr natijasi eslab qolinadi, lekin DARHOL yuborilmaydi.

        Har kadr uchun so'rov yuborish daqiqasiga ~600 so'rov degani va
        `client_ingest` chegarasini bir zumda yeb qo'yadi. Taymer esa
        daqiqada bittasini yuboradi.
        """
        if result.get("state") == "ok":
            self._last_embedding = result.get("embedding")
        elif result.get("state") == "none":
            self._last_embedding = None
            self._monitor.push_event("face_not_found", severity=2)
        elif result.get("state") == "multiple":
            self._monitor.push_event("multiple_faces", severity=3)

    def _send_periodic_face(self) -> None:
        if not self._monitor.is_active:
            return
        embedding = self._last_embedding
        if embedding is None:
            # Yuz umuman yo'q - buni hodisa sifatida yubordik, davriy
            # tekshiruvga esa "0 yuz" deb bildiramiz.
            worker = ApiWorker(self._repo.periodic_face, score=0, faces_detected=0, parent=self)
        else:
            worker = ApiWorker(
                self._repo.periodic_face,
                embedding=[float(value) for value in embedding],
                faces_detected=1,
                parent=self,
            )
        worker.succeeded.connect(self._on_periodic_result)
        worker.failed.connect(lambda message, code: log.info("Davriy FaceID: %s", message))
        self._workers.run(worker)

    def _on_periodic_result(self, result) -> None:
        data = result or {}
        if data.get("terminated"):
            self.session_lost.emit("face_failed")
            return
        # `passed` - backend `verify_periodic_face` javobidagi maydon.
        # `fail_count` ketma-ket muvaffaqiyatsizliklar soni: operatorga
        # chetlashtirishgacha qancha qolganini ko'rsatamiz.
        passed = bool(data.get("passed", True))
        fail_count = int(data.get("fail_count") or 0)
        max_fail = int(data.get("max_fail") or 0)
        if passed:
            self.face_badge.setText("FaceID: mos")
            self.face_badge.setStyleSheet(badge_style("success"))
        else:
            self.face_badge.setText("FaceID: mos emas ({}/{})".format(fail_count, max_fail))
            self.face_badge.setStyleSheet(badge_style("error"))

    def _on_network_changed(self, online: bool) -> None:
        self.network_badge.setText("Aloqa bor" if online else "Aloqa yo'q")
        self.network_badge.setStyleSheet(badge_style("success" if online else "error"))
        if not online:
            self.message.show_message(
                "Server bilan aloqa yo'q. Hodisalar buferda saqlanmoqda.", "warning"
            )
        else:
            self.message.clear_message()

    def _on_screenshot_sent(self, total: int) -> None:
        self.shot_badge.setText("Skrinshot: {}".format(total))
        self.shot_badge.setStyleSheet(badge_style("success"))

    def _on_screenshot_failed(self, message: str) -> None:
        # Xabar `MessageBar` ga CHIQARILMAYDI: u tarmoq holati uchun
        # band va skrinshot xatosi odatda o'sha uzilishning natijasi -
        # ikkita bir xil ogohlantirish operatorni chalg'itadi. Nishon
        # esa ko'rinib turadi.
        pending = self._screenshots.pending
        self.shot_badge.setText(
            "Skrinshot: navbatda {}".format(pending) if pending else "Skrinshot: xato"
        )
        self.shot_badge.setStyleSheet(badge_style("error"))
        log.info("Skrinshot xatosi: %s", message)

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
        from PyQt6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getText(self, "Texnik muammo", "Muammoni qisqacha yozing:")
        if not ok or not text.strip():
            return
        worker = ApiWorker(
            self._repo.report_technical_problem,
            kind="other",
            description=text.strip(),
            parent=self,
        )
        worker.succeeded.connect(
            lambda _: self.message.show_message("Muammo qayd etildi", "success")
        )
        worker.failed.connect(lambda message, code: self.message.show_message(message, "error"))
        self._workers.run(worker)

    def _on_finish_clicked(self) -> None:
        answer = QMessageBox.question(
            self,
            "Imtihonni yakunlash",
            "Sessiyani yakunlaysizmi? Talabgor testga qayta kira olmaydi.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.finish(reason="Operator yakunladi")

    def finish(self, *, reason: str = "") -> None:
        self.overlay.start("Yakunlanmoqda...")
        worker = ApiWorker(self._repo.finish_session, reason=reason, parent=self)
        worker.succeeded.connect(lambda _: self._after_finish())
        # Server javob bermasa ham client oqimi to'xtaydi: sessiyani
        # `close_stale_sessions` baribir yopadi (heartbeat kelmaydi).
        worker.failed.connect(lambda message, code: self._after_finish())
        self._workers.run(worker)

    def _after_finish(self) -> None:
        self.overlay.stop()
        self.stop()
        self.session_finished.emit()

    def _on_session_lost(self, reason: str) -> None:
        self.stop()
        self.session_lost.emit(reason)

    # ------------------------------------------------------------------
    def stop(self) -> None:
        """Nazoratni to'xtatadi va WebView'ni tozalaydi."""
        self._face_timer.stop()
        # Skrinshot xizmati sessiya tokeni bekor qilinishidan OLDIN
        # to'xtatiladi: u yakunda qolgan kadrlarni va commit'larni
        # yuborishga urinadi, tokensiz esa ular 401 oladi.
        self._screenshots.stop()
        self._monitor.stop()

        if self._camera is not None:
            try:
                self._camera.face_result.disconnect(self._on_face_result)
            except TypeError:
                pass
            retire_camera(self._camera)
            self._camera = None

        # Sahifani bo'sh holatga o'tkazamiz: aks holda tugagan sessiya
        # ekranda ko'rinib turadi va keyingi talabgor uni ko'radi.
        self.web_view.setUrl(QUrl("about:blank"))
        self._last_embedding = None

        from services.api_client import ApiClient

        ApiClient().set_session_token(None)

    def shutdown(self) -> None:
        self.stop()
        self._screenshots.shutdown()
        self._workers.wait_all()
