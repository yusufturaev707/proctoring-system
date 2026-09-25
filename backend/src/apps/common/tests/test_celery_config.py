"""
Celery konfiguratsiyasi — ishchi o'lik bo'lsa ham tizim o'zini tiklay olishi.

Haqiqiy hodisadan: ishlab chiqish mashinasida (Windows) ishchilar
`prefork` bilan ishga tushgan va ~3 hafta BIRORTA ham vazifa
bajarmagan (`inspect stats` -> `"total": {}`). Shu vaqt ichida broker
navbatlarida ~93 000 ta davriy "tik" to'plangan edi.
"""

import sys
import unittest

from django.test import SimpleTestCase

from config.celery import app


class CeleryConfigTests(SimpleTestCase):
    def test_every_periodic_task_expires(self):
        """
        Davriy vazifa `expires` siz bo'lsa, ishchi to'xtab turgan kunlarda
        to'plangan tiklar tiklangach BIRDANIGA bajariladi (masalan 26 ta
        partitsiya aylantirish ketma-ket).
        """
        missing = [
            name for name, entry in app.conf.beat_schedule.items()
            if not (entry.get("options") or {}).get("expires")
        ]
        self.assertEqual(missing, [], "expires yo'q: " + ", ".join(missing))

    @unittest.skipUnless(sys.platform == "win32", "faqat Windows")
    def test_windows_uses_threads_pool(self):
        """`prefork` Windows'da vazifalarni JIMGINA bajarmaydi."""
        self.assertEqual(app.conf.worker_pool, "threads")
