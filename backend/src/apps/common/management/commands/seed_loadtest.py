"""
Yuklama sinovi uchun SINTETIK ma'lumot (idempotent).

    python manage.py seed_loadtest --users 7500 --platform-url http://127.0.0.1:8099/api/check \
        --manifest loadtest/results/manifest.json

HECH QACHON PRODUCTION BAZASIDA ISHLATMANG. Buyruq faqat `LT`
belgili yozuvlarni yaratadi va `cleanup_loadtest` ularni to'liq
o'chiradi, lekin sinov yuklamasi (sessiyalar, fayllar, audit) jonli
bazaga tushsa — bu allaqachon voqea. Himoya: `--allow-db` bilan
bazaning nomi aniq aytilmaguncha buyruq ishlamaydi.

NIMA YARATILADI (har "foydalanuvchi" = bitta kompyuter = bitta talabgor):

    Region    "LT Yuklama viloyati" (dtm_id 990001)
    Zone      "LT bino 01".. (har binoda --per-building kompyuter)
    AllowedPublicIp  100.64.<bino>.1 — binoning "NAT manzili"
    Computer  LT-B01-0001, machine_uuid, MAC, LAN IP, raqam
    DeviceToken  lt-dev-01-0001 (ACTIVE, `muid:<UUID>` izi)
    User      lt_op_01_0001 (Operator) — kompyuter operatori
    User      lt_proctor_01.. (Proktor) — panel foydalanuvchisi
    Exam      "LT Yuklama imtihoni" (site_url -> stub platforma)
    ExamSchedule  bugun, barcha binolar uchun
    ComputerBooking  har kompyuterga bitta JSHSHIR

NIMA UCHUN 100.64.0.0/10: bu CGNAT diapazoni — internetda
marshrutlanmaydi (haqiqiy tashkilotga tegishli emas), Python esa uni
xususiy deb HISOBLAMAYDI (`is_private=False`), ya'ni server uni
"binoning tashqi manzili" sifatida `AllowedPublicIp` bo'yicha
baholaydi — production'dagi kabi. 203.0.113.x/198.18.x kabi
hujjat/benchmark diapazonlari Python'da xususiy hisoblanadi va
tekshiruvni boshqa yo'lga burardi.

JSHSHIR — `99999` bilan boshlanadigan 14 xonali SOXTA raqam; ism
"Test Nomzod 0001". Haqiqiy shaxsiy ma'lumot ishlatilmaydi.

PAROL XESHI BIR MARTA hisoblanadi va hamma sintetik foydalanuvchiga
yoziladi: PBKDF2 har foydalanuvchi uchun ~0.3-1 s, 7500 ta uchun bu
soatlab kutish bo'lardi. Login paytidagi TEKSHIRUV narxi esa
o'zgarmaydi (u aynan yuklama modelining bir qismi).
"""

from __future__ import annotations

import json
import math
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.management import BaseCommand, CommandError, call_command
from django.db import connection, transaction
from django.utils import timezone

REGION_DTM_ID = 990001
REGION_NAME = "LT Yuklama viloyati"
ZONE_NUMBER_BASE = 9000
EXAM_NAME = "LT Yuklama imtihoni"
EXAM_TYPE_KEY = "lt-loadtest"
USER_PREFIX = "lt_"
DEVICE_PREFIX = "lt-dev-"
PINFL_PREFIX = "99999"


def building_ip(building: int) -> str:
    """Binoning "tashqi (NAT) manzili" — 100.64.<b>.1 (b = 1..254)."""
    return f"100.64.{building}.1"


def identity(index: int, per_building: int) -> dict:
    """
    `index` (1..N) -> bitta sintetik ish o'rni.

    Formula boshqa joyda TAKRORLANMAYDI: Locust `--manifest` faylini
    o'qiydi, ya'ni yagona manba shu funksiya.
    """
    building = (index - 1) // per_building + 1
    number = (index - 1) % per_building + 1
    machine_uuid = f"99999999-{building:04X}-4000-8000-{index:012X}"
    return {
        "index": index,
        "building": building,
        "number": number,
        "inventory_code": f"LT-B{building:02d}-{number:04d}",
        "machine_uuid": machine_uuid,
        "mac": "02:4C:54:{:02X}:{:02X}:{:02X}".format(building, number >> 8, number & 0xFF),
        "lan_ip": f"10.{building}.{number // 250}.{number % 250 + 1}",
        "device_id": f"{DEVICE_PREFIX}{building:02d}-{number:04d}",
        "pinfl": f"{PINFL_PREFIX}{index:09d}",
        "public_ip": building_ip(building),
    }


class Command(BaseCommand):
    help = "Yuklama sinovi uchun sintetik ma'lumot (LT belgili, idempotent)"

    def add_arguments(self, parser):
        parser.add_argument("--users", type=int, default=7500,
                            help="Kompyuter/talabgor soni (standart 7500)")
        parser.add_argument("--per-building", type=int, default=500,
                            help="Bitta binodagi kompyuterlar (standart 500)")
        parser.add_argument("--computers-per-operator", type=int, default=1,
                            help="Bitta operator hisobi nechta kompyuterda ishlaydi. "
                                 "1 — har kompyuterga alohida hisob (standart). "
                                 ">1 — `pinfl_lookup_operator` (300/soat) chegarasini "
                                 "sinash uchun.")
        parser.add_argument("--proctors", type=int, default=50,
                            help="Panel foydalanuvchilari (Proktor roli)")
        parser.add_argument("--password", default="LoadTest-2026!",
                            help="Barcha sintetik xodimlarning paroli")
        parser.add_argument("--platform-url", default="http://127.0.0.1:8099/api/check",
                            help="Tashqi platforma (stub) manzili — Exam.site_url")
        parser.add_argument("--schedule-hours", type=int, default=8,
                            help="Jadval oynasi: hozirdan boshlab necha soat ochiq")
        parser.add_argument("--manifest", default="",
                            help="Locust uchun JSON manifest yo'li")
        parser.add_argument("--allow-db", default="",
                            help="Himoya: bazaning NOMI aynan shu bo'lishi shart")

    def handle(self, *args, **opts):
        db_name = connection.settings_dict.get("NAME")
        if not opts["allow_db"] or opts["allow_db"] != db_name:
            raise CommandError(
                f"Himoya: joriy baza '{db_name}'. Sinov ma'lumotini yozish uchun "
                f"`--allow-db {db_name}` bering. PRODUCTION bazasida ISHLATMANG."
            )
        users = opts["users"]
        per_building = opts["per_building"]
        if users < 1 or per_building < 1:
            raise CommandError("--users va --per-building musbat bo'lishi kerak")
        buildings = math.ceil(users / per_building)
        if buildings > 254:
            raise CommandError("Binolar soni 254 dan oshmasligi kerak (100.64.<b>.1)")

        from apps.users.models import Role

        if not Role.objects.filter(name="Operator").exists():
            self.stdout.write("Rollar yo'q — `seed_base_data` chaqirilmoqda")
            call_command("seed_base_data")

        started = timezone.now()
        password_hash = make_password(opts["password"])
        with transaction.atomic():
            region = self._region()
            zones = self._zones(region, buildings, per_building)
            self._allowed_ips(zones)
            identities = [identity(i, per_building) for i in range(1, users + 1)]
            computers = self._computers(zones, identities)
            self._devices(computers, identities)
            operators = self._operators(
                region, zones, identities, opts["computers_per_operator"], password_hash
            )
            proctors = self._proctors(region, opts["proctors"], password_hash)
            exam, schedule = self._exam(opts["platform_url"], opts["schedule_hours"])
            self._bookings(schedule, computers, identities)

        manifest = {
            "generated_at": timezone.now().isoformat(),
            "database": db_name,
            "exam_id": exam.pk,
            "schedule_id": schedule.pk,
            "region_id": region.pk,
            "zones": {str(b): z.pk for b, z in zones.items()},
            "password": opts["password"],
            "per_building": per_building,
            "proctors": proctors,
            "users": [
                {
                    **ident,
                    "zone_id": zones[ident["building"]].pk,
                    "username": operators[ident["index"]],
                }
                for ident in identities
            ],
        }
        if opts["manifest"]:
            path = Path(opts["manifest"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            self.stdout.write(f"Manifest: {path.resolve()}")

        elapsed = (timezone.now() - started).total_seconds()
        self.stdout.write(self.style.SUCCESS(
            f"Tayyor ({elapsed:.1f} s): {users} kompyuter, {buildings} bino, "
            f"{len(set(operators.values()))} operator, {len(proctors)} proktor, "
            f"imtihon #{exam.pk}, jadval #{schedule.pk} "
            f"({timezone.localtime(schedule.starts_at):%H:%M}–"
            f"{timezone.localtime(schedule.ends_at):%H:%M})"
        ))

    # ------------------------------------------------------------------
    def _region(self):
        from apps.regions.models import Region

        region = Region.objects.filter(dtm_id=REGION_DTM_ID).first()
        if region is None:
            region = Region.objects.create(
                name=REGION_NAME, dtm_id=REGION_DTM_ID, vm_number=REGION_DTM_ID, is_active=True
            )
        return region

    def _zones(self, region, buildings: int, per_building: int) -> dict:
        from apps.regions.models import Zone

        zones = {}
        for b in range(1, buildings + 1):
            zone, _ = Zone.objects.update_or_create(
                region=region,
                number=ZONE_NUMBER_BASE + b,
                defaults={
                    "name": f"LT bino {b:02d}",
                    "capacity": per_building,
                    "is_active": True,
                    "deleted_at": None,
                },
            )
            zones[b] = zone
        return zones

    def _allowed_ips(self, zones: dict) -> None:
        from apps.controls.models import AllowedPublicIp

        for b, zone in zones.items():
            AllowedPublicIp.objects.update_or_create(
                ip_address=building_ip(b),
                defaults={"zone": zone, "name": f"LT bino {b:02d} NAT", "is_active": True},
            )
        # `allowed_ip_map` keshlanadi — yangi manzil darhol ko'rinsin.
        from django.core.cache import cache

        cache.clear()

    def _computers(self, zones: dict, identities: list) -> dict:
        from apps.devices.models import Computer

        existing = {
            c.inventory_code: c
            for c in Computer.objects.filter(inventory_code__startswith="LT-B", deleted_at__isnull=True)
        }
        new_rows = [
            Computer(
                zone=zones[i["building"]],
                number=i["number"],
                inventory_code=i["inventory_code"],
                ip_address=i["lan_ip"],
                machine_uuid=i["machine_uuid"],
                mac_address=i["mac"],
                is_active=True,
            )
            for i in identities
            if i["inventory_code"] not in existing
        ]
        Computer.objects.bulk_create(new_rows, batch_size=1000)
        return {
            c.inventory_code: c
            for c in Computer.objects.filter(inventory_code__startswith="LT-B", deleted_at__isnull=True)
        }

    def _devices(self, computers: dict, identities: list) -> None:
        from apps.devices.models import DeviceToken

        existing = set(
            DeviceToken.objects.filter(device_id__startswith=DEVICE_PREFIX)
            .values_list("device_id", flat=True)
        )
        rows = [
            DeviceToken(
                computer=computers[i["inventory_code"]],
                device_id=i["device_id"],
                hardware_fingerprint=f"muid:{i['machine_uuid']}",
                status=DeviceToken.Status.ACTIVE,
                app_version="loadtest",
            )
            for i in identities
            if i["device_id"] not in existing
        ]
        DeviceToken.objects.bulk_create(rows, batch_size=1000)
        # Oldingi sinovda bekor qilingan yoki o'zgargan bo'lsa — tiklash.
        DeviceToken.objects.filter(device_id__startswith=DEVICE_PREFIX).update(
            status=DeviceToken.Status.ACTIVE, revoked_at=None, revoke_reason=""
        )

    def _operators(self, region, zones, identities, per_operator: int, password_hash) -> dict:
        from apps.users.models import Role, User

        role = Role.objects.get(name="Operator")
        per_operator = max(1, per_operator)
        mapping = {}
        wanted = {}
        for i in identities:
            slot = (i["number"] - 1) // per_operator + 1
            username = f"{USER_PREFIX}op_{i['building']:02d}_{slot:04d}"
            mapping[i["index"]] = username
            wanted.setdefault(username, i["building"])
        existing = set(
            User.objects.filter(username__in=list(wanted)).values_list("username", flat=True)
        )
        User.objects.bulk_create(
            [
                User(
                    username=name,
                    password=password_hash,
                    first_name="Operator",
                    last_name=name,
                    role=role,
                    region=region,
                    zone=zones[building],
                    is_active=True,
                )
                for name, building in wanted.items()
                if name not in existing
            ],
            batch_size=1000,
        )
        User.objects.filter(username__in=list(wanted)).update(
            password=password_hash, is_active=True, role=role, region=region
        )
        return mapping

    def _proctors(self, region, count: int, password_hash) -> list:
        from apps.users.models import Role, User

        role = Role.objects.get(name="Proktor")
        names = [f"{USER_PREFIX}proctor_{n:02d}" for n in range(1, count + 1)]
        existing = set(User.objects.filter(username__in=names).values_list("username", flat=True))
        User.objects.bulk_create(
            [
                User(username=n, password=password_hash, first_name="Proktor",
                     last_name=n, role=role, region=region, is_active=True)
                for n in names
                if n not in existing
            ]
        )
        User.objects.filter(username__in=names).update(
            password=password_hash, is_active=True, role=role, region=region
        )
        return names

    def _exam(self, platform_url: str, hours: int):
        from apps.exams.models import Exam, ExamSchedule, ExamType

        exam_type, _ = ExamType.objects.update_or_create(
            key=EXAM_TYPE_KEY, defaults={"name": "LT yuklama turi", "is_active": True}
        )
        exam = Exam.objects.filter(name=EXAM_NAME, deleted_at__isnull=True).first()
        if exam is None:
            exam = Exam(name=EXAM_NAME)
        exam.key = "lt"
        exam.exam_type = exam_type
        exam.site_url = platform_url
        exam.duration_minutes = 180
        exam.is_active = True
        exam.save()

        now = timezone.now()
        schedule = (
            ExamSchedule.objects.filter(exam=exam, zone__isnull=True, deleted_at__isnull=True)
            .order_by("-pk")
            .first()
        )
        if schedule is None:
            schedule = ExamSchedule(exam=exam, zone=None)
        # Oyna HAR yurishda yangilanadi: sinov kuni buyruq qayta
        # ishga tushiriladi va jadval "bugun, hozirdan" bo'ladi.
        schedule.exam_date = timezone.localdate(now)
        schedule.starts_at = now + timedelta(minutes=5)
        schedule.ends_at = now + timedelta(hours=max(1, hours))
        schedule.checkin_lead_minutes = 60
        schedule.is_active = True
        schedule.save()
        return exam, schedule

    def _bookings(self, schedule, computers: dict, identities: list) -> None:
        from apps.exams.models import ComputerBooking

        now = timezone.now()
        existing = {
            b.computer_id: b
            for b in ComputerBooking.objects.filter(schedule=schedule)
        }
        rows = []
        for i in identities:
            computer = computers[i["inventory_code"]]
            if computer.pk in existing:
                continue
            rows.append(ComputerBooking(
                schedule=schedule, computer=computer, is_active=True,
                is_booked=True, pinfl=i["pinfl"], booked_at=now,
            ))
        ComputerBooking.objects.bulk_create(rows, batch_size=1000, ignore_conflicts=True)
        # Oldingi sinov joylarni bo'shatgan bo'lishi mumkin (`completed`) —
        # har bir kompyuter yana o'z JSHSHIRiga biriktiriladi.
        by_pinfl = {computers[i["inventory_code"]].pk: i["pinfl"] for i in identities}
        stale = [
            b for b in ComputerBooking.objects.filter(schedule=schedule)
            if not b.is_booked or b.pinfl != by_pinfl.get(b.computer_id, b.pinfl)
        ]
        for b in stale:
            b.is_booked = True
            b.pinfl = by_pinfl.get(b.computer_id, b.pinfl)
            b.booked_at = now
            b.is_active = True
        if stale:
            # Ikki bosqich: avval bo'shatib, keyin biriktirish —
            # `unique_booking_schedule_pinfl` oraliqda to'qnashmasin.
            ComputerBooking.objects.filter(pk__in=[b.pk for b in stale]).update(
                is_booked=False, pinfl=""
            )
            ComputerBooking.objects.bulk_update(
                stale, ["is_booked", "pinfl", "booked_at", "is_active"], batch_size=1000
            )
        if settings.DEBUG:
            self.stdout.write(f"  Bron: {len(rows)} yangi, {len(stale)} tiklandi")
