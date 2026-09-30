from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import SoftDeleteModel, TimeStampedModel
from apps.common.utils.validators import (
    inventory_code_validator,
    mac_address_validator,
    machine_uuid_validator,
)


class Camera(SoftDeleteModel):
    """IP kamera. Zonani kuzatadi (kompyuter kamerasidan alohida)."""

    class Vendor(models.TextChoices):
        HIKVISION = "hikvision", _("Hikvision")
        DAHUA = "dahua", _("Dahua")
        ONVIF = "onvif", _("ONVIF (umumiy)")
        GENERIC = "generic", _("Boshqa")

    class Transport(models.TextChoices):
        TCP = "tcp", _("TCP")
        UDP = "udp", _("UDP")

    class Status(models.TextChoices):
        ONLINE = "online", _("Online")
        OFFLINE = "offline", _("Offline")
        ERROR = "error", _("Xatolik")

    name = models.CharField(_("Nom"), max_length=120)
    zone = models.ForeignKey(
        "regions.Zone", on_delete=models.PROTECT, related_name="cameras"
    )
    ip_address = models.GenericIPAddressField(_("IP manzil"))
    # `unique=True` EMAS — pastdagi shartli cheklovga qarang.
    mac_address = models.CharField(
        _("MAC manzil"), max_length=17, validators=[mac_address_validator]
    )
    rtsp_path = models.CharField(max_length=255, blank=True, default="/Streaming/Channels/101")

    # --- Ulanish parametrlari ---
    #
    # Ilgari RTSP URL faqat `ip_address + rtsp_path` dan yig'ilardi va bu
    # bitta vendor (Hikvision, 554-port, TCP) uchun ishlardi. Boshqa
    # kamera qo'yilgan zahoti yo'l ham, port ham, transport ham
    # boshqacha bo'ladi va ularni `rtsp_path` ichiga tiqib bo'lmaydi.
    #
    # `vendor` URL YIG'ISHDA qatnashmaydi — u faqat administrator uchun
    # belgi va client tomonda kelajakdagi vendor-maxsus xatti-harakat
    # (masalan ONVIF discovery) uchun ilgak. Yo'lni har doim `rtsp_path`
    # belgilaydi: "vendor bo'yicha yo'lni taxmin qilish" modeli birinchi
    # nostandart proshivkada buziladi.
    vendor = models.CharField(
        _("Ishlab chiqaruvchi"), max_length=32, choices=Vendor.choices, default=Vendor.HIKVISION
    )
    port = models.PositiveIntegerField(_("RTSP port"), default=554)
    # TCP standart: UDP'da paket yo'qolishi kadrni buzadi va dalil
    # sifatidagi qiymatini yo'qotadi. UDP tanlovi LAN'dagi yuqori
    # bitrate oqimlar uchun qoldirilgan.
    transport = models.CharField(
        _("Transport"), max_length=8, choices=Transport.choices, default=Transport.TCP
    )

    login = models.CharField(max_length=120, blank=True, default="")
    # Parol OCHIQ SAQLANMAYDI — AES-GCM bilan shifrlanadi (services.py).
    password_encrypted = models.TextField(blank=True, default="")

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.OFFLINE, db_index=True
    )
    #: Oxirgi marta ONLINE bo'lgan payt.
    last_seen_at = models.DateTimeField(null=True, blank=True)
    #: Holat SABABI - odam tilida ("Login yoki parol noto'g'ri").
    #: `error` holatida hal qiluvchi: "xatolik" so'zining o'zi
    #: administratorga nimani tuzatishni aytmaydi.
    status_message = models.CharField(max_length=200, blank=True, default="")
    #: Oxirgi TEKSHIRUV payti (natijasidan qat'i nazar). `last_seen_at`
    #: dan farqi: offline kamerada ham "holat qanchalik yangi?" degan
    #: savolga javob beradi - tekshiruv umuman ishlamayotganini shu
    #: yerdan bilish mumkin.
    last_checked_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} — {self.ip_address}"

    class Meta:
        db_table = "camera"
        verbose_name = _("IP kamera")
        verbose_name_plural = _("IP kameralar")
        ordering = ["zone", "name"]
        constraints = [
            # Shartli: o'chirilgan kamera MAC manzilni band qilib qolmaydi.
            # Oddiy `unique=True` bo'lsa, kamerani almashtirgach eskisining
            # MAC'ini yangisiga berib bo'lmasdi.
            models.UniqueConstraint(
                fields=["mac_address"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_camera_mac",
            ),
        ]
        indexes = [
            models.Index(fields=["zone", "status"], name="idx_camera_zone_status"),
        ]


class Computer(SoftDeleteModel):
    """Imtihon kompyuteri."""

    class Status(models.TextChoices):
        OFFLINE = "offline", _("Offline")
        ONLINE = "online", _("Online")
        IN_EXAM = "in_exam", _("Imtihonda")
        BLOCKED = "blocked", _("Bloklangan")

    zone = models.ForeignKey(
        "regions.Zone", on_delete=models.PROTECT, related_name="computers"
    )
    #: Xonadagi TARTIB RAQAMI — stolga yopishtirilgan raqam.
    #
    # `inventory_code` DAN BOSHQA SAVOLGA javob beradi va ikkalasi
    # ham kerak: inventar kodi buxgalteriya uchun ("INV-2024-0123",
    # mashina almashtirilsa o'zgaradi), raqam esa XONADAGI O'RIN
    # uchun ("12-kompyuter") va u mashina almashtirilganda ham
    # o'sha joyda qoladi.
    #
    # Amalda operator va talabgor aynan shu raqam bilan ishlaydi:
    # "12-kompyuterga o'ting", "15-kompyuterda kamera ishlamayapti".
    # Inventar kodini ular hech qachon aytmaydi - u stikerning
    # orqasida yoki umuman ko'rinmaydi.
    #
    # IXTIYORIY: hamma markazda ham mashinalar raqamlanmagan va
    # majburiy qilish mavjud yozuvlarni migratsiyada to'ldirishga
    # majbur qilardi - to'g'ri javobni esa faqat o'sha markaz
    # biladi.
    number = models.PositiveSmallIntegerField(
        _("Raqami"), null=True, blank=True, db_index=True
    )
    # Ikkalasi ham `unique=True` EMAS — pastdagi shartli cheklovlarga qarang.
    inventory_code = models.CharField(
        _("Inventar kodi"), max_length=50, validators=[inventory_code_validator]
    )
    # IXTIYORIY: Excel importida (`computer_import.py`) IP yo'q - DHCP
    # tarmog'ida u o'zgarib turadi va mashinani MAC belgilaydi. Ilgari
    # majburiy edi va avtomatik inventarizatsiya "0.0.0.0" qo'yardi,
    # `unique_computer_zone_ip` esa binoda bittadan ortiq shunday
    # mashinaga yo'l qo'ymasdi. NULL bu cheklovga tushmaydi.
    ip_address = models.GenericIPAddressField(_("IP manzil"), null=True, blank=True)
    #: MASHINA IDENTIFIKATORI - (machine_uuid, mac_address) JUFTLIGI.
    #: UUID - ona platadagi SMBIOS UUID (`wmic csproduct get uuid` bilan
    #: bir xil satr, katta harf). U TAKRORLANADI: arzon platalarda bir
    #: partiyada bir xil, shuning uchun o'zi unikal emas (juftlik -
    #: `unique_computer_uuid_mac`, qidiruv - `services.find_computer_by_identity`).
    #
    # Ilgari bu rolni MAC bajarardi va u amalda o'zgaradi: tarmoq kartasi
    # almashtiriladi, USB/Wi-Fi adapter ulanadi, marshrut boshqa adapterga
    # o'tadi, virtual adapter "asosiy" bo'lib qoladi - har safar ishlab
    # turgan mashina "ro'yxatda yo'q" bo'lib qolardi. UUID ona plata
    # bilan birga yashaydi va OS qayta o'rnatilganda ham o'zgarmaydi.
    #
    # NULL - hali ma'lum emas (UUID'dan oldingi yozuvlar). Bunday qator
    # birinchi handshake'da BIR MARTA bog'lanadi, faqat client aytgan MAC
    # administrator kiritgan MAC bilan mos kelsa (`verify_machine`), yoki
    # Excel importida MAC bo'yicha to'ldiriladi. Bo'sh satr emas NULL:
    # shartli unikal cheklov NULL'larni solishtirmaydi.
    machine_uuid = models.CharField(
        _("Machine UUID"), max_length=36, null=True, blank=True,
        validators=[machine_uuid_validator],
    )
    #: Juftlikning ikkinchi yarmi. Yangi va tahrirlanayotgan yozuvda
    #: MAJBURIY (panel serializer'i, Excel import, Django admin) va doim
    #: `normalize_mac` shaklida. Modelda `blank=True` faqat MAC'siz ESKI
    #: yozuvlar uchun (o'tish davri: ular faqat UUID bilan, shu UUID'li
    #: yagona yozuv bo'lsa tanladi - `find_computer_by_identity`).
    #: Client uni HECH QACHON yozmaydi.
    mac_address = models.CharField(
        _("MAC manzil"), max_length=17, blank=True, default="",
        validators=[mac_address_validator],
    )
    info_pc = models.JSONField(_("Qurilma ma'lumotlari"), blank=True, null=True)
    cameras = models.ManyToManyField(
        "devices.Camera", related_name="computers", blank=True
    )

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.OFFLINE, db_index=True
    )
    last_seen_at = models.DateTimeField(null=True, blank=True, db_index=True)
    is_active = models.BooleanField(default=True)

    @property
    def label(self) -> str:
        """
        Ekranda ko'rsatiladigan nom: "№12 · INV-001".

        Raqam OLDINDA, chunki odam mashinani aynan shu bo'yicha
        qidiradi. Raqam yo'q bo'lsa faqat inventar kodi qoladi -
        "№None" yozuvi hech narsani anglatmasdi.
        """
        if self.number:
            return "№{} · {}".format(self.number, self.inventory_code)
        return self.inventory_code

    def __str__(self):
        return f"{self.label} — {self.machine_uuid or self.mac_address or '-'}"

    class Meta:
        db_table = "computer"
        verbose_name = _("Kompyuter")
        verbose_name_plural = _("Kompyuterlar")
        # RAQAM BO'YICHA, keyin inventar kodi. Operator ro'yxatni
        # xonadagi tartibda ko'radi; raqamsiz mashinalar oxirida
        # qoladi (Postgres `NULLS LAST`) - ular odatda yangi
        # qo'shilgan va hali joylashtirilmagan.
        ordering = ["zone", "number", "inventory_code"]
        constraints = [
            # Raqam faqat BINO ichida unikal - "12-kompyuter" har
            # binoda bor va bu normal holat. Ikkita "12" bitta
            # binoda esa raqamning butun ma'nosini yo'qotardi:
            # operator qaysi biriga borishni bilmasdi.
            models.UniqueConstraint(
                fields=["zone", "number"],
                condition=models.Q(deleted_at__isnull=True, number__isnull=False),
                name="unique_computer_zone_number",
            ),
            # IP faqat zona ichida unikal — turli binolarda 192.168.1.10 normal holat.
            models.UniqueConstraint(
                fields=["zone", "ip_address"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_computer_zone_ip",
            ),
            # Shartli: hisobdan chiqarilgan kompyuter inventar kodini va MAC
            # manzilini abadiy band qilib qolmaydi. Eski mashina o'rniga
            # yangisini o'sha kod bilan qo'yish odatiy hol.
            models.UniqueConstraint(
                fields=["inventory_code"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_computer_inventory_code",
            ),
            # IDENTIFIKATOR - (UUID, MAC) juftligi. Faqat UUID unikal
            # EMAS: bir partiyadagi platalarda u bir xil va bunday ikkinchi
            # mashinani qo'shib bo'lmasdi. `unique_computer_mac` bilan
            # birga u ortiqcha ko'rinadi, lekin juftlik qoidasini BAZADA
            # aniq yozadi - MAC cheklovi o'zgarsa ham juftlik himoyada
            # qoladi. Hisobdan chiqarilgan mashina juftlikni band qilmaydi.
            models.UniqueConstraint(
                fields=["machine_uuid", "mac_address"],
                condition=(
                    models.Q(deleted_at__isnull=True, machine_uuid__isnull=False)
                    & ~models.Q(mac_address="")
                ),
                name="unique_computer_uuid_mac",
            ),
            # MAC tizim bo'ylab unikal (zavod manzili). Bo'sh qiymat -
            # faqat MAC'siz eski yozuvlar - bir-biriga "to'qnashmaydi".
            models.UniqueConstraint(
                fields=["mac_address"],
                condition=models.Q(deleted_at__isnull=True) & ~models.Q(mac_address=""),
                name="unique_computer_mac",
            ),
        ]
        indexes = [
            models.Index(fields=["zone", "status"], name="idx_computer_zone_status"),
            models.Index(fields=["status", "last_seen_at"], name="idx_computer_heartbeat"),
        ]


class DeviceToken(TimeStampedModel):
    """
    Desktop client o'rnatilgan kompyuterning identifikatori.

    Bu KREDENSIAL EMAS. Autentifikatsiyani xodim JWT'si bajaradi
    (`proctoring/authentication.py` ga qarang); `device_id` esa sessiya
    qaysi mashinada va qaysi binoda o'tayotganini belgilaydi — dashboard,
    viloyat bo'yicha ajratish va bayonnoma shunga tayanadi.

    Ilgari bu yerda HMAC siri bor edi va har bir so'rov imzolanardi. U
    olib tashlandi: imzo "qaysi kompyuter" ni isbotlardi, lekin "kim" ni
    emas — chetlashtirish va shaxs tasdig'i esa aynan ism-sharifga
    bog'lanishi kerak bo'lgan qarorlar.
    """

    class Status(models.TextChoices):
        PENDING = "pending", _("Tasdiqlanmagan")
        ACTIVE = "active", _("Faol")
        REVOKED = "revoked", _("Bekor qilingan")

    computer = models.ForeignKey(
        "devices.Computer", on_delete=models.CASCADE, related_name="device_tokens"
    )
    device_id = models.CharField(_("Qurilma ID"), max_length=64, unique=True)
    hardware_fingerprint = models.CharField(
        max_length=128, blank=True, default="", db_index=True
    )

    # --- Apparat profili (proktorlik AI uchun) ---
    #
    # CPU/RAM/CUDA tafsiloti `Computer.info_pc` (JSON) da yotadi va u
    # yerda qolishi to'g'ri: u mashinaning xususiyati, client
    # nusxasiniki emas. Bu yerda esa faqat ikkita QIDIRILADIGAN qiymat
    # bor — administrator "qaysi mashinalar CPU rejimida ishlayapti?"
    # degan savolga JSON ichini titmasdan javob olishi kerak, chunki
    # aynan o'sha mashinalarda kuzatuv sifati past bo'ladi.
    gpu_name = models.CharField(_("GPU"), max_length=120, blank=True, default="")
    performance_profile = models.CharField(
        _("Unumdorlik profili"), max_length=8, blank=True, default="", db_index=True,
        help_text=_("high / medium / low / cpu / minimal — client o'zi aniqlaydi"),
    )

    app_version = models.CharField(max_length=32, blank=True, default="")
    app_hash = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text=_("Client binary SHA-256 — o'zgargani anomaliya sifatida belgilanadi"),
    )

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    last_used_at = models.DateTimeField(null=True, blank=True)
    #: So'rovning MANBA manzili (server o'zi ko'rgan).
    last_ip = models.GenericIPAddressField(null=True, blank=True)
    #: Client O'ZI aniqlagan tashqi manzil (ipify va h.k.).
    #
    # `last_ip` dan farqi: server bino ichida tursa, u client'ning LAN
    # manzilini ko'radi va binoning haqiqiy tashqi manzilini bilmaydi.
    # Bu maydon administratorga "bu bino qaysi IP bilan chiqadi" degan
    # savolga javob beradi - `AllowedPublicIp` ni to'g'ri to'ldirish uchun.
    #
    # DIQQAT: bu qiymat client'dan keladi, ya'ni ISHONCHSIZ. U hech
    # qachon kirish ruxsatini hal qilmaydi (`is_ip_allowed` faqat server
    # ko'rgan manzil bilan ishlaydi) - u ma'lumot va diagnostika uchun.
    reported_public_ip = models.GenericIPAddressField(null=True, blank=True)
    #: Client O'ZI aniqlagan LOKAL (LAN) manzil.
    #
    # NIMA UCHUN KERAK: panelda "bu sessiya qaysi mashinada o'tdi"
    # degan savolga javob beradigan yagona aniq manzil shu. Server
    # ko'rgan manzil (`last_ip`) NAT ortidagi butun bino uchun bitta
    # bo'lishi mumkin, dev'da esa u umuman `127.0.0.1` - ya'ni
    # bayonnomada foydasiz qiymat qolardi.
    #
    # ISHONCHSIZ, `reported_public_ip` bilan bir xil sababdan: uni
    # client yuboradi. Hech qanday ruxsat qarori bunga tayanmaydi -
    # u faqat ma'lumot va diagnostika uchun.
    reported_lan_ip = models.GenericIPAddressField(null=True, blank=True)
    #: Client O'ZI o'lchagan Machine UUID - oxirgi handshake'dagi.
    #
    # `Computer.machine_uuid` dan farqi: u administrator tasdiqlagan
    # qiymat, bu esa "dastur hozir QAYSI ona platada ishlayapti". Panelda
    # ikkalasi yonma-yon ko'rinadi: `mismatch`/`not_found` holatida
    # administrator to'g'ri qiymatni shu yerdan oladi (mashinaga borib
    # `wmic` yozish shart emas). ISHONCHSIZ - ruxsat qarori bunga
    # tayanmaydi, `verify_machine` uni kompyuter yozuvi bilan solishtiradi.
    reported_machine_uuid = models.CharField(max_length=36, blank=True, default="")
    #: Client aytgan MAC (marshrut tanlagan adapter) - oxirgi handshake'dagi.
    #
    # Juftlik tekshiruvi (`find_computer_by_identity`) MAC'ga tayanadi:
    # administrator qaysi mashinalar `not_found` olayotganini shu qiymat
    # va `Computer.mac_address` farqidan ko'radi (`audit_machine_identity`,
    # panel). ISHONCHSIZ - qaror handshake'dagi qiymat bilan qilinadi,
    # bu faqat diagnostika. Client `Computer.mac_address` ga HECH QACHON
    # yozmaydi.
    reported_mac = models.CharField(max_length=17, blank=True, default="")
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.CharField(max_length=255, blank=True, default="")

    @property
    def is_usable(self) -> bool:
        return self.status == self.Status.ACTIVE

    def __str__(self):
        return f"{self.device_id} ({self.status})"

    class Meta:
        db_table = "device_token"
        verbose_name = _("Qurilma tokeni")
        verbose_name_plural = _("Qurilma tokenlari")
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["status", "last_used_at"], name="idx_device_status_used"),
        ]
