"""
FaceEngine: yuklash xatolarini tasniflash, hujjat rasmi sabablari va
GPU ishlash paytida yiqilganda CPU'ga o'tish.

Haqiqiy model YUKLANMAYDI — dvigatel soxta `app` bilan quriladi.
"""

from __future__ import annotations

import base64
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import face_engine  # noqa: E402
from services.face_engine import (  # noqa: E402
    FaceEngine,
    ModelLoadError,
    classify_model_error,
    decode_photo_base64,
)


def _engine(app=None, *, gpu=False) -> FaceEngine:
    """Singleton'ni chetlab o'tgan, "yuklangan" dvigatel."""
    engine = object.__new__(FaceEngine)
    FaceEngine.__init__(engine)
    engine._app = app
    engine._initialized = True
    engine._use_gpu = gpu
    return engine


class _Face:
    def __init__(self, width=100):
        self.bbox = np.array([10, 10, 10 + width, 10 + width], dtype=np.float32)
        self.det_score = 0.9
        self.embedding = np.ones(512, dtype=np.float32)


class _App:
    def __init__(self, faces=None, error=None):
        self.faces = faces or []
        self.error = error
        self.calls = 0

    def get(self, frame):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return list(self.faces)


def _jpeg(width=200, height=240) -> str:
    import cv2

    ok, buffer = cv2.imencode(".jpg", np.full((height, width, 3), 120, dtype=np.uint8))
    assert ok
    return base64.b64encode(buffer.tobytes()).decode("ascii")


class ClassifyTest(unittest.TestCase):
    def test_kinds(self):
        cases = [
            (FileNotFoundError("x"), "missing"),
            (AssertionError(), "missing"),
            (RuntimeError("[ONNXRuntimeError] : 3 : NO_SUCHFILE : Load model from a.onnx "
                          "failed:File doesn't exist"), "missing"),
            (RuntimeError("[ONNXRuntimeError] : 7 : INVALID_PROTOBUF : Load model from "
                          "a.onnx failed:Protobuf parsing failed."), "corrupt"),
            (MemoryError(), "memory"),
            (RuntimeError("std::bad_alloc"), "memory"),
            (OSError("[WinError 1455] The paging file is too small"), "memory"),
            (ImportError("DLL load failed while importing onnxruntime_pybind11_state"), "runtime"),
            (RuntimeError("LoadLibrary failed with error 126 onnxruntime_providers_cuda.dll"),
             "runtime"),
            (ModelLoadError("gpu_required", "GPU talab"), "gpu_required"),
            (ModelLoadError("corrupt", "Model fayli bo'sh"), "corrupt"),
            (ValueError("nimadir"), "unknown"),
        ]
        for exc, kind in cases:
            with self.subTest(exc=exc):
                problem = classify_model_error(exc)
                self.assertEqual(problem.kind, kind)
                self.assertTrue(problem.title)
                self.assertTrue(problem.detail)

    def test_only_transient_problems_retry(self):
        self.assertTrue(classify_model_error(MemoryError()).retryable)
        self.assertFalse(classify_model_error(FileNotFoundError()).retryable)
        self.assertFalse(
            classify_model_error(RuntimeError("INVALID_PROTOBUF")).retryable
        )


class ModelFilesTest(unittest.TestCase):
    def test_empty_and_missing_files(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ModelLoadError) as ctx:
                face_engine._check_model_files(root)
            self.assertEqual(ctx.exception.kind, "missing")
            (root / "det.onnx").write_bytes(b"")
            with self.assertRaises(ModelLoadError) as ctx:
                face_engine._check_model_files(root)
            self.assertEqual(ctx.exception.kind, "corrupt")


class ReferenceTest(unittest.TestCase):
    def test_reasons(self):
        engine = _engine(_App(faces=[]))
        self.assertEqual(engine.embed_reference("")[1], "missing")
        self.assertEqual(engine.embed_reference("   ")[1], "missing")
        self.assertEqual(engine.embed_reference("bm90IGFuIGltYWdl")[1], "not_image")
        self.assertEqual(engine.embed_reference(_jpeg(30, 30))[1], "too_small")
        self.assertEqual(engine.embed_reference(_jpeg())[1], "no_face")

    def test_padding_retry_and_data_prefix(self):
        app = _App()
        results = [[], [_Face(80)]]
        app.get = lambda frame: results.pop(0)
        engine = _engine(app)
        embedding, reason = engine.embed_reference("data:image/jpeg;base64," + _jpeg())
        self.assertEqual(reason, "ok")
        self.assertAlmostEqual(float(np.linalg.norm(embedding)), 1.0, places=4)

    def test_model_not_ready(self):
        engine = _engine(_App())
        engine._initialized = False
        self.assertEqual(engine.embed_reference(_jpeg())[1], "model_not_ready")

    def test_detection_error_is_reason_not_exception(self):
        engine = _engine(_App(error=RuntimeError("boom")))
        self.assertEqual(engine.embed_reference(_jpeg())[1], "error")

    def test_decode_prefix(self):
        raw = decode_photo_base64("data:image/png;base64," + base64.b64encode(b"abc").decode())
        self.assertEqual(raw, b"abc")


class GpuFallbackTest(unittest.TestCase):
    def test_repeated_gpu_errors_switch_to_cpu(self):
        broken = _App(error=RuntimeError("CUDA failure 700"))
        engine = _engine(broken, gpu=True)
        cpu_app = _App(faces=[_Face()])
        with mock.patch.object(FaceEngine, "_build_app", return_value=cpu_app) as build, \
                mock.patch.object(face_engine, "FACE_REQUIRE_GPU", False):
            frame = np.zeros((64, 64, 3), dtype=np.uint8)
            for _ in range(face_engine._GPU_RUN_ERRORS):
                with self.assertRaises(RuntimeError):
                    engine.detect(frame)
            build.assert_called_once()
            self.assertFalse(engine.uses_gpu)
            self.assertTrue(engine.gpu_failed)
            self.assertEqual(len(engine.detect(frame)), 1)

    def test_single_error_does_not_switch(self):
        engine = _engine(_App(error=RuntimeError("bir marta")), gpu=True)
        with mock.patch.object(FaceEngine, "_build_app") as build:
            with self.assertRaises(RuntimeError):
                engine.detect(np.zeros((8, 8, 3), dtype=np.uint8))
            build.assert_not_called()
        self.assertTrue(engine.uses_gpu)

    def test_gpu_session_failure_falls_back_to_cpu_on_load(self):
        from proctoring.hardware import cuda_runtime

        engine = object.__new__(FaceEngine)
        FaceEngine.__init__(engine)
        cpu_app = _App()
        cpu_app.models = {}
        status = cuda_runtime.CudaStatus()
        status.listed = status.available = True
        with mock.patch.object(cuda_runtime, "prepare", return_value=status), \
                mock.patch.object(
                    cuda_runtime, "providers",
                    return_value=["CUDAExecutionProvider", "CPUExecutionProvider"],
                ), \
                mock.patch.object(face_engine, "_check_model_files"), \
                mock.patch.object(face_engine, "FACE_REQUIRE_GPU", False), \
                mock.patch.object(
                    FaceEngine, "_build_app",
                    side_effect=[RuntimeError("CUDA failure 100: no CUDA-capable device"), cpu_app],
                ) as build:
            engine.initialize()
        self.assertTrue(engine.is_ready)
        self.assertFalse(engine.uses_gpu)
        self.assertTrue(engine.gpu_failed)
        self.assertEqual(build.call_args_list[1].args[1], ["CPUExecutionProvider"])

    def test_corrupt_file_on_gpu_is_not_retried_on_cpu(self):
        from proctoring.hardware import cuda_runtime

        engine = object.__new__(FaceEngine)
        FaceEngine.__init__(engine)
        status = cuda_runtime.CudaStatus()
        status.listed = status.available = True
        with mock.patch.object(cuda_runtime, "prepare", return_value=status), \
                mock.patch.object(
                    cuda_runtime, "providers",
                    return_value=["CUDAExecutionProvider", "CPUExecutionProvider"],
                ), \
                mock.patch.object(face_engine, "_check_model_files"), \
                mock.patch.object(
                    FaceEngine, "_build_app",
                    side_effect=RuntimeError("INVALID_PROTOBUF : Load model from x failed"),
                ) as build:
            with self.assertRaises(RuntimeError):
                engine.initialize()
        build.assert_called_once()
        self.assertEqual(engine.problem.kind, "corrupt")

    def test_state_after_failed_initialize(self):
        engine = object.__new__(FaceEngine)
        FaceEngine.__init__(engine)
        with mock.patch.object(
            FaceEngine, "_initialize_locked", side_effect=MemoryError()
        ):
            with self.assertRaises(MemoryError):
                engine.initialize()
        self.assertEqual(engine.state, "failed")
        self.assertEqual(engine.problem.kind, "memory")


if __name__ == "__main__":
    unittest.main()
