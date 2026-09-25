"""
Channel layer'ning Redis ulanishi o'lik ulanishga chidamlimi.

Stsenariy haqiqiy nosozlikdan: panelning jonli kuzatuvi "ulandi, keyin
uzildi" sikliga tushardi, chunki `group_add` pool'da soatlab bo'sh
yotgan va yo'lda jimgina tashlab yuborilgan ulanishni olardi, redis-py
8 esa standart holatda NOL marta qayta urinadi.

O'lik ulanish server tomonidan `CLIENT KILL` bilan yasaladi — socket
client pool'ida qoladi, lekin uning narigi uchi yo'q. Nazorat testi
(qayta urinishsiz) aynan shu holat xato berishini ko'rsatadi: aks holda
asosiy test "hech narsa buzilmagani uchun o'tdi" bo'lib qolishi mumkin
edi.
"""

from __future__ import annotations

import unittest
import uuid

from django.conf import settings
from django.test import SimpleTestCase

from apps.common.tests.utils import redis_available


def _layer(host: dict):
    from channels_redis.core import RedisChannelLayer

    return RedisChannelLayer(hosts=[host], prefix=f"test-{uuid.uuid4().hex[:8]}")


async def _kill_connections(client_name: str) -> int:
    """Nomi berilgan client'ning barcha ulanishlarini SERVER tomonidan uzadi."""
    import redis.asyncio as aioredis

    admin = aioredis.Redis.from_url(f"{settings.REDIS_URL}/15")
    try:
        killed = 0
        for info in await admin.client_list():
            if info.get("name") == client_name:
                killed += await admin.client_kill_filter(_id=info["id"])
        return killed
    finally:
        await admin.aclose()


class ChannelLayerDeadConnectionTests(SimpleTestCase):
    def setUp(self):
        if not redis_available():
            raise unittest.SkipTest("Redis mavjud emas — test o'tkazib yuborildi")
        self.client_name = f"layer-test-{uuid.uuid4().hex[:8]}"

    def _host(self, **overrides) -> dict:
        from config.settings.base import _channel_layer_host

        host = _channel_layer_host(f"{settings.REDIS_URL}/15")
        host["client_name"] = self.client_name
        host.update(overrides)
        return host

    async def test_group_add_survives_dead_pooled_connection(self):
        layer = _layer(self._host())
        try:
            await layer.group_add("monitor", "specific.a!1")
            self.assertGreater(await _kill_connections(self.client_name), 0)

            # Pool'dagi ulanish o'lik — buyruq yangi ulanishda qaytariladi.
            await layer.group_add("monitor", "specific.a!2")
            await layer.group_discard("monitor", "specific.a!1")
        finally:
            await layer.flush()
            await layer.close_pools()

    async def test_without_retry_dead_connection_fails(self):
        """Nazorat: redis-py standarti (0 urinish) aynan shu holatda yiqiladi."""
        from redis.asyncio.retry import Retry
        from redis.backoff import NoBackoff
        from redis.exceptions import ConnectionError as RedisConnectionError

        layer = _layer(
            self._host(retry=Retry(NoBackoff(), 0), retry_on_error=[], health_check_interval=0)
        )
        try:
            await layer.group_add("monitor", "specific.b!1")
            self.assertGreater(await _kill_connections(self.client_name), 0)

            with self.assertRaises((RedisConnectionError, OSError)):
                await layer.group_add("monitor", "specific.b!2")
        finally:
            await layer.flush()
            await layer.close_pools()
