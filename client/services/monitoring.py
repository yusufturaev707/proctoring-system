"""
Imtihon davomidagi fon nazorati: heartbeat va hodisalar buferi.

Ikkalasi ham backendning ikki bosqichli yozish modeliga mos ishlaydi:
client hodisani DARHOL yubormaydi, buferga yig'adi va 5 soniyada bir
marta bitta so'rovda jo'natadi. 500 mashina x sekundiga 1 so'rov o'rniga
500/5 = 100 so'rov/s bo'ladi.
"""

from __future__ import annotations

import logging
import random
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from config import EVENT_BATCH_MAX
from core.errors import ClientError
from services import net_policy, runtime_settings
from services.network_status import on_power_resumed
from services.repositories import ProctoringRepository
from services.workers import ApiWorker, WorkerHolder

log = logging.getLogger(__name__)

#: Hodisa buferi xatodan keyin qancha kutadi (soniya): 5 -> 10 -> 20 ...
#: chegara 120, jitter bilan (`net_policy.Backoff`). Ilgari bufer har
#: 5 s da urinardi — server tushganda 5000 mashina × 0.2 so'rov/s, u
#: turganda esa hamma to'plangan navbatini BIR LAHZADA yuborardi.
_FLUSH_BACKOFF_BASE_S = 5.0
_FLUSH_BACKOFF_CAP_S = 120.0

#: Heartbeat o'tgach (aloqa bor) kutib qolgan buferni shu oraliqda,
#: tasodifiy paytda yuborish (soniya).
_RECOVERY_SPREAD_S = 5.0

#: Uyg'ongandan keyingi birinchi heartbeat shu oraliqda, tasodifiy
#: paytda (ms) — butun zal bir vaqtda uyg'onsa ham bir lahzada urmaydi.
_RESUME_JITTER_MS = 3_000


def _is_offline_error(exc) -> bool:
    """
    "Aloqa yo'q" deb ko'rsatiladigan xato: serverga yetib bo'lmadi yoki
    u vaqtincha javob bermayapti. 400/403 kabi javoblar — server BOR,
    ekranda "aloqa yo'q" deyish yolg'on bo'lardi.
    """
    code = getattr(exc, "code", "") or ""
    status = int(getattr(exc, "status", 0) or 0)
    return code in ("network", "server_unavailable", "invalid_response") or status >= 500


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionMonitor(QObject):
    """
    Sessiya faol paytda ishlaydigan fon nazorati.

    `start()` faqat sessiya tokeni olinganidan keyin chaqiriladi;
    `stop()` esa sessiya yakunlanganda yoki sahifadan chiqilganda.
    """

    #: Backend sessiyani yakunlagan/chetlashtirgan bo'lsa.
    session_lost = pyqtSignal(str)
    #: Tarmoq holati o'zgardi (True - aloqa bor).
    network_changed = pyqtSignal(bool)

    def __init__(self, repo: Optional[ProctoringRepository] = None, parent=None) -> None:
        super().__init__(parent)
        self._repo = repo or ProctoringRepository()
        self._workers = WorkerHolder()
        # `deque(maxlen=...)` - tarmoq uzoq uzilib qolsa xotira cheksiz
        # o'smaydi: eng eski hodisalar tushib qoladi. Yo'qotish yomon,
        # lekin client'ning xotira yetishmasligidan qulashi battar.
        #
        # Hajm `start()` da imtihon profilidan qayta o'rnatiladi
        # (`network.offline_buffer_size`); bu yerda - `.env` zaxirasi.
        self._queue: deque = deque(
            maxlen=runtime_settings.fallback("network.offline_buffer_size")
        )
        self._online = True
        self._active = False
        #: Client bajargan yuz solishtirishlari soni (JAMI).
        #
        # Serverga faqat MUVAFFAQIYATSIZ tekshiruvlar yuboriladi
        # (solishtirish clientda), ya'ni "nechta tekshiruv bo'ldi"
        # degan savolga faqat client javob bera oladi. Qiymat
        # heartbeat bilan ketadi va Redis'dagi `face_checks` ga
        # YOZILADI - egasi bitta bo'lgani uchun ikki marta sanash
        # ham, poyga ham yo'q.
        self._face_checks = 0

        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.setInterval(
            runtime_settings.fallback("network.heartbeat_interval")
        )
        self._heartbeat_timer.timeout.connect(self._send_heartbeat)

        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(
            runtime_settings.fallback("network.event_batch_interval")
        )
        self._flush_timer.timeout.connect(self._flush_events)

        # Bitta uchuvchi so'rov: heartbeat oralig'i (30 s) timeout'dan
        # (ulanish 10 + o'qish 30 s) qisqa, ya'ni uzilgan tarmoqda har
        # tsikl yangi thread ochib, ular to'planib borardi. Bufer uchun
        # esa bu TARTIB masalasi ham: parallel batch'lar hodisalarni
        # aralashtirib yuborardi.
        self._heartbeat_busy = False
        self._flushing = False
        self._heartbeat_backoff = net_policy.Backoff(base=5.0, cap=_FLUSH_BACKOFF_CAP_S)
        self._flush_backoff = net_policy.Backoff(
            base=_FLUSH_BACKOFF_BASE_S, cap=_FLUSH_BACKOFF_CAP_S
        )
        on_power_resumed(self._on_power_resumed)

    # ------------------------------------------------------------------
    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def pending_events(self) -> int:
        return len(self._queue)

    def start(self, config: Optional[dict] = None) -> None:
        """
        `config` - IMTIHON PROFILI (`AppState.config`).

        Oraliqlar va bufer hajmi SHU YERDA o'qiladi, konstruktorda emas:
        sahifa bitta, imtihonlar esa ko'p va har birining profili boshqa
        bo'lishi mumkin. Ilgari client bu uchta qiymatni umuman
        serverdan olmasdi - panelda "Heartbeat intervali" bor edi,
        lekin hamma mashina `.env` dagi 30 s bilan ishlardi.
        """
        if self._active:
            return
        self._heartbeat_timer.setInterval(
            runtime_settings.get(config, "network.heartbeat_interval")
        )
        self._flush_timer.setInterval(
            runtime_settings.get(config, "network.event_batch_interval")
        )
        size = runtime_settings.get(config, "network.offline_buffer_size")
        if size != self._queue.maxlen:
            # Sessiyadan oldin navbatga tushgan hodisalar SAQLANADI
            # (yangi deque eskisidan to'ldiriladi) - hajm o'zgargani
            # uchun dalil yo'qolmasligi kerak.
            self._queue = deque(self._queue, maxlen=size)
        self._active = True
        self._heartbeat_busy = False
        self._flushing = False
        self._heartbeat_backoff.success()
        self._flush_backoff.success()
        self._heartbeat_timer.start()
        self._flush_timer.start()
        # Birinchi heartbeat darhol: sessiya ochilgani dashboardda
        # 30 soniya kutmasdan ko'rinishi kerak.
        self._send_heartbeat()
        log.info(
            "Sessiya nazorati boshlandi (heartbeat %s ms, hodisalar %s ms, bufer %s)",
            self._heartbeat_timer.interval(), self._flush_timer.interval(),
            self._queue.maxlen,
        )

    def stop(self) -> None:
        if not self._active:
            return
        self._active = False
        self._heartbeat_timer.stop()
        self._flush_timer.stop()
        # Oxirgi buferni yuborishga urinamiz - aks holda yakunlashdan
        # oldingi 5 soniyadagi hodisalar yo'qoladi. Backoff va "bitta
        # uchuvchi" qoidasi bu yerda CHETLAB o'tiladi: bu oxirgi imkon.
        self._flush_events(force=True)
        self._workers.wait_all(10_000)
        log.info("Sessiya nazorati to'xtadi")

    # ------------------------------------------------------------------
    def set_face_checks(self, total: int) -> None:
        """Yuz tekshiruvlari sonini yangilaydi (keyingi heartbeat bilan ketadi)."""
        try:
            self._face_checks = max(0, int(total))
        except (TypeError, ValueError):
            pass

    def push_event(self, event_type: str, *, severity: int = 1, payload: Optional[dict] = None) -> None:
        """
        Hodisani buferga qo'yadi.

        `client_event_id` - takroriy yuborishda dublikatni to'sadi
        (backend `ignore_conflicts=True` bilan yozadi). Tarmoq uzilib,
        batch qayta yuborilsa, bir hodisa ikki marta yozilmaydi.
        """
        self._queue.append(
            {
                "client_event_id": uuid.uuid4().hex,
                "type": event_type,
                "severity": int(severity),
                "occurred_at": now_iso(),
                "payload": payload or {},
            }
        )

    # ------------------------------------------------------------------
    def _send_heartbeat(self) -> None:
        if not self._active or self._heartbeat_busy:
            return
        if not self._heartbeat_backoff.ready():
            # Server `Retry-After` bilan "kuting" degan — tsikl o'tkazib
            # yuboriladi. Oddiy uzilishda bu to'siq yo'q: heartbeat
            # aloqa tiklanganini bilishning asosiy yo'li.
            return
        metrics = {
            "network_ok": self._online,
            "queued_events": len(self._queue),
            "face_checks": self._face_checks,
        }
        metrics.update(self._system_metrics())
        self._heartbeat_busy = True
        worker = ApiWorker(self._repo.heartbeat, parent=self, **metrics)
        worker.succeeded.connect(self._on_heartbeat_ok)
        worker.failed_error.connect(self._on_heartbeat_failed)
        self._workers.run(worker)

    @staticmethod
    def _system_metrics() -> dict:
        """CPU/xotira - psutil bo'lmasa jimgina o'tkazib yuboriladi."""
        try:
            import psutil

            return {
                "cpu_percent": float(psutil.cpu_percent(interval=None)),
                "memory_percent": float(psutil.virtual_memory().percent),
            }
        except Exception:
            return {}

    def _on_heartbeat_ok(self, result) -> None:
        self._heartbeat_busy = False
        self._heartbeat_backoff.success()
        self._set_online(True)
        # Aloqa bor — backoff'da kutayotgan bufer bir daqiqa kutmasin,
        # lekin tasodifiy paytda (hamma bir lahzada emas).
        self._flush_backoff.nudge(_RECOVERY_SPREAD_S)
        data = result if isinstance(result, dict) else {}
        # `should_stop` - backend hisoblab bergan yagona bayroq
        # (`HeartbeatView`). Status ro'yxatini client tomonda takrorlash
        # kerak emas: terminal holatlar to'plami serverda o'zgarishi mumkin.
        if data.get("should_stop"):
            self.session_lost.emit(str(data.get("status") or "stopped"))

    def _flush_events(self, force: bool = False) -> None:
        if not self._queue:
            return
        if not force and (self._flushing or not self._flush_backoff.ready()):
            return
        batch = []
        while self._queue and len(batch) < EVENT_BATCH_MAX:
            batch.append(self._queue.popleft())

        self._flushing = True
        worker = ApiWorker(self._repo.send_events, batch, parent=self)
        worker.succeeded.connect(self._on_flush_ok)
        # Yuborilmagan batch buferga QAYTARILADI (chapdan), tartib
        # saqlanadi. Proktorlikda "dalil yo'qoldi" holati bo'lmasligi kerak.
        worker.failed_error.connect(lambda exc: self._requeue(batch, exc))
        self._workers.run(worker)

    def _on_flush_ok(self, _result) -> None:
        self._flushing = False
        self._flush_backoff.success()
        self._set_online(True)

    def _requeue(self, batch: list, exc) -> None:
        self._flushing = False
        code = getattr(exc, "code", "") or ""
        status = int(getattr(exc, "status", 0) or 0)
        if code in ("session_not_found", "session_forbidden"):
            # Sessiya yopilgan — qayta yuborishning ma'nosi yo'q.
            if self._active:
                self.session_lost.emit(code)
            return
        if net_policy.is_poison_payload(status):
            # "ZAHARLI" BATCH: server uni tuzilishi uchun rad etdi (400)
            # va har takror xuddi shu javobni oladi. Navbat boshiga
            # qaytarilsa, orqasidagi HAMMA hodisa abadiy kutib qolardi.
            # Yo'qotish log'da qoladi (soni va turlari, payload'siz).
            log.error(
                "Hodisalar batch'i server tomonidan rad etildi (%s %s) - %s ta hodisa "
                "tashlandi: %s",
                status, code or "-", len(batch),
                sorted({str(item.get("type")) for item in batch}),
            )
            return
        for event in reversed(batch):
            self._queue.appendleft(event)
        delay = self._flush_backoff.failure(getattr(exc, "retry_after", None))
        if _is_offline_error(exc):
            self._set_online(False)
        log.warning(
            "Hodisalarni yuborib bo'lmadi (%s): %s - %.0f s dan keyin qayta",
            code or "-", getattr(exc, "message", exc), delay,
        )

    def _on_heartbeat_failed(self, exc) -> None:
        self._heartbeat_busy = False
        code = getattr(exc, "code", "") or ""
        if code in ("session_not_found", "session_forbidden"):
            if self._active:
                self.session_lost.emit(code)
            return
        retry_after = getattr(exc, "retry_after", None)
        if retry_after:
            self._heartbeat_backoff.failure(retry_after)
        if _is_offline_error(exc):
            self._set_online(False)
        log.warning(
            "Heartbeat muvaffaqiyatsiz (%s): %s", code or "-", getattr(exc, "message", exc)
        )

    def _on_power_resumed(self) -> None:
        """
        Kompyuter uyqudan uyg'ondi: aloqani DARHOL (jitter bilan) tekshirish.

        Uyqu paytida taymerlar to'xtagan, TCP ulanishlar esa o'lgan;
        keyingi heartbeat 30 s kutmasin — proktor panelida mashina shu
        vaqt "aloqa yo'q" bo'lib turardi.
        """
        if not self._active:
            return
        self._heartbeat_backoff.success()
        self._flush_backoff.nudge(_RECOVERY_SPREAD_S)
        QTimer.singleShot(random.randint(0, _RESUME_JITTER_MS), self._send_heartbeat)

    def _set_online(self, online: bool) -> None:
        if online != self._online:
            self._online = online
            self.network_changed.emit(online)


class ClientErrorGuard:
    """
    `with` bloki ichidagi `ClientError` ni yutadi va log'ga yozadi.

    Fon amallari (masalan yakunlashda oxirgi hodisani yuborish) asosiy
    oqimni to'xtatmasligi kerak.
    """

    def __init__(self, context: str) -> None:
        self._context = context

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None and issubclass(exc_type, ClientError):
            log.warning("%s: %s", self._context, exc)
            return True
        return False
