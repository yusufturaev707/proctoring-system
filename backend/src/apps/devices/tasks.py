import logging

from celery import shared_task
from django.utils import timezone

from apps.devices.models import Camera, Computer
from apps.devices.selectors import stale_computers

logger = logging.getLogger(__name__)


@shared_task(name="devices.refresh_device_status")
def refresh_device_status(timeout_seconds: int = 120):
    """
    Heartbeat kelmay qolgan kompyuterlarni offline deb belgilaydi.

    Bitta `UPDATE ... WHERE` — Python siklida `save()` chaqirish
    o'rniga. 10 000 qatorda bu farq 10 000 so'rov va 1 so'rov.
    """
    updated = stale_computers(timeout_seconds).update(
        status=Computer.Status.OFFLINE, updated_at=timezone.now()
    )
    if updated:
        logger.info("%s ta kompyuter offline deb belgilandi", updated)
    return {"offline": updated}


@shared_task(name="devices.probe_cameras")
def probe_cameras():
    """
    Barcha faol IP kameralarning holati (online / offline / xatolik).

    Ilgari `Camera.status` HECH QAYERDA yangilanmasdi va panelda har
    doim standart qiymat - "Offline" - turardi, ya'ni ishlab turgan
    kamera ham "o'chiq" bo'lib ko'rinardi. Endi har daqiqada haqiqiy
    RTSP so'rovi bilan tekshiriladi (`camera_probe.py`).

    `CAMERA_PROBE_ENABLED=false` - server kameralar tarmog'iga yetib
    bormaydigan o'rnatish uchun (markazlashgan server, NAT): u holda
    hamma kamera "offline" ko'rinib, yolg'on xabar berardi.
    """
    from django.conf import settings

    from apps.devices import services

    if not getattr(settings, "CAMERA_PROBE_ENABLED", True):
        return {"skipped": True}
    cameras = Camera.objects.alive().filter(is_active=True).only(
        "pk", "ip_address", "port", "rtsp_path", "login", "password_encrypted"
    )
    counts = services.check_cameras(cameras)
    logger.info("Kamera tekshiruvi: %s", counts)
    return counts
