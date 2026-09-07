from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from apps.exams.models import Exam, ExamSchedule, ExamType


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

    class Meta:
        model = Exam
        fields = (
            "id", "name", "key", "exam_type", "exam_type_name", "external_code",
            "site_url", "allowed_domains", "duration_minutes", "setting",
            "setting_name", "is_active", "sessions_count", "created_at", "deleted_at",
        )
        read_only_fields = ("id", "created_at", "deleted_at")

    def validate_allowed_domains(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Ro'yxat bo'lishi kerak")
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise serializers.ValidationError("Har bir element bo'sh bo'lmagan matn bo'lishi kerak")
        return [item.strip().lower() for item in value]


class ExamScheduleSerializer(serializers.ModelSerializer):
    exam_name = serializers.CharField(source="exam.name", read_only=True)
    zone_name = serializers.CharField(source="zone.name", read_only=True, default="")
    is_open = serializers.SerializerMethodField()

    class Meta:
        model = ExamSchedule
        fields = (
            "id", "exam", "exam_name", "zone", "zone_name", "exam_date",
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
        return attrs
