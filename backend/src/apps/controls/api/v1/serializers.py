from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from apps.controls.models import (
    AllowedPublicIp,
    ClientExitPassword,
    CocoObject,
    CocoObjectGroup,
    HotKeyboardKey,
    ModelVersion,
    RdpObject,
    Setting,
)


class AllowedPublicIpSerializer(serializers.ModelSerializer):
    zone_name = serializers.CharField(source="zone.name", read_only=True, default="")
    # Viloyat modelda YO'Q — u bino orqali aniqlanadi. Lekin panel formasi
    # "avval viloyat, keyin o'sha viloyatning binolari" tartibida ishlaydi,
    # ya'ni tahrirlashda viloyatni oldindan tanlab qo'yish uchun uning
    # ID'si kerak. Faqat o'qish: yozishda e'tiborga olinmaydi, haqiqiy
    # bog'lanish `zone` orqali (`CameraSerializer` dagi bilan bir xil naqsh).
    region = serializers.IntegerField(source="zone.region_id", read_only=True, default=None)
    region_name = serializers.CharField(source="zone.region.name", read_only=True, default="")

    class Meta:
        model = AllowedPublicIp
        fields = (
            "id", "zone", "zone_name", "region", "region_name",
            "name", "ip_address", "is_active", "created_at",
        )
        read_only_fields = ("id", "created_at")


class ClientExitPasswordSerializer(serializers.ModelSerializer):
    """
    Chiqish paroli — o'qishda parol MAYDONI umuman qaytmaydi.

    `write_only` yetarli emas deb o'ylash mumkin, lekin aynan shu kerak:
    javobda parol bo'lmasligi kerak, formada esa uni kiritish mumkin.
    Tahrirlashda maydon bo'sh qoldirilsa — eski parol saqlanadi
    (`update` da tekshiriladi), ya'ni "nomni o'zgartiraman" degan
    tahrir parolni tasodifan yo'q qilib qo'ymaydi.
    """

    region_name = serializers.CharField(source="region.name", read_only=True, default="")
    password = serializers.CharField(
        write_only=True, required=False, allow_blank=True,
        style={"input_type": "password"}, min_length=4, max_length=128,
        help_text="Bo'sh qoldirilsa amaldagi parol o'zgarmaydi",
    )
    #: Panelda "parol o'rnatilganmi?" ni ko'rsatish uchun — qiymatning
    #: o'zi emas, faqat mavjudligi.
    has_password = serializers.SerializerMethodField()

    class Meta:
        model = ClientExitPassword
        fields = (
            "id", "region", "region_name", "name",
            "password", "has_password", "is_active", "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def get_has_password(self, obj) -> bool:
        return bool(obj.password)

    def validate(self, attrs):
        # Yangi yozuvda parol MAJBURIY: parolsiz qator "faol, lekin hech
        # qachon mos kelmaydigan" holatni yaratardi va uni panelda
        # ajratib bo'lmasdi.
        if self.instance is None and not attrs.get("password"):
            raise serializers.ValidationError({"password": "Parol kiritilishi shart"})
        return attrs

    def create(self, validated_data):
        raw = validated_data.pop("password")
        instance = ClientExitPassword(**validated_data)
        instance.set_password(raw)
        instance.save()
        return instance

    def update(self, instance, validated_data):
        raw = validated_data.pop("password", "")
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if raw:
            instance.set_password(raw)
        instance.save()
        return instance


class ModelVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ModelVersion
        fields = ("id", "name", "code", "file_key", "is_active", "created_at")
        read_only_fields = ("id", "created_at")


class CocoObjectGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = CocoObjectGroup
        fields = ("id", "name", "code", "is_active")


class CocoObjectSerializer(serializers.ModelSerializer):
    group_name = serializers.CharField(source="group.name", read_only=True, default="")

    class Meta:
        model = CocoObject
        fields = ("id", "name", "code", "group", "group_name", "severity", "is_active")


class RdpObjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = RdpObject
        fields = ("id", "name", "code", "process_names", "is_active")


class HotKeyboardKeySerializer(serializers.ModelSerializer):
    class Meta:
        model = HotKeyboardKey
        fields = ("id", "name", "code", "is_active")


class SettingSerializer(serializers.ModelSerializer):
    detect_classes_detail = CocoObjectSerializer(source="detect_classes", many=True, read_only=True)
    rdp_objects_detail = RdpObjectSerializer(source="rdp_objects", many=True, read_only=True)
    hotkeys_detail = HotKeyboardKeySerializer(source="hotkeys", many=True, read_only=True)
    detect_model_name = serializers.CharField(source="detect_model.name", read_only=True, default="")
    # Cheklov shartli (`deleted_at IS NULL`) — DRF undan validator yasamaydi.
    name = serializers.CharField(
        max_length=100,
        validators=[
            UniqueValidator(
                queryset=Setting.objects.alive(),
                message="Bunday nomli profil allaqachon mavjud",
            )
        ],
    )

    class Meta:
        model = Setting
        exclude = ("deleted_at",)
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_faceid_audit_rate(self, value):
        if not 0 <= value <= 1:
            raise serializers.ValidationError("0 va 1 orasida bo'lishi kerak")
        return value

    def validate_detect_confidence(self, value):
        if not 0 < value <= 1:
            raise serializers.ValidationError("0 dan katta va 1 dan kichik bo'lishi kerak")
        return value

    def validate(self, attrs):
        interval = attrs.get("faceid_interval", getattr(self.instance, "faceid_interval", 10))
        if interval < 3:
            raise serializers.ValidationError(
                {"faceid_interval": "3 soniyadan kam interval clientni va serverni ortiqcha yuklaydi"}
            )
        return attrs
