from django.contrib.auth.hashers import check_password, make_password
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _

from apps.common.models import SoftDeleteModel, TimeStampedModel


class AllowedPublicIp(TimeStampedModel):
    """
    Kirishga ruxsat etilgan tashqi IP'lar.

    Client uydan emas, aynan imtihon markazidan ulanayotganini tekshiradi —
    bu JSHSHIR qidiruvi hujum yuzasini keskin toraytiradi.
    """

    zone = models.ForeignKey(
        "regions.Zone", on_delete=models.CASCADE, blank=True, null=True, related_name="allowed_ips"
    )
    name = models.CharField(max_length=255, blank=True, default="")
    ip_address = models.GenericIPAddressField(unique=True)
    is_active = models.BooleanField(default=True, db_index=True)

    def __str__(self):
        return f"{self.zone or 'global'} — {self.ip_address}"

    class Meta:
        verbose_name = _("Ruxsat etilgan IP")
        verbose_name_plural = _("Ruxsat etilgan IP'lar")
        db_table = "allowed_public_ip"
        ordering = ["ip_address"]


class ClientExitPassword(TimeStampedModel):
    """
    Desktop client'dan chiqish paroli — HAR BIR VILOYAT uchun alohida.

    Nega viloyat bo'yicha va nega umuman kerak:

    Kiosk rejimida dastur o'zini yopishga ruxsat bermaydi. Xodim tizimga
    kirgan bo'lsa, u O'Z paroli bilan chiqadi va audit iziga ismi
    yoziladi — bu eng yaxshi holat. Lekin dastur login sahifasida
    turganda hech qanday xodim yo'q va o'sha paytda mashinani qonuniy
    yopishning yo'li qolmaydi: yagona chora — quvvatdan uzish.

    Shu bo'shliqni yopadi. Yagona umumiy parol o'rniga viloyat bo'yicha
    ajratilgani ataylab: 14 ta hududda bitta parol ishlatilsa, uning
    bir markazdan sizib chiqishi butun respublikani ochib qo'yardi.
    Viloyat paroli sizsa — zarar o'sha viloyat bilan cheklanadi va uni
    boshqalarga tegmasdan almashtirish mumkin.

    PAROL HASH KO'RINISHIDA saqlanadi (`make_password`), shifrlangan
    holda emas. Server uni hech qayerga uzatmaydi — faqat solishtiradi,
    demak teskari o'girish qobiliyati keraksiz xavf bo'lardi: baza
    nusxasi qo'lga tushsa, barcha viloyatlarning paroli ochiq bo'lardi.
    Administrator parolni KO'RA olmaydi, faqat yangisini o'rnata oladi.
    """

    #: `OneToOne` — "har bir viloyat uchun bitta parol" qoidasi DB
    #: darajasida kafolatlanadi, dastur mantig'iga tayanmasdan.
    region = models.OneToOneField(
        "regions.Region",
        verbose_name=_("Viloyat"),
        on_delete=models.CASCADE,
        related_name="exit_password",
    )
    name = models.CharField(_("Izoh"), max_length=255, blank=True, default="")
    #: Hash (`pbkdf2_sha256$...`), ochiq parol EMAS.
    password = models.CharField(_("Parol"), max_length=255)
    is_active = models.BooleanField(_("Faol"), default=True, db_index=True)

    def set_password(self, raw: str) -> None:
        self.password = make_password(raw)

    def check_password(self, raw: str) -> bool:
        if not raw or not self.password:
            return False
        return check_password(raw, self.password)

    def __str__(self):
        return f"{self.region} — chiqish paroli"

    class Meta:
        verbose_name = _("Chiqish paroli")
        verbose_name_plural = _("Chiqish parollari")
        db_table = "client_exit_password"
        ordering = ["region__dtm_id"]


# --------------------------------------------------------------------------
# YOLO obyekt aniqlash
# --------------------------------------------------------------------------
class ModelVersion(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=100, unique=True)
    file_key = models.CharField(max_length=500, blank=True, default="")
    is_active = models.BooleanField(default=False)

    def __str__(self):
        return str(self.name)

    class Meta:
        db_table = "model_version"
        verbose_name = _("Model versiyasi")
        verbose_name_plural = _("Model versiyalari")
        ordering = ["id"]


class CocoObjectGroup(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return str(self.name)

    class Meta:
        db_table = "coco_object_group"
        verbose_name = _("COCO obyekt guruhi")
        verbose_name_plural = _("COCO obyekt guruhlari")
        ordering = ["id"]


class CocoObject(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    code = models.PositiveSmallIntegerField(unique=True)
    group = models.ForeignKey(
        "controls.CocoObjectGroup",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        # `related_name="objects"` QILMANG — u standart menejerni bosib qoladi
        # va `CocoObjectGroup.objects.all()` ishlamay qoladi.
        related_name="coco_objects",
    )
    # Aniqlanganda qaysi jiddiylik darajasidagi hodisa yaratiladi.
    severity = models.PositiveSmallIntegerField(default=2)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return str(self.name)

    class Meta:
        db_table = "coco_object"
        verbose_name = _("COCO obyekt")
        verbose_name_plural = _("COCO obyektlar")
        ordering = ["code"]


# --------------------------------------------------------------------------
# RDP / klaviatura
# --------------------------------------------------------------------------
class RdpObject(TimeStampedModel):
    """Aniqlanishi kerak bo'lgan masofaviy boshqaruv dasturi (AnyDesk, TeamViewer...)."""

    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=100, unique=True)
    process_names = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return str(self.name)

    class Meta:
        db_table = "rdp"
        verbose_name = _("RDP dastur")
        verbose_name_plural = _("RDP dasturlar")
        ordering = ["id"]


class HotKeyboardKey(TimeStampedModel):
    """Bloklanishi kerak bo'lgan klaviatura kombinatsiyasi."""

    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return str(self.name)

    class Meta:
        db_table = "hot_keyboard_key"
        verbose_name = _("Tezkor tugma")
        verbose_name_plural = _("Tezkor tugmalar")
        ordering = ["id"]


# --------------------------------------------------------------------------
# Sozlamalar
# --------------------------------------------------------------------------
class Setting(SoftDeleteModel):
    """
    Client xulq-atvori profili.

    Sozlamalar soni CHEKLANMAGAN — har bir imtihon o'z profiliga ega
    bo'lishi mumkin (`Exam.setting`). Masalan matematika uchun kalkulyator
    ruxsat etilib, chet tili uchun quloqchin bloklanadi.

    `is_active` esa boshqa narsa: bu GLOBAL STANDART, ya'ni o'z sozlamasi
    biriktirilmagan imtihonlar uchun zaxira. Shunday sozlama faqat bitta
    bo'ladi (`unique_active_setting`).

    Client har bir handshake'da shu profilni oladi, shuning uchun u
    keshlanadi — aks holda 10 000 client har 30 soniyada DB'ni o'qiydi.
    """

    # `unique=True` EMAS — pastdagi shartli cheklovga qarang.
    name = models.CharField(_("Nom"), max_length=100)
    is_active = models.BooleanField(_("Global standart"), default=False, db_index=True)

    # --- FaceID ---
    is_faceid_student = models.BooleanField(_("Talabgor yuz tekshiruvi"), default=True)
    is_faceid_exam = models.BooleanField(_("Test davomida yuz tekshiruvi"), default=True)
    faceid_interval = models.PositiveSmallIntegerField(_("Interval (s)"), default=10)
    faceid_max_fail = models.PositiveSmallIntegerField(_("Maks. muvaffaqiyatsiz urinish"), default=3)
    warning_timeout = models.PositiveSmallIntegerField(_("Ogohlantirish kutish vaqti (s)"), default=5)
    faceid_min_score_student = models.PositiveSmallIntegerField(_("Min ball (talabgor)"), default=70)
    faceid_min_score_exam = models.PositiveSmallIntegerField(_("Min ball (test)"), default=70)
    # Client hisoblagan embedding'ni serverda tasodifiy qayta tekshirish ulushi.
    # Clientga to'liq ishonib bo'lmaydi — bu statistik nazorat.
    faceid_audit_rate = models.FloatField(_("Server auditi ulushi"), default=0.05)

    # --- Qurilma ---
    is_screen_record = models.BooleanField(_("Ekranni yozish"), default=False)
    is_detect_monitor = models.BooleanField(_("Monitor tekshiruvi"), default=True)
    is_detect_camera = models.BooleanField(_("Kamera tekshiruvi"), default=True)
    screenshot_interval = models.PositiveSmallIntegerField(_("Skrinshot intervali (s)"), default=10)
    screenshot_quality = models.PositiveSmallIntegerField(_("Skrinshot sifati"), default=65)
    screenshot_max_width = models.PositiveSmallIntegerField(_("Maks. kenglik"), default=960)
    # Kadr oldingisidan sezilarli farq qilmasa — yuborilmaydi.
    # Talabgor asosan qimirlamaydi, shuning uchun bu trafikni ~10x kamaytiradi.
    screenshot_dedup_threshold = models.PositiveSmallIntegerField(_("Dedup chegarasi"), default=6)

    # --- YOLO ---
    is_enable_detect = models.BooleanField(_("Obyekt aniqlash"), default=False)
    detect_model = models.ForeignKey(
        "controls.ModelVersion", on_delete=models.SET_NULL, blank=True, null=True
    )
    detect_classes = models.ManyToManyField(
        "controls.CocoObject", related_name="settings", blank=True
    )
    detect_confidence = models.FloatField(_("Ishonch chegarasi"), default=0.5)
    detect_frame_skip = models.PositiveSmallIntegerField(_("Kadr o'tkazish"), default=20)

    # --- RDP ---
    is_enable_rdp_detect = models.BooleanField(_("RDP aniqlash"), default=True)
    rdp_objects = models.ManyToManyField(
        "controls.RdpObject", related_name="settings", blank=True
    )
    hotkeys = models.ManyToManyField(
        "controls.HotKeyboardKey", related_name="settings", blank=True
    )

    # --- Texnik muammolar ---
    is_enable_check_tp = models.BooleanField(_("Texnik muammoni tekshirish"), default=True)

    # --- Tarmoq ---
    heartbeat_interval = models.PositiveSmallIntegerField(_("Heartbeat intervali (s)"), default=30)
    event_batch_interval = models.PositiveSmallIntegerField(_("Event batch intervali (s)"), default=5)
    # Internet uzilganda client shuncha eventni lokal SQLite'da saqlaydi.
    offline_buffer_size = models.PositiveIntegerField(_("Offline buffer hajmi"), default=5000)

    def save(self, *args, **kwargs):
        # Global standart har doim bitta bo'lishini kafolatlaymiz.
        if self.is_active:
            with transaction.atomic():
                Setting.objects.filter(is_active=True).exclude(pk=self.pk).update(
                    is_active=False
                )
                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)

        from apps.controls.services import invalidate_setting_cache

        invalidate_setting_cache(self)

    def __str__(self):
        return f"{self.name}{' (faol)' if self.is_active else ''}"

    class Meta:
        verbose_name = _("Sozlama")
        verbose_name_plural = _("Sozlamalar")
        db_table = "settings"
        ordering = ["name"]
        constraints = [
            # Global standart faqat bitta — DB darajasida kafolat.
            # Imtihonga biriktirilgan sozlamalar soni esa cheklanmagan.
            models.UniqueConstraint(
                fields=["is_active"],
                condition=models.Q(is_active=True, deleted_at__isnull=True),
                name="unique_active_setting",
            ),
            # Shartli: o'chirilgan profil nomini qayta ishlatish mumkin.
            models.UniqueConstraint(
                fields=["name"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_setting_name",
            ),
        ]
