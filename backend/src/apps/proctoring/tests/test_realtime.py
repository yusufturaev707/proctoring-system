"""
Sinxron koddan `group_send` — doimiy loop (`realtime._LayerLoop`).

Xavf: har chaqiruvga yangi event loop = channels_redis'da har xabarga
yangi Redis TCP ulanishi (yuklama sinovida TIME_WAIT 14 000+ va ulanish
xatolari). Testlar Redis'siz: loop'ni qayd etadigan soxta layer.
"""

import asyncio
import threading
import time
from unittest import mock

from django.test import SimpleTestCase

from apps.proctoring.services import realtime


class _RecordingLayer:
    def __init__(self, delay: float = 0.0):
        self.delay = delay
        self.loops = []
        self.messages = []

    async def group_send(self, group, message):
        if self.delay:
            await asyncio.sleep(self.delay)
        self.loops.append(asyncio.get_running_loop())
        self.messages.append((group, message))


class LayerLoopTests(SimpleTestCase):
    def setUp(self):
        # Har test o'z loop'i bilan — boshqa testdagi holat aralashmasin.
        patcher = mock.patch.object(realtime, "_LAYER_LOOP", realtime._LayerLoop())
        patcher.start()
        self.addCleanup(patcher.stop)

    def _send_with(self, layer, *args, **kwargs):
        with mock.patch.object(realtime, "get_channel_layer", return_value=layer):
            realtime.group_send(*args, **kwargs)

    def test_calls_from_many_threads_share_one_loop(self):
        layer = _RecordingLayer()
        threads = [
            threading.Thread(target=self._send_with, args=(layer, "zone.1", {"n": n}))
            for n in range(8)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(layer.messages), 8)
        self.assertEqual(len({id(loop) for loop in layer.loops}), 1)

    def test_loop_is_reopened_after_fork(self):
        layer = _RecordingLayer()
        self._send_with(layer, "zone.1", {})
        # Fork'dan keyingi bola: PID boshqa, ota thread'i bolada yo'q.
        with mock.patch.object(realtime.os, "getpid", return_value=-1):
            self._send_with(layer, "zone.1", {})
        self.assertNotEqual(id(layer.loops[0]), id(layer.loops[1]))

    def test_slow_layer_does_not_block_past_timeout(self):
        layer = _RecordingLayer(delay=1.0)
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            self._send_with(layer, "zone.1", {}, timeout=0.05)
        self.assertLess(time.monotonic() - started, 0.5)

    def test_send_helper_swallows_errors(self):
        """`_send` (sessiya holati, buyruqlar) asosiy oqimni yiqitmaydi."""
        with mock.patch.object(realtime, "group_send", side_effect=OSError("redis down")):
            realtime.send_client_command(session_id=1, command="warn")
