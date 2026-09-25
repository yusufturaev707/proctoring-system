"""
Boshlang'ich ma'lumotlarni yaratadi.

    python manage.py seed_base_data
    python manage.py seed_base_data --demo   # demo hudud/bino/kompyuter ham
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.users import services
from apps.users.models import Permission, Role

#: Rol -> (kalit, respublika bo'yichami, ruxsat kodlari).
#:
#: `is_global=True` - hudud filtri qo'llanmaydi (`User.is_region_scoped`).
#: Bu ilgari `is_superuser` bayrog'i orqali hal qilinardi; endi qaror
#: rolda, ya'ni "kim nima ko'radi" savoliga javob bitta jadvalda.
ROLE_MATRIX: dict[str, tuple[int, bool, list[str]]] = {
    # Respublika administratori — yagona to'liq huquqli rol.
    #
    # Superadmin roli OLIB TASHLANDI (migratsiya `0003_drop_superadmin_role`):
    # u Administrator bilan bir xil ruxsatlarga ega edi va faqat
    # `is_superuser` bayrog'i bilan farqlanardi. Ikkita amalda bir xil
    # rol "kim nima qila oladi" savolini chalkashtirardi.
    "Administrator": (1, True, ["*"]),
    "Proktor": (
        2,
        False,
        [
            "dashboard.view", "sessions.view", "sessions.warn", "sessions.terminate",
            "technical.view", "technical.resolve", "devices.view",
            # Dalilni ko'rish AYNAN proktorga kerak: chetlashtirish
            # qarorini u chiqaradi va uni asoslash uchun videoni
            # ko'rishi shart. Kuzatuv siyosatini o'zgartirish huquqi
            # esa unda YO'Q - u qoidani qo'llaydi, o'zgartirmaydi.
            "evidence.view", "controls.proctoring_view",
            # Talabgor "qaysi kompyuterda o'tirishi kerak edi?" —
            # proktor buni ko'radi, lekin bronni o'zgartirmaydi.
            "bookings.view",
        ],
    ),
    "Monitoring": (
        3,
        False,
        ["dashboard.view", "sessions.view", "technical.view", "devices.view", "bookings.view"],
    ),
    "Kuzatuvchi": (4, False, ["dashboard.view", "sessions.view"]),
    # Imtihon markazidagi ish o'rni: talabgorni qabul qiladi va uning
    # shaxsini hujjat bo'yicha tasdiqlaydi. Chetlashtirish huquqi YO'Q —
    # u proktorning ishi.
    "Operator": (
        5,
        False,
        [
            "client.operate", "client.identity", "client.exit",
            "sessions.view", "technical.view",
            # Operator talabgorni stolga YO'NALTIRADI va buning uchun
            # bron ro'yxatini ko'rishi kerak.
            "bookings.view",
        ],
    ),
}


class Command(BaseCommand):
    help = "Ruxsatlar, rollar va (ixtiyoriy) demo ma'lumotlarni yaratadi"

    def add_arguments(self, parser):
        parser.add_argument("--demo", action="store_true", help="Demo hudud/qurilmalarni ham yaratadi")

    @transaction.atomic
    def handle(self, *args, **options):
        created = services.sync_default_permissions()
        self.stdout.write(self.style.SUCCESS(f"Ruxsatlar: {created} ta yangi"))

        for name, (key, is_global, codes) in ROLE_MATRIX.items():
            # Qidiruv NOM bo'yicha: kalitlar shu relizda qayta
            # raqamlangan (Superadmin olib tashlandi), shuning uchun
            # `key` bo'yicha qidirish mavjud rolni boshqasining ustiga
            # yozib yuborardi.
            role, _ = Role.objects.update_or_create(
                name=name,
                defaults={"key": key, "is_global": is_global, "is_active": True},
            )
            if codes == ["*"]:
                role.permissions.set(Permission.objects.all())
            else:
                role.permissions.set(Permission.objects.filter(code__in=codes))
            scope = "respublika" if is_global else "viloyat"
            self.stdout.write(
                f"  Rol: {name} ({role.permissions.count()} ruxsat, {scope})"
            )

        self._seed_controls()

        if options["demo"]:
            self._seed_demo()

        self.stdout.write(self.style.SUCCESS("Tayyor."))

    def _seed_controls(self):
        from apps.controls.models import CocoObject, HotKeyboardKey, RdpObject, Setting

        # Imtihonda eng ko'p uchraydigan taqiqlangan obyektlar (COCO indekslari).
        coco_defaults = [
            (67, "Telefon", 4), (73, "Kitob", 3), (63, "Noutbuk", 4),
            (62, "Televizor/Monitor", 3), (0, "Odam", 2), (26, "Sumka", 1),
        ]
        for code, name, severity in coco_defaults:
            CocoObject.objects.update_or_create(
                code=code, defaults={"name": name, "severity": severity, "is_active": True}
            )

        # CLIENT'DA ICHKI KATALOG BOR (`client/services/threat_rules.py`)
        # va u serverdan MUSTAQIL ishlaydi — bu jadval bo'sh bo'lsa ham
        # AnyDesk, VirtualBox va qolganlari aniqlanadi. Bu yozuvlar ikki
        # vazifani bajaradi: panelda ro'yxat ko'rinib tursin (aks holda
        # administrator "aniqlash sozlanmagan" deb o'ylardi) va yangi
        # dastur qo'shish FORMATI namuna bilan ko'rsatilsin.
        #
        # Shuning uchun ular faqat jarayon nomi bilan emas, ichki
        # katalogdagi kabi QAYTA NOMLASHGA CHIDAMLI belgilar bilan
        # yoziladi: nom bo'yicha qidiruv `AnyDesk.exe` ni `note.exe`
        # deb nomlash bilan bekor bo'ladi.
        rdp_defaults = [
            {
                "code": "anydesk", "name": "AnyDesk", "category": "remote",
                "process_names": ["AnyDesk.exe"],
                "publishers": ["AnyDesk Software GmbH"],
                "original_filenames": ["AnyDesk.exe"],
                "service_names": ["AnyDesk"], "ports": [7070],
            },
            {
                "code": "teamviewer", "name": "TeamViewer", "category": "remote",
                "process_names": ["TeamViewer.exe", "TeamViewer_Service.exe"],
                "publishers": ["TeamViewer"],
                "original_filenames": ["TeamViewer.exe", "TeamViewer_Service.exe"],
                "service_names": ["TeamViewer"], "ports": [5938],
            },
            {
                "code": "rustdesk", "name": "RustDesk", "category": "remote",
                "process_names": ["rustdesk.exe"],
                # Imzo egasi dastur nomiga o'xshamaydi — aynan shu
                # sababdan uni faqat nom bo'yicha qidirish yaramaydi.
                "publishers": ["Purslane Ltd"],
                "original_filenames": ["rustdesk.exe"],
                "service_names": ["RustDesk"],
                "ports": [21115, 21116, 21117, 21118, 21119],
            },
            {
                "code": "crd", "name": "Chrome Remote Desktop", "category": "remote",
                "process_names": ["remoting_host.exe"],
                # "Google LLC" imzosi ATAYLAB yo'q: u Chrome'ning
                # o'zini ham tutardi.
                "original_filenames": [
                    "remoting_host.exe", "remote_assistance_host.exe",
                ],
                "products": ["Chrome Remote Desktop"],
                "service_names": ["chromoting"],
            },
            {
                "code": "mstsc", "name": "Remote Desktop Connection", "category": "remote",
                "process_names": ["mstsc.exe"],
                "original_filenames": ["mstsc.exe"],
                "products": ["Remote Desktop Connection"],
            },
            {
                "code": "virtualbox", "name": "Oracle VirtualBox", "category": "vm",
                "process_names": ["VirtualBox.exe", "VBoxSVC.exe"],
                "publishers": ["innotek GmbH"],
                "original_filenames": ["VirtualBox.exe", "VBoxSVC.exe"],
                "products": ["VirtualBox"], "service_names": ["VBoxSDS"],
            },
            {
                "code": "vmware", "name": "VMware Workstation", "category": "vm",
                "process_names": ["vmware.exe", "vmware-vmx.exe"],
                "publishers": ["VMware, Inc."],
                "original_filenames": ["vmware.exe", "vmware-vmx.exe"],
                "service_names": ["VMwareHostd"],
            },
        ]
        for entry in rdp_defaults:
            RdpObject.objects.update_or_create(
                code=entry.pop("code"), defaults={**entry, "is_active": True}
            )

        hotkey_defaults = [
            ("Alt+Tab", "alt+tab"), ("Win", "win"), ("Ctrl+Shift+I", "ctrl+shift+i"),
            ("F12", "f12"), ("Ctrl+C", "ctrl+c"), ("Ctrl+V", "ctrl+v"),
            ("PrintScreen", "printscreen"), ("Ctrl+P", "ctrl+p"), ("Alt+F4", "alt+f4"),
        ]
        for name, code in hotkey_defaults:
            HotKeyboardKey.objects.update_or_create(
                code=code, defaults={"name": name, "is_active": True}
            )

        setting, was_created = Setting.objects.get_or_create(
            name="Standart", defaults={"is_active": True}
        )
        if was_created:
            setting.detect_classes.set(CocoObject.objects.filter(is_active=True))
            setting.rdp_objects.set(RdpObject.objects.all())
            setting.hotkeys.set(HotKeyboardKey.objects.all())
            self.stdout.write("  Standart sozlama yaratildi")

    def _seed_demo(self):
        """
        Demo ma'lumot.

        ASOSIY QOIDA: mavjud yozuvga TEGILMAYDI. Ilgari bu yerda
        `update_or_create` ishlatilardi va u bazada haqiqiy ma'lumot
        bo'lganda ikki xil buzilardi:

          * `Region` ning uchta maydoni ham unikal (`name`, `dtm_id`,
            `vm_number`). `dtm_id=1` bo'yicha qidirish boshqa `dtm_id`
            ostidagi "Toshkent shahri" ga urilib, butun buyruqni
            `IntegrityError` bilan yiqitardi;
          * `zone` va `computer` esa yiqilmasdan, haqiqiy binoni
            "1-bino" ga, haqiqiy kompyuterni demo IP/MAC ga aylantirib
            qo'yardi — bu buyruqning maqsadi emas.

        Endi mavjud viloyat/bino QAYTA ISHLATILADI, faqat yetishmagani
        yaratiladi. Buyruq shu tufayli idempotent ham bo'ldi.
        """
        from django.db.models import Q

        from apps.devices.models import Computer
        from apps.exams.models import Exam, ExamType
        from apps.regions.models import Region, Zone

        # Avval NOM bo'yicha: viloyatlar ro'yxati yuklangan bazada demo
        # ma'lumot har safar bir xil joyga tushishi kerak. Topilmasa —
        # birinchi faol viloyat, u ham bo'lmasa yangisi yaratiladi.
        region = (
            Region.objects.filter(name="Toshkent shahri").first()
            or Region.objects.filter(is_active=True).order_by("dtm_id").first()
        )
        if region is None:
            region = Region.objects.create(
                name="Toshkent shahri", dtm_id=1, vm_number=1, is_active=True
            )

        zone = (
            Zone.objects.filter(region=region, deleted_at__isnull=True)
            .order_by("number")
            .first()
        )
        if zone is None:
            zone = Zone.objects.create(
                region=region, name="1-bino", number=1, capacity=200, is_active=True
            )

        computers = 0
        for index in range(1, 11):
            code = f"PC-{index:04d}"
            ip_address = f"192.168.10.{index}"
            mac_address = f"AA:BB:CC:DD:{index:02X}:01"
            # Uchala shartli unikal cheklov ham oldindan tekshiriladi
            # (`inventory_code`, `mac_address`, `zone`+`ip_address`) —
            # aks holda bitta mos kelib qolgan qator butun tranzaksiyani
            # bekor qilardi.
            taken = Computer.objects.filter(deleted_at__isnull=True).filter(
                Q(inventory_code=code)
                | Q(mac_address=mac_address)
                | Q(zone=zone, ip_address=ip_address)
                # To'rtinchi shartli cheklov: raqam bino ichida
                # unikal. Demo ikki marta ishga tushirilsa, o'sha
                # raqam bilan ikkinchi qator tranzaksiyani
                # bekor qilardi.
                | Q(zone=zone, number=index)
            )
            if taken.exists():
                continue
            Computer.objects.create(
                zone=zone,
                number=index,
                inventory_code=code,
                ip_address=ip_address,
                mac_address=mac_address,
                is_active=True,
            )
            computers += 1
        # Turlar demo bo'limida: haqiqiy ro'yxat muassasaga bog'liq va uni
        # operator admin panelidan kiritadi. Bu yerda faqat namuna.
        exam_type, _ = ExamType.objects.update_or_create(
            key="demo", defaults={"name": "Demo turi", "is_active": True}
        )
        Exam.objects.update_or_create(
            name="Demo imtihon",
            defaults={
                "key": "demo", "external_code": "demo-2026",
                "exam_type": exam_type,
                "site_url": "https://ntest.uzbmb.uz/login",
                "is_active": True,
            },
        )
        self.stdout.write(
            f"  Demo: {region.name} / {zone.name}, "
            f"{computers} ta yangi kompyuter, 1 imtihon turi, 1 imtihon"
        )
