"""
Imtihon sirlari: platforma sarlavhasi.

Modelga `Camera` bilan bir xil naqsh qo'llanadi (`devices/services.py`):
shifrlash/deshifrlash MODELDA emas, service'da. Sabab - model qatlami
kalitni bilmasligi kerak: `FIELD_ENCRYPTION_KEY` sozlamalarda va uni
model importiga bog'lash migratsiyalarni ham kalitga bog'lab qo'yardi
(kalitsiz `makemigrations` ishlamasdi).
"""

from __future__ import annotations

from apps.common.utils.crypto import decrypt, encrypt
from apps.exams.models import Exam

#: Niqoblangan ko'rinishda qiymatning boshi va oxiridan nechta belgi
#: qoladi. Administrator "to'g'ri token turibdimi?" degan savolga javob
#: topishi kerak, lekin niqob tokenni tiklashga yaramasligi ham shart.
_MASK_HEAD = 4
_MASK_TAIL = 4


def set_site_header(exam: Exam, raw_header: str) -> None:
    """
    Sarlavhani shifrlab yozadi (obyektni SAQLAMAYDI).

    Bo'sh qiymat - sarlavhani O'CHIRISH: platforma tokensiz ishlay
    boshlaganda uni bazada qoldirish kerak emas.
    """
    exam.site_header_encrypted = encrypt((raw_header or "").strip()) or ""


def get_site_header(exam: Exam) -> str:
    """Ochiq ko'rinishdagi sarlavha (`"Nom: qiymat"`) yoki bo'sh satr."""
    return decrypt(exam.site_header_encrypted) or ""


def mask_site_header(exam: Exam) -> str:
    """
    Panelda ko'rsatish uchun niqoblangan ko'rinish.

    SARLAVHA NOMI TO'LIQ QOLADI, qiymat esa niqoblanadi:
    "Authorization: Bear••••34u". Nom sir emas va aynan u
    administratorga kerak bo'ladi - "Authorization" o'rniga
    "X-Api-Key" yozib qo'yilgani shu yerdan ko'rinadi.

    Niqob qaytarish API'da qiymatning O'ZINI qaytarishdan
    farq qiladi: token brauzer devtools'ida, HAR ro'yxat
    so'rovida va eksport faylida ko'rinib qolardi.
    """
    header = get_site_header(exam)
    if not header:
        return ""
    name, separator, value = header.partition(":")
    if not separator:
        # Ikki nuqta yo'q - qiymat butunlay niqoblanadi: qaysi qismi
        # nom ekanini bilmasdan uni ochiq qoldirib bo'lmaydi.
        return _mask(header)
    return "{}: {}".format(name.strip(), _mask(value.strip()))


def _mask(value: str) -> str:
    if len(value) <= _MASK_HEAD + _MASK_TAIL:
        return "•" * len(value)
    return "{}{}{}".format(value[:_MASK_HEAD], "•" * 6, value[-_MASK_TAIL:])
