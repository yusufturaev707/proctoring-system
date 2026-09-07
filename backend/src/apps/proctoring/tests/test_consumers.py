"""
WebSocket consumer'lari.

Asosiy tekshiruv — **autentifikatsiya**. Ikki consumer ikki xil qoidada
ishlaydi va bu ataylab:

    MonitorConsumer (brauzer) — token query parametrida, chunki brauzer
        WebSocket API'si maxsus header qo'shishga imkon bermaydi.
    ClientConsumer (PyQt6)    — token AVVAL header'da. `QWebSocket`
        header qo'ya oladi, URL'dagi token esa nginx access log'ida
        qoladi.

Ikkinchi tekshiruv — obuna chegarasi: proktor o'z viloyatidan
tashqaridagi binoga obuna bo'la olmaydi (WebSocket orqali ma'lumot
sizib chiqishining oldini oladi).
"""

from django.test import TransactionTestCase

from apps.common.tests.utils import redis_available
from apps.common.tests.ws import WebsocketCommunicator
from apps.common.utils.crypto import hash_token
from apps.proctoring.consumers import (
    CLOSE_FORBIDDEN,
    CLOSE_UNAUTHORIZED,
    ClientConsumer,
    MonitorConsumer,
)
from apps.proctoring.services import state as session_state
from apps.proctoring.tests import factories


def access_token(user) -> str:
    from rest_framework_simplejwt.tokens import AccessToken

    return str(AccessToken.for_user(user))


class ClientConsumerAuthTests(TransactionTestCase):
    """
    `TransactionTestCase`: consumer o'z thread'ida DB'ga murojaat
    qiladi va oddiy `TestCase` ning tranzaksiyasi u yerdan ko'rinmaydi.
    """

    def setUp(self):
        if not redis_available():
            self.skipTest("Redis mavjud emas")
        self.session = factories.make_session()
        self.raw_token = "test-opaque-token"
        session_state.store_session_token(
            token_hash=hash_token(self.raw_token),
            payload={
                "session_id": self.session.pk,
                "public_id": str(self.session.public_id),
                "exam_id": self.session.exam_id,
                "device_id": None,
                "zone_id": self.session.zone_id,
                "status": self.session.status,
            },
        )
        self.addCleanup(
            session_state.revoke_session_token, hash_token(self.raw_token)
        )

    async def _connect(self, *, header=None, query=""):
        headers = [(b"host", b"testserver")]
        if header is not None:
            headers.append((b"x-proctoring-session", header.encode()))
        return WebsocketCommunicator(
            ClientConsumer.as_asgi(), f"/ws/client/{query}", headers=headers
        )

    async def test_connects_with_header_token(self):
        """Asosiy yo'l: token `X-Proctoring-Session` header'ida."""
        communicator = await self._connect(header=self.raw_token)
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        message = await communicator.receive_json_from()
        self.assertEqual(message["type"], "connected")
        self.assertEqual(message["session"], str(self.session.public_id))
        await communicator.disconnect()

    async def test_connects_with_query_token_for_backwards_compatibility(self):
        """
        Eski yo'l saqlangan.

        Eski client nusxalari va qo'lda diagnostika shu orqali ulanadi.
        """
        communicator = await self._connect(
            query=f"?proctoring_session={self.raw_token}"
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        await communicator.disconnect()

    async def test_header_wins_over_query(self):
        """
        Header birinchi o'qiladi.

        Ikkalasi ham berilgan bo'lsa (client yangilanish paytida),
        ishonchliroq manba tanlanadi.
        """
        communicator = await self._connect(
            header=self.raw_token, query="?proctoring_session=xato-token"
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        await communicator.disconnect()

    async def test_rejects_missing_token(self):
        communicator = await self._connect()
        connected, code = await communicator.connect()
        self.assertFalse(connected)
        self.assertEqual(code, CLOSE_UNAUTHORIZED)

    async def test_rejects_unknown_token(self):
        communicator = await self._connect(header="mavjud-bo'lmagan")
        connected, code = await communicator.connect()
        self.assertFalse(connected)
        self.assertEqual(code, CLOSE_UNAUTHORIZED)

    async def test_heartbeat_is_acknowledged(self):
        communicator = await self._connect(header=self.raw_token)
        await communicator.connect()
        await communicator.receive_json_from()  # "connected"

        await communicator.send_json_to({"action": "heartbeat", "queued_events": 3})
        message = await communicator.receive_json_from()
        self.assertEqual(message["type"], "heartbeat_ack")
        await communicator.disconnect()

    async def test_ping_pong(self):
        communicator = await self._connect(header=self.raw_token)
        await communicator.connect()
        await communicator.receive_json_from()

        await communicator.send_json_to({"action": "ping"})
        self.assertEqual((await communicator.receive_json_from())["type"], "pong")
        await communicator.disconnect()

    async def test_proctor_command_reaches_the_client(self):
        """
        Proktor buyrug'i sessiya guruhi orqali yetadi.

        Aynan shu kanal tufayli chetlashtirish darhol kuchga kiradi -
        heartbeat tsiklini (30 s) kutmasdan.
        """
        from apps.proctoring.services.realtime import send_client_command

        communicator = await self._connect(header=self.raw_token)
        await communicator.connect()
        await communicator.receive_json_from()

        from asgiref.sync import sync_to_async

        await sync_to_async(send_client_command)(
            session_id=self.session.pk,
            command="terminate",
            payload={"reason": "Qoida buzildi"},
        )

        message = await communicator.receive_json_from()
        self.assertEqual(message["type"], "command")
        self.assertEqual(message["payload"]["command"], "terminate")
        self.assertEqual(message["payload"]["reason"], "Qoida buzildi")
        await communicator.disconnect()


class MonitorConsumerTests(TransactionTestCase):
    def setUp(self):
        self.region = factories.make_region()
        self.other_region = factories.make_region()
        self.zone = factories.make_zone(region=self.region)
        self.foreign_zone = factories.make_zone(region=self.other_region)
        self.proctor = factories.make_user(
            permissions=["sessions.view"], region=self.region
        )

    async def _connect(self, token):
        communicator = WebsocketCommunicator(
            MonitorConsumer.as_asgi(), f"/ws/monitor/?token={token}"
        )
        return communicator

    async def test_rejects_without_token(self):
        communicator = WebsocketCommunicator(MonitorConsumer.as_asgi(), "/ws/monitor/")
        connected, code = await communicator.connect()
        self.assertFalse(connected)
        self.assertEqual(code, CLOSE_UNAUTHORIZED)

    async def test_rejects_user_without_permission(self):
        from asgiref.sync import sync_to_async

        nobody = await sync_to_async(factories.make_user)(permissions=[])
        communicator = await self._connect(
            await sync_to_async(access_token)(nobody)
        )
        connected, code = await communicator.connect()
        self.assertFalse(connected)
        self.assertEqual(code, CLOSE_FORBIDDEN)

    async def test_subscribes_to_own_region_zone(self):
        from asgiref.sync import sync_to_async

        communicator = await self._connect(
            await sync_to_async(access_token)(self.proctor)
        )
        await communicator.connect()
        await communicator.receive_json_from()  # "connected"

        await communicator.send_json_to(
            {"action": "subscribe", "zones": [self.zone.pk]}
        )
        message = await communicator.receive_json_from()
        self.assertEqual(message["groups"], [f"zone.{self.zone.pk}"])
        await communicator.disconnect()

    async def test_cannot_subscribe_to_foreign_zone(self):
        """
        Hudud chegarasi WebSocket'da ham ishlaydi.

        Aks holda proktor boshqa viloyatning hodisalar oqimiga obuna
        bo'lib, ma'lumotni ko'ra olardi.
        """
        from asgiref.sync import sync_to_async

        communicator = await self._connect(
            await sync_to_async(access_token)(self.proctor)
        )
        await communicator.connect()
        await communicator.receive_json_from()

        await communicator.send_json_to(
            {"action": "subscribe", "zones": [self.foreign_zone.pk]}
        )
        message = await communicator.receive_json_from()
        self.assertEqual(message["groups"], [])
        await communicator.disconnect()
