"""
Oferta JSHSHIR javobida: test (`Exam.offer`) -> `offer` -> client dialogi.

Kafolatlar:
  * matn AYNAN shu testning ofertasi; ofertasiz yoki nofaol ofertali
    testda `offer` yo'q;
  * HAR qidiruvda qaytadan beriladi (rozilik saqlanmaydi va qayta
    ishlatilmaydi) — doim eng oxirgi tahrir;
  * server rozilikni talab qilmaydi va yozmaydi: qadam clientda.
"""

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.common.tests.utils import RedisStateMixin
from apps.controls import offers
from apps.controls.models import AllowedPublicIp
from apps.proctoring.models import ExamSession
from apps.proctoring.tests import factories
from apps.proctoring.tests.test_client_api import bearer

TEXT = "<h2>Oferta</h2><p>Shaxsga doir ma'lumotlarimni qayta ishlashga roziman.</p>"
PINFL = "30000000000001"


class OfferLookupTests(RedisStateMixin, TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient()
        self.exam = factories.make_exam()
        factories.make_schedule(exam=self.exam)
        self.device = factories.make_device()
        self.computer = self.device.computer
        self.operator = factories.make_user(permissions=["client.operate"])
        AllowedPublicIp.objects.create(ip_address="8.8.8.8", zone=self.computer.zone)
        self.offer = offers.save_offer(title="Oferta", content=TEXT, exams=[self.exam])
        self.exam.refresh_from_db()

    # --- yordamchilar ---------------------------------------------------
    def _post(self, url_name, payload):
        return self.client.post(
            reverse(url_name),
            payload,
            format="json",
            HTTP_AUTHORIZATION=bearer(self.operator),
            HTTP_X_DEVICE_ID=self.device.device_id,
            REMOTE_ADDR="8.8.8.8",
        )

    def _lookup(self):
        response = self._post(
            "client-candidate-lookup",
            {"pinfl": PINFL, "exam_id": self.exam.pk, **factories.machine_of(self.device)},
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["data"]

    def _verify(self, challenge):
        return self._post(
            "client-face-verify",
            {"challenge": challenge, "embedding": [0.1] * 512, "score": 90, "faces_detected": 1},
        )

    # --- testlar ------------------------------------------------------
    def test_lookup_carries_offer_text(self):
        offer = self._lookup()["offer"]
        self.assertEqual(offer["offer_id"], self.offer.pk)
        self.assertEqual(offer["title"], "Oferta")
        self.assertEqual(offer["content_html"], TEXT)
        self.assertEqual(offer["version"], 1)
        # Rozilik izi yo'q — client hech narsani qaytarib yubormaydi.
        self.assertNotIn("accepted_at", offer)
        self.assertNotIn("content_hash", offer)

    def test_exam_without_offer_has_no_offer(self):
        offers.assign_exams(self.offer, [])
        self.assertIsNone(self._lookup()["offer"])

    def test_inactive_offer_not_shown(self):
        offers.save_offer(offer=self.offer, title="Oferta", content=TEXT, is_active=False)
        self.assertIsNone(self._lookup()["offer"])

    def test_each_exam_gets_its_own_offer(self):
        """Boshqa testning ofertasi bu testda ko'rsatilmaydi — va aksincha."""
        other_exam = factories.make_exam()
        other_text = "<p>Boshqa test shartlari: ma'lumotlarim qayta ishlanishiga roziman.</p>"
        other = offers.save_offer(title="Boshqa oferta", content=other_text, exams=[other_exam])
        self.assertEqual(self._lookup()["offer"]["title"], "Oferta")

        offers.assign_exams(other, [other_exam, self.exam])
        offer = self._lookup()["offer"]
        self.assertEqual(offer["title"], "Boshqa oferta")
        self.assertEqual(offer["offer_id"], other.pk)

    def test_offer_returned_on_every_lookup(self):
        """Yuz tekshiruvidan o'tib sessiya ochilgandan keyin ham — rozilik eslab qolinmaydi."""
        first = self._lookup()
        self.assertEqual(self._verify(first["challenge"]).status_code, 201)
        self.assertEqual(self._lookup()["offer"]["content_html"], TEXT)

    def test_latest_edit_is_shown(self):
        self._lookup()
        edited = TEXT + "<p>Yangi band qo'shildi.</p>"
        offers.save_offer(offer=self.offer, title="Oferta", content=edited)
        offer = self._lookup()["offer"]
        self.assertEqual(offer["version"], 2)
        self.assertEqual(offer["content_html"], edited)

    def test_face_check_not_gated_and_nothing_recorded(self):
        """Server rozilikni talab qilmaydi: qadam clientda, sessiyada iz yo'q."""
        data = self._lookup()
        self.assertEqual(self._verify(data["challenge"]).status_code, 201)
        self.assertNotIn("offer", ExamSession.objects.get().meta)
