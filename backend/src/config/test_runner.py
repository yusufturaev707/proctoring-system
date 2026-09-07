"""
Test runner — `python manage.py test` ni argumentsiz ishlatish uchun.

Muammo joylashuvda: `manage.py` `backend/` da, kod esa `backend/src/`
da (`manage.py` `src` ni `sys.path` ga o'zi qo'shadi). Standart
`DiscoverRunner` label berilmaganda joriy katalogdan (`backend/`)
qidiradi, `src/` esa oddiy paket emas — natijada discovery hech narsa
topmaydi va `NO TESTS RAN` chiqadi.

Bu jimgina yuz beradigan xato: chiqishda "0 test" yozilsa-yu, hech
qanday ogohlantirish bo'lmasa, uni "testlar o'tdi" deb o'qish oson.
Shuning uchun standart label kodda belgilanadi.
"""

from django.test.runner import DiscoverRunner


class ProctoringTestRunner(DiscoverRunner):
    """Label berilmasa — butun `apps` paketi."""

    def build_suite(self, test_labels=None, **kwargs):
        return super().build_suite(test_labels or ["apps"], **kwargs)
