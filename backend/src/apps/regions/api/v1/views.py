from django.db.models import Count, Q
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.common.mixins import AuditLogMixin, PermissionRequiredMixin, SoftDeleteRestoreMixin
from apps.common.permissions import HasRolePermission
from apps.regions.api.v1.serializers import RegionSerializer, ZoneSerializer
from apps.regions.models import Region, Zone


class RegionViewSet(PermissionRequiredMixin, AuditLogMixin, viewsets.ModelViewSet):
    queryset = Region.objects.annotate(
        zones_count=Count("zones", filter=Q(zones__deleted_at__isnull=True), distinct=True)
    ).order_by("name")  # annotate() Meta.ordering ni bekor qiladi
    serializer_class = RegionSerializer
    permission_classes = [IsAuthenticated, HasRolePermission]
    required_permission = "regions.manage"
    required_read_permission = "regions.view"
    audit_object_type = "Region"
    filterset_fields = ["is_active"]
    search_fields = ["name"]
    ordering_fields = ["name", "dtm_id", "vm_number"]

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if user.is_region_scoped:
            queryset = queryset.filter(pk=user.region_id)
        return queryset


class ZoneViewSet(
    PermissionRequiredMixin, AuditLogMixin, SoftDeleteRestoreMixin, viewsets.ModelViewSet
):
    queryset = (
        Zone.objects
        .select_related("region")
        .annotate(
            computers_count=Count(
                "computers", filter=Q(computers__deleted_at__isnull=True), distinct=True
            ),
            cameras_count=Count(
                "cameras", filter=Q(cameras__deleted_at__isnull=True), distinct=True
            ),
        )
        .order_by("region__name", "number")  # annotate() Meta.ordering ni bekor qiladi
    )
    serializer_class = ZoneSerializer
    permission_classes = [IsAuthenticated, HasRolePermission]
    required_permission = "regions.manage"
    required_read_permission = "regions.view"
    audit_object_type = "Zone"
    filterset_fields = ["region", "is_active", "is_part"]
    search_fields = ["name", "address"]
    ordering_fields = ["number", "name"]

    def get_queryset(self):
        queryset = self.apply_deleted_filter(super().get_queryset())
        user = self.request.user
        if user.is_region_scoped:
            queryset = queryset.filter(region_id=user.region_id)
        return queryset
