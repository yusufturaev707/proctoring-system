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


class ProctoringState(models.TextChoices):
    """
    AI kuzatuvining hayot sikli - `ExamSession.status` dan MUSTAQIL.

    Modul darajasida (sinf ichida emas), chunki uni uch joy o'qiydi:
    model, client API va serverdagi tekshiruvlar. Sinf ichida bo'lsa,
    ularning har biri `ExamSession` ni import qilishga majbur bo'lardi -
    holbuki ular faqat holat nomlarini bilishi kerak.

    O'tishlar:

        idle -> camera_check -> ready -> starting -> active
                     |                                 |
                     v                        degraded / paused
                  failed                               |
                                            finishing -> completed

    `degraded` - kuzatuv ISHLAYAPTI, lekin to'liq emas (bitta kamera
    yo'q, GPU CPU'ga tushdi, FPS past). Bu holat ATAYLAB imtihonni
    to'xtatmaydi: aks holda har bir texnik nosozlik aybsiz talabgorning
    imtihonini buzardi. Qaror siyosatda (`camera_lost_action`).
    """

    IDLE = "idle", _("Boshlanmagan")
    CAMERA_CHECK = "camera_check", _("Kamera tekshiruvida")
    READY = "ready", _("Tayyor")
    STARTING = "starting", _("Ishga tushmoqda")
    ACTIVE = "active", _("Faol")
    DEGRADED = "degraded", _("Cheklangan rejim")
    PAUSED = "paused", _("To'xtatib turilgan")
    FINISHING = "finishing", _("Yakunlanmoqda")
    COMPLETED = "completed", _("Yakunlangan")
    FAILED = "failed", _("Muvaffaqiyatsiz")


#: Kuzatuv HAQIQATDA ishlab turgan holatlar.
#
# Ro'yxat shu yerda, chunki uni uch joy o'qiydi: dalil qabul qilish
# (`evidence/upload/` faqat shu holatlarda ishlaydi), diagnostika va
# yakunlash vazifasi. Uchta joyda takrorlansa, ular albatta ajralib
# ketadi - va o'shanda dalil jimgina rad etila boshlaydi.
PROCTORING_RUNNING_STATES = frozenset(
    {
        ProctoringState.ACTIVE,
        ProctoringState.DEGRADED,
        ProctoringState.PAUSED,
        ProctoringState.FINISHING,
    }
)


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
    # `external_test_link` — AYNAN SHU havola WebView'ni ochadi
    # (`data.test_link`). Token uning ICHIDA va uni platformaning
    # o'zi shunday beradi; bizning `token_hash` (proktorlik
    # sessiyasi) bilan hech qanday aloqasi yo'q: boshqa tizim,
    # boshqa domen, boshqa hayot sikli.
    #
    # Shifrlangan saqlanadi: bu tirik kredensial, uni deshifrlash
    # faqat `exam/access/` javobini yig'ishda bir marta kerak
    # bo'ladi. Bu maydon bo'yicha qidiruv ham, saralash ham
    # qilinmaydi, ya'ni shifrlash hech nimani qiyinlashtirmaydi.
    #
    # NIMA UCHUN SESSIYAGA MUZLATILADI: havola JSHSHIR tekshiruvida
    # bir marta olinadi (FaceID'dan OLDIN) va WebView ochilguncha
    # bir necha daqiqa o'tadi. Uni qayta so'rash platformada yangi
    # havola yaratib, eskisini bekor qilishi mumkin.
    external_test_link_enc = models.TextField(blank=True, default="")
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
    #: `{hodisa_turi: ball}` - ballning TUSHUNTIRISHI.
    #
    # Yagona `risk_score` proktorga "72" deb aytadi va boshqa hech
    # narsa demaydi. Chetlashtirish qarori esa asoslanishi kerak:
    # "72 ball, shundan 40 tasi telefon, 20 tasi ikkinchi odam" -
    # bu tekshirib bo'ladigan da'vo, "72" esa yo'q. Apellyatsiyada
    # aynan shu farq hal qiluvchi.
    risk_breakdown = models.JSONField(default=dict, blank=True)

    # --- AI proktorlik holati ---
    #
    # `status` dan ALOHIDA va bu ataylab: `status` "imtihon qanday
    # ketyapti" (jarayonda / tugadi / chetlashtirildi), bu esa
    # "kuzatuv qanday ishlayapti" degan savolga javob beradi.
    # Ularni birlashtirish "kamera uzildi = imtihon tugadi" degan
    # noto'g'ri xulosaga olib kelardi - holbuki kamera uzilishi
    # ko'pincha 15 soniyalik USB nosozligi.
    proctoring_state = models.CharField(
        max_length=12, choices=ProctoringState.choices,
        default=ProctoringState.IDLE, db_index=True,
    )
    #: Oxirgi kamera tekshiruvi natijasi (`camera/check/` javobi).
    #
    # Sessiyada saqlanadi, chunki imtihon boshlashga ruxsat AYNAN
    # shunga qarab beriladi va bu qaror keyin tekshirilishi kerak:
    # "nega bu mashinada ikkinchi kamerasiz boshlandi?".
    camera_check = models.JSONField(default=dict, blank=True)
    #: Client tanlagan unumdorlik profili (`high`/`medium`/`low`/`cpu`).
    #
    # Bayonnoma uchun muhim: CPU rejimida kuzatuv chastotasi past va
    # "hech narsa aniqlanmadi" xulosasining vazni ham past bo'ladi.
    ai_profile = models.CharField(max_length=8, blank=True, default="")

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
    def external_test_link(self) -> str:
        """Test havolasi (deshifrlangan). WebView AYNAN shuni ochadi."""
        from apps.common.utils.crypto import decrypt

        return decrypt(self.external_test_link_enc) or ""

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
        # --- AI proktorlik: shaxs ---
        FACE_OCCLUDED = "face_occluded", _("Yuz qisman yopilgan")
        FACE_TOO_FAR = "face_too_far", _("Yuz juda uzoqda")
        FACE_TOO_CLOSE = "face_too_close", _("Yuz juda yaqin")
        STUDENT_LEFT_FRAME = "student_left_frame", _("Talabgor kadrdan chiqdi")
        SECOND_PERSON = "second_person", _("Kadrda ikkinchi odam")
        # --- AI proktorlik: nigoh va poza ---
        LOOKING_AWAY = "looking_away", _("Chetga qaradi")
        PROLONGED_LOOKING_AWAY = "prolonged_looking_away", _("Uzoq vaqt chetga qaradi")
        EXCESSIVE_HEAD_MOVEMENT = "excessive_head_movement", _("Bosh harakati ko'p")
        EYES_CLOSED = "eyes_closed", _("Ko'zlar yumuq")
        HAND_BELOW_DESK = "hand_below_desk", _("Qo'l stol ostida")
        SUSPICIOUS_HAND_MOVEMENT = "suspicious_hand_movement", _("Shubhali qo'l harakati")
        UNAUTHORIZED_DEVICE = "unauthorized_device", _("Ruxsatsiz qurilma")
        # --- AI proktorlik: birlashtirilgan (fusion) ---
        #
        # Bular ALOHIDA turlar va tarkibiy hodisalarni ALMASHTIRMAYDI:
        # "telefon aniqlandi" yozuvi o'z o'rnida qoladi, bu esa uning
        # ustidagi xulosa. Dalil zanjiri shu tarzda buzilmaydi -
        # apellyatsiyada "nima uchun yuqori shubha?" degan savolga
        # tarkibiy hodisalar bilan javob berish mumkin.
        HIGH_SUSPICION_PHONE = "high_suspicion_phone", _("Yuqori shubha - telefon")
        HIGH_SUSPICION_PERSON = "high_suspicion_person", _("Yuqori shubha - begona shaxs")
        HIGH_SUSPICION_IDENTITY = "high_suspicion_identity", _("Yuqori shubha - shaxs almashtirilgan")
        # --- AI proktorlik: kuzatuvning o'z holati ---
        #
        # Kuzatuv NOSOZLIGI ham hodisa. Usiz bayonnomada bo'shliq
        # paydo bo'ladi va uni "hech narsa bo'lmagan" deb o'qish
        # mumkin - holbuki u "hech narsa KO'RILMAGAN" degani.
        CAMERA_DEGRADED = "camera_degraded", _("Kamera sifati pasaydi")
        CAMERA_RECONNECTED = "camera_reconnected", _("Kamera qayta ulandi")
        PROCTORING_DEGRADED = "proctoring_degraded", _("Kuzatuv cheklangan rejimda")
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

    # --- AI proktorlik maydonlari ---
    #
    # Nima uchun aynan shu beshtasi ustun bo'ldi, qolgani `payload` da:
    # bu qiymatlar bo'yicha FILTRLANADI va SARALANADI (proktor "ishonchi
    # 90 dan yuqori va 5 soniyadan uzoq hodisalarni ko'rsat" deydi),
    # JSON ichidagi kalit bo'yicha esa bu so'rov indekssiz ketardi.
    # Qolgan hamma narsa (bbox, landmark, tarkibiy hodisalar) `payload`
    # da qoladi - ular faqat bitta hodisani ochib ko'rganda kerak.
    #
    # Barchasi NULL bo'lishi mumkin: qurilma hodisalari (`window_blur`
    # va h.k.) ularga umuman ega emas. PostgreSQL'da NULL ustun
    # qo'shish metadata amali, ya'ni partitsiyalangan jadval qayta
    # yozilmaydi.
    duration_ms = models.PositiveIntegerField(blank=True, null=True)
    #: 0-100. Model ishonchi (`confidence`), foizga keltirilgan.
    confidence = models.PositiveSmallIntegerField(default=0)
    #: Qaysi kamera ko'rgan - `primary` yoki `secondary`.
    #
    # AI hodisalarida MAJBURIY yoziladi: ikki kamerali o'rnatishda
    # "kim ko'rdi" savolisiz hodisani tekshirib bo'lmaydi. Stol
    # kamerasidagi telefon va yuz kamerasidagi telefon butunlay
    # boshqa vazn.
    camera_role = models.CharField(max_length=10, blank=True, default="")
    #: ByteTrack izi - bir obyektning bir necha hodisasini bog'laydi.
    track_id = models.PositiveIntegerField(blank=True, null=True)
    #: `EvidenceArtifact` ga havola. FK ATAYLAB EMAS.
    #
    # Bu jadval partitsiyalangan va kuniga milliardlab qator oladi.
    # Partitsiyalangan jadvaldan chiqadigan FK har bir INSERT'da
    # tekshiruv so'rovi qo'shadi va `bulk_create` ning butun ma'nosini
    # yo'qotadi. Yaxlitlik dastur tomonida ta'minlanadi: dalil AVVAL
    # yoziladi, hodisa KEYIN - teskarisida ochilmaydigan havola qoladi
    # (skrinshot yo'lidagi "avval fayl, keyin qator" qoidasi bilan
    # bir xil mantiq).
    evidence_id = models.BigIntegerField(blank=True, null=True)

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
    """
    Har bir yuz tekshiruvi. Chetlashtirish qarori shu log bilan asoslanadi.

    SOLISHTIRISH CLIENTDA bajariladi (`services/face_engine.py`): ikkala
    embedding ham o'sha yerda bo'ladi — etalon FaceID bosqichida
    olingan, jonli vektor esa hozirgi kadrdan. Server chegarani
    (`Setting.faceid_min_score_*`) va oqibatni (hisoblagich,
    chetlashtirish) qo'llaydi. Shuning uchun `source` odatda `client`:
    u "ballni kim hisobladi" degan savolga javob beradi va uni
    bayonnomada ko'rsatib turish shart.

    SESSIYA BO'SH BO'LISHI MUMKIN va bu ataylab. Kirishdagi tekshiruv
    sessiya YARATILISHIDAN oldin bo'ladi: talabgor kamera oldida
    turibdi, sessiya esa faqat moslik tasdiqlangach ochiladi. Ya'ni
    "kira olmadi" holatini sessiyaga bog'lab bo'lmaydi — aynan o'sha
    holat esa eng qimmatli yozuv (boshqa odam urinib ko'rdimi?).
    Shuning uchun sessiyasiz qator `pinfl`, `exam` va `zone` ni O'ZIDA
    saqlaydi: usiz uni na topib, na hudud bo'yicha cheklab bo'lardi.

    RASM QATORDA EMAS, DISKDA. `image_path` — storage ildiziga NISBIY
    yo'l (`ProctoringScreenshot` va `EvidenceArtifact` bilan bir xil
    qoida: ildiz ko'chganda hamma qator bir vaqtda yaroqsiz
    bo'lmasligi va API javobida server strukturasi oshkor
    bo'lmasligi kerak). Muddati `image_purge_after` da — tozalash
    vazifasi siyosatni qayta o'qimasligi kerak, chunki u sessiya
    tugagach o'zgargan bo'lishi mumkin.
    """

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
        "proctoring.ExamSession",
        on_delete=models.CASCADE,
        related_name="face_logs",
        null=True,
        blank=True,
    )

    # --- Sessiyasiz qator uchun kontekst ---
    #
    # Sessiya bor bo'lsa ham to'ldiriladi: qator O'ZI ma'noga ega
    # bo'lishi kerak (`EvidenceArtifact.event_type` bilan bir xil
    # sabab — sessiya anonimlashtirilgach ham "qaysi imtihon, qaysi
    # bino" savoli javobsiz qolmaydi).
    exam = models.ForeignKey(
        "exams.Exam",
        on_delete=models.PROTECT,
        related_name="face_logs",
        null=True,
        blank=True,
    )
    zone = models.ForeignKey(
        "regions.Zone",
        on_delete=models.SET_NULL,
        related_name="face_logs",
        null=True,
        blank=True,
    )
    #: Sessiya anonimlashtirilganda BO'SHATILADI (`purge_expired_artifacts`).
    pinfl = models.CharField(max_length=14, blank=True, default="", db_index=True)

    stage = models.CharField(max_length=16, choices=Stage.choices, default=Stage.PERIODIC)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.CLIENT)

    score = models.PositiveSmallIntegerField(default=0)
    threshold = models.PositiveSmallIntegerField(default=70)
    passed = models.BooleanField(default=False, db_index=True)
    faces_detected = models.PositiveSmallIntegerField(default=1)

    #: S3 yo'li uchun (hozircha ishlatilmaydi, fayl tizimi yo'li ustun).
    image_key = models.CharField(max_length=500, blank=True, default="")
    #: `faceid/{exam}/{session|pending}/...` — storage ildiziga NISBIY.
    image_path = models.CharField(max_length=500, blank=True, default="")
    #: ETALON (pasport) rasmi — FAQAT kirishdagi tekshiruvda.
    #
    # Ilgari u hech qayerda saqlanmasdi: platformadan kelib, client
    # xotirasida solishtirishga ishlatilar va yo'qolardi. Panelda esa
    # ballning O'ZI hech narsani isbotlamaydi — apellyatsiyada
    # "47 ball" degan yozuv emas, IKKI RASM kerak: hujjatdagi odam va
    # kameradagi odam yonma-yon. Shuning uchun kirish tekshiruvida
    # client ikkala kadrni ham yuboradi.
    #
    # Test davomidagi tekshiruvlarda u BO'SH qoladi va bu ataylab:
    # u yerda etalon pasport rasmi emas, kirishda tasdiqlangan kadr
    # va uni har 10 soniyada qayta saqlash bir xil rasmni yuzlab
    # marta diskka yozardi.
    reference_image_path = models.CharField(max_length=500, blank=True, default="")
    image_purge_after = models.DateTimeField(blank=True, null=True, db_index=True)

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
            # Sessiyasiz urinishlar FAQAT shu indeks bo'yicha topiladi:
            # "shu JSHSHIR bugun necha marta urinib, kira olmadi?".
            models.Index(fields=["pinfl", "-occurred_at"], name="idx_facelog_pinfl_time"),
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


class EvidenceArtifact(models.Model):
    """
    Shubhali hodisaning DALILI: kadr yoki qisqa video klip.

    NIMA UCHUN `ProctoringScreenshot` YETMAYDI (ular yonma-yon yashaydi):

      * skrinshot MUNTAZAM olinadi (har 10 s) va u "imtihon qanday
        o'tdi" degan umumiy manzarani beradi; dalil esa HODISAGA
        bog'langan va u "aynan nima ko'rindi" degan savolga javob
        beradi. Ikkalasining hayot sikli, hajmi va saqlash muddati
        boshqacha;
      * dalilda hodisa konteksti bor - qaysi kamera, qaysi model,
        qanday ishonch, qayerda ramka chizilgan. Skrinshot jadvaliga
        bu ustunlarni qo'shish uning har bir qatorini (kuniga
        yuz minglab) bekorga kengaytirardi;
      * dalil VIDEO ham bo'lishi mumkin, skrinshot esa hech qachon.

    IKKI FORMAT, IKKI SAQLASH MUDDATI. Kadr ~150 KB, klip ~1.2 MB -
    ya'ni 500 mashinali bino kuniga ~5 GB klip yig'adi. Ularni bitta
    muddat bilan saqlash diskni klip hisobiga to'ldiradi va kadrlarni
    ham birga olib ketadi. Muddat `ProctoringPolicy` da alohida
    (`evidence_clip_retention_days` / `evidence_frame_retention_days`),
    bu yerda esa allaqachon hisoblangan `purge_after` yotadi -
    tozalash vazifasi siyosatni qayta o'qimasligi kerak (u sessiya
    tugagach o'zgargan bo'lishi mumkin).

    FAYL YO'LI NISBIY - `ProctoringScreenshot` dagi bilan aynan bir xil
    sabab: storage ildizi ko'chganda barcha qatorlar bir vaqtda
    yaroqsiz bo'lmasligi va API javobida server katalog strukturasi
    oshkor bo'lmasligi kerak.

    YOZISH TARTIBI: avval fayl, keyin qator, keyin HODISA. Uchinchisi
    muhim - `ProctoringEvent.evidence_id` FK emas, ya'ni ochilmaydigan
    havoladan DB himoya qilmaydi. Teskari tartibda proktor "dalilni
    ko'rish" tugmasini bosib 404 olardi.
    """

    class Kind(models.TextChoices):
        FRAME = "frame", _("Kadr")
        CLIP = "clip", _("Video klip")

    class Storage(models.TextChoices):
        FS = "fs", _("Fayl tizimi")
        S3 = "s3", _("Obyekt storage")

    id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey(
        "proctoring.ExamSession",
        on_delete=models.CASCADE,
        related_name="evidence",
        verbose_name=_("Sessiya"),
    )
    kind = models.CharField(_("Turi"), max_length=8, choices=Kind.choices, default=Kind.FRAME)
    storage = models.CharField(
        _("Saqlash"), max_length=4, choices=Storage.choices, default=Storage.FS
    )

    #: `{exam_id}/{session_id}/evidence/{captured_at}_{n}.{ext}` - ildizga NISBATAN.
    file_path = models.CharField(_("Fayl yo'li"), max_length=500, blank=True, default="")
    #: S3 yo'li uchun (fayl tizimi rejimida bo'sh qoladi).
    object_key = models.CharField(max_length=500, blank=True, default="")
    content_hash = models.CharField(_("SHA-256"), max_length=64, blank=True, default="", db_index=True)
    size_bytes = models.PositiveIntegerField(_("Hajmi (bayt)"), default=0)
    mime_type = models.CharField(_("MIME turi"), max_length=64, default="image/jpeg")
    width = models.PositiveSmallIntegerField(default=0)
    height = models.PositiveSmallIntegerField(default=0)
    #: Klip uzunligi. Kadr uchun `0`.
    duration_ms = models.PositiveIntegerField(default=0)

    # --- Hodisa konteksti ---
    #
    # `event_type` MATN sifatida takrorlanadi (hodisaga FK yo'q):
    # `ProctoringEvent` partitsiyalangan va unga FK qo'yish
    # `bulk_create` ni buzadi. Takrorlanish ongli - dalil hodisasiz
    # ham ma'noga ega bo'lishi kerak (hodisa retention bilan
    # partitsiyadan chiqib ketishi mumkin, dalil esa qoladi).
    event_type = models.CharField(_("Hodisa turi"), max_length=48, blank=True, default="", db_index=True)
    camera_role = models.CharField(_("Kamera roli"), max_length=10, blank=True, default="")
    confidence = models.PositiveSmallIntegerField(_("Ishonch"), default=0)
    #: `[{"cls": "cell phone", "conf": 0.94, "bbox": [x1,y1,x2,y2], "track_id": 7}]`
    #
    # Ramkalar RASMGA CHIZILMAYDI, alohida saqlanadi. Chizilgan rasm
    # o'zgartirilgan dalil bo'lardi: apellyatsiyada "bu ramkani kim
    # qo'ygan?" degan savolga javob berib bo'lmasdi. Panel ularni
    # rasm ustiga overlay qilib ko'rsatadi va istalgan payt
    # o'chirib qo'yish mumkin.
    boxes = models.JSONField(default=list, blank=True)

    captured_at = models.DateTimeField(_("Olingan vaqti"), db_index=True)
    received_at = models.DateTimeField(auto_now_add=True)
    #: Client yuklashni yakunladimi (S3 presigned PUT yoki multipart).
    is_committed = models.BooleanField(default=False, db_index=True)
    purge_after = models.DateTimeField(blank=True, null=True, db_index=True)

    def __str__(self):
        return f"Evidence<{self.pk}> {self.kind} {self.event_type}"

    class Meta:
        verbose_name = _("Dalil")
        verbose_name_plural = _("Dalillar")
        db_table = "evidence_artifact"
        ordering = ["-captured_at", "-id"]
        constraints = [
            # Fayl yo'li takrorlanmasligi kerak - bir fayl ikki qatorga
            # bog'lansa, birinchi tozalash ikkinchisini ochilmaydigan
            # holga keltiradi. Shartli: S3 rejimida `file_path` bo'sh
            # bo'ladi va bo'sh qatorlar bir-biriga xalaqit bermasligi
            # kerak.
            models.UniqueConstraint(
                fields=["file_path"],
                condition=~models.Q(file_path=""),
                name="unique_evidence_file_path",
            ),
            models.UniqueConstraint(
                fields=["object_key"],
                condition=~models.Q(object_key=""),
                name="unique_evidence_object_key",
            ),
            # Saqlash usuli va yo'l MOS bo'lishi shart: "fayl tizimi,
            # lekin yo'lsiz" qatori tozalash vazifasini jimgina
            # o'tkazib yuborardi va fayl diskda abadiy qolardi.
            models.CheckConstraint(
                condition=(
                    models.Q(storage="fs") & ~models.Q(file_path="")
                    | models.Q(storage="s3") & ~models.Q(object_key="")
                ),
                name="evidence_storage_path_present",
            ),
        ]
        indexes = [
            models.Index(fields=["session", "-captured_at"], name="idx_evidence_session_time"),
            # Retention shu indeks bo'yicha yuradi.
            models.Index(fields=["is_committed", "purge_after"], name="idx_evidence_purge"),
            # "Shu sessiyadagi telefon dalillari" - sessiya kartochkasidagi filtr.
            models.Index(fields=["session", "event_type"], name="idx_evidence_session_type"),
        ]


class LocalRecording(models.Model):
    """
    MASHINADA qoladigan yozuv: ekran videosi yoki kamera klipi.

    NIMA UCHUN FAYL SERVERGA YUBORILMAYDI. Ekran yozuvi 3 soatlik
    imtihonda ~360 MB, kamera klipi ~1-3 MB va ular hodisa sayin
    yig'iladi. 500 mashinali bino kuniga ~500 GB degani - bu hech
    qanday kanalga ham, diskka ham sig'maydi. Skrinshot esa
    avvalgidek YUBORILADI: u ~60 KB va proktorga imtihon davomida,
    real vaqtda kerak.

    Ya'ni bu jadval FAYLNI emas, uning MANZILINI saqlaydi: qaysi
    mashinada, qaysi yo'lda, qancha hajm va davomiylik. Proktor
    yoki tekshiruv komissiyasi shu yozuvga qarab mashinani topadi
    va faylni o'sha yerdan oladi.

    YO'L ABSOLYUT VA BU ISTISNO. `ProctoringScreenshot.file_path` va
    `EvidenceArtifact.file_path` ataylab NISBIY (storage ildizi
    ko'chsa qatorlar yaroqsiz bo'lmasligi uchun) - lekin u yerda
    ildiz BIZNIKI va u bitta. Bu yerda fayl BOSHQA mashinada
    yotibdi va uning ildizi har mashinada boshqacha bo'lishi mumkin
    (eng bo'sh disk tanlanadi). Nisbiy yo'l "qayerdan qidiray?"
    degan savolni javobsiz qoldirardi.

    MASHINA BELGISI QATORDA TAKRORLANADI (`machine_mac`,
    `device_id`). Sessiyadan ham topsa bo'lardi, lekin yozuv
    sessiyadan UZOQROQ yashaydi: hodisalar partitsiyadan chiqib
    ketadi, qurilma boshqa binoga ko'chiriladi, sessiya esa
    retention bilan tozalanadi. Faylni topish uchun kerak bo'lgan
    ma'lumot yozuvning O'ZIDA qolishi kerak.
    """

    class Kind(models.TextChoices):
        SCREEN = "screen", _("Ekran yozuvi")
        CLIP = "clip", _("Kamera klipi")

    id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey(
        "proctoring.ExamSession",
        on_delete=models.CASCADE,
        related_name="local_recordings",
        verbose_name=_("Sessiya"),
    )
    kind = models.CharField(
        _("Turi"), max_length=8, choices=Kind.choices, default=Kind.SCREEN, db_index=True
    )

    #: Mashinadagi TO'LIQ yo'l (`D:\ProctoringArchive\...\screen.mp4`).
    local_path = models.CharField(_("Mashinadagi yo'l"), max_length=500)
    size_bytes = models.BigIntegerField(_("Hajmi (bayt)"), default=0)
    duration_ms = models.PositiveIntegerField(_("Davomiyligi (ms)"), default=0)
    width = models.PositiveSmallIntegerField(default=0)
    height = models.PositiveSmallIntegerField(default=0)
    #: Yozilgan kadrlar soni va tashlab yuborilganlari - yozuv
    #: sifatining o'lchovi. Ko'p tashlangan kadr "mashina yetishmadi"
    #: degani va u apellyatsiyada javob bo'ladi.
    frames = models.PositiveIntegerField(default=0)
    frames_dropped = models.PositiveIntegerField(default=0)

    # --- Qaysi mashinada ---
    device_id = models.CharField(_("Qurilma"), max_length=64, blank=True, default="", db_index=True)
    machine_mac = models.CharField(_("MAC manzil"), max_length=32, blank=True, default="")

    # --- Klip konteksti (ekran yozuvida bo'sh) ---
    #
    # `EvidenceArtifact` dagi bilan bir xil maydonlar va bu ongli
    # takrorlanish: klip endi ikki joyda bo'lishi mumkin - eski
    # o'rnatishlarda serverda, yangisida mashinada. Panel ikkalasini
    # bir xil ko'rsatishi kerak.
    event_type = models.CharField(_("Hodisa turi"), max_length=48, blank=True, default="", db_index=True)
    camera_role = models.CharField(_("Kamera roli"), max_length=10, blank=True, default="")
    confidence = models.PositiveSmallIntegerField(_("Ishonch"), default=0)

    captured_at = models.DateTimeField(_("Olingan vaqti"), db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"LocalRecording<{self.pk}> {self.kind} {self.local_path}"

    @property
    def file_url(self) -> str:
        """
        `file://` ko'rinishi - panelda nusxalash uchun.

        Brauzer uni OCHA OLMAYDI (xavfsizlik cheklovi) va bu
        kutilgan: manzil odam uchun, mashinani topib borish uchun.
        """
        if not self.local_path:
            return ""
        return "file:///{}".format(self.local_path.replace("\\", "/").lstrip("/"))

    class Meta:
        verbose_name = _("Mashinadagi yozuv")
        verbose_name_plural = _("Mashinadagi yozuvlar")
        db_table = "local_recording"
        ordering = ["-captured_at", "-id"]
        constraints = [
            # Bitta fayl - bitta qator. Client qayta urinishi (tarmoq
            # xatosi) ikkinchi qator yaratmasligi kerak: panelda u
            # "ikkita yozuv bor" bo'lib ko'rinardi.
            models.UniqueConstraint(
                fields=["session", "local_path"], name="unique_local_recording_path"
            ),
        ]
        indexes = [
            models.Index(fields=["session", "-captured_at"], name="idx_localrec_session"),
        ]


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
        # Kamera kredensiali desktop client'ga berildi.
        #
        # Bu YOZUV MAJBURIY: RTSP paroli kameraning ichida yashaydi va
        # uni serverdan bekor qilib bo'lmaydi. Ya'ni "kim, qachon,
        # qaysi mashinada, qaysi kameraning kalitini oldi" degan
        # savolga javob beradigan yagona manba shu jurnal - parol
        # sizib chiqqan taqdirda tergov faqat shu yerdan boshlanadi.
        CAMERA_CREDENTIAL_ISSUE = "camera_credential_issue", _("Kamera kredensiali berildi")
        CAMERA_LIVE_VIEW = "camera_live_view", _("Kamera tasviri ko'rildi")
        # Kuzatuv ishga tushdi - imtihonning haqiqiy boshlanish nuqtasi.
        #
        # Aynan shu yozuv "imtihon qanday sharoitda boshlandi" degan
        # savolga javob beradi: kamera tekshiruvi qanday holatda edi,
        # qanday unumdorlik profili ishladi. Apellyatsiyada "kuzatuv
        # to'liq ishlaganmi?" degan savol shu yerdan boshlanadi.
        #
        # YAKUNLASH audit'ga TUSHMAYDI: u har bir sessiyada bo'ladi
        # va jurnalni shovqinga aylantirardi; sessiyaning yakunlangani
        # `ExamSession.finished_at` da allaqachon bor.
        PROCTORING_START = "proctoring_start", _("Kuzatuv boshlandi")
        # Dalil (kadr yoki video klip) ochib ko'rildi.
        #
        # Talabgorning tasviriga har bir kirish qayd etiladi: bu
        # shaxsiy ma'lumot va unga kirish faktining o'zi tekshirilishi
        # kerak bo'lgan harakat.
        EVIDENCE_VIEW = "evidence_view", _("Dalil ko'rildi")
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
