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

  MASOFAVIY BOSHQARUV VA VIRTUALIZATSIYA - ALOHIDA thread'da
    skanerlanadi (`threat_scanner`). Jarayonlar ro'yxatini o'qish
    sekin mashinada 100 ms, imzolarni tekshirish esa undan ham
    ko'proq oladi va UI thread'ida u WebView'ni tutib qolardi.

    Bu yerda modul o'z qoidasidan CHETGA CHIQADI va topilganini
    darhol YO'Q QILADI. Sabab: imtihon o'rtasida ishga tushirilgan
    AnyDesk "keyinroq ko'rib chiqiladigan hodisa" emas - u o'sha
    lahzada ekranni boshqa odamga ochib beradi. Qolgan hamma
    narsada qoida kuchda: kuzatamiz va xabar qilamiz.

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


class _ThreatScanner(QThread):
    """
    Masofaviy boshqaruv, virtualizatsiya va yordamchi vositalarni
    imtihon DAVOMIDA kuzatadi.

    Ilgari bu sinf jarayonlarni FAQAT NOM bo'yicha solishtirardi va
    ro'yxat serverdan kelardi (`Setting.rdp_objects`). Bu tekshiruvni
    chetlab o'tish uchun `AnyDesk.exe` ni qayta nomlash yetardi -
    ya'ni himoya eng sodda hujumga ham dosh bermasdi. Endi qaror
    `threat_scanner` da: PE resursi, Authenticode imzosi, xizmat nomi
    va tinglanayotgan port bo'yicha.

    SERVERDAGI RO'YXAT YO'QOLMADI - u ichki katalogga QO'SHILADI
    (`_rules_from_names`). Administrator panelga yangi dastur
    qo'shganda uni butun parkka tarqatish uchun client'ni qayta
    yig'ish shart emas.

    TOPILGANI DARHOL YO'Q QILINADI. Ishga tushishdagi tozalash faqat
    o'sha paytdagi holatni ko'radi; imtihon o'rtasida ishga tushirilgan
    AnyDesk esa aynan eng xavfli holat va uni keyingi skanergacha
    qoldirish mumkin emas. Hodisa YO'Q QILINGAN holatda ham yoziladi -
    bayonnomada "urinish bo'lgan" degan yozuv qolishi kerak.

    Faqat O'ZGARISHLAR haqida xabar beradi (edge detection): dastur
    ishlab turgani har 15 soniyada takroriy hodisa bo'lmasligi kerak,
    lekin u yopilib qayta ochilsa - bu yangi hodisa.
    """

    #: Yangi topilgan `Finding` obyektlari.
    found = pyqtSignal(list)

    def __init__(self, rdp_config: dict, allow: list, parent=None) -> None:
        super().__init__(parent)
        from services import threat_rules

        # TARTIB QARORI: aniq ichki qoidalar -> server ro'yxati ->
        # kalit so'z tori. Qidiruv birinchi mos kelgan qoidada
        # to'xtaydi, shuning uchun har uchala qatlamning o'rni muhim:
        #
        #   ichki katalog OLDINDA, chunki uning belgilari kuchliroq
        #     (imzo, `OriginalFilename`) va `blocking` bayrog'i
        #     tekshirilgan. Serverdagi bir nomli, faqat jarayon nomi
        #     bilan yozilgan dublikat oldinda tursa, u AnyDesk'ni
        #     to'smaydigan qoida sifatida qayd etardi;
        #   server ro'yxati O'RTADA — u katalogda YO'Q dasturlarni
        #     qo'shadi;
        #   `FALLBACK_RULES` OXIRIDA — "remote desktop" kabi keng
        #     kalit so'z undan keyingi har qanday aniq qoidani
        #     soyalab qo'yardi.
        self._rules = (
            threat_rules.BUILTIN_RULES
            + _rules_from_config(rdp_config)
            + threat_rules.FALLBACK_RULES
        )
        self._allow = [str(item).strip().lower() for item in (allow or []) if str(item).strip()]
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
        from services import threat_scanner

        while self._running:
            try:
                report = threat_scanner.scan(rules=self._rules, allow=self._allow)
                fresh = [
                    finding
                    for finding in report.findings
                    if (finding.code, finding.kind, finding.name, finding.service)
                    not in self._seen
                ]
                # Holat AVVAL yangilanadi: `neutralize` sekin (xizmat
                # to'xtashini 8 soniyagacha kutadi) va shu paytda
                # `stop()` kelishi mumkin.
                self._seen = {
                    (item.code, item.kind, item.name, item.service)
                    for item in report.findings
                }
                if fresh:
                    partial = threat_scanner.ThreatReport(
                        findings=fresh, elevated=report.elevated
                    )
                    threat_scanner.neutralize(partial)
                    self.found.emit(fresh)
            except Exception:
                # Skanerlashda xato (huquq, WMI, o'chib ketgan jarayon).
                # Kuzatuv to'xtamaydi - keyingi tsiklda qayta uriniladi.
                log.debug("Tahdid skanerida xato", exc_info=True)

            # Kichik bo'laklarda uxlaymiz: `stop()` chaqirilganda
            # thread 15 soniya kutib turmasligi kerak - dastur
            # yopilishi shuncha cho'zilardi.
            for _ in range(_PROCESS_SCAN_MS // 250):
                if not self._running:
                    return
                self.msleep(250)


def _rules_from_config(rdp_config: dict) -> tuple:
    """
    Serverdagi `Setting.rdp_objects` yozuvlarini qoidaga aylantiradi.

    IKKI SHAKL QO'LLAB-QUVVATLANADI va bu ataylab:

      `rules`     — to'liq yozuv (imzo, `OriginalFilename`, xizmat,
                    port). Yangi backend shuni beradi.
      `processes` — faqat nomlar ro'yxati. ESKI backend bilan
                    ishlaydigan client uchun saqlangan: server
                    yangilanmagan o'rnatishda `rules` umuman
                    kelmaydi va o'shanda nomlar bo'yicha qidiruv
                    hech yo'qdan yaxshiroq.

    Ikkalasi ham kelsa `processes` E'TIBORGA OLINMAYDI: u `rules`
    ichidagi `names` ning nusxasi va uni ikkinchi marta qo'shish
    bitta dastur uchun ikkita hodisa berardi.

    Nom `AnyDesk.exe` ham, `anydesk` ham yozilishi mumkin — kengaytma
    o'zi qo'shiladi.
    """
    from services.threat_rules import ThreatRule

    config = rdp_config or {}
    rules: list = []

    for raw in config.get("rules") or []:
        try:
            code = str(raw.get("code") or "").strip().lower()
            if not code:
                continue
            rules.append(
                ThreatRule(
                    code=code,
                    label=str(raw.get("label") or code),
                    category=str(raw.get("category") or "remote"),
                    # `is_blocking` panelda ochiq qo'yilgan bo'lsagina
                    # to'sadi — standart qiymat `False`.
                    blocking=bool(raw.get("blocking")),
                    publishers=_lowered(raw.get("publishers")),
                    originals=_exe_names(raw.get("originals")),
                    products=_lowered(raw.get("products")),
                    names=_exe_names(raw.get("names")),
                    services=_lowered(raw.get("services")),
                    ports=tuple(
                        port for port in (raw.get("ports") or []) if isinstance(port, int)
                    ),
                    hint="Bu dastur administrator ro'yxatida taqiqlangan.",
                )
            )
        except (AttributeError, TypeError, ValueError):
            # Bitta buzilgan yozuv butun ro'yxatni yo'qotmasligi kerak.
            log.warning("Serverdagi tahdid qoidasi o'qilmadi: %r", raw)

    if rules:
        return tuple(rules)

    names = _exe_names(config.get("processes"))
    if not names:
        return ()
    return (
        ThreatRule(
            code="server_list",
            label="Taqiqlangan dastur (panel ro'yxati)",
            category="remote",
            blocking=False,
            originals=names,
            names=names,
            hint="Bu dastur administrator ro'yxatida taqiqlangan.",
        ),
    )


def _lowered(values) -> tuple:
    return tuple(
        sorted({str(item).strip().lower() for item in (values or []) if str(item).strip()})
    )


def _exe_names(values) -> tuple:
    """Nomlarni kichik harfga o'tkazadi va `.exe` kengaytmasini qo'shadi."""
    names = set()
    for raw in values or []:
        name = str(raw or "").strip().lower()
        if not name:
            continue
        names.add(name if name.endswith(".exe") else name + ".exe")
    return tuple(sorted(names))


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
        self._scanner: Optional[_ThreatScanner] = None
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

        # --- Masofaviy boshqaruv / virtualizatsiya ---
        if rdp.get("enabled", True):
            from config import THREAT_SCAN_ALLOW

            # Ro'yxat BO'SH BO'LSA HAM ishga tushadi va bu o'zgarish
            # ataylab. Ilgari bo'sh ro'yxat kuzatuvni butunlay
            # o'chirardi, ya'ni panelda `RdpObject` yozuvlarini
            # qo'shishni unutish jimgina "himoya yo'q" holatini
            # yaratardi. Endi ichki katalog baribir ishlaydi, server
            # ro'yxati esa unga QO'SHILADI.
            self._scanner = _ThreatScanner(rdp, THREAT_SCAN_ALLOW, parent=self)
            self._scanner.found.connect(self._on_threats_found)
            self._scanner.start()
            log.info(
                "Tahdid kuzatuvi boshlandi (panel ro'yxati: %s ta qoida, %s ta nom)",
                len(rdp.get("rules") or []), len(rdp.get("processes") or []),
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
    # Masofaviy boshqaruv / virtualizatsiya
    # ------------------------------------------------------------------
    def _on_threats_found(self, findings: list) -> None:
        """
        Topilmalarni hodisa oqimiga o'tkazadi.

        HODISA TURI BO'YICHA GURUHLANADI. Bitta skanerda AnyDesk ham,
        VirtualBox ham topilishi mumkin va ularni bitta hodisaga
        qo'shish panelda ikkita butunlay boshqa muammoni bitta
        qatorga siqib qo'yardi: `rdp_detected` va `vm_detected`
        frontendda ham har xil turkumga tushadi (`utils/events.js`).

        JIDDIYLIK YO'Q QILINGANIGA QARAB O'ZGARADI. Yopib bo'lgan
        dastur - YUQORI (3): u imtihonga ta'sir qilmadi, lekin
        urinish bo'lgan. Yopib bo'lmagani - KRITIK (4) va u
        write-behind buferini chetlab o'tib darhol yoziladi
        (`ingest.IMMEDIATE_SEVERITY`), ya'ni proktor ekranida o'sha
        zahoti ko'rinadi - masofaviy boshqaruv HOZIR ishlab turibdi.
        """
        if not self._active:
            return

        grouped: dict = {}
        for finding in findings:
            if finding.neutralized:
                log.warning("Imtihon davomida yo'q qilindi: %s", finding.describe())
            else:
                log.error(
                    "Imtihon davomida YO'Q QILINMADI: %s | sabab: %s",
                    finding.describe(), finding.reason,
                )
            grouped.setdefault(finding.event_type, []).append(finding)

        for event_type, items in grouped.items():
            severity = 3 if all(item.neutralized for item in items) else 4
            self.detected.emit(
                event_type,
                severity,
                {
                    "processes": [item.name or item.service for item in items if item.name or item.service],
                    "codes": [item.code for item in items],
                    "neutralized": all(item.neutralized for item in items),
                    # Birinchi topilmaning dalili — payload'da uzunlik
                    # chegarasi bor (`ingest._BROADCAST_DETAIL_KEYS`),
                    # shuning uchun hammasini yozishning ma'nosi yo'q.
                    "evidence": items[0].evidence,
                },
            )

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
