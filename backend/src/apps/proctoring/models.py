"""
Proktorlik domeni.

Asosiy g'oya — ma'lumotni umr bo'yi (lifetime) ajratish:

  Hot     (Redis)      : joriy sessiya holati, heartbeat, fail counter
  Warm    (S3/MinIO)   : skrinshot va yuz rasmlari (binary)
  Cold    (PostgreSQL) : sessiya, hodisa, audit — huquqiy dalil

PostgreSQL'da faqat metadata yotadi. Binary hech qachon DB'ga tushmaydi:
10 000 talaba × 10s × 120 KB = ~13 TB/kun — bunga hech qanday RDBMS bardosh
bermaydi.
"""

import uuid

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import PublicIDModel, TimeStampedModel


class ExamSession(PublicIDModel):
    """
    Imtihon sessiyasi — tizimning markaziy obyekti.

    Talabgor uchun alohida jadval ATAYLAB YO'Q. Talabgor ma'lumoti tashqi
    platformadan keladi va bu yerda imtihon paytidagi holatiga ko'ra
    MUZLATIB saqlanadi. Buning uchta natijasi bor:

      * bayonnomadagi F.I.Sh. keyinchalik tashqi platformada o'zgarsa ham
        o'zgarmaydi — huquqiy hujjat uchun to'g'ri xulq;
      * `reference_embedding` har sessiyada yangidan olinadi, ya'ni bir
        marta xato yozilgan etalon keyingi imtihonlarda aybsiz talabgorni
        chetlashtirib qo'ymaydi;
      * yuzning vaqt bilan o'zgarishi (soqol, ko'zoynak) muammo emas.

    Buning evaziga "10-sanadagi odam 1-sanadagi bilan bir xilmi" degan
    kafolat yo'qoladi. Shaxsni tasdiqlash — operatorning hujjat bo'yicha
    tekshiruvi; FaceID esa faqat "sessiya davomida odam almashtirilmagani"
    ni kafolatlaydi.

    Bitta talabgor bir necha sessiyaga ega bo'lishi mumkin (elektr uzilishi,
    boshqa kompyuterga ko'chirish, boshqa fan, boshqa sana). `attempt_no`
    bir kun ichidagi urinishlarni ajratadi.
    """

    class Status(models.TextChoices):
        PENDING = "pending", _("Kutilmoqda")
        FACE_CHECK = "face_check", _("Yuz tekshiruvida")
        READY = "ready", _("Tayyor")
        IN_PROGRESS = "in_progress", _("Jarayonda")
        FINISHED = "finished", _("Tugatilgan")
        TERMINATED = "terminated", _("Chetlashtirilgan")
        TECHNICAL_PROBLEM = "technical_problem", _("Texnik muammo")
        EXPIRED = "expired", _("Muddati tugagan")

    #: Sessiya yakunlangan hisoblanadigan holatlar.
    TERMINAL_STATUSES = frozenset(
        {Status.FINISHED, Status.TERMINATED, Status.EXPIRED}
    )

    # --- Talabgor (tashqi platformadan, imtihon paytiga muzlatilgan) ---
    #
    # `null` faqat anonimlashtirilgan sessiya uchun. PostgreSQL unique
    # indeksi NULL'larni farqli deb hisoblaydi, shuning uchun retention
    # `unique_session_attempt` ni buzmaydi.
    pinfl = models.CharField(
        _("JSHSHIR"), max_length=14, null=True, blank=True, db_index=True
    )
    last_name = models.CharField(_("Familiya"), max_length=255, blank=True, default="")
    first_name = models.CharField(_("Ism"), max_length=255, blank=True, default="")
    middle_name = models.CharField(_("Otasining ismi"), max_length=255, blank=True, default="")
    external_candidate_id = models.CharField(max_length=100, blank=True, default="")
    photo_key = models.CharField(max_length=500, blank=True, default="")

    # --- Tashqi platformadagi sessiya ---
    #
    # `external_session_token` — AYNAN SHU token WebView'ni ochadi. U
    # tashqi platformaniki va bizning `token_hash` (proktorlik sessiyasi)
    # bilan hech qanday aloqasi yo'q: boshqa tizim, boshqa domen, boshqa
    # hayot sikli. Ikkalasi bir-birini almashtira olmaydi.
    #
    # Shifrlangan saqlanadi: bu tirik kredensial, uni deshifrlash faqat
    # `exam/access/` javobini yig'ishda bir marta kerak bo'ladi. JSHSHIR
    # dan farqli o'laroq bu maydon bo'yicha qidiruv ham, saralash ham
    # qilinmaydi, ya'ni shifrlash hech nimani qiyinlashtirmaydi.
    external_session_token_enc = models.TextField(blank=True, default="")
    external_status = models.CharField(
        _("Tashqi platformadagi status"), max_length=32, blank=True, default=""
    )
    # Platforma ruxsat bergan kirish oynasi — bizning `ExamSchedule` dan
    # ALOHIDA. Jadval "seans qachon", bu esa "aynan shu talabgorga qachon".
    external_access_from = models.DateTimeField(blank=True, null=True)
    external_access_until = models.DateTimeField(blank=True, null=True)

    #: Shu sessiya uchun yuz etaloni. Kirishda olinadi, davriy tekshiruvlar
    #: shunga nisbatan bajariladi. Sessiya tugagach qayta ishlatilmaydi.
    reference_embedding = ArrayField(models.FloatField(), blank=True, null=True)

    # Retention: shu muddatdan keyin PII o'chiriladi (sessiya qatori qoladi).
    anonymize_after = models.DateTimeField(blank=True, null=True, db_index=True)
    is_anonymized = models.BooleanField(default=False, db_index=True)

    exam = models.ForeignKey(
        "exams.Exam", on_delete=models.PROTECT, related_name="sessions"
    )
    schedule = models.ForeignKey(
        "exams.ExamSchedule", on_delete=models.SET_NULL, blank=True, null=True, related_name="sessions"
    )
    computer = models.ForeignKey(
        "devices.Computer", on_delete=models.PROTECT, blank=True, null=True, related_name="sessions"
    )
    zone = models.ForeignKey(
        "regions.Zone", on_delete=models.PROTECT, blank=True, null=True, related_name="sessions"
    )
    device = models.ForeignKey(
        "devices.DeviceToken", on_delete=models.SET_NULL, blank=True, null=True, related_name="sessions"
    )

    attempt_no = models.PositiveSmallIntegerField(default=1)
    exam_date = models.DateField(db_index=True)

    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.PENDING, db_index=True
    )

    # Sessiya tokeni OCHIQ saqlanmaydi — faqat HMAC hash'i.
    token_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)
    token_expires_at = models.DateTimeField(blank=True, null=True)

    started_at = models.DateTimeField(blank=True, null=True, db_index=True)
    finished_at = models.DateTimeField(blank=True, null=True, db_index=True)
    last_heartbeat_at = models.DateTimeField(blank=True, null=True, db_index=True)

    ip_address = models.GenericIPAddressField(blank=True, null=True, db_index=True)
    mac_address = models.CharField(max_length=17, blank=True, default="")

    # --- Proktorlik yig'indisi (Redis'dan davriy ravishda ko'chiriladi) ---
    face_fail_count = models.PositiveSmallIntegerField(default=0)
    face_check_count = models.PositiveIntegerField(default=0)
    event_count = models.PositiveIntegerField(default=0)
    screenshot_count = models.PositiveIntegerField(default=0)
    #: 0–100. Hodisalar jiddiyligidan hisoblanadi, proktorni tartiblash uchun.
    risk_score = models.PositiveSmallIntegerField(default=0, db_index=True)

    terminated_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, blank=True, null=True, related_name="terminated_sessions"
    )
    termination_reason = models.CharField(max_length=500, blank=True, default="")

    meta = models.JSONField(default=dict, blank=True)

    @property
    def full_name(self) -> str:
        parts = [self.last_name, self.first_name, self.middle_name]
        return " ".join(part for part in parts if part).strip()

    @property
    def external_session_token(self) -> str:
        """Tashqi platforma tokeni (deshifrlangan). WebView shu bilan ochiladi."""
        from apps.common.utils.crypto import decrypt

        return decrypt(self.external_session_token_enc) or ""

    @property
    def external_access_open(self) -> bool:
        """Platforma bergan kirish oynasi hozir ochiqmi."""
        from django.utils import timezone

        now = timezone.now()
        if self.external_access_from and now < self.external_access_from:
            return False
        if self.external_access_until and now > self.external_access_until:
            return False
        return True

    @property
    def identity(self) -> dict:
        """Operator tasdig'i haqidagi yozuv (`meta` ichida saqlanadi)."""
        return (self.meta or {}).get("identity") or {}

    @property
    def identity_verified(self) -> bool:
        """
        Shaxs hujjat bo'yicha tasdiqlanganmi.

        Buni FaceID BERA OLMAYDI: etalon shu sessiyaning o'zida olinadi,
        ya'ni yuz tekshiruvi faqat "sessiya davomida odam almashtirilmadi"
        ni kafolatlaydi. "Bu aynan o'sha talabgormi" degan savolga faqat
        hujjatni ko'rgan operator javob bera oladi.
        """
        return bool(self.identity.get("verified"))

    @property
    def masked_pinfl(self) -> str:
        from apps.common.utils.crypto import mask_pinfl

        return mask_pinfl(self.pinfl) if self.pinfl else ""

    @property
    def is_active(self) -> bool:
        return self.status not in self.TERMINAL_STATUSES

    @property
    def duration_seconds(self) -> int | None:
        if not self.started_at:
            return None
        end = self.finished_at
        if end is None:
            from django.utils import timezone

            end = timezone.now()
        return int((end - self.started_at).total_seconds())

    def __str__(self):
        return f"Session<{self.public_id}> {self.status}"

    class Meta:
        verbose_name = _("Imtihon sessiyasi")
        verbose_name_plural = _("Imtihon sessiyalari")
        db_table = "exam_session"
        ordering = ["-id"]
        constraints = [
            # Bitta talabgor + imtihon + sana + urinish = bitta sessiya.
            models.UniqueConstraint(
                fields=["pinfl", "exam", "exam_date", "attempt_no"],
                name="unique_session_attempt",
            ),
            # JSHSHIR faqat anonimlashtirilgan sessiyada bo'sh bo'lishi mumkin.
            models.CheckConstraint(
                condition=models.Q(pinfl__isnull=False) | models.Q(is_anonymized=True),
                name="session_pinfl_required_unless_anonymized",
            ),
        ]
        indexes = [
            # "Bu talabgor avval qachon topshirgan" — tarix ekrani shu indeksda.
            models.Index(fields=["pinfl", "-exam_date"], name="idx_session_pinfl"),
            # Retention: muddati o'tgan sessiyalarni topish
            models.Index(
                fields=["is_anonymized", "anonymize_after"], name="idx_session_retention"
            ),
            # Dashboard: "shu binoda hozir faol sessiyalar"
            models.Index(fields=["zone", "status", "exam_date"], name="idx_session_zone_status"),
            # Monitoring: "eng xavfli sessiyalar tepada"
            models.Index(
                fields=["status", "-risk_score"],
                name="idx_session_risk",
                condition=models.Q(status__in=["in_progress", "face_check", "ready"]),
            ),
            # Stale detector: heartbeat kelmayotgan faol sessiyalar
            models.Index(
                fields=["last_heartbeat_at"],
                name="idx_session_heartbeat",
                condition=models.Q(status="in_progress"),
            ),
            models.Index(fields=["exam", "exam_date"], name="idx_session_exam_date"),
            models.Index(fields=["token_hash"], name="idx_session_token"),
        ]


class ProctoringEvent(models.Model):
    """
    Proktorlik hodisasi — eng katta jadval (kuniga milliardlab qator).

    Loyihalash qarorlari:
      * `TimeStampedModel` dan meros olinmagan: `updated_at` va qo'shimcha
        indeks bu jadvalda sof isrof. Hodisa hech qachon yangilanmaydi.
      * `occurred_at` bo'yicha RANGE partitsiyalanadi (migratsiyada
        raw SQL orqali). Eski ma'lumot `DROP PARTITION` bilan bir soniyada
        o'chadi; `DELETE` esa bir kun ishlaydi.
      * Yozish faqat `bulk_create` orqali, Celery buffer'idan.
    """

    class Type(models.TextChoices):
        # --- Oyna / fokus ---
        WINDOW_BLUR = "window_blur", _("Oynadan chiqish")
        WINDOW_FOCUS = "window_focus", _("Oynaga qaytish")
        FULLSCREEN_EXIT = "fullscreen_exit", _("To'liq ekrandan chiqish")
        # --- Kirish qurilmalari ---
        HOTKEY_BLOCKED = "hotkey_blocked", _("Tezkor tugma bloklandi")
        CLIPBOARD_BLOCKED = "clipboard_blocked", _("Nusxa ko'chirish bloklandi")
        # --- Qurilma ---
        MULTI_MONITOR = "multi_monitor", _("Bir nechta monitor")
        CAMERA_LOST = "camera_lost", _("Kamera yo'qoldi")
        CAMERA_BLOCKED = "camera_blocked", _("Kamera yopilgan")
        RDP_DETECTED = "rdp_detected", _("Masofaviy boshqaruv aniqlandi")
        VM_DETECTED = "vm_detected", _("Virtual mashina aniqlandi")
        PROCESS_BLACKLISTED = "process_blacklisted", _("Taqiqlangan dastur")
        # --- Yuz / obyekt ---
        FACE_NOT_FOUND = "face_not_found", _("Yuz topilmadi")
        FACE_MISMATCH = "face_mismatch", _("Yuz mos kelmadi")
        MULTIPLE_FACES = "multiple_faces", _("Bir nechta yuz")
        OBJECT_DETECTED = "object_detected", _("Taqiqlangan obyekt")
        # --- Tarmoq / tizim ---
        NETWORK_LOST = "network_lost", _("Tarmoq uzildi")
        NETWORK_RESTORED = "network_restored", _("Tarmoq tiklandi")
        CLIENT_ANOMALY = "client_anomaly", _("Client anomaliyasi")
        NAVIGATION_BLOCKED = "navigation_blocked", _("URL bloklandi")
        # --- Proktor amallari ---
        PROCTOR_WARNING = "proctor_warning", _("Proktor ogohlantirdi")
        SESSION_TERMINATED = "session_terminated", _("Sessiya tugatildi")

    class Severity(models.IntegerChoices):
        INFO = 0, _("Ma'lumot")
        LOW = 1, _("Past")
        MEDIUM = 2, _("O'rta")
        HIGH = 3, _("Yuqori")
        CRITICAL = 4, _("Kritik")

    id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey(
        "proctoring.ExamSession", on_delete=models.CASCADE, related_name="events"
    )
    type = models.CharField(max_length=32, choices=Type.choices, db_index=True)
    severity = models.SmallIntegerField(choices=Severity.choices, default=Severity.LOW)

    # Client hodisani qachon qayd etgan (uzilishdan keyin kech kelishi mumkin).
    occurred_at = models.DateTimeField(db_index=True)
    received_at = models.DateTimeField(auto_now_add=True)

    payload = models.JSONField(default=dict, blank=True)
    screenshot_key = models.CharField(max_length=500, blank=True, default="")

    # Client tomonidan yaratilgan ID — takroriy yuborishda dublikatni to'sadi.
    client_event_id = models.CharField(max_length=64, blank=True, default="")

    def __str__(self):
        return f"{self.type}@{self.occurred_at:%H:%M:%S}"

    class Meta:
        verbose_name = _("Proktorlik hodisasi")
        verbose_name_plural = _("Proktorlik hodisalari")
        db_table = "proctoring_event"
        ordering = ["-occurred_at"]
        indexes = [
            # Sessiya tafsiloti sahifasi (cursor pagination shu indeksda ishlaydi)
            models.Index(fields=["session", "-occurred_at"], name="idx_event_session_time"),
            # "Oxirgi 5 daqiqadagi kritik hodisalar" — dashboard uchun
            models.Index(
                fields=["-occurred_at"],
                name="idx_event_critical",
                condition=models.Q(severity__gte=3),
            ),
            models.Index(fields=["type", "-occurred_at"], name="idx_event_type_time"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "client_event_id"],
                condition=~models.Q(client_event_id=""),
                name="unique_session_client_event",
            ),
        ]


class FaceVerificationLog(models.Model):
    """Har bir yuz tekshiruvi. Chetlashtirish qarori shu log bilan asoslanadi."""

    class Stage(models.TextChoices):
        INITIAL = "initial", _("Kirishda")
        PERIODIC = "periodic", _("Test davomida")
        AUDIT = "audit", _("Server auditi")
        MANUAL = "manual", _("Proktor tekshiruvi")

    class Source(models.TextChoices):
        CLIENT = "client", _("Client (ONNX)")
        SERVER = "server", _("Server (GPU)")

    id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey(
        "proctoring.ExamSession", on_delete=models.CASCADE, related_name="face_logs"
    )
    stage = models.CharField(max_length=16, choices=Stage.choices, default=Stage.PERIODIC)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.CLIENT)

    score = models.PositiveSmallIntegerField(default=0)
    threshold = models.PositiveSmallIntegerField(default=70)
    passed = models.BooleanField(default=False, db_index=True)
    faces_detected = models.PositiveSmallIntegerField(default=1)

    image_key = models.CharField(max_length=500, blank=True, default="")
    occurred_at = models.DateTimeField(db_index=True)
    received_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Face<{self.session_id}> {self.score} {'OK' if self.passed else 'FAIL'}"

    class Meta:
        verbose_name = _("Yuz tekshiruvi")
        verbose_name_plural = _("Yuz tekshiruvlari")
        db_table = "face_verification_log"
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["session", "-occurred_at"], name="idx_facelog_session_time"),
            models.Index(
                fields=["session"],
                name="idx_facelog_failed",
                condition=models.Q(passed=False),
            ),
        ]


class ScreenshotMeta(models.Model):
    """
    Skrinshot METADATA'si. Binary object storage'da.

    `sha256` ikki vazifani bajaradi:
      1. Yaxlitlikni tekshirish (client yuklagani bilan mos keladimi);
      2. Anomaliya aniqlash — ketma-ket kadrlar hash'i bir xil bo'lsa,
         client oldindan yozilgan tasvirni uzatayotgan bo'lishi mumkin.
    """

    class Kind(models.TextChoices):
        SCREEN = "screen", _("Ekran")
        WEBCAM = "webcam", _("Veb-kamera")
        IPCAM = "ipcam", _("IP kamera")

    id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey(
        "proctoring.ExamSession", on_delete=models.CASCADE, related_name="screenshots"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.SCREEN)

    object_key = models.CharField(max_length=500)
    sha256 = models.CharField(max_length=64, blank=True, default="", db_index=True)
    size_bytes = models.PositiveIntegerField(default=0)
    width = models.PositiveSmallIntegerField(default=0)
    height = models.PositiveSmallIntegerField(default=0)

    captured_at = models.DateTimeField(db_index=True)
    received_at = models.DateTimeField(auto_now_add=True)
    # Client yuklashni tasdiqlaganmi (presigned PUT muvaffaqiyatli tugadimi).
    is_committed = models.BooleanField(default=False, db_index=True)
    purge_after = models.DateTimeField(blank=True, null=True, db_index=True)

    class Meta:
        verbose_name = _("Skrinshot")
        verbose_name_plural = _("Skrinshotlar")
        db_table = "screenshot_meta"
        ordering = ["-captured_at"]
        indexes = [
            models.Index(fields=["session", "-captured_at"], name="idx_shot_session_time"),
            models.Index(fields=["is_committed", "purge_after"], name="idx_shot_purge"),
        ]


class ProctoringScreenshot(models.Model):
    """
    Fayl tizimida saqlanadigan skrinshot.

    `ScreenshotMeta` dan farqi — u obyekt storage'ini (S3/MinIO) nazarda
    tutadi va binary backend'dan umuman o'tmaydi (presigned URL). Bu model
    esa binary Django orqali kelib diskka yozilgan holat uchun: MinIO
    ko'tarilmagan, bitta server ko'lamidagi o'rnatishlar uchun. Ikkalasi
    parallel yashaydi, chunki ular boshqa-boshqa o'rnatish profillari.

    **DB'da faqat NISBIY yo'l saqlanadi.** Absolyut yo'l saqlansa:
      * storage root ko'chganda (yoki dev/prod da farq qilganda) barcha
        qatorlar bir vaqtda yaroqsiz bo'ladi;
      * u API javobiga yoki log'ga tushib, server katalog strukturasini
        oshkor qiladi.
    Root sozlamada yashaydi, qatorda emas.

    `content_hash` ikki vazifani bajaradi:
      1. Yaxlitlik — diskdagi fayl o'sha faylmi (dalil sifatida muhim);
      2. Anomaliya — ketma-ket kadrlar hash'i bir xil bo'lsa, client
         oldindan yozilgan tasvirni qayta-qayta uzatayotgan bo'ladi.
    """

    id = models.BigAutoField(primary_key=True)
    # CASCADE: sessiya o'chsa qatorlar ham ketadi. Diqqat — bu holda
    # fayllar diskda qoladi (bulk delete fayl tizimiga tegmaydi). Sessiya
    # normal ish jarayonida O'CHIRILMAYDI (retention uni anonimlashtiradi,
    # o'chirmaydi), shuning uchun bu faqat dev/test yo'li.
    session = models.ForeignKey(
        "proctoring.ExamSession",
        on_delete=models.CASCADE,
        related_name="stored_screenshots",
        verbose_name=_("Sessiya"),
    )

    #: `{exam_id}/{session_id}/{captured_at}_{seq}.{ext}` — storage root'ga nisbatan.
    file_path = models.CharField(_("Fayl yo'li"), max_length=500, unique=True)
    content_hash = models.CharField(_("SHA-256"), max_length=64, db_index=True)
    file_size = models.PositiveIntegerField(_("Hajmi (bayt)"), default=0)
    mime_type = models.CharField(_("MIME turi"), max_length=64, default="image/jpeg")

    #: Sessiya ichidagi tartib raqami — bir soniyada bir necha kadr
    #: kelganda fayl nomlarini ajratadi.
    seq = models.PositiveIntegerField(_("Tartib raqami"), default=0)

    captured_at = models.DateTimeField(_("Olingan vaqti"), db_index=True)
    received_at = models.DateTimeField(_("Qabul qilingan vaqti"), auto_now_add=True)

    class Meta:
        verbose_name = _("Skrinshot (fayl)")
        verbose_name_plural = _("Skrinshotlar (fayl)")
        db_table = "proctoring_screenshot"
        ordering = ["-captured_at", "-seq"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "captured_at", "seq"],
                name="unique_screenshot_session_seq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["session", "-captured_at"], name="idx_pshot_session_time"
            ),
            # Retention shu indeks bo'yicha yuradi: `captured_at < cutoff`.
            models.Index(fields=["captured_at"], name="idx_pshot_retention"),
        ]

    def __str__(self):
        return f"Screenshot<{self.pk}> {self.file_path}"


class TechnicalProblem(TimeStampedModel):
    """Texnik muammo — qo'shimcha vaqt berish qarori shu yerda qayd etiladi."""

    class Kind(models.TextChoices):
        POWER = "power", _("Elektr")
        NETWORK = "network", _("Tarmoq")
        HARDWARE = "hardware", _("Uskuna")
        SOFTWARE = "software", _("Dastur")
        OTHER = "other", _("Boshqa")

    session = models.ForeignKey(
        "proctoring.ExamSession", on_delete=models.CASCADE, related_name="technical_problems"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.OTHER)
    description = models.TextField(blank=True, default="")

    started_at = models.DateTimeField(db_index=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    overtime = models.DurationField(blank=True, null=True)

    is_resolved = models.BooleanField(_("Qaror qabul qilindi"), default=False, db_index=True)
    resolved_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, blank=True, null=True, related_name="resolved_problems"
    )
    resolution_note = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        verbose_name = _("Texnik muammo")
        verbose_name_plural = _("Texnik muammolar")
        db_table = "technical_problem"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["session", "-started_at"], name="idx_tp_session_time"),
            models.Index(
                fields=["-started_at"],
                name="idx_tp_unresolved",
                condition=models.Q(is_resolved=False),
            ),
        ]
class AuditLog(models.Model):
    """
    Xodim harakatlari.

    "Kim, kimni, qachon, qaysi IP dan chetlashtirdi" — bu savol apellyatsiya
    va sud jarayonida beriladi. Shuning uchun audit ixtiyoriy emas.
    """

    class Action(models.TextChoices):
        LOGIN = "login", _("Kirish")
        LOGOUT = "logout", _("Chiqish")
        CREATE = "create", _("Yaratish")
        UPDATE = "update", _("O'zgartirish")
        DELETE = "delete", _("O'chirish")
        SESSION_WARN = "session_warn", _("Ogohlantirish")
        SESSION_TERMINATE = "session_terminate", _("Chetlashtirish")
        SESSION_RESTORE = "session_restore", _("Tiklash")
        IDENTITY_CONFIRM = "identity_confirm", _("Shaxs tasdiqlandi")
        IDENTITY_REJECT = "identity_reject", _("Shaxs tasdiqlanmadi")
        CLIENT_EXIT = "client_exit", _("Client'dan chiqish")
        TP_RESOLVE = "tp_resolve", _("Texnik muammo qarori")
        SETTING_CHANGE = "setting_change", _("Sozlama o'zgarishi")
        DEVICE_REVOKE = "device_revoke", _("Qurilmani bloklash")
        CLIENT_ANOMALY = "client_anomaly", _("Client anomaliyasi")
        RESTORE = "restore", _("Tiklash")
        EXPORT = "export", _("Eksport")

    id = models.BigAutoField(primary_key=True)
    actor = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, blank=True, null=True, related_name="audit_logs"
    )
    actor_username = models.CharField(max_length=255, blank=True, default="")
    action = models.CharField(max_length=32, choices=Action.choices, db_index=True)

    object_type = models.CharField(max_length=64, blank=True, default="", db_index=True)
    object_id = models.CharField(max_length=64, blank=True, default="")

    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.CharField(max_length=500, blank=True, default="")
    request_id = models.CharField(max_length=64, blank=True, default="")
    meta = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f"{self.actor_username} {self.action} {self.object_type}#{self.object_id}"

    class Meta:
        verbose_name = _("Audit yozuvi")
        verbose_name_plural = _("Audit yozuvlari")
        db_table = "audit_log"
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["actor", "-created_at"], name="idx_audit_actor_time"),
            models.Index(
                fields=["object_type", "object_id", "-created_at"], name="idx_audit_object"
            ),
        ]
