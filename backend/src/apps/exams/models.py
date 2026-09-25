from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import SoftDeleteModel, TimeStampedModel


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
    # Platformaga so'rov bilan ketadigan QO'SHIMCHA SARLAVHA, to'liq
    # ko'rinishda: "Authorization: Bearer eyJhbGci...".
    #
    # SHIFRLANGAN SAQLANADI va sabab `Camera.password_encrypted` dagi
    # bilan bir xil: bu KREDENSIAL. Ochiq ustunda yotsa, bazaning bir
    # marta o'qilishi tashqi platformaning API'siga to'liq kirish
    # beradi. Nomi ham shunga mos - `site_header` emas: maydonda
    # sarlavhaning o'zi emas, uning shifrlangan ko'rinishi yotadi va
    # nom buni yashirmasligi kerak.
    #
    # `TextField`: shifrlangan matn asl qiymatdan ~1.4 barobar uzun
    # (base64 + nonce), JWT esa 2-4 KB bo'lishi mumkin.
    site_header_encrypted = models.TextField(
        _("Platforma sarlavhasi"), blank=True, default=""
    )

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
        """
        WebView'da ochilishiga ruxsat etilgan domenlar.

        MANBA BITTA — `site_url`. Ilgari qo'lda to'ldiriladigan
        `allowed_domains` ro'yxati ham bor edi va u ikki muammo
        tug'dirardi: administrator uni `site_url` bilan birga
        yangilashni unutsa, imtihon oq ekranda ochilardi (domen
        bloklangan), bo'sh qoldirilsa esa ro'yxat jimgina
        `site_url` domeniga tushardi - ya'ni maydon ko'p hollarda
        umuman ishlamasdi.

        Ro'yxat client'ga beriladi va u yerda
        `QWebEngineUrlRequestInterceptor` allowlist sifatida
        qo'llanadi. Bo'sh ro'yxat client uchun "tekshiruv
        o'chirilgan" degani, shuning uchun `site_url` noto'g'ri
        bo'lsa ham bu yerdan bo'sh ro'yxat qaytishi mumkin - o'sha
        holatda WebView umuman ochilmaydi (`login_url` ham o'sha
        maydondan keladi).
        """
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


class ComputerBooking(TimeStampedModel):
    """
    Test sessiyasidagi ish o'rni (kompyuter) va unga biriktirilgan talabgor.

    "TEST SESSIYASI" — `ExamSchedule`: imtihon + sana + vaqt + (ixtiyoriy)
    bino. Talabgorning shaxsiy sessiyasi (`proctoring.ExamSession`) bu
    yerga TO'G'RI KELMAYDI: u FaceID'dan keyin yaratiladi, bron esa
    undan ancha oldin — talabgor binoga kelmasdanoq — tuziladi.

    Bitta qator = bitta kompyuter shu sessiyada. Qator ikki narsani
    saqlaydi va ular ATAYLAB alohida bayroq:

        is_active  - mashina ishchi holatdami (buzilgan bo'lsa `False`);
        is_booked  - unga talabgor biriktirilganmi (`pinfl` bilan).

    Ular birlashtirilsa "buzilgan, lekin talabgori bor" holatini
    ifodalab bo'lmasdi — aynan shu holatda administrator talabgorni
    boshqa kompyuterga KO'CHIRADI va buning uchun kim ko'chirilishi
    kerakligini ko'rishi shart.

    Qatorlar kompyuterlar ro'yxatidan YIG'ILADI (`services.generate_seats`)
    yoki biriktirish paytida yaratiladi — administrator 500 ta qatorni
    qo'lda kiritmaydi.

    `Computer.is_active` (hisobdan chiqarilgan) BU YERDAGI `is_active`
    DAN BOSHQA: birinchisi mashina umuman ishlatilmaydi, ikkinchisi esa
    "bugun, shu sessiyada buzildi" (sichqoncha ishlamaydi, kamera yo'q).
    Ertangi sessiyada o'sha mashina yana ishlashi mumkin.
    """

    schedule = models.ForeignKey(
        "exams.ExamSchedule",
        verbose_name=_("Test sessiyasi"),
        on_delete=models.CASCADE,
        related_name="bookings",
    )
    # PROTECT: bronda turgan kompyuterni fizik o'chirish bron tarixini
    # (kim qayerda o'tirgan) jimgina yo'qotardi. Kompyuterlar baribir
    # yumshoq o'chiriladi (`SoftDeleteModel`).
    computer = models.ForeignKey(
        "devices.Computer",
        verbose_name=_("Kompyuter"),
        on_delete=models.PROTECT,
        related_name="bookings",
    )
    is_active = models.BooleanField(_("Ishchi holatda"), default=True, db_index=True)
    is_booked = models.BooleanField(_("Band"), default=False, db_index=True)
    # Tashqi platformada `imie`. Loyihaning qolgan qismida (sessiya,
    # FaceID jurnali, qidiruv) bu qiymat `pinfl` deb ataladi va shu
    # nom saqlanadi: bitta tushuncha uchun ikkita nom so'rovlarda
    # albatta aralashib ketardi.
    pinfl = models.CharField(
        _("JSHSHIR"), max_length=14, blank=True, default="", db_index=True
    )
    booked_at = models.DateTimeField(_("Biriktirilgan vaqt"), null=True, blank=True)
    booked_by = models.ForeignKey(
        "users.User",
        verbose_name=_("Kim biriktirgan"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    # JOY BIR SESSIYADA BIR NECHA TALABGORGA XIZMAT QILADI: talabgor
    # clientda «Yakunlash» ni bosganda yoki administrator uni
    # chetlashtirganda joy o'zi bo'shaydi va keyingisi shu kompyuterga
    # biriktiriladi (`bookings.release_after_session`). Ikkala yakun ham
    # shu hisoblagichda — "shu joyda imtihoni yakunlanganlar".
    # Shu ikki maydon bo'shatilgan joyning izi — usiz oxirgi talabgor
    # yakunlagach sessiyada birorta `is_booked` qolmas va
    # `bookings_enforced` bron tekshiruvini JIMGINA o'chirib qo'yardi.
    finished_count = models.PositiveIntegerField(_("Yakunlaganlar soni"), default=0)
    last_finished_at = models.DateTimeField(_("Oxirgi yakun"), null=True, blank=True)

    @property
    def masked_pinfl(self) -> str:
        from apps.common.utils.crypto import mask_pinfl

        return mask_pinfl(self.pinfl) if self.pinfl else ""

    def __str__(self):
        return "{} · {}".format(self.computer.label, self.pinfl or "bo'sh")

    class Meta:
        verbose_name = _("Kompyuter broni")
        verbose_name_plural = _("Kompyuter bronlari")
        db_table = "computer_booking"
        ordering = ["schedule", "computer__zone", "computer__number", "computer__inventory_code"]
        constraints = [
            # Bitta kompyuter bitta sessiyada BIR MARTA: ikki qator
            # bo'lsa "bu joy bo'shmi?" savolining ikki javobi bo'lardi.
            models.UniqueConstraint(
                fields=["schedule", "computer"], name="unique_booking_schedule_computer"
            ),
            # Bitta talabgor bitta sessiyada BITTA joyda. Bu cheklov
            # bazada — ilova tekshiruvi ikki parallel API so'rovida
            # (tashqi tizim bir JSHSHIR'ni ikki marta yubordi) o'tib
            # ketardi.
            models.UniqueConstraint(
                fields=["schedule", "pinfl"],
                condition=~models.Q(pinfl=""),
                name="unique_booking_schedule_pinfl",
            ),
            # `is_booked` va `pinfl` BIR XIL narsani aytishi shart:
            # "band, lekin kim ekani noma'lum" yoki "bo'sh, lekin
            # JSHSHIR yozilgan" qatori JSHSHIR tekshiruvida ikki xil
            # talqin qilinardi.
            models.CheckConstraint(
                condition=(
                    models.Q(is_booked=True) & ~models.Q(pinfl="")
                ) | (
                    models.Q(is_booked=False) & models.Q(pinfl="")
                ),
                name="booking_pinfl_matches_flag",
            ),
        ]
        indexes = [
            models.Index(fields=["schedule", "is_booked"], name="idx_booking_schedule_booked"),
        ]
