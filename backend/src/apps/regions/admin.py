from django.contrib import admin

from apps.regions.models import Region, Zone


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ("name", "dtm_id", "vm_number", "is_active")
    list_filter = ("is_active", "is_have_part")
    search_fields = ("name",)


@admin.register(Zone)
class ZoneAdmin(admin.ModelAdmin):
    list_display = ("name", "number", "region", "capacity", "is_active")
    list_filter = ("region", "is_active", "is_part")
    search_fields = ("name", "address")
    list_select_related = ("region",)
