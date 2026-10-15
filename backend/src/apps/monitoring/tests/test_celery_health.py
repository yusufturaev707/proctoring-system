"""
Davriy vazifalar sog'lig'i: signal oxirgi bajarilishni yozadi, o'quvchi
uni beat jadvali bilan solishtiradi.
"""

import time
from datetime import timedelta
from types import SimpleNamespace

from celery.schedules import crontab
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

    def test_failure_counted(self):
        self.run_task("devices.probe_cameras", state="FAILURE")
        task = self.tasks()["probe-cameras"]
        self.assertEqual(task["health"], "failed")
        self.assertEqual(task["failures_24h"], 1)
