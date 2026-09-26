"""
O'rindiq kalibrlashi — "kadrdagi odamlardan qaysi biri TALABGOR".

Ishga tushirish (`client/` dan):

    venv/Scripts/python -m unittest discover -s tests

Ssenariylar HAQIQIY nosozlikdan: ish joyi tepasidagi IP kamera
(2688x1520), stolda o'tirgan talabgor va undan BALANDROQ chiqadigan
tik turgan odam. Ilgari "eng baland ramka — talabgor" qoidasi aynan
shu kadrda talabgorning o'zini «Begona odam» deb belgilagan edi.

Qt ham, model ham kerak emas: analizator sof mantiq.
"""

from __future__ import annotations

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from proctoring.behavior.behavior_analyzer import BehaviorAnalyzer, FrameFeatures  # noqa: E402
from proctoring.behavior.seat_anchor import SeatAnchor  # noqa: E402
from proctoring.evidence.recorder import _boxes_of  # noqa: E402
from proctoring.pose.pose_estimator import KEYPOINTS, Pose  # noqa: E402
from proctoring.tracking.bytetrack import Track  # noqa: E402

W, H = 2688, 1520
#: Obyekt tahlili chastotasi (profil bo'yicha ~5 kadr/s).
STEP = 0.2

#: Stolda o'tirgan talabgor — kadrning chap pastida, KICHIK ramka.
SEATED = [134, 842, 1153, 1511]
#: Stol yonida tik turgan odam — kameraga yaqin, BALAND ramka.
STANDING = [1900, 150, 2500, 1500]


def person(track_id, bbox, score=0.9):
    return Track(track_id=track_id, cls="Odam", bbox=np.array(bbox, dtype=float),
                 score=score, code=0)


def jitter(bbox, t, amplitude=8):
    """O'tirgan odamning kichik tebranishi (yozadi, egiladi)."""
    dx = amplitude * np.sin(t * 1.7)
    dy = amplitude * np.cos(t * 1.3)
    return [bbox[0] + dx, bbox[1] + dy, bbox[2] + dx, bbox[3] + dy]


class Scene:
    """Vaqt bo'yicha kadrlar yuboradigan yordamchi."""

    def __init__(self):
        self.analyzer = BehaviorAnalyzer({})
        self.t = 100.0
        self.events = []

    def run(self, seconds, tracks_at, poses_at=None):
        for _ in range(int(round(seconds / STEP))):
            self.t += STEP
            self.events += self.analyzer.analyse(FrameFeatures(
                timestamp=self.t, camera_role="secondary", frame_width=W, frame_height=H,
                tracks=tracks_at(self.t),
                poses=poses_at(self.t) if poses_at else None,
            ))

    def opened(self, event_type):
        return [e for e in self.events if e.type == event_type and e.severity > 0]


class SeatCalibrationTests(unittest.TestCase):
    def test_seated_student_is_calibrated_despite_operator_at_start(self):
        """Operator boshida yonida turib harakatlanadi — o'rindiq baribir talabgorniki."""
        scene = Scene()

        def start(t):
            # Operator stol yonida yuradi (katta, lekin barqaror emas).
            walk = 300 * np.sin(t)
            return [person(1, jitter(SEATED, t)),
                    person(2, [STANDING[0] + walk, STANDING[1], STANDING[2] + walk, STANDING[3]])]

        scene.run(6, start)
        scene.run(12, lambda t: [person(1, jitter(SEATED, t))])

        seat = scene.analyzer.seat_of("secondary")
        self.assertIsNotNone(seat)
        # O'rindiq — o'tirgan talabgorning markazi (kadrga nisbatan).
        self.assertAlmostEqual(seat[0], (SEATED[0] + SEATED[2]) / 2 / W, delta=0.02)
        self.assertAlmostEqual(seat[1], (SEATED[1] + SEATED[3]) / 2 / H, delta=0.02)
        # Operator boshida turgani "ikkinchi odam" emas (kalibrlash sukuti).
        self.assertEqual(scene.opened("second_person"), [])

    def test_standing_person_is_the_stranger_not_the_student(self):
        """ASL XATO: baland ramkali tik turgan odam talabgor bo'lib qolmaydi."""
        scene = Scene()
        scene.run(16, lambda t: [person(1, jitter(SEATED, t))])
        scene.run(4, lambda t: [person(1, jitter(SEATED, t)), person(7, STANDING)])

        events = scene.opened("second_person")
        self.assertEqual(len(events), 1)
        marks = {mark["kind"]: mark for mark in _boxes_of(events[0])}
        # Talabgor belgisi — o'tirgan odamda (kadr chap pastida).
        self.assertLess(marks["student"]["box"][0], 0.1)
        self.assertGreater(marks["student"]["box"][1], 0.5)
        # Begona — tik turgan odam.
        self.assertGreater(marks["person"]["box"][0], 0.65)

    def test_student_keeps_seat_after_track_id_changes(self):
        """Iz uzilib qayta tug'ilsa (to'silish), o'rindiqdagi yangi iz talabgor."""
        scene = Scene()
        scene.run(16, lambda t: [person(1, jitter(SEATED, t))])
        scene.run(4, lambda t: [person(42, jitter(SEATED, t)), person(7, STANDING)])

        marks = {m["kind"]: m for m in _boxes_of(scene.opened("second_person")[0])}
        self.assertLess(marks["student"]["box"][0], 0.1)

    def test_nobody_at_seat_gives_no_second_person(self):
        """Talabgor joyida yo'q — bu xona kamerasining xulosasi emas (`no_face`)."""
        scene = Scene()
        scene.run(16, lambda t: [person(1, jitter(SEATED, t))])
        scene.run(4, lambda t: [person(7, STANDING), person(8, [1500, 200, 1850, 1450])])
        self.assertEqual(scene.opened("second_person"), [])

    def test_small_background_person_is_ignored(self):
        """Orqa qatordagi kichik odam begona hisoblanmaydi."""
        scene = Scene()
        scene.run(16, lambda t: [person(1, jitter(SEATED, t))])
        scene.run(4, lambda t: [person(1, jitter(SEATED, t)), person(9, [2300, 60, 2450, 300])])
        self.assertEqual(scene.opened("second_person"), [])

    def test_ambiguous_calibration_is_rejected(self):
        """Ikki teng barqaror odam — o'rindiq tanlanmaydi (noto'g'ri nol yomonroq)."""
        anchor = SeatAnchor(calibration_seconds=3)
        t = 0.0
        left = person(1, [400, 500, 1000, 1300])
        right = person(2, [1688, 500, 2288, 1300])
        for _ in range(30):
            t += STEP
            anchor.observe([left, right], W, H, t)
        self.assertFalse(anchor.calibrated)
        # Zaxira qoida baribir javob beradi.
        self.assertIsNotNone(anchor.pick([left.bbox, right.bbox], W, H))

    def test_warmup_is_bounded(self):
        """Kalibrlash noaniq qolsa ham sukut cheksiz davom etmaydi."""
        anchor = SeatAnchor(calibration_seconds=3)
        anchor.observe([], W, H, 0.0)
        self.assertTrue(anchor.warming_up(1.0))
        self.assertFalse(anchor.warming_up(3.5))


class HandBelowDeskTests(unittest.TestCase):
    def test_uses_student_pose_not_first_pose(self):
        """Pose ro'yxatida birinchi turgan odamning qo'llari talabgorga yozilmaydi."""
        def pose(bbox, wrists_visible):
            keypoints = np.zeros((len(KEYPOINTS), 3), dtype=float)
            x1, y1, x2, y2 = bbox
            index = {name: i for i, name in enumerate(KEYPOINTS)}
            shoulder_y = y1 + (y2 - y1) * 0.3
            keypoints[index["left_shoulder"]] = (x1 + 50, shoulder_y, 0.9)
            keypoints[index["right_shoulder"]] = (x2 - 50, shoulder_y, 0.9)
            if wrists_visible:
                keypoints[index["left_wrist"]] = (x1 + 80, shoulder_y + 60, 0.9)
                keypoints[index["right_wrist"]] = (x2 - 80, shoulder_y + 60, 0.9)
            return Pose(score=0.9, bbox=np.array(bbox, dtype=float), keypoints=keypoints)

        scene = Scene()
        scene.run(16, lambda t: [person(1, jitter(SEATED, t))])
        # Tik turgan odam birinchi (qo'llari ko'rinmaydi), talabgor ikkinchi (qo'llari stolda).
        scene.run(
            5,
            lambda t: [person(1, jitter(SEATED, t))],
            lambda t: [pose(STANDING, wrists_visible=False), pose(SEATED, wrists_visible=True)],
        )
        self.assertEqual(scene.opened("hand_below_desk"), [])


if __name__ == "__main__":
    unittest.main()
