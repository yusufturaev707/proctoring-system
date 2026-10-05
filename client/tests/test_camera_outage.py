"""
Imtihon paytida veb-kamera uzilib, qayta ulanishi.

Ikki amaliy xato qo'riqlanadi:

  * QAYTA ULANISHDA BOSHQA KAMERA. Indeks DirectShow sanog'idagi o'rin:
    noutbukda (ichki + USB, USB #0) USB uzilsa ichki kamera #0 ga
    suriladi va eski indeks bilan ochilardi (`WebcamSource._current_index`).
  * UZILISHDA "MOS". Oxirgi yuz natijasi / kadr tozalanmasdi - davriy
    FaceID kamera yo'q paytda ham "mos" deb sanardi, AI pipeline esa
    muzlagan kadrni tahlil qilardi.

Haqiqiy kamera ishlatilmaydi.
"""

import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from proctoring import pipeline as pipeline_module
from proctoring.camera import dshow
from proctoring.camera.webcam import WebcamSource
from proctoring.pipeline import ProctoringPipeline
from ui.pages import exam_webview_page
from ui.pages.exam_webview_page import ExamWebViewPage

USB = r"\\?\usb#vid_046d&pid_085e#cam"
BUILTIN = r"\\?\usb#vid_04f2&pid_b6dd#builtin"


def _device(index, path):
    return SimpleNamespace(index=index, device_path=path)


class CurrentIndexTests(unittest.TestCase):
    def _source(self, index=0, path=USB):
        return WebcamSource(index, role="primary", label="USB", device_path=path)

    def test_shifted_index_follows_device_path(self):
        source = self._source(index=0)
        devices = [_device(0, BUILTIN), _device(1, USB)]
        with mock.patch.object(dshow, "enumerate_devices", return_value=devices):
            self.assertEqual(source._current_index(), 1)
        self.assertEqual(source.info.index, 1)

    def test_absent_device_is_not_replaced_by_another(self):
        # USB uzilgan, ichki kamera #0 ga surilgan - u OCHILMASLIGI kerak.
        source = self._source(index=0)
        devices = [_device(0, BUILTIN)]
        with mock.patch.object(dshow, "enumerate_devices", return_value=devices), \
                mock.patch("cv2.VideoCapture") as capture:
            self.assertFalse(source.open())
        capture.assert_not_called()
        self.assertTrue(source.last_error)

    def test_empty_enumeration_keeps_index(self):
        # Bo'sh ro'yxat COM xatosi ham bo'lishi mumkin - eski yo'l.
        source = self._source(index=2)
        with mock.patch.object(dshow, "enumerate_devices", return_value=[]):
            self.assertEqual(source._current_index(), 2)

    def test_other_usb_port_is_found_by_unique_name(self):
        # Seriya raqamsiz kamera: yo'lda port izi, boshqa portda yo'l boshqa.
        source = WebcamSource(1, role="primary", label="Logi C270 HD WebCam", device_path=USB)
        moved = SimpleNamespace(index=0, device_path=USB + "-port2", name="Logi C270 HD WebCam")
        other = SimpleNamespace(index=1, device_path=BUILTIN, name="Integrated Camera")
        with mock.patch.object(dshow, "enumerate_devices", return_value=[moved, other]):
            self.assertEqual(source._current_index(), 0)
        self.assertEqual(source._device_path, USB + "-port2")

    def test_ambiguous_name_is_not_guessed(self):
        source = WebcamSource(0, role="primary", label="Logi C270 HD WebCam", device_path=USB)
        twins = [
            SimpleNamespace(index=0, device_path="a", name="Logi C270 HD WebCam"),
            SimpleNamespace(index=1, device_path="b", name="Logi C270 HD WebCam"),
        ]
        with mock.patch.object(dshow, "enumerate_devices", return_value=twins):
            self.assertIsNone(source._current_index())

    def test_is_present_uses_exact_path_only(self):
        source = self._source(index=0)
        with mock.patch.object(dshow, "enumerate_devices_strict", return_value=[_device(0, USB)]):
            self.assertTrue(source.is_present())
        # Boshqa portga ulangan (yo'l boshqa) - eski ulanish baribir o'lik.
        moved = SimpleNamespace(index=0, device_path=USB + "-port2", name="USB")
        with mock.patch.object(dshow, "enumerate_devices_strict", return_value=[moved]):
            self.assertFalse(source.is_present())
        with mock.patch.object(dshow, "enumerate_devices_strict", return_value=[]):
            self.assertFalse(source.is_present())   # kamera umuman yo'q

    def test_is_present_unknown_when_list_unreadable(self):
        with mock.patch.object(dshow, "enumerate_devices_strict", return_value=None):
            self.assertIsNone(self._source().is_present())
        self.assertIsNone(self._source(path="").is_present())

    def test_without_device_path_no_enumeration(self):
        source = self._source(index=3, path="")
        with mock.patch.object(dshow, "enumerate_devices") as enumerate_devices:
            self.assertEqual(source._current_index(), 3)
        enumerate_devices.assert_not_called()


class StuckReadReplacementTests(unittest.TestCase):
    """
    DirectShow'da USB sug'urilganda `read()` UMUMAN qaytmasligi mumkin.
    Ilgari har keyingi `open()` "javob bermayapti" bilan rad etilardi -
    kabel qayta ulansa ham kamera imtihon oxirigacha o'chiq qolardi.
    """

    def _source_class(self):
        from proctoring.camera.base import CameraInfo, CameraSource

        class Device(CameraSource):
            instances = []

            def __init__(self):
                super().__init__(CameraInfo(role="primary", source="local", label="cam"))
                self.release = threading.Event()
                self.hang = False
                self.closed = 0
                self.threads = set()
                Device.instances.append(self)

            def open(self):
                self.threads.add(threading.get_ident())
                return True

            def read(self):
                self.threads.add(threading.get_ident())
                if self.hang:
                    self.release.wait(10)
                return np.zeros((4, 4, 3), dtype=np.uint8)

            def close(self):
                self.threads.add(threading.get_ident())
                self.closed += 1

            def fresh_copy(self):
                return Device()

        return Device

    def test_stuck_read_is_abandoned_and_device_reopened(self):
        from proctoring.camera import guard

        Device = self._source_class()
        first = Device()
        source = guard.GuardedSource(first, open_timeout=1, read_timeout=0.2, close_timeout=0.1)
        self.addCleanup(first.release.set)
        self.assertTrue(source.open())
        first.hang = True
        self.assertIsNone(source.read())
        self.assertTrue(source.hung)
        source.close()

        # Hali erta - eski qoida: rad.
        self.assertFalse(source.open())
        with mock.patch.object(guard, "_REPLACE_AFTER_S", 0.3):
            time.sleep(0.35)
            self.assertTrue(source.open())
        second = Device.instances[-1]
        self.assertIsNot(second, first)
        self.assertIsNotNone(source.read())
        self.assertIs(second.info, source.info)
        # Yangi manba eski osilgan thread'da emas.
        self.assertTrue(second.threads.isdisjoint(first.threads))

        # Osilgan chaqiruv qaytsa - eski manba O'Z thread'ida yopiladi.
        first.release.set()
        deadline = time.monotonic() + 2
        while first.closed == 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertGreaterEqual(first.closed, 1)
        self.assertEqual(second.closed, 0)
        source.close()
        self.assertEqual(second.closed, 1)


class LivenessTests(unittest.TestCase):
    """Qayta ulangan kamera ochildi, lekin qora bufer berdi (noutbuk log'i)."""

    def setUp(self):
        from proctoring.camera.liveness import FrameLiveness

        self.liveness = FrameLiveness(window_s=5.0, slow_read_s=0.5)
        self.black = np.zeros((72, 128, 3), dtype=np.uint8)

    def noisy(self, seed):
        return np.random.default_rng(seed).integers(0, 255, (72, 128, 3), dtype=np.uint8)

    def test_live_camera(self):
        for n in range(20):
            self.assertEqual(self.liveness.observe(self.noisy(n), 1.0, n), "live")

    def test_covered_camera_is_alive(self):
        # Yopilgan ob'ektiv: to'liq qora, lekin kadrlar o'z tezligida.
        for n in range(200):
            self.assertEqual(self.liveness.observe(self.black, 0.03, n * 0.03), "live")

    def test_black_buffer_with_slow_reads_is_dead(self):
        states = [self.liveness.observe(self.black, 1.0, float(n)) for n in range(7)]
        self.assertEqual(states[:5], ["suspect"] * 5)
        self.assertEqual(states[5], "dead")

    def test_frozen_frame_with_slow_reads_is_dead_and_recovers(self):
        frozen = self.noisy(1)
        states = [self.liveness.observe(frozen, 1.0, float(n)) for n in range(7)]
        self.assertEqual(states[0], "live")      # birinchisi - solishtiradigani yo'q
        self.assertEqual(states[-1], "dead")
        self.assertEqual(self.liveness.observe(self.noisy(2), 0.03, 8.0), "live")

    def test_report_once(self):
        self.liveness.observe(self.black, 1.0, 0.0)
        self.assertEqual(self.liveness.report(1.0), "")
        self.assertIn("o'qish 1000 ms", self.liveness.report(3.0))
        self.assertEqual(self.liveness.report(4.0), "")

    def test_virtual_and_ip_cameras_are_not_checked(self):
        from proctoring.camera.base import CameraInfo
        from proctoring.camera.liveness import applies

        local = SimpleNamespace(info=CameraInfo(role="primary", source="local", label="x"))
        virtual = SimpleNamespace(info=CameraInfo(role="primary", source="local", label="OBS", is_virtual=True))
        ip = SimpleNamespace(info=CameraInfo(role="primary", source="ip", label="cam"))
        self.assertEqual([applies(local), applies(virtual), applies(ip)], [True, False, False])


class WorkerDeadStreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_dead_stream_reopens_and_restores_only_on_live_frame(self):
        import functools

        import core.system_events
        from proctoring.camera.base import CameraInfo, CameraSource
        from proctoring.camera.liveness import FrameLiveness
        from services import camera_worker

        black = np.zeros((8, 8, 3), dtype=np.uint8)

        class Replugged(CameraSource):
            def __init__(self):
                super().__init__(CameraInfo(role="primary", source="local", label="USB Video Device"))
                self.opens = 0

            def open(self):
                self.opens += 1
                return True

            def read(self):
                # 1-ochilish: qora bufer; 2-ochilish: tirik tasvir.
                if self.opens == 1:
                    return black
                return np.random.default_rng().integers(0, 255, (8, 8, 3), dtype=np.uint8)

            def close(self):
                calls.append("close")

            def recover_dead_stream(self):
                calls.append("recover")
                return "DirectShow, drayver formati"

        calls = []
        source = Replugged()
        worker = camera_worker.CameraWorker(source=source, detect=False)
        errors, restored, frames = [], [], []
        worker.camera_error.connect(errors.append)
        worker.camera_restored.connect(lambda: restored.append(True))

        def on_frame(_frame):
            frames.append(1)
            if len(frames) >= 3:
                worker.stop()

        worker.frame_ready.connect(on_frame)
        fast = functools.partial(FrameLiveness, window_s=0.05, slow_read_s=0.0)
        with mock.patch.object(core.system_events, "system_events", return_value=mock.Mock()), \
                mock.patch.object(camera_worker, "FrameLiveness", fast), \
                mock.patch.object(camera_worker, "_BACKOFF_S", (0.01,)):
            worker.run()

        self.assertEqual(source.opens, 2)
        # Tiklash qadami manba YOPILGANDAN keyin (pnputil ochiq oqimga tegmasin).
        self.assertEqual(calls[:2], ["close", "recover"])
        self.assertEqual(errors, [camera_worker.DEAD_STREAM_MESSAGE])
        self.assertEqual(restored, [True])
        self.assertGreaterEqual(len(frames), 3)   # qora kadr berilmadi


class SettleTests(unittest.TestCase):
    def test_reopen_after_failure_waits_for_device(self):
        from proctoring.camera import webcam

        source = WebcamSource(0, role="primary", label="USB Video Device", device_path="")
        failing = mock.Mock(isOpened=mock.Mock(return_value=False))
        working = mock.MagicMock(isOpened=mock.Mock(return_value=True))
        working.get.return_value = 0
        with mock.patch("cv2.VideoCapture", side_effect=[failing, working]), \
                mock.patch.object(webcam.time, "sleep") as sleep:
            self.assertFalse(source.open())
            sleep.assert_not_called()
            self.assertTrue(source.open())
        sleep.assert_called_once_with(webcam._SETTLE_AFTER_RETURN_S)
        source.close()


class RecoveryLadderTests(unittest.TestCase):
    """
    Noutbuk: qayta ulangan kamera DirectShow+MJPG da har safar qora bufer
    berdi, dastur qayta ishga tushganda ham. Oddiy qayta ochish yordam
    bermaydi - usul almashadi, oxirida qurilma qayta ishga tushiriladi.
    """

    PATH = r"\\?\usb#vid_1bcf&pid_2284&mi_00#7&2b3c&0&0000#{65e8773d-8f56-11d0-a3b9-00a0c9223196}\global"

    def setUp(self):
        from proctoring.camera import webcam

        webcam._LAST_RESTART.clear()
        self.webcam = webcam

    def test_instance_id_from_device_path(self):
        self.assertEqual(
            self.webcam.instance_id_from_path(self.PATH),
            r"USB\VID_1BCF&PID_2284&MI_00\7&2B3C&0&0000",
        )
        self.assertEqual(self.webcam.instance_id_from_path("OBS-Camera"), "")

    def _ladder(self, msmf_safe):
        source = WebcamSource(0, role="primary", label="USB Video Device", device_path=self.PATH)
        steps = []
        run = mock.Mock(return_value=SimpleNamespace(returncode=0))
        with mock.patch.object(WebcamSource, "_msmf_safe", return_value=msmf_safe), \
                mock.patch("subprocess.run", run):
            for _ in range(4):
                steps.append((source.recover_dead_stream(), source._mode))
        return steps, run

    def test_single_camera_ladder(self):
        steps, run = self._ladder(True)
        self.assertEqual([mode for _, mode in steps], ["native", "msmf", "dshow", "native"])
        self.assertIn("qayta ishga tushirildi", steps[2][0])
        args = run.call_args[0][0]
        self.assertEqual(args[:2], ["pnputil", "/restart-device"])
        self.assertEqual(args[2], r"USB\VID_1BCF&PID_2284&MI_00\7&2B3C&0&0000")

    def test_restart_has_cooldown(self):
        steps, run = self._ladder(False)   # native, restart, native, restart
        self.assertEqual(run.call_count, 1)
        self.assertIn("yaqinda", steps[3][0])

    def _open(self, source):
        capture = mock.MagicMock(isOpened=mock.Mock(return_value=True))
        capture.get.return_value = 0
        with mock.patch("cv2.VideoCapture", return_value=capture) as factory, \
                mock.patch.object(dshow, "enumerate_devices", return_value=[]):
            self.assertTrue(source.open())
        return factory, capture

    def test_native_mode_forces_nothing(self):
        import cv2

        source = WebcamSource(2, role="primary", device_path=self.PATH)
        source._mode = "native"
        factory, capture = self._open(source)
        self.assertEqual(factory.call_args[0], (2, cv2.CAP_DSHOW))
        props = [call[0][0] for call in capture.set.call_args_list]
        self.assertNotIn(cv2.CAP_PROP_FOURCC, props)
        self.assertNotIn(cv2.CAP_PROP_FRAME_WIDTH, props)

    def test_msmf_mode_uses_media_foundation_index_zero(self):
        import cv2

        source = WebcamSource(1, role="primary", device_path=self.PATH)
        source._mode = "msmf"
        factory, capture = self._open(source)
        self.assertEqual(factory.call_args[0], (0, cv2.CAP_MSMF))
        props = [call[0][0] for call in capture.set.call_args_list]
        self.assertNotIn(cv2.CAP_PROP_FOURCC, props)

    def test_msmf_only_with_single_physical_camera(self):
        one = [SimpleNamespace(index=0, device_path=self.PATH, name="USB Video Device")]
        two = one + [SimpleNamespace(index=1, device_path="x", name="Integrated Camera")]
        with_obs = one + [SimpleNamespace(index=1, device_path="", name="OBS Virtual Camera")]
        source = WebcamSource(0, role="primary", device_path=self.PATH)
        for devices, expected in ((one, True), (two, False), (with_obs, True)):
            with mock.patch.object(dshow, "enumerate_devices", return_value=devices):
                self.assertEqual(source._msmf_safe(), expected)


class ManagerPresenceTests(unittest.TestCase):
    """AI kuzatuv oqimi (`CameraStream`) - noutbuk log'idagi yo'l."""

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_stream_fails_when_device_disappears(self):
        from proctoring.camera import manager
        from proctoring.camera.base import CameraInfo, CameraSource

        class Frames(CameraSource):
            def __init__(self):
                super().__init__(CameraInfo(role="primary", source="local", label="USB Video Device"))
                self.present = True

            def open(self):
                return True

            def read(self):
                time.sleep(0.005)
                return np.zeros((4, 4, 3), dtype=np.uint8)

            def close(self):
                pass

            def is_present(self):
                return self.present

        source = Frames()
        states = []
        stream_fields = SimpleNamespace(
            _running=True, _reconnect_requested=False, _source=source, _role="primary",
            _health=SimpleNamespace(frames_dropped=0, frames_total=0, last_error="", state=None),
            _frame_times=[], _read_times=[], _mutex=None, _preview_interval=1e9,
            _outage=False,
        )

        def set_state(state):
            states.append(state)
            stream_fields._health.state = state

        stream_fields._set_state = set_state
        stream_fields._mark_lost = lambda: manager.CameraStream._mark_lost(stream_fields)
        threading.Timer(0.05, lambda: setattr(source, "present", False)).start()
        with mock.patch.object(manager, "_PRESENCE_CHECK_S", 0.01), \
                mock.patch.object(manager, "QMutexLocker"), \
                mock.patch.object(manager, "_HEALTH_INTERVAL_MS", 1e12):
            started = time.monotonic()
            manager.CameraStream._read_loop(stream_fields)
        self.assertLess(time.monotonic() - started, 2.0)
        # Tirik kadr - ONLINE (ochilishda emas), keyin uzilish - FAILED.
        self.assertEqual(states, [manager.CameraState.ONLINE, manager.CameraState.FAILED])
        self.assertTrue(stream_fields._health.last_error)

    def test_failed_is_reported_once_per_outage(self):
        from proctoring.camera import manager

        states = []
        fields = SimpleNamespace(_outage=False, _set_state=states.append)
        manager.CameraStream._mark_lost(fields)
        manager.CameraStream._mark_lost(fields)   # qayta ochildi, yana o'lik
        self.assertEqual(states, [manager.CameraState.FAILED])


class PipelineStaleFrameTests(unittest.TestCase):
    def test_frozen_frame_is_not_analysed(self):
        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        now = 1000.0
        latest = {"primary": (frame, now - 0.1), "secondary": (frame, now - 10.0)}
        stub = SimpleNamespace(
            _manager=SimpleNamespace(latest_frame=lambda role: latest.get(role, (None, 0.0)))
        )
        frames = ProctoringPipeline._grab_frames(stub, now)
        self.assertEqual(list(frames), ["primary"])

    def test_stale_identity_is_not_returned(self):
        embedding = np.ones(512, dtype=np.float32)
        stub = SimpleNamespace(_last_identity=(embedding, 1), _last_identity_at=None)
        getter = ProctoringPipeline.latest_identity.fget
        self.assertEqual(getter(stub), (None, None))

        stub._last_identity_at = time.monotonic()
        self.assertIs(getter(stub)[0], embedding)

        stub._last_identity_at = time.monotonic() - pipeline_module._IDENTITY_MAX_AGE_S - 1
        self.assertEqual(getter(stub), (None, None))


class PeriodicFaceOutageTests(unittest.TestCase):
    def _page(self, *, face_at):
        return SimpleNamespace(
            _supervisor=SimpleNamespace(is_active=False),
            _last_embedding=np.ones(512, dtype=np.float32),
            _last_faces=1,
            _last_face_at=face_at,
        )

    def test_old_result_is_not_compared(self):
        stale = time.monotonic() - exam_webview_page._FACE_RESULT_MAX_AGE_S - 1
        self.assertEqual(ExamWebViewPage._current_face(self._page(face_at=stale)), (None, None))
        fresh = ExamWebViewPage._current_face(self._page(face_at=time.monotonic()))
        self.assertEqual(fresh[1], 1)

    def test_camera_error_forgets_last_result(self):
        stub = SimpleNamespace(
            _last_embedding=np.ones(512, dtype=np.float32),
            _last_faces=1,
            _last_face_at=time.monotonic(),
            _monitor=SimpleNamespace(push_event=mock.Mock()),
            message=SimpleNamespace(show_message=mock.Mock()),
        )
        ExamWebViewPage._on_camera_error(stub, "Kamera uzildi")
        self.assertIsNone(stub._last_embedding)
        self.assertEqual(stub._last_face_at, 0.0)
        stub._monitor.push_event.assert_called_once()

    def test_no_fresh_result_is_neither_match_nor_mismatch(self):
        stub = SimpleNamespace(
            _monitor=SimpleNamespace(is_active=True, set_face_checks=mock.Mock()),
            _state=SimpleNamespace(face_reference=np.ones(512, dtype=np.float32)),
            _supervisor=SimpleNamespace(is_active=False, identity_ready=False),
            _camera=object(),
            _current_face=lambda: (None, None),
            _face_threshold=lambda: 40,
            _report_face_failure=mock.Mock(),
            _update_status_tooltip=mock.Mock(),
            _status={},
            _face_checks=0,
            _passed_since_last=0,
        )
        ExamWebViewPage._run_face_check(stub)
        stub._report_face_failure.assert_not_called()
        self.assertEqual((stub._face_checks, stub._passed_since_last), (0, 0))
        self.assertEqual(stub._status["face"], "FaceID: kamera kadri yo'q")


if __name__ == "__main__":
    unittest.main()
