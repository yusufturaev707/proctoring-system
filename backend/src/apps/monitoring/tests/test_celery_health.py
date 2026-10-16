"""
Davriy vazifalar sog'lig'i: signal oxirgi bajarilishni yozadi, o'quvchi
uni beat jadvali bilan solishtiradi.
"""

import json
import time
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from celery.schedules import crontab
from django.conf import settings
from django.test import SimpleTestCase, override_settings

from apps.common.tests.utils import RedisStateMixin
from apps.monitoring import celery_health


class DescribeTests(SimpleTestCase):
    def test_interval(self):
        self.assertEqual(celery_health._describe(5.0), ("har 5 s", 5.0))
        self.assertEqual(celery_health._describe(timedelta(minutes=1)), ("har 60 s", 60.0))

    def test_crontab(self):
        self.assertEqual(celery_health._describe(crontab(hour=3, minute=0)), ("har kuni 03:00", None))
        self.assertEqual(celery_health._describe(crontab(minute=25)), ("har soat :25", None))


@override_settings(SYSTEM_MONITOR={"ENABLED": True})
class PeriodicHealthTests(RedisStateMixin, SimpleTestCase):
    def run_task(self, name, state="SUCCESS"):
        task = SimpleNamespace(name=name)
        celery_health._on_prerun(task_id="t1")
        celery_health._on_postrun(task_id="t1", task=task, state=state)

    def tasks(self, now=None):
        return {item["name"]: item for item in celery_health.periodic_tasks(now=now)["tasks"]}

    def test_fresh_run_is_ok(self):
        self.run_task("proctoring.flush_event_buffer")
        task = self.tasks()["flush-event-buffer"]
        self.assertEqual(task["health"], "ok")
        self.assertIsNotNone(task["last_runtime_s"])

    def test_old_run_is_stale(self):
        self.run_task("proctoring.flush_event_buffer")
        task = self.tasks(now=time.time() + 120)["flush-event-buffer"]  # oraliq 5 s
        self.assertEqual(task["health"], "stale")

    def test_never_ran(self):
        self.run_task("proctoring.flush_event_buffer")
        self.assertEqual(self.tasks()["probe-cameras"]["health"], "never")

    def record_at(self, name, ts):
        celery_health.store.client_or_none().hset(
            celery_health.LAST_RUN_KEY, name, json.dumps({"ts": ts, "state": "SUCCESS", "runtime_s": 1.0}),
        )

    def last_local_run(self, hour, minute):
        """Jadval zonasidagi eng yaqin o'tgan HH:MM (Unix vaqti)."""
        local = datetime.now(ZoneInfo(settings.CELERY_TIMEZONE))
        run = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if run > local:
            run -= timedelta(days=1)
        return run.timestamp()

    def test_daily_task_that_ran_today_is_ok(self):
        """Regressiya: UTC'dagi vaqt crontab'da "o'tkazib yuborilgan" ko'rinardi."""
        self.record_at("proctoring.purge_expired_artifacts", self.last_local_run(4, 0) + 60)
        self.assertEqual(self.tasks()["purge-expired-artifacts"]["health"], "ok")

    def test_daily_task_missed_is_stale(self):
        self.record_at("proctoring.purge_expired_artifacts", self.last_local_run(4, 0) - 2 * 86400)
        self.assertEqual(self.tasks()["purge-expired-artifacts"]["health"], "stale")

    def test_failure_counted(self):
        self.run_task("devices.probe_cameras", state="FAILURE")
        task = self.tasks()["probe-cameras"]
        self.assertEqual(task["health"], "failed")
        self.assertEqual(task["failures_24h"], 1)
