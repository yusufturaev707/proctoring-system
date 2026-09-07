"""
Javob konverti va xato ishlovchisi.

Barcha javoblar `{success, data, error}` ga o'raladi va frontend axios
interceptor'i shunga tayanadi. Konvert shakli o'zgarsa, admin panelning
HAR BIR sahifasi bir vaqtda buziladi — shuning uchun u shartnoma
sifatida qat'iy tekshiriladi.
"""

import json

from django.db import IntegrityError
from django.http import Http404
from django.test import SimpleTestCase
from rest_framework import status
from rest_framework.exceptions import NotAuthenticated, ValidationError
from rest_framework.response import Response

from apps.common.exceptions import DomainError, api_exception_handler
from apps.common.renderers import ApiJSONRenderer


def render(data, status_code=200):
    response = Response(data, status=status_code)
    raw = ApiJSONRenderer().render(data, renderer_context={"response": response})
    return raw


class RendererTests(SimpleTestCase):
    def test_wraps_success(self):
        body = json.loads(render({"id": 7}))
        self.assertEqual(body, {"success": True, "data": {"id": 7}, "error": None})

    def test_wraps_error_status(self):
        body = json.loads(render({"detail": "yo'q"}, status_code=404))
        self.assertFalse(body["success"])
        self.assertIsNone(body["data"])
        self.assertEqual(body["error"], {"detail": "yo'q"})

    def test_does_not_double_wrap(self):
        """
        Exception handler allaqachon konvert yasagan bo'lsa qayta
        o'ralmaydi — aks holda `data.data.data` paydo bo'lardi.
        """
        payload = {"success": False, "data": None, "error": {"code": "x"}}
        self.assertEqual(json.loads(render(payload, status_code=400)), payload)

    def test_204_has_empty_body(self):
        """
        `204 No Content` da TANA BO'LMASLIGI shart.

        Konvert qo'shilsa `Content-Length` javob bilan mos kelmaydi va
        brauzer `ERR_CONTENT_LENGTH_MISMATCH` beradi. DRF
        `DestroyModelMixin` aynan 204 qaytaradi, ya'ni bu har bir
        o'chirish amalida sodir bo'lardi.
        """
        self.assertEqual(render(None, status_code=204), b"")

    def test_list_payload_is_wrapped(self):
        body = json.loads(render([1, 2, 3]))
        self.assertEqual(body["data"], [1, 2, 3])


class ExceptionHandlerTests(SimpleTestCase):
    def _handle(self, exc):
        response = api_exception_handler(exc, {})
        return response.status_code, response.data["error"]

    def test_domain_error_keeps_code(self):
        code, error = self._handle(DomainError("Xato", code="my_code"))
        self.assertEqual(code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(error["code"], "my_code")
        self.assertEqual(error["message"], "Xato")

    def test_http404_becomes_not_found(self):
        code, error = self._handle(Http404())
        self.assertEqual(code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(error["code"], "not_found")

    def test_validation_error_returns_field_details(self):
        """
        Maydon xatolari `details` da qoladi — `ResourceForm` ularni
        maydon ostida ko'rsatadi.
        """
        code, error = self._handle(ValidationError({"name": ["Majburiy maydon"]}))
        self.assertEqual(code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(error["details"], {"name": ["Majburiy maydon"]})

    def test_not_authenticated_is_401(self):
        code, _ = self._handle(NotAuthenticated())
        self.assertEqual(code, status.HTTP_401_UNAUTHORIZED)

    def test_unhandled_exception_is_masked(self):
        """
        Kutilmagan xato tafsilotlari clientga CHIQMAYDI.

        Stack trace log'da qoladi; javobda faqat umumiy xabar - aks
        holda ichki struktura (jadval nomlari, yo'llar) oshkor bo'ladi.
        """
        response = api_exception_handler(RuntimeError("parol=maxfiy"), {})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data["error"]["code"], "internal_error")
        self.assertNotIn("maxfiy", json.dumps(response.data))


class IntegrityErrorTranslationTests(SimpleTestCase):
    """
    DB cheklovi nomi -> odam o'qiydigan xabar.

    PostgreSQL matni ("duplicate key value violates unique constraint
    ...") operatorga hech narsa aytmaydi.
    """

    def _message(self, text):
        response = api_exception_handler(IntegrityError(text), {})
        return response.status_code, response.data["error"]["message"]

    def test_known_constraint_is_translated(self):
        code, message = self._message(
            'duplicate key value violates unique constraint "unique_computer_mac"'
        )
        self.assertEqual(code, status.HTTP_409_CONFLICT)
        self.assertIn("MAC", message)

    def test_foreign_key_message(self):
        _, message = self._message("violates foreign key constraint on table x")
        self.assertIn("bog'langan", message)

    def test_unknown_duplicate_falls_back(self):
        _, message = self._message('duplicate key value violates unique constraint "nomalum"')
        self.assertEqual(message, "Bunday yozuv allaqachon mavjud")

    def test_not_null_message(self):
        _, message = self._message('null value violates not-null constraint')
        self.assertEqual(message, "Majburiy maydon to'ldirilmagan")

    def test_every_mapped_constraint_has_a_message(self):
        """
        Xarita bo'sh yoki buzilgan qiymat saqlamasligini kafolatlaymiz:
        bo'sh xabar foydalanuvchiga bo'sh dialog ko'rsatardi.
        """
        from apps.common.exceptions import CONSTRAINT_MESSAGES

        for constraint, message in CONSTRAINT_MESSAGES.items():
            with self.subTest(constraint=constraint):
                self.assertTrue(message.strip(), constraint)
