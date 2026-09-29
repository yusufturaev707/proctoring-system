"""
`REQUIRE_MACHINE_MAC=true` qilinsa qaysi kompyuterlar to'silishini ko'rsatadi.

Nima uchun kerak:
    Qat'iy rejimda UUID mos kelgan mashinaning MAC'i ham yozuvdagiga
    mos bo'lishi shart. MAC amalda o'zgaradi (tarmoq kartasi
    almashtirilgan, Wi-Fi yoqilib marshrut boshqa adapterga o'tgan) va
    buni imtihon KUNI emas, yoqishdan OLDIN bilish kerak.

Manba - `DeviceToken.reported_mac` (mashina oxirgi handshake'da aytgan
MAC). Qoida `devices.services.mac_matches` dan - handshake bilan bir
xil; alohida qoida bu ro'yxatni yolg'onga aylantirardi.

Ishlatish:
    python manage.py audit_machine_macs
    python manage.py audit_machine_macs --zone 12

HECH NARSA YOZMAYDI.
"""

from django.core.management.base import BaseCommand
from django.db.models import F, OuterRef, Subquery
from django.utils import timezone

from apps.devices.models import Computer, DeviceToken
from apps.devices.services import mac_matches


class Command(BaseCommand):
    help = "REQUIRE_MACHINE_MAC yoqilsa to'siladigan kompyuterlarni ko'rsatadi (faqat o'qiydi)"

    def add_arguments(self, parser):
        parser.add_argument("--zone", type=int, help="Faqat shu bino (Zone ID)")

    def handle(self, *args, **options):
        # Mashina bir necha client nusxasini ko'rgan bo'lishi mumkin
        # (qayta o'rnatish) - hozirgi holatni eng oxirgi ulangan tirik
        # nusxa aytadi.
        latest = (
            DeviceToken.objects.filter(computer=OuterRef("pk"))
            .exclude(status=DeviceToken.Status.REVOKED)
            # NULL (hech ulanmagan) oxirida - PostgreSQL `DESC` da ular birinchi.
            .order_by(F("last_used_at").desc(nulls_last=True), "-pk")
        )
        # Faqat qoida TA'SIR QILADIGAN yozuvlar: MAC'siz yozuv faqat UUID
        # bilan o'tadi, UUID'siz yozuv esa allaqachon MAC bo'yicha
        # tanilyapti (bog'lash yo'li), hisobdan chiqarilgani esa baribir
        # to'silgan.
        computers = (
            Computer.objects.alive()
            .filter(is_active=True, machine_uuid__isnull=False)
            .exclude(mac_address="")
            .select_related("zone")
            .annotate(
                last_reported_mac=Subquery(latest.values("reported_mac")[:1]),
                last_seen=Subquery(latest.values("last_used_at")[:1]),
            )
            .order_by("zone__name", "number", "inventory_code")
        )
        if options.get("zone"):
            computers = computers.filter(zone_id=options["zone"])

        rows = []
        unknown = 0
        for computer in computers:
            reported = computer.last_reported_mac or ""
            if mac_matches(computer, reported):
                continue
            if not reported:
                # Farq emas, NOMA'LUM: mashina yangi migratsiyadan keyin
                # hali ulanmagan. Qat'iy rejimda baribir to'siladi, lekin
                # administrator uchun sabab boshqa - avval ulab ko'rish.
                unknown += 1
            rows.append((
                computer.zone.name if computer.zone_id else "-",
                str(computer.number) if computer.number is not None else "-",
                computer.inventory_code,
                computer.mac_address,
                reported or "(aytilmagan)",
                (
                    timezone.localtime(computer.last_seen).strftime("%Y-%m-%d %H:%M")
                    if computer.last_seen else "-"
                ),
            ))

        if rows:
            header = ("Bino", "Raqam", "Inventar kodi", "Yozuvdagi MAC", "Mashina aytgan MAC", "Oxirgi ulanish")
            widths = [max(len(str(row[i])) for row in (header, *rows)) for i in range(len(header))]
            line = "  ".join("{:<%d}" % width for width in widths)
            self.stdout.write(line.format(*header))
            self.stdout.write("  ".join("-" * width for width in widths))
            for row in rows:
                self.stdout.write(line.format(*row))
            self.stdout.write("")

        summary = "REQUIRE_MACHINE_MAC=true qilinsa {} ta kompyuter to'siladi".format(len(rows))
        if unknown:
            summary += " ({} tasi hali MAC aytmagan - avval ulab ko'ring)".format(unknown)
        style = self.style.WARNING if rows else self.style.SUCCESS
        self.stdout.write(style(summary))
