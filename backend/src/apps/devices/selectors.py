from django.db.models import Count, Q
from django.utils import timezone

from apps.devices.models import Camera, Computer, DeviceToken


def computers_base(*, include_deleted: bool = False):
    """
    Kompyuterlar. Standart holda faqat TIRIKLARI.

    `include_deleted=True` — "Savat" ko'rinishi uchun (viewset o'zi
    `deleted_at` bo'yicha filtrlaydi, `SoftDeleteRestoreMixin` ga
    qarang). Boshqa chaqiruvchilar (masalan kameralar `Prefetch` i)
    standart xulqda qoladi.
    """
    queryset = Computer.objects.select_related("zone", "zone__region")
    return queryset if include_deleted else queryset.filter(deleted_at__isnull=True)


def cameras_base(*, include_deleted: bool = False):
    queryset = Camera.objects.select_related("zone", "zone__region")
    return queryset if include_deleted else queryset.filter(deleted_at__isnull=True)


def device_tokens_base():
    return DeviceToken.objects.select_related("computer", "computer__zone")


def stale_computers(timeout_seconds: int = 120):
    """
    Heartbeat kelmay qolgan kompyuterlar.

    `idx_computer_heartbeat` indeksi aynan shu so'rov uchun.
    """
    threshold = timezone.now() - timezone.timedelta(seconds=timeout_seconds)
    return Computer.objects.filter(
        status__in=[Computer.Status.ONLINE, Computer.Status.IN_EXAM],
        last_seen_at__lt=threshold,
    )


def zone_device_summary(*, region_id=None) -> list[dict]:
    """Bino bo'yicha uskuna holati."""
    from apps.regions.models import Zone

    queryset = Zone.objects.filter(deleted_at__isnull=True, is_active=True)
    if region_id:
        queryset = queryset.filter(region_id=region_id)

    alive = Q(computers__deleted_at__isnull=True)
    return list(
        queryset.annotate(
            computers_total=Count("computers", filter=alive, distinct=True),
            computers_online=Count(
                "computers",
                filter=alive & Q(computers__status__in=["online", "in_exam"]),
                distinct=True,
            ),
            cameras_total=Count(
                "cameras", filter=Q(cameras__deleted_at__isnull=True), distinct=True
            ),
            cameras_online=Count(
                "cameras",
                filter=Q(cameras__deleted_at__isnull=True, cameras__status="online"),
                distinct=True,
            ),
        )
        .values(
            "id", "name", "number", "region__name",
            "computers_total", "computers_online", "cameras_total", "cameras_online",
        )
        .order_by("region__name", "number")
    )
