from django.contrib import admin

from apps.devices.models import Camera, Computer, DeviceToken


@admin.register(Computer)
class ComputerAdmin(admin.ModelAdmin):
    list_display = ("number", "inventory_code", "zone", "machine_uuid", "ip_address", "mac_address", "status", "last_seen_at")
    list_filter = ("status", "zone__region", "is_active")
    search_fields = ("number", "inventory_code", "machine_uuid", "ip_address", "mac_address")
    list_select_related = ("zone", "zone__region")
    filter_horizontal = ("cameras",)


@admin.register(Camera)
class CameraAdmin(admin.ModelAdmin):
    list_display = ("name", "zone", "ip_address", "status", "last_seen_at")
    list_filter = ("status", "zone__region", "is_active")
    search_fields = ("name", "ip_address", "mac_address")
    list_select_related = ("zone",)
    # Shifrlangan parol admin'da ko'rsatilmaydi.
    exclude = ("password_encrypted",)


@admin.register(DeviceToken)
class DeviceTokenAdmin(admin.ModelAdmin):
    list_display = (
        "device_id", "computer", "status", "app_version",
        "performance_profile", "gpu_name", "last_used_at",
    )
    list_filter = ("status",)
    search_fields = ("device_id", "hardware_fingerprint")
    list_select_related = ("computer",)
    readonly_fields = ("device_id", "last_used_at", "last_ip")
