import re

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")
PINFL_RE = re.compile(r"^\d{14}$")

mac_address_validator = RegexValidator(
    regex=MAC_RE,
    message="MAC manzil formati noto'g'ri (AA:BB:CC:DD:EE:FF)",
    code="invalid_mac",
)

inventory_code_validator = RegexValidator(
    regex=r"^[A-Za-z0-9_\-]{3,50}$",
    message="Inventar kodi faqat harf, raqam, `-` va `_` dan iborat bo'lishi kerak",
    code="invalid_inventory_code",
)


def validate_pinfl(value: str) -> None:
    """
    JSHSHIR — aynan 14 ta raqam.

    Birinchi raqam shaxs turini bildiradi (1–6). Bu yengil tekshiruv
    tasodifiy xato kiritishni ushlaydi va tashqi API'ga keraksiz
    so'rov ketishining oldini oladi.
    """
    digits = str(value or "").strip()
    if not PINFL_RE.match(digits):
        raise ValidationError("JSHSHIR 14 ta raqamdan iborat bo'lishi kerak", code="invalid_pinfl")
    if digits[0] not in "34569":
        raise ValidationError("JSHSHIR birinchi raqami noto'g'ri", code="invalid_pinfl")


def normalize_mac(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = str(value).replace("-", ":").upper().strip()
    return cleaned if MAC_RE.match(cleaned) else None
