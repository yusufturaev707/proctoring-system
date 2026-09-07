from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import SoftDeleteModel, TimeStampedModel
from apps.common.utils.validators import inventory_code_validator, mac_address_validator


class Camera(SoftDeleteModel):
    """IP kamera. Zonani kuzatadi (kompyuter kamerasidan alohida)."""

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
    login = models.CharField(max_length=120, blank=True, default="")
    # Parol OCHIQ SAQLANMAYDI — AES-GCM bilan shifrlanadi (services.py).
    password_encrypted = models.TextField(blank=True, default="")

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.OFFLINE, db_index=True
    )
    last_seen_at = models.DateTimeField(null=True, blank=True)
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
    # Ikkalasi ham `unique=True` EMAS — pastdagi shartli cheklovlarga qarang.
    inventory_code = models.CharField(
        _("Inventar kodi"), max_length=50, validators=[inventory_code_validator]
    )
    ip_address = models.GenericIPAddressField(_("IP manzil"))
    mac_address = models.CharField(
        _("MAC manzil"), max_length=17, validators=[mac_address_validator]
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

    def __str__(self):
        return f"{self.inventory_code} — {self.mac_address}"

    class Meta:
        db_table = "computer"
        verbose_name = _("Kompyuter")
        verbose_name_plural = _("Kompyuterlar")
        ordering = ["zone", "inventory_code"]
        constraints = [
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
            models.UniqueConstraint(
                fields=["mac_address"],
                condition=models.Q(deleted_at__isnull=True),
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
