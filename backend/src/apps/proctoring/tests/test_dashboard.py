"""
Dashboard agregatlari: natija shakli va umumiy kesh.

Selektorlar tarixni o'qimaslik uchun qayta yozilgan (`zone_breakdown` —
ikki so'rov, `event_type_breakdown` — partitsiya oralig'i). Bu testlar
natija avvalgidek qolganini qo'riqlaydi.
"""

from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.proctoring import selectors
from apps.proctoring.models import ExamSession, ProctoringEvent
from apps.proctoring.tests import factories
from apps.proctoring.tests.test_client_api import bearer


class ZoneBreakdownTests(TestCase):
    def test_counts_only_the_requested_date_and_keeps_empty_zones(self):
        region = factories.make_region()
        busy = factories.make_zone(region=region)
        empty = factories.make_zone(region=region)
        today = timezone.localdate()
        factories.make_session(computer=factories.make_computer(zone=busy))
        factories.make_session(
            computer=factories.make_computer(zone=busy), status=ExamSession.Status.TERMINATED
        )
        # Kechagi sessiya bugungi kesimga KIRMAYDI.
        factories.make_session(
            computer=factories.make_computer(zone=busy), exam_date=today - timedelta(days=1)
        )

        rows = {row["id"]: row for row in selectors.zone_breakdown(region_id=region.pk)}

        self.assertEqual(
            {key: rows[busy.pk][key] for key in ("total", "active", "terminated", "problems")},
            {"total": 2, "active": 1, "terminated": 1, "problems": 0},
        )
        self.assertEqual(rows[empty.pk]["total"], 0)
        self.assertEqual(set(rows[busy.pk]), {
            "id", "name", "number", "region__name", "total", "active", "terminated", "problems",
        })


class EventTypeBreakdownTests(TestCase):
    def test_counts_events_of_sessions_of_that_date(self):
        session = factories.make_session()
        now = timezone.now()
        ProctoringEvent.objects.bulk_create([
            ProctoringEvent(session=session, type="window_blur", severity=1, occurred_at=now, payload={}),
            ProctoringEvent(session=session, type="window_blur", severity=1, occurred_at=now, payload={}),
            ProctoringEvent(session=session, type="multi_monitor", severity=2, occurred_at=now, payload={}),
        ])

        rows = selectors.event_type_breakdown(exam_date=timezone.localdate().isoformat())

        self.assertEqual(rows[0], {"type": "window_blur", "count": 2})
        self.assertEqual(len(rows), 2)

    def test_invalid_date_falls_back_to_today(self):
        self.assertEqual(selectors.event_type_breakdown(exam_date="sana-emas"), [])


class DashboardCacheTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = factories.make_user(permissions=["dashboard.view"])
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=bearer(self.user))

    def test_second_request_within_ttl_is_served_from_cache(self):
        with override_settings(PROCTORING={**settings.PROCTORING, "DASHBOARD_CACHE_SECONDS": 10}):
            first = self.client.get("/api/v1/dashboard/summary/")
            factories.make_session()
            second = self.client.get("/api/v1/dashboard/summary/")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(
            first.json()["data"]["summary"]["total"], second.json()["data"]["summary"]["total"]
        )
        # Platforma holati keshlanmaydi — har javobda bor.
        self.assertIn("external_platform", second.json()["data"])

    def test_zero_ttl_disables_cache(self):
        with override_settings(PROCTORING={**settings.PROCTORING, "DASHBOARD_CACHE_SECONDS": 0}):
            first = self.client.get("/api/v1/dashboard/zones/")
            factories.make_session()
            second = self.client.get("/api/v1/dashboard/zones/")
        total = lambda response: sum(row["total"] for row in response.json()["data"]["zones"])  # noqa: E731
        self.assertEqual(total(second), total(first) + 1)
