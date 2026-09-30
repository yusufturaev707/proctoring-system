"""
Kompyuter identifikatori - (Machine UUID, MAC) juftligi - bo'yicha muammolar.

Nima uchun kerak:
    Mashina endi faqat juftlik bo'yicha tanilanadi
    (`devices.services.find_computer_by_identity`). Yozuvdagi MAC
    mashinanikidan farq qilsa yoki umuman yo'q bo'lsa, handshake
    `not_found` beradi - buni imtihon KUNI emas, oldindan bilish kerak.

Uch ro'yxat:
    1. MAC'siz kompyuterlar - o'tish davrida faqat UUID bilan tanilyapti
       va shu UUID'li ikkinchi yozuv qo'shilishi bilan tanilmay qoladi;
    2. bir xil UUID'li guruhlar - bir partiyadagi platalar; ularda MAC
       yagona ajratuvchi, MAC'siz a'zo esa tanilmaydi;
    3. oxirgi handshake'da mashina aytgan MAC (`DeviceToken.reported_mac`)
       yozuvdagidan farq qiladigan kompyuterlar - ular hozir `not_found`.

"Bitta device_id ni ikki xil juftlik ishlatgan" holati tekshirilMAYDI:
`DeviceToken` faqat OXIRGI aytilgan qiymatni saqlaydi, tarix yo'q.

Ishlatish:
    python manage.py audit_machine_identity
    python manage.py audit_machine_identity --zone 12

HECH NARSA YOZMAYDI.
"""

from django.core.management.base import BaseCommand
from django.db.models import Count, F, OuterRef, Subquery
from django.utils import timezone

from apps.common.utils.validators import normalize_mac
from apps.devices.models import Computer, DeviceToken


class Command(BaseCommand):
    help = "Kompyuter identifikatori (UUID, MAC) muammolarini ko'rsatadi (faqat o'qiydi)"

    def add_arguments(self, parser):
        parser.add_argument("--zone", type=int, help="Faqat shu bino (Zone ID)")

    def handle(self, *args, **options):
        computers = Computer.objects.alive().select_related("zone")
        if options.get("zone"):
            computers = computers.filter(zone_id=options["zone"])

        no_mac = self._no_mac(computers)
        groups = self._same_uuid(computers)
        changed, silent = self._reported_differs(computers)

        self.stdout.write(
            "Bitta device_id ni ikki xil juftlik ishlatgani tekshirilmadi: "
            "qurilma faqat oxirgi aytilgan qiymatni saqlaydi (tarix yo'q)."
        )
        summary = (
            "MAC'siz: {} ta; bir xil UUID'li guruh: {} ta; mashina aytgan MAC "
            "yozuvdagidan farq qiladi: {} ta".format(no_mac, groups, changed)
        )
        if silent:
            summary += " ({} ta kompyuter hali MAC aytmagan - avval ulab ko'ring)".format(silent)
        problems = no_mac or groups or changed
        self.stdout.write((self.style.WARNING if problems else self.style.SUCCESS)(summary))

    # ------------------------------------------------------------------
    def _no_mac(self, computers) -> int:
        rows = [
            (_zone(c), _number(c), c.inventory_code, c.machine_uuid or "-")
            for c in computers.filter(mac_address="").order_by("zone__name", "number", "inventory_code")
        ]
        self._table(
            "1. MAC'siz kompyuterlar (administrator MAC kiritishi kerak)",
            ("Bino", "Raqam", "Inventar kodi", "Machine UUID"), rows,
        )
        return len(rows)

    def _same_uuid(self, computers) -> int:
        duplicated = (
            computers.filter(machine_uuid__isnull=False)
            .values("machine_uuid")
            .annotate(total=Count("pk"))
            .filter(total__gt=1)
            .values_list("machine_uuid", flat=True)
        )
        members = computers.filter(machine_uuid__in=list(duplicated)).order_by(
            "machine_uuid", "zone__name", "number", "inventory_code"
        )
        rows = [
            (c.machine_uuid, _zone(c), _number(c), c.inventory_code, c.mac_address or "(MAC yo'q)")
            for c in members
        ]
        self._table(
            "2. Bir xil Machine UUID'li kompyuterlar (ajratuvchi - faqat MAC)",
            ("Machine UUID", "Bino", "Raqam", "Inventar kodi", "MAC"), rows,
        )
        return len({row[0] for row in rows})

    def _reported_differs(self, computers) -> tuple[int, int]:
        # Mashina bir necha client nusxasini ko'rgan bo'lishi mumkin
        # (qayta o'rnatish) - hozirgi holatni eng oxirgi ulangan tirik
        # nusxa aytadi.
        latest = (
            DeviceToken.objects.filter(computer=OuterRef("pk"))
            .exclude(status=DeviceToken.Status.REVOKED)
            # NULL (hech ulanmagan) oxirida - PostgreSQL `DESC` da ular birinchi.
            .order_by(F("last_used_at").desc(nulls_last=True), "-pk")
        )
        annotated = (
            computers.filter(is_active=True)
            .exclude(mac_address="")
            .annotate(
                last_reported_mac=Subquery(latest.values("reported_mac")[:1]),
                last_seen=Subquery(latest.values("last_used_at")[:1]),
            )
            .order_by("zone__name", "number", "inventory_code")
        )
        rows = []
        silent = 0
        for computer in annotated:
            reported = normalize_mac(computer.last_reported_mac) or ""
            if not reported:
                silent += 1
                continue
            if reported == normalize_mac(computer.mac_address):
                continue
            rows.append((
                _zone(computer), _number(computer), computer.inventory_code,
                computer.mac_address, reported,
                (
                    timezone.localtime(computer.last_seen).strftime("%Y-%m-%d %H:%M")
                    if computer.last_seen else "-"
                ),
            ))
        self._table(
            "3. Mashina aytgan MAC yozuvdagidan farq qiladi (hozir `not_found`)",
            ("Bino", "Raqam", "Inventar kodi", "Yozuvdagi MAC", "Mashina aytgan MAC", "Oxirgi ulanish"),
            rows,
        )
        return len(rows), silent

    def _table(self, title: str, header: tuple, rows: list) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING(title))
        if not rows:
            self.stdout.write("   yo'q")
            self.stdout.write("")
            return
        widths = [max(len(str(row[i])) for row in (header, *rows)) for i in range(len(header))]
        line = "  ".join("{:<%d}" % width for width in widths)
        self.stdout.write(line.format(*header))
        self.stdout.write("  ".join("-" * width for width in widths))
        for row in rows:
            self.stdout.write(line.format(*row))
        self.stdout.write("")


def _zone(computer) -> str:
    return computer.zone.name if computer.zone_id else "-"


def _number(computer) -> str:
    return str(computer.number) if computer.number is not None else "-"
