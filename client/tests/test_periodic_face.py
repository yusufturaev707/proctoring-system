"""
Davriy FaceID: yuz yo'q / bir nechta / juda uzoq - "solishtirib bo'lmadi",
"mos kelmadi" EMAS (`ExamWebViewPage._run_face_check`).

Ilgari bunday tekshiruv `face/periodic/` ga ball 0 bilan ketardi: har
oraliqda jurnal qatori + JPEG + HIGH hodisa + `face_fails` va oxiri
`high_suspicion_identity`. Yo'qlik o'z kanalida (`FaceEpisodes`).
"""

import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from ui.pages.exam_webview_page import ExamWebViewPage


def vector(seed):
    value = np.random.default_rng(seed).normal(size=512).astype(np.float32)
    return value / np.linalg.norm(value)


REFERENCE = vector(1)


def page(embedding, faces):
    return SimpleNamespace(
        _monitor=SimpleNamespace(is_active=True, set_face_checks=mock.Mock()),
        _state=SimpleNamespace(face_reference=REFERENCE),
        _supervisor=SimpleNamespace(is_active=False, identity_ready=False),
        _camera=object(),
        _current_face=lambda: (embedding, faces),
        _face_threshold=lambda: 40,
        _report_face_failure=mock.Mock(),
        _update_status_tooltip=mock.Mock(),
        _status={},
        _face_checks=0,
        _passed_since_last=0,
    )


class PeriodicFaceTests(unittest.TestCase):
    def test_uncomparable_is_not_reported(self):
        for embedding, faces in ((None, 0), (None, 2), (None, 1)):
            with self.subTest(faces=faces):
                stub = page(embedding, faces)
                ExamWebViewPage._run_face_check(stub)
                stub._report_face_failure.assert_not_called()
                self.assertEqual((stub._face_checks, stub._passed_since_last), (0, 0))

    def test_real_mismatch_is_reported(self):
        stub = page(vector(2), 1)
        ExamWebViewPage._run_face_check(stub)
        stub._report_face_failure.assert_called_once()
        self.assertEqual(stub._face_checks, 1)

    def test_match_counts_as_passed(self):
        stub = page(REFERENCE.copy(), 1)
        ExamWebViewPage._run_face_check(stub)
        stub._report_face_failure.assert_not_called()
        self.assertEqual((stub._face_checks, stub._passed_since_last), (1, 1))


if __name__ == "__main__":
    unittest.main()
