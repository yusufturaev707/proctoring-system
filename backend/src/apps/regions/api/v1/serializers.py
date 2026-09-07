from rest_framework import serializers

from apps.regions.models import Region, Zone


class RegionSerializer(serializers.ModelSerializer):
    zones_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Region
        fields = (
            "id", "name", "dtm_id", "vm_number",
            "is_have_part", "is_active", "zones_count", "created_at",
        )
        read_only_fields = ("id", "created_at")


class ZoneSerializer(serializers.ModelSerializer):
    region_name = serializers.CharField(source="region.name", read_only=True)
    computers_count = serializers.IntegerField(read_only=True)
    cameras_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Zone
        fields = (
            "id", "region", "region_name", "name", "number", "address",
            "capacity", "is_active", "is_part",
            "computers_count", "cameras_count", "created_at", "deleted_at",
        )
        read_only_fields = ("id", "created_at", "deleted_at")
