from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from apps.common.region_scope import ensure_in_region, region_pk, zone_region
from apps.controls import offers as offer_services
from apps.exams.models import Exam
from apps.controls.models import (
    AllowedPublicIp,
    ClientExitPassword,
    CocoObject,
    CocoObjectGroup,
    EventRiskWeight,
    HotKeyboardKey,
    ModelVersion,
    Offer,
    OfferRevision,
    ProctoringPolicy,
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
    # Tarmoq yozuvida IP bo'sh: panel formasi bo'sh maydonni `""` qilib
    # yuboradi, DRF esa `GenericIPAddressField` uchun bo'sh satrni rad
    # etardi. Bo'sh qiymat `validate` da `None` ga aylanadi; unikallik
    # tekshiruvi saqlanadi (bo'sh qiymatda ishlamaydi).
    ip_address = serializers.IPAddressField(
        required=False, allow_null=True, allow_blank=True,
        validators=[UniqueValidator(queryset=AllowedPublicIp.objects.all())],
    )

    class Meta:
        model = AllowedPublicIp
        fields = (
            "id", "zone", "zone_name", "region", "region_name",
            "name", "ip_address", "network", "is_active", "created_at",
        )
        read_only_fields = ("id", "created_at")

    def validate(self, attrs):
        # Binosiz (umumiy) manzil — respublika darajasidagi qaror: u
        # BARCHA binolarga ochiladi va viloyat xodimi uni yarata olmaydi.
        ensure_in_region(
            self, attrs, "zone", region_of=zone_region,
            message="Faqat o'z viloyatingiz binosi uchun manzil qo'sha olasiz",
            null_message="Binosiz (umumiy) manzilni faqat respublika administratori qo'shadi",
        )
        # IP yoki tarmoq — qoida Django admin bilan BITTA
        # (`services.clean_allowlist_entry`). PATCH'da yuborilmagan maydon
        # yozuvdagi qiymatda qoladi.
        from django.core.exceptions import ValidationError as DjangoValidationError

        from apps.controls.services import clean_allowlist_entry

        instance = self.instance
        try:
            attrs["ip_address"], attrs["network"] = clean_allowlist_entry(
                ip_address=attrs.get("ip_address", getattr(instance, "ip_address", None)),
                network=attrs.get("network", getattr(instance, "network", "")),
                exclude_pk=getattr(instance, "pk", None),
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict)
        return attrs


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
        # Boshqa viloyatning kiosk kalitini o'rnatish — o'sha viloyatdagi
        # har bir imtihon mashinasini ochish demak.
        ensure_in_region(
            self, attrs, "region", region_of=region_pk,
            message="Faqat o'z viloyatingiz parolini o'rnata olasiz",
        )
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
        fields = (
            "id", "name", "code", "category", "process_names",
            "publishers", "original_filenames", "products",
            "service_names", "ports", "is_blocking", "is_active",
        )

    #: Client qoidani shu ro'yxatlar bo'yicha qidiradi
    #: (`client/services/device_watch.py`) — hammasi bo'sh qoida HECH
    #: NARSANI tutmaydi, panelda esa "taqiqlangan" bo'lib ko'rinardi.
    SIGN_FIELDS = (
        "publishers", "original_filenames", "products",
        "service_names", "ports", "process_names",
    )

    def validate(self, attrs):
        def current(name):
            if name in attrs:
                return attrs[name]
            return getattr(self.instance, name, None) if self.instance else None

        if not any(current(name) for name in self.SIGN_FIELDS):
            raise serializers.ValidationError(
                {"process_names": "Kamida bitta aniqlash belgisi kiriting — belgisiz yozuvni client topa olmaydi"}
            )
        return attrs


class HotKeyboardKeySerializer(serializers.ModelSerializer):
    class Meta:
        model = HotKeyboardKey
        fields = ("id", "name", "code", "is_active")

    def validate_code(self, value):
        # Client tanimagan kod imtihonda JIMGINA bloklanmaydi
        # (`controls/hotkeys.py`) — shuning uchun saqlashdan oldin.
        from apps.controls.hotkeys import clean_hotkey

        try:
            canonical = clean_hotkey(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        # Model `unique` tekshiruvi XOM qiymatga qaradi: `printscreen` va
        # `print screen` bitta tugma — kanonik shakl bo'yicha qayta.
        duplicate = HotKeyboardKey.objects.filter(code=canonical)
        if self.instance is not None:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise serializers.ValidationError("Bu kombinatsiya allaqachon ro'yxatda bor")
        return canonical


class _ProfilesMixin(serializers.Serializer):
    """
    Yozuv qaysi sozlama profillarida yoqilgan.

    Dastur yoki tugma O'ZI hech narsa qilmaydi: client faqat imtihon
    profiliga (`Setting.rdp_objects` / `hotkeys`) kirganlarini oladi
    (`services._serialize`). Ilgari panel buni ko'rsatmasdi — yangi
    yozuv qo'shilib, hech bir profilga kiritilmasa ham "ishlayapti"
    deb o'ylanardi. Ro'yxat viewset'dagi `Prefetch(to_attr=...)` dan
    (N+1 yo'q); faqat ro'yxat/tafsilot javobida — `SettingSerializer`
    ichidagi nusxa (`*_detail`) bu maydonni olmaydi.
    """

    profiles = serializers.SerializerMethodField()

    def get_profiles(self, obj):
        profiles = getattr(obj, "alive_profiles", None)
        if profiles is None:
            profiles = obj.settings.alive().order_by("-is_active", "name")
        return [
            {"id": item.id, "name": item.name, "is_default": item.is_active}
            for item in profiles
        ]


class RdpObjectListSerializer(_ProfilesMixin, RdpObjectSerializer):
    class Meta(RdpObjectSerializer.Meta):
        fields = (*RdpObjectSerializer.Meta.fields, "profiles", "created_at", "updated_at")


class HotKeyboardKeyListSerializer(_ProfilesMixin, HotKeyboardKeySerializer):
    class Meta(HotKeyboardKeySerializer.Meta):
        fields = (*HotKeyboardKeySerializer.Meta.fields, "profiles", "created_at", "updated_at")


class SettingSerializer(serializers.ModelSerializer):
    detect_classes_detail = CocoObjectSerializer(source="detect_classes", many=True, read_only=True)
    rdp_objects_detail = RdpObjectSerializer(source="rdp_objects", many=True, read_only=True)
    hotkeys_detail = HotKeyboardKeySerializer(source="hotkeys", many=True, read_only=True)
    detect_model_name = serializers.CharField(source="detect_model.name", read_only=True, default="")
    #: Shu profilning AI kuzatuv holati (`ProctoringPolicy`) - FAQAT O'QISH.
    #
    # NIMA UCHUN BU YERDA. Obyekt aniqlash (YOLO) kaliti shu profilda,
    # AI kuzatuvning bosh kaliti esa ALOHIDA modelda va panelning boshqa
    # bo'limida («AI kuzatuv -> Kuzatuv siyosati»). YOLO faqat ikkalasi
    # ham yoqilganda ishlaydi (`controls.services._serialize_proctoring`)
    # va ilgari profil sahifasida buni aytadigan hech narsa yo'q edi:
    # administrator YOLO ni yoqib, siyosat yaratmagan edi - client esa
    # jimgina "AI kuzatuv siyosatda o'chirilgan" deb ishlayverdi.
    ai_proctoring = serializers.SerializerMethodField()
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

    def get_ai_proctoring(self, obj) -> dict:
        # Teskari one-to-one yo'q bo'lsa `RelatedObjectDoesNotExist`
        # (u `AttributeError` ham) - `getattr` standart qiymati ishlaydi.
        policy = getattr(obj, "proctoring", None)
        enabled = bool(policy and policy.is_enabled)
        return {
            "policy_id": policy.pk if policy else None,
            "enabled": enabled,
            # Client'ga ketadigan `modules.objects` bilan AYNAN bir xil
            # formula - panel boshqa narsani va'da qilmasligi kerak.
            "objects": bool(enabled and policy.enable_objects and obj.is_enable_detect),
            "evidence": bool(enabled and policy.evidence_enabled),
        }

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
        far_warn = attrs.get("faceid_far_warn_s", getattr(self.instance, "faceid_far_warn_s", 10))
        far_unverified = attrs.get(
            "faceid_far_unverified_s", getattr(self.instance, "faceid_far_unverified_s", 120)
        )
        if far_unverified < far_warn:
            # Ikkinchi bosqich birinchisidan oldin kela olmaydi - client
            # baribir tenglashtirardi, panel esa boshqa narsani ko'rsatardi.
            raise serializers.ValidationError(
                {"faceid_far_unverified_s": "Ogohlantirish vaqtidan kam bo'lmasligi kerak"}
            )
        # Bazadagi `setting_screenshot_has_destination` cheklovining
        # aynan o'zi: DRF `CheckConstraint` dan validator yasamaydi va
        # usiz qisman `PATCH` 500 (`IntegrityError`) olardi.
        keep_local = attrs.get(
            "is_screenshot_local", getattr(self.instance, "is_screenshot_local", True)
        )
        upload = attrs.get(
            "is_screenshot_upload", getattr(self.instance, "is_screenshot_upload", True)
        )
        if not keep_local and not upload:
            raise serializers.ValidationError(
                {"is_screenshot_local": "Skrinshot kamida bitta joyda saqlanishi kerak (mashinada yoki serverda)"}
            )
        return attrs


class ProctoringPolicySerializer(serializers.ModelSerializer):
    """
    AI kuzatuv siyosati.

    `setting` almashtirilishi mumkin emas (`OneToOne`), lekin uni
    `read_only` qilib bo'lmaydi - yaratishda u kerak. Shuning uchun
    tahrirlashda `validate` uni qulflaydi: siyosatni boshqa profilga
    ko'chirish "kuzatuv sozlamasi qayerdan keldi?" degan savolni
    tarixdan yo'qotardi va bu audit izini buzardi.
    """

    setting_name = serializers.CharField(source="setting.name", read_only=True)
    setting_is_active = serializers.BooleanField(source="setting.is_active", read_only=True)

    class Meta:
        model = ProctoringPolicy
        fields = (
            "id", "setting", "setting_name", "setting_is_active", "is_enabled",
            # kamera
            "camera_count", "primary_camera_kind", "secondary_camera_kind",
            "primary_required", "secondary_required", "allow_virtual_camera",
            "min_fps", "min_width", "min_height",
            "camera_lost_grace_s", "camera_lost_action",
            # modullar
            "enable_identity", "enable_objects", "enable_pose", "enable_gaze",
            "enable_tracking",
            "identity_fps", "object_fps", "pose_fps", "gaze_fps", "gpu_profile_override",
            # temporal
            "no_face_warn_s", "no_face_suspicious_s",
            "gaze_away_warn_s", "gaze_away_suspicious_s",
            "object_min_frames", "object_min_conf", "object_min_duration_ms",
            "fusion_window_ms",
            # xavf
            "risk_decay_per_min", "risk_event_cooldown_s",
            "threshold_low", "threshold_medium", "threshold_high",
            # dalil
            "evidence_enabled", "evidence_clip_seconds", "evidence_min_severity",
            "evidence_clip_retention_days", "evidence_frame_retention_days",
            "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def validate(self, attrs):
        if self.instance is not None and "setting" in attrs:
            if attrs["setting"].pk != self.instance.setting_id:
                raise serializers.ValidationError(
                    {"setting": "Siyosatni boshqa profilga ko'chirib bo'lmaydi"}
                )

        def value(name):
            """
            Maydonning KUCHGA KIRADIGAN qiymati.

            Uchta manba, shu tartibda: so'rovda kelgani, mavjud
            yozuvdagisi, modeldagi standart. Uchinchisi shart:
            DRF model standartini `validated_data` ga QO'YMAYDI
            (maydon shunchaki `required=False` bo'ladi), ya'ni
            yaratishda yuborilmagan maydon `None` bo'lib kelardi
            va tekshiruv `NoneType < NoneType` bilan yiqilardi.
            """
            if name in attrs:
                return attrs[name]
            if self.instance is not None:
                return getattr(self.instance, name)
            return ProctoringPolicy._meta.get_field(name).default

        # Chegaralar DB darajasida ham tekshiriladi, lekin u yerda xato
        # `IntegrityError` bo'lib chiqadi va panelda qaysi maydon
        # aybdorligi ko'rinmaydi.
        low, medium, high = value("threshold_low"), value("threshold_medium"), value("threshold_high")
        if not (low < medium < high):
            raise serializers.ValidationError(
                {"threshold_medium": "Chegaralar o'sish tartibida bo'lishi kerak: past < o'rta < yuqori"}
            )

        # Ikkinchi kamera majburiy, lekin kameralar soni bitta -
        # bu holat imtihonni HECH QACHON boshlanmaydigan qiladi va uni
        # faqat imtihon kuni sezish mumkin.
        if value("camera_count") == 1 and value("secondary_required"):
            raise serializers.ValidationError(
                {
                    "secondary_required": (
                        "Kameralar soni 1 bo'lganda ikkilamchi kamerani majburiy "
                        "qilib bo'lmaydi - imtihon hech qachon boshlanmaydi"
                    )
                }
            )
        return attrs


class EventRiskWeightSerializer(serializers.ModelSerializer):
    """Hodisa turi -> xavf og'irligi."""

    #: Turdagi xatoni panelda darhol ko'rsatish uchun: noma'lum tur
    #: jimgina yozilib, hech qachon ishlamasdi.
    event_type = serializers.CharField(max_length=48)

    class Meta:
        model = EventRiskWeight
        fields = (
            "id", "event_type", "weight", "cooldown_s",
            "is_active", "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")
        # Cooldown endi haqiqatan ishlaydi, ya'ni katta qiymat xavfli:
        # 32767 s (~9 soat) butun imtihon davomida shu turdagi hodisani
        # ballga faqat BIR MARTA qo'shardi. Chegara paneldagi bilan bir xil.
        extra_kwargs = {"cooldown_s": {"max_value": 3600}}

    def validate_event_type(self, value):
        from apps.proctoring.models import ProctoringEvent

        value = value.strip()
        if value not in ProctoringEvent.Type.values:
            raise serializers.ValidationError(
                "Noma'lum hodisa turi. Ruxsat etilganlari: "
                + ", ".join(sorted(ProctoringEvent.Type.values)[:8])
                + " ..."
            )
        return value


class OfferSerializer(serializers.ModelSerializer):
    """
    Oferta (panel). Yozish faqat `offers.save_offer` orqali — versiya qoidasi.

    `content` kirishda TOZALANADI (`offers.clean_content`) va javobda
    tozalangan shaklda qaytadi: muharrir saqlangandan keyin AYNAN bazadagi
    matnni ko'rsatadi (olib tashlangan teg panelda ham yo'qoladi).

    `exams` — shu ofertani so'raydigan testlar (bog'lanish `Exam.offer`
    da). Ro'yxat to'liq almashtiriladi: boshqa ofertadagi test tanlansa
    shu ofertaga ko'chadi (`offers.assign_exams`).
    """

    updated_by_name = serializers.SerializerMethodField()
    #: `OfferViewSet.get_queryset` annotatsiyasi; ro'yxatda N+1 bo'lmasin.
    consents_count = serializers.IntegerField(read_only=True, default=0)
    exams = serializers.PrimaryKeyRelatedField(
        many=True, required=False, queryset=Exam.objects.alive(),
    )
    exam_list = serializers.SerializerMethodField()

    class Meta:
        model = Offer
        fields = (
            "id", "title", "content", "version", "is_active", "exams", "exam_list",
            "updated_by_name", "consents_count", "created_at", "updated_at", "deleted_at",
        )
        read_only_fields = ("id", "version", "created_at", "updated_at", "deleted_at")

    def _alive_exams(self, obj) -> list:
        # `OfferViewSet` faqat tirik imtihonlarni oldindan yuklaydi
        # (`alive_exams`); boshqa joydan chaqirilsa — so'rov bilan.
        cached = getattr(obj, "alive_exams", None)
        if cached is not None:
            return cached
        return list(obj.exams.alive().order_by("name")) if obj.pk else []

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Standart `exams` o'chirilgan imtihonlarni ham qaytarardi — forma
        # ularni ko'rmaydi va saqlashda jimgina ajratib yuborardi.
        data["exams"] = [exam.pk for exam in self._alive_exams(instance)]
        return data

    def get_exam_list(self, obj) -> list[dict]:
        return [
            {"id": exam.pk, "name": exam.name, "is_active": exam.is_active}
            for exam in self._alive_exams(obj)
        ]

    def get_updated_by_name(self, obj) -> str:
        user = obj.updated_by
        if user is None:
            return ""
        return user.get_full_name() or user.username

    def validate_title(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Sarlavha bo'sh bo'lmasligi kerak")
        return value

    def validate_content(self, value):
        try:
            return offer_services.clean_content(value)
        except offer_services.OfferContentError as exc:
            raise serializers.ValidationError(str(exc))

    def _save(self, instance, validated_data):
        offer = offer_services.save_offer(
            offer=instance,
            title=validated_data.get("title", getattr(instance, "title", "")),
            content=validated_data.get("content", getattr(instance, "content", "")),
            is_active=validated_data.get("is_active"),
            exams=validated_data.get("exams"),
            actor=self.context["request"].user,
        )
        # Oldindan yuklangan ro'yxat endi eski — javob bazadan o'qisin.
        offer.__dict__.pop("alive_exams", None)
        return offer

    def create(self, validated_data):
        return self._save(None, validated_data)

    def update(self, instance, validated_data):
        return self._save(instance, validated_data)


class OfferRevisionSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    consents_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = OfferRevision
        fields = (
            "id", "version", "title", "content", "content_hash",
            "created_by_name", "consents_count", "created_at",
        )
        read_only_fields = fields

    def get_created_by_name(self, obj) -> str:
        user = obj.created_by
        if user is None:
            return ""
        return user.get_full_name() or user.username
