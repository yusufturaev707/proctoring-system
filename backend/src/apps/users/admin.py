from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.users.models import FaceProfile, Permission, Role, User


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "group")
    list_filter = ("group",)
    search_fields = ("code", "name")


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "is_global", "is_active")
    list_filter = ("is_active", "is_global")
    filter_horizontal = ("permissions",)
    search_fields = ("name",)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "get_full_name", "role", "region", "is_active", "is_staff")
    list_filter = ("is_active", "is_staff", "is_superuser", "role", "region")
    search_fields = ("username", "first_name", "last_name", "phone")
    ordering = ("-id",)
    list_select_related = ("role", "region")

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Shaxsiy", {"fields": ("first_name", "last_name", "middle_name", "phone", "telegram_id")}),
        ("Tashkiliy", {"fields": ("role", "region", "zone")}),
        ("Ruxsatlar", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Kirish tarixi", {"fields": ("last_login_at", "last_login_ip")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("username", "password1", "password2", "role", "region")}),
    )
    readonly_fields = ("last_login_at", "last_login_ip")


@admin.register(FaceProfile)
class FaceProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "embedding_model", "is_active", "updated_at")
    list_select_related = ("user",)
    # Embedding — katta massiv, admin ro'yxatida ko'rsatilmaydi.
    exclude = ("embedding",)
