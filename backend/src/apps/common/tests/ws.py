"""
WebSocket consumer'larini sinash uchun minimal communicator.

Nima uchun `channels.testing.WebsocketCommunicator` EMAS: u
`channels/testing/__init__.py` orqali importlanadi va o'sha fayl
`ChannelsLiveServerTestCase` ni, u esa `daphne` ni tortadi. Loyiha
ataylab **uvicorn** da ishlaydi (`deploy/README.md`), ya'ni daphne'ni
faqat test importi uchun bog'liqliklarga qo'shish - butun ASGI
serverni bitta `import` uchun o'rnatish demak.

Bu yerdagi klass ASGI WebSocket protokolining o'zi bilan ishlaydi
(`asgiref.testing.ApplicationCommunicator` ustida) va bizga kerakli
to'rtta amalni beradi: ulanish, qabul qilish, yuborish, uzilish.
"""

from __future__ import annotations

import json

from asgiref.testing import ApplicationCommunicator


class WebsocketCommunicator:
    """ASGI WebSocket ilovasi bilan gaplashuvchi test yordamchisi."""

    def __init__(self, application, path: str, *, headers=None):
        query = b""
        if "?" in path:
            path, _, raw_query = path.partition("?")
            query = raw_query.encode()

        self.scope = {
            "type": "websocket",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query,
            "headers": list(headers or []),
            "subprotocols": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
        self._application = application
        self._communicator = None

    # ------------------------------------------------------------------
    def _start(self):
        # Communicator scope NUSXASI bilan yaratiladi, shuning uchun uni
        # `connect()` gacha o'zgartirish mumkin (test header qo'shadi).
        if self._communicator is None:
            self._communicator = ApplicationCommunicator(self._application, self.scope)
        return self._communicator

    async def connect(self, timeout: float = 3.0):
        """
        Qaytaradi `(ulandimi, subprotokol_yoki_yopilish_kodi)`.

        `channels` dagi bilan bir xil shakl - testlar tanish ko'rinishda
        qoladi.
        """
        communicator = self._start()
        await communicator.send_input({"type": "websocket.connect"})
        message = await communicator.receive_output(timeout)

        if message["type"] == "websocket.close":
            return False, message.get("code", 1000)
        return True, message.get("subprotocol")

    async def send_json_to(self, data) -> None:
        await self._start().send_input(
            {"type": "websocket.receive", "text": json.dumps(data)}
        )

    async def receive_json_from(self, timeout: float = 3.0):
        message = await self._start().receive_output(timeout)
        assert message["type"] == "websocket.send", message
        return json.loads(message["text"])

    async def disconnect(self, code: int = 1000, timeout: float = 3.0) -> None:
        communicator = self._start()
        await communicator.send_input({"type": "websocket.disconnect", "code": code})
        await communicator.wait(timeout)
