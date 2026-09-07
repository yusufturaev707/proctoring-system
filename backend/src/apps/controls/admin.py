from django.contrib import admin

from apps.controls.models import (
    AllowedPublicIp,
    CocoObject,
    CocoObjectGroup,
    HotKeyboardKey,
    ModelVersion,
    RdpObject,
    Setting,
)


@admin.register(Setting)
class SettingAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "faceid_interval", "screenshot_interval")
    list_filter = ("is_active",)
    filter_horizontal = ("detect_classes", "rdp_objects", "hotkeys")


@admin.register(AllowedPublicIp)
class AllowedPublicIpAdmin(admin.ModelAdmin):
    list_display = ("ip_address", "zone", "name", "is_active")
    list_filter = ("is_active", "zone")
    search_fields = ("ip_address", "name")
