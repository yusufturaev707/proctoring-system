"""
Test platformasiga natija yuborish vazifalari (`platform_push.py`).

Navbat — `default` (`maintenance` worker'i ham uni o'qiydi): yangi
systemd servisi kerak emas. Har urinish qisqa (`EXTERNAL_PLATFORM`
timeout'lari), platforma o'chiq bo'lsa breaker darhol `PUSH_RETRY` beradi —
worker thread'lari osilib qolmaydi.
"""

from __future__ import annotations

import logging

from celery import shared_task

from apps.integrations import exam_site, platform_push

logger = logging.getLogger(__name__)

#: 30 s, 60 s, 120 s, 240 s — platforma ~7 daqiqa ichida tiklansa yetadi.
#: Ko'proq kutish ma'nosiz: skrinshot oqimi to'xtamaydi va navbat o'sadi.
MAX_RETRIES = 4


def _retry_or_give_up(task, outcome: str, what: str):
    if outcome != exam_site.PUSH_RETRY:
        return outcome
    if task.request.retries >= MAX_RETRIES:
        logger.error("Platformaga yuborilmadi, urinishlar tugadi: %s", what)
        return "failed"
    raise task.retry(countdown=30 * (2 ** task.request.retries), max_retries=MAX_RETRIES)


@shared_task(bind=True, name="integrations.push_face_result", ignore_result=True)
def push_face_result(self, log_id: int):
    outcome = platform_push.send_face_result(log_id)
    return _retry_or_give_up(self, outcome, f"face_result id={log_id}")


@shared_task(bind=True, name="integrations.push_screenshot", ignore_result=True)
def push_screenshot(self, source: str, ref: dict):
    outcome = platform_push.send_screenshot(source, ref)
    return _retry_or_give_up(self, outcome, f"screenshot {source}:{ref.get('id') or ref.get('object_key')}")
