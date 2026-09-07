"""
Imtihon davomidagi fon nazorati: heartbeat va hodisalar buferi.

Ikkalasi ham backendning ikki bosqichli yozish modeliga mos ishlaydi:
client hodisani DARHOL yubormaydi, buferga yig'adi va 5 soniyada bir
marta bitta so'rovda jo'natadi. 500 mashina x sekundiga 1 so'rov o'rniga
500/5 = 100 so'rov/s bo'ladi.
"""

from __future__ import annotations

import logging
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from config import EVENT_BATCH_MAX, EVENT_FLUSH_INTERVAL_MS, HEARTBEAT_INTERVAL_MS
from core.errors import ClientError
from services.repositories import ProctoringRepository
from services.workers import ApiWorker, WorkerHolder

log = logging.getLogger(__name__)


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
        self._queue: deque = deque(maxlen=5000)
        self._online = True
        self._active = False

        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.setInterval(HEARTBEAT_INTERVAL_MS)
        self._heartbeat_timer.timeout.connect(self._send_heartbeat)

        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(EVENT_FLUSH_INTERVAL_MS)
        self._flush_timer.timeout.connect(self._flush_events)

    # ------------------------------------------------------------------
    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def pending_events(self) -> int:
        return len(self._queue)

    def start(self) -> None:
        if self._active:
            return
        self._active = True
        self._heartbeat_timer.start()
        self._flush_timer.start()
        # Birinchi heartbeat darhol: sessiya ochilgani dashboardda
        # 30 soniya kutmasdan ko'rinishi kerak.
        self._send_heartbeat()
        log.info("Sessiya nazorati boshlandi")

    def stop(self) -> None:
        if not self._active:
            return
        self._active = False
        self._heartbeat_timer.stop()
        self._flush_timer.stop()
        # Oxirgi buferni yuborishga urinamiz - aks holda yakunlashdan
        # oldingi 5 soniyadagi hodisalar yo'qoladi.
        self._flush_events()
        self._workers.wait_all(10_000)
        log.info("Sessiya nazorati to'xtadi")

    # ------------------------------------------------------------------
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
        if not self._active:
            return
        metrics = {
            "network_ok": self._online,
            "queued_events": len(self._queue),
        }
        metrics.update(self._system_metrics())
        worker = ApiWorker(self._repo.heartbeat, parent=self, **metrics)
        worker.succeeded.connect(self._on_heartbeat_ok)
        worker.failed.connect(self._on_request_failed)
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
        self._set_online(True)
        data = result or {}
        # `should_stop` - backend hisoblab bergan yagona bayroq
        # (`HeartbeatView`). Status ro'yxatini client tomonda takrorlash
        # kerak emas: terminal holatlar to'plami serverda o'zgarishi mumkin.
        if data.get("should_stop"):
            self.session_lost.emit(str(data.get("status") or "stopped"))

    def _flush_events(self) -> None:
        if not self._queue:
            return
        batch = []
        while self._queue and len(batch) < EVENT_BATCH_MAX:
            batch.append(self._queue.popleft())

        worker = ApiWorker(self._repo.send_events, batch, parent=self)
        worker.succeeded.connect(lambda _: self._set_online(True))
        # Yuborilmagan batch buferga QAYTARILADI (chapdan), tartib
        # saqlanadi. Proktorlikda "dalil yo'qoldi" holati bo'lmasligi kerak.
        worker.failed.connect(lambda message, code: self._requeue(batch, message, code))
        self._workers.run(worker)

    def _requeue(self, batch: list, message: str, code: str) -> None:
        self._set_online(False)
        for event in reversed(batch):
            self._queue.appendleft(event)
        log.warning("Hodisalarni yuborib bo'lmadi (%s): %s", code or "-", message)

    def _on_request_failed(self, message: str, code: str) -> None:
        if code in ("session_not_found", "session_forbidden"):
            self.session_lost.emit(code)
            return
        self._set_online(False)
        log.warning("Fon so'rovi muvaffaqiyatsiz (%s): %s", code or "-", message)

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
