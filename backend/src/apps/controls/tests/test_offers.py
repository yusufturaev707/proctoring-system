"""
Oferta API'si (panel): versiyalash, testga biriktirish, tozalash.

Asosiy kafolat вЂ” ROZILIK BERILGAN MATN O'ZGARMAYDI: tahrir yangi
`OfferRevision` yaratadi, eskisi joyida qoladi.
"""

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.controls import offers
from apps.controls.models import Offer, OfferRevision
from apps.proctoring.models import AuditLog
from apps.proctoring.tests import factories

TEXT = "<p>Men shaxsga doir ma'lumotlarimni qayta ishlashga roziman.</p>"


class OfferApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient()
        self.staff = factories.make_user(permissions=["controls.manage", "controls.view"])
        self.client.force_authenticate(self.staff)
        self.list_url = reverse("offer-list")

    def _create(self, **extra):
        response = self.client.post(
            self.list_url, {"title": "Oferta", "content": TEXT, **extra}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()["data"]

    def test_create_makes_first_revision(self):
        data = self._create()
        self.assertEqual(data["version"], 1)
        revision = OfferRevision.objects.get()
        self.assertEqual(revision.version, 1)
        self.assertEqual(revision.content, TEXT)
        self.assertEqual(revision.created_by, self.staff)
        self.assertEqual(len(revision.content_hash), 64)
        self.assertTrue(AuditLog.objects.filter(object_type="Offer", action="create").exists())

    def test_content_edit_creates_new_revision_and_keeps_old(self):
        data = self._create()
        url = reverse("offer-detail", args=[data["id"]])
        new_text = TEXT.replace("roziman", "to'liq roziman")
        response = self.client.patch(url, {"content": new_text}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["data"]["version"], 2)
        self.assertEqual(
            list(OfferRevision.objects.order_by("version").values_list("content", flat=True)),
            [TEXT, new_text],
        )

    def test_status_change_does_not_create_revision(self):
        data = self._create()
        url = reverse("offer-detail", args=[data["id"]])
        self.client.patch(url, {"is_active": True}, format="json")
        self.assertEqual(OfferRevision.objects.count(), 1)
        self.assertEqual(Offer.objects.get().version, 1)

    def test_many_offers_can_be_active(self):
        """Har testning o'z ofertasi вЂ” "bitta amaldagi" cheklovi yo'q."""
        first = self._create()
        second = self._create()
        self.assertEqual(Offer.objects.filter(is_active=True).count(), 2)
        self.assertTrue(first["is_active"] and second["is_active"])

    def test_assign_exams_and_read_back(self):
        exam_a, exam_b = factories.make_exam(name="Matematika"), factories.make_exam(name="Fizika")
        data = self._create(exams=[exam_a.pk, exam_b.pk])
        self.assertEqual(sorted(data["exams"]), sorted([exam_a.pk, exam_b.pk]))
        self.assertEqual([row["name"] for row in data["exam_list"]], ["Fizika", "Matematika"])
        exam_a.refresh_from_db()
        self.assertEqual(offers.current_revision(exam_a).offer_id, data["id"])

        # Ro'yxat to'liq almashtiriladi: chiqarilgan test ajraladi.
        url = reverse("offer-detail", args=[data["id"]])
        response = self.client.patch(url, {"exams": [exam_b.pk]}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["data"]["exams"], [exam_b.pk])
        exam_a.refresh_from_db()
        self.assertIsNone(exam_a.offer_id)
        self.assertIsNone(offers.current_revision(exam_a))

        audit = AuditLog.objects.filter(object_type="Offer", action="update").latest("id")
        self.assertEqual(audit.meta["exams"]["removed"], [exam_a.pk])

    def test_exam_moves_from_other_offer(self):
        exam = factories.make_exam()
        first = self._create(exams=[exam.pk])
        second = self._create(exams=[exam.pk])
        exam.refresh_from_db()
        self.assertEqual(exam.offer_id, second["id"])
        listed = self.client.get(reverse("offer-detail", args=[first["id"]])).json()["data"]
        self.assertEqual(listed["exams"], [])
        audit = AuditLog.objects.filter(object_type="Offer", action="create").latest("id")
        self.assertEqual(audit.meta["exams"]["moved"], {str(exam.pk): first["id"]})

    def test_patch_without_exams_keeps_assignment(self):
        exam = factories.make_exam()
        data = self._create(exams=[exam.pk])
        self.client.patch(reverse("offer-detail", args=[data["id"]]), {"title": "Yangi"}, format="json")
        exam.refresh_from_db()
        self.assertEqual(exam.offer_id, data["id"])

    def test_filter_by_exam(self):
        exam = factories.make_exam()
        data = self._create(exams=[exam.pk])
        self._create()
        response = self.client.get(self.list_url, {"exams": exam.pk})
        self.assertEqual([row["id"] for row in response.json()["data"]["results"]], [data["id"]])

    def test_deleted_exam_not_listed_and_not_assignable(self):
        exam = factories.make_exam()
        data = self._create(exams=[exam.pk])
        exam.delete()
        listed = self.client.get(reverse("offer-detail", args=[data["id"]])).json()["data"]
        self.assertEqual(listed["exams"], [])
        response = self.client.patch(
            reverse("offer-detail", args=[data["id"]]), {"exams": [exam.pk]}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_content_is_sanitized(self):
        data = self._create(content=TEXT + '<script>alert(1)</script><p onclick="x()">Qo\'shimcha band</p>')
        self.assertNotIn("script", data["content"])
        self.assertNotIn("onclick", data["content"])
        self.assertIn("Qo'shimcha band", data["content"])

    def test_empty_content_rejected(self):
        response = self.client.post(
            self.list_url, {"title": "Oferta", "content": "<p>  </p><script>x</script>"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Offer.objects.exists())

    def test_delete_is_soft(self):
        data = self._create()
        response = self.client.delete(reverse("offer-detail", args=[data["id"]]))
        self.assertEqual(response.status_code, 204)
        offer = Offer.objects.get(pk=data["id"])
        self.assertIsNotNone(offer.deleted_at)
        # Versiya joyida вЂ” unga berilgan roziliklar yetim qolmaydi.
        self.assertTrue(OfferRevision.objects.filter(offer=offer).exists())

    def test_delete_refused_while_assigned(self):
        """O'chirish testdan rozilik qadamini jimgina olib tashlamasin."""
        exam = factories.make_exam(name="Kimyo")
        data = self._create(exams=[exam.pk])
        response = self.client.delete(reverse("offer-detail", args=[data["id"]]))
        self.assertEqual(response.status_code, 409)
        error = response.json()["error"]
        self.assertEqual(error["code"], "offer_in_use")
        self.assertIn("Kimyo", error["message"])
        self.assertIsNone(Offer.objects.get(pk=data["id"]).deleted_at)

    def test_revisions_endpoint_lists_history(self):
        data = self._create()
        url = reverse("offer-detail", args=[data["id"]])
        self.client.patch(url, {"title": "Oferta (yangi)"}, format="json")
        response = self.client.get(reverse("offer-revisions", args=[data["id"]]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["version"] for row in response.json()["data"]], [2, 1])

    def test_region_staff_cannot_write(self):
        region_staff = factories.make_user(
            permissions=["controls.manage", "controls.view"], region=factories.make_region()
        )
        self.client.force_authenticate(region_staff)
        response = self.client.post(self.list_url, {"title": "Oferta", "content": TEXT}, format="json")
        self.assertEqual(response.status_code, 403)
