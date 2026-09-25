from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from apps.common.region_scope import ensure_in_region, zone_region
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
            "ip_address", "mac_address", "rtsp_path", "vendor", "port", "transport",
            "login", "password",
            "has_password", "status", "status_message", "last_seen_at", "last_checked_at",
            "is_active", "created_at", "deleted_at",
        )
        read_only_fields = (
            "id", "status", "status_message", "last_seen_at", "last_checked_at",
            "created_at", "deleted_at",
        )

    def get_has_password(self, obj) -> bool:
        return bool(obj.password_encrypted)

    def validate(self, attrs):
        # Kamera viloyat chegarasidan chiqmaydi (`common.region_scope`).
        ensure_in_region(
            self, attrs, "zone", region_of=zone_region,
            message="Kamerani faqat o'z viloyatingiz binosiga qo'sha olasiz",
        )
        return attrs

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
    # Raqam IXTIYORIY va `0` QABUL QILINMAYDI: "0-kompyuter" degan
    # o'rin bo'lmaydi va bo'sh maydon o'rniga tushgan nol jimgina
    # yolg'on raqam yaratardi.
    number = serializers.IntegerField(
        min_value=1, max_value=32767, required=False, allow_null=True
    )
    # Ekranda ko'rsatiladigan nom ("№12 · INV-001") - panel va
    # client uni O'ZI YASAMAYDI. Ikki joyda yasalsa, bittasida
    # raqamsiz mashina "№None" bo'lib chiqardi.
    label = serializers.CharField(read_only=True)

    class Meta:
        model = Computer
        fields = (
            "id", "zone", "zone_name", "region", "region_name", "number",
            "inventory_code", "label",
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
        ensure_in_region(
            self, attrs, "zone", region_of=zone_region,
            message="Kompyuterni faqat o'z viloyatingiz binosiga qo'sha olasiz",
        )
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
    """
    Qurilma (client nusxasi) + uning HOZIRGI holati.

    `is_online` DB'dan emas, Redis'dan keladi (`presence_map`):
    "client dasturi shu daqiqada ishlab turibdimi" degan savolga
    javob beradi va TTL bilan o'zi so'nadi. `last_used_at` esa
    DB'da qoladi — u "oxirgi marta qachon ko'rindi" degan boshqa
    savol va u saralash/filtrlash uchun kerak.
    """

    computer_code = serializers.CharField(source="computer.inventory_code", read_only=True)
    # Raqam ALOHIDA maydon: panelda u ustun bo'lib saralanadi va
    # matn ichiga qo'shilsa saralash "10, 11, 2" tartibida chiqardi.
    computer_number = serializers.IntegerField(
        source="computer.number", read_only=True, default=None
    )
    zone_name = serializers.CharField(source="computer.zone.name", read_only=True)
    region_name = serializers.CharField(
        source="computer.zone.region.name", read_only=True, default=""
    )
    computer_status = serializers.CharField(source="computer.status", read_only=True, default="")
    is_online = serializers.SerializerMethodField()
    #: Client'ga kirgan xodim (Redis'dagi presence yozuvidan).
    online_staff = serializers.SerializerMethodField()
    #: `exam` — imtihon ketyapti, `idle` — talabgor kutilmoqda.
    online_state = serializers.SerializerMethodField()

    class Meta:
        model = DeviceToken
        fields = (
            "id", "device_id", "computer", "computer_code", "computer_number", "zone_name", "region_name",
            "hardware_fingerprint", "app_version", "app_hash", "status",
            "computer_status", "is_online", "online_staff", "online_state",
            "last_used_at", "last_ip", "reported_public_ip", "reported_lan_ip",
            "gpu_name", "performance_profile",
            "revoked_at", "revoke_reason", "created_at",
        )
        # PANELDAN FAQAT `computer` O'ZGARADI (qayta biriktirish).
        #
        # Holat — faqat `approve/` va `revoke/` orqali: ilgari `status`
        # ham yozilardi va `PATCH {"status": "active"}` tasdiqlashni
        # ham, blok sababini ham, ularning auditini ham chetlab o'tardi.
        # Apparat va versiya maydonlarini client YOZADI (handshake):
        # ular o'lchov natijasi va uni panelda qo'lda tuzatish "qaysi
        # mashinada kuzatuv sekin" degan ro'yxatni, `app_hash` esa
        # client butunligi tekshiruvini yolg'onga aylantirardi.
        read_only_fields = tuple(
            name for name in fields if name != "computer"
        )

    def validate_computer(self, computer):
        """
        Qayta biriktirish — obraz ko'chirilgan mashinaning TUZATISHI.

        `verify_machine` `mismatch` desa (client aytgan MAC boshqa
        kompyuterniki), administrator qurilmani to'g'ri kompyuterga
        o'tkazadi. Ikki chegara: hisobdan chiqarilgan mashinaga
        biriktirib bo'lmaydi va viloyat administratori qurilmani boshqa
        viloyatning kompyuteriga "olib keta" olmaydi — aks holda
        sessiyalari boshqa proktorning jadvaliga tushib qolardi.
        """
        if computer.deleted_at is not None:
            raise serializers.ValidationError("Kompyuter hisobdan chiqarilgan")
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_region_scoped", False):
            if computer.zone.region_id != user.region_id:
                raise serializers.ValidationError("Kompyuter sizning viloyatingizda emas")
        return computer

    def _presence(self, obj) -> dict:
        """
        Sahifadagi barcha qurilmalar uchun BITTA `MGET`.

        Natija view'dan keladi (`get_serializer_context`); u yerda
        tayyorlanmagan bo'lsa (masalan bitta obyekt so'ralganda)
        shu yerda so'raladi.
        """
        presence = self.context.get("presence")
        if presence is None:
            from apps.devices.services import presence_map

            presence = presence_map([obj.device_id])
        return presence.get(obj.device_id) or {}

    def get_is_online(self, obj) -> bool:
        return bool(self._presence(obj).get("online"))

    def get_online_staff(self, obj) -> str:
        return self._presence(obj).get("staff", "")

    def get_online_state(self, obj) -> str:
        return self._presence(obj).get("state", "")


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
