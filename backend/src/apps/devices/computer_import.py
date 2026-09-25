"""
Kompyuterlarni Excel'dan ommaviy qo'shish.

Ustunlar (nomdagi qavs ichi e'tiborsiz qoldiriladi -
`dtm_id (region.dtm_id)` = `dtm_id`):

    dtm_id          viloyat (`Region.dtm_id`)          majburiy
    zone_number     bino (`Zone.number`, o'sha viloyatda) majburiy
    mac_address     mashina                            majburiy
    number          xonadagi tartib raqami             majburiy
    inventory_code  buxgalteriya kodi                  ixtiyoriy

Viloyat va bino TASHQI RAQAMLAR bilan beriladi (FaceID integratsiyasidagi
kabi, `CLAUDE.md`): ichki ID'ni Excel tayyorlaydigan odam bilmaydi.

HAMMASI YOKI HECH NARSA. Bitta qatorda xato bo'lsa, birorta ham qator
yozilmaydi va javobda har bir xato qator/ustun bilan qaytadi. Qisman
import "qaysilari tushdi?" degan savolni qoldirardi va tuzatilgan faylni
qayta yuklash endi yarmi "allaqachon bor" bo'lib chiqardi. Shu sababli
`dry_run` ham bor: panel avval tekshiradi, keyin yozadi - ikkalasi bitta
funksiya, ya'ni tekshiruvda "o'tdi" degan fayl yozishda yiqilmaydi
(poyga holatidan tashqari, uni bazadagi cheklovlar ushlaydi).

MAC ALLAQACHON RO'YXATDA - XATO EMAS, O'TKAZIB YUBORILADI. Tuzatilgan
yoki to'ldirilgan faylni qayta yuklash odatiy ish va u oldingi safar
qo'shilgan mashinalar tufayli yiqilmasligi kerak. Mavjud yozuv
O'ZGARTIRILMAYDI: import - qo'shish vositasi, tahrirlash emas.
"""

from __future__ import annotations

import io
import re

from django.db import transaction

from apps.common.utils.validators import normalize_mac
from apps.regions.models import Region, Zone

from .models import Computer

MAX_ROWS = 5000
MAX_FILE_BYTES = 5 * 1024 * 1024

#: (ustun kodi, shablondagi sarlavha, majburiymi)
COLUMNS = (
    ("dtm_id", "dtm_id (region.dtm_id)", True),
    ("zone_number", "zone_number (zone.number)", True),
    ("mac_address", "mac_address", True),
    ("number", "number", True),
    ("inventory_code", "inventory_code", False),
)
_REQUIRED = [code for code, _, required in COLUMNS if required]
_INVENTORY_RE = re.compile(r"^[A-Za-z0-9_\-]{3,50}$")


class ImportFileError(Exception):
    """Fayl umuman o'qilmadi (qator darajasidagi xato emas)."""


def _clean(value) -> str:
    """Katak qiymati -> satr; qavs ichi tashlanadi (`12 (Toshkent)` -> `12`)."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        # Excel sonni float qilib saqlaydi: 12 -> 12.0.
        value = int(value)
    return str(value).split("(")[0].strip()


def _header(value) -> str:
    return _clean(value).lower().replace(" ", "_")


def _int(value: str):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Shablon
# --------------------------------------------------------------------------
def build_template() -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    ws = wb.active
    ws.title = "Kompyuterlar"
    ws.append([title for _, title, _ in COLUMNS])
    head_fill = PatternFill("solid", fgColor="1F6F5C")
    optional_fill = PatternFill("solid", fgColor="6B7C77")
    for index, (_, _, required) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=index)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = head_fill if required else optional_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[cell.column_letter].width = 28
    ws.row_dimensions[1].height = 24
    ws.freeze_panes = "A2"
    # MAC va inventar kodi MATN bo'lishi kerak: Excel "00-1A-..." yoki
    # "0012" ni son/sana deb o'girib qo'yardi.
    for letter in ("C", "E"):
        for row in range(2, MAX_ROWS + 2):
            ws[f"{letter}{row}"].number_format = "@"
    positive = DataValidation(type="whole", operator="greaterThan", formula1="0", allow_blank=True)
    positive.error = "Musbat butun son kiriting"
    ws.add_data_validation(positive)
    positive.add(f"A2:B{MAX_ROWS + 1}")
    positive.add(f"D2:D{MAX_ROWS + 1}")

    guide = wb.create_sheet("Yo'riqnoma")
    guide.column_dimensions["A"].width = 22
    guide.column_dimensions["B"].width = 80
    rows = [
        ("Ustun", "Qiymat"),
        ("dtm_id", "Viloyatning DTM ID raqami (Viloyatlar sahifasidagi «DTM ID»). Majburiy."),
        ("zone_number", "Binoning raqami - o'sha viloyat ichida (Binolar sahifasi). Majburiy."),
        ("mac_address", "AA:BB:CC:DD:EE:FF yoki AA-BB-CC-DD-EE-FF. Majburiy, tizim bo'ylab unikal."),
        ("number", "Xonadagi tartib raqami (stoldagi raqam), 1..32767. Majburiy, bino ichida unikal."),
        ("inventory_code", "Ixtiyoriy. 3-50 belgi: lotin harfi, raqam, '-', '_'. "
                           "Bo'sh bo'lsa AUTO-<MAC> ko'rinishida yaratiladi."),
        ("", ""),
        ("Qoidalar", "Sarlavhadagi qavs ichi e'tiborsiz qoldiriladi. Bitta qatorda xato bo'lsa "
                     "hech narsa yozilmaydi. MAC allaqachon ro'yxatda bo'lsa qator o'tkazib "
                     "yuboriladi (mavjud yozuv o'zgarmaydi). Ko'pi bilan {} qator.".format(MAX_ROWS)),
        ("Namuna", "dtm_id=10, zone_number=1, mac_address=00:1A:2B:3C:4D:5E, number=12, inventory_code=INV-0012"),
    ]
    for row in rows:
        guide.append(row)
    guide["A1"].font = Font(bold=True)
    guide["B1"].font = Font(bold=True)
    for row in guide.iter_rows(min_row=2):
        row[1].alignment = Alignment(wrap_text=True, vertical="top")
        row[0].font = Font(bold=True)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


# --------------------------------------------------------------------------
# O'qish
# --------------------------------------------------------------------------
def read_rows(upload) -> list[dict]:
    """Birinchi varaqni o'qiydi: `[{"row": 2, "dtm_id": "10", ...}, ...]`."""
    from openpyxl import load_workbook

    if upload.size > MAX_FILE_BYTES:
        raise ImportFileError("Fayl juda katta (ko'pi bilan 5 MB).")
    try:
        wb = load_workbook(upload, read_only=True, data_only=True)
    except Exception:
        raise ImportFileError("Fayl o'qilmadi - .xlsx formatidagi Excel fayl yuklang.")
    try:
        ws = wb.worksheets[0]
        rows = ws.iter_rows(values_only=True)
        header = next(rows, None)
        if not header:
            raise ImportFileError("Fayl bo'sh.")
        index = {}
        for position, value in enumerate(header):
            code = _header(value)
            if code in dict((c, 1) for c, _, _ in COLUMNS) and code not in index:
                index[code] = position
        missing = [code for code in _REQUIRED if code not in index]
        if missing:
            raise ImportFileError("Ustun topilmadi: {}.".format(", ".join(missing)))

        result = []
        for number, values in enumerate(rows, start=2):
            item = {
                code: _clean(values[position]) if position < len(values) else ""
                for code, position in index.items()
            }
            if not any(item.values()):
                continue  # bo'sh qator (Excel oxirida qoldiradi)
            item["row"] = number
            result.append(item)
            if len(result) > MAX_ROWS:
                raise ImportFileError("Qatorlar juda ko'p (ko'pi bilan {}).".format(MAX_ROWS))
        if not result:
            raise ImportFileError("Faylda ma'lumot qatori yo'q.")
        return result
    finally:
        wb.close()


# --------------------------------------------------------------------------
# Tekshirish va yozish
# --------------------------------------------------------------------------
def import_computers(rows: list[dict], *, user, dry_run: bool) -> dict:
    """
    Qatorlarni tekshiradi va (xato bo'lmasa, `dry_run=False` da) yozadi.

    Barcha bazaviy qidiruvlar TO'PLAM bo'yicha - qator soniga bog'liq
    bo'lmagan 5 ta so'rov (viloyat, bino, MAC, inventar, raqam).
    """
    errors: list[dict] = []
    skipped: list[dict] = []

    def fail(row, column, message):
        errors.append({"row": row["row"], "column": column, "message": message})

    dtm_ids = {_int(r.get("dtm_id")) for r in rows} - {None}
    regions = {r.dtm_id: r for r in Region.objects.filter(dtm_id__in=dtm_ids)}
    zones = {
        (z.region_id, z.number): z
        for z in Zone.objects.filter(region__in=regions.values()).select_related("region")
    }

    parsed = []
    for row in rows:
        before = len(errors)
        dtm_id = _int(row.get("dtm_id"))
        region = regions.get(dtm_id)
        zone = None
        if dtm_id is None:
            fail(row, "dtm_id", "Viloyat DTM ID si kiritilmagan yoki son emas.")
        elif region is None:
            fail(row, "dtm_id", "DTM ID {} li viloyat topilmadi.".format(dtm_id))
        elif user.is_region_scoped and region.pk != user.region_id:
            fail(row, "dtm_id", "Bu viloyat sizning hududingizga tegishli emas.")
        else:
            zone_number = _int(row.get("zone_number"))
            zone = zones.get((region.pk, zone_number))
            if zone_number is None:
                fail(row, "zone_number", "Bino raqami kiritilmagan yoki son emas.")
            elif zone is None:
                fail(row, "zone_number", "«{}» viloyatida {}-bino topilmadi.".format(region.name, zone_number))

        mac = normalize_mac(row.get("mac_address"))
        if not row.get("mac_address"):
            fail(row, "mac_address", "MAC manzil kiritilmagan.")
        elif mac is None:
            fail(row, "mac_address", "MAC formati noto'g'ri (AA:BB:CC:DD:EE:FF).")

        number = _int(row.get("number"))
        if number is None or not 1 <= number <= 32767:
            fail(row, "number", "Kompyuter raqami 1..32767 oralig'idagi butun son bo'lishi kerak.")

        code = row.get("inventory_code", "")
        if code and not _INVENTORY_RE.match(code):
            fail(row, "inventory_code", "Inventar kodi: 3-50 belgi, lotin harfi, raqam, '-' yoki '_'.")
        if not code and mac:
            code = "AUTO-" + mac.replace(":", "")

        if len(errors) == before:
            parsed.append({"row": row["row"], "zone": zone, "mac": mac, "number": number, "code": code})

    # --- fayl ichidagi takrorlar -----------------------------------------
    def duplicates(key, column, message):
        seen = {}
        for item in parsed:
            value = key(item)
            if value in seen:
                errors.append({"row": item["row"], "column": column,
                               "message": message.format(seen[value])})
            else:
                seen[value] = item["row"]

    duplicates(lambda i: i["mac"], "mac_address", "Bu MAC faylda takrorlangan ({}-qator).")
    duplicates(lambda i: i["code"].upper(), "inventory_code", "Bu inventar kodi faylda takrorlangan ({}-qator).")
    duplicates(lambda i: (i["zone"].pk, i["number"]), "number", "Bu raqam shu binoda faylda takrorlangan ({}-qator).")

    # --- bazadagi mavjud yozuvlar -----------------------------------------
    alive = Computer.objects.filter(deleted_at__isnull=True)
    existing_mac = {
        c.mac_address: c
        for c in alive.filter(mac_address__in={i["mac"] for i in parsed}).select_related("zone")
    }
    to_create = []
    for item in parsed:
        known = existing_mac.get(item["mac"])
        if known is not None:
            skipped.append({"row": item["row"], "mac_address": item["mac"],
                            "message": "Allaqachon ro'yxatda: {} ({}).".format(known.label, known.zone.name)})
        else:
            to_create.append(item)

    taken_codes = set(
        alive.filter(inventory_code__in={i["code"] for i in to_create})
        .values_list("inventory_code", flat=True)
    )
    zone_ids = {i["zone"].pk for i in to_create}
    taken_numbers = set(
        alive.filter(zone_id__in=zone_ids, number__in={i["number"] for i in to_create})
        .values_list("zone_id", "number")
    )
    for item in to_create:
        if item["code"] in taken_codes:
            errors.append({"row": item["row"], "column": "inventory_code",
                           "message": "«{}» inventar kodi boshqa kompyuterda band.".format(item["code"])})
        if (item["zone"].pk, item["number"]) in taken_numbers:
            errors.append({"row": item["row"], "column": "number",
                           "message": "{}-raqam «{}» binosida band.".format(item["number"], item["zone"].name)})

    errors.sort(key=lambda e: (e["row"], e["column"]))
    report = {
        "total": len(rows),
        "to_create": len(to_create) if not errors else 0,
        "skipped": skipped,
        "errors": errors,
        "created": 0,
        "dry_run": dry_run,
    }
    if errors or dry_run or not to_create:
        report["to_create"] = 0 if errors else len(to_create)
        return report

    with transaction.atomic():
        Computer.objects.bulk_create([
            Computer(zone=item["zone"], mac_address=item["mac"], number=item["number"],
                     inventory_code=item["code"], is_active=True)
            for item in to_create
        ])
    report["created"] = len(to_create)
    report["to_create"] = len(to_create)
    return report
