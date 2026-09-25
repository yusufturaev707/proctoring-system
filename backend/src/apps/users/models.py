"""
Xodimlar (admin / proktor / monitoring). Talabgorlar bu yerda EMAS —
ular `proctoring.Candidate` da, chunki ular tizim foydalanuvchisi emas.
"""

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import TimeStampedModel
from apps.users.user_manager import UserManager


class Permission(TimeStampedModel):
    """
    Ilova darajasidagi ruxsat (`sessions.terminate` kabi).

    Django'ning `auth.Permission` i model-CRUD ga bog'langan; bizga esa
    "sessiyani tugatish", "chetlashtirishni tasdiqlash" kabi biznes
    amallari kerak.
    """

    code = models.CharField(_("Kod"), max_length=100, unique=True)
    name = models.CharField(_("Nom"), max_length=255)
    group = models.CharField(_("Guruh"), max_length=100, db_index=True, default="general")

    def __str__(self):
        return f"{self.code}"

    class Meta:
        verbose_name = _("Ruxsat")
        verbose_name_plural = _("Ruxsatlar")
        db_table = "permission_code"
        ordering = ["group", "code"]


class Role(TimeStampedModel):
    """Rol — ruxsatlar to'plami."""

    name = models.CharField(_("Nom"), max_length=255, unique=True)
    key = models.IntegerField(_("Kalit"), unique=True)
    description = models.CharField(_("Izoh"), max_length=500, blank=True, default="")
    permissions = models.ManyToManyField(
        "users.Permission", related_name="roles", blank=True
    )
    # Hudud filtridan ozod rol.
    #
    # Standart holatda xodim faqat o'z viloyati ma'lumotini ko'radi
    # (`User.is_region_scoped`). Ba'zi rollar esa mohiyatan respublika
    # darajasida ishlaydi - masalan Administrator: u barcha viloyatlarni
    # boshqaradi va unga viloyat biriktirish shart emas.
    #
    # Bu ilgari `is_superuser` bayrog'i orqali hal qilinardi, ya'ni
    # respublika darajasidagi ish uchun Django superuser'i talab
    # qilinardi. Endi qaror ROLDA: superuser faqat favqulodda zaxira
    # yo'l bo'lib qoladi.
    is_global = models.BooleanField(
        _("Butun respublika bo'yicha"),
        default=False,
        help_text=_("Yoqilsa - bu roldagi xodim barcha viloyatlarni ko'radi"),
    )
    is_active = models.BooleanField(_("Faol"), default=True, db_index=True)

    def __str__(self):
        return str(self.name)

    class Meta:
        verbose_name = _("Rol")
        verbose_name_plural = _("Rollar")
        db_table = "roles"
        ordering = ["key"]


class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    username = models.CharField(_("Login"), max_length=255, unique=True)
    first_name = models.CharField(_("Ism"), max_length=255, blank=True, default="")
    last_name = models.CharField(_("Familiya"), max_length=255, blank=True, default="")
    middle_name = models.CharField(_("Otasining ismi"), max_length=255, blank=True, default="")
    phone = models.CharField(_("Telefon"), max_length=20, blank=True, default="")
    telegram_id = models.CharField(max_length=32, blank=True, null=True, unique=True)

    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, db_index=True)

    region = models.ForeignKey(
        "regions.Region",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="users",
        help_text=_(
            "Viloyat darajasidagi rol uchun MAJBURIY — bo'sh bo'lsa xodim "
            "admin panelda hech narsa ko'rmaydi. Butun respublika: rolda"
        ),
    )
    zone = models.ForeignKey(
        "regions.Zone",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="users",
    )
    role = models.ForeignKey(
        "users.Role", on_delete=models.PROTECT, blank=True, null=True, related_name="users"
    )

    last_login_at = models.DateTimeField(blank=True, null=True)
    last_login_ip = models.GenericIPAddressField(blank=True, null=True)

    objects = UserManager()
    USERNAME_FIELD = "username"
    REQUIRED_FIELDS: list[str] = []

    def __str__(self):
        return str(self.username)

    def get_full_name(self) -> str:
        parts = [self.last_name, self.first_name, self.middle_name]
        full = " ".join(part for part in parts if part).strip()
        return full or self.username

    def get_short_name(self) -> str:
        return self.first_name or self.username

    @property
    def role_name(self) -> str:
        return self.role.name if self.role else ""

    @property
    def role_key(self) -> int:
        return self.role.key if self.role else 0

    @property
    def region_name(self) -> str:
        return self.region.name if self.region else ""

    def permission_codes(self) -> list[str]:
        """
        Rol ruxsatlari. Instansiya darajasida keshlanadi — har bir permission
        tekshiruvida M2M so'rovi ketmasligi uchun.
        """
        cached = getattr(self, "_permission_codes_cache", None)
        if cached is not None:
            return cached

        if self.is_superuser:
            codes = ["*"]
        elif self.role_id and self.role.is_active:
            codes = sorted(self.role.permissions.values_list("code", flat=True))
        else:
            codes = []

        self._permission_codes_cache = codes
        return codes

    @property
    def is_region_scoped(self) -> bool:
        """
        Hudud filtri qo'llanadimi.

        Ilgari bu shart o'nta `get_queryset()` da qo'lda takrorlanardi
        (`not user.is_superuser and user.region_id`). Qoida o'zgarganda
        (masalan `Role.is_global` qo'shilganda) ularning birortasini
        unutish - jimgina ma'lumot oshkor bo'lishi demak. Shuning uchun
        qoida BITTA joyda.
        """
        if self.is_superuser:
            return False
        if self.role_id and self.role.is_active and self.role.is_global:
            return False
        # Viloyat biriktirilmagan xodim bu yerda `False` beradi, lekin u
        # hamma narsani KO'RMAYDI: admin yuzasida uni `lacks_region`
        # to'xtatadi (`common.permissions.HasRegionAssignment`). Qoida
        # shu yerda "bo'sh viloyat = cheklov yo'q" bo'lib qolgani
        # ataylab — o'nlab `filter(region_id=user.region_id)` None bilan
        # ishlasa `NULL` qatorlarni (bino biriktirilmagan sessiya,
        # viloyatsiz xodim) OCHIB qo'yardi.
        return self.region_id is not None

    @property
    def lacks_region(self) -> bool:
        """
        Viloyat darajasidagi rol, lekin viloyat biriktirilmagan.

        Ilgari bunday xodim BARCHA viloyatlarni ko'rardi (tarixiy xulq):
        yangi hisob yaratib viloyatni tanlashni unutish yoki viloyatni
        o'chirish jimgina butun respublika ma'lumotini ochib qo'yardi.
        Endi xato YOPIQ tomonga: admin panelda bunday xodim hech narsa
        ko'rmaydi va ekranda sababi aytiladi. Butun respublikani ko'rish
        — ochiq qaror, u rolda (`Role.is_global`).
        """
        if self.is_superuser:
            return False
        if self.role_id and self.role.is_active and self.role.is_global:
            return False
        return self.region_id is None

    def has_role_permission(self, code: str) -> bool:
        if self.is_superuser:
            return True
        codes = self.permission_codes()
        if "*" in codes or code in codes:
            return True
        # `sessions.*` kabi wildcard qo'llab-quvvatlanadi.
        prefix = code.split(".")[0]
        return f"{prefix}.*" in codes

    class Meta:
        verbose_name = _("Foydalanuvchi")
        verbose_name_plural = _("Foydalanuvchilar")
        db_table = "users"
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["region", "is_active"], name="idx_user_region_active"),
            models.Index(fields=["role"], name="idx_user_role"),
        ]


class FaceProfile(TimeStampedModel):
    """
    Xodimning yuz ma'lumotlari — ATAYLAB `User` dan ajratilgan.

    Sabab: embedding + rasm ~250 KB. Agar ular `users` jadvalida bo'lsa,
    HAR BIR autentifikatsiya so'rovi (`SELECT ... FROM users WHERE id=...`)
    shu og'irlikni tortadi. Ajratilgan jadvalda faqat kerak bo'lganda o'qiladi.
    """

    user = models.OneToOneField(
        "users.User", on_delete=models.CASCADE, related_name="face_profile"
    )
    # Rasm DB'da emas — object storage'da.
    photo_key = models.CharField(max_length=500, blank=True, default="")
    # Normalizatsiya qilingan vektor. Postgres native massiv.
    embedding = ArrayField(models.FloatField(), size=None, blank=True, null=True)
    embedding_model = models.CharField(max_length=100, blank=True, default="")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"FaceProfile<{self.user_id}>"

    class Meta:
        verbose_name = _("Yuz profili")
        verbose_name_plural = _("Yuz profillari")
        db_table = "user_face_profile"
