from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _

from apps.common.models import SoftDeleteModel, TimeStampedModel


def validate_heartbeat_interval(value):
    """
    Heartbeat oralig'i `HEARTBEAT_TIMEOUT` ning YARMIDAN oshmasin.

    Server sessiyani `HEARTBEAT_TIMEOUT` (standart 90 s) davomida
    heartbeat kelmasa "aloqa yo'q" deb ko'rsatadi. Oraliq undan katta
    yoki unga yaqin bo'lsa, ishlab turgan client ham panelda o'chib-
    yonib turardi. Chegara sozlamadan o'qiladi (qadab qo'yilmagan):
    timeout o'zgarsa, ruxsat etilgan oraliq ham u bilan birga siljiydi.
    """
    limit = int(settings.PROCTORING["HEARTBEAT_TIMEOUT"]) // 2
    if value > limit:
        raise ValidationError(
            _("Heartbeat oralig'i %(limit)s soniyadan oshmasligi kerak "
              "(server %(timeout)s s kutadi)"),
            params={"limit": limit, "timeout": limit * 2},
        )


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
    # Xavf balliga qo'shiladigan qiymat (0-100).
    #
    # `severity` dan ALOHIDA va bu ataylab: jiddiylik "hodisa qanchalik
    # tez yozilsin va proktorga ko'rsatilsinmi" degan TEXNIK savolni
    # hal qiladi (>= HIGH buferni chetlab o'tadi), og'irlik esa
    # "talabgorning xavf balliga qancha qo'shilsin" degan MAZMUNIY
    # savolni. Telefon va kitob ikkalasi ham `HIGH` bo'lishi mumkin,
    # lekin telefon xavfliroq — birinchisi tashqi aloqa, ikkinchisi
    # faqat ma'lumot.
    risk_weight = models.PositiveSmallIntegerField(
        _("Xavf og'irligi"), default=15,
        help_text=_("Aniqlanganda xavf balliga qo'shiladi (0-100)"),
    )
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
    """
    Aniqlanishi kerak bo'lgan dastur (AnyDesk, TeamViewer, VirtualBox...).

    FAQAT `process_names` YETARLI EMAS va bu amaliyotda ko'rindi:
    `AnyDesk.exe` ni `notepad.exe` deb qayta nomlash bir soniyalik ish,
    ya'ni fayl nomi bo'yicha qidiradigan ro'yxat eng sodda chetlab
    o'tishga ham dosh bermaydi. Shuning uchun qator qayta nomlash
    O'ZGARTIRMAYDIGAN belgilarni ham saqlaydi:

        publishers          — Authenticode imzosidagi egasining nomi
        original_filenames  — PE resursidagi `OriginalFilename`
        products            — `ProductName` / `FileDescription`
        service_names       — Windows xizmati nomi (oynasiz qism)
        ports               — tinglanadigan TCP portlar

    Client'da AYNAN SHU tuzilmadagi ichki katalog bor
    (`client/services/threat_rules.py`) va u imzo, resurs, xizmat va
    port bo'yicha qidiradi. Bu jadval uni ALMASHTIRMAYDI, QO'SHADI:
    yangi dasturni 500 mashinaga tarqatish uchun client'ni qayta
    yig'ish shart emas.

    `is_blocking` STANDART `False` va bu ataylab. Ichki katalogdagi
    yozuvlar tekshirilgan, panelga esa ixtiyoriy qiymat yozilishi
    mumkin — shu jumladan muassasaning o'z dasturiga to'g'ri
    keladigani. Bunday yozuv butun imtihonni bloklab qo'ymasligi
    kerak: dastur baribir yopiladi va hodisa yoziladi.
    """

    class Category(models.TextChoices):
        REMOTE = "remote", _("Masofaviy boshqaruv")
        VM = "vm", _("Virtual mashina")
        TOOL = "tool", _("Yordamchi vosita")

    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=100, unique=True)
    #: Toifa hodisa TURINI belgilaydi: `rdp_detected` / `vm_detected` /
    #: `process_blacklisted`. Frontendda ular har xil turkumga tushadi
    #: (`utils/events.js`), ya'ni jonli kuzatuvda ajralib turadi.
    category = models.CharField(
        _("Toifa"), max_length=16, choices=Category.choices, default=Category.REMOTE
    )
    process_names = models.JSONField(default=list, blank=True)
    publishers = models.JSONField(
        _("Imzo egalari"), default=list, blank=True,
        help_text=_("Sertifikatdagi tashkilot nomi, masalan: AnyDesk Software GmbH"),
    )
    original_filenames = models.JSONField(
        _("OriginalFilename"), default=list, blank=True,
        help_text=_("PE resursidagi asl nom — faylni qayta nomlash unga ta'sir qilmaydi"),
    )
    products = models.JSONField(
        _("Mahsulot nomlari"), default=list, blank=True,
        help_text=_("ProductName / FileDescription ichidan qism satr bo'yicha qidiriladi"),
    )
    service_names = models.JSONField(
        _("Windows xizmatlari"), default=list, blank=True,
        help_text=_("Oynasiz qism shu yerda yashaydi; xizmatsiz jarayonni o'ldirish foydasiz"),
    )
    ports = models.JSONField(
        _("Portlar"), default=list, blank=True,
        help_text=_("Tinglanadigan TCP portlar — resursi va imzosi tozalangan binar uchun"),
    )
    is_blocking = models.BooleanField(
        _("Imtihonni to'sadi"), default=False,
        help_text=_("Yopib bo'lmasa imtihon boshlanmaydi"),
    )
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
    #: Chegara ballari — `max(0, cosine) * 100` shkalasida
    #: (`common/utils/vectors.py:similarity_score`).
    #
    # 40 = cosine 0.40 va bu ArcFace/`buffalo_l` uchun amaliy chegara:
    # bir xil odamning hujjat rasmi va jonli kadri odatda 0.40-0.70
    # oralig'ida bo'ladi (yorug'lik, yosh farqi, ko'zoynak ta'sir
    # qiladi), butunlay boshqa odam esa 0.00-0.15.
    #
    # Ilgari bu yerda 70 turardi, lekin BOSHQA shkalada
    # (`(cos+1)/2*100`) — o'sha 70 aynan hozirgi 40 ga teng edi.
    # Mavjud profillar migratsiya bilan ko'chirildi
    # (`controls.0008_score_scale`).
    faceid_min_score_student = models.PositiveSmallIntegerField(_("Min ball (talabgor)"), default=40)
    faceid_min_score_exam = models.PositiveSmallIntegerField(_("Min ball (test)"), default=40)
    # Client hisoblagan embedding'ni serverda tasodifiy qayta tekshirish ulushi.
    # Clientga to'liq ishonib bo'lmaydi — bu statistik nazorat.
    #: HOZIRCHA ISHLATILMAYDI.
    #
    # Solishtirish clientda bajariladi va serverga faqat ball keladi;
    # uni qayta hisoblash uchun rasmdan embedding olish, ya'ni
    # serverda ML runtime kerak. Maydon olib tashlanmadi: alohida GPU
    # servisi qo'shilganda shartnoma o'zgarmasligi kerak, o'chirilsa
    # esa mavjud profillardagi qiymat yo'qolardi.
    faceid_audit_rate = models.FloatField(_("Server auditi ulushi"), default=0.05)

    # --- FaceID: kirish tekshiruvi OQIMI (client) ---
    #
    # Ilgari bu to'rttasi har bir mashinaning `.env` ida yashardi
    # (`FACE_GUIDE_SECONDS`, `FACE_MATCH_STREAK`, ...). Ular apparatga
    # emas, IMTIHON QOIDASIGA tegishli: "talabgor qancha kutsin, necha
    # kadrdan keyin qaror qilinsin" - buni 500 mashinada qo'lda
    # tahrirlash imkonsiz, bir binoda ikki xil qiymat esa bir xil
    # talabgorga ikki xil natija berardi. `.env` dagi qiymat endi faqat
    # ZAXIRA (sozlama kelmagan holat uchun).
    faceid_guide_seconds = models.PositiveSmallIntegerField(
        _("Joylashish sanog'i (s)"), default=5,
        validators=[MaxValueValidator(30)],
        help_text=_("Kamera ochilgach yuzni ovalga joylash vaqti; 0 - sanoqsiz"),
    )
    faceid_match_streak = models.PositiveSmallIntegerField(
        _("Tasdiq uchun ketma-ket kadr"), default=3,
        validators=[MinValueValidator(1), MaxValueValidator(30)],
        help_text=_("Shuncha ketma-ket kadr mos kelsa - shaxs tasdiqlanadi"),
    )
    # Urinish yopilishi uchun IKKALASI ham kerak (kadr soni VA vaqt) -
    # temporal qatlamdagi "bitta kadr hech qachon qaror emas" qoidasi.
    # Shuning uchun vaqtning pastki chegarasi 1: `0` qoidani faqat kadr
    # soniga tushirardi va tez kamerada 2-3 soniyada xulosa chiqardi.
    faceid_fail_streak = models.PositiveSmallIntegerField(
        _("Rad uchun ketma-ket kadr"), default=15,
        validators=[MinValueValidator(1), MaxValueValidator(300)],
        help_text=_("Shuncha ketma-ket kadr mos kelmasa (va vaqt o'tsa) - urinish yopiladi"),
    )
    faceid_fail_min_seconds = models.PositiveSmallIntegerField(
        _("Rad uchun minimal vaqt (s)"), default=8,
        validators=[MinValueValidator(1), MaxValueValidator(120)],
        help_text=_("Urinish shu vaqtdan oldin muvaffaqiyatsiz deb yopilmaydi"),
    )

    # --- FaceID: test davomida yuz JUDA UZOQ (client `face_presence`) ---
    #
    # Yuz kadrda bor, lekin solishtirish uchun kichik - davriy tekshiruv
    # "solishtirib bo'lmadi" deydi va serverga hech narsa yubormaydi.
    # Usiz talabgor kameradan uzoq o'tirib shaxs tekshiruvini jimgina
    # chetlab o'tardi. Chegaralar `ProctoringPolicy` da EMAS: bu AI
    # o'chiq yo'lning qoidasi, siyosat esa o'sha paytda ko'pincha yo'q.
    faceid_far_warn_s = models.PositiveSmallIntegerField(
        _("Yuz uzoqda — ogohlantirish (s)"), default=10,
        validators=[MinValueValidator(1), MaxValueValidator(600)],
        help_text=_("Shuncha uzluksiz uzoq o'tirsa - past jiddiylikdagi hodisa"),
    )
    faceid_far_unverified_s = models.PositiveSmallIntegerField(
        _("Yuz uzoqda — shaxs tasdiqlanmadi (s)"), default=120,
        validators=[MinValueValidator(1), MaxValueValidator(3600)],
        help_text=_("Shuncha vaqt shaxsni solishtirib bo'lmasa - o'rta jiddiylikdagi hodisa"),
    )

    # --- Qurilma ---
    # Standart `True` (`controls.0012_client_runtime_settings`). Ilgari
    # maydon bor edi, lekin client uni O'QIMASDI va ekranni `.env` dagi
    # `SCREEN_RECORD_ENABLED` (standart `true`) bo'yicha yozardi - ya'ni
    # paneldagi "o'chiq" haqiqatni aytmasdi. Endi qaror shu yerda va
    # migratsiya mavjud profillarni AMALDAGI xulqqa (yozuv yoqilgan)
    # keltirdi: aks holda yangilanish jimgina dalilni o'chirib qo'yardi.
    is_screen_record = models.BooleanField(_("Ekranni yozish"), default=True)
    # Ekran yozuvi hajm bilan kelishuv (o'lchangan, mp4v, 3 soat):
    # 1280@1 ~110 MB ("qotib-qotib"), 1600@5 ~550 MB (standart),
    # 1280@8 ~730 MB (5 FPS dan sezilarli silliq emas). Kenglikni
    # pasaytirish dalilni yo'qotadi - kichik shriftli savol o'qilmaydi.
    screen_record_fps = models.PositiveSmallIntegerField(
        _("Ekran yozuvi FPS"), default=5,
        validators=[MinValueValidator(1), MaxValueValidator(15)],
    )
    screen_record_width = models.PositiveSmallIntegerField(
        _("Ekran yozuvi kengligi (px)"), default=1600,
        validators=[MinValueValidator(640), MaxValueValidator(3840)],
    )
    # ULUSH foizda (piksel emas): qat'iy piksel yozuv kengligi
    # o'zgarganda nisbatni buzardi. 12% da 1600 px yozuvda ~192x144 -
    # yuz tanib olinadi, test sahifasi deyarli yopilmaydi.
    screen_record_pip_percent = models.PositiveSmallIntegerField(
        _("Yozuvdagi kamera oynasi (%)"), default=12,
        validators=[MinValueValidator(5), MaxValueValidator(30)],
        help_text=_("Kamera tasviri kengligi - yozuv kengligiga nisbatan"),
    )
    # Skrinshot OSTIGA qo'shiladigan kamera tasmasi
    # (`client/services/camera_overlay.py`). Har skrinshotni ~24% ga
    # og'irlashtiradi - trafik masalasi, ya'ni imtihon qarori.
    is_screenshot_camera_overlay = models.BooleanField(
        _("Skrinshotga kamera kadri"), default=True,
    )
    screenshot_pip_percent = models.PositiveSmallIntegerField(
        _("Skrinshotdagi kamera ramkasi (%)"), default=16,
        validators=[MinValueValidator(5), MaxValueValidator(40)],
        help_text=_("Ramka kengligi - skrinshot kengligiga nisbatan"),
    )
    is_detect_monitor = models.BooleanField(_("Monitor tekshiruvi"), default=True)
    is_detect_camera = models.BooleanField(_("Kamera tekshiruvi"), default=True)
    # SKRINSHOT TAYMER BILAN OLINMAYDI - faqat test platformasi buyurganda
    # (javob belgilandi -> client lokal xizmatiga `POST /api/capture_screen`).
    # Shuning uchun interval ham, dedup ham yo'q (`controls.0013`): har
    # kadr ma'noli lahza. Kadr mashinada HAR DOIM saqlanadi; bu bayroq
    # faqat "serverga ham yuborilsinmi" savoli (trafik, server diski).
    is_screenshot_upload = models.BooleanField(
        _("Skrinshotni serverga yuborish"), default=True,
        help_text=_("O'chiq bo'lsa skrinshot faqat client mashinasida saqlanadi"),
    )
    # 1920/80: ekran o'z o'lchamida qoladi. Ilgari 960/65 edi va 1920 li
    # ekranda test matni ~6 px harfga aylanib, O'QILMASDI — skrinshot
    # dalil sifatida ma'nosini yo'qotardi. Xiralikning asosiy sababi
    # kichraytirish, sifat ikkinchi darajali (o'lchangan: 960/65 ~42 KB,
    # 1920/80 ~157 KB — optimallashtirilgan progressiv JPEG bilan).
    screenshot_quality = models.PositiveSmallIntegerField(_("Skrinshot sifati"), default=80)
    screenshot_max_width = models.PositiveSmallIntegerField(_("Maks. kenglik"), default=1920)

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
    # Topilgan, lekin yo'q qilib bo'lmagan tahdid (admin huquqi yetmay
    # xizmat to'xtamadi) imtihonni TO'SADIMI. Ilgari `.env` dagi
    # `THREAT_BLOCK_EXAM` edi: bu mashina xususiyati emas, IMTIHON
    # SIYOSATI - qaror "Davom etish" bosilganda, imtihon profili
    # kelgandan keyin qabul qilinadi (`policy.check_readiness`).
    # Skanerning o'zi (yoqilishi, ruxsat ro'yxati, VDI) esa `.env` da
    # qoladi: u Qt'dan va serverdan OLDIN ishga tushadi.
    is_threat_block_exam = models.BooleanField(
        _("Yo'q qilinmagan tahdid imtihonni to'sadi"), default=True,
    )

    # --- Texnik muammolar ---
    is_enable_check_tp = models.BooleanField(_("Texnik muammoni tekshirish"), default=True)

    # --- Tarmoq ---
    # Chegara `HEARTBEAT_TIMEOUT` ning yarmi (`validate_heartbeat_interval`):
    # bitta kechikkan heartbeat sessiyani panelda "aloqa yo'q" qilmasligi
    # kerak. Client bu qiymatni O'QIYDI (ilgari `.env` dagi qadab
    # qo'yilgan 30 s ishlardi va paneldagi maydon hech narsani
    # o'zgartirmasdi).
    heartbeat_interval = models.PositiveSmallIntegerField(
        _("Heartbeat intervali (s)"), default=30,
        validators=[MinValueValidator(5), validate_heartbeat_interval],
    )
    event_batch_interval = models.PositiveSmallIntegerField(
        _("Event batch intervali (s)"), default=5,
        validators=[MinValueValidator(1), MaxValueValidator(60)],
    )
    # Tarmoq uzilganda client RAM'da shuncha hodisani ushlaydi (eng
    # eskisi tushib qoladi). Imtihon mashinasi ko'pincha 4 GB.
    offline_buffer_size = models.PositiveIntegerField(
        _("Offline buffer hajmi"), default=5000,
        validators=[MinValueValidator(100), MaxValueValidator(50000)],
    )

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


# --------------------------------------------------------------------------
# AI proktorlik
# --------------------------------------------------------------------------
class ProctoringPolicy(TimeStampedModel):
    """
    Kompyuter ko'ruvi (AI) siyosati — `Setting` ning davomi.

    NIMA UCHUN ALOHIDA MODEL, `Setting` ga maydon qo'shish emas:

      * `Setting` allaqachon 30 dan ortiq maydonga ega va u client
        XULQINI tasvirlaydi (skrinshot oralig'i, bloklangan tugmalar,
        heartbeat). Bu yerdagi maydonlar esa boshqa savolga javob
        beradi — "kamera nimani ko'radi va qachon shubha deb ataladi".
        Bitta jadvalda ular 60 ta ustun bo'lib qo'shilib ketardi va
        admin formasi o'qib bo'lmas holga kelardi;
      * bu qiymatlarni O'ZGARTIRISH huquqi ham boshqacha: skrinshot
        oralig'ini o'zgartirish — operatsion qaror, xavf og'irligini
        pasaytirish esa chetlashtirish statistikasiga bevosita ta'sir
        qiladi;
      * `OneToOne` tanlangani uchun imtihonga bog'lanish TEKIN keladi:
        `Exam.setting` allaqachon bor, ya'ni "SAT uchun ikki kamera,
        mashq testi uchun bitta" talabi hech qanday yangi
        bog'lanishsiz ishlaydi.

    Siyosat YO'Q bo'lsa — bu "AI o'chirilgan" degani emas, "standart
    qiymatlar" degani (`controls.services._default_proctoring`). Aks
    holda yangi `Setting` yaratgan administrator kuzatuvni bilmagan
    holda o'chirib qo'yardi.
    """

    class CameraKind(models.TextChoices):
        AUTO = "auto", _("Ixtiyoriy (biriktirishga qarab)")
        LOCAL = "local", _("Lokal veb-kamera")
        IP = "ip", _("IP kamera")

    class CameraLostAction(models.TextChoices):
        WARN = "warn", _("Ogohlantirish")
        PAUSE = "pause", _("Imtihonni to'xtatib turish")
        TERMINATE = "terminate", _("Chetlashtirish")

    class GpuProfile(models.TextChoices):
        AUTO = "auto", _("Avtomatik (client aniqlaydi)")
        HIGH = "high", _("Yuqori")
        MEDIUM = "medium", _("O'rta")
        LOW = "low", _("Past")
        CPU = "cpu", _("Faqat CPU")
        # Client'dagi eng past profil: YOLO va poza umuman
        # ishga tushmaydi, faqat yuz tekshiruvi qoladi. U
        # avtomatik tanlovda ham bor (4 GB RAM li mashina) va
        # ro'yxatda bo'lmasa administrator zaif mashinani
        # oldindan shu rejimga qo'ya olmasdi.
        MINIMAL = "minimal", _("Minimal (faqat yuz)")

    setting = models.OneToOneField(
        "controls.Setting",
        verbose_name=_("Sozlama profili"),
        on_delete=models.CASCADE,
        related_name="proctoring",
    )
    is_enabled = models.BooleanField(_("AI proktorlik yoqilgan"), default=False)

    # --- Kamera ---
    camera_count = models.PositiveSmallIntegerField(_("Kameralar soni"), default=1)
    primary_camera_kind = models.CharField(
        _("Birlamchi kamera turi"), max_length=8,
        choices=CameraKind.choices, default=CameraKind.AUTO,
    )
    secondary_camera_kind = models.CharField(
        _("Ikkilamchi kamera turi"), max_length=8,
        choices=CameraKind.choices, default=CameraKind.AUTO,
    )
    primary_required = models.BooleanField(_("Birlamchi majburiy"), default=True)
    secondary_required = models.BooleanField(_("Ikkilamchi majburiy"), default=False)
    # Virtual kamera (OBS, ManyCam, Snap) — oldindan yozilgan videoni
    # jonli oqim sifatida ko'rsatishning eng oson yo'li. Standart holda
    # taqiqlangan; ayrim markazlarda drayver darajasidagi virtual
    # qurilma qonuniy ishlatilishi mumkin, shuning uchun sozlama.
    allow_virtual_camera = models.BooleanField(_("Virtual kameraga ruxsat"), default=False)

    min_fps = models.PositiveSmallIntegerField(_("Minimal FPS"), default=12)
    min_width = models.PositiveSmallIntegerField(_("Minimal kenglik"), default=640)
    min_height = models.PositiveSmallIntegerField(_("Minimal balandlik"), default=480)
    # Kamera uzilgach shuncha soniya HECH QANDAY chora ko'rilmaydi.
    #
    # USB kamera qayta ulanishi, RTSP oqimining tiklanishi va drayver
    # qayta yuklanishi 10–20 soniya oladi. Bu oynasiz har bir vaqtinchalik
    # uzilish chetlashtirishga aylanardi — proktorlikda eng qimmat
    # xato turi (aybsiz talabgor).
    camera_lost_grace_s = models.PositiveSmallIntegerField(
        _("Kamera uzilishiga chidam (s)"), default=30
    )
    camera_lost_action = models.CharField(
        _("Kamera uzilganda"), max_length=10,
        choices=CameraLostAction.choices, default=CameraLostAction.WARN,
    )

    # --- AI modullari ---
    enable_identity = models.BooleanField(_("Shaxs (FaceID)"), default=True)
    enable_objects = models.BooleanField(_("Obyekt aniqlash (YOLO)"), default=True)
    enable_pose = models.BooleanField(_("Poza va qo'llar"), default=False)
    enable_gaze = models.BooleanField(_("Nigoh va bosh holati"), default=True)
    enable_tracking = models.BooleanField(_("Obyekt kuzatuvi (ByteTrack)"), default=True)

    # Har bir modul uchun ALOHIDA chastota.
    #
    # Bitta umumiy FPS ishlamaydi: ArcFace kadri 112x112 (arzon), YOLO
    # 640x640 (qimmat), poza esa oraliqda. Ularni bitta tezlikda
    # yuritish GPU'ni eng qimmatiga qarab cheklaydi va arzonlari
    # bekorga sekinlashadi. `0` — modul o'sha profilda umuman
    # ishlamaydi (client apparatga qarab pasaytirishi mumkin).
    identity_fps = models.PositiveSmallIntegerField(_("Shaxs FPS"), default=10)
    object_fps = models.PositiveSmallIntegerField(_("Obyekt FPS"), default=6)
    pose_fps = models.PositiveSmallIntegerField(_("Poza FPS"), default=8)
    gaze_fps = models.PositiveSmallIntegerField(_("Nigoh FPS"), default=10)
    gpu_profile_override = models.CharField(
        _("Unumdorlik profili"), max_length=8,
        choices=GpuProfile.choices, default=GpuProfile.AUTO,
        help_text=_("`auto` — client apparatni o'zi aniqlaydi"),
    )

    # --- Temporal chegaralar ---
    #
    # BITTA KADR HECH QACHON QAROR EMAS. Bu butun tizimning asosiy
    # qoidasi: yolg'on ijobiy natija (aybsiz talabgorni ayblash)
    # o'tkazib yuborilgan buzilishdan qimmatroq. Shuning uchun har bir
    # hodisa turi uchun "qancha vaqt davom etsa e'tiborga olinadi"
    # degan chegara bor va u sozlanadi.
    no_face_warn_s = models.PositiveSmallIntegerField(_("Yuz yo'q — ogohlantirish (s)"), default=2)
    no_face_suspicious_s = models.PositiveSmallIntegerField(_("Yuz yo'q — shubha (s)"), default=5)
    gaze_away_warn_s = models.PositiveSmallIntegerField(_("Nigoh chetda — ogohlantirish (s)"), default=2)
    gaze_away_suspicious_s = models.PositiveSmallIntegerField(_("Nigoh chetda — shubha (s)"), default=5)

    object_min_frames = models.PositiveSmallIntegerField(_("Obyekt: min kadr"), default=5)
    object_min_conf = models.FloatField(_("Obyekt: min ishonch"), default=0.80)
    object_min_duration_ms = models.PositiveIntegerField(_("Obyekt: min davomiylik (ms)"), default=1200)

    # Turli modullardan kelgan hodisalar shu oyna ichida bo'lsa —
    # birlashtirilishi mumkin ("telefon" + "pastga qaradi" + "qo'l
    # telefon yonida" = yuqori shubha).
    fusion_window_ms = models.PositiveIntegerField(_("Birlashtirish oynasi (ms)"), default=3000)

    # --- Xavf balli ---
    #
    # Ball CHEKSIZ o'smasligi kerak: bitta uzoq davom etgan holat
    # (masalan kamera burchagi noto'g'ri va yuz vaqti-vaqti bilan
    # yo'qoladi) talabgorni 100 ballga olib chiqib, haqiqiy
    # buzilishlarni ko'rinmas qilib qo'yardi.
    risk_decay_per_min = models.PositiveSmallIntegerField(_("Ball pasayishi (daq)"), default=5)
    risk_event_cooldown_s = models.PositiveSmallIntegerField(
        _("Bir xil hodisa oralig'i (s)"), default=60,
        help_text=_("Shu oraliq ichidagi takror hodisa ballga qo'shilmaydi"),
    )
    threshold_low = models.PositiveSmallIntegerField(_("Past chegara"), default=20)
    threshold_medium = models.PositiveSmallIntegerField(_("O'rta chegara"), default=40)
    threshold_high = models.PositiveSmallIntegerField(_("Yuqori chegara"), default=70)

    # --- Dalil ---
    evidence_enabled = models.BooleanField(_("Dalil to'plash"), default=True)
    # Hodisadan OLDIN va KEYIN olinadigan soniyalar. Oldingi qism halqa
    # buferdan keladi: hodisa tasdiqlanganda unga qadar bo'lgan kadrlar
    # allaqachon o'tib ketgan bo'ladi va aynan ular eng qimmatli —
    # telefonni chiqarish harakati hodisadan OLDIN bo'ladi.
    evidence_clip_seconds = models.PositiveSmallIntegerField(_("Klip uzunligi (s)"), default=5)
    evidence_min_severity = models.PositiveSmallIntegerField(_("Min jiddiylik"), default=2)
    # Kadr va klip uchun retention ALOHIDA: klip kadrdan ~10 barobar
    # katta va fayl tizimida saqlanadi (`SCREENSHOT_STORAGE` bilan bir
    # xil disk). 500 client x 3 soat x 8 hodisa ~ 5 GB/kun/bino —
    # 90 kunlik saqlash 450 GB degani.
    evidence_clip_retention_days = models.PositiveSmallIntegerField(_("Klip saqlash (kun)"), default=30)
    evidence_frame_retention_days = models.PositiveSmallIntegerField(_("Kadr saqlash (kun)"), default=90)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self._invalidate()

    def delete(self, *args, **kwargs):
        """
        O'CHIRISHDA HAM kesh tozalanadi.

        `save()` bilan bir xil sabab, lekin oqibati jiddiyroq: siyosat
        o'chirilganda profil standart qiymatlarga qaytishi kerak
        (`_default_proctoring`, ya'ni `enabled=False`). Kesh
        tozalanmasa, client 5 daqiqa davomida ALLAQACHON YO'Q
        siyosat bo'yicha ishlab turardi — "ikkinchi kamera majburiy"
        talabi o'chirilgan bo'lsa ham imtihonni bloklab turaverardi.
        """
        setting = self.setting
        super().delete(*args, **kwargs)
        self._invalidate(setting)

    def _invalidate(self, setting=None) -> None:
        # Kesh `Setting` kalitida yotadi (`controls.services._cache_key`),
        # ya'ni siyosat o'zgarganda ham o'sha kalit tozalanishi kerak —
        # aks holda client 5 daqiqa davomida eski AI sozlamasi bilan
        # ishlab turadi.
        from apps.controls.services import invalidate_setting_cache

        invalidate_setting_cache(setting or self.setting)

    def __str__(self):
        return f"{self.setting.name} — proktorlik siyosati"

    class Meta:
        db_table = "proctoring_policy"
        verbose_name = _("Proktorlik siyosati")
        verbose_name_plural = _("Proktorlik siyosatlari")
        ordering = ["setting__name"]
        constraints = [
            # Chegaralar o'sish tartibida bo'lishi SHART. Aks holda
            # "o'rta" chegarasi "past" dan kichik bo'lib qolsa, xavf
            # darajasi hisoblab bo'lmaydigan holatga tushadi va bu
            # jimgina yuz beradi — panelda deyarli har bir sessiya
            # "yuqori" ko'rinardi.
            models.CheckConstraint(
                condition=models.Q(threshold_low__lt=models.F("threshold_medium"))
                & models.Q(threshold_medium__lt=models.F("threshold_high")),
                name="proctoring_policy_thresholds_ordered",
            ),
            models.CheckConstraint(
                condition=models.Q(camera_count__gte=1) & models.Q(camera_count__lte=2),
                name="proctoring_policy_camera_count",
            ),
        ]


class EventRiskWeight(TimeStampedModel):
    """
    Hodisa turi -> xavf balliga qo'shiladigan og'irlik.

    Ilgari bu jadval KODDA yotardi (`proctoring/services/ingest.py`
    dagi `RISK_WEIGHTS`) va uni o'zgartirish reliz talab qilardi.
    Amalda esa og'irliklar aynan ekspluatatsiya davomida sozlanadi:
    birinchi imtihon mavsumidan keyin ma'lum bo'ladiki, masalan
    `window_blur` juda tez-tez uchraydi va uning og'irligi haqiqiy
    buzilishlarni ko'mib yuboryapti.

    Kod ichidagi qiymatlar ZAXIRA sifatida QOLADI: bu jadval bo'sh
    bo'lsa yoki kesh/DB javob bermasa, tizim eski xulqda ishlaydi.
    "Sozlanmagan tizim ballni umuman hisoblamaydi" holati bo'lmasligi
    kerak — u chetlashtirish qarorini asossiz qoldirardi.
    """

    event_type = models.CharField(_("Hodisa turi"), max_length=48, unique=True)
    weight = models.PositiveSmallIntegerField(_("Og'irlik"), default=5)
    # JIDDIYLIK BU YERDA YO'Q va bu ataylab (`0011_drop_risk_weight_severity`).
    # Uning egasi — client: yuz 2 soniya yo'q va 20 soniya yo'q bir xil
    # hodisa turi, lekin har xil jiddiylik. Ilgari `severity` ustuni
    # bor edi, lekin hech qayerda o'qilmasdi — administrator uni
    # o'zgartirib, hech narsa o'zgarmaganini ko'rardi. Uni ustun qilish
    # esa xavfli: jiddiylik darhol yozishni (write-behind'ni chetlab
    # o'tish), proktor ekraniga chiqishni va dalil yig'ishni hal qiladi,
    # ya'ni paneldagi bitta raqam kritik hodisani jimgina oddiyga
    # aylantirardi.
    #
    # Takror oralig'i — TURGA XOS (`risk.cooldown_for`): `0` bo'lsa
    # siyosatdagi `risk_event_cooldown_s` ishlaydi.
    cooldown_s = models.PositiveSmallIntegerField(
        _("Takror oralig'i (s)"), default=0,
        help_text=_("0 — siyosatdagi umumiy qiymat ishlatiladi"),
    )
    is_active = models.BooleanField(_("Faol"), default=True, db_index=True)

    def __str__(self):
        return f"{self.event_type} (+{self.weight})"

    class Meta:
        db_table = "event_risk_weight"
        verbose_name = _("Hodisa og'irligi")
        verbose_name_plural = _("Hodisa og'irliklari")
        ordering = ["-weight", "event_type"]
