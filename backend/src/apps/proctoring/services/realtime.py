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

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


def zone_group(zone_id: int | None) -> str:
    return f"zone.{zone_id or 0}"


def region_group(region_id: int | None) -> str:
    return f"region.{region_id or 0}"


def session_group(session_id: int) -> str:
    return f"session.{session_id}"


def _send(group: str, message: dict) -> None:
    try:
        layer = get_channel_layer()
        if layer is None:
            return
        async_to_sync(layer.group_send)(group, message)
    except Exception as exc:
        # Realtime — qulaylik qatlami. U ishlamasa ham asosiy oqim davom etadi.
        logger.debug("WebSocket yuborishda xato (%s): %s", group, exc)


def broadcast_session_update(session, **fields) -> None:
    """
    Sessiya holati o'zgarganda dashboard'ni yangilaydi.

    Frontend (`useLiveMonitor.js`) `session_update` xabarini kutadi —
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


