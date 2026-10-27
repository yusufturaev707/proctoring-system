"""
Ofertaga rozilik: JSHSHIR javobi -> `offer/accept/` -> FaceID.

Kafolatlar:
  * matn JSHSHIR javobida keladi — AYNAN shu testning ofertasi (`Exam.offer`);
    ofertasiz yoki nofaol ofertali testda qadam yo'q;
  * rozilikgacha yuz tekshiruvi (`face/verify/`, `face/attempt/`) YOPIQ va
    rad javobi challenge'ni SARFLAMAYDI;
  * rozilik aynan berilgan versiya va matn iziga yoziladi;
  * sessiya ochilganda rozilik unga bog'lanadi va `meta.offer` da qoladi;
  * bugungi rozilik qayta qidiruvda takrorlanmaydi, yangi versiyada esa so'raladi.
"""

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.common.html_sanitizer import content_hash
from apps.common.tests.utils import RedisStateMixin
from apps.controls import offers
from apps.controls.models import AllowedPublicIp
from apps.proctoring.models import ExamSession, FaceVerificationLog, OfferConsent
from apps.proctoring.tests import factories
from apps.proctoring.tests.test_client_api import bearer

TEXT = "<h2>Oferta</h2><p>Shaxsga doir ma'lumotlarimni qayta ishlashga roziman.</p>"
PINFL = "30000000000001"


class OfferConsentFlowTests(RedisStateMixin, TestCase):
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

    def _accept(self, data, **override):
        offer = data["offer"]
        return self._post(
            "client-offer-accept",
            {
                "challenge": data["challenge"],
                "revision_id": offer["revision_id"],
                "content_hash": offer["content_hash"],
                **override,
            },
        )

    def _verify(self, challenge):
        return self._post(
            "client-face-verify",
            {"challenge": challenge, "embedding": [0.1] * 512, "score": 90, "faces_detected": 1},
        )

    # --- testlar ------------------------------------------------------
    def test_lookup_carries_offer_text(self):
        offer = self._lookup()["offer"]
        self.assertEqual(offer["title"], "Oferta")
        self.assertEqual(offer["content_html"], TEXT)
        self.assertEqual(offer["version"], 1)
        self.assertEqual(offer["content_hash"], content_hash(TEXT))
        self.assertIsNone(offer["accepted_at"])

    def test_exam_without_offer_skips_step(self):
        offers.assign_exams(self.offer, [])
        data = self._lookup()
        self.assertIsNone(data["offer"])
        self.assertEqual(self._verify(data["challenge"]).status_code, 201)

    def test_inactive_offer_skips_step(self):
        offers.save_offer(offer=self.offer, title="Oferta", content=TEXT, is_active=False)
        data = self._lookup()
        self.assertIsNone(data["offer"])
        self.assertEqual(self._verify(data["challenge"]).status_code, 201)

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

    def test_consent_for_one_exam_not_reused_in_another(self):
        """Bir xil matn ikki testda — rozilik test bo'yicha alohida."""
        self._accept(self._lookup())
        other_exam = factories.make_exam()
        factories.make_schedule(exam=other_exam)
        offers.assign_exams(self.offer, [self.exam, other_exam])
        self.exam = other_exam
        self.assertIsNone(self._lookup()["offer"]["accepted_at"])

    def test_face_verify_blocked_until_consent_without_spending_challenge(self):
        data = self._lookup()
        response = self._verify(data["challenge"])
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "offer_not_accepted")
        self.assertFalse(ExamSession.objects.exists())

        self.assertEqual(self._accept(data).status_code, 201)
        # Rad javobi challenge'ni yo'q qilmagan — o'sha challenge bilan ochiladi.
        self.assertEqual(self._verify(data["challenge"]).status_code, 201)

    def test_face_attempt_blocked_until_consent(self):
        data = self._lookup()
        response = self._post(
            "client-face-attempt",
            {"challenge": data["challenge"], "score": 10, "faces_detected": 1},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "offer_not_accepted")
        self.assertFalse(FaceVerificationLog.objects.exists())

    def test_consent_recorded_and_linked_to_session(self):
        data = self._lookup()
        response = self._accept(data)
        self.assertEqual(response.status_code, 201, response.content)

        consent = OfferConsent.objects.get()
        self.assertEqual(consent.pinfl, PINFL)
        self.assertEqual(consent.exam, self.exam)
        self.assertEqual(consent.revision.version, 1)
        self.assertEqual(consent.content_hash, content_hash(TEXT))
        self.assertEqual(consent.device, self.device)
        self.assertEqual(consent.computer, self.computer)
        self.assertEqual(consent.operator, self.operator)
        self.assertIsNone(consent.session)

        self.assertEqual(self._verify(data["challenge"]).status_code, 201)
        session = ExamSession.objects.get()
        consent.refresh_from_db()
        self.assertEqual(consent.session, session)
        self.assertEqual(session.meta["offer"]["consent_id"], consent.pk)
        self.assertEqual(session.meta["offer"]["revision_id"], consent.revision_id)

    def test_repeated_accept_is_idempotent(self):
        data = self._lookup()
        first = self._accept(data).json()["data"]
        second = self._accept(data).json()["data"]
        self.assertEqual(first["consent_id"], second["consent_id"])
        self.assertEqual(OfferConsent.objects.count(), 1)

    def test_wrong_hash_rejected(self):
        data = self._lookup()
        response = self._accept(data, content_hash="0" * 64)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "offer_outdated")
        self.assertFalse(OfferConsent.objects.exists())

    def test_offer_replaced_between_lookup_and_accept(self):
        data = self._lookup()
        offers.save_offer(offer=self.offer, title="Oferta", content=TEXT + "<p>Yangi band</p>")
        # Client eski versiyani tasdiqlayapti — u JSHSHIR javobidagi matn,
        # rozilik shunga yoziladi (talabgor aynan shuni ko'rgan).
        self.assertEqual(self._accept(data).status_code, 201)
        self.assertEqual(OfferConsent.objects.get().revision.version, 1)
        # Keyingi qidiruv — yangi versiya, rozilik qayta so'raladi.
        fresh = self._lookup()["offer"]
        self.assertEqual(fresh["version"], 2)
        self.assertIsNone(fresh["accepted_at"])

    def test_todays_consent_reused_on_next_lookup(self):
        first = self._lookup()
        self._accept(first)
        second = self._lookup()
        self.assertIsNotNone(second["offer"]["accepted_at"])
        # Rozilik qayta so'ralmaydi — yuz tekshiruvi darhol ochiq.
        self.assertEqual(self._verify(second["challenge"]).status_code, 201)
        self.assertEqual(OfferConsent.objects.count(), 1)

    def test_challenge_bound_to_device(self):
        data = self._lookup()
        other = factories.make_device(computer=factories.make_computer(zone=self.computer.zone))
        response = self.client.post(
            reverse("client-offer-accept"),
            {
                "challenge": data["challenge"],
                "revision_id": data["offer"]["revision_id"],
                "content_hash": data["offer"]["content_hash"],
            },
            format="json",
            HTTP_AUTHORIZATION=bearer(self.operator),
            HTTP_X_DEVICE_ID=other.device_id,
            REMOTE_ADDR="8.8.8.8",
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(OfferConsent.objects.exists())
