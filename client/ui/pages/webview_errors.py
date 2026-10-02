"""
Imtihon WebView'ining nosozliklari: aniqlash, matn va tiklash qoidasi.

`exam_webview_page.py` dan ALOHIDA, chunki uch qism sof mantiq va
testlanadi (`tests/test_webview_errors.py`):

  * `webengine_process_problem` — `QtWebEngineProcess.exe` joyidami;
  * `describe_load_error` — Chromium xato kodi -> operator tilidagi matn
    va "avtomatik qayta urinishga arziydimi";
  * `CrashGuard` — renderer qulashlarini sanaydi va "qayta-qayta
    qulayapti" holatini (antivirus, buzilgan o'rnatish) ajratadi.

Ekrandagi panel (`WebErrorPanel`) ham shu yerda: u brauzer USTIDA
turadi, suzuvchi panel esa undan ham yuqorida — sayt ochilmasa ham
«Imtihonni yakunlash» tugmasi qo'l ostida qolishi shart.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections import deque
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QLabel, QPushButton, QVBoxLayout

from services import net_policy
from ui.styles import COLORS, primary_button_style
from ui.widgets.indicators import StateBadge

log = logging.getLogger(__name__)

_PROCESS_EXE = "QtWebEngineProcess.exe" if sys.platform == "win32" else "QtWebEngineProcess"

#: Renderer shu oyna ichida shuncha marta qulasa — avtomatik qayta
#: yuklash TO'XTAYDI (qo'lda tugma qoladi). Sabab odatda doimiy:
#: antivirus jarayonni o'ldiryapti yoki o'rnatish buzilgan; cheksiz
#: qayta yuklash esa faqat CPU va ekran miltillashi bo'lardi.
CRASH_LIMIT = 4
CRASH_WINDOW_S = 600.0

#: Qayta yuklash kechikishi (soniya): renderer qulashi va sahifa
#: ochilmasligi uchun alohida. Jitter bilan — butun zal bir vaqtda
#: internetni yo'qotib, bir vaqtda qaytganda test saytini urmasin.
CRASH_RELOAD_BASE_S = 1.0
CRASH_RELOAD_CAP_S = 15.0
LOAD_RETRY_BASE_S = 5.0
LOAD_RETRY_CAP_S = 60.0

#: Chromium `net::ERR_ABORTED` — navigatsiya boshqasi bilan almashtirildi
#: (platforma JS'i yo'naltirdi, foydalanuvchi tez bosdi). Xato EMAS.
ERR_ABORTED = -3
#: `net::ERR_BLOCKED_BY_CLIENT` — bizning interceptor to'sdi.
ERR_BLOCKED_BY_CLIENT = -20


def webengine_process_problem() -> Optional[str]:
    """
    `QtWebEngineProcess` topilmasa — operator uchun matn, aks holda `None`.

    NIMA UCHUN OLDINDAN: Qt jarayonni topolmasa `qFatal` chaqiradi va
    butun dastur Python'dagi har qanday `try` dan tashqarida, izsiz
    yopiladi. Antivirus `.exe` ni karantinga olgan mashinada bu dastur
    ochilishi bilan (sahifalar qurilayotganda) sodir bo'lardi.

    Qidiruv tartibi Qt'niki bilan bir xil: `QTWEBENGINEPROCESS_PATH`,
    `LibraryExecutablesPath`, dastur papkasi.
    """
    candidates = []
    env_path = os.environ.get("QTWEBENGINEPROCESS_PATH", "").strip()
    if env_path:
        candidates.append(env_path)
    try:
        from PyQt6.QtCore import QCoreApplication, QLibraryInfo

        candidates.append(os.path.join(
            QLibraryInfo.path(QLibraryInfo.LibraryPath.LibraryExecutablesPath), _PROCESS_EXE
        ))
        app_dir = QCoreApplication.applicationDirPath() if QCoreApplication.instance() else ""
        if app_dir:
            candidates.append(os.path.join(app_dir, _PROCESS_EXE))
    except Exception:
        # Aniqlab bo'lmadi — TO'SMAYMIZ: soxta "topilmadi" imtihonni
        # asossiz yopardi, haqiqiy yo'qlikni esa baribir Qt aytadi.
        log.debug("QtWebEngineProcess yo'lini aniqlab bo'lmadi", exc_info=True)
        return None
    candidates.append(os.path.join(os.path.dirname(sys.executable), _PROCESS_EXE))

    for path in candidates:
        if path and os.path.isfile(path):
            return None
    log.error("QtWebEngineProcess topilmadi. Qidirilgan joylar: %s", candidates)
    return (
        "Brauzer komponenti (QtWebEngineProcess.exe) topilmadi. Antivirus uni "
        "karantinga olgan bo'lishi mumkin — istisnoga qo'shing yoki dasturni "
        "qayta o'rnating. Administratorga murojaat qiling."
    )


def describe_load_error(domain: str, code: int, error_string: str = "") -> Optional[tuple]:
    """
    Asosiy sahifa ochilmadi: `(sarlavha, matn, avtomatik_qayta)` yoki `None`.

    `None` — panel ko'rsatilmaydi: navigatsiya shunchaki almashtirilgan
    (`ERR_ABORTED`) yoki sayt 4xx sahifasini O'ZI ko'rsatyapti
    (masalan "havola muddati tugagan" — bu platformaning matni va
    operator uni o'qishi kerak).

    `domain` — `QWebEngineLoadingInfo.ErrorDomain` nomi.
    """
    code = int(code or 0)
    if domain in ("HttpErrorDomain", "HttpStatusCodeDomain"):
        if code >= 500:
            return (
                "Test sayti vaqtincha ishlamayapti",
                "Test platformasi xato qaytardi (HTTP {}). Sahifa avtomatik qayta "
                "yuklanadi; takrorlansa administratorga murojaat qiling.".format(code),
                True,
            )
        return None
    if code == ERR_ABORTED:
        return None
    if domain == "CertificateErrorDomain":
        # Qayta urinish befoyda va XAVFLI tomonga undaydi: sertifikat
        # xatosi — tarmoqda kimdir aloqani to'xtatayotgan bo'lishi mumkin.
        return (
            "Xavfsiz ulanish o'rnatilmadi",
            "Test saytining sertifikati tekshiruvdan o'tmadi (kompyuter soati "
            "noto'g'ri yoki tarmoqda proksi bor). Administratorga murojaat qiling.",
            False,
        )
    if domain == "DnsErrorDomain" or code in (-105, -137):
        return (
            "Test sayti topilmadi",
            "Test saytining manzili aniqlanmadi (DNS). Internet ulanishini "
            "tekshiring — aloqa tiklangach sahifa o'zi qayta yuklanadi.",
            True,
        )
    if code in (-106, -21):  # INTERNET_DISCONNECTED, NETWORK_CHANGED
        return (
            "Internet aloqasi yo'q",
            "Kompyuter internetga ulanmagan. Tarmoq kabeli yoki Wi-Fi ni "
            "tekshiring — aloqa tiklangach sahifa o'zi qayta yuklanadi.",
            True,
        )
    if code in (-7, -118):  # TIMED_OUT, CONNECTION_TIMED_OUT
        return (
            "Test sayti javob bermayapti",
            "Test sayti belgilangan vaqtda javob bermadi. Sahifa avtomatik "
            "qayta yuklanadi.",
            True,
        )
    return (
        "Test sahifasi ochilmadi",
        "Test saytiga ulanib bo'lmadi ({}). Sahifa avtomatik qayta "
        "yuklanadi.".format(error_string or code),
        True,
    )


class CrashGuard:
    """
    Renderer qulashlarini sanaydi. Sof mantiq, vaqt manbai — parametr.

    `record()` — qulashni qayd etadi va keyingi qayta yuklashgacha
    kutishni qaytaradi; `None` — chegara oshdi, avtomatik tiklash yo'q.
    """

    def __init__(self, *, limit: int = CRASH_LIMIT, window_s: float = CRASH_WINDOW_S,
                 clock=time.monotonic, rng=None) -> None:
        self._limit = limit
        self._window = window_s
        self._clock = clock
        self._rng = rng
        self._times: deque = deque()

    def record(self) -> Optional[float]:
        now = self._clock()
        self._times.append(now)
        while self._times and now - self._times[0] > self._window:
            self._times.popleft()
        count = len(self._times)
        if count > self._limit:
            return None
        kwargs = {"rng": self._rng} if self._rng is not None else {}
        return net_policy.backoff_delay(
            count - 1, base=CRASH_RELOAD_BASE_S, cap=CRASH_RELOAD_CAP_S, **kwargs
        )

    def reset(self) -> None:
        self._times.clear()

    @property
    def count(self) -> int:
        return len(self._times)


class WebErrorPanel(QFrame):
    """
    Brauzer ustidagi xato ekrani: sarlavha, matn, sanoq va bitta tugma.

    Modal EMAS va `exec()` YO'Q: imtihon davomida heartbeat, taymerlar
    va proktor buyruqlari to'xtamasligi kerak (`CLAUDE.md`, dialoglar).
    """

    #: Operator tugmani bosdi yoki sanoq tugadi.
    retry_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # MD3: sahifa foni (tinted surface) ustida markazdagi karta - belgi,
        # sarlavha, izoh, sanoq va bitta "pill" tugma. Dialoglar bilan BIR
        # XIL ko'rinish (`StateBadge`, 28 px karta): operator uchun bu ham
        # "tizim xabari", test sahifasining bir qismi emas.
        self.setObjectName("webErrorPanel")
        self.setStyleSheet(
            "QFrame#webErrorPanel {{ background-color: {bg}; }}"
            "QFrame#webErrorCard {{ background-color: {card}; border: none; border-radius: 28px; }}".format(
                bg=COLORS["background"], card=COLORS["surface_container_lowest"],
            )
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 48, 48, 48)
        outer.addStretch(1)

        card = QFrame(self)
        card.setObjectName("webErrorCard")
        card.setMaximumWidth(560)
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(16, 32, 20, 40))
        card.setGraphicsEffect(shadow)
        outer.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(2)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(40, 36, 40, 32)
        layout.setSpacing(12)

        self._badge = StateBadge(size=64)
        self._badge.set_state("warning")
        layout.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(4)

        self._title = QLabel(card)
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setWordWrap(True)
        self._title.setStyleSheet(
            "font-size: 22px; font-weight: 700; color: {};".format(COLORS["on_surface"])
        )
        layout.addWidget(self._title)

        self._text = QLabel(card)
        self._text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._text.setWordWrap(True)
        self._text.setStyleSheet(
            "font-size: 15px; color: {};".format(COLORS["on_surface_variant"])
        )
        layout.addWidget(self._text)

        self._countdown_label = QLabel(card)
        self._countdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._countdown_label.setStyleSheet(
            "font-size: 13px; color: {};".format(COLORS["outline"])
        )
        layout.addWidget(self._countdown_label)
        layout.addSpacing(8)

        self._button = QPushButton("Qayta yuklash", card)
        self._button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._button.setMinimumWidth(240)
        self._button.setStyleSheet(primary_button_style(48))
        self._button.clicked.connect(self._on_clicked)
        layout.addWidget(self._button, 0, Qt.AlignmentFlag.AlignHCenter)

        self._remaining = 0
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._on_tick)
        self.hide()

    def show_error(self, title: str, text: str, *, retry_in_s: Optional[float] = None,
                   button_text: str = "Qayta yuklash") -> None:
        """`retry_in_s` — avtomatik qayta urinishgacha (`None` — faqat qo'lda)."""
        self._title.setText(title)
        self._text.setText(text)
        self._button.setText(button_text)
        self._button.setEnabled(True)
        self._tick.stop()
        if retry_in_s is not None:
            self._remaining = max(1, int(round(retry_in_s)))
            self._update_countdown()
            self._tick.start()
        else:
            self._countdown_label.setText("")
        self.show()
        self.raise_()

    def show_progress(self, text: str) -> None:
        """Qayta yuklanmoqda — tugma vaqtincha o'chadi (ikki marta bosilmasin)."""
        self._tick.stop()
        self._countdown_label.setText(text)
        self._button.setEnabled(False)

    def dismiss(self) -> None:
        self._tick.stop()
        self.hide()

    def _update_countdown(self) -> None:
        self._countdown_label.setText(
            "{} soniyadan keyin avtomatik qayta yuklanadi".format(self._remaining)
        )

    def _on_tick(self) -> None:
        self._remaining -= 1
        if self._remaining <= 0:
            self._tick.stop()
            self.retry_requested.emit()
            return
        self._update_countdown()

    def _on_clicked(self) -> None:
        self._tick.stop()
        self.retry_requested.emit()
