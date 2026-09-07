from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import SoftDeleteModel


class ExamType(SoftDeleteModel):
    """
    Imtihon turi — imtihonlarni guruhlaydigan ma'lumotnoma.

    Nima uchun alohida jadval, `TextChoices` emas: turlar ro'yxati
    operatsion ma'lumot, u yangi imtihon mavsumida o'zgaradi. `TextChoices`
    bo'lsa, har bir yangi tur uchun kod relizi va migratsiya kerak bo'lardi —
    operator buni admin panelidan qila olishi kerak.
    """

    name = models.CharField(_("Nom"), max_length=255)
    # Kod bo'yicha murojaat qilinadigan BARQAROR kalit (hisobot, tashqi
    # integratsiya, client mantiqi). Nom keyinchalik o'zgarishi mumkin,
    # kalit esa o'zgarmaydi — shuning uchun bog'lanish nomga emas, shunga
    # quriladi. Qarang: `controls` dagi kod asosidagi `Permission`.
    key = models.CharField(_("Kalit"), max_length=100, db_index=True)
    is_active = models.BooleanField(_("Faol"), default=True, db_index=True)

    def __str__(self):
        return str(self.name)

    class Meta:
        verbose_name = _("Imtihon turi")
        verbose_name_plural = _("Imtihon turlari")
        db_table = "exam_type"
        ordering = ["name"]
        constraints = [
            # Shartli cheklovlar — loyihadagi boshqa konfiguratsiya
            # modellari bilan bir xil qoida: o'chirilgan yozuv nomni ham,
            # kalitni ham abadiy band qilib qolmaydi.
            models.UniqueConstraint(
                fields=["name"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_exam_type_name",
            ),
            models.UniqueConstraint(
                fields=["key"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_exam_type_key",
            ),
        ]


class Exam(SoftDeleteModel):
    """Imtihon (fan/yo'nalish). Tashqi platformadagi test bilan bog'lanadi."""

    # `unique=True` EMAS — pastdagi shartli cheklovga qarang.
    name = models.CharField(_("Nom"), max_length=255)
    key = models.CharField(_("Kalit"), max_length=100, blank=True, default="", db_index=True)
    # `null=True` — jadvalda allaqachon imtihonlar bor va ular turga
    # bo'linmagan; majburiy qilinsa migratsiya ularga soxta tur yozishga
    # majbur qilardi. `PROTECT` — ishlatilayotgan turni fizik o'chirib
    # bo'lmaydi (yumshoq o'chirish esa `deleted_at` orqali ishlaydi).
    exam_type = models.ForeignKey(
        "exams.ExamType",
        verbose_name=_("Imtihon turi"),
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="exams",
    )
    external_code = models.CharField(
        _("Tashqi platforma kodi"), max_length=100, blank=True, default="", db_index=True
    )
    site_url = models.URLField(
        _("Test platformasi URL"), max_length=500, default="https://ntest.uzbmb.uz/login"
    )
    # WebView'da ochilishiga ruxsat etilgan domenlar. Bo'sh bo'lsa `site_url`
    # domeni ishlatiladi. Bu ro'yxat client'ga beriladi va u yerda
    # QWebEngineUrlRequestInterceptor allowlist sifatida qo'llanadi.
    allowed_domains = models.JSONField(_("Ruxsat etilgan domenlar"), default=list, blank=True)

    duration_minutes = models.PositiveIntegerField(_("Davomiyligi (daq)"), default=180)
    setting = models.ForeignKey(
        "controls.Setting",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="exams",
        help_text=_("Bo'sh bo'lsa — global faol sozlama ishlatiladi"),
    )
    is_active = models.BooleanField(_("Faol"), default=True, db_index=True)

    def __str__(self):
        return str(self.name)

    def get_allowed_domains(self) -> list[str]:
        if self.allowed_domains:
            return list(self.allowed_domains)
        from urllib.parse import urlparse

        host = urlparse(self.site_url).hostname
        return [host] if host else []

    class Meta:
        verbose_name = _("Imtihon")
        verbose_name_plural = _("Imtihonlar")
        db_table = "exams"
        ordering = ["id"]
        constraints = [
            # Shartli: o'chirilgan imtihon nomini abadiy band qilib qolmaydi.
            # Oddiy `unique=True` da admin ro'yxatda hech nima ko'rmay turib
            # "Bunday nomli imtihon allaqachon mavjud" xatosini olardi.
            models.UniqueConstraint(
                fields=["name"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_exam_name",
            ),
        ]


class ExamSchedule(SoftDeleteModel):
    """
    Imtihon oynasi (sana + vaqt + zona).

    Nima uchun alohida model: `/client/candidate/lookup/` endpoint'i faqat
    ochiq imtihon oynasi ichida ishlashi kerak. Aks holda JSHSHIR qidiruvi
    24/7 ochiq turadi — bu kerakmas hujum yuzasi.
    """

    exam = models.ForeignKey(
        "exams.Exam", on_delete=models.CASCADE, related_name="schedules"
    )
    zone = models.ForeignKey(
        "regions.Zone",
        on_delete=models.CASCADE,
        related_name="exam_schedules",
        blank=True,
        null=True,
        help_text=_("Bo'sh bo'lsa — barcha binolar uchun"),
    )
    exam_date = models.DateField(_("Sana"), db_index=True)
    starts_at = models.DateTimeField(_("Boshlanishi"))
    ends_at = models.DateTimeField(_("Tugashi"))
    # Kirish oynasi boshlanishidan necha daqiqa oldin ochiladi.
    checkin_lead_minutes = models.PositiveIntegerField(default=60)
    is_active = models.BooleanField(default=True)

    @property
    def opens_at(self):
        """Kirish oynasi ochiladigan vaqt (imtihon boshlanishidan oldin)."""
        from django.utils import timezone

        return self.starts_at - timezone.timedelta(minutes=self.checkin_lead_minutes)

    def is_open(self, at=None) -> bool:
        """
        Berilgan momentda kirish oynasi ochiqmi.

        Mantiq ataylab modelda: uni ham serializer (`is_open` maydoni), ham
        `lookup_candidate` chaqiradi. Ikki joyda takrorlansa, admin panelda
        "ochiq" ko'rinib turgan imtihon client'da rad etilishi mumkin.
        """
        from django.utils import timezone

        now = at or timezone.now()
        return bool(self.is_active and self.opens_at <= now <= self.ends_at)

    def __str__(self):
        return f"{self.exam.name} — {self.exam_date}"

    class Meta:
        verbose_name = _("Imtihon jadvali")
        verbose_name_plural = _("Imtihon jadvallari")
        db_table = "exam_schedule"
        ordering = ["-exam_date", "starts_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="exam_schedule_ends_after_starts",
            ),
        ]
        indexes = [
            models.Index(
                fields=["exam_date", "is_active"], name="idx_schedule_date_active"
            ),
            models.Index(fields=["zone", "exam_date"], name="idx_schedule_zone_date"),
        ]
