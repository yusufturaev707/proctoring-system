"""
PyQt6 client so'rovlari uchun serializerlar.

Bu yuza kuniga milliardlab so'rov qabul qiladi, shuning uchun validatsiya
ataylab yengil: `ModelSerializer` emas, oddiy `Serializer`. ModelSerializer
har bir chaqiruvda model meta'sini o'qiydi va DB unique-tekshiruvlarini
qo'shadi — bu ingest yo'lida keraksiz yuk.
"""

from django.conf import settings
from rest_framework import serializers

from apps.common.utils.validators import (
    mac_address_validator,
    machine_uuid_validator,
    normalize_machine_uuid,
    validate_pinfl,
)
from apps.proctoring.models import ProctoringEvent, ScreenshotMeta


class MachineUuidField(serializers.CharField):
    """
    Machine UUID - kanonik shaklga keltirilib qabul qilinadi.

    Qoida client bilan bir xil (`normalize_machine_uuid`): kichik harf
    yoki `{...}` qavsli qiymat bitta mashinani ikki xil yozuvga
    aylantirmasligi kerak. Ixtiyoriy - eski client'lar yubormaydi.
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("max_length", 64)
        kwargs.setdefault("required", False)
        kwargs.setdefault("allow_blank", True)
        kwargs.setdefault("validators", [machine_uuid_validator])
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        return normalize_machine_uuid(value) or value


class PreflightSerializer(serializers.Serializer):
    """
    Ishga tushishdagi tarmoq tekshiruvi — qaror shu yagona maydonda.

    Maydon IXTIYORIY, lekin usiz javob har doim rad etish bo'ladi
    (`public_ip_unknown`): clientda internet bo'lmasa u tashqi manzilni
    aniqlay olmaydi va tekshirish uchun hech narsa qolmaydi.
    """

    public_ip = serializers.IPAddressField(
        protocol="IPv4", required=False, allow_blank=True
    )


class AccessAttemptSerializer(serializers.Serializer):
    """
    Dasturga kirish urinishi — kim, qayerdan va nima bilan tugadi.

    Barcha maydonlar CLIENT aytadi va ular tekshirilmaydi: bu jurnal
    yozuvi, kirish qarori emas. Qaror `preflight` da chiqarilgan va
    server o'z xulosasini shu yerda qaytadan hisoblaydi — client
    aytgani bilan farq qilsa, jurnalda ikkalasi ham qoladi.

    MAC formati tekshiriladi, chunki u jurnalda IZLASH kaliti: buzilgan
    qiymat keyin hech qachon topilmaydi.
    """

    machine_uuid = MachineUuidField()
    mac_address = serializers.CharField(
        max_length=17, required=False, allow_blank=True, validators=[mac_address_validator]
    )
    ip_address = serializers.IPAddressField(protocol="IPv4", required=False, allow_blank=True)
    public_ip = serializers.IPAddressField(protocol="IPv4", required=False, allow_blank=True)
    hostname = serializers.CharField(max_length=64, required=False, allow_blank=True)
    app_version = serializers.CharField(max_length=32, required=False, allow_blank=True)
    #: Client oqimi natijasi: login sahifasi ochildimi?
    entered_login = serializers.BooleanField(default=False)
    #: Client tomondagi xato kodi (`ip_not_allowed`, `network`, ...).
    code = serializers.CharField(max_length=64, required=False, allow_blank=True)


class HandshakeSerializer(serializers.Serializer):
    app_version = serializers.CharField(max_length=32, required=False, allow_blank=True)
    app_hash = serializers.CharField(max_length=64, required=False, allow_blank=True)
    # Ixtiyoriy: eski client'lar yubormaydi, u holda tekshiruv o'tkazib
    # yuboriladi (`record_handshake` bo'sh qiymatga tegmaydi).
    hardware_fingerprint = serializers.CharField(
        max_length=128, required=False, allow_blank=True
    )
    # Client o'zi aniqlagan tashqi manzil (diagnostika uchun; kirish
    # ruxsatini u EMAS, server ko'rgan manzil hal qiladi).
    public_ip = serializers.IPAddressField(required=False, allow_blank=True)
    # MASHINA IDENTIFIKATORI - ona platadagi SMBIOS UUID. Server uni
    # `Computer.machine_uuid` bilan solishtiradi va mos kelmasa imtihonni
    # boshlashga ruxsat bermaydi (`devices.services.verify_machine`).
    # Client aytgan qiymat yozuvga YOZILMAYDI (bitta istisno - UUID'siz
    # eski yozuvga MAC mos kelganda bir marta bog'lash).
    #
    # Ixtiyoriy: eski client'lar yubormaydi - ular uchun MAC bo'yicha
    # avvalgi tekshiruv qoladi (qaror `REQUIRE_MACHINE_MATCH` da).
    machine_uuid = MachineUuidField()
    # MAC va LAN manzili - WinAPI orqali, marshrut tanlagan adapterdan
    # (`client/services/winapi_net.py`). MAC endi IKKILAMCHI belgi.
    mac_address = serializers.CharField(max_length=17, required=False, allow_blank=True)
    ip_address = serializers.IPAddressField(required=False, allow_blank=True)
    info_pc = serializers.JSONField(required=False)
    monitors = serializers.IntegerField(min_value=0, default=1)
    cameras = serializers.IntegerField(min_value=0, default=1)
    # Apparat imkoniyati - qurilma yozuviga tushadi. Ixtiyoriy: eski
    # client'lar yubormaydi va u holda maydon o'zgarishsiz qoladi.
    gpu_name = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    # Ro'yxat `controls.ProctoringPolicy.GpuProfile` bilan mos
    # bo'lishi shart (`auto` dan tashqari - u tanlov, o'lchov emas).
    # Client'da `minimal` profil ham bor va u aynan zaif mashinada
    # tanlanadi: ro'yxatdan tushib qolsa, o'sha mashinalarning
    # handshake'i 400 olardi.
    performance_profile = serializers.ChoiceField(
        choices=["high", "medium", "low", "cpu", "minimal"],
        required=False, allow_blank=True, default="",
    )


class CandidateLookupSerializer(serializers.Serializer):
    pinfl = serializers.CharField(max_length=14, validators=[validate_pinfl])
    exam_id = serializers.IntegerField(min_value=1)
    # Client ishlab turgan mashina ("talabgor AYNAN qaysi stolda") —
    # kompyuter broni bilan solishtiriladi
    # (`exams.bookings.resolve_candidate_seat`). Asos - Machine UUID;
    # MAC - uni yubormaydigan eski client uchun. Ikkalasi ham bo'lmasa
    # qurilmaning `Computer` biriktiruvi ishlatiladi.
    machine_uuid = MachineUuidField()
    mac_address = serializers.CharField(
        max_length=17, required=False, allow_blank=True, validators=[mac_address_validator]
    )


class EmbeddingField(serializers.ListField):
    """Yuz vektori — o'lchami qat'iy tekshiriladi."""

    child = serializers.FloatField()

    def to_internal_value(self, data):
        # `multipart/form-data` ichma-ich strukturani KO'TARMAYDI:
        # 512 float alohida maydon bo'lib kelardi. Shuning uchun
        # vektor JSON satr sifatida ham qabul qilinadi — aynan
        # `EvidenceUploadSerializer.validate_boxes` dagi naqsh.
        #
        # HTML/multipart kirishida DRF `QueryDict.getlist()` ni
        # chaqiradi va satr BIR ELEMENTLI RO'YXAT ichida keladi.
        # Uni ochmasak, `FloatField` ga butun JSON satr tushib,
        # "String value too large" degan tushunarsiz xato berardi.
        if isinstance(data, (list, tuple)) and len(data) == 1 and isinstance(data[0], str):
            data = data[0]
        if isinstance(data, str):
            import json

            try:
                data = json.loads(data)
            except (TypeError, ValueError):
                raise serializers.ValidationError("Embedding JSON emas")
        value = super().to_internal_value(data)
        expected = settings.PROCTORING["FACE_EMBEDDING_DIM"]
        if len(value) != expected:
            raise serializers.ValidationError(
                f"Embedding o'lchami {expected} bo'lishi kerak, kelgani {len(value)}"
            )
        return value


class FaceVerifySerializer(serializers.Serializer):
    """
    Kirishdagi yuz tekshiruvi — MOSLIK TASDIQLANGAN holat.

    Solishtirishni client bajargan; bu yerga uning natijasi keladi:
    etalon vektor (sessiyaga muzlatiladi), ball va o'sha paytdagi
    KADR. Mos kelmagan urinish boshqa endpointga boradi
    (`FaceAttemptSerializer`) — u sessiya yaratmaydi.

    So'rov `multipart/form-data` da keladi (rasm bor), shuning uchun
    `embedding` JSON satr sifatida uzatiladi.
    """

    challenge = serializers.CharField(max_length=128)
    embedding = EmbeddingField(required=False, allow_null=True)
    score = serializers.IntegerField(min_value=0, max_value=100, required=False, allow_null=True)
    faces_detected = serializers.IntegerField(min_value=0, max_value=20, default=1)
    #: Jonli kadr. IXTIYORIY: kamera kadrni bermagan bo'lsa ham
    #: sessiya ochilishi kerak — rasm dalil, to'siq emas.
    #
    # `FileField`, `ImageField` EMAS: ikkinchisi buzilgan faylni 400
    # bilan rad etardi va o'shanda butun tekshiruv yiqilardi. Tur
    # baytlardan aniqlanadi (`face_images.store` -> `_detect_image`)
    # va xato o'sha yerda yutiladi — qator rasmsiz yoziladi.
    image = serializers.FileField(required=False, allow_null=True)
    #: HUJJAT (pasport) rasmi — platformadan kelgan etalon.
    #
    # Client uni BIR MARTA, kirish tekshiruvida yuboradi. Ilgari u
    # hech qayerda saqlanmasdi: solishtirishga ishlatilib, client
    # xotirasida qolib ketardi. Panelda esa ballning o'zi hech
    # narsani isbotlamaydi — apellyatsiyada hujjatdagi odam va
    # kameradagi odam YONMA-YON kerak bo'ladi.
    #
    # Test davomida YUBORILMAYDI: u yerda etalon pasport rasmi emas,
    # kirishda tasdiqlangan kadr va uni har tekshiruvda qayta
    # saqlash bir xil rasmni yuzlab marta diskka yozardi.
    reference_image = serializers.FileField(required=False, allow_null=True)
    image_key = serializers.CharField(max_length=500, required=False, allow_blank=True)

    def validate(self, attrs):
        if attrs.get("embedding") is None and attrs.get("score") is None:
            raise serializers.ValidationError("embedding yoki score berilishi shart")
        return attrs


class FaceAttemptSerializer(serializers.Serializer):
    """
    Kirishda MOS KELMAGAN urinish.

    Sessiya YO'Q va yaratilmaydi ham: talabgor hali kirmadi. Yozuv
    esa kerak — kadrda boshqa odam turgan bo'lishi mumkin.

    `challenge` sarflanmaydi: talabgor qayta urinib ko'radi.
    """

    challenge = serializers.CharField(max_length=128)
    score = serializers.IntegerField(min_value=0, max_value=100, required=False, allow_null=True)
    faces_detected = serializers.IntegerField(min_value=0, max_value=20, default=1)
    image = serializers.FileField(required=False, allow_null=True)
    #: Hujjat rasmi - `FaceVerifySerializer.reference_image` bilan
    #: bir xil sabab: aynan MOS KELMAGAN urinishda "kadrda kim
    #: turgan edi?" degan savol eng qimmatli va unga javob
    #: ikkita rasmni yonma-yon qo'yib beriladi.
    reference_image = serializers.FileField(required=False, allow_null=True)


class PeriodicFaceSerializer(serializers.Serializer):
    """
    Test davomidagi yuz tekshiruvi — FAQAT MUVAFFAQIYATSIZ NATIJA.

    `embedding` MAYDONI YO'Q va bu ataylab: solishtirish clientda
    bajariladi (ikkala vektor ham o'sha yerda), serverga esa ball,
    kadr va oradagi muvaffaqiyatli tekshiruvlar soni keladi.
    Vektorni baribir qabul qilish "server ham solishtiradimi?"
    degan savolni ochiq qoldirardi.
    """

    score = serializers.IntegerField(min_value=0, max_value=100)
    faces_detected = serializers.IntegerField(min_value=0, max_value=20, default=1)
    image = serializers.FileField(required=False, allow_null=True)
    #: Oxirgi xabardan keyingi MUVAFFAQIYATLI tekshiruvlar soni —
    #: usiz server "ketma-ket" qoidasini qo'llay olmaydi.
    passed_since_last = serializers.IntegerField(min_value=0, required=False, default=0)
    occurred_at = serializers.DateTimeField(required=False)


class EventItemSerializer(serializers.Serializer):
    client_event_id = serializers.CharField(max_length=64, required=False, allow_blank=True)
    type = serializers.ChoiceField(choices=ProctoringEvent.Type.choices)
    severity = serializers.IntegerField(min_value=0, max_value=4, default=1)
    occurred_at = serializers.DateTimeField()
    payload = serializers.JSONField(required=False)
    screenshot_key = serializers.CharField(max_length=500, required=False, allow_blank=True)


class EventBatchSerializer(serializers.Serializer):
    """
    Client 5 soniyalik oynada to'plangan hodisalarni bitta so'rovda yuboradi.

    `max_length=200` — buzilgan client cheksiz katta batch yuborib
    xotirani to'ldirmasligi uchun.
    """

    events = serializers.ListField(child=EventItemSerializer(), min_length=1, max_length=200)


class HeartbeatSerializer(serializers.Serializer):
    """
    Faollik signali va client hisoblagichlari.

    Maydonlar TO'G'RIDAN-TO'G'RI Redis hash'iga tushadi
    (`state.touch_heartbeat` -> `extra`), ya'ni nomlar o'sha yerdagi
    kalitlar bilan bir xil bo'lishi shart.
    """

    monitors = serializers.IntegerField(min_value=0, required=False)
    cameras_active = serializers.IntegerField(min_value=0, required=False)
    cpu_percent = serializers.FloatField(min_value=0, max_value=100, required=False)
    memory_percent = serializers.FloatField(min_value=0, max_value=100, required=False)
    queued_events = serializers.IntegerField(min_value=0, required=False)
    network_ok = serializers.BooleanField(default=True)
    #: Client bajargan yuz solishtirishlari soni (JAMI, o'sib boruvchi).
    #
    # Serverga faqat muvaffaqiyatsiz tekshiruvlar yuboriladi, ya'ni
    # "nechta tekshiruv bo'ldi" degan savolga faqat client javob
    # bera oladi. Qiymat `face_checks` kalitiga YOZILADI (oshirilmaydi):
    # egasi bitta bo'lgani uchun poyga ham, ikki marta sanash ham yo'q.
    face_checks = serializers.IntegerField(min_value=0, required=False)


class PresignRequestSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=ScreenshotMeta.Kind.choices, default=ScreenshotMeta.Kind.SCREEN)
    content_type = serializers.CharField(max_length=64, default="image/jpeg")
    count = serializers.IntegerField(min_value=1, max_value=20, default=1)


class ScreenshotCommitSerializer(serializers.Serializer):
    object_key = serializers.CharField(max_length=500)
    kind = serializers.ChoiceField(choices=ScreenshotMeta.Kind.choices, default=ScreenshotMeta.Kind.SCREEN)
    sha256 = serializers.CharField(max_length=64, required=False, allow_blank=True)
    size_bytes = serializers.IntegerField(min_value=0, default=0)
    width = serializers.IntegerField(min_value=0, max_value=10000, default=0)
    height = serializers.IntegerField(min_value=0, max_value=10000, default=0)
    captured_at = serializers.DateTimeField()

    # Test platformasidagi savol (client lokal xizmatiga kelgan `q_id`/`q_n`).
    # Belgilar to'plami client bilan BIR XIL (`local_service.QUESTION_ID_RE`).
    question_id = serializers.RegexField(
        r"^[A-Za-z0-9_.\-]{1,64}$", required=False, allow_blank=True, default="",
    )
    question_number = serializers.IntegerField(
        min_value=1, max_value=100000, required=False, allow_null=True, default=None,
    )


class ScreenshotCommitBatchSerializer(serializers.Serializer):
    screenshots = serializers.ListField(
        child=ScreenshotCommitSerializer(), min_length=1, max_length=50
    )


class ScreenshotUploadSerializer(serializers.Serializer):
    """
    Fayl tizimi yo'li: binary AYNAN shu so'rovda keladi.

    `content_type` va fayl kengaytmasi ataylab QABUL QILINMAYDI. Ularni
    client istalgancha yozadi, shuning uchun ular bu yerda hech qanday
    qaror uchun ishlatilmaydi: haqiqiy tur baytlardan aniqlanadi
    (`services/screenshots.py`), fayl nomi esa serverda yasaladi.
    """

    file = serializers.FileField(write_only=True)
    captured_at = serializers.DateTimeField()

    # Test platformasidagi savol (client lokal xizmatiga kelgan `q_id`/`q_n`).
    # Belgilar to'plami client bilan BIR XIL (`local_service.QUESTION_ID_RE`).
    question_id = serializers.RegexField(
        r"^[A-Za-z0-9_.\-]{1,64}$", required=False, allow_blank=True, default="",
    )
    question_number = serializers.IntegerField(
        min_value=1, max_value=100000, required=False, allow_null=True, default=None,
    )


class TechnicalProblemReportSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=[
            ("power", "Elektr"), ("network", "Tarmoq"), ("hardware", "Uskuna"),
            ("software", "Dastur"), ("other", "Boshqa"),
        ],
        default="other",
    )
    description = serializers.CharField(max_length=1000, required=False, allow_blank=True)


class IdentityConfirmSerializer(serializers.Serializer):
    """
    Operatorning hujjat bo'yicha qarori.

    `reject` — hujjat mos kelmadi, sessiya chetlashtiriladi.
    `confirm` — hujjat mos, imtihon ochiladi.
    """

    DOCUMENT_TYPES = [
        ("passport", "Pasport"),
        ("id_card", "ID karta"),
        ("birth_certificate", "Tug'ilganlik guvohnomasi"),
        ("driver_license", "Haydovchilik guvohnomasi"),
        ("other", "Boshqa"),
    ]

    decision = serializers.ChoiceField(choices=[("confirm", "Tasdiqlash"), ("reject", "Rad etish")])
    # HUJJAT MA'LUMOTI IXTIYORIY va `default=""` ATAYLAB qo'yilgan.
    #
    # Client bu maydonlarni yubormaydi: operator ekranda hujjatni
    # ko'zi bilan tekshiradi va faqat "tasdiqlash / rad etish"
    # tugmasini bosadi. Maydonlar API'da QOLDIRILDI - boshqa
    # o'rnatishda hujjat raqamini qayd etish talab qilinishi mumkin
    # va o'shanda client'ni yangilash kifoya, shartnomani emas.
    #
    # `default` bo'lmasa kalit `validated_data` da UMUMAN bo'lmaydi
    # va view'dagi `data["document_type"]` `KeyError` bilan 500
    # qaytarardi - ya'ni maydonni olib tashlash oqimni buzardi.
    document_type = serializers.ChoiceField(
        choices=DOCUMENT_TYPES, required=False, allow_blank=True, default=""
    )
    document_number = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default=""
    )
    reason = serializers.CharField(
        max_length=500, required=False, allow_blank=True, default=""
    )
    note = serializers.CharField(
        max_length=500, required=False, allow_blank=True, default=""
    )

    def validate(self, attrs):
        """
        RAD ETISH sababsiz bo'lmaydi, TASDIQLASH esa hujjatsiz bo'ladi.

        Farq javobgarlikda. Tasdiqlashda operator o'z nomi bilan
        javob beradi va u audit izida qoladi ("kim kiritdi") — hujjat
        raqami bunga hech nima qo'shmasdi, chunki operator uni
        baribir hujjatdan ko'chirardi va noto'g'ri raqamni ham
        yozib qo'yishi mumkin edi. Ekranda esa hujjat rasmi va jonli
        kadr yonma-yon turadi — haqiqiy tekshiruv o'sha yerda.

        Rad etish esa TALABGORNI imtihondan chetlatadi va bu qaror
        apellyatsiyaga tushishi mumkin: sababsiz yozuv "nega
        qo'yilmagan?" degan savolga javob bermasdi.
        """
        if attrs["decision"] == "reject" and not (attrs.get("reason") or "").strip():
            raise serializers.ValidationError(
                {"reason": "Rad etish sababi ko'rsatilishi shart"}
            )
        return attrs


class ExitVerifySerializer(serializers.Serializer):
    password = serializers.CharField(max_length=120)
    # Login qilinmagan holatda viloyatni aniqlashning yagona yo'li.
    # Ixtiyoriy: qurilma ro'yxatdan o'tgan bo'lsa, viloyat `X-Device-ID`
    # orqali kompyuter -> bino -> viloyat zanjiri bilan topiladi.
    public_ip = serializers.IPAddressField(
        protocol="IPv4", required=False, allow_blank=True
    )


class SessionFinishSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True)
    # Talabgor testni O'ZI yakunladi («Yakunlash» tugmasi) — kompyuter
    # broni bo'shaydi. Standart `false`: dasturdan chiqishdagi yakun va
    # eski client nusxalari joyni band qoldiradi (bo'shatish
    # qaytarilmaydi, band qoldirish esa panelda bir bosishda tuzatiladi).
    completed = serializers.BooleanField(required=False, default=False)


class PresenceSerializer(serializers.Serializer):
    """
    Client "tirikman" signali.

    Bo'sh so'rov ham to'g'ri: `in_exam` faqat panelda holatni
    ajratish uchun ("imtihonda" va "bo'sh turibdi"). Uni clientga
    ishonib topshirish mumkin, chunki qaror emas - `ExamSession`
    haqiqati baribir DB'da.
    """

    in_exam = serializers.BooleanField(required=False, default=False)


class CameraStreamSerializer(serializers.Serializer):
    """
    Kamera oqimi uchun so'rov.

    KAMERA ID BO'YICHA, rol bo'yicha emas. Ilgari client rolni
    yuborardi va server uni `CameraAssignment` dan izlardi; endi
    biriktirish yo'q - rolni operator client tomonda tanlaydi va
    server uni umuman bilmaydi. ID esa handshake bergan ro'yxatdan
    keladi, ya'ni client o'ylab topgan qiymat emas.

    `role` ixtiyoriy va faqat AUDIT uchun: jurnalda "qaysi vazifa
    uchun so'raldi" degan yozuv qolishi kerak, aks holda ikkita
    kamerali mashinada yozuvlar ajratib bo'lmas holga kelardi.
    """

    camera_id = serializers.IntegerField(min_value=1)
    #: `preview` - tekshiruv sahifasida VAZIFASI HALI BERILMAGAN kamera
    #: (uchinchi qurilma, masalan binodagi IP kamera). Operator uni
    #: ko'rib turib vazifa berishi uchun oqim ochiladi.
    role = serializers.ChoiceField(
        choices=["primary", "secondary", "preview"], required=False, default="primary"
    )


class CameraMeasurementSerializer(serializers.Serializer):
    """
    Bitta kameraning XOM O'LCHOVLARI.

    Bu yerda hech qanday XULOSA yo'q ("ok", "passed" kabi maydonlar
    ataylab qabul qilinmaydi): baholashni server bajaradi
    (`services/camera_check.py`). Client aytgan xulosaga ishonish
    o'zgartirilgan nusxaga "hammasi joyida" deyishga imkon berardi.

    Barcha o'lchovlar IXTIYORIY va bu ongli: kamera ochilmagan
    bo'lsa FPS ham, yorug'lik ham yo'q. `None` va `0` FARQ QILADI —
    birinchisi "o'lchanmadi", ikkinchisi "o'lchandi va nol".
    """

    role = serializers.ChoiceField(choices=["primary", "secondary"])
    source = serializers.ChoiceField(choices=["local", "ip"], required=False, default="local")
    label = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    #: OS'dagi qurilma indeksi (lokal veb-kamera uchun).
    #
    # Server uni SOLISHTIRISH uchun ishlatadi: kameralar alohida
    # tekshirilgani sababli suratchada oldingi o'lchov qolishi mumkin
    # va u AYNAN o'sha qurilmaga tegishli ekaniga ishonch kerak.
    # Operator rollarni almashtirsa, indeks mos kelmaydi va eski
    # o'lchov tashlanadi.
    local_index = serializers.IntegerField(required=False, allow_null=True, default=None)

    #: Bu kamera SHU so'rovda o'lchandimi.
    #
    # `False` — "kamera bor, lekin hozir tekshirilmadi". U "kamera
    # topilmadi" dan (`available=False`) BOSHQA holat: birinchisini
    # operator tekshirish tugmasini bosib hal qiladi, ikkinchisini
    # esa kabelni ulab. Ularni aralashtirish operatorni mavjud
    # bo'lmagan nosozlikni qidirishga majbur qilardi.
    measured = serializers.BooleanField(default=True)

    available = serializers.BooleanField(default=False)
    opened = serializers.BooleanField(default=False)
    is_virtual = serializers.BooleanField(default=False)
    error = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")

    frames = serializers.IntegerField(required=False, min_value=0, default=0)
    fps = serializers.FloatField(required=False, min_value=0, default=0.0)
    width = serializers.IntegerField(required=False, min_value=0, default=0)
    height = serializers.IntegerField(required=False, min_value=0, default=0)
    latency_ms = serializers.IntegerField(required=False, min_value=0, default=0)

    # Yuzga oid o'lchovlar - faqat birlamchi kamerada to'ldiriladi.
    faces = serializers.IntegerField(required=False, min_value=0, allow_null=True, default=None)
    face_width_px = serializers.IntegerField(required=False, min_value=0, allow_null=True, default=None)
    brightness = serializers.IntegerField(
        required=False, min_value=0, max_value=255, allow_null=True, default=None
    )
    face_offset = serializers.FloatField(
        required=False, min_value=0, max_value=1, allow_null=True, default=None
    )


class CameraCheckSerializer(serializers.Serializer):
    """Kamera tekshiruvi natijasi."""

    cameras = CameraMeasurementSerializer(many=True, allow_empty=True)
    #: Ixtiyoriy: berilsa o'sha imtihonning siyosati bo'yicha
    #: baholanadi, aks holda global standart bo'yicha.
    exam_id = serializers.IntegerField(required=False, allow_null=True)


class ProctoringStartSerializer(serializers.Serializer):
    """Kuzatuvni ishga tushirish."""

    #: Client aniqlagan unumdorlik profili (`high`/`medium`/`low`/`cpu`).
    #
    # Bayonnoma uchun muhim: CPU rejimida kuzatuv chastotasi past va
    # "hech narsa aniqlanmadi" xulosasining vazni ham past bo'ladi.
    ai_profile = serializers.CharField(max_length=8, required=False, allow_blank=True, default="")


class ProctoringStopSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class LocalRecordingSerializer(serializers.Serializer):
    """
    Mashinada qolgan yozuvning MANZILI (fayl emas).

    FAYL YO'Q va butun gap shunda: ekran yozuvi ~360 MB, kamera
    klipi hodisa sayin yig'iladi. Ularni yuklash 500 mashinali
    binoda kuniga yuzlab gigabayt degani. Shuning uchun serverga
    faqat "qayerda yotibdi va qanaqa" degan ma'lumot keladi.

    YO'L TEKSHIRILADI, LEKIN ISHONILMAYDI. Client uni o'zi aytadi
    va uni tasdiqlashning imkoni yo'q - fayl boshqa mashinada.
    Shuning uchun bu yerda faqat SHAKL tekshiriladi (uzunlik,
    kengaytma): panelga ko'rinadigan matn boshqariladigan
    bo'lishi kerak, aks holda u yerda ixtiyoriy satr chiqardi.
    """

    kind = serializers.ChoiceField(choices=["screen", "clip"])
    local_path = serializers.CharField(max_length=500)
    captured_at = serializers.DateTimeField()
    size_bytes = serializers.IntegerField(min_value=0, default=0)
    duration_ms = serializers.IntegerField(min_value=0, default=0)
    width = serializers.IntegerField(min_value=0, max_value=16384, default=0)
    height = serializers.IntegerField(min_value=0, max_value=16384, default=0)
    frames = serializers.IntegerField(min_value=0, default=0)
    frames_dropped = serializers.IntegerField(min_value=0, default=0)
    event_type = serializers.CharField(max_length=48, required=False, allow_blank=True, default="")
    camera_role = serializers.ChoiceField(
        choices=["primary", "secondary"], required=False, allow_blank=True, default=""
    )
    confidence = serializers.IntegerField(min_value=0, max_value=100, required=False, default=0)
    #: Sessiyaning `public_id` si. Token bor bo'lsa FAQAT solishtirish
    #: uchun; token bekor bo'lgan bo'lsa (chetlashtirish) - sessiyani
    #: topishning yagona yo'li (`recordings.session_without_token`).
    session_id = serializers.UUIDField(required=False, allow_null=True, default=None)

    def validate_local_path(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Yo'l bo'sh")
        # Faqat video: bu endpoint rasmlar uchun emas (ular
        # avvalgidek yuklanadi) va kengaytma panelda qaysi
        # dasturda ochishni aytadi.
        if not value.lower().endswith((".mp4", ".webm")):
            raise serializers.ValidationError("Faqat video fayl kutiladi")
        return value


#: Dalil belgisining turlari — panel rangi shundan
#: (`client/proctoring/behavior/behavior_analyzer._mark`).
_MARK_KINDS = {"object", "person", "student", "face"}


def _clean_mark(item) -> dict | None:
    """
    Bitta belgini QAT'IY tozalaydi; yaroqsizi tashlanadi (butun dalil emas).

    Belgi client'dan keladi va panelda rasm USTIGA chiziladi, shuning
    uchun faqat ma'lum kalitlar o'tadi: nisbiy ramka (0..1), qisqa nom,
    tur va ishonch. Eski client'ning piksel formati (`bbox`) ham shu
    yerda tushib qoladi — kadr o'lchamisiz u to'g'ri joyga chizilmasdi.
    Yaroqsiz belgi uchun butun dalilni rad etish esa kadrni yo'qotardi.
    """
    if not isinstance(item, dict):
        return None
    box = item.get("box")
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        x1, y1, x2, y2 = (min(1.0, max(0.0, float(value))) for value in box)
    except (TypeError, ValueError):
        return None
    if x2 <= x1 or y2 <= y1:
        return None

    mark = {
        "label": str(item.get("label") or "")[:48],
        "kind": item.get("kind") if item.get("kind") in _MARK_KINDS else "object",
        "box": [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)],
    }
    try:
        conf = float(item["conf"])
    except (KeyError, TypeError, ValueError):
        conf = None
    if conf is not None and 0.0 <= conf <= 1.0:
        mark["conf"] = round(conf, 3)
    return mark


class EvidenceUploadSerializer(serializers.Serializer):
    """
    Dalil fayli va uning hodisa konteksti.

    Fayl `multipart/form-data` da keladi, shuning uchun barcha
    maydonlar SATR sifatida uzatiladi va DRF ularni o'giradi.
    `boxes` esa JSON satr: ichma-ich strukturani form-data
    ko'tarmaydi.
    """

    file = serializers.FileField()
    kind = serializers.ChoiceField(choices=["frame", "clip"], default="frame")
    captured_at = serializers.DateTimeField()
    event_type = serializers.CharField(max_length=48, required=False, allow_blank=True, default="")
    camera_role = serializers.ChoiceField(
        choices=["primary", "secondary"], required=False, allow_blank=True, default=""
    )
    confidence = serializers.IntegerField(min_value=0, max_value=100, required=False, default=0)
    duration_ms = serializers.IntegerField(min_value=0, required=False, default=0)
    #: `[{"cls": "cell phone", "conf": 0.94, "bbox": [x1,y1,x2,y2]}]`
    boxes = serializers.JSONField(required=False, default=list)

    def validate_boxes(self, value):
        """
        Ramkalar ro'yxati CHEKLANADI.

        Ular client'dan keladi va JSON maydonga yoziladi. Cheksiz
        ro'yxat DB qatorini megabaytlarga cho'zishi mumkin -
        `payload` oq ro'yxati bilan bir xil sabab
        (`ingest._BROADCAST_DETAIL_KEYS`).
        """
        if isinstance(value, str):
            import json

            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                raise serializers.ValidationError("Ramkalar JSON emas")
        if not isinstance(value, list):
            raise serializers.ValidationError("Ramkalar ro'yxat bo'lishi kerak")
        return [mark for mark in map(_clean_mark, value[:20]) if mark]
