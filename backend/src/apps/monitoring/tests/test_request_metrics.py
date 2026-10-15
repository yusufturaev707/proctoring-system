"""
So'rovlar statistikasi: marshrut nomi, gistogramma persentili va
Redis'dagi daqiqalik chelaklar.
"""

import time
from collections import Counter
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from apps.common.tests.utils import RedisStateMixin
from apps.monitoring import request_metrics, store
from apps.monitoring.request_metrics import BUCKETS_MS, _percentile, clean_route


class RouteNameTests(SimpleTestCase):
    def test_router_regex_becomes_pattern(self):
        self.assertEqual(
            clean_route("api/v1/^sessions/(?P<pk>[^/.]+)/events/$"), "sessions/{pk}/events/",
        )

    def test_path_converter(self):
        self.assertEqual(clean_route("api/v1/cameras/<int:pk>/live/"), "cameras/{pk}/live/")

    def test_plain_route(self):
        self.assertEqual(clean_route("api/v1/client/heartbeat/"), "client/heartbeat/")


class PercentileTests(SimpleTestCase):
    def test_empty_histogram(self):
        self.assertIsNone(_percentile([0] * (len(BUCKETS_MS) + 1), BUCKETS_MS, 0.95))

    def test_interpolates_inside_bucket(self):
        histogram = [0] * (len(BUCKETS_MS) + 1)
        histogram[3] = 100  # 50..100 ms
        self.assertEqual(_percentile(histogram, BUCKETS_MS, 0.5), 75.0)

    def test_overflow_bucket_reports_lower_bound(self):
        """Oxirgi chelak yuqori chegarasiz — uydirma son emas, "≥ 10 s"."""
        histogram = [0] * (len(BUCKETS_MS) + 1)
        histogram[-1] = 10
        self.assertEqual(_percentile(histogram, BUCKETS_MS, 0.99), float(BUCKETS_MS[-1]))

    def test_summary_error_percent(self):
        summary = request_metrics.summarize(Counter({"n": 200, "c2": 198, "c5": 2, "us": 200_000}), 60)
        self.assertEqual(summary["error_pct"], 1.0)
        self.assertEqual(summary["avg_ms"], 1.0)
        self.assertAlmostEqual(summary["rps"], 3.33, places=2)


@override_settings(SYSTEM_MONITOR={"ENABLED": True, "CACHE_SECONDS": 0})
class AggregatorRedisTests(RedisStateMixin, SimpleTestCase):
    def test_flush_and_read_windows(self):
        aggregator = request_metrics._Aggregator()
        for _ in range(9):
            aggregator.record("GET sessions/", 200, 30)
        aggregator.record("POST client/heartbeat/", 503, 1200)
        aggregator.flush()

        window = request_metrics.windows(spans=(1,))["1m"]
        self.assertEqual(window["count"], 10)
        self.assertEqual(window["status"]["5xx"], 1)
        self.assertEqual(window["status"]["503"], 1)

        routes = {item["route"]: item for item in request_metrics.routes(5)["routes"]}
        self.assertEqual(routes["GET sessions/"]["count"], 9)
        self.assertEqual(routes["POST client/heartbeat/"]["errors_5xx"], 1)

    def test_buckets_expire(self):
        aggregator = request_metrics._Aggregator()
        aggregator.record("GET x/", 200, 5)
        aggregator.flush()
        minute = int(time.time() // 60)
        ttl = store.client_or_none().ttl(request_metrics.totals_key(minute))
        self.assertGreater(ttl, 0)


@override_settings(SYSTEM_MONITOR={"ENABLED": True, "CACHE_SECONDS": 0})
class MiddlewareTests(TestCase):
    def test_records_route_pattern_not_url(self):
        recorded = []
        with mock.patch.object(
            request_metrics.aggregator, "record", side_effect=lambda *args: recorded.append(args),
        ):
            APIClient().get("/api/v1/sessions/123/")
        self.assertTrue(recorded)
        route, status, _duration = recorded[-1]
        self.assertEqual(route, "GET sessions/{pk}/")
        self.assertEqual(status, 401)

    def test_redis_failure_does_not_break_request(self):
        with mock.patch.object(store, "client_or_none", side_effect=OSError("redis yo'q")), \
                mock.patch.object(request_metrics, "FLUSH_INTERVAL_S", 0):
            response = APIClient().get("/healthz/")
        self.assertEqual(response.status_code, 200)
