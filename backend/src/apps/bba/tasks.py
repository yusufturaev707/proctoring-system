from celery import shared_task
from django.conf import settings
from django.core.cache import cache

from apps.bba import services
from apps.bba.client import is_configured

POLL_LOCK_KEY = "bba:lock:poll"
INVENTORY_LOCK_KEY = "bba:lock:inventory"


@shared_task(name="bba.poll", ignore_result=True)
def poll():
    """
    Console holati (har `BBA_STATUS_POLL_SECONDS`, `config/celery.py`).

    Qulf — oldingi yurish (sekin Console) tugamay turib keyingisi
    boshlanmasin: ikkalasi bir xil qatorlarni yozib, holat o'zgarishini
    panelga ikki marta yuborardi. Qulf o'z muddati bilan ham tushadi
    (ishchi o'lsa).
    """
    if not is_configured():
        return
    interval = settings.BBA_CONSOLE["STATUS_POLL_SECONDS"]
    if not cache.add(POLL_LOCK_KEY, 1, timeout=max(60, interval * 4)):
        return
    try:
        result = services.poll()
    finally:
        cache.delete(POLL_LOCK_KEY)
    # Yangi kompyuterning UUID/MAC'i — darhol, 5 daqiqalik yurishni kutmay.
    if result.get("created"):
        sync_inventories.apply_async(queue="maintenance", expires=600)


@shared_task(name="bba.sync_inventories", ignore_result=True)
def sync_inventories():
    """Eskirgan inventory'lar (`services.sync_inventories`, vaqt byudjeti bilan)."""
    if not is_configured():
        return
    if not cache.add(INVENTORY_LOCK_KEY, 1, timeout=services.INVENTORY_TIME_BUDGET_S * 3):
        return
    try:
        services.sync_inventories()
    finally:
        cache.delete(INVENTORY_LOCK_KEY)
