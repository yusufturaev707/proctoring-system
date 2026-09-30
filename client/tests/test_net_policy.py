"""
Tarmoq siyosati (`services/net_policy.py`) va WebView xato qoidalari
(`ui/pages/webview_errors.py`) — sof mantiq.

Qo'riqlanadigan narsa — "reconnect storm" bo'lmasligi: kechikish
o'sadi, chegaralangan, jitter'li va `Retry-After` dan qisqa emas.
"""

import unittest

from services import net_policy as np
from ui.pages import webview_errors as we


class BackoffDelayTests(unittest.TestCase):
    def test_grows_exponentially_until_cap(self):
        values = [np.backoff_delay(i, base=1, cap=30, rng=lambda: 1.0) for i in range(8)]
        self.assertEqual(values, [1, 2, 4, 8, 16, 30, 30, 30])

    def test_equal_jitter_keeps_lower_bound(self):
        # rng=0 -> yarmi: hech qachon ~0 (darhol qayta urinish) emas.
        self.assertEqual(np.backoff_delay(3, base=1, cap=30, rng=lambda: 0.0), 4.0)
        self.assertEqual(np.backoff_delay(3, base=1, cap=30, rng=lambda: 0.5), 6.0)

    def test_huge_attempt_does_not_overflow(self):
        self.assertEqual(np.backoff_delay(10_000, base=1, cap=60, rng=lambda: 1.0), 60)

    def test_real_jitter_spreads_values(self):
        values = {round(np.backoff_delay(4, base=1, cap=60), 3) for _ in range(50)}
        self.assertGreater(len(values), 10)
        self.assertTrue(all(8.0 <= v <= 16.0 for v in values))


class RetryAfterTests(unittest.TestCase):
    def test_seconds(self):
        self.assertEqual(np.parse_retry_after("12"), 12.0)
        self.assertEqual(np.parse_retry_after(" 0 "), 0.0)

    def test_invalid_and_missing(self):
        for value in (None, "", "soon", "nan"):
            self.assertIsNone(np.parse_retry_after(value), value)

    def test_negative_and_huge_are_clamped(self):
        self.assertEqual(np.parse_retry_after("-5"), 0.0)
        self.assertEqual(np.parse_retry_after("86400"), np.MAX_RETRY_AFTER_S)

    def test_http_date(self):
        now = 1_700_000_000.0  # 2023-11-14 22:13:20 GMT
        self.assertAlmostEqual(
            np.parse_retry_after("Tue, 14 Nov 2023 22:13:50 GMT", now=now), 30.0
        )


class ClassificationTests(unittest.TestCase):
    def test_retryable_statuses(self):
        for status in (408, 429, 502, 503, 504):
            self.assertTrue(np.is_retryable_status(status), status)
        for status in (200, 400, 401, 403, 404, 409, 500):
            self.assertFalse(np.is_retryable_status(status), status)

    def test_poison_only_payload_errors(self):
        for status in (400, 413, 415, 422):
            self.assertTrue(np.is_poison_payload(status), status)
        # 401/403/404/409/429/5xx — element to'g'ri, muhit vaqtincha noto'g'ri.
        for status in (0, 401, 403, 404, 408, 409, 429, 500, 502, 503):
            self.assertFalse(np.is_poison_payload(status), status)


class BackoffStateTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.backoff = np.Backoff(base=5, cap=60, rng=lambda: 1.0, clock=lambda: self.now)

    def test_failure_blocks_until_delay(self):
        self.assertTrue(self.backoff.ready())
        self.assertEqual(self.backoff.failure(), 5)
        self.assertFalse(self.backoff.ready())
        self.now += 5
        self.assertTrue(self.backoff.ready())
        self.assertEqual(self.backoff.failure(), 10)

    def test_retry_after_is_respected(self):
        delay = self.backoff.failure(retry_after=40)
        self.assertGreaterEqual(delay, 40)

    def test_success_resets(self):
        self.backoff.failure()
        self.backoff.failure()
        self.backoff.success()
        self.assertTrue(self.backoff.ready())
        self.assertEqual(self.backoff.failure(), 5)

    def test_nudge_only_shortens(self):
        self.backoff.failures = 4
        self.backoff.failure()  # 60 s
        self.backoff.nudge(5)
        self.assertLessEqual(self.backoff.remaining(), 5)
        self.backoff.success()
        self.backoff.nudge(5)  # kutish yo'q edi - uzaytirilmaydi
        self.assertTrue(self.backoff.ready())


class LoadErrorTests(unittest.TestCase):
    def test_aborted_and_site_4xx_are_silent(self):
        self.assertIsNone(we.describe_load_error("ConnectionErrorDomain", we.ERR_ABORTED))
        self.assertIsNone(we.describe_load_error("HttpStatusCodeDomain", 404))

    def test_site_5xx_retries(self):
        title, text, auto = we.describe_load_error("HttpStatusCodeDomain", 502)
        self.assertTrue(auto)
        self.assertIn("502", text)

    def test_dns_and_offline_retry(self):
        self.assertTrue(we.describe_load_error("DnsErrorDomain", -105)[2])
        self.assertTrue(we.describe_load_error("ConnectionErrorDomain", -106)[2])

    def test_certificate_error_does_not_auto_retry(self):
        self.assertFalse(we.describe_load_error("CertificateErrorDomain", -202)[2])


class CrashGuardTests(unittest.TestCase):
    def test_limit_within_window(self):
        now = [0.0]
        guard = we.CrashGuard(limit=3, window_s=100, clock=lambda: now[0], rng=lambda: 1.0)
        delays = [guard.record() for _ in range(3)]
        self.assertEqual(delays, [1.0, 2.0, 4.0])
        self.assertIsNone(guard.record())  # 4-qulash - avtomatik yuklash yo'q

    def test_old_crashes_expire(self):
        now = [0.0]
        guard = we.CrashGuard(limit=2, window_s=100, clock=lambda: now[0], rng=lambda: 1.0)
        guard.record()
        guard.record()
        now[0] = 500.0
        self.assertEqual(guard.record(), 1.0)


if __name__ == "__main__":
    unittest.main()
