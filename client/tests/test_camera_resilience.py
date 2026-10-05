"""
Kamera qatlamining chidamliligi: vaqt chegarasi (`guard.py`), sabab
tanlash (`diagnose.py`), kadr sifati va `CameraWorker` qayta ulanishi.

Haqiqiy kamera ISHLATILMAYDI — soxta manbalar nosozlikni aniq taqlid
qiladi (osilgan `read()`, ochilmaydigan qurilma, istisno).
"""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proctoring.camera import diagnose  # noqa: E402
from proctoring.camera.base import CameraInfo, CameraSource  # noqa: E402
from proctoring.camera.guard import GuardedSource, normalize_frame  # noqa: E402


def _frame(value: int = 128, size=(48, 64)) -> np.ndarray:
    return np.full((size[0], size[1], 3), value, dtype=np.uint8)


class FakeSource(CameraSource):
    """Boshqariladigan manba: ochilish natijasi, osilish, istisno."""

    def __init__(self, *, open_results=None, frames=None, role="primary") -> None:
        super().__init__(CameraInfo(role=role, source="local", label="fake"))
        self.open_results = list(open_results or [True])
        self.frames = frames  # None -> doim kadr
        self.block = threading.Event()
        self.hang_reads = False
        self.raise_on_read = False
        self.opened = False
        self.open_calls = 0
        self.close_calls = 0
        self.threads = set()

    def open(self) -> bool:
        self.threads.add(threading.get_ident())
        self.open_calls += 1
        result = self.open_results.pop(0) if self.open_results else True
        self.opened = bool(result)
        if not result:
            self._last_error = "ochilmadi"
        return bool(result)

    def read(self):
        self.threads.add(threading.get_ident())
        if self.raise_on_read:
            raise RuntimeError("drayver xatosi")
        if self.hang_reads:
            self.block.wait(10)
        if self.frames is not None:
            return self.frames.pop(0) if self.frames else None
        return _frame()

    def close(self) -> None:
        self.threads.add(threading.get_ident())
        self.close_calls += 1
        self.opened = False


class GuardedSourceTest(unittest.TestCase):
    def test_normal_calls_run_on_one_io_thread(self):
        inner = FakeSource()
        source = GuardedSource(inner, open_timeout=2, read_timeout=2)
        self.assertTrue(source.open())
        self.assertIsNotNone(source.read())
        source.close()
        self.assertFalse(inner.opened)
        # DirectShow qurilmasi bitta thread'da ishlashi kerak.
        self.assertEqual(len(inner.threads), 1)
        self.assertNotIn(threading.get_ident(), inner.threads)

    def test_hung_read_times_out_and_does_not_block_caller(self):
        inner = FakeSource()
        source = GuardedSource(inner, open_timeout=2, read_timeout=0.3, close_timeout=0.2)
        self.assertTrue(source.open())
        inner.hang_reads = True
        started = time.monotonic()
        self.assertIsNone(source.read())
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertTrue(source.hung)
        self.assertIn("javob bermayapti", source.last_error)

        # Osilgan paytda keyingi o'qish KUTMAYDI, ochish rad etiladi.
        started = time.monotonic()
        self.assertIsNone(source.read())
        self.assertLess(time.monotonic() - started, 0.2)
        self.assertFalse(source.open())

        # Yopish osilgan chaqiruv qaytgach bajariladi (boshqa thread'dan
        # `release()` qilinmaydi).
        source.close()
        self.assertEqual(inner.close_calls, 0)
        inner.hang_reads = False
        inner.block.set()
        deadline = time.monotonic() + 3
        while inner.close_calls == 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(inner.close_calls, 1)
        self.assertFalse(source.hung)
        self.assertTrue(source.open())
        source.close()

    def test_abandoned_open_is_closed_when_it_finally_returns(self):
        release = threading.Event()

        class SlowOpen(FakeSource):
            def open(self_inner):
                release.wait(5)
                return super().open()

        inner = SlowOpen()
        source = GuardedSource(inner, open_timeout=0.2, read_timeout=1)
        self.assertFalse(source.open())
        release.set()
        deadline = time.monotonic() + 3
        while inner.close_calls == 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        # Hech kim kutmagan ochilish qurilmani band qilib qolmaydi.
        self.assertEqual(inner.close_calls, 1)
        self.assertFalse(inner.opened)

    def test_abort_interrupts_wait(self):
        inner = FakeSource()
        source = GuardedSource(inner, open_timeout=2, read_timeout=5, close_timeout=0.2)
        self.assertTrue(source.open())
        inner.hang_reads = True
        threading.Timer(0.2, source.abort).start()
        started = time.monotonic()
        self.assertIsNone(source.read())
        self.assertLess(time.monotonic() - started, 1.5)
        inner.block.set()

    def test_exception_in_read_is_empty_frame(self):
        inner = FakeSource()
        source = GuardedSource(inner, open_timeout=2, read_timeout=2)
        self.assertTrue(source.open())
        inner.raise_on_read = True
        self.assertIsNone(source.read())
        inner.raise_on_read = False
        self.assertIsNotNone(source.read())
        source.close()


class NormalizeFrameTest(unittest.TestCase):
    def test_shapes(self):
        gray = np.zeros((10, 12), dtype=np.uint8)
        self.assertEqual(normalize_frame(gray).shape, (10, 12, 3))
        bgra = np.zeros((10, 12, 4), dtype=np.uint8)
        self.assertEqual(normalize_frame(bgra).shape, (10, 12, 3))
        self.assertEqual(normalize_frame(_frame()).shape, (48, 64, 3))

    def test_unusable_frames_become_none(self):
        self.assertIsNone(normalize_frame(None))
        self.assertIsNone(normalize_frame(np.zeros((0, 0, 3), dtype=np.uint8)))
        self.assertIsNone(normalize_frame(np.zeros((10, 10, 3), dtype=np.uint16)))
        self.assertIsNone(normalize_frame("kadr"))


class DiagnoseTest(unittest.TestCase):
    class _Device:
        def __init__(self, index, path=""):
            self.index = index
            self.device_path = path

    def test_privacy_denied_wins(self):
        message = diagnose.explain_local_failure(
            0, privacy_reader=lambda hive, key: "Deny" if key.endswith("NonPackaged") else "Allow",
            devices=[self._Device(0)],
        )
        self.assertEqual(message, diagnose.PRIVACY_MESSAGE)
        self.assertIn("Maxfiylik", message)

    def test_device_absent_is_not_found(self):
        message = diagnose.explain_local_failure(
            1, privacy_reader=lambda hive, key: "Allow", devices=[self._Device(0)]
        )
        self.assertEqual(message, diagnose.NOT_FOUND_MESSAGE)
        message = diagnose.explain_local_failure(
            0, "usb#new", privacy_reader=lambda hive, key: "", devices=[self._Device(0, "usb#old")]
        )
        self.assertEqual(message, diagnose.NOT_FOUND_MESSAGE)

    def test_device_present_is_busy_or_lost(self):
        devices = [self._Device(0, "usb#a")]
        allow = lambda hive, key: "Allow"  # noqa: E731
        self.assertEqual(
            diagnose.explain_local_failure(0, "usb#a", privacy_reader=allow, devices=devices),
            diagnose.BUSY_MESSAGE,
        )
        self.assertEqual(
            diagnose.explain_local_failure(
                0, "usb#a", lost=True, privacy_reader=allow, devices=devices
            ),
            diagnose.LOST_MESSAGE,
        )

    def test_reader_error_is_not_denied(self):
        def broken(hive, key):
            raise OSError("registr yo'q")

        self.assertFalse(diagnose.privacy_denied(broken))


class QualityTest(unittest.TestCase):
    def test_dark_and_bright(self):
        from services.camera_worker import assess_quality

        self.assertIn("dark", assess_quality(_frame(10)))
        self.assertIn("bright", assess_quality(_frame(250)))
        self.assertEqual(assess_quality(_frame(128)), [])

    def test_blur_on_face_crop(self):
        from services.camera_worker import assess_quality

        flat = _frame(128, size=(240, 320))
        self.assertIn("blurry", assess_quality(flat, [40, 40, 200, 200]))
        rng = np.random.default_rng(1)
        sharp = rng.integers(0, 255, size=(240, 320, 3), dtype=np.uint8)
        self.assertNotIn("blurry", assess_quality(sharp, [40, 40, 200, 200]))

    def test_never_raises(self):
        from services.camera_worker import assess_quality

        self.assertEqual(assess_quality(None), [])
        self.assertEqual(assess_quality(_frame(), ["x"]), [])


class CameraWorkerReconnectTest(unittest.TestCase):
    """`run()` shu thread'da chaqiriladi — signal ulanishlari to'g'ridan-to'g'ri."""

    @classmethod
    def setUpClass(cls):
        # QApplication (QCoreApplication EMAS): keyingi test modullari
        # (`test_lockdown_hook`) oyna yaratadi va QCoreApplication
        # ustida Qt jarayonni qFatal bilan yiqitadi.
        from PyQt6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        # Tizim hodisalari manbai (nativ filtr) ULANMAYDI — u jarayon
        # bo'yicha global. Faqat funksiya almashtiriladi: `sys.modules`
        # ni almashtirish test davomida import qilingan modullarni
        # keyin o'chirib, keyingi testda ularni QAYTA yuklatardi.
        from unittest import mock

        import core.system_events
        import services.camera_worker as module

        patcher = mock.patch.object(
            core.system_events, "system_events", return_value=mock.Mock()
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        self.module = module
        self._backoff = module._BACKOFF_S
        module._BACKOFF_S = (0.05,)

    def tearDown(self):
        self.module._BACKOFF_S = self._backoff

    def test_open_failure_retries_and_restores(self):
        inner = FakeSource(open_results=[False, False, True])
        worker = self.module.CameraWorker(source=inner, detect=False)
        errors, restored, frames = [], [], []
        worker.camera_error.connect(errors.append)
        worker.camera_restored.connect(lambda: restored.append(True))

        def on_frame(frame):
            frames.append(frame)
            if len(frames) >= 3:
                worker.stop()

        worker.frame_ready.connect(on_frame)
        worker.run()

        self.assertEqual(inner.open_calls, 3)
        # Bir xil sabab — BITTA xabar (hodisa oqimi to'lib ketmasin).
        self.assertEqual(errors, ["ochilmadi"])
        self.assertEqual(restored, [True])
        self.assertGreaterEqual(len(frames), 3)
        self.assertFalse(inner.opened)

    def test_lost_frames_reconnect_instead_of_exit(self):
        inner = FakeSource(frames=[_frame()] + [None] * 40)
        worker = self.module.CameraWorker(source=inner, detect=False)
        errors = []

        def on_error(message):
            errors.append(message)
            worker.stop()

        worker.camera_error.connect(on_error)
        worker.run()
        self.assertEqual(len(errors), 1)
        self.assertFalse(inner.opened)

    def test_unplugged_camera_that_keeps_returning_frames_reconnects(self):
        """
        Noutbukda amalda topilgan: USB sug'urilgach DirectShow `read()`
        kadr qaytaraverdi - bo'sh kadrlar qoidasi uzilishni ko'rmadi va
        kabel qayta ulanganda kamera qayta ochilmadi (3 daqiqa log jim).
        """
        from unittest import mock

        inner = FakeSource()
        presence = {"value": True}
        inner.is_present = lambda: presence["value"]
        worker = self.module.CameraWorker(source=inner, detect=False)
        errors, restored, frames = [], [], []

        def on_frame(_frame):
            frames.append(1)
            if len(frames) == 5:
                presence["value"] = False   # sug'urildi - kadr baribir keladi
            if restored:
                worker.stop()

        def on_error(message):
            errors.append(message)
            presence["value"] = True        # qayta ulandi

        worker.frame_ready.connect(on_frame)
        worker.camera_error.connect(on_error)
        worker.camera_restored.connect(lambda: restored.append(True))
        with mock.patch.object(self.module, "_PRESENCE_CHECK_S", 0.0):
            worker.run()

        self.assertEqual(len(errors), 1)
        self.assertEqual(restored, [True])
        self.assertEqual(inner.open_calls, 2)   # yopildi va QAYTA ochildi

    def test_unknown_presence_does_not_disconnect(self):
        from unittest import mock

        inner = FakeSource()
        inner.is_present = lambda: None          # ro'yxat o'qilmadi
        worker = self.module.CameraWorker(source=inner, detect=False)
        frames, errors = [], []
        worker.camera_error.connect(errors.append)

        def on_frame(_frame):
            frames.append(1)
            if len(frames) >= 20:
                worker.stop()

        worker.frame_ready.connect(on_frame)
        with mock.patch.object(self.module, "_PRESENCE_CHECK_S", 0.0):
            worker.run()
        self.assertEqual(errors, [])
        self.assertEqual(inner.open_calls, 1)

    def test_unexpected_exception_does_not_kill_loop(self):
        inner = FakeSource()
        worker = self.module.CameraWorker(source=inner, detect=False)
        calls = {"n": 0}
        original = worker._read_loop

        def flaky(source):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("kutilmagan")
            worker.stop()

        worker._read_loop = flaky
        errors = []
        worker.camera_error.connect(errors.append)
        worker.run()
        self.assertEqual(calls["n"], 2)
        self.assertTrue(errors and "kutilmagan" in errors[0])
        self.assertIsNotNone(original)


if __name__ == "__main__":
    unittest.main()
