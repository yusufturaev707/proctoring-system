"""
BBA Console ma'lumotining MAHALLIY nusxasi.

Nusxa, chunki: (1) panel ro'yxati 10 000 kompyuterni Console'ga har sahifada
borib emas, o'z bazasidan filtrlab/saralab beradi; (2) Console vaqtincha
ishlamasa ham oxirgi ma'lumot ko'rinadi; (3) Console limiti 300 so'rov/daqiqa
— har panel ochilishi unga tushsa limit tugardi.

Qatorlar O'CHIRILMAYDI: Console ro'yxatida ko'rinmay qolgan kompyuter
(huquq olib qo'yilgan, vaqtincha) `is_visible=False` + `missing_since` oladi.
"""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import TimeStampedModel


class BbaRegion(TimeStampedModel):
    console_id = models.UUIDField(unique=True)
    name = models.CharField(_("Nom"), max_length=255)
    code = models.CharField(max_length=64, blank=True, default="")
    subnet = models.CharField(max_length=64, blank=True, default="")
    #: Bizning viloyat. Viloyat xodimi FAQAT shu orqali bog'langan Console
    #: hududlarini ko'radi; bog'lanmagani — faqat respublika darajasida.
    #: Avtomatik (nom bo'yicha) bog'lanMAYDI: nomlar ikki tizimda har xil
    #: yozilgan va xato bog'lash boshqa viloyat kompyuterlarini ochardi.
    region = models.ForeignKey(
        "regions.Region", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="bba_regions", verbose_name=_("Viloyat"),
    )
    room_count = models.PositiveIntegerField(default=0)
    device_count = models.PositiveIntegerField(default=0)
    is_visible = models.BooleanField(default=True)
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bba_region"
        ordering = ["name"]
        verbose_name = _("BBA hududi")
        verbose_name_plural = _("BBA hududlari")

    def __str__(self):
        return self.name


class BbaRoom(TimeStampedModel):
    console_id = models.UUIDField(unique=True)
    bba_region = models.ForeignKey(
        BbaRegion, on_delete=models.CASCADE, null=True, blank=True, related_name="rooms"
    )
    name = models.CharField(_("Nom"), max_length=255)
    code = models.CharField(max_length=64, blank=True, default="")
    device_count = models.PositiveIntegerField(default=0)
    is_visible = models.BooleanField(default=True)
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bba_room"
        ordering = ["bba_region__name", "name"]
        verbose_name = _("BBA xonasi")
        verbose_name_plural = _("BBA xonalari")

    def __str__(self):
        return self.name


class BbaDevice(TimeStampedModel):
    class Status(models.TextChoices):
        #: Agent hozir ulangan — kompyuter YONIQ.
        ONLINE = "online", _("Yoniq")
        #: Normal o'chirilgan (Windows'dan "Shut down").
        OFFLINE_GRACEFUL = "offline_graceful", _("O'chirilgan")
        #: Aloqa kutilmaganda uzilgan: tok o'chdi, kabel sug'urildi, qotib qoldi.
        OFFLINE_UNEXPECTED = "offline_unexpected", _("Aloqa uzilgan")
        UNKNOWN = "unknown", _("Noma'lum")

    console_id = models.UUIDField(unique=True)
    room = models.ForeignKey(
        BbaRoom, on_delete=models.SET_NULL, null=True, blank=True, related_name="devices"
    )
    #: Xonadan ko'chirilgan (filtr va viloyat chegarasi bitta JOIN'siz).
    bba_region = models.ForeignKey(
        BbaRegion, on_delete=models.SET_NULL, null=True, blank=True, related_name="devices"
    )
    #: Console'dagi nomi (`BBA-110-3`) va Windows nomi.
    hostname_code = models.CharField(max_length=255, blank=True, default="", db_index=True)
    hostname = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.UNKNOWN, db_index=True
    )
    #: Holat BIZ ko'rgan paytda o'zgargan vaqt (Console'niki emas).
    status_changed_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    enrolled_at = models.DateTimeField(null=True, blank=True)
    #: `null` emas — Console'dan chiqarilgan: unga test ruxsat etilmaydi.
    revoked_at = models.DateTimeField(null=True, blank=True)
    agent_version = models.CharField(max_length=32, blank=True, default="")
    test_mode_enabled = models.BooleanField(default=False)
    #: Oxirgi to'liq ro'yxatda bormi. Har so'rovda yangilanadigan "synced_at"
    #: ATAYLAB yo'q: u har 15 s da 10 000 qatorni yozardi — oxirgi
    #: sinxronizatsiya vaqti umumiy (`services.STATE_KEY`).
    is_visible = models.BooleanField(default=True, db_index=True)
    missing_since = models.DateTimeField(null=True, blank=True)

    # --- Identifikatorlar (inventory'dan, `identity.extract`) ---
    system_uuid = models.CharField(max_length=36, blank=True, default="", db_index=True)
    #: Jismoniy adapterlar MAC'lari, kanonik shaklda.
    macs = models.JSONField(default=list, blank=True)
    primary_mac = models.CharField(max_length=17, blank=True, default="")
    #: `primary_mac` adapterining IPv4 manzili (DHCP'da o'zgaradi — faqat
    #: ko'rsatish va import taklifi, identifikator EMAS).
    primary_ip = models.GenericIPAddressField(null=True, blank=True)
    baseboard_serial = models.CharField(max_length=128, blank=True, default="")
    tpm_ek_hash = models.CharField(max_length=128, blank=True, default="")
    machine_guid = models.CharField(max_length=64, blank=True, default="")

    # --- Inventory (oxirgi snapshot to'liq) ---
    inventory = models.JSONField(null=True, blank=True)
    inventory_changes = models.JSONField(null=True, blank=True)
    #: Agent ma'lumotni olgan payt (`CapturedAt`).
    inventory_captured_at = models.DateTimeField(null=True, blank=True)
    #: Biz Console'dan olgan payt (snapshot `null` bo'lsa ham).
    inventory_fetched_at = models.DateTimeField(null=True, blank=True, db_index=True)
    inventory_error = models.CharField(max_length=300, blank=True, default="")

    #: Bizning kompyuter yozuvi — (UUID, MAC) juftligi bo'yicha
    #: (`services.link_computers`, qoida `devices.services.match_identity`).
    computer = models.ForeignKey(
        "devices.Computer", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="bba_devices",
    )

    class Meta:
        db_table = "bba_device"
        ordering = ["hostname_code", "hostname"]
        verbose_name = _("BBA kompyuteri")
        verbose_name_plural = _("BBA kompyuterlari")
        indexes = [
            models.Index(fields=["bba_region", "status"], name="idx_bba_device_region_status"),
            models.Index(fields=["room", "status"], name="idx_bba_device_room_status"),
        ]

    def __str__(self):
        return self.hostname_code or self.hostname or str(self.console_id)

    @property
    def name(self) -> str:
        return self.hostname_code or self.hostname or str(self.console_id)[:8]


class BbaJob(TimeStampedModel):
    """
    Panelimizdan yuborilgan job — "KIM yubordi" savoliga javob.

    Console o'z tarixini yuritadi (`GET /jobs`), lekin unda yuboruvchi —
    integratsiya hisobi; panelning qaysi xodimi bosgani faqat shu yerda.
    Holat Console'dan yangilanadi (`services.refresh_jobs`).
    """

    class Status(models.TextChoices):
        PENDING = "pending", _("Navbatda")
        SENT = "sent", _("Yuborildi")
        RECEIVED = "received", _("Qabul qilindi")
        RUNNING = "running", _("Bajarilmoqda")
        DONE = "done", _("Bajarildi")
        FAILED = "failed", _("Xato")
        TIMEOUT = "timeout", _("Vaqt tugadi")
        CANCELLED = "cancelled", _("Bekor qilindi")
        #: Console job'ni yaratmadi (bulk javobida shu kompyuterga xato).
        ERROR = "error", _("Yuborilmadi")

    TERMINAL = frozenset({"done", "failed", "timeout", "cancelled", "error"})

    device = models.ForeignKey(BbaDevice, on_delete=models.CASCADE, related_name="jobs")
    console_job_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    bulk_operation_id = models.CharField(max_length=64, blank=True, default="")
    job_type = models.CharField(max_length=64, db_index=True)
    params = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    result = models.JSONField(null=True, blank=True)
    error = models.CharField(max_length=300, blank=True, default="")
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="bba_jobs",
    )
    issued_by_username = models.CharField(max_length=150, blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bba_job"
        ordering = ["-created_at", "-id"]
        verbose_name = _("BBA job")
        verbose_name_plural = _("BBA job'lar")

    def __str__(self):
        return f"{self.job_type} → {self.device}"

    @property
    def is_terminal(self) -> bool:
        return self.status in self.TERMINAL
