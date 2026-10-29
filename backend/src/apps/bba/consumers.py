"""
`ws/bba/?token=<JWT>` — BBA kompyuterlari holati real vaqtda.

Autentifikatsiya va panel yuzasi qoidasi `MonitorConsumer` bilan BITTA
(meros): token, `panel.access`, viloyatsiz viloyat xodimi rad etiladi.
Guruh ulanishda server tomonidan tanlanadi — client obuna so'ramaydi, ya'ni
viloyat xodimi boshqa viloyat guruhiga yozila olmaydi.
"""

from __future__ import annotations

import logging

from apps.bba.services import bba_group
from apps.proctoring.consumers import (
    _LAYER_ERRORS,
    CLOSE_FORBIDDEN,
    CLOSE_LAYER_UNAVAILABLE,
    CLOSE_UNAUTHORIZED,
    MonitorConsumer,
)

logger = logging.getLogger(__name__)


class BbaConsumer(MonitorConsumer):
    async def connect(self):
        self.user = await self._authenticate()
        if self.user is None:
            await self.close(code=CLOSE_UNAUTHORIZED)
            return
        if not await self._has_permission():
            await self.close(code=CLOSE_FORBIDDEN)
            return
        self.groups_joined = []
        try:
            await self._join(bba_group(self.user.get("region_id")))
        except _LAYER_ERRORS as exc:
            logger.warning("bba: channel layer ishlamadi: %s", exc)
            await self.close(code=CLOSE_LAYER_UNAVAILABLE)
            return
        await self.accept()
        await self.send_json({"type": "subscribed", "groups": self.groups_joined})

    async def _has_permission(self) -> bool:
        if self.user.get("lacks_region") or not self.user.get("has_panel_access"):
            return False
        permissions = self.user.get("permissions", [])
        return self.user["is_superuser"] or "*" in permissions or "bba.view" in permissions

    async def receive_json(self, content, **kwargs):
        if content.get("action") == "ping":
            await self.send_json({"type": "pong"})

    async def bba_update(self, event):
        await self.send_json({"type": event["kind"], "payload": event["payload"]})
