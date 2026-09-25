from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from apps.common.region_scope import ensure_in_region, zone_region
from apps.exams import services as exam_services
from apps.devices.models import Computer
from apps.exams.models import ComputerBooking, Exam, ExamSchedule, ExamType


class ExamTypeSerializer(serializers.ModelSerializer):
    exams_count = serializers.IntegerField(read_only=True)
    # Cheklovlar shartli (`deleted_at IS NULL`) — DRF ulardan validator
    # yasamaydi, ya'ni takroriy qiymat maydonga bog'lanmagan 409 bo'lib
    # qaytardi. Qarang: `devices` serializerlaridagi bir xil naqsh.
    name = serializers.CharField(
        max_length=255,
        validators=[
            UniqueValidator(
                queryset=ExamType.objects.alive(),
                message="Bunday nomli imtihon turi allaqachon mavjud",
            )
        ],
    )
    key = serializers.CharField(
        max_length=100,
        validators=[
            UniqueValidator(
                queryset=ExamType.objects.alive(),
                message="Bunday kalitli imtihon turi allaqachon mavjud",
            )
        ],
    )

    class Meta:
        model = ExamType
        fields = (
            "id", "name", "key", "is_active", "exams_count", "created_at", "deleted_at",
        )
        read_only_fields = ("id", "created_at", "deleted_at")

    def validate_key(self, value):
        # Kalit kod sifatida ishlatiladi (hisobot, integratsiya), shuning
        # uchun registr va bo'shliqdan qat'i nazar bitta shaklga keltiriladi.
        return value.strip().lower()


class ExamSerializer(serializers.ModelSerializer):
    setting_name = serializers.CharField(source="setting.name", read_only=True, default="")
    exam_type_name = serializers.CharField(source="exam_type.name", read_only=True, default="")
    # `queryset` — `alive()`: standart menejer yumshoq o'chirilgan turlarni
    # ham qaytaradi, ya'ni hisobdan chiqarilgan turni biriktirib bo'lardi.
    exam_type = serializers.PrimaryKeyRelatedField(
        queryset=ExamType.objects.alive(), required=False, allow_null=True
    )
    sessions_count = serializers.IntegerField(read_only=True)
    # Cheklov shartli (`deleted_at IS NULL`) — DRF undan validator yasamaydi.
    name = serializers.CharField(
        max_length=255,
        validators=[
            UniqueValidator(
                queryset=Exam.objects.alive(),
                message="Bunday nomli imtihon allaqachon mavjud",
            )
        ],
    )

    # Sarlavha KREDENSIAL, shuning uchun `Camera.password` bilan bir xil
    # naqsh: yozish uchun ochiq maydon, o'qish uchun esa faqat niqob.
    # To'liq qiymatni qaytarish uni brauzer devtools'iga, har bir
    # ro'yxat so'roviga va CSV eksportiga chiqarardi.
    site_header = serializers.CharField(
        write_only=True, required=False, allow_blank=True, max_length=4096,
        help_text="To'liq sarlavha: «Authorization: Bearer <token>»",
    )
    site_header_masked = serializers.SerializerMethodField()

    class Meta:
        model = Exam
        fields = (
            "id", "name", "key", "exam_type", "exam_type_name", "external_code",
            "site_url", "site_header", "site_header_masked",
            "duration_minutes", "setting",
            "setting_name", "is_active", "sessions_count", "created_at", "deleted_at",
        )
        read_only_fields = ("id", "created_at", "deleted_at")

    def get_site_header_masked(self, obj) -> str:
        return exam_services.mask_site_header(obj)

    def validate_site_header(self, value):
        """
        Format: «Nom: qiymat».

        Tekshiruv YENGIL va ataylab: sarlavha nomi (RFC 7230 token)
        bo'sh bo'lmasligi va qiymat bo'lishi kifoya. Qat'iyroq
        tekshiruv birinchi nostandart platformada to'sib qo'yardi,
        xato sarlavha esa baribir platformaning o'zida 401 bilan
        ko'rinadi.

        Yangi qator TAQIQLANADI: u HTTP so'roviga ikkinchi sarlavha
        kiritish (header injection) imkonini berardi.
        """
        raw = (value or "").strip()
        if not raw:
            return ""
        if "\n" in raw or "\r" in raw:
            raise serializers.ValidationError(
                "Sarlavha bitta qatordan iborat bo'lishi kerak"
            )
        name, separator, header_value = raw.partition(":")
        if not separator or not name.strip() or not header_value.strip():
            raise serializers.ValidationError(
                "Format: «Authorization: Bearer <token>» — nom va qiymat "
                "ikki nuqta bilan ajratiladi"
            )
        return raw

    def create(self, validated_data):
        raw_header = validated_data.pop("site_header", "")
        exam = super().create(validated_data)
        if raw_header:
            exam_services.set_site_header(exam, raw_header)
            exam.save(update_fields=["site_header_encrypted", "updated_at"])
        return exam

    def update(self, instance, validated_data):
        # `None` — maydon umuman kelmadi (tegilmaydi); `""` — ataylab
        # tozalash. PATCH bilan boshqa maydonni yangilash sarlavhani
        # o'chirib yubormasligi kerak.
        raw_header = validated_data.pop("site_header", None)
        exam = super().update(instance, validated_data)
        if raw_header is not None:
            exam_services.set_site_header(exam, raw_header)
            exam.save(update_fields=["site_header_encrypted", "updated_at"])
        return exam


class ExamScheduleSerializer(serializers.ModelSerializer):
    exam_name = serializers.CharField(source="exam.name", read_only=True)
    zone_name = serializers.CharField(source="zone.name", read_only=True, default="")
    # Viloyat seansning O'Z maydoni emas (bino orqali). Panel formasi
    # "avval viloyat, keyin uning binolari" tartibida ishlaydi va
    # tahrirlashda viloyatni oldindan tanlash uchun ID kerak — faqat
    # o'qish (`CameraSerializer.region` bilan bir xil naqsh).
    region = serializers.IntegerField(source="zone.region_id", read_only=True, default=None)
    region_name = serializers.CharField(source="zone.region.name", read_only=True, default="")
    is_open = serializers.SerializerMethodField()

    class Meta:
        model = ExamSchedule
        fields = (
            "id", "exam", "exam_name", "zone", "zone_name", "region", "region_name", "exam_date",
            "starts_at", "ends_at", "checkin_lead_minutes", "is_active",
            "is_open", "created_at", "deleted_at",
        )
        read_only_fields = ("id", "created_at", "deleted_at")

    def get_is_open(self, obj) -> bool:
        """
        Hozir kirish oynasi ochiqmi.

        Mantiq modelda (`ExamSchedule.is_open`) — client oqimi ham aynan
        shuni chaqiradi, shuning uchun admin panel ko'rsatgan holat bilan
        haqiqiy ruxsat har doim mos keladi.
        """
        return obj.is_open()

    def validate(self, attrs):
        starts_at = attrs.get("starts_at") or getattr(self.instance, "starts_at", None)
        ends_at = attrs.get("ends_at") or getattr(self.instance, "ends_at", None)
        if starts_at and ends_at and ends_at <= starts_at:
            raise serializers.ValidationError(
                {"ends_at": "Tugash vaqti boshlanish vaqtidan keyin bo'lishi kerak"}
            )
        # Umumiy seans (`zone=NULL`) BARCHA viloyatlarga amal qiladi —
        # uni faqat respublika darajasida yaratish mumkin (viloyat xodimi
        # uni faqat KO'RADI, `ExamScheduleViewSet.get_queryset`).
        ensure_in_region(
            self, attrs, "zone", region_of=zone_region,
            message="Seansni faqat o'z viloyatingiz binosi uchun yarata olasiz",
            null_message="Barcha binolar uchun (umumiy) seansni faqat respublika administratori yaratadi",
        )
        return attrs


# --------------------------------------------------------------------------
# Kompyuter bronlari
# --------------------------------------------------------------------------
class ComputerBookingSerializer(serializers.ModelSerializer):
    """
    Bron qatori — panel jadvali uchun.

    `pinfl`, `is_booked`, `booked_*` bu serializer orqali YOZILMAYDI:
    biriktirish alohida amallar (`assign/`, `release/`) — ular
    tekshiruv (band joy, buzilgan kompyuter, sessiya doirasi) va audit
    bilan keladi. Oddiy PATCH ularni chetlab o'tishi mumkin bo'lardi.
    Yoziladigani faqat `is_active` (ishchi / buzilgan).

    JSHSHIR panelda TO'LIQ (`CLAUDE.md`: "JSHSHIR: panelda TO'LIQ") —
    administrator uni hujjat bilan solishtiradi.
    """

    exam_name = serializers.CharField(source="schedule.exam.name", read_only=True)
    exam_date = serializers.DateField(source="schedule.exam_date", read_only=True)
    starts_at = serializers.DateTimeField(source="schedule.starts_at", read_only=True)
    computer_number = serializers.IntegerField(source="computer.number", read_only=True)
    computer_label = serializers.CharField(source="computer.label", read_only=True)
    inventory_code = serializers.CharField(source="computer.inventory_code", read_only=True)
    zone = serializers.IntegerField(source="computer.zone_id", read_only=True)
    zone_name = serializers.CharField(source="computer.zone.name", read_only=True)
    region_name = serializers.CharField(source="computer.zone.region.name", read_only=True, default="")
    booked_by_name = serializers.SerializerMethodField()
    #: Talabgor sessiyasi holati (FaceID'dan o'tgan bo'lsa) — "keldimi?"
    #: degan savolga javob. Annotatsiyadan keladi, qatorma-qator
    #: so'rov emas (`ComputerBookingViewSet.queryset`).
    session_status = serializers.CharField(read_only=True, default=None)

    class Meta:
        model = ComputerBooking
        fields = (
            "id", "schedule", "exam_name", "exam_date", "starts_at",
            "computer", "computer_number", "computer_label", "inventory_code",
            "zone", "zone_name", "region_name",
            "is_active", "is_booked", "pinfl", "booked_at", "booked_by_name",
            "session_status", "finished_count", "last_finished_at",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "is_booked", "pinfl", "booked_at", "booked_by_name",
            "finished_count", "last_finished_at", "created_at", "updated_at",
        )
        # `unique_together` validatori o'rniga `validate` dagi aniq xabar.
        validators = []

    def get_booked_by_name(self, obj) -> str:
        user = obj.booked_by
        if user is None:
            return ""
        return user.get_full_name() or user.username

    def validate(self, attrs):
        from apps.common.exceptions import SeatUnavailable
        from apps.exams import bookings

        if self.instance is not None:
            # Joyning O'ZINI (sessiya, kompyuter) almashtirib bo'lmaydi —
            # talabgorni ko'chirish `assign/` orqali.
            for name in ("schedule", "computer"):
                if name in attrs and attrs[name] != getattr(self.instance, name):
                    raise serializers.ValidationError(
                        {name: "Joyni o'zgartirib bo'lmaydi — talabgorni ko'chirishdan foydalaning"}
                    )
            return attrs

        schedule, computer = attrs["schedule"], attrs["computer"]
        user = self.context["request"].user
        region_id = user.region_id if user.is_region_scoped else None
        try:
            bookings._check_scope(schedule, computer, region_id=region_id)
        except SeatUnavailable as exc:
            raise serializers.ValidationError({"computer": str(exc.detail)})
        if ComputerBooking.objects.filter(schedule=schedule, computer=computer).exists():
            raise serializers.ValidationError(
                {"computer": "Bu kompyuter shu test sessiyasida allaqachon bor"}
            )
        return attrs


class BookingScheduleField(serializers.PrimaryKeyRelatedField):
    """Faqat tirik (o'chirilmagan) test sessiyalari."""

    def get_queryset(self):
        return ExamSchedule.objects.alive().select_related("exam", "zone")


class BookingAssignSerializer(serializers.Serializer):
    """
    `assign/` — bitta talabgor.

    `computer` berilmasa joy AVTOMATIK tanlanadi (binodagi eng kichik
    raqamli bo'sh ishchi kompyuter); umumiy sessiyada bino `zone` bilan
    toraytiriladi.
    """

    schedule = BookingScheduleField()
    pinfl = serializers.CharField(max_length=20)
    computer = serializers.PrimaryKeyRelatedField(
        queryset=Computer.objects.alive().select_related("zone__region"),
        required=False,
        allow_null=True,
    )
    zone = serializers.IntegerField(required=False, allow_null=True, min_value=1)


class BookingBulkItemSerializer(serializers.Serializer):
    pinfl = serializers.CharField(max_length=20)
    computer = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    zone = serializers.IntegerField(required=False, allow_null=True, min_value=1)


class BookingBulkAssignSerializer(serializers.Serializer):
    schedule = BookingScheduleField()
    items = serializers.ListField(
        child=BookingBulkItemSerializer(), allow_empty=False, max_length=1000
    )


class BookingGenerateSerializer(serializers.Serializer):
    schedule = BookingScheduleField()
    zone = serializers.IntegerField(required=False, allow_null=True, min_value=1)
