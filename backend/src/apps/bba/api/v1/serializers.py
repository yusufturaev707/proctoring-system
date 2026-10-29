from rest_framework import serializers

from apps.bba import jobs
from apps.bba.models import BbaDevice, BbaJob, BbaRegion, BbaRoom
from apps.regions.models import Region, Zone


class BbaRegionSerializer(serializers.ModelSerializer):
    """Faqat `region` (bizning viloyat) yoziladi — qolgani Console'dan."""

    region = serializers.PrimaryKeyRelatedField(
        queryset=Region.objects.all(), allow_null=True, required=False
    )
    region_name = serializers.CharField(source="region.name", read_only=True, default=None)

    class Meta:
        model = BbaRegion
        fields = (
            "id", "console_id", "name", "code", "subnet", "region", "region_name",
            "room_count", "device_count", "is_visible", "synced_at",
        )
        read_only_fields = (
            "id", "console_id", "name", "code", "subnet", "room_count", "device_count",
            "is_visible", "synced_at",
        )


class BbaRoomSerializer(serializers.ModelSerializer):
    bba_region_name = serializers.CharField(source="bba_region.name", read_only=True, default=None)

    class Meta:
        model = BbaRoom
        fields = ("id", "console_id", "name", "code", "bba_region", "bba_region_name", "device_count", "is_visible")
        read_only_fields = fields


class BbaDeviceSerializer(serializers.ModelSerializer):
    """Ro'yxat qatori — inventory JSON'siz (u faqat tafsilotda)."""

    name = serializers.CharField(read_only=True)
    room_name = serializers.CharField(source="room.name", read_only=True, default=None)
    bba_region_name = serializers.CharField(source="bba_region.name", read_only=True, default=None)
    region = serializers.IntegerField(source="bba_region.region_id", read_only=True, default=None)
    region_name = serializers.CharField(source="bba_region.region.name", read_only=True, default=None)
    computer_label = serializers.CharField(source="computer.label", read_only=True, default=None)
    computer_zone_name = serializers.CharField(source="computer.zone.name", read_only=True, default=None)

    class Meta:
        model = BbaDevice
        fields = (
            "id", "console_id", "name", "hostname_code", "hostname", "status",
            "status_changed_at", "last_seen_at", "enrolled_at", "revoked_at", "agent_version",
            "test_mode_enabled", "is_visible", "missing_since", "room", "room_name",
            "bba_region", "bba_region_name", "region", "region_name", "system_uuid", "primary_mac",
            "primary_ip", "macs",
            "computer", "computer_label", "computer_zone_name", "inventory_captured_at",
            "inventory_fetched_at",
        )
        read_only_fields = fields


class BbaDeviceDetailSerializer(BbaDeviceSerializer):
    computer_detail = serializers.SerializerMethodField()
    suggested_inventory_code = serializers.SerializerMethodField()

    class Meta(BbaDeviceSerializer.Meta):
        fields = BbaDeviceSerializer.Meta.fields + (
            "baseboard_serial", "tpm_ek_hash", "machine_guid", "inventory",
            "inventory_changes", "inventory_error", "computer_detail", "suggested_inventory_code",
        )
        read_only_fields = fields

    def get_computer_detail(self, obj):
        computer = obj.computer
        if computer is None or computer.deleted_at is not None:
            return None
        return {
            "id": computer.pk,
            "label": computer.label,
            "zone": computer.zone_id,
            "zone_name": computer.zone.name,
            "region_name": computer.zone.region.name,
            "machine_uuid": computer.machine_uuid,
            "mac_address": computer.mac_address,
            "is_active": computer.is_active,
        }

    def get_suggested_inventory_code(self, obj) -> str:
        from apps.bba.services import default_inventory_code

        if obj.computer_id or not obj.system_uuid:
            return ""
        return default_inventory_code(obj, obj.primary_mac)


class BbaJobSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source="device.name", read_only=True)
    job_label = serializers.SerializerMethodField()

    class Meta:
        model = BbaJob
        fields = (
            "id", "device", "device_name", "job_type", "job_label", "params", "status",
            "result", "error", "console_job_id", "bulk_operation_id", "issued_by_username",
            "created_at", "sent_at", "completed_at",
        )
        read_only_fields = fields

    def get_job_label(self, obj) -> str:
        spec = jobs.BY_CODE.get(obj.job_type)
        return spec.label if spec else obj.job_type


class ImportComputerSerializer(serializers.Serializer):
    zone = serializers.PrimaryKeyRelatedField(queryset=Zone.objects.alive())
    number = serializers.IntegerField(min_value=1, max_value=32767, required=False, allow_null=True)
    inventory_code = serializers.CharField(max_length=50, required=False, allow_blank=True)
    mac_address = serializers.CharField(max_length=32, required=False, allow_blank=True)
    #: Yuborilmasa — tanlangan MAC adapterining inventory'dagi IPv4 manzili;
    #: bo'sh satr — IP'siz.
    ip_address = serializers.IPAddressField(
        protocol="IPv4", required=False, allow_blank=True, allow_null=True
    )


class BulkImportSerializer(serializers.Serializer):
    zone = serializers.PrimaryKeyRelatedField(queryset=Zone.objects.alive())


class SendJobSerializer(serializers.Serializer):
    job_type = serializers.ChoiceField(choices=[item.code for item in jobs.CATALOG])
    params = serializers.JSONField(required=False, default=dict)
    confirm = serializers.BooleanField(required=False, default=False)
