import logging

from celery import shared_task
from django.utils import timezone

from apps.devices.models import Computer
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
