"""
Global himoya: tutilmagan xatolar dasturni YOPMAYDI.

ASOSIY TALAB: imtihon davomida dastur hech qachon kutilmaganda
yopilmasligi kerak. Bu modul to'rt manbani bitta joyga yig'adi:

  * `sys.excepthook` - asosiy thread va Qt slotlari. PyQt6 slotdan
    chiqib ketgan istisnoni `sys.excepthook` ga beradi; ilgak STANDART
    bo'lsa esa `qFatal()` bilan jarayonni O'LDIRADI (tekshirildi:
    PyQt6 6.11, chiqish kodi 0xC0000409). Shuning uchun ilgak har doim
    o'rnatilgan bo'lishi SHART - uni olib tashlash yoki standartga
    qaytarish birinchi slot xatosida imtihonni yopadi;
  * `threading.excepthook` - oddiy `threading.Thread` lar (jarayonni
    o'ldirmaydi, lekin frozen rejimda stderr yo'q - xato izsiz yo'qolardi);
  * `sys.unraisablehook` - `__del__`, GC paytidagi xatolar (faqat log);
  * `faulthandler` - NATIV qulash (access violation, abort). Python
    kodi bu paytda ishlamaydi, shuning uchun fayl DASTLABKI ochilgan
    va butun hayot davomida ochiq turadigan deskriptorga yoziladi.

Qt'ning o'z xabarlari (`qWarning`, `qCritical`) `qInstallMessageHandler`
orqali log'ga tushadi - aks holda frozen rejimda ular ham yo'qolardi.

FOYDALANUVCHIGA: xato faqat log'ga yoziladi va `reporter()` signali
orqali UI ga "xato bo'ldi" deb aytiladi. UI (MainWindow) uni bloklamaydigan
xabar sifatida ko'rsatadi. Bir xil xato qayta-qayta kelsa xabarlar
UYILMAYDI - `ErrorThrottle`.
"""

from __future__ import annotations

import faulthandler
import logging
import os
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("crash_guard")

#: Native crash log ochiq deskriptori - YIG'ILMASLIGI kerak:
#: `faulthandler` faqat raqamli deskriptorni saqlaydi va fayl obyekti
#: yopilsa qulash paytida yozuv yo'qoladi.
_native_log_file = None
_hooks_installed = False
_qt_handler_installed = False

#: Native log hajm chegarasi. `faulthandler` Windows'da BIRINCHI
#: bosqichdagi (keyin ushlangan) istisnolarni ham yozadi - ba'zi
#: drayverlar buni tez-tez qiladi va fayl cheksiz o'sishi mumkin edi.
_NATIVE_LOG_MAX_BYTES = 5 * 1024 * 1024


# ----------------------------------------------------------------------
# Takrorlanuvchi xatolarni cheklash (sof mantiq - testlanadi)
# ----------------------------------------------------------------------
@dataclass
class ErrorThrottle:
    """
    Qaysi xato foydalanuvchiga KO'RSATILADI.

    Ikki chegara:
      * bir xil imzo (`signature`) - `repeat_s` ichida bir marta;
      * umuman - `global_gap_s` ichida bir marta.

    Sabab: taymer slotidagi xato har 30 ms da takrorlanishi mumkin
    va har biriga oyna ochish UI ni o'zi bosib qo'yardi. Hisoblagich
    esa to'xtamaydi - xabarda "N marta takrorlandi" ko'rinadi.
    """

    repeat_s: float = 60.0
    global_gap_s: float = 5.0
    counts: dict = field(default_factory=dict)
    _last_shown: dict = field(default_factory=dict)
    _last_any: Optional[float] = None

    def record(self, signature: str, now: float) -> tuple[int, bool]:
        count = self.counts.get(signature, 0) + 1
        self.counts[signature] = count
        last = self._last_shown.get(signature)
        if last is not None and now - last < self.repeat_s:
            return count, False
        if self._last_any is not None and now - self._last_any < self.global_gap_s:
            return count, False
        self._last_shown[signature] = now
        self._last_any = now
        return count, True


_throttle = ErrorThrottle()
_throttle_lock = threading.Lock()


def signature_of(exc_type, tb) -> str:
    """Xato imzosi: tur + eng ichki kadrning fayli va qatori."""
    location = ""
    try:
        frames = traceback.extract_tb(tb) if tb is not None else []
        if frames:
            last = frames[-1]
            location = "{}:{}".format(os.path.basename(last.filename), last.lineno)
    except Exception:  # noqa: BLE001
        location = ""
    name = getattr(exc_type, "__name__", str(exc_type))
    return "{} ({})".format(name, location) if location else name


# ----------------------------------------------------------------------
# UI ga xabar - lazy QObject
# ----------------------------------------------------------------------
_reporter = None


def reporter():
    """
    `error_occurred(signature: str, count: int)` signalli yagona QObject.

    LAZY: QApplication'dan oldin QObject yaratish mumkin emas, ilgak esa
    import paytidayoq o'rnatiladi. QApplication yo'q bo'lsa `None` -
    xato baribir log'ga yozilgan.
    """
    global _reporter
    if _reporter is not None:
        return _reporter
    try:
        from PyQt6.QtCore import QCoreApplication, QObject, pyqtSignal
    except Exception:  # noqa: BLE001
        return None
    if QCoreApplication.instance() is None:
        return None

    class _ErrorReporter(QObject):
        # `event` DEB NOMLANMAYDI - QObject.event() ni bosib qo'yardi.
        error_occurred = pyqtSignal(str, int)

    _reporter = _ErrorReporter()
    # Asosiy thread'ga bog'lash: signal istalgan thread'dan chiqsa ham
    # qabul qiluvchi (UI) navbat orqali asosiy thread'da ishlaydi.
    app = QCoreApplication.instance()
    if app is not None and _reporter.thread() is not app.thread():
        _reporter.moveToThread(app.thread())
    return _reporter


def _notify(signature: str) -> None:
    try:
        with _throttle_lock:
            count, show = _throttle.record(signature, time.monotonic())
        if not show:
            return
        target = _reporter  # yangisini YARATMAYMIZ - bu fon thread bo'lishi mumkin
        if target is not None:
            target.error_occurred.emit(signature, count)
    except Exception:  # noqa: BLE001 - ilgak hech qachon yiqilmasligi kerak
        pass


# ----------------------------------------------------------------------
# Python ilgaklari
# ----------------------------------------------------------------------
def _format(exc_type, exc_value, exc_tb) -> str:
    try:
        return "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    except Exception:  # noqa: BLE001
        return "{}: {!r}".format(exc_type, exc_value)


def _excepthook(exc_type, exc_value, exc_tb) -> None:
    """
    Asosiy thread / Qt slot xatosi: log + UI xabari. JARAYON DAVOM ETADI.

    `KeyboardInterrupt` (dev konsolida Ctrl+C) standart yo'ldan ketadi.
    """
    try:
        if exc_type is not None and issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logging.getLogger("client").error(
            "Qo'lga olinmagan xato (dastur davom etmoqda):\n%s",
            _format(exc_type, exc_value, exc_tb),
        )
        _notify(signature_of(exc_type, exc_tb))
    except Exception:  # noqa: BLE001
        pass


def _thread_excepthook(args) -> None:
    try:
        if args.exc_type is SystemExit:
            return
        name = getattr(args.thread, "name", "?")
        logging.getLogger("client").error(
            "Fon thread'ida (%s) qo'lga olinmagan xato:\n%s",
            name, _format(args.exc_type, args.exc_value, args.exc_traceback),
        )
        _notify(signature_of(args.exc_type, args.exc_traceback))
    except Exception:  # noqa: BLE001
        pass


def _unraisable_hook(unraisable) -> None:
    """GC/`__del__` xatolari - faqat log (foydalanuvchiga ko'rsatilmaydi)."""
    try:
        logging.getLogger("client").warning(
            "Ko'tarib bo'lmaydigan xato (%s): %s",
            getattr(unraisable, "err_msg", "") or "Exception ignored",
            _format(unraisable.exc_type, unraisable.exc_value, unraisable.exc_traceback),
        )
    except Exception:  # noqa: BLE001
        pass


def install_python_hooks() -> None:
    """Idempotent. `setup_logging` chaqiradi - importdan keyin DARHOL."""
    global _hooks_installed
    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    sys.unraisablehook = _unraisable_hook
    _hooks_installed = True


def hooks_installed() -> bool:
    return _hooks_installed and sys.excepthook is _excepthook


# ----------------------------------------------------------------------
# Native qulash log'i
# ----------------------------------------------------------------------
def enable_native_crash_log(path=None) -> Optional[str]:
    """
    `faulthandler` ni OCHIQ turadigan faylga yoqadi. Yo'lni qaytaradi.

    Fayl alohida (`crash-native.log`), asosiy log EMAS: qulash paytida
    `faulthandler` to'g'ridan-to'g'ri deskriptorga yozadi va
    `RotatingFileHandler` bilan bitta faylni bo'lishish yozuvlarni
    aralashtirib yuborardi.
    """
    global _native_log_file
    if _native_log_file is not None:
        return getattr(_native_log_file, "name", None)
    try:
        if path is None:
            from core.bundle_paths import logs_root

            path = logs_root() / "crash-native.log"
        path = str(path)
        try:
            if os.path.getsize(path) > _NATIVE_LOG_MAX_BYTES:
                os.replace(path, path + ".1")
        except OSError:
            pass
        handle = open(path, "a", encoding="utf-8", buffering=1)
        handle.write(
            "\n=== {} pid={} - native crash log yoqildi\n".format(
                time.strftime("%Y-%m-%d %H:%M:%S"), os.getpid()
            )
        )
        handle.flush()
        faulthandler.enable(file=handle, all_threads=True)
        _native_log_file = handle
        return path
    except Exception:  # noqa: BLE001 - diagnostika, ishga tushishning sharti emas
        log.warning("Native crash log yoqilmadi", exc_info=True)
        return None


# ----------------------------------------------------------------------
# Qt xabarlari
# ----------------------------------------------------------------------
#: Bir xil Qt xabari necha marta to'liq yoziladi. Keyin faqat har
#: 100-si: drayver/WebEngine ogohlantirishlari soniyasiga o'nlab
#: marta takrorlanib, asosiy log'ni bir necha soatda to'ldirardi.
_QT_REPEAT_FULL = 5
_qt_counts: dict = {}


def _qt_message_handler(msg_type, context, message) -> None:
    try:
        from PyQt6.QtCore import QtMsgType

        text = str(message)
        count = _qt_counts.get(text, 0) + 1
        if len(_qt_counts) < 2000:
            _qt_counts[text] = count
        if count > _QT_REPEAT_FULL and count % 100:
            return
        suffix = " (x{})".format(count) if count > 1 else ""
        qt_log = logging.getLogger("qt")
        if msg_type == QtMsgType.QtFatalMsg:
            # Keyin Qt jarayonni to'xtatadi - hech bo'lmasa sababi qolsin.
            qt_log.critical("QT FATAL: %s", text)
            for handler in logging.getLogger().handlers:
                try:
                    handler.flush()
                except Exception:  # noqa: BLE001
                    pass
        elif msg_type == QtMsgType.QtCriticalMsg:
            qt_log.error("%s%s", text, suffix)
        elif msg_type == QtMsgType.QtWarningMsg:
            qt_log.warning("%s%s", text, suffix)
        else:
            qt_log.debug("%s%s", text, suffix)
    except Exception:  # noqa: BLE001
        pass


def install_qt_message_handler() -> bool:
    global _qt_handler_installed
    try:
        from PyQt6.QtCore import qInstallMessageHandler

        qInstallMessageHandler(_qt_message_handler)
        _qt_handler_installed = True
        return True
    except Exception:  # noqa: BLE001
        log.debug("Qt xabar ilgagi o'rnatilmadi", exc_info=True)
        return False


def uninstall_qt_message_handler() -> None:
    """
    Chiqishda: Python yakunlanayotganda Qt yana xabar bersa, ilgak
    yarim-yo'q qilingan interpretatorga murojaat qilib qulashi mumkin.
    """
    global _qt_handler_installed
    if not _qt_handler_installed:
        return
    try:
        from PyQt6.QtCore import qInstallMessageHandler

        qInstallMessageHandler(None)
    except Exception:  # noqa: BLE001
        pass
    _qt_handler_installed = False
