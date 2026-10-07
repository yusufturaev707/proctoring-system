from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from apps.common.exceptions import PanelAccessDenied
from apps.regions.models import Region, Zone
from apps.users.models import (
    PANEL_ACCESS_CODE,
    FaceProfile,
    Permission,
    Role,
    User,
    codes_grant,
)

#: Rol muharririda o'zidan olib tashlab bo'lmaydigan huquqlar: ularsiz
#: xodim rolni qaytarib tuzata olmaydi (panel yopiladi yoki rollar
#: sahifasi yo'qoladi) — tuzatish faqat DB/superuser orqali qolardi.
_SELF_LOCKOUT_CODES = (PANEL_ACCESS_CODE, "users.manage")


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
            "permissions", "permission_ids", "users_count", "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def validate(self, attrs):
        """
        Rol muharririda ikki xavf.

          * IMTIYOZNI OSHIRISH: `users.manage` li respublika xodimi
            O'Z rolini tahrirlab unga `*` yoki `controls.manage` qo'sha
            olardi — `UserWriteSerializer` dagi "sizda yo'q ruxsatli
            rolni bera olmaysiz" qoidasi bu yo'lni yopmasdi. Endi
            QO'SHILAYOTGAN har ruxsat tahrirlovchida bo'lishi shart
            (olib tashlash erkin).
          * O'ZINI QULFLASH: o'z rolini nofaol qilish yoki undan panel
            kirishi / `users.manage` ni olib tashlash xodimni darhol
            tizimdan chiqarib qo'yardi va qaytarish yo'li qolmasdi.

        Superuser — zaxira yo'l, tekshirilmaydi.
        """
        actor = getattr(self.context.get("request"), "user", None)
        if actor is None or not actor.is_authenticated or actor.is_superuser:
            return attrs

        old_codes = (
            set(self.instance.permissions.values_list("code", flat=True))
            if self.instance is not None else set()
        )
        if "permissions" in attrs:
            new_codes = {permission.code for permission in attrs["permissions"]}
            missing = sorted(
                code for code in new_codes - old_codes if not actor.has_role_permission(code)
            )
            if missing:
                raise serializers.ValidationError(
                    {"permission_ids": "Sizda yo'q ruxsatni rolga qo'sha olmaysiz: "
                                       + ", ".join(missing[:5])}
                )
        else:
            new_codes = old_codes

        if self.instance is not None and self.instance.pk == actor.role_id:
            if not attrs.get("is_active", self.instance.is_active):
                raise serializers.ValidationError(
                    {"is_active": "O'z rolingizni nofaol qila olmaysiz — tizimdan chiqib qolasiz"}
                )
            if not attrs.get("is_global", self.instance.is_global) and actor.region_id is None:
                raise serializers.ValidationError(
                    {"is_global": "Sizga viloyat biriktirilmagan — o'z rolingizni viloyat "
                                  "darajasiga tushirsangiz panel yopiladi"}
                )
            lost = [code for code in _SELF_LOCKOUT_CODES if not codes_grant(new_codes, code)]
            if lost:
                raise serializers.ValidationError(
                    {"permission_ids": "O'z rolingizdan bu huquqlarni olib tashlay olmaysiz: "
                                       + ", ".join(lost)}
                )
        return attrs


class RoleBriefSerializer(serializers.ModelSerializer):
    """Foydalanuvchi kartasi uchun — rolning o'zi, ruxsatlarsiz."""

    class Meta:
        model = Role
        fields = ("id", "name", "key", "description", "is_global", "is_active")


class UserListSerializer(serializers.ModelSerializer):
    """Ro'yxat uchun yengil versiya — nested obyektlarsiz."""

    full_name = serializers.CharField(source="get_full_name", read_only=True)
    role_name = serializers.CharField(read_only=True)
    region_name = serializers.CharField(read_only=True)
    zone_name = serializers.SerializerMethodField()
    #: Hisob QAYERDA ishlaydi: `panel` (`panel.access`) va `client`
    #: (`client.operate`). Jadvaldagi "Faqat client" belgisi shundan —
    #: rol nomidan taxmin qilinmaydi (rollar panelda qayta nomlanadi).
    surfaces = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id", "username", "full_name", "first_name", "last_name", "middle_name",
            "phone", "is_active", "is_staff", "is_superuser",
            "role", "role_name", "region", "region_name", "zone", "zone_name",
            "surfaces", "last_login_at", "created_at",
        )

    def get_zone_name(self, obj) -> str:
        return obj.zone.name if obj.zone_id else ""

    def get_surfaces(self, obj) -> list[str]:
        surfaces = []
        if obj.has_panel_access:
            surfaces.append("panel")
        if obj.has_role_permission("client.operate"):
            surfaces.append("client")
        return surfaces


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
    #: Panel `/me/` dan oladi: eski token bilan qolgan client roli
    #: (Operator) uchun "bu hisob panel uchun emas" ekrani.
    has_panel_access = serializers.BooleanField(read_only=True)
    role_detail = RoleBriefSerializer(source="role", read_only=True)
    #: Foydalanuvchi kartasi uchun: kod emas, NOM va guruh bilan.
    permission_details = serializers.SerializerMethodField()

    class Meta(UserListSerializer.Meta):
        fields = UserListSerializer.Meta.fields + (
            "telegram_id", "permissions", "permission_details", "has_face_profile",
            "last_login_ip", "updated_at", "lacks_region", "is_region_scoped",
            "has_panel_access", "role_detail",
        )

    def get_permissions(self, obj) -> list[str]:
        return obj.permission_codes()

    def get_permission_details(self, obj) -> list[dict]:
        # Superuser rolga bog'liq emas (`permission_codes() == ["*"]`) —
        # ro'yxat bo'sh, panel `is_superuser` bo'yicha "to'liq" deb yozadi.
        if obj.is_superuser or not obj.role_id or not obj.role.is_active:
            return []
        return [
            {"code": item.code, "name": item.name, "group": item.group}
            for item in obj.role.permissions.all()
        ]

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

        # O'z hisobini bloklash yoki rolini almashtirish — xodim darhol
        # tizimdan chiqib qolishi mumkin (yangi rolda panel kirishi
        # bo'lmasa). Bunday o'zgarishni boshqa administrator qiladi.
        if self.instance is not None and self.instance.pk == actor.pk:
            if attrs.get("is_active") is False:
                raise serializers.ValidationError(
                    {"is_active": "O'z hisobingizni bloklay olmaysiz"}
                )
            if "role" in attrs and attrs["role"] != self.instance.role:
                raise serializers.ValidationError(
                    {"role": "O'z rolingizni o'zgartira olmaysiz — buni boshqa administrator qiladi"}
                )

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
    #: Qaysi yuzaga kirilmoqda. Panel `panel` yuboradi; desktop client
    #: maydonni yubormaydi (eski nusxalar ham) — standart `client`.
    surface = serializers.ChoiceField(
        choices=("panel", "client"), required=False, default="client"
    )

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

        # Operator kabi client rollariga panel tokeni BERILMAYDI. Bu
        # qulaylik qatlami (aniq xabar) — haqiqiy to'siq har endpointda
        # (`HasPanelAccess`): client login'idan olingan token ham panelda
        # hech narsa ochmaydi.
        if attrs.get("surface") == "panel" and not user.has_panel_access:
            raise PanelAccessDenied()

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
