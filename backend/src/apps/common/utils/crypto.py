"""
Kriptografik yordamchilar.

Ikki xil primitiv, ikki xil maqsad:

* `hash_token` — HMAC-SHA256, DETERMINISTIK. Sessiya va qurilma tokenlari
                 DB/Redis'da ochiq saqlanmaydi, faqat hash'i yotadi.
* `encrypt`    — AES-256-GCM, TASODIFIY nonce. Qaytariladigan shifrlash;
                 hozircha faqat IP kamera RTSP parollari uchun.

Talabgor JSHSHIR'i va F.I.Sh. si ATAYLAB ochiq saqlanadi: imtihon
markazlari o'z nazoratimizdagi ishonchli hududda, qidiruv/saralash esa
shifrlangan maydonda ishlamaydi. Bu ongli qaror — DB backup'lari
shunga mos himoyalanishi kerak.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings

_NONCE_SIZE = 12  # GCM uchun tavsiya etilgan
_VERSION = b"\x01"  # kalit rotatsiyasi uchun prefiks


def _derive_key(raw: str, salt: bytes) -> bytes:
    """Ixtiyoriy uzunlikdagi env qiymatidan 32-baytli kalit chiqaradi."""
    return hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt, 200_000, dklen=32)


class _KeyCache:
    """Kalit chiqarish qimmat (200k iteratsiya) — bir marta hisoblab keshlaymiz."""

    _aes_key: bytes | None = None
    _hmac_key: bytes | None = None

    @classmethod
    def aes(cls) -> bytes:
        if cls._aes_key is None:
            cls._aes_key = _derive_key(settings.FIELD_ENCRYPTION_KEY, b"proctoring.aes.v1")
        return cls._aes_key

    @classmethod
    def hmac(cls) -> bytes:
        if cls._hmac_key is None:
            cls._hmac_key = _derive_key(settings.TOKEN_HASH_KEY, b"proctoring.token.v1")
        return cls._hmac_key

    @classmethod
    def reset(cls) -> None:
        cls._aes_key = None
        cls._hmac_key = None


# --------------------------------------------------------------------------
# JSHSHIR
# --------------------------------------------------------------------------
def normalize_pinfl(pinfl: str) -> str:
    """Faqat raqamlarni qoldiradi — DB'ga va Redis kalitlariga shu shakl tushadi."""
    return "".join(ch for ch in str(pinfl or "") if ch.isdigit())


def opaque_key(value: str) -> str:
    """
    Kesh/throttle kalitlari uchun qaytarilmaydigan qisqa identifikator.

    JSHSHIR DB'da ochiq yotadi, lekin uni Redis kalitining O'ZIGA yozish
    keraksiz: kalitlar `KEYS`/`SCAN` bilan ro'yxatlanadi va monitoring
    vositalarida ko'rinadi.
    """
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:32]


def mask_pinfl(pinfl: str) -> str:
    """UI va log uchun: 12345678901234 -> 1234******1234"""
    digits = "".join(ch for ch in str(pinfl) if ch.isdigit())
    if len(digits) <= 8:
        return "*" * len(digits)
    return f"{digits[:4]}{'*' * (len(digits) - 8)}{digits[-4:]}"


# --------------------------------------------------------------------------
# Qaytariladigan shifrlash (IP kamera parollari)
# --------------------------------------------------------------------------
def encrypt(plaintext: str | None) -> str | None:
    if plaintext in (None, ""):
        return None
    nonce = os.urandom(_NONCE_SIZE)
    ciphertext = AESGCM(_KeyCache.aes()).encrypt(nonce, str(plaintext).encode("utf-8"), None)
    return base64.b64encode(_VERSION + nonce + ciphertext).decode("ascii")


def decrypt(token: str | None) -> str | None:
    if token in (None, ""):
        return None
    try:
        raw = base64.b64decode(token)
        if raw[:1] != _VERSION:
            return None
        nonce = raw[1 : 1 + _NONCE_SIZE]
        ciphertext = raw[1 + _NONCE_SIZE :]
        return AESGCM(_KeyCache.aes()).decrypt(nonce, ciphertext, None).decode("utf-8")
    except Exception:
        # Buzilgan yoki boshqa kalit bilan shifrlangan — ilovani yiqitmaymiz.
        return None


# --------------------------------------------------------------------------
# Token generatsiyasi
# --------------------------------------------------------------------------
def generate_token(nbytes: int = 32) -> str:
    """Sessiya/qurilma tokeni uchun kriptografik tasodifiy qiymat."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """
    Token DB/Redis'da OCHIQ saqlanmaydi — faqat hash'i.

    Redis dump'i sizib chiqsa ham faol sessiyalarni o'g'irlab bo'lmaydi.
    HMAC (oddiy sha256 emas) — kalitsiz hash jadvali tuzishning oldini oladi.
    """
    return hmac.new(_KeyCache.hmac(), token.encode("utf-8"), hashlib.sha256).hexdigest()


def constant_time_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(str(left), str(right))


def sign_payload(secret: str, payload: str) -> str:
    """Client so'rovlarini imzolash uchun HMAC-SHA256."""
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
