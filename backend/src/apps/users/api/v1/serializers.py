from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from apps.regions.models import Region, Zone
from apps.users.models import FaceProfile, Permission, Role, User


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ("id", "code", "name", "group")


class RoleSerializer(serializers.ModelSerializer):
    permissions = PermissionSerializer(many=True, read_only=True)
    permission_ids = serializers.PrimaryKeyRelatedField(
        queryset=Permission.objects.all(),
        many=True,
        write_only=True,
        required=False,
        source="permissions",
    )
    users_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Role
        fields = (
            "id", "name", "key", "description", "is_active", "is_global",
            "permissions", "permission_ids", "users_count", "created_at",
        )
        read_only_fields = ("id", "created_at")


class UserListSerializer(serializers.ModelSerializer):
    """Ro'yxat uchun yengil versiya — nested obyektlarsiz."""

    full_name = serializers.CharField(source="get_full_name", read_only=True)
    role_name = serializers.CharField(read_only=True)
    region_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = (
            "id", "username", "full_name", "first_name", "last_name", "middle_name",
            "phone", "is_active", "is_staff", "is_superuser",
            "role", "role_name", "region", "region_name", "zone",
            "last_login_at", "created_at",
        )


class UserDetailSerializer(UserListSerializer):
    permissions = serializers.SerializerMethodField()
    has_face_profile = serializers.SerializerMethodField()
    #: Panel uchun: "nega hech narsa ko'rinmayapti?" degan savolga ochiq
    #: javob (`User.lacks_region`) va viloyat tanlash maydonlarini
    #: qulflash kerakmi (`is_region_scoped`). Ikkalasi ham server
    #: qoidasining nusxasi — frontend o'zi hisoblasa, rol matritsasi
    #: o'zgarganda ajralib ketardi.
    lacks_region = serializers.BooleanField(read_only=True)
    is_region_scoped = serializers.BooleanField(read_only=True)

    class Meta(UserListSerializer.Meta):
        fields = UserListSerializer.Meta.fields + (
            "telegram_id", "permissions", "has_face_profile", "last_login_ip", "updated_at",
            "lacks_region", "is_region_scoped",
        )

    def get_permissions(self, obj) -> list[str]:
        return obj.permission_codes()

    def get_has_face_profile(self, obj) -> bool:
        return hasattr(obj, "face_profile") and bool(obj.face_profile.embedding)


class UserWriteSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, min_length=3)
    role = serializers.PrimaryKeyRelatedField(
        queryset=Role.objects.all(), required=False, allow_null=True
    )
    region = serializers.PrimaryKeyRelatedField(
        queryset=Region.objects.all(), required=False, allow_null=True
    )
    zone = serializers.PrimaryKeyRelatedField(
        queryset=Zone.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = User
        fields = (
            "id", "username", "password", "first_name", "last_name", "middle_name",
            "phone", "telegram_id", "role", "region", "zone", "is_active", "is_staff",
        )

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate(self, attrs):
        """
        Imtiyozni oshirishga (privilege escalation) qarshi tekshiruv.

        `get_queryset()` viloyatga biriktirilgan adminni faqat O'Z
        viloyatidagi xodimlarni KO'RISH bilan cheklaydi, lekin yozishda
        hech qanday to'siq yo'q edi. Natijada ikkita teshik bor edi:

          * boshqa viloyatga xodim yaratish (keyin uni ko'rmaydi, lekin
            hisob ishlaydi);
          * o'zida yo'q ruxsatlarni beruvchi rolni biriktirish — masalan
            `controls.manage` ni yangi hisobga berib, o'sha hisob bilan
            kirish. Bu rol matritsasidagi har qanday ajratishni
            ma'nosiz qilardi.

        Superuser bu tekshiruvdan o'tadi.
        """
        self._validate_scope_shape(attrs)

        actor = getattr(self.context.get("request"), "user", None)
        if actor is None or not actor.is_authenticated or actor.is_superuser:
            return attrs

        if actor.is_region_scoped:
            region = attrs.get("region", getattr(self.instance, "region", None))
            if getattr(region, "pk", None) != actor.region_id:
                raise serializers.ValidationError(
                    {"region": "Faqat o'z viloyatingizga xodim qo'sha olasiz"}
                )
            # Respublika roli viloyat chegarasini BUTUNLAY olib tashlaydi
            # (`User.is_region_scoped`). Ruxsatlar tekshiruvi buni
            # ushlamasdi: kam ruxsatli respublika roli (masalan faqat
            # `sessions.view`) viloyat adminining o'zida ham bor, ya'ni u
            # yangi hisob orqali barcha viloyatlarning sessiyalarini
            # ko'ra olardi.
            role = attrs.get("role")
            if role is not None and role.is_global:
                raise serializers.ValidationError(
                    {"role": "Respublika darajasidagi rolni faqat respublika administratori beradi"}
                )

        role = attrs.get("role")
        if role is not None:
            missing = sorted(
                code
                for code in role.permissions.values_list("code", flat=True)
                if not actor.has_role_permission(code)
            )
            if missing:
                raise serializers.ValidationError(
                    {
                        "role": "Bu rolda sizda yo'q ruxsatlar bor: "
                        + ", ".join(missing[:5])
                    }
                )

        # `is_staff` Django admin paneliga kirish demak - uni faqat
        # superuser bera oladi.
        if attrs.get("is_staff") and not getattr(self.instance, "is_staff", False):
            raise serializers.ValidationError(
                {"is_staff": "Xodimga admin panel huquqini faqat superuser beradi"}
            )
        return attrs

    def _validate_scope_shape(self, attrs):
        """
        Hisobning o'zi izchil bo'lishi — kim yaratayotganidan qat'i nazar.

          * viloyat darajasidagi rol VILOYATSIZ bo'lmaydi: bunday hisob
            admin panelda hech narsa ko'rmaydi (`User.lacks_region`), ya'ni
            u faqat "ishlamaydigan xodim" yaratardi;
          * bino tanlangan viloyatning binosi bo'lishi shart — aks holda
            xodim bir viloyatga, binosi boshqasiga yozilardi.

        Tahrirda yuborilmagan maydonlar joriy qiymatdan olinadi: faqat
        rolni almashtirish ham shu qoidadan o'tadi.
        """
        def current(name):
            return attrs[name] if name in attrs else getattr(self.instance, name, None)

        role, region, zone = current("role"), current("region"), current("zone")
        if role is not None and not role.is_global and region is None:
            raise serializers.ValidationError(
                {"region": "Bu rol viloyat darajasida — viloyatni tanlang"}
            )
        if zone is not None and region is not None and zone.region_id != region.pk:
            raise serializers.ValidationError(
                {"zone": "Bino tanlangan viloyatga tegishli emas"}
            )

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        if not password:
            raise serializers.ValidationError({"password": "Parol kiritilishi shart"})
        return User.objects.create_user(password=password, **validated_data)

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class SetPasswordSerializer(serializers.Serializer):
    password = serializers.CharField(min_length=3, write_only=True)

    def validate_password(self, value):
        validate_password(value)
        return value


class FaceProfileSerializer(serializers.ModelSerializer):
    embedding = serializers.ListField(
        child=serializers.FloatField(), write_only=True, required=False, allow_null=True
    )
    has_embedding = serializers.SerializerMethodField()

    class Meta:
        model = FaceProfile
        fields = ("id", "photo_key", "embedding", "has_embedding", "embedding_model", "is_active", "updated_at")
        read_only_fields = ("id", "updated_at")

    def get_has_embedding(self, obj) -> bool:
        return bool(obj.embedding)


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate(self, attrs):
        request = self.context.get("request")
        user = authenticate(
            request, username=attrs["username"].strip(), password=attrs["password"]
        )
        if user is None:
            # Ataylab umumiy xabar: "bunday login yo'q" va "parol xato"
            # javoblarini ajratish login enumeration'ga imkon beradi.
            raise serializers.ValidationError("Login yoki parol noto'g'ri")
        if not user.is_active:
            raise serializers.ValidationError("Hisob bloklangan")

        # Rolsiz hisobga token BERILMAYDI.
        #
        # Ilgari bunday hisob muvaffaqiyatli kirar, panel ochilar, lekin
        # har bir sahifa "ruxsat yo'q" ko'rsatardi: har bir endpoint
        # `HasRolePermission` dan o'tadi. Bu ikki jihatdan yomon edi -
        # xodim nima bo'layotganini tushunmasdi, va foydasiz token
        # baribir amal qilib turardi (o'g'irlansa, hisobga keyin rol
        # berilishi bilan ishlay boshlardi).
        #
        # `is_superuser` - ataylab istisno: u zaxira yo'l va rol talab
        # qilmaydi (`HasRolePermission` da ham shunday).
        if not user.is_superuser and not (user.role_id and user.role.is_active):
            raise serializers.ValidationError(
                "Hisobingizga faol rol biriktirilmagan. Administratorga murojaat qiling."
            )

        attrs["user"] = user
        return attrs


class TokenPairSerializer(serializers.Serializer):
    """Login javobi."""

    access = serializers.CharField()
    refresh = serializers.CharField()
    user = UserDetailSerializer()

    @classmethod
    def for_user(cls, user, context=None):
        refresh = RefreshToken.for_user(user)
        # Front-end har so'rovda `/me/` chaqirmasligi uchun rolni claim'ga qo'shamiz.
        refresh["role"] = user.role_key
        refresh["region_id"] = user.region_id
        return {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": UserDetailSerializer(user, context=context or {}).data,
        }
