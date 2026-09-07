"""
PyQt6 client so'rovlari uchun serializerlar.

Bu yuza kuniga milliardlab so'rov qabul qiladi, shuning uchun validatsiya
ataylab yengil: `ModelSerializer` emas, oddiy `Serializer`. ModelSerializer
har bir chaqiruvda model meta'sini o'qiydi va DB unique-tekshiruvlarini
qo'shadi — bu ingest yo'lida keraksiz yuk.
"""

from django.conf import settings
from rest_framework import serializers

from apps.common.utils.validators import mac_address_validator, validate_pinfl
from apps.proctoring.models import ProctoringEvent, ScreenshotMeta


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
    info_pc = serializers.JSONField(required=False)
    monitors = serializers.IntegerField(min_value=0, default=1)
    cameras = serializers.IntegerField(min_value=0, default=1)


class CandidateLookupSerializer(serializers.Serializer):
    pinfl = serializers.CharField(max_length=14, validators=[validate_pinfl])
    exam_id = serializers.IntegerField(min_value=1)


class EmbeddingField(serializers.ListField):
    """Yuz vektori — o'lchami qat'iy tekshiriladi."""

    child = serializers.FloatField()

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        expected = settings.PROCTORING["FACE_EMBEDDING_DIM"]
        if len(value) != expected:
            raise serializers.ValidationError(
                f"Embedding o'lchami {expected} bo'lishi kerak, kelgani {len(value)}"
            )
        return value


class FaceVerifySerializer(serializers.Serializer):
    """Kirishdagi yuz tekshiruvi."""

    challenge = serializers.CharField(max_length=128)
    embedding = EmbeddingField(required=False, allow_null=True)
    score = serializers.IntegerField(min_value=0, max_value=100, required=False, allow_null=True)
    faces_detected = serializers.IntegerField(min_value=0, max_value=20, default=1)
    image_key = serializers.CharField(max_length=500, required=False, allow_blank=True)

    def validate(self, attrs):
        if attrs.get("embedding") is None and attrs.get("score") is None:
            raise serializers.ValidationError("embedding yoki score berilishi shart")
        return attrs


class PeriodicFaceSerializer(serializers.Serializer):
    """Test davomidagi yuz tekshiruvi."""

    embedding = EmbeddingField(required=False, allow_null=True)
    score = serializers.IntegerField(min_value=0, max_value=100, required=False, allow_null=True)
    faces_detected = serializers.IntegerField(min_value=0, max_value=20, default=1)
    image_key = serializers.CharField(max_length=500, required=False, allow_blank=True)
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
    monitors = serializers.IntegerField(min_value=0, required=False)
    cameras_active = serializers.IntegerField(min_value=0, required=False)
    cpu_percent = serializers.FloatField(min_value=0, max_value=100, required=False)
    memory_percent = serializers.FloatField(min_value=0, max_value=100, required=False)
    queued_events = serializers.IntegerField(min_value=0, required=False)
    network_ok = serializers.BooleanField(default=True)


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
    document_type = serializers.ChoiceField(choices=DOCUMENT_TYPES, required=False)
    document_number = serializers.CharField(max_length=32, required=False, allow_blank=True)
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True)

    def validate(self, attrs):
        if attrs["decision"] == "confirm":
            # Hujjatsiz tasdiq — audit uchun qiymatsiz yozuv.
            if not attrs.get("document_type"):
                raise serializers.ValidationError(
                    {"document_type": "Tasdiqlash uchun hujjat turi ko'rsatilishi shart"}
                )
            if not (attrs.get("document_number") or "").strip():
                raise serializers.ValidationError(
                    {"document_number": "Tasdiqlash uchun hujjat raqami shart"}
                )
        elif not (attrs.get("reason") or "").strip():
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
