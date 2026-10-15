"""
WebSocket orqali xabar yuborish.

Kanal strategiyasi (yuklama uchun kritik):

    zone.<id>       — proktorlar shu binoni kuzatadi
    region.<id>     — viloyat koordinatori
    session.<id>    — aniq bitta client (buyruqlar shu yerga)

Global kanal ATAYLAB YO'Q. 10 000 sessiyadan kelayotgan hodisalarni bitta
kanalga yig'ish Redis pub/sub'ni ham, brauzerni ham yiqitadi. Proktor
jismonan 20-30 sessiyani kuzata oladi, shuning uchun fan-out bino
darajasida cheklanadi.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from concurrent.futures import TimeoutError as FutureTimeout

from asgiref.sync import async_to_sync
from channels.layers import InMemoryChannelLayer, get_channel_layer

logger = logging.getLogger(__name__)

# Sinxron koddan `group_send` kutishining chegarasi. Realtime — qulaylik
# qatlami: Redis osilib qolsa so'rov/ingest thread'i shu vaqtdan ortiq
# turmasligi kerak.
SEND_TIMEOUT_S = 3.0


class _LayerLoop:
    """
    Jarayonga BITTA doimiy event loop (fon thread'i) — `group_send` shu yerda.

    NIMA UCHUN `async_to_sync(layer.group_send)` EMAS: sinxron thread'da
    (gunicorn view, Celery ingest) u har chaqiruvda YANGI event loop
    yaratadi, channels_redis esa ulanishlar pool'ini loop'ga bog'laydi —
    ya'ni har xabar Redis'ga yangi TCP ulanish ochib, loop yopilganda
    uni tashlardi. O'lchangan: 200 ta `group_send` = 207 ta yangi ulanish
    (~5 ms har biri). 5000 client'li yuklama sinovida shu ulanishlar
    TIME_WAIT da 14 000 dan oshib, Redis'ga ulanish xatolari boshlandi;
    uzilishdan keyingi hodisalar bo'ronida ephemeral portlar tugaydi
    (Linux'da ham — bir manzilga ~470 yangi ulanish/s). Doimiy loop'da
    pool tirik qoladi va ulanishlar qayta ishlatiladi.

    Loop dangasa ochiladi va PID bilan tekshiriladi: gunicorn
    `preload_app` / Celery prefork fork qilganda ota jarayonning
    thread'i bolaga o'tmaydi — bola o'z loop'ini ochadi.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._pid: int | None = None

    def _ensure(self) -> asyncio.AbstractEventLoop:
        pid = os.getpid()
        with self._lock:
            alive = self._thread is not None and self._thread.is_alive()
            if self._loop is None or self._pid != pid or not alive:
                loop = asyncio.new_event_loop()
                thread = threading.Thread(
                    target=loop.run_forever, name="channel-layer-loop", daemon=True
                )
                thread.start()
                self._loop, self._thread, self._pid = loop, thread, pid
            return self._loop

    def run(self, coro_factory, timeout: float):
        future = asyncio.run_coroutine_threadsafe(coro_factory(), self._ensure())
        try:
            return future.result(timeout)
        except FutureTimeout:
            future.cancel()
            raise


_LAYER_LOOP = _LayerLoop()


def group_send(group: str, message: dict, *, timeout: float = SEND_TIMEOUT_S) -> None:
    """
    Sinxron koddan guruhga xabar. Xato CHAQIRUVCHIGA ko'tariladi.

    In-memory layer (testlar) eski yo'lda qoladi: u ulanish ochmaydi, uning
    navbatlari esa iste'molchining loop'iga bog'langan — boshqa loop'dan
    yozish ularni buzardi.
    """
    layer = get_channel_layer()
    if layer is None:
        return
    if isinstance(layer, InMemoryChannelLayer):
        async_to_sync(layer.group_send)(group, message)
        return
    _LAYER_LOOP.run(lambda: layer.group_send(group, message), timeout)


def zone_group(zone_id: int | None) -> str:
    return f"zone.{zone_id or 0}"


def region_group(region_id: int | None) -> str:
    return f"region.{region_id or 0}"


def session_group(session_id: int) -> str:
    return f"session.{session_id}"


def _send(group: str, message: dict) -> None:
    try:
        group_send(group, message)
    except Exception as exc:
        # Realtime — qulaylik qatlami. U ishlamasa ham asosiy oqim davom etadi.
        logger.debug("WebSocket yuborishda xato (%s): %s", group, exc)


def broadcast_session_update(session, **fields) -> None:
    """
    Sessiya holati o'zgarganda dashboard'ni yangilaydi.

    Frontend (`useLiveMonitor.ts`) `session_update` xabarini kutadi —
    busiz jonli kuzatuv jadvalidagi status faqat sahifa yangilanganda
    o'zgaradi.
    """
    _send(
        zone_group(session.zone_id),
        {
            "type": "session.update",
            "payload": {
                "session_id": session.pk,
                "public_id": str(session.public_id),
                "status": session.status,
                "risk_score": session.risk_score,
                **fields,
            },
        },
    )


def send_client_command(*, session_id: int, command: str, payload: dict | None = None) -> None:
    """
    Client'ga buyruq (ogohlantirish, chetlashtirish, davom ettirish).

    Aynan shu ikki tomonlama kanal sababli client uchun WebSocket kerak
    (SSE emas): proktor talabgorning ekraniga real vaqtda ta'sir qila
    olishi kerak.
    """
    _send(
        session_group(session_id),
        {"type": "client.command", "payload": {"command": command, **(payload or {})}},
    )


