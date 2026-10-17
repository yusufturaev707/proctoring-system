"""
`Exam.resource_domains` - savol rasmlari/shriftlar keladigan domenlar.

Qoida bitta joyda (`apps/exams/domains.py`); panel serializer'i va
Django admin (`Exam.clean`) uni chaqiradi, client'ga esa
`get_resource_domains` orqali faqat yaroqli yozuvlar boradi.

Eng qimmat xatolar:

* keng yozuv (`uz`, `localhost`) - butun zona yoki mashinadagi lokal
  xizmatlar rasm so'rovi uchun ochilib qolardi;
* host bo'lmagan qiymat (`https://cdn.uz/img`, `cdn.uz:8443`) -
  client hostni solishtiradi va yozuv jimgina hech narsaga mos kelmasdi;
* bazadagi buzilgan yozuv - `exam/access/` ni yiqitmasligi kerak.
"""

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

from apps.exams.api.v1.serializers import ExamSerializer
from apps.exams.domains import (
    MAX_RESOURCE_DOMAINS,
    clean_resource_domain,
    clean_resource_domains,
    safe_resource_domains,
)
from apps.exams.models import Exam


class CleanResourceDomainTests(SimpleTestCase):
    def test_canonical_host(self):
        cases = {
            "cdn.test.uz": "cdn.test.uz",
            "  CDN.Test.UZ  ": "cdn.test.uz",
            "https://cdn.test.uz/img/q1.png": "cdn.test.uz",
            "http://cdn.test.uz:8443/x": "cdn.test.uz",
            "cdn.test.uz/img": "cdn.test.uz",
            "cdn.test.uz:8443": "cdn.test.uz",
            "*.cdn.test.uz": "cdn.test.uz",
            "cdn.test.uz.": "cdn.test.uz",
            "xn--80ak6aa92e.uz": "xn--80ak6aa92e.uz",
            "10.0.0.5": "10.0.0.5",
            "10.0.0.5:8080": "10.0.0.5",
            "http://10.0.0.5/img": "10.0.0.5",
            "fd00::1": "fd00::1",
            "[fd00::1]:443": "fd00::1",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(clean_resource_domain(raw), expected)

    def test_rejected(self):
        for raw in (
            "", "   ", "uz", "*.uz", "localhost", "*", "*.",
            "127.0.0.1", "::1", "0.0.0.0", "169.254.1.1", "224.0.0.1",
            "http://localhost/x", "https://", "cdn..uz", "-cdn.uz", "cdn-.uz",
            "cdn_files.uz", "тест.uz", "10.0.0", "a" * 64 + ".uz",
        ):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    clean_resource_domain(raw)

    def test_list_is_deduplicated_in_order(self):
        self.assertEqual(
            clean_resource_domains(["b.uz", "https://A.uz/x", "b.uz", "*.a.uz"]),
            ["b.uz", "a.uz"],
        )

    def test_list_error_names_the_entry(self):
        with self.assertRaisesMessage(ValueError, "«localhost»"):
            clean_resource_domains(["cdn.uz", "localhost"])

    def test_list_limit(self):
        many = ["cdn{}.uz".format(index) for index in range(MAX_RESOURCE_DOMAINS + 1)]
        with self.assertRaises(ValueError):
            clean_resource_domains(many)
        self.assertEqual(len(clean_resource_domains(many[:-1])), MAX_RESOURCE_DOMAINS)

    def test_non_list_rejected(self):
        with self.assertRaises(ValueError):
            clean_resource_domains({"cdn.uz": True})
        self.assertEqual(clean_resource_domains(None), [])

    def test_safe_variant_drops_invalid_entries(self):
        self.assertEqual(
            safe_resource_domains(["cdn.uz", "uz", 5, None, "CDN.uz", "img.uz"]),
            ["cdn.uz", "img.uz"],
        )
        self.assertEqual(safe_resource_domains({"x": 1}), [])
        self.assertEqual(safe_resource_domains(None), [])


class ExamResourceDomainsApiTests(TestCase):
    def _serializer(self, value, instance=None, partial=False):
        data = {"resource_domains": value}
        if instance is None:
            data.update(name="Tarix", site_url="https://ntest.uzbmb.uz/login")
        return ExamSerializer(instance=instance, data=data, partial=partial)

    def test_create_stores_canonical_list(self):
        serializer = self._serializer(["https://CDN.uzbmb.uz/img/1.png", "*.files.uz"])
        serializer.is_valid(raise_exception=True)
        exam = serializer.save()
        exam.refresh_from_db()
        self.assertEqual(exam.resource_domains, ["cdn.uzbmb.uz", "files.uz"])
        self.assertEqual(
            ExamSerializer(exam).data["resource_domains"], ["cdn.uzbmb.uz", "files.uz"]
        )

    def test_invalid_entry_is_a_field_error(self):
        serializer = self._serializer(["cdn.uz", "localhost"])
        self.assertFalse(serializer.is_valid())
        self.assertIn("resource_domains", serializer.errors)

    def test_default_is_empty_and_patch_keeps_value(self):
        serializer = ExamSerializer(
            data={"name": "Biologiya", "site_url": "https://ntest.uzbmb.uz/login"}
        )
        serializer.is_valid(raise_exception=True)
        exam = serializer.save()
        self.assertEqual(exam.resource_domains, [])

        exam.resource_domains = ["cdn.uz"]
        exam.save(update_fields=["resource_domains"])
        patch = ExamSerializer(instance=exam, data={"duration_minutes": 90}, partial=True)
        patch.is_valid(raise_exception=True)
        patch.save()
        exam.refresh_from_db()
        self.assertEqual(exam.resource_domains, ["cdn.uz"])

    def test_model_clean_uses_the_same_rule(self):
        """Django admin formasi `full_clean` orqali shu qoidadan o'tadi."""
        exam = Exam(name="Adabiyot", resource_domains=["https://Img.uz/a", "img.uz"])
        exam.clean()
        self.assertEqual(exam.resource_domains, ["img.uz"])

        exam.resource_domains = ["uz"]
        with self.assertRaises(ValidationError) as ctx:
            exam.clean()
        self.assertIn("resource_domains", ctx.exception.message_dict)

    def test_client_gets_only_valid_entries(self):
        exam = Exam.objects.create(
            name="Huquq", resource_domains=["cdn.uz", "localhost", "*.uz"]
        )
        self.assertEqual(exam.get_resource_domains(), ["cdn.uz"])
