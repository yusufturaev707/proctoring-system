from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from apps.devices import services
from apps.devices.models import Camera, Computer, DeviceToken

# Cheklovlar SHARTLI (`deleted_at IS NULL`), DRF esa shartli
# `UniqueConstraint` dan validator yasamaydi. Ularsiz takroriy qiymat
# faqat DB darajasida ushlanib, 409 bo'lib qaytardi — ya'ni xato aniq
# maydonga bog'lanmasdi. Quyidagi validatorlar buni tiklaydi.
_alive_camera_mac = UniqueValidator(
    queryset=Camera.objects.alive(), message="Bunday MAC manzilli kamera allaqachon mavjud"
)
_alive_computer_mac = UniqueValidator(
    queryset=Computer.objects.alive(), message="Bunday MAC manzilli kompyuter allaqachon mavjud"
)
_alive_computer_code = UniqueValidator(
    queryset=Computer.objects.alive(), message="Bunday inventar kodi allaqachon ishlatilgan"
)


class CameraSerializer(serializers.ModelSerializer):
    zone_name = serializers.CharField(source="zone.name", read_only=True)
    region_name = serializers.CharField(source="zone.region.name", read_only=True)
    # Viloyat kameraning O'Z maydoni emas — u bino orqali aniqlanadi.
    # Lekin panelda forma "avval viloyat, keyin o'sha viloyatning binolari"
    # tartibida ishlaydi, ya'ni tahrirlashda viloyatni oldindan tanlab
    # qo'yish uchun uning ID'si kerak. Faqat o'qish uchun: yozishda bu
    # maydon e'tiborga olinmaydi, haqiqiy bog'lanish `zone` orqali.
    region = serializers.IntegerField(source="zone.region_id", read_only=True)
    mac_address = serializers.CharField(max_length=17, validators=[_alive_camera_mac])
    # Parol faqat YOZISH uchun. RTSP URL ham qaytarilmaydi — aks holda
    # login/parol React DevTools va network tab'da ochiq ko'rinadi.
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    has_password = serializers.SerializerMethodField()

    class Meta:
        model = Camera
        fields = (
            "id", "name", "zone", "zone_name", "region", "region_name",
            "ip_address", "mac_address", "rtsp_path", "login", "password",
            "has_password", "status", "last_seen_at", "is_active", "created_at", "deleted_at",
        )
        read_only_fields = ("id", "status", "last_seen_at", "created_at", "deleted_at")

    def get_has_password(self, obj) -> bool:
        return bool(obj.password_encrypted)

    def create(self, validated_data):
        raw_password = validated_data.pop("password", "")
        camera = Camera(**validated_data)
        if raw_password:
            services.set_camera_password(camera, raw_password)
        camera.save()
        return camera

    def update(self, instance, validated_data):
        raw_password = validated_data.pop("password", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if raw_password:
            services.set_camera_password(instance, raw_password)
        instance.save()
        return instance


class ComputerSerializer(serializers.ModelSerializer):
    zone_name = serializers.CharField(source="zone.name", read_only=True)
    region_name = serializers.CharField(source="zone.region.name", read_only=True)
    # Qarang: `CameraSerializer.region` — bino orqali olinadi, faqat o'qish.
    region = serializers.IntegerField(source="zone.region_id", read_only=True)
    # `queryset` sifatida `alive()` — `Camera.objects` standart menejeri
    # yumshoq o'chirilganlarni ham qaytaradi, ya'ni hisobdan chiqarilgan
    # kamerani qayta biriktirib bo'lardi.
    cameras = serializers.PrimaryKeyRelatedField(
        many=True, required=False, queryset=Camera.objects.alive()
    )
    cameras_detail = serializers.SerializerMethodField()
    active_session_id = serializers.IntegerField(read_only=True, required=False)
    inventory_code = serializers.CharField(max_length=50, validators=[_alive_computer_code])
    mac_address = serializers.CharField(max_length=17, validators=[_alive_computer_mac])

    class Meta:
        model = Computer
        fields = (
            "id", "zone", "zone_name", "region", "region_name", "inventory_code",
            "ip_address", "mac_address", "info_pc", "cameras", "cameras_detail",
            "status", "last_seen_at", "is_active", "active_session_id", "created_at",
            "deleted_at",
        )
        read_only_fields = ("id", "status", "last_seen_at", "created_at", "deleted_at")

    @staticmethod
    def _alive_cameras(instance) -> list:
        """
        Bog'langan kameralarning yumshoq o'chirilmaganlari.

        Filtr Python'da, `.alive()` bilan EMAS: `instance.cameras.all()`
        view'dagi `Prefetch` keshidan keladi, queryset'ga yangi filtr
        qo'shilsa esa kesh chetlab o'tiladi va har bir kompyuter uchun
        alohida so'rov ketadi (ro'yxatda — N+1).
        """
        return [c for c in instance.cameras.all() if c.deleted_at is None]

    def get_cameras_detail(self, obj) -> list:
        return CameraSerializer(
            self._alive_cameras(obj), many=True, context=self.context
        ).data

    def to_representation(self, instance):
        # `cameras` ham, `cameras_detail` ham bir xil ro'yxatni ko'rsatishi
        # kerak. M2M through-jadvali yumshoq o'chirishda tozalanmaydi
        # (`Camera.delete()` faqat `deleted_at` qo'yadi), shuning uchun
        # xom bog'lanish o'chirilgan kamera ID'sini ham qaytarardi va
        # panel formasida "arvoh" tanlov bo'lib qolardi.
        data = super().to_representation(instance)
        data["cameras"] = [camera.pk for camera in self._alive_cameras(instance)]
        return data

    def validate(self, attrs):
        """
        Kamera va kompyuter BIR BINODA bo'lishi shart.

        Bog'lanish "egalik" emas, "qamrov" — boshqa binodagi kamera bu
        xonani jismonan ko'rmaydi. Panel formasi tanlovni bino bo'yicha
        filtrlaydi (`camerasOfZone`), lekin u faqat qulaylik: API'ga
        to'g'ridan-to'g'ri yuborilgan ID hech qayerda tekshirilmasdi va
        shu yo'l bilan `RegionScopedPermission` chegarasi ham chetlab
        o'tilardi (begona viloyat kamerasini biriktirish mumkin edi).
        """
        zone = attrs.get("zone") or getattr(self.instance, "zone", None)
        cameras = attrs.get("cameras")

        if cameras is None and "zone" in attrs and self.instance is not None:
            # Bino almashtirilyapti, kameralar yuborilmagan — mavjud
            # bog'lanishlar yangi binoda ma'nosiz bo'lib qoladi.
            # (Panel formasi `resets: ['cameras']` bilan buni o'zi
            # tozalaydi; tekshiruv to'g'ridan-to'g'ri API uchun.)
            cameras = self._alive_cameras(self.instance)

        if not cameras or zone is None:
            return attrs

        alien = [camera for camera in cameras if camera.zone_id != zone.pk]
        if alien:
            raise serializers.ValidationError(
                {
                    "cameras": (
                        "Boshqa binodagi kamerani biriktirib bo'lmaydi: "
                        + ", ".join(f"{c.name} — {c.zone}" for c in alien)
                    )
                }
            )
        return attrs


class DeviceTokenSerializer(serializers.ModelSerializer):
    computer_code = serializers.CharField(source="computer.inventory_code", read_only=True)
    zone_name = serializers.CharField(source="computer.zone.name", read_only=True)

    class Meta:
        model = DeviceToken
        fields = (
            "id", "device_id", "computer", "computer_code", "zone_name",
            "hardware_fingerprint", "app_version", "app_hash", "status",
            "last_used_at", "last_ip", "reported_public_ip",
            "revoked_at", "revoke_reason", "created_at",
        )
        read_only_fields = (
            "id", "device_id", "last_used_at", "last_ip", "reported_public_ip",
            "revoked_at", "created_at",
        )


class DeviceRegisterSerializer(serializers.Serializer):
    """Client birinchi marta ro'yxatdan o'tishi."""

    inventory_code = serializers.CharField(max_length=50, required=False, allow_blank=True)
    mac_address = serializers.CharField(max_length=17, required=False, allow_blank=True)
    ip_address = serializers.IPAddressField(required=False, allow_blank=True)
    # Client o'zi aniqlagan tashqi manzil. Ixtiyoriy: internet bo'lmasa
    # yoki provayderlar javob bermasa client uni bo'sh yuboradi.
    public_ip = serializers.IPAddressField(required=False, allow_blank=True)
    hardware_fingerprint = serializers.CharField(max_length=128, required=False, allow_blank=True)
    app_version = serializers.CharField(max_length=32, required=False, allow_blank=True)
    app_hash = serializers.CharField(max_length=64, required=False, allow_blank=True)
    info_pc = serializers.JSONField(required=False)

    def validate(self, attrs):
        if not any([attrs.get("inventory_code"), attrs.get("mac_address"), attrs.get("ip_address")]):
            raise serializers.ValidationError(
                "inventory_code, mac_address yoki ip_address dan kamida bittasi kerak"
            )
        return attrs
