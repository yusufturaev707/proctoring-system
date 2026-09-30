"""
Log'dagi maxfiy qiymatlarni yashirish.

QOIDA: log'ga token, parol, JSHSHIR, embedding va `test_link` tushmasligi
kerak. Kod shunga amal qiladi, lekin bu filtr - IKKINCHI QATLAM:
traceback'dagi `repr(kwargs)`, serverning xato matni yoki uchinchi
tomon kutubxonasining xabari (requests/urllib3 URL'ni to'liq yozadi)
qoidani bilmaydi. Log fayli esa imtihon mashinasida yotadi va uni
texnik xodim ham, ba'zan talabgor ham ko'ra oladi.

FORMATLANGAN MATN ustida ishlaydi (`RedactingFormatter`), `record.msg`
ustida emas: `args` dagi qiymat va `exc_info` traceback'i faqat
formatlashdan keyin bitta satrga birlashadi.

Naqshlar ATAYLAB tor: juda keng naqsh (masalan har qanday uzun son)
diagnostikani yo'q qilardi - vaqt belgisi, port, PID ham yashirinib
qolardi.
"""

from __future__ import annotations

import logging
import re

_MASK = "<yashirildi>"

#: JWT: uch qism, birinchi ikkitasi base64url JSON (`eyJ` bilan boshlanadi).
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}")

#: `Authorization: Bearer <...>` va shunga o'xshash sarlavhalar.
_BEARER = re.compile(r"(?i)\b(Bearer|Token)\s+[A-Za-z0-9._~+/=-]{8,}")

#: `kalit=qiymat`, `"kalit": "qiymat"`, `kalit: qiymat` - kalit nomi
#: bo'yicha. Ro'yxat mijozdagi haqiqiy maydon nomlaridan olingan
#: (`repositories.py`, `api_client.py`, `ProctoringSession`).
_SECRET_KEYS = (
    "password", "passwd", "parol", "new_password", "old_password",
    "token", "access", "refresh", "access_token", "refresh_token",
    "proctoring_session_token", "session_token", "x-proctoring-session",
    "authorization", "secret", "api_key", "apikey", "x-api-key",
    "challenge", "test_link", "external_test_link",
    "pinfl", "imie", "jshshir",
    "embedding", "reference_embedding", "image_base64", "photo_base64",
)
_KEY_VALUE = re.compile(
    r"(?i)(?P<key>[\"']?\b(?:" + "|".join(re.escape(k) for k in _SECRET_KEYS) + r")\b[\"']?"
    r"\s*[:=]\s*)"
    r"(?P<value>\"[^\"]*\"|'[^']*'|\[[^\]]*\]|[^\s,;&}\)]+)"
)

#: `data:image/jpeg;base64,...` - pasport rasmi, jonli kadr.
_DATA_URI = re.compile(r"data:[a-z]+/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=]{16,}", re.IGNORECASE)

#: 16+ ketma-ket kasr son - embedding vektori (512 float).
_VECTOR = re.compile(r"(?:-?\d+\.\d+(?:[eE][-+]?\d+)?\s*,\s*){15,}-?\d+\.\d+(?:[eE][-+]?\d+)?")

#: JSHSHIR (PINFL) - aynan 14 raqam, atrofida boshqa raqam yo'q.
#: Niqob ekrandagi bilan bir xil shaklda (`3270******0024`): muammoni
#: tahlil qilganda qaysi talabgor ekanini operatorning ekranidagi
#: yozuv bilan solishtirish mumkin, to'liq raqam esa tiklanmaydi.
_PINFL = re.compile(r"(?<![\d.])(\d{4})\d{6}(\d{4})(?![\d.])")


def redact(text: str) -> str:
    """Matndagi maxfiy qiymatlarni niqoblaydi. Xato ko'tarmaydi."""
    if not text:
        return text
    try:
        text = _DATA_URI.sub("data:<rasm yashirildi>", text)
        text = _JWT.sub("<jwt yashirildi>", text)
        text = _BEARER.sub(lambda m: m.group(1) + " " + _MASK, text)
        text = _KEY_VALUE.sub(lambda m: m.group("key") + _MASK, text)
        text = _VECTOR.sub("<vektor yashirildi>", text)
        text = _PINFL.sub(r"\1******\2", text)
    except Exception:  # noqa: BLE001 - log yozuvi hech qachon yiqilmasligi kerak
        return text
    return text


class RedactingFormatter(logging.Formatter):
    """Oddiy `Formatter` + `redact()` - traceback ham qamrab olinadi."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))
