"""
Qurilma va oyna nazorati - imtihon davomidagi hodisalar manbai.

Bu modul HECH NARSANI to'smaydi va hech qanday qaror qabul qilmaydi: u
faqat kuzatadi va hodisa chiqaradi. Bloklash `services/lockdown.py` da,
qaror esa serverda (`ingest.RISK_WEIGHTS`, proktor). Sabab oddiy -
"to'sish" va "qayd etish" har xil hayot sikliga ega: to'siq dastur
ishga tushishi bilan qo'yiladi va chiqishda olib tashlanadi, kuzatuv
esa faqat sessiya davomida ishlaydi.

Nimalar kuzatiladi va NIMA UCHUN aynan shu usulda:

  OYNA FOKUSI - `applicationStateChanged` orqali, oyna darajasidagi
    `focusChanged` orqali EMAS. Ikkinchisi bizning o'z dialoglarimizda
    ham ishga tushardi (texnik muammo oynasi, ogohlantirish overlay'i)
    va hodisa oqimi soxta `window_blur` bilan to'lardi. Dastur
    darajasidagi holat esa faqat BOSHQA dastur fokusni olganda
    o'zgaradi - bu aynan kerakli hodisa.

  TO'LIQ EKRAN - oynaga hodisa filtri qo'yiladi. Faqat dastur to'liq
    ekranda BOSHLANGAN bo'lsa kuzatiladi: `FULLSCREEN=false` bilan
    ishlayotgan dev mashinasida har ishga tushishda soxta
    `fullscreen_exit` chiqishi kerak emas.

  MONITORLAR - `screenAdded`/`screenRemoved` signallari va boshlanishdagi
    tekshiruv. Ikkinchi monitor imtihon boshida ham, o'rtasida ulansa
    ham bir xil darajada muhim.

  RDP - jarayonlar ro'yxati ALOHIDA thread'da skanerlanadi.
    `psutil.process_iter` sekin mashinada 100 ms gacha oladi va UI
    thread'ida u WebView'ni tutib qolardi.

  BLOKLANGAN TUGMALAR - `lockdown` observer'i orqali. Bloklashning
    o'zi hodisa emas, lekin Alt+Tab ni qayta-qayta bosish - niyatning
    eng aniq belgisi.

HODISA JIDDIYLIGI serverdagi xulqni belgilaydi: `HIGH` (3) va undan
yuqorisi buferni chetlab o'tib DARHOL DB'ga yoziladi va WebSocket
orqali proktorga uzatiladi (`services/ingest.py`). Shuning uchun tez
takrorlanadigan hodisalar (`hotkey_blocked`) ataylab `LOW` - aks holda
har bosish alohida tranzaksiya bo'lardi.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from PyQt6.QtCore import QEvent, QObject, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication

log = logging.getLogger(__name__)

#: Jarayonlar ro'yxati qanchalik tez-tez tekshiriladi (ms).
#:
#: 15 s - kelishuv: masofaviy boshqaruv dasturi ishga tushishi va
#: ulanishi shuncha vaqt oladi, ya'ni aniqlash kechikmaydi; ayni paytda
#: skanerlash yuki (~200 jarayon) sezilarli bo'lmaydi.
_PROCESS_SCAN_MS = 15_000

#: Bitta tugma uchun hodisa oralig'i (s).
#:
#: Talabgor Alt+Tab ni bosib turishi mumkin va hook har takrorda ishga
#: tushadi. Chegarasiz bu daqiqasiga yuzlab hodisa degani va u
#: `client_ingest` throttle'ini yeb qo'yardi. Oraliqdagi bosishlar
#: YO'QOLMAYDI - ular sanaladi va keyingi hodisaning `payload` ida
#: `repeats` sifatida ketadi.
_HOTKEY_COOLDOWN_S = 15.0


class _ProcessScanner(QThread):
    """
    Jarayonlar ro'yxatini fon rejimida kuzatadi.

    Faqat O'ZGARISHLAR haqida xabar beradi (edge detection): dastur
    ishlab turgani har 15 soniyada takroriy hodisa bo'lmasligi kerak,
    lekin u yopilib qayta ochilsa - bu yangi hodisa.
    """

    #: Ro'yxatda paydo bo'lgan jarayonlar nomi.
    appeared = pyqtSignal(list)

    def __init__(self, process_names: list, parent=None) -> None:
        super().__init__(parent)
        # Taqqoslash kichik harfda va kengaytmasiz ham bajariladi:
        # panelga `AnyDesk.exe` ham, `anydesk` ham yozilishi mumkin.
        self._targets = {}
        for raw in process_names or []:
            name = str(raw or "").strip().lower()
            if not name:
                continue
            self._targets[name] = raw
            if name.endswith(".exe"):
                self._targets[name[:-4]] = raw
        self._running = False
        self._seen: set = set()

    def start(self, *args, **kwargs) -> None:
        """
        Bayroq thread BOSHLANISHIDAN oldin qo'yiladi.

        Uni `run()` ichida qo'yish POYGA beradi: `start()` dan keyin
        darhol `stop()` chaqirilsa (qisqa sessiya, tezda yopilgan
        sahifa), `stop()` bayroqni `False` qiladi, keyin endigina
        boshlangan `run()` uni `True` ga QAYTARADI va thread abadiy
        ishlab qoladi. Natijada dastur yopilishida "QThread destroyed
        while still running" bilan qulaydi.
        """
        self._running = True
        super().start(*args, **kwargs)

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        if not self._targets:
            return
        try:
            import psutil
        except ImportError:
            log.warning("psutil yo'q - RDP aniqlash ishlamaydi")
            return

        while self._running:
            found = set()
            try:
                for process in psutil.process_iter(["name"]):
                    name = (process.info.get("name") or "").strip().lower()
                    if not name:
                        continue
                    if name in self._targets:
                        found.add(self._targets[name])
                    elif name.endswith(".exe") and name[:-4] in self._targets:
                        found.add(self._targets[name[:-4]])
            except Exception:
                # Jarayonlar ro'yxatini o'qib bo'lmadi (huquq, WMI).
                # Kuzatuv to'xtamaydi - keyingi tsiklda qayta uriniladi.
                log.debug("Jarayonlarni skanerlashda xato", exc_info=True)
                found = self._seen

            new = sorted(found - self._seen)
            self._seen = found
            if new:
                self.appeared.emit(new)

            # Kichik bo'laklarda uxlaymiz: `stop()` chaqirilganda
            # thread 15 soniya kutib turmasligi kerak - dastur
            # yopilishi shuncha cho'zilardi.
            for _ in range(_PROCESS_SCAN_MS // 250):
                if not self._running:
                    return
                self.msleep(250)


class DeviceWatcher(QObject):
    """
    Sessiya davomida ishlaydigan qurilma kuzatuvchisi.

    Hodisalar `detected` signali orqali chiqadi va ularni `SessionMonitor`
    buferiga chaqiruvchi joylashtiradi. Bu modul buferni BILMAYDI:
    shu tufayli uni sinash uchun tarmoq ham, sessiya ham kerak emas.
    """

    #: (hodisa turi, jiddiylik, payload)
    #:
    #: Nomi `event` EMAS va bo'la olmaydi: `QObject.event()` - Qt'ning
    #: markaziy virtual metodi va uni `pyqtSignal` bilan bosib qo'yish
    #: obyektga birinchi bola qo'shilishi bilan (masalan `parent=self`
    #: bilan yaratilgan QThread) butun jarayonni QULATADI. Xato
    #: jimgina yuz beradi - Python istisno ham bermaydi.
    detected = pyqtSignal(str, int, dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._active = False
        self._window = None
        self._watch_fullscreen = False
        self._scanner: Optional[_ProcessScanner] = None
        self._app = QApplication.instance()

        #: Bloklangan tugmalar: kod -> (oxirgi xabar vaqti, sanoq).
        self._hotkey_state: dict = {}

    # ------------------------------------------------------------------
    def start(self, config: Optional[dict], *, window=None) -> None:
        if self._active or self._app is None:
            return
        self._active = True
        config = config or {}
        device = config.get("device") or {}
        rdp = config.get("rdp") or {}

        self._app.applicationStateChanged.connect(self._on_app_state)

        # --- To'liq ekran ---
        self._window = window
        if window is not None and window.isFullScreen():
            self._watch_fullscreen = True
            window.installEventFilter(self)

        # --- Monitorlar ---
        if device.get("detect_monitor", True):
            self._app.screenAdded.connect(self._on_screens_changed)
            self._app.screenRemoved.connect(self._on_screens_changed)
            screens = len(self._app.screens())
            if screens > 1:
                # Boshlanishdagi holat ham hodisa: ikkinchi monitor
                # imtihon boshlanishidan oldin ulangan bo'lsa, u
                # keyin ulangandan kam xavfli emas.
                self._emit_multi_monitor(screens, "startup")

        # --- RDP ---
        if rdp.get("enabled", True):
            processes = rdp.get("processes") or []
            if processes:
                self._scanner = _ProcessScanner(processes, parent=self)
                self._scanner.appeared.connect(self._on_processes_found)
                self._scanner.start()
                log.info("RDP kuzatuvi: %s ta dastur", len(processes))
            else:
                # Ro'yxat bo'sh - bu "aniqlash yoqilgan, lekin nimani
                # qidirishni administrator ko'rsatmagan" holati.
                log.warning(
                    "RDP aniqlash yoqilgan, lekin dasturlar ro'yxati bo'sh - "
                    "panelda `RdpObject` yozuvlarini qo'shing"
                )

        log.info("Qurilma kuzatuvi boshlandi")

    def stop(self) -> None:
        if not self._active:
            return
        self._active = False

        try:
            self._app.applicationStateChanged.disconnect(self._on_app_state)
        except TypeError:
            pass
        try:
            self._app.screenAdded.disconnect(self._on_screens_changed)
            self._app.screenRemoved.disconnect(self._on_screens_changed)
        except TypeError:
            pass

        if self._window is not None and self._watch_fullscreen:
            self._window.removeEventFilter(self)
        self._window = None
        self._watch_fullscreen = False

        if self._scanner is not None:
            self._scanner.stop()
            # Skaner 250 ms lik bo'laklarda uxlaydi, ya'ni bu kutish
            # amalda qisqa. Tugamasa `terminate()`: ishlab turgan
            # QThread bilan chiqish Qt'da qulash demak
            # (`main_window._await` da ham xuddi shu qoida).
            if not self._scanner.wait(3000):
                log.warning("Jarayon skaneri tugamadi - terminate")
                self._scanner.terminate()
                self._scanner.wait(1000)
            self._scanner = None

        self._hotkey_state.clear()
        log.info("Qurilma kuzatuvi to'xtadi")

    # ------------------------------------------------------------------
    # Oyna fokusi
    # ------------------------------------------------------------------
    def _on_app_state(self, state) -> None:
        if not self._active:
            return
        if state == Qt.ApplicationState.ApplicationActive:
            # Qaytish INFO darajasida: u o'z-o'zicha buzilish emas,
            # lekin usiz "qancha vaqt tashqarida bo'ldi" degan savolga
            # javob bo'lmaydi.
            self.detected.emit("window_focus", 0, {})
        elif state == Qt.ApplicationState.ApplicationInactive:
            self.detected.emit("window_blur", 2, {})

    def eventFilter(self, obj, event) -> bool:
        """
        To'liq ekrandan chiqish.

        Hodisa YUTILMAYDI (`False` qaytariladi): bu kuzatuv, to'siq
        emas - oyna holatini boshqarish `MainWindow` ning ishi.
        """
        if (
            self._active
            and self._watch_fullscreen
            and event.type() == QEvent.Type.WindowStateChange
            and obj is self._window
            and not obj.isFullScreen()
        ):
            self.detected.emit(
                "fullscreen_exit", 3, {"state": int(obj.windowState().value)}
            )
        return False

    # ------------------------------------------------------------------
    # Monitorlar
    # ------------------------------------------------------------------
    def _on_screens_changed(self, _screen=None) -> None:
        if not self._active or self._app is None:
            return
        screens = len(self._app.screens())
        if screens > 1:
            self._emit_multi_monitor(screens, "changed")

    def _emit_multi_monitor(self, count: int, reason: str) -> None:
        self.detected.emit(
            "multi_monitor",
            3,
            {
                "count": count,
                "reason": reason,
                "screens": [
                    {
                        "name": screen.name(),
                        "width": screen.geometry().width(),
                        "height": screen.geometry().height(),
                    }
                    for screen in self._app.screens()
                ],
            },
        )

    # ------------------------------------------------------------------
    # RDP
    # ------------------------------------------------------------------
    def _on_processes_found(self, names: list) -> None:
        if not self._active:
            return
        log.warning("Masofaviy boshqaruv dasturi aniqlandi: %s", names)
        # CRITICAL: imtihon paytida masofaviy boshqaruv - eng jiddiy
        # texnik buzilish va u buferni chetlab o'tib darhol yozilishi
        # kerak (`ingest.IMMEDIATE_SEVERITY`).
        self.detected.emit("rdp_detected", 4, {"processes": names})

    # ------------------------------------------------------------------
    # Bloklangan tugmalar
    # ------------------------------------------------------------------
    def report_blocked_key(self, code: str) -> None:
        """
        `lockdown` observer'i - HOOK THREAD'idan chaqiriladi.

        Bu yerda faqat hisoblagich yangilanadi va Qt signali chiqariladi;
        signal UI thread'iga Qt tomonidan marshal qilinadi, ya'ni
        buferga yozish o'sha yerda bo'ladi.

        Oraliqdagi bosishlar yo'qolmaydi: ular sanaladi va keyingi
        hodisaning `repeats` maydonida ketadi.
        """
        if not self._active:
            return
        now = time.monotonic()
        last, repeats = self._hotkey_state.get(code, (0.0, 0))

        if now - last < _HOTKEY_COOLDOWN_S:
            self._hotkey_state[code] = (last, repeats + 1)
            return

        self._hotkey_state[code] = (now, 0)
        self.detected.emit("hotkey_blocked", 1, {"key": code, "repeats": repeats + 1})
