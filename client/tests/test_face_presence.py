"""
"Yuz yo'q" / "bir nechta yuz" - epizod bo'yicha (`services/face_presence.py`).

Ilgari har kadr hodisa edi: 10 natija/s -> panelga sekundiga o'nlab
"Yuz topilmadi". Endi bitta epizodda ko'pi bilan ikki hodisa va bitta yopilish (davomiylik).
"""

import unittest

from services.face_presence import FaceEpisodes


def feed(episodes, state, start, seconds, step=0.1, faces=0):
    """`seconds` davomida har `step` da bitta natija (10/s)."""
    events, t = [], start
    while t < start + seconds - 1e-9:
        events.extend(episodes.observe(state, t, faces=faces))
        t += step
    return events, t


class FaceEpisodesTests(unittest.TestCase):
    def test_long_absence_gives_two_events_not_hundreds(self):
        episodes = FaceEpisodes(warn_s=2, suspicious_s=5)
        events, _ = feed(episodes, "none", 0.0, 30.0)  # 300 ta "yuz yo'q" kadri
        self.assertEqual([(e[0], e[1], e[2]["stage"]) for e in events], [
            ("face_not_found", 2, "warning"),
            ("face_not_found", 3, "suspicious"),
        ])
        self.assertGreaterEqual(events[0][2]["duration_ms"], 2000)

    def test_short_glance_away_is_silent(self):
        episodes = FaceEpisodes(warn_s=2, suspicious_s=5)
        events, t = feed(episodes, "none", 0.0, 1.5)
        more, _ = feed(episodes, "ok", t, 3.0)
        self.assertEqual(events + more, [])

    def test_flicker_does_not_split_episode(self):
        episodes = FaceEpisodes(warn_s=2, suspicious_s=5, release_s=1.0)
        events, t = feed(episodes, "none", 0.0, 2.5)
        flicker, t = feed(episodes, "ok", t, 0.3)  # bitta-ikki kadr yuz "ko'rindi"
        rest, _ = feed(episodes, "none", t, 1.0)
        self.assertEqual(len(events + flicker + rest), 1)

    def test_new_episode_after_face_returns(self):
        episodes = FaceEpisodes(warn_s=2, suspicious_s=5, release_s=1.0)
        first, t = feed(episodes, "none", 0.0, 3.0)
        _, t = feed(episodes, "ok", t, 2.0)
        second, _ = feed(episodes, "none", t, 3.0)
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)

    def test_multiple_faces_once_per_episode(self):
        episodes = FaceEpisodes()
        quick, t = feed(episodes, "multiple", 0.0, 0.5, faces=2)
        _, t = feed(episodes, "ok", t, 2.0)
        long, _ = feed(episodes, "multiple", t, 20.0, faces=3)
        self.assertEqual(quick, [])
        self.assertEqual([(e[0], e[1], e[2]["faces"]) for e in long], [("multiple_faces", 3, 3)])

    def test_far_face_is_not_absence(self):
        episodes = FaceEpisodes(warn_s=2, suspicious_s=5)
        events, _ = feed(episodes, "far", 0.0, 9.0)  # suyanib o'tirdi - hodisa yo'q
        self.assertEqual(events, [])

    def test_long_far_episode_escalates_once(self):
        episodes = FaceEpisodes(far_warn_s=10, far_unverified_s=120)
        events, _ = feed(episodes, "far", 0.0, 300.0, step=0.5)
        self.assertEqual([(e[0], e[1], e[2]["stage"]) for e in events], [
            ("face_too_far", 1, "warning"),
            ("face_too_far", 2, "unverified"),
        ])

    def test_episode_end_carries_total_duration(self):
        episodes = FaceEpisodes(warn_s=2, suspicious_s=5, release_s=1.0)
        opened, t = feed(episodes, "none", 0.0, 1800.0, step=0.5)  # 30 daqiqa
        closed, _ = feed(episodes, "ok", t, 2.0)
        self.assertEqual(len(opened), 2)
        self.assertEqual(len(closed), 1)
        event_type, severity, payload = closed[0]
        self.assertEqual((event_type, severity, payload["closed"]), ("face_not_found", 0, True))
        # Davomiylik yuz QAYTGAN paytgacha, yopilish kechikishisiz.
        self.assertAlmostEqual(payload["duration_ms"] / 1000, 1800.0, delta=1.0)

    def test_silent_episode_has_no_closing(self):
        episodes = FaceEpisodes(warn_s=2, suspicious_s=5)
        events, t = feed(episodes, "none", 0.0, 1.0)
        more, _ = feed(episodes, "ok", t, 2.0)
        self.assertEqual(events + more + episodes.close_all(t + 3), [])

    def test_close_all_on_stop(self):
        episodes = FaceEpisodes(warn_s=2, suspicious_s=5)
        _, t = feed(episodes, "multiple", 0.0, 3.0, faces=3)
        closing = episodes.close_all(t)
        self.assertEqual([(e[0], e[1], e[2]["faces"]) for e in closing], [("multiple_faces", 0, 3)])
        self.assertEqual(episodes.close_all(t + 1), [])  # takroriy to'xtatish - bo'sh

    def test_thresholds_from_policy(self):
        episodes = FaceEpisodes.from_config(
            {"proctoring": {"temporal": {"no_face_warn_s": 4, "no_face_suspicious_s": 9}}}
        )
        self.assertEqual((episodes.warn_s, episodes.suspicious_s), (4.0, 9.0))
        # "Uzoq yuz" - Setting profilidan (`face.*`), siyosatdan emas.
        far = FaceEpisodes.from_config({"face": {"far_warn_s": 30, "far_unverified_s": 300}})
        self.assertEqual((far.far_warn_s, far.far_unverified_s), (30.0, 300.0))
        self.assertEqual(FaceEpisodes.from_config(None).far_warn_s, 10.0)
        # Teskari tartib (eski server/buzilgan baza) - ikkinchisi birinchisidan oldin kelmaydi.
        swapped = FaceEpisodes.from_config({"face": {"far_warn_s": 60, "far_unverified_s": 20}})
        self.assertEqual(swapped.far_unverified_s, 60.0)
        self.assertEqual(FaceEpisodes.from_config(None).warn_s, 2.0)
        self.assertEqual(FaceEpisodes.from_config({"proctoring": {"temporal": {"no_face_warn_s": "x"}}}).warn_s, 2.0)
