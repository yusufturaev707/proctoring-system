"""
WebSocket consumer'lari.

Ikki xil client, ikki xil ehtiyoj:

  MonitorConsumer — proktor dashboard'i. JWT bilan autentifikatsiya,
                    bino/viloyat guruhlariga obuna bo'ladi.

  ClientConsumer  — PyQt6 desktop. Sessiya tokeni bilan, o'z sessiya
                    guruhiga qo'shiladi va buyruqlarni qabul qiladi.
"""

from __future__ import annotations

import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from redis.exceptions import RedisError

from apps.proctoring.services.realtime import region_group, session_group, zone_group

logger = logging.getLogger(__name__)

CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
# RFC 6455 "Internal Error": server vaqtincha xizmat qila olmadi, client
# backoff bilan qayta ulanadi. 44xx dan farqi — token ham, ruxsat ham
# joyida, ya'ni qayta urinish ma'noli.
CLOSE_LAYER_UNAVAILABLE = 1011

# Channel layer'ning Redis'i ishlamay qolgandagi xatolar. `OSError` ham
# kiradi: Windows'da o'lik socket ba'zan redis-py o'ramidan tashqarida
# `WinError 121` bo'lib chiqadi.
_LAYER_ERRORS = (RedisError, OSError)


class MonitorConsumer(AsyncJsonWebsocketConsumer):
    """
    Proktor dashboard'i.

    Ulanish: `ws://host/ws/monitor/?token=<JWT access>`

    Token query parametrida keladi, chunki brauzer WebSocket API'si
    maxsus header qo'shishga imkon bermaydi. Bu qabul qilinadigan
    kelishuv: token qisqa muddatli (30 daq) va ulanish TLS ostida.
    """

    async def connect(self):
        self.user = await self._authenticate()
        if self.user is None:
            await self.close(code=CLOSE_UNAUTHORIZED)
            return

        if not await self._has_permission():
            await self.close(code=CLOSE_FORBIDDEN)
            return

        self.groups_joined: list[str] = []
        await self.accept()
        await self.send_json({"type": "connected", "user": self.user["username"]})

    async def disconnect(self, code):
        # Uzilishda Redis xatosi YUTILADI: ulanish baribir yopilyapti va
        # istisno faqat "Exception in ASGI application" shovqini berardi.
        # Tashlab ketilgan a'zolik o'zi eskiradi — o'lik kanalga
        # yuborilgan xabar `expiry` (20 s) dan keyin o'chadi, guruh
        # yozuvi esa `group_expiry` da.
        for group in getattr(self, "groups_joined", []):
            try:
                await self.channel_layer.group_discard(group, self.channel_name)
            except _LAYER_ERRORS as exc:
                logger.warning("monitor: guruhdan chiqib bo'lmadi (%s): %s", group, exc)

    async def receive_json(self, content, **kwargs):
        action = content.get("action")

        try:
            if action == "subscribe":
                await self._subscribe(content.get("zones", []), content.get("regions", []))
            elif action == "unsubscribe":
                await self._unsubscribe(content.get("zones", []), content.get("regions", []))
            elif action == "ping":
                await self.send_json({"type": "pong"})
        except _LAYER_ERRORS as exc:
            # Channel layer ichidagi qayta urinishlar (`_channel_layer_host`)
            # ham yordam bermadi — Redis haqiqatan ishlamayapti. Yarim
            # obunali ulanishni tirik qoldirish panelda "ulangan, lekin
            # hodisa kelmaydi" degan eng yomon holatni berardi; ochiq
            # yopilish esa client'ni backoff bilan qayta ulanishga
            # majbur qiladi.
            logger.warning("monitor: channel layer ishlamadi (%s): %s", action, exc)
            await self.close(code=CLOSE_LAYER_UNAVAILABLE)

    async def _subscribe(self, zones: list, regions: list) -> None:
        """
        Guruhlarga obuna.

        Foydalanuvchi o'z viloyatidan tashqaridagi binoga obuna bo'la
        olmaydi — bu WebSocket orqali ma'lumot sizib chiqishining
        oldini oladi.
        """
        allowed_region = self.user.get("region_id")

        for zone_id in zones[:50]:  # bir ulanishga cheklov
            if allowed_region and not await self._zone_in_region(zone_id, allowed_region):
                continue
            await self._join(zone_group(int(zone_id)))

        for region_id in regions[:10]:
            if allowed_region and int(region_id) != allowed_region:
                continue
            await self._join(region_group(int(region_id)))

        await self.send_json({"type": "subscribed", "groups": self.groups_joined})

    async def _join(self, group: str) -> None:
        # `group_add` takroriy obunada ham chaqiriladi — u guruh
        # a'zoligining muddatini yangilaydi; ro'yxatga esa bir marta
        # yoziladi (panel zonalar o'zgarganda qayta obuna bo'ladi va
        # ro'yxat har safar o'sib borardi).
        await self.channel_layer.group_add(group, self.channel_name)
        if group not in self.groups_joined:
            self.groups_joined.append(group)

    async def _unsubscribe(self, zones: list, regions: list) -> None:
        targets = [zone_group(int(z)) for z in zones] + [region_group(int(r)) for r in regions]
        for group in targets:
            await self.channel_layer.group_discard(group, self.channel_name)
            if group in self.groups_joined:
                self.groups_joined.remove(group)

    # --- Guruhdan keladigan xabarlar ---
    async def proctoring_event(self, event):
        await self.send_json({"type": "event", "payload": event["payload"]})

    async def session_update(self, event):
        await self.send_json({"type": "session_update", "payload": event["payload"]})

    # --- Yordamchilar ---
    async def _authenticate(self) -> dict | None:
        from urllib.parse import parse_qs

        query = parse_qs(self.scope.get("query_string", b"").decode())
        raw_token = (query.get("token") or [None])[0]
        if not raw_token:
            return None
        return await self._resolve_user(raw_token)

    @database_sync_to_async
    def _resolve_user(self, raw_token: str) -> dict | None:
        from rest_framework_simplejwt.exceptions import TokenError
        from rest_framework_simplejwt.tokens import AccessToken

        from apps.users.models import User

        try:
            token = AccessToken(raw_token)
            user = User.objects.select_related("role").get(pk=token["user_id"], is_active=True)
        except (TokenError, KeyError, User.DoesNotExist):
            return None

        return {
            # Viloyatsiz viloyat xodimi — HTTP'dagi `HasRegionAssignment`
            # bilan bir xil qoida (`_has_permission` rad etadi). Usiz u bu
            # kanal orqali barcha binolarga obuna bo'la olardi:
            # `_subscribe` cheklovni faqat `region_id` bor bo'lganda
            # qo'llaydi. 4401 EMAS, 4403: token yaroqli va panel uni
            # yangilab qayta-qayta ulanishga urinmasligi kerak.
            "lacks_region": user.lacks_region,
            "id": user.pk,
            "username": user.username,
            # `is_region_scoped` — HTTP bilan bir xil manba: ilgari bu
            # yerda `is_superuser` edi va respublika roli (`is_global`)
            # bilan kelgan Administrator o'z viloyatiga qamalib qolardi.
            "region_id": user.region_id if user.is_region_scoped else None,
            "is_superuser": user.is_superuser,
            "permissions": user.permission_codes(),
        }

    async def _has_permission(self) -> bool:
        if self.user.get("lacks_region"):
            return False
        permissions = self.user.get("permissions", [])
        return (
            self.user["is_superuser"]
            or "*" in permissions
            or "sessions.view" in permissions
            or "sessions.*" in permissions
        )

    @database_sync_to_async
    def _zone_in_region(self, zone_id, region_id) -> bool:
        from apps.regions.models import Zone

        return Zone.objects.filter(pk=zone_id, region_id=region_id).exists()


class ClientConsumer(AsyncJsonWebsocketConsumer):
    """
    PyQt6 desktop client.

    Ulanish: `ws://host/ws/client/` + `X-Proctoring-Session` header'i
    (yoki eski yo'l: `?proctoring_session=<opaque>` — `_authenticate`
    ga qarang).

    Client uchun WebSocket (SSE emas) tanlangan, chunki kanal ikki
    tomonlama bo'lishi shart: proktor "ogohlantirish ko'rsat",
    "sessiyani yop", "davom ettir" buyruqlarini yuboradi.
    """

    async def connect(self):
        self.session_info = await self._authenticate()
        if self.session_info is None:
            await self.close(code=CLOSE_UNAUTHORIZED)
            return

        group = session_group(self.session_info["session_id"])
        try:
            await self.channel_layer.group_add(group, self.channel_name)
        except _LAYER_ERRORS as exc:
            # Guruhsiz ulanish proktor buyruqlarini ("to'xtat",
            # "ogohlantir") hech qachon olmaydi — uni qabul qilish
            # nazorat kanali ishlayapti degan yolg'on bo'lardi.
            logger.warning("client: channel layer ishlamadi: %s", exc)
            await self.close(code=CLOSE_LAYER_UNAVAILABLE)
            return
        self.group = group
        await self.accept()
        await self.send_json(
            {"type": "connected", "session": self.session_info["public_id"]}
        )

    async def disconnect(self, code):
        group = getattr(self, "group", None)
        if group:
            try:
                await self.channel_layer.group_discard(group, self.channel_name)
            except _LAYER_ERRORS as exc:
                logger.warning("client: guruhdan chiqib bo'lmadi (%s): %s", group, exc)

    async def receive_json(self, content, **kwargs):
        action = content.get("action")

        if action == "heartbeat":
            # WebSocket heartbeat DB'ga tegmaydi — faqat Redis.
            await self._touch(content)
            await self.send_json({"type": "heartbeat_ack"})
        elif action == "ping":
            await self.send_json({"type": "pong"})

    async def client_command(self, event):
        """Proktordan kelgan buyruq."""
        await self.send_json({"type": "command", "payload": event["payload"]})

    # --- Yordamchilar ---
    async def _authenticate(self) -> dict | None:
        """
        Token avval HEADER'dan, keyin query parametridan o'qiladi.

        `MonitorConsumer` dan farqi shu va sabab clientning turida:
        brauzer WebSocket API'si maxsus header qo'shishga imkon
        bermaydi, PyQt6 dagi `QWebSocket` esa beradi. Query
        parametridagi opaque sessiya tokeni nginx access log'ida va
        proksi jurnallarida ochiq qoladi, ya'ni undan qochish
        mumkin bo'lganda qochish kerak.

        Query parametri qo'llab-quvvatlanishda QOLADI: eski client
        nusxalari (va qo'lda diagnostika) shu yo'ldan ulanadi.
        """
        raw_token = self._header_token()
        if not raw_token:
            from urllib.parse import parse_qs

            query = parse_qs(self.scope.get("query_string", b"").decode())
            raw_token = (query.get("proctoring_session") or [None])[0]

        if not raw_token:
            return None
        return await self._resolve_session(raw_token)

    def _header_token(self) -> str:
        """
        `X-Proctoring-Session` header'i.

        ASGI `scope["headers"]` — nomi kichik harfda normallashtirilgan
        `(bytes, bytes)` juftliklari ro'yxati.
        """
        for name, value in self.scope.get("headers") or []:
            if name == b"x-proctoring-session":
                return value.decode("latin-1").strip()
        return ""

    @database_sync_to_async
    def _resolve_session(self, raw_token: str) -> dict | None:
        from apps.common.utils.crypto import hash_token
        from apps.proctoring.services import state as session_state

        payload = session_state.resolve_session_token(hash_token(raw_token))
        if payload is None:
            return None
        return payload

    @database_sync_to_async
    def _touch(self, content: dict) -> None:
        from apps.proctoring.services import state as session_state

        session_state.touch_heartbeat(
            self.session_info["session_id"],
            zone_id=self.session_info.get("zone_id"),
            extra={"ws": 1, "queued": content.get("queued_events", 0)},
        )
