from django import forms
from django.contrib import admin

from apps.common.utils.validators import normalize_mac, normalize_machine_uuid
from apps.devices import services
from apps.devices.models import Camera, Computer, DeviceToken


class ComputerAdminForm(forms.ModelForm):
    """
    Panel serializer'idagi qoidalar Django admin'da ham.

    Admin - uchinchi kirish yo'li: usiz `2c-f0-...` shaklidagi yoki
    MAC'siz yozuv shu yerdan kirib, juftlik bo'yicha qidiruvni
    (`find_computer_by_identity`) jimgina buzardi. (UUID, MAC) juftligi
    va MAC unikalligini modeldagi shartli cheklovlar
    (`validate_constraints`) tekshiradi.
    """

    class Meta:
        model = Computer
        fields = "__all__"

    def clean_machine_uuid(self):
        value = self.cleaned_data.get("machine_uuid")
        if not value:
            return None
        normalized = normalize_machine_uuid(value)
        if not normalized:
            raise forms.ValidationError("Machine UUID noto'g'ri yoki to'ldirilmagan")
        return normalized

    def clean_mac_address(self):
        value = normalize_mac(self.cleaned_data.get("mac_address"))
        if not value:
            # UUID takrorlanadi - MAC'siz yozuvni bir partiyadagi boshqa
            # mashinalardan ajratib bo'lmaydi.
            raise forms.ValidationError("MAC manzil kiritilishi shart (AA:BB:CC:DD:EE:FF)")
        return value


@admin.register(Computer)
class ComputerAdmin(admin.ModelAdmin):
    form = ComputerAdminForm
    list_display = ("number", "inventory_code", "zone", "machine_uuid", "ip_address", "mac_address", "status", "last_seen_at")
    list_filter = ("status", "zone__region", "is_active")
    search_fields = ("number", "inventory_code", "machine_uuid", "ip_address", "mac_address")
    list_select_related = ("zone", "zone__region")
    filter_horizontal = ("cameras",)

    def save_model(self, request, obj, form, change):
        # Panel bilan bir xil: juftlik o'zgarsa qurilmalar etaloni ham
        # (`services.rebaseline_fingerprints`). `form.initial` — saqlashdan
        # OLDINGI qiymatlar (`obj` ga forma allaqachon yozilgan).
        old_uuid = form.initial.get("machine_uuid") if change else ""
        old_mac = form.initial.get("mac_address") if change else ""
        super().save_model(request, obj, form, change)
        if change:
            services.rebaseline_fingerprints(obj, old_uuid=old_uuid or "", old_mac=old_mac or "")


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
