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

    def test_without_device_path_no_enumeration(self):
        source = self._source(index=3, path="")
        with mock.patch.object(dshow, "enumerate_devices") as enumerate_devices:
            self.assertEqual(source._current_index(), 3)
        enumerate_devices.assert_not_called()


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
