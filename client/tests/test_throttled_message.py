"""
429 matni: operator NIMA to'silganini va qancha kutishini biladi.

Server `details.scope` (`pinfl` / `device` / `operator`) va haqiqiy
`details.wait` ni beradi (`apps/common/throttling.py`). Har chegarada
operatorning harakati boshqa — matn shuni aytishi shart.
"""

import unittest

from core.errors import ERROR_MESSAGES, throttle_scope, throttled_message


class ThrottledMessageTests(unittest.TestCase):
    def test_pinfl_scope_says_other_candidates_are_fine(self):
        text = throttled_message({"scope": "pinfl", "wait": 1500}, 300)
        self.assertIn("Bu JSHSHIR", text)
        self.assertIn("~25 daqiqaga", text)
        self.assertIn("Boshqa talabgorlarni", text)

    def test_device_and_operator_scopes(self):
        self.assertIn("boshqa kompyuterda", throttled_message({"scope": "device", "wait": 61}))
        self.assertIn("~2 daqiqaga", throttled_message({"scope": "device", "wait": 61}))
        self.assertIn("Administratorga", throttled_message({"scope": "operator", "wait": 3600}))

    def test_seconds_when_short(self):
        self.assertIn("40 soniyaga", throttled_message({"scope": "pinfl", "wait": 40}))

    def test_wait_falls_back_to_retry_after(self):
        self.assertIn("~5 daqiqaga", throttled_message({"scope": "pinfl"}, 300.0))

    def test_no_wait_keeps_sentence_clean(self):
        text = throttled_message({"scope": "pinfl"})
        self.assertNotIn("  ", text)
        self.assertTrue(text.startswith("Bu JSHSHIR bilan qidiruv vaqtincha"))

    def test_unknown_or_missing_scope_is_the_old_text(self):
        self.assertEqual(throttle_scope({"scope": "zzz"}), "")
        self.assertEqual(throttle_scope(None), "")
        self.assertEqual(
            throttled_message({}, 30),
            ERROR_MESSAGES["throttled"].rstrip(".") + " (30 soniyadan keyin)",
        )


if __name__ == "__main__":
    unittest.main()
