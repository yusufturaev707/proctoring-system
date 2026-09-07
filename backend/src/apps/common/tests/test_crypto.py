"""
Kriptografik yordamchilar.

Bu yerdagi testlar "funksiya ishlaydimi" ni emas, **xavfsizlik
xususiyatlarini** tekshiradi: shifrlash nondeterministik ekanini, hash
kalitga bog'liq ekanini va kalit almashganda eski qiymatlar ochilmay
qolishini. Ularning har biri buzilsa kod baribir "ishlayveradi" —
shuning uchun ular testsiz sezilmay o'zgarib ketishi mumkin.
"""

from django.test import SimpleTestCase, override_settings

from apps.common.utils import crypto


class KeyCacheMixin:
    """
    Kalitlar `_KeyCache` da keshlanadi (chiqarish 200k iteratsiya).

    Kalitni `override_settings` bilan almashtirish keshni O'ZI
    tozalamaydi, shuning uchun har bir testdan oldin va keyin
    tozalanadi — aks holda testlar bir-birining kalitini meros oladi
    va tartibga bog'liq bo'lib qoladi.
    """

    def setUp(self):
        super().setUp()
        crypto._KeyCache.reset()
        self.addCleanup(crypto._KeyCache.reset)


class EncryptDecryptTests(KeyCacheMixin, SimpleTestCase):
    def test_roundtrip(self):
        token = crypto.encrypt("kamera-paroli-123")
        self.assertNotIn("kamera-paroli-123", token)
        self.assertEqual(crypto.decrypt(token), "kamera-paroli-123")

    def test_unicode_roundtrip(self):
        secret = "parol-o'zbekcha-ЯЁ-🔐"
        self.assertEqual(crypto.decrypt(crypto.encrypt(secret)), secret)

    def test_ciphertext_is_not_deterministic(self):
        """
        Har shifrlashda yangi nonce.

        Deterministik bo'lsa, bir xil parolli ikkita kamera bazada bir
        xil qiymat bilan yotadi va baza nusxasi qo'lga tushganda
        "qaysi kameralarda bir xil parol" ma'lum bo'ladi.
        """
        first = crypto.encrypt("bir xil parol")
        second = crypto.encrypt("bir xil parol")
        self.assertNotEqual(first, second)
        self.assertEqual(crypto.decrypt(first), crypto.decrypt(second))

    def test_empty_values_pass_through(self):
        self.assertIsNone(crypto.encrypt(""))
        self.assertIsNone(crypto.encrypt(None))
        self.assertIsNone(crypto.decrypt(""))
        self.assertIsNone(crypto.decrypt(None))

    def test_corrupted_token_returns_none_instead_of_raising(self):
        """
        Buzilgan qiymat ilovani YIQITMAYDI.

        `Camera.password` xossasi har ro'yxat so'rovida chaqiriladi;
        bitta buzilgan qator butun sahifani 500 ga aylantirmasligi kerak.
        """
        for bad in ("not-base64!!", "AAAA", crypto.encrypt("x")[:-4]):
            with self.subTest(value=bad):
                self.assertIsNone(crypto.decrypt(bad))

    def test_decrypt_with_different_key_fails_closed(self):
        """
        `FIELD_ENCRYPTION_KEY` o'zgarsa eski qiymatlar OCHILMAYDI.

        Bu kutilgan xulq va u `.env` hujjatida ham yozilgan: kalit
        almashtirilsa kamera parollarini qayta kiritish kerak.
        """
        token = crypto.encrypt("eski-parol")
        crypto._KeyCache.reset()
        with override_settings(FIELD_ENCRYPTION_KEY="butunlay-boshqa-kalit-32-bayt!!"):
            self.assertIsNone(crypto.decrypt(token))


class HashTokenTests(KeyCacheMixin, SimpleTestCase):
    def test_is_deterministic(self):
        self.assertEqual(crypto.hash_token("abc"), crypto.hash_token("abc"))

    def test_differs_per_input(self):
        self.assertNotEqual(crypto.hash_token("abc"), crypto.hash_token("abd"))

    def test_depends_on_key(self):
        """
        HMAC, oddiy SHA256 emas.

        Kalitsiz hash bo'lsa, baza nusxasi bilan oldindan hisoblangan
        jadval tuzib sessiya tokenlarini tiklash mumkin bo'lardi.
        """
        digest = crypto.hash_token("sessiya-tokeni")
        crypto._KeyCache.reset()
        with override_settings(TOKEN_HASH_KEY="boshqa-hash-kaliti"):
            self.assertNotEqual(crypto.hash_token("sessiya-tokeni"), digest)

    def test_hex_sha256_length(self):
        self.assertEqual(len(crypto.hash_token("x")), 64)


class TokenGenerationTests(SimpleTestCase):
    def test_tokens_are_unique(self):
        tokens = {crypto.generate_token(32) for _ in range(200)}
        self.assertEqual(len(tokens), 200)

    def test_url_safe(self):
        token = crypto.generate_token(32)
        self.assertTrue(all(ch.isalnum() or ch in "-_" for ch in token), token)


class PinflTests(SimpleTestCase):
    def test_normalize_keeps_only_digits(self):
        self.assertEqual(crypto.normalize_pinfl(" 123-456 789 01234 "), "12345678901234")

    def test_normalize_handles_none(self):
        self.assertEqual(crypto.normalize_pinfl(None), "")

    def test_mask_keeps_first_and_last_four(self):
        self.assertEqual(crypto.mask_pinfl("12345678901234"), "1234******1234")

    def test_mask_short_value_is_fully_hidden(self):
        """
        Qisqa qiymat TO'LIQ yashiriladi.

        Aks holda 8 xonali qiymatda birinchi va oxirgi 4 raqam butun
        qiymatni beradi — ya'ni niqob hech nimani yashirmaydi.
        """
        self.assertEqual(crypto.mask_pinfl("12345678"), "*" * 8)

    def test_opaque_key_is_stable_and_short(self):
        key = crypto.opaque_key("12345678901234")
        self.assertEqual(key, crypto.opaque_key("12345678901234"))
        self.assertEqual(len(key), 32)
        self.assertNotIn("12345678901234", key)


class ConstantTimeCompareTests(SimpleTestCase):
    def test_equal_and_not_equal(self):
        self.assertTrue(crypto.constant_time_compare("abc", "abc"))
        self.assertFalse(crypto.constant_time_compare("abc", "abd"))
