"""
BBA Console — panel yuzasi (`/api/v1/bba/...`).

Ro'yxatlar MAHALLIY nusxadan (`models.py`), Console'ga faqat amallar
(job, wake, inventory'ni yangilash) va tafsilot sahifasidagi tarixlar boradi.

Ruxsatlar: `bba.view` — ko'rish; `bba.manage` — kompyuterni ro'yxatga
qo'shish, viloyatga bog'lash, qo'lda sinxronizatsiya; `bba.jobs` — job va
Wake-on-LAN (kompyuterni o'chirish/skript — ko'rishdan ALOHIDA huquq).
Viloyat chegarasi — `services.visible_devices` (Console hududi bizning
viloyatga bog'langan bo'lsa).
"""

from django.core.cache import cache
from django.db.models import Count
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.bba import jobs, services, tasks
from apps.bba.api.v1.serializers import (
    BbaDeviceDetailSerializer,
    BbaDeviceSerializer,
    BbaJobSerializer,
    BbaRegionSerializer,
    BbaRoomSerializer,
    BulkImportSerializer,
    ImportComputerSerializer,
    SendJobSerializer,
)
from apps.bba.client import is_configured
from apps.bba.identity import canonical_mac
from apps.bba.models import BbaDevice, BbaJob, BbaRegion, BbaRoom
from apps.common.mixins import AuditLogMixin, BulkSelectionMixin, PermissionRequiredMixin


def _truthy(value) -> bool | None:
    if value in (None, ""):
        return None
    return str(value).lower() in {"1", "true", "yes"}


class BbaOverviewView(PermissionRequiredMixin, APIView):
    permission_classes = [IsAuthenticated]
    required_permission = "bba.view"

    def get(self, request):
        return Response(services.overview(request.user))


class BbaJobTypesView(PermissionRequiredMixin, APIView):
    permission_classes = [IsAuthenticated]
    required_permission = "bba.view"

    def get(self, request):
        return Response({"types": jobs.catalog(), "lock_features": list(jobs.LOCK_FEATURES)})


class BbaSyncView(PermissionRequiredMixin, APIView):
    """
    Qo'lda sinxronizatsiya — davriy yurish bilan bitta qulf
    (`tasks.POLL_LOCK_KEY`): ikkalasi bir vaqtda bir xil qatorlarni yozmasin.
    """

    permission_classes = [IsAuthenticated]
    required_permission = "bba.manage"

    def post(self, request):
        if not is_configured():
            raise services.as_domain_error(services.BbaNotConfigured())
        if not cache.add(tasks.POLL_LOCK_KEY, 1, timeout=120):
            raise services.BbaIntegrationError(
                "Sinxronizatsiya hozir ketmoqda — biroz kuting", code="bba_sync_busy"
            )
        try:
            cache.delete(services.TREE_SYNCED_KEY)
            result = services.poll()
        finally:
            cache.delete(tasks.POLL_LOCK_KEY)
        if result.get("error"):
            raise services.BbaIntegrationError(result["error"], code="bba_sync_failed")
        tasks.sync_inventories.apply_async(queue="maintenance", expires=600)
        return Response(result)


class BbaRegionViewSet(
    PermissionRequiredMixin, AuditLogMixin, mixins.ListModelMixin, mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Console hududlari va ularning bizning viloyatga bog'lanishi (respublika)."""

    serializer_class = BbaRegionSerializer
    permission_classes = [IsAuthenticated]
    required_permission = "bba.manage"
    required_read_permission = "bba.view"
    republic_write_only = True
    audit_object_type = "BbaRegion"
    filterset_fields = ["is_visible", "region"]
    search_fields = ["name", "code"]
    ordering_fields = ["name", "device_count"]
    pagination_class = None
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        queryset = BbaRegion.objects.select_related("region")
        user = self.request.user
        if user.is_region_scoped:
            queryset = queryset.filter(region_id=user.region_id)
        return queryset

    def perform_update(self, serializer):
        old_region = serializer.instance.region_id
        instance = serializer.save()
        self.log_audit("update", instance, {"region": [old_region, instance.region_id]})
        return instance


class BbaRoomViewSet(PermissionRequiredMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = BbaRoomSerializer
    permission_classes = [IsAuthenticated]
    required_permission = "bba.view"
    filterset_fields = ["bba_region", "is_visible"]
    search_fields = ["name", "code"]
    ordering_fields = ["name", "device_count"]
    pagination_class = None

    def get_queryset(self):
        queryset = BbaRoom.objects.select_related("bba_region")
        user = self.request.user
        if user.is_region_scoped:
            queryset = queryset.filter(bba_region__region_id=user.region_id)
        return queryset


class BbaDeviceViewSet(PermissionRequiredMixin, BulkSelectionMixin, viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    required_permission = "bba.view"
    action_permissions = {
        "import_computer": "bba.manage",
        "bulk_import": "bba.manage",
        "send_job": "bba.jobs",
        "bulk_send_job": "bba.jobs",
        "wake": "bba.jobs",
        "bulk_wake": "bba.jobs",
    }
    bulk_max_ids = jobs.MAX_BULK_DEVICES
    filterset_fields = ["status", "bba_region", "room", "is_visible"]
    search_fields = ["hostname_code", "hostname", "system_uuid", "primary_mac"]
    ordering_fields = [
        "hostname_code", "hostname", "status", "last_seen_at", "status_changed_at",
        "agent_version", "inventory_fetched_at",
    ]
    ordering = ["hostname_code", "hostname"]

    def get_serializer_class(self):
        return BbaDeviceDetailSerializer if self.action == "retrieve" else BbaDeviceSerializer

    def get_queryset(self):
        queryset = services.visible_devices(self.request.user).select_related(
            "room", "bba_region", "bba_region__region", "computer", "computer__zone", "computer__zone__region"
        )
        if self.action != "retrieve":
            queryset = queryset.defer("inventory", "inventory_changes")
        params = self.request.query_params
        # «Ro'yxatda» — bog'langan kompyuter TIRIK (hisobdan chiqarilgani
        # bog'lanmagan hisoblanadi: uni qayta qo'shish mumkin).
        linked = _truthy(params.get("linked"))
        alive_link = {"computer__isnull": False, "computer__deleted_at__isnull": True}
        if linked is True:
            queryset = queryset.filter(**alive_link)
        elif linked is False:
            queryset = queryset.exclude(**alive_link)
        revoked = _truthy(params.get("revoked"))
        if revoked is not None:
            queryset = queryset.filter(revoked_at__isnull=not revoked)
        mac = canonical_mac(params.get("mac"))
        if params.get("mac"):
            queryset = queryset.filter(macs__contains=[mac]) if mac else queryset.none()
        return queryset

    def _require_devices_manage(self):
        user = self.request.user
        if not (user.is_superuser or user.has_role_permission("devices.manage")):
            raise PermissionDenied("Kompyuter qo'shish uchun «Qurilmalarni boshqarish» ruxsati kerak")

    def _selection(self) -> list:
        return list(self.bulk_queryset().defer("inventory", "inventory_changes"))

    # --- Viloyat -> xona ko'rinishi ---
    #: `by-room` javobi chegarasi (bitta viloyat; xonalar xaritasi sahifalanmaydi).
    BY_ROOM_LIMIT = 3000

    def _grouping_queryset(self):
        """Viloyat chegarasi + `linked`/`revoked`; `is_visible` standarti — ko'rinadiganlar."""
        queryset = self.get_queryset()
        visible = _truthy(self.request.query_params.get("is_visible", "true"))
        if visible is not None:
            queryset = queryset.filter(is_visible=visible)
        return queryset

    @action(detail=False, methods=["get"])
    def tree(self, request):
        """
        Viloyat (Console hududi) -> xona daraxti, har tugunda holatlar soni.

        Bitta GROUP BY: 10 000 kompyuterni brauzerga olib kelib sanash
        o'rniga. Xonasiz kompyuterlar — `room: null` tugunida, hududsizlar —
        `id: null` viloyatida (yashirilmaydi: ular ham "qayerda?" savoli).
        """
        counts = (
            self._grouping_queryset().order_by()
            .values("bba_region", "room", "status").annotate(n=Count("id"))
        )
        regions = {item.pk: item for item in BbaRegion.objects.select_related("region")}
        rooms = {item.pk: item for item in BbaRoom.objects.all()}
        empty = {value: 0 for value in BbaDevice.Status.values}
        tree: dict = {}
        for row in counts:
            region_id, room_id = row["bba_region"], row["room"]
            region = regions.get(region_id)
            node = tree.setdefault(region_id, {
                "id": region_id,
                "name": region.name if region else "Hududsiz",
                "region_name": region.region.name if region and region.region else None,
                "total": 0, "by_status": dict(empty), "rooms": {},
            })
            room = rooms.get(room_id)
            leaf = node["rooms"].setdefault(room_id, {
                "id": room_id,
                "name": room.name if room else "Xonaga biriktirilmagan",
                "total": 0, "by_status": dict(empty),
            })
            for target in (node, leaf):
                target["total"] += row["n"]
                target["by_status"][row["status"]] += row["n"]
        result = []
        for node in sorted(tree.values(), key=lambda item: (item["id"] is None, item["name"])):
            node["rooms"] = sorted(node["rooms"].values(), key=lambda item: (item["id"] is None, item["name"]))
            result.append(node)
        return Response({"regions": result})

    @action(detail=False, methods=["get"], url_path="by-room")
    def by_room(self, request):
        """
        Bitta viloyat (`?bba_region=<id>` yoki `none` — hududsizlar)
        kompyuterlari, sahifasiz. Javob `results` kalitida — panelning
        jonli yangilanishi (`useBbaLive`) uni ro'yxat kabi to'g'rilaydi.
        """
        raw = request.query_params.get("bba_region")
        if not raw:
            raise serializers.ValidationError({"bba_region": "Viloyat tanlanmagan"})
        queryset = self._grouping_queryset().defer("inventory", "inventory_changes")
        if raw == "none":
            queryset = queryset.filter(bba_region__isnull=True)
        else:
            try:
                queryset = queryset.filter(bba_region_id=int(raw))
            except ValueError:
                raise serializers.ValidationError({"bba_region": "Noto'g'ri qiymat"})
        rows = list(queryset.order_by("room__name", "hostname_code", "hostname")[: self.BY_ROOM_LIMIT + 1])
        return Response({
            "results": BbaDeviceSerializer(rows[: self.BY_ROOM_LIMIT], many=True).data,
            "truncated": len(rows) > self.BY_ROOM_LIMIT,
        })

    # --- Console'dan tafsilot ---
    @action(detail=True, methods=["post"], url_path="refresh-inventory")
    def refresh_inventory(self, request, pk=None):
        device = services.refresh_inventory(self.get_object())
        return Response(BbaDeviceDetailSerializer(device, context={"request": request}).data)

    @action(detail=True, methods=["get"])
    def connectivity(self, request, pk=None):
        return Response({"events": services.connectivity(self.get_object())})

    @action(detail=True, methods=["get"], url_path="job-history")
    def job_history(self, request, pk=None):
        return Response({"jobs": services.device_job_history(self.get_object())})

    # --- Bizning ro'yxatga qo'shish ---
    @action(detail=True, methods=["post"], url_path="import")
    def import_computer(self, request, pk=None):
        self._require_devices_manage()
        payload = ImportComputerSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        computer = services.import_computer(
            self.get_object(), zone_id=data["zone"].pk, request=request,
            number=data.get("number"), inventory_code=data.get("inventory_code", ""),
            mac_address=data.get("mac_address", ""),
        )
        return Response({"computer": computer.pk, "label": computer.label}, status=201)

    @action(detail=False, methods=["post"], url_path="bulk-import")
    def bulk_import(self, request):
        self._require_devices_manage()
        payload = BulkImportSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        results = services.bulk_import(
            self._selection(), zone_id=payload.validated_data["zone"].pk, request=request
        )
        return Response({
            "results": results,
            "created": sum(1 for row in results if row["status"] == "created"),
            "skipped": sum(1 for row in results if row["status"] == "skipped"),
            "failed": sum(1 for row in results if row["status"] == "error"),
        })

    # --- Job va Wake-on-LAN ---
    def _job_payload(self):
        payload = SendJobSerializer(data=self.request.data)
        payload.is_valid(raise_exception=True)
        return payload.validated_data

    @action(detail=True, methods=["post"], url_path="send-job")
    def send_job(self, request, pk=None):
        data = self._job_payload()
        created = services.dispatch_job(
            [self.get_object()], job_type=data["job_type"], params=data["params"],
            confirm=data["confirm"], request=request,
        )
        return Response({"jobs": BbaJobSerializer(created, many=True).data}, status=201)

    @action(detail=False, methods=["post"], url_path="bulk-send-job")
    def bulk_send_job(self, request):
        data = self._job_payload()
        created = services.dispatch_job(
            self._selection(), job_type=data["job_type"], params=data["params"],
            confirm=data["confirm"], request=request,
        )
        return Response({
            "jobs": BbaJobSerializer(created, many=True).data,
            "sent": sum(1 for job in created if job.status != BbaJob.Status.ERROR),
            "failed": sum(1 for job in created if job.status == BbaJob.Status.ERROR),
        }, status=201)

    @action(detail=True, methods=["post"])
    def wake(self, request, pk=None):
        return Response({"results": services.wake([self.get_object()], request=request)})

    @action(detail=False, methods=["post"], url_path="bulk-wake")
    def bulk_wake(self, request):
        return Response({"results": services.wake(self._selection(), request=request)})


class BbaJobViewSet(PermissionRequiredMixin, viewsets.ReadOnlyModelViewSet):
    """Panelimizdan yuborilgan job'lar (kim yuborgani bilan)."""

    serializer_class = BbaJobSerializer
    permission_classes = [IsAuthenticated]
    required_permission = "bba.view"
    action_permissions = {"cancel": "bba.jobs", "resend": "bba.jobs"}
    filterset_fields = ["device", "status", "job_type"]
    search_fields = ["device__hostname_code", "device__hostname", "issued_by_username"]
    ordering_fields = ["created_at", "status", "job_type"]
    ordering = ["-created_at", "-id"]

    def get_queryset(self):
        queryset = BbaJob.objects.select_related("device")
        user = self.request.user
        if user.is_region_scoped:
            queryset = queryset.filter(device__bba_region__region_id=user.region_id)
        return queryset

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        job = self.get_object()
        if job.status not in (BbaJob.Status.PENDING, BbaJob.Status.SENT):
            raise serializers.ValidationError({"detail": "Faqat navbatdagi yoki yuborilgan job bekor qilinadi"})
        return Response(BbaJobSerializer(services.cancel_job(job, request=request)).data)

    @action(detail=True, methods=["post"])
    def resend(self, request, pk=None):
        job = self.get_object()
        if job.status not in ("sent", "failed", "timeout", "cancelled"):
            raise serializers.ValidationError({"detail": "Bu holatdagi job qayta yuborilmaydi"})
        return Response(BbaJobSerializer(services.resend_job(job, request=request)).data)
