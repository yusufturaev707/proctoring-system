"""
Windows tizim hodisalari: uyqudan uyg'onish va ekran o'zgarishi.

SHARTNOMA (boshqa qatlamlar shunga tayanadi):

    from core.system_events import system_events
    system_events().power_resumed.connect(...)    # argumentsiz
    system_events().display_changed.connect(...)  # argumentsiz

  * `power_resumed` - `WM_POWERBROADCAST` (`PBT_APMRESUMEAUTOMATIC` /
    `PBT_APMRESUMESUSPEND`). Windows uyg'onishda IKKALASINI ham, har bir
    top-level oynaga yuboradi - shuning uchun `_RESUME_DEBOUNCE_MS`
    ichida bitta signal. Kamera qayta ochilishi (C2) va tarmoq qayta
    ulanishi (C3) shunga ulanadi;
  * `display_changed` - `WM_DISPLAYCHANGE`, `WM_DPICHANGED`, ekran
    qo'shildi/olindi, ekran DPI/geometriyasi o'zgardi. Bitta monitor
    ulash o'nlab xabar beradi - `_DISPLAY_DEBOUNCE_MS`.
  * `power_suspending` - `PBT_APMSUSPEND` (qo'shimcha, diagnostika).

IMPORT ARZON va QApplication'dan OLDIN xavfsiz: Qt klassi faqat birinchi
`system_events()` chaqiruvida yaratiladi. Nativ manba (ilova darajasidagi
`QAbstractNativeEventFilter`) QApplication paydo bo'lgan zahoti ulanadi -
`main.py` uni ochiq chaqiradi (`attach()`), kechikkan chaqiruvchi uchun esa
`system_events()` o'zi ham urinadi.

Signal HAR DOIM asosiy thread'da chiqadi (filtr Qt hodisa siklida ishlaydi).
"""

from __future__ import annotations

import logging
import sys

log = logging.getLogger(__name__)

_WM_POWERBROADCAST = 0x0218
_WM_DISPLAYCHANGE = 0x007E
_WM_DPICHANGED = 0x02E0
_PBT_APMSUSPEND = 0x0004
_PBT_APMRESUMESUSPEND = 0x0007
_PBT_APMRESUMEAUTOMATIC = 0x0012

#: Uyg'onishdan keyingi takroriy xabarlar oynasi.
_RESUME_DEBOUNCE_MS = 3000
#: Ekran o'zgarishi "tinchigan"idan keyin bitta signal.
_DISPLAY_DEBOUNCE_MS = 700


def classify_message(message: int, wparam: int) -> str:
    """
    Nativ xabar -> "resume" | "suspend" | "display" | "".

    Sof funksiya (testlanadi): qaror shu yerda, Qt'ga bog'liq qism esa
    faqat uni signalga aylantiradi.
    """
    if message == _WM_POWERBROADCAST:
        if wparam in (_PBT_APMRESUMEAUTOMATIC, _PBT_APMRESUMESUSPEND):
            return "resume"
        if wparam == _PBT_APMSUSPEND:
            return "suspend"
        return ""
    if message in (_WM_DISPLAYCHANGE, _WM_DPICHANGED):
        return "display"
    return ""


_instance = None
_filter = None


def _create():
    from PyQt6.QtCore import QObject, QTimer, pyqtSignal

    class SystemEvents(QObject):
        power_resumed = pyqtSignal()
        power_suspending = pyqtSignal()
        display_changed = pyqtSignal()

        def __init__(self) -> None:
            super().__init__()
            self._attached = False
            self._resume_timer = None
            self._display_timer = None
            self._screens_connected = set()

        # --------------------------------------------------------------
        def _ensure_timers(self) -> None:
            # Taymerlar QApplication bor bo'lganda yaratiladi (attach).
            if self._resume_timer is not None:
                return
            self._resume_timer = QTimer(self)
            self._resume_timer.setSingleShot(True)
            self._resume_timer.setInterval(_RESUME_DEBOUNCE_MS)
            self._display_timer = QTimer(self)
            self._display_timer.setSingleShot(True)
            self._display_timer.setInterval(_DISPLAY_DEBOUNCE_MS)
            self._display_timer.timeout.connect(self._emit_display)

        def handle(self, kind: str) -> None:
            """Nativ filtr va Qt ekran signallaridan keladi (asosiy thread)."""
            try:
                self._ensure_timers()
                if kind == "resume":
                    # Birinchi xabarda DARHOL, keyingilari oyna ichida yutiladi:
                    # kamera va tarmoqni qayta tiklash kechikmasligi kerak.
                    if self._resume_timer.isActive():
                        return
                    self._resume_timer.start()
                    log.info("Tizim uyqudan uyg'ondi - qayta tiklash signali")
                    self.power_resumed.emit()
                elif kind == "suspend":
                    log.info("Tizim uyqu rejimiga o'tmoqda")
                    self.power_suspending.emit()
                elif kind == "display":
                    self._display_timer.start()
            except Exception:  # noqa: BLE001 - signal manbai hech qachon yiqilmaydi
                log.debug("Tizim hodisasini qayta ishlashda xato", exc_info=True)

        def _emit_display(self) -> None:
            self._connect_screens()
            log.info("Ekran konfiguratsiyasi o'zgardi (monitor/DPI)")
            self.display_changed.emit()

        # --------------------------------------------------------------
        def attach(self) -> bool:
            """Nativ filtr va QGuiApplication ekran signallarini ulaydi."""
            if self._attached:
                return True
            from PyQt6.QtCore import QCoreApplication

            app = QCoreApplication.instance()
            if app is None:
                return False
            if self.thread() is not app.thread():
                self.moveToThread(app.thread())
            self._ensure_timers()
            _install_native_filter(app, self)
            try:
                from PyQt6.QtGui import QGuiApplication

                if isinstance(app, QGuiApplication):
                    app.screenAdded.connect(lambda _s: self.handle("display"))
                    app.screenRemoved.connect(lambda _s: self.handle("display"))
                    app.primaryScreenChanged.connect(lambda _s: self.handle("display"))
                    self._connect_screens()
            except Exception:  # noqa: BLE001
                log.debug("Ekran signallari ulanmadi", exc_info=True)
            self._attached = True
            return True

        def _connect_screens(self) -> None:
            try:
                from PyQt6.QtGui import QGuiApplication

                for screen in QGuiApplication.screens():
                    key = id(screen)
                    if key in self._screens_connected:
                        continue
                    self._screens_connected.add(key)
                    screen.logicalDotsPerInchChanged.connect(
                        lambda _v: self.handle("display")
                    )
                    screen.geometryChanged.connect(lambda _v: self.handle("display"))
            except Exception:  # noqa: BLE001
                log.debug("Ekran DPI signallari ulanmadi", exc_info=True)

    return SystemEvents()


def _install_native_filter(app, target) -> None:
    """Ilova darajasidagi filtr - BARCHA top-level oynalarimiz xabarlari."""
    global _filter
    if _filter is not None or sys.platform != "win32":
        return
    from ctypes import wintypes

    from PyQt6.QtCore import QAbstractNativeEventFilter

    class _PowerDisplayFilter(QAbstractNativeEventFilter):
        def nativeEventFilter(self, event_type, message):
            try:
                if bytes(event_type) == b"windows_generic_MSG":
                    msg = wintypes.MSG.from_address(int(message))
                    kind = classify_message(int(msg.message), int(msg.wParam or 0))
                    if kind:
                        target.handle(kind)
            except Exception:  # noqa: BLE001
                pass
            # HECH QACHON yutmaymiz: Qt ham bu xabarlarni o'zi qayta ishlaydi
            # (ekran ro'yxati, DPI).
            return False, 0

    _filter = _PowerDisplayFilter()
    app.installNativeEventFilter(_filter)


def system_events():
    """
    Jarayon bo'yicha yagona `SystemEvents` QObject.

    QApplication hali yo'q bo'lsa ham obyekt qaytadi (signalga ulanish
    mumkin); nativ manba QApplication paydo bo'lgach `attach()` bilan
    ulanadi.
    """
    global _instance
    if _instance is None:
        _instance = _create()
    try:
        _instance.attach()
    except Exception:  # noqa: BLE001
        log.debug("Tizim hodisalari manbai ulanmadi", exc_info=True)
    return _instance
