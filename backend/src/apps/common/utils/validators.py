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


# --------------------------------------------------------------------------
# Machine UUID (SMBIOS) - kompyuterning ASOSIY identifikatori
# --------------------------------------------------------------------------
# Qoidalar client bilan AYNAN bir xil (`client/services/system_info.py:
# normalize_machine_uuid`): ikki tomonda ikki xil qoida bo'lsa, client
# "yaroqli" deb yuborgan qiymat serverda 400 olardi yoki teskarisi.
MACHINE_UUID_RE = re.compile(
    r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$"
)

#: Ishlab chiqaruvchi to'ldirmagan "UUID"lar - ko'p mashinada BIR XIL
#: (arzon ona platalar, "To Be Filled By O.E.M."). Ularni qabul qilish
#: o'nlab kompyuterni bitta mashina qilib qo'yardi.
PLACEHOLDER_MACHINE_UUIDS = frozenset({
    "00000000-0000-0000-0000-000000000000",
    "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF",
    "03000200-0400-0500-0006-000700080009",
    "00020003-0004-0005-0006-000700080009",
    "12345678-1234-5678-90AB-CDDEEFAABBCC",
    "01234567-89AB-CDEF-0123-456789ABCDEF",
})


def normalize_machine_uuid(value) -> str:
    """
    Kanonik shakl (`XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX`, katta harf)
    yoki bo'sh satr (yaroqsiz).

    Katta harf SHART: `wmic`, PowerShell va SMBIOS o'quvchimiz katta
    harf beradi, Excel'ga esa kimdir kichik harf bilan yozadi - bazada
    ikki xil yozuv bitta mashinani ikkita qilardi (unikal cheklov ham
    ularni ajratmasdi).
    """
    text = str(value or "").strip().strip("{}").strip().upper()
    if not MACHINE_UUID_RE.match(text):
        return ""
    if text in PLACEHOLDER_MACHINE_UUIDS:
        return ""
    if len(set(text.replace("-", ""))) < 3:
        return ""
    return text


def machine_uuid_validator(value) -> None:
    if value in (None, ""):
        return
    if not normalize_machine_uuid(value):
        raise ValidationError(
            "Machine UUID noto'g'ri yoki to'ldirilmagan (XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX)",
            code="invalid_machine_uuid",
        )
