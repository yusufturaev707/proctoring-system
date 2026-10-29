"""
BBA Console bilan sinxronizatsiya va amallar.

Uch xil chastota (Console limiti 300 so'rov/daqiqa, `bba_agent_api.md` §6-7):

| Nima | Qachon | So'rov |
|---|---|---|
| holat (`/devices`) | `STATUS_POLL_SECONDS` (15 s) | 500 kompyuterga 1 |
| hudud/xona daraxti | `TREE_SYNC_SECONDS` (5 daq) | 2 |
| inventory | 6 soatdan eski + yangi kompyuter | kompyuterga 1, pauza bilan |

Holat o'zgarishi panelga WebSocket bilan boriladi (`broadcast`, `ws/bba/`):
Console'da push yo'q, shuning uchun "real vaqt" = so'rov oralig'i.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, F, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers, status

from apps.bba import identity, jobs
from apps.bba.client import (
    BbaAuthError,
    BbaError,
    BbaForbidden,
    BbaNotConfigured,
    BbaNotFound,
    BbaRateLimited,
    BbaUnavailable,
    get_client,
    is_configured,
    login_block_reason,
)
from apps.bba.models import BbaDevice, BbaJob, BbaRegion, BbaRoom
from apps.common.exceptions import DomainError

logger = logging.getLogger(__name__)

STATE_KEY = "bba:state"
TREE_SYNCED_KEY = "bba:tree_synced_at"
#: Jo'natilgan, lekin yakunlanmagan job shu muddatdan keyin kuzatilmaydi.
JOB_TRACK_HOURS = 24
#: Bitta so'rovda holati yangilanadigan job'lar sahifasi.
JOB_REFRESH_PAGE = 200
#: Umumiy sahifada topilmagan job'lar uchun qurilma bo'yicha so'rovlar chegarasi.
JOB_REFRESH_DEVICE_LIMIT = 5
#: Inventory yurishining vaqt byudjeti: `maintenance` navbatining ikki
#: ishchisidan birini uzoq band qilmasin (yurish 5 daqiqada bir).
INVENTORY_TIME_BUDGET_S = 120
BROADCAST_CHUNK = 500

#: Holat so'rovida yangilanadigan maydonlar. Inventory (katta JSON) bu
#: yerda YO'Q — har 15 s da 10 000 ta snapshot'ni o'qish behuda.
_SYNC_FIELDS = (
    "room", "bba_region", "hostname_code", "hostname", "status", "status_changed_at",
    "last_seen_at", "enrolled_at", "revoked_at", "agent_version", "test_mode_enabled",
    "is_visible", "missing_since",
)


class BbaIntegrationError(DomainError):
    """Console xatosi panel javobida — matn administrator uchun."""

    status_code = status.HTTP_502_BAD_GATEWAY
    default_code = "bba_error"


class BbaAlreadyLinked(DomainError):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Bu kompyuter allaqachon ro'yxatda"
    default_code = "bba_already_linked"


def as_domain_error(exc: BbaError) -> DomainError:
    """Console xatosini HTTP javobiga: 403 — ruxsat, 429/503 — kuting, qolgani 502."""
    error = BbaIntegrationError(str(exc), code=exc.code)
    if isinstance(exc, BbaForbidden):
        error.status_code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, BbaNotFound):
        error.status_code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, (BbaRateLimited, BbaNotConfigured, BbaUnavailable, BbaAuthError)):
        error.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif exc.status in (400, 409, 422):
        error.status_code = status.HTTP_400_BAD_REQUEST
    return error


# --------------------------------------------------------------------------
# Yordamchilar
# --------------------------------------------------------------------------
def _dt(value):
    return parse_datetime(value) if isinstance(value, str) and value else None


def _uuid(value) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError):
        return ""


def _int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _status(value) -> str:
    return value if value in BbaDevice.Status.values else BbaDevice.Status.UNKNOWN


def _job_status(value) -> str:
    return value if value in BbaJob.Status.values else BbaJob.Status.SENT


def _first(data: dict, *keys, default=None):
    for key in keys:
        if isinstance(data, dict) and data.get(key) not in (None, ""):
            return data[key]
    return default


def visible_devices(user):
    """Viloyat xodimi — faqat o'z viloyatiga bog'langan Console hududlari."""
    queryset = BbaDevice.objects.all()
    if user.is_region_scoped:
        queryset = queryset.filter(bba_region__region_id=user.region_id)
    return queryset


def save_state(**fields) -> None:
    state = cache.get(STATE_KEY) or {}
    state.update(fields)
    cache.set(STATE_KEY, state, None)


def state() -> dict:
    return cache.get(STATE_KEY) or {}


# --------------------------------------------------------------------------
# Real vaqt
# --------------------------------------------------------------------------
def bba_group(region_id: int | None = None) -> str:
    return f"bba.region.{region_id}" if region_id else "bba.all"


def broadcast(kind: str, rows: list[dict]) -> None:
    """
    `rows` — har birida `region` (bizning viloyat ID'si yoki `None`).

    Hammasi `bba.all` ga (respublika), bog'langani o'z viloyati guruhiga ham.
    Realtime — qulaylik: xato sinxronizatsiyani to'xtatmaydi.
    """
    if not rows:
        return
    from apps.proctoring.services.realtime import group_send

    by_group: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_group[bba_group()].append(row)
        if row.get("region"):
            by_group[bba_group(row["region"])].append(row)
    for group, items in by_group.items():
        for start in range(0, len(items), BROADCAST_CHUNK):
            try:
                group_send(group, {
                    "type": "bba.update",
                    "kind": kind,
                    "payload": items[start:start + BROADCAST_CHUNK],
                })
            except Exception as exc:  # noqa: BLE001
                logger.debug("bba: WebSocket yuborilmadi (%s): %s", group, exc)


def _region_map() -> dict[int, int | None]:
    return dict(BbaRegion.objects.values_list("pk", "region_id"))


def status_row(device: BbaDevice, regions: dict[int, int | None]) -> dict:
    return {
        "id": device.pk,
        "status": device.status,
        "status_changed_at": device.status_changed_at.isoformat() if device.status_changed_at else None,
        "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
        "is_visible": device.is_visible,
        "region": regions.get(device.bba_region_id),
    }


# --------------------------------------------------------------------------
# Daraxt va holat
# --------------------------------------------------------------------------
def _upsert(model, existing: dict, console_id: str, values: dict):
    obj = existing.get(console_id)
    if obj is None:
        obj = model.objects.create(console_id=console_id, **values)
        existing[console_id] = obj
        return obj
    changed = [name for name, value in values.items() if getattr(obj, name) != value]
    if changed:
        for name in changed:
            setattr(obj, name, values[name])
        obj.save(update_fields=[*changed, "updated_at"])
    return obj


def sync_tree(client=None) -> dict:
    """Hudud va xonalar (o'nlab/yuzlab qator — oddiy upsert)."""
    client = client or get_client()
    now = timezone.now()
    regions_data = client.regions()
    rooms_data = client.rooms()

    regions = {str(item.console_id): item for item in BbaRegion.objects.all()}
    seen_regions = set()
    for item in regions_data:
        console_id = _uuid(item.get("ID"))
        if not console_id:
            continue
        seen_regions.add(console_id)
        _upsert(BbaRegion, regions, console_id, {
            "name": str(item.get("Name") or console_id)[:255],
            "code": str(item.get("Code") or "")[:64],
            "subnet": str(item.get("Subnet") or "")[:64],
            "room_count": _int(item.get("room_count")),
            "device_count": _int(item.get("device_count")),
            "is_visible": True,
            "synced_at": now,
        })
    BbaRegion.objects.filter(is_visible=True).exclude(console_id__in=seen_regions).update(is_visible=False)

    rooms = {str(item.console_id): item for item in BbaRoom.objects.all()}
    seen_rooms = set()
    for item in rooms_data:
        console_id = _uuid(item.get("ID"))
        if not console_id:
            continue
        seen_rooms.add(console_id)
        region = regions.get(_uuid(item.get("RegionID")))
        _upsert(BbaRoom, rooms, console_id, {
            "bba_region": region,
            "name": str(item.get("Name") or console_id)[:255],
            "code": str(item.get("Code") or "")[:64],
            "device_count": _int(item.get("device_count")),
            "is_visible": True,
            "synced_at": now,
        })
    BbaRoom.objects.filter(is_visible=True).exclude(console_id__in=seen_rooms).update(is_visible=False)

    cache.set(TREE_SYNCED_KEY, now.timestamp(), None)
    return {"regions": len(seen_regions), "rooms": len(seen_rooms)}


def _device_values(item: dict, room) -> dict:
    return {
        "room_id": room[0] if room else None,
        "bba_region_id": room[1] if room else None,
        "hostname_code": str(item.get("HostnameCode") or "")[:255],
        "hostname": str(item.get("Hostname") or "")[:255],
        "status": _status(item.get("Status")),
        "last_seen_at": _dt(item.get("LastSeenAt")),
        "enrolled_at": _dt(item.get("EnrolledAt")),
        "revoked_at": _dt(item.get("RevokedAt")),
        "agent_version": str(item.get("AgentVersion") or "")[:32],
        "test_mode_enabled": bool(item.get("TestModeEnabled")),
    }


def sync_devices(client=None) -> dict:
    """
    Barcha ko'rinadigan kompyuterlar holati — bitta yurishda.

    Faqat O'ZGARGAN qatorlar yoziladi (`bulk_update`); holati o'zgarganlar
    panelga yuboriladi. Ro'yxatda yo'qolgani o'chirilmaydi —
    `is_visible=False` (Console huquqi olingan bo'lishi mumkin).
    """
    client = client or get_client()
    now = timezone.now()
    items = list(client.iter_devices())

    def load_rooms():
        return {
            str(console_id): (pk, region_id)
            for pk, console_id, region_id in BbaRoom.objects.values_list("pk", "console_id", "bba_region_id")
        }

    rooms = load_rooms()
    if any(_uuid(item.get("RoomID")) not in rooms for item in items if item.get("RoomID")):
        # Yangi xona daraxt yurishidan oldin paydo bo'ldi — kutmaymiz.
        sync_tree(client)
        rooms = load_rooms()

    existing = {
        str(device.console_id): device
        for device in BbaDevice.objects.only("console_id", *_SYNC_FIELDS)
    }
    to_create: list[BbaDevice] = []
    to_update: list[BbaDevice] = []
    changed_status: list[BbaDevice] = []
    seen: set[str] = set()

    for item in items:
        console_id = _uuid(item.get("ID"))
        if not console_id or console_id in seen:
            continue
        seen.add(console_id)
        values = _device_values(item, rooms.get(_uuid(item.get("RoomID"))))
        device = existing.get(console_id)
        if device is None:
            device = BbaDevice(console_id=console_id, status_changed_at=now, **values)
            to_create.append(device)
            continue
        dirty = False
        if device.status != values["status"]:
            device.status_changed_at = now
            changed_status.append(device)
            dirty = True
        for name, value in values.items():
            if getattr(device, name) != value:
                setattr(device, name, value)
                dirty = True
        if not device.is_visible:
            device.is_visible = True
            device.missing_since = None
            changed_status.append(device)
            dirty = True
        if dirty:
            to_update.append(device)

    missing = [
        device for console_id, device in existing.items()
        if console_id not in seen and device.is_visible
    ]
    for device in missing:
        device.is_visible = False
        device.missing_since = now
    with transaction.atomic():
        if to_create:
            BbaDevice.objects.bulk_create(to_create, batch_size=500, ignore_conflicts=True)
        if to_update or missing:
            BbaDevice.objects.bulk_update([*to_update, *missing], list(_SYNC_FIELDS), batch_size=500)

    created = list(BbaDevice.objects.filter(console_id__in=[d.console_id for d in to_create])) if to_create else []
    touched = [*dict.fromkeys(changed_status), *missing, *created]
    if touched:
        regions = _region_map()
        broadcast("status", [status_row(device, regions) for device in touched])
    return {
        "total": len(seen),
        "created": len(created),
        "updated": len(to_update),
        "status_changed": len(set(map(id, changed_status))),
        "missing": len(missing),
    }


def link_computers(devices=None) -> int:
    """
    Console kompyuteri <-> bizning kompyuter: (UUID, MAC) juftligi.

    Qoida handshake bilan BITTA (`devices.services.match_identity`): UUID
    bir xil yozuvlar ichidan jismoniy MAC'lardan birortasi mos kelgani.
    UUID'siz (eski agent) yoki faqat MAC bo'yicha bog'lanmaydi.
    """
    from apps.devices.models import Computer
    from apps.devices.services import match_identity

    queryset = devices if devices is not None else BbaDevice.objects.all()
    rows = list(queryset.only("id", "system_uuid", "macs", "computer_id"))
    uuids = {row.system_uuid for row in rows if row.system_uuid}
    by_uuid: dict[str, list] = defaultdict(list)
    if uuids:
        for computer in Computer.objects.alive().filter(machine_uuid__in=uuids).only(
            "id", "machine_uuid", "mac_address"
        ):
            by_uuid[computer.machine_uuid].append(computer)

    changed = []
    for row in rows:
        target = None
        records = by_uuid.get(row.system_uuid) if row.system_uuid else None
        if records:
            for mac in row.macs or [""]:
                target = match_identity(records, mac)
                if target is not None:
                    break
        computer_id = target.pk if target else None
        if computer_id != row.computer_id:
            row.computer_id = computer_id
            changed.append(row)
    if changed:
        BbaDevice.objects.bulk_update(changed, ["computer"], batch_size=500)
    return len(changed)


# --------------------------------------------------------------------------
# Inventory
# --------------------------------------------------------------------------
_INVENTORY_FIELDS = (
    "inventory", "inventory_changes", "inventory_captured_at", "inventory_fetched_at",
    "inventory_error", "system_uuid", "macs", "primary_mac", "baseboard_serial",
    "tpm_ek_hash", "machine_guid",
)


def fetch_inventory(device: BbaDevice, client=None) -> BbaDevice:
    """
    Bitta kompyuterning oxirgi inventory'si. `snapshot: null` — xato emas,
    "hali yig'ilmagan". 403/404 qatorga yoziladi va chaqiruvchiga ko'tariladi.
    """
    client = client or get_client()
    now = timezone.now()
    try:
        data = client.inventory(str(device.console_id))
    except (BbaForbidden, BbaNotFound) as exc:
        device.inventory_error = str(exc)[:300]
        device.inventory_fetched_at = now
        device.save(update_fields=["inventory_error", "inventory_fetched_at", "updated_at"])
        raise
    snapshot = data.get("snapshot") if isinstance(data, dict) else None
    if not isinstance(snapshot, dict):
        snapshot = None
    ids = identity.extract(snapshot)
    device.inventory = snapshot
    device.inventory_changes = data.get("changes") if isinstance(data, dict) else None
    device.inventory_captured_at = _dt((snapshot or {}).get("CapturedAt"))
    device.inventory_fetched_at = now
    device.inventory_error = ""
    for name in ("system_uuid", "macs", "primary_mac", "baseboard_serial", "tpm_ek_hash", "machine_guid"):
        setattr(device, name, ids[name])
    device.save(update_fields=[*_INVENTORY_FIELDS, "updated_at"])
    link_computers(BbaDevice.objects.filter(pk=device.pk))
    device.refresh_from_db(fields=["computer"])
    return device


def sync_inventories(client=None, *, limit: int | None = None) -> dict:
    """
    Eskirgan (yoki hech olinmagan) inventory'lar — avval hech olinmaganlar.

    Vaqt byudjeti bilan: qolgani keyingi yurishda. 429 — kutib davom
    etadi; Console ishlamasa/login rad etilsa — yurish to'xtaydi.
    """
    cfg = settings.BBA_CONSOLE
    client = client or get_client()
    cutoff = timezone.now() - timedelta(hours=cfg["INVENTORY_MAX_AGE_HOURS"])
    queryset = (
        BbaDevice.objects.filter(is_visible=True)
        .filter(Q(inventory_fetched_at__isnull=True) | Q(inventory_fetched_at__lt=cutoff))
        .order_by(F("inventory_fetched_at").asc(nulls_first=True), "id")
        .defer("inventory", "inventory_changes")
    )
    started = time.monotonic()
    done = errors = 0
    stopped = ""
    for device in queryset[: limit or cfg["INVENTORY_BATCH"]]:
        if time.monotonic() - started > INVENTORY_TIME_BUDGET_S:
            stopped = "time_budget"
            break
        try:
            fetch_inventory(device, client)
            done += 1
        except (BbaForbidden, BbaNotFound):
            errors += 1
        except BbaRateLimited as exc:
            time.sleep(exc.retry_after)
            errors += 1
        except BbaError as exc:
            stopped = str(exc)
            break
        if cfg["INVENTORY_PAUSE"]:
            time.sleep(cfg["INVENTORY_PAUSE"])
    return {"fetched": done, "errors": errors, "stopped": stopped}


def refresh_inventory(device: BbaDevice) -> BbaDevice:
    """Paneldagi «Yangilash»: yaqinda olingan bo'lsa Console'ga bormaydi."""
    window = settings.BBA_CONSOLE["INVENTORY_REFRESH_SECONDS"]
    fresh = device.inventory_fetched_at and (
        timezone.now() - device.inventory_fetched_at < timedelta(seconds=window)
    )
    if fresh and not device.inventory_error:
        return device
    try:
        return fetch_inventory(device)
    except BbaError as exc:
        raise as_domain_error(exc) from exc


# --------------------------------------------------------------------------
# Davriy yurish
# --------------------------------------------------------------------------
def poll() -> dict:
    """
    Celery `bba.poll` (har `STATUS_POLL_SECONDS`): daraxt (eskirgan bo'lsa),
    holat, kutilayotgan job'lar. Natija holati panel uchun keshda.
    """
    if not is_configured():
        return {"skipped": "disabled"}
    client = get_client()
    now = timezone.now()
    try:
        tree_at = cache.get(TREE_SYNCED_KEY) or 0
        if now.timestamp() - tree_at >= settings.BBA_CONSOLE["TREE_SYNC_SECONDS"]:
            sync_tree(client)
            link_computers()
        result = sync_devices(client)
        if pending_jobs().exists():
            result["jobs"] = refresh_jobs(client)
    except BbaError as exc:
        save_state(ok=False, error=str(exc), error_code=exc.code, last_error_at=now.isoformat())
        logger.warning("BBA Console sinxronizatsiyasi: %s", exc)
        return {"error": str(exc)}
    save_state(
        ok=True, error="", error_code="", last_success_at=now.isoformat(),
        total=result["total"],
    )
    return result


# --------------------------------------------------------------------------
# Kompyuterni bizning ro'yxatga qo'shish
# --------------------------------------------------------------------------
def default_inventory_code(device: BbaDevice, mac: str) -> str:
    """Console nomi (`BBA-110-3`) yaroqli va bo'sh bo'lsa — o'sha, aks holda AUTO-kod."""
    import re

    from apps.devices.models import Computer
    from apps.devices.services import auto_inventory_code

    code = (device.hostname_code or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_\-]{3,50}", code) and not Computer.objects.alive().filter(
        inventory_code=code
    ).exists():
        return code
    return auto_inventory_code(machine_uuid=device.system_uuid, mac_address=mac)


def import_computer(device: BbaDevice, *, zone_id, request, number=None,
                    inventory_code: str = "", mac_address: str = ""):
    """
    Console kompyuterini bizning `Computer` sifatida qo'shadi.

    Tekshiruv panel formasi bilan BITTA (`ComputerSerializer`): juftlik
    unikalligi, MAC majburiyligi, viloyat chegarasi. UUID — inventory'dan
    (placeholder bo'lsa qo'shilmaydi: uni minglab mashina bo'lishadi).
    """
    from apps.devices.api.v1.serializers import ComputerSerializer
    from apps.proctoring.services.audit import record_audit

    if device.computer_id and device.computer and device.computer.deleted_at is None:
        raise BbaAlreadyLinked(extra={"computer": device.computer_id})
    if not device.system_uuid:
        raise serializers.ValidationError({
            "detail": "Inventory'da haqiqiy System UUID yo'q — avval inventory'ni yangilang "
                      "(agent 0.1.96+ kerak)"
        })
    mac = identity.canonical_mac(mac_address) if mac_address else device.primary_mac
    if mac_address and mac not in (device.macs or []):
        raise serializers.ValidationError(
            {"mac_address": "Bu MAC kompyuterning jismoniy adapterlari ichida yo'q"}
        )
    if not mac:
        raise serializers.ValidationError({"mac_address": "Kompyuterda jismoniy MAC topilmadi"})

    serializer = ComputerSerializer(
        data={
            "zone": zone_id,
            "number": number,
            "inventory_code": (inventory_code or "").strip() or default_inventory_code(device, mac),
            "machine_uuid": device.system_uuid,
            "mac_address": mac,
        },
        context={"request": request},
    )
    serializer.is_valid(raise_exception=True)
    with transaction.atomic():
        computer = serializer.save()
        device.computer = computer
        device.save(update_fields=["computer", "updated_at"])
    record_audit(
        actor=request.user, action="bba_import_computer", object_type="Computer",
        object_id=computer.pk, request=request,
        meta={"bba_device": str(device.console_id), "hostname_code": device.hostname_code},
    )
    return computer


def bulk_import(devices, *, zone_id, request) -> list[dict]:
    """Har kompyuter alohida: bittasining xatosi qolganlarini to'xtatmaydi."""
    results = []
    for device in devices:
        row = {"id": device.pk, "name": device.name}
        try:
            with transaction.atomic():
                computer = import_computer(device, zone_id=zone_id, request=request)
            row.update(status="created", computer=computer.pk)
        except BbaAlreadyLinked:
            row.update(status="skipped", message="Allaqachon ro'yxatda")
        except serializers.ValidationError as exc:
            row.update(status="error", message=_flatten(exc.detail))
        results.append(row)
    return results


def _flatten(detail) -> str:
    if isinstance(detail, dict):
        return "; ".join(_flatten(value) for value in detail.values())
    if isinstance(detail, (list, tuple)):
        return "; ".join(_flatten(value) for value in detail)
    return str(detail)


# --------------------------------------------------------------------------
# Job'lar
# --------------------------------------------------------------------------
def pending_jobs():
    since = timezone.now() - timedelta(hours=JOB_TRACK_HOURS)
    return BbaJob.objects.filter(created_at__gte=since).exclude(status__in=BbaJob.TERMINAL)


def dispatch_job(devices: list[BbaDevice], *, job_type: str, params, confirm: bool, request) -> list[BbaJob]:
    """
    Job yuborish — bitta kompyuter `POST /devices/{id}/jobs`, ko'pi bulk.

    Qayta urinish YO'Q (`client.post`). Har kompyuterga `BbaJob` qatori:
    kim yuborgani shu yerda qoladi; Console rad etgan kompyuter `error`.
    """
    from apps.proctoring.services.audit import record_audit

    if not devices:
        raise serializers.ValidationError({"ids": "Hech narsa tanlanmagan"})
    if len(devices) > jobs.MAX_BULK_DEVICES:
        raise serializers.ValidationError(
            {"ids": f"Bir martada ko'pi bilan {jobs.MAX_BULK_DEVICES} ta kompyuter"}
        )
    cleaned = jobs.clean_params(job_type, params)
    spec = jobs.BY_CODE[job_type]
    if spec.dangerous and not confirm:
        raise serializers.ValidationError({"confirm": "Bu amal xavfli — tasdiqlang"})
    body = {"type": job_type, "params": cleaned, "confirm": bool(spec.dangerous)}
    user = request.user
    base = {
        "job_type": job_type, "params": cleaned, "issued_by": user,
        "issued_by_username": user.username,
    }
    client = get_client()
    try:
        if len(devices) == 1:
            response = client.create_job(str(devices[0].console_id), body)
            records = [BbaJob(
                device=devices[0],
                console_job_id=str(_first(response, "job_id", "JobID", default=""))[:64],
                status=_job_status(_first(response, "status", "Status")),
                **base,
            )]
            bulk_id = ""
        else:
            response = client.bulk_create_jobs([str(d.console_id) for d in devices], body)
            bulk_id = str(_first(response, "bulk_operation_id", "BulkOperationID", default=""))[:64]
            records = _bulk_records(devices, response.get("jobs") or [], bulk_id, base)
    except BbaError as exc:
        raise as_domain_error(exc) from exc
    now = timezone.now()
    for record in records:
        if record.status != BbaJob.Status.ERROR:
            record.sent_at = now
    created = BbaJob.objects.bulk_create(records)
    record_audit(
        actor=user, action="bba_job", object_type="BbaDevice",
        object_id=devices[0].pk if len(devices) == 1 else None, request=request,
        meta={
            "type": job_type,
            "params": jobs.audit_params(job_type, cleaned),
            "devices": len(devices),
            "console_ids": [str(d.console_id) for d in devices[:50]],
            "bulk_operation_id": bulk_id,
            "failed": sum(1 for r in created if r.status == BbaJob.Status.ERROR),
        },
    )
    return created


def _bulk_records(devices, items: list, bulk_id: str, base: dict) -> list[BbaJob]:
    """
    Bulk javobi `{bulk_operation_id, jobs: [...]}`. Elementda `device_id`
    bo'lsa shu bo'yicha, bo'lmasa (va soni teng bo'lsa) tartib bo'yicha.
    Javobda yo'q kompyuter — `sent` (`refresh_jobs` uni `BulkOperationID`
    bo'yicha topadi).
    """
    by_device = {}
    for item in items:
        if isinstance(item, dict):
            console_id = _uuid(_first(item, "device_id", "DeviceID"))
            if console_id:
                by_device[console_id] = item
    if not by_device and len(items) == len(devices):
        by_device = {str(device.console_id): item for device, item in zip(devices, items) if isinstance(item, dict)}
    records = []
    for device in devices:
        item = by_device.get(str(device.console_id)) or {}
        error = str(_first(item, "error", "Error", default=""))[:300]
        records.append(BbaJob(
            device=device,
            console_job_id=str(_first(item, "job_id", "JobID", default=""))[:64],
            bulk_operation_id=bulk_id,
            status=BbaJob.Status.ERROR if error else _job_status(_first(item, "status", "Status")),
            error=error,
            **base,
        ))
    return records


def _apply_console_job(job: BbaJob, record: dict) -> bool:
    values = {
        "status": _job_status(record.get("Status")),
        "result": record.get("Result"),
        "sent_at": _dt(record.get("SentAt")) or job.sent_at,
        "completed_at": _dt(record.get("CompletedAt")),
    }
    job_id = str(record.get("JobID") or "")[:64]
    if job_id and not job.console_job_id:
        values["console_job_id"] = job_id
    changed = False
    for name, value in values.items():
        if getattr(job, name) != value:
            setattr(job, name, value)
            changed = True
    return changed


def refresh_jobs(client=None) -> int:
    """
    Kutilayotgan job'lar holati: avval umumiy oxirgi sahifa (bitta so'rov),
    topilmaganlari — qurilma bo'yicha (cheklangan son).
    """
    client = client or get_client()
    pending = list(pending_jobs().select_related("device"))
    if not pending:
        return 0

    def index(records):
        by_id, by_bulk = {}, {}
        for record in records:
            if record.get("JobID"):
                by_id[str(record["JobID"])] = record
            if record.get("BulkOperationID"):
                by_bulk[(str(record["BulkOperationID"]), _uuid(record.get("DeviceID")))] = record
        return by_id, by_bulk

    def match(job, by_id, by_bulk):
        if job.console_job_id:
            return by_id.get(job.console_job_id)
        if job.bulk_operation_id:
            return by_bulk.get((job.bulk_operation_id, str(job.device.console_id)))
        return None

    by_id, by_bulk = index(client.jobs(limit=JOB_REFRESH_PAGE)["jobs"])
    changed, unresolved = [], []
    for job in pending:
        record = match(job, by_id, by_bulk)
        if record is None:
            unresolved.append(job)
        elif _apply_console_job(job, record):
            changed.append(job)

    devices = list(dict.fromkeys(job.device for job in unresolved))[:JOB_REFRESH_DEVICE_LIMIT]
    for device in devices:
        by_id, by_bulk = index(client.jobs(device_id=str(device.console_id), limit=50)["jobs"])
        for job in unresolved:
            if job.device_id == device.pk:
                record = match(job, by_id, by_bulk)
                if record is not None and _apply_console_job(job, record):
                    changed.append(job)

    if changed:
        BbaJob.objects.bulk_update(
            changed, ["status", "result", "sent_at", "completed_at", "console_job_id"]
        )
        regions = _region_map()
        broadcast("job", [
            {
                "id": job.pk, "device": job.device_id, "status": job.status,
                "region": regions.get(job.device.bba_region_id),
            }
            for job in changed
        ])
    return len(changed)


def cancel_job(job: BbaJob, *, request) -> BbaJob:
    return _job_action(job, "cancel", request)


def resend_job(job: BbaJob, *, request) -> BbaJob:
    return _job_action(job, "resend", request)


def _job_action(job: BbaJob, action: str, request) -> BbaJob:
    from apps.proctoring.services.audit import record_audit

    if not job.console_job_id:
        raise serializers.ValidationError({"detail": "Job Console'da yaratilmagan"})
    client = get_client()
    try:
        response = (client.cancel_job if action == "cancel" else client.resend_job)(job.console_job_id)
    except BbaError as exc:
        raise as_domain_error(exc) from exc
    reported = _first(response or {}, "status", "Status")
    if reported in BbaJob.Status.values:
        job.status = reported
    else:
        job.status = BbaJob.Status.CANCELLED if action == "cancel" else BbaJob.Status.SENT
    if action == "resend":
        job.completed_at = None
        job.result = None
    job.save(update_fields=["status", "completed_at", "result", "updated_at"])
    record_audit(
        actor=request.user, action=f"bba_job_{action}", object_type="BbaJob",
        object_id=job.pk, request=request, meta={"console_job_id": job.console_job_id},
    )
    return job


def wake(devices: list[BbaDevice], *, request) -> list[dict]:
    """
    Wake-on-LAN — Console xonadagi boshqa YONIQ kompyuter orqali uzatadi.
    Xonada yoniq kompyuter bo'lmasa Console rad etadi (409).
    """
    from apps.proctoring.services.audit import record_audit

    if not devices:
        raise serializers.ValidationError({"ids": "Hech narsa tanlanmagan"})
    if len(devices) > jobs.MAX_BULK_DEVICES:
        raise serializers.ValidationError(
            {"ids": f"Bir martada ko'pi bilan {jobs.MAX_BULK_DEVICES} ta kompyuter"}
        )
    client = get_client()
    try:
        if len(devices) == 1:
            response = client.wake(str(devices[0].console_id))
            items = [{"device_id": str(devices[0].console_id), **(response or {})}]
        else:
            items = (client.wake_many([str(d.console_id) for d in devices]) or {}).get("results") or []
    except BbaError as exc:
        raise as_domain_error(exc) from exc
    by_console = {str(d.console_id): d for d in devices}
    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        device = by_console.get(_uuid(_first(item, "device_id", "DeviceID")))
        results.append({
            "id": device.pk if device else None,
            "name": device.name if device else "",
            "status": str(_first(item, "status", "Status", default="")),
            "message": str(_first(item, "error", "message", default=""))[:300],
        })
    record_audit(
        actor=request.user, action="bba_wake", object_type="BbaDevice",
        object_id=devices[0].pk if len(devices) == 1 else None, request=request,
        meta={"devices": len(devices), "console_ids": [str(d.console_id) for d in devices[:50]]},
    )
    return results


# --------------------------------------------------------------------------
# Tafsilot sahifasi uchun Console'dan to'g'ridan-to'g'ri
# --------------------------------------------------------------------------
def connectivity(device: BbaDevice, limit: int = 30) -> list[dict]:
    try:
        events = get_client().connectivity(str(device.console_id), limit)
    except BbaError as exc:
        raise as_domain_error(exc) from exc
    return [
        {
            "kind": event.get("Kind") or "",
            "detail": event.get("Detail"),
            "occurred_at": event.get("OccurredAt"),
            "reported_at": event.get("ReportedAt"),
        }
        for event in events if isinstance(event, dict)
    ]


def device_job_history(device: BbaDevice, limit: int = 25) -> list[dict]:
    """
    Console'dagi shu kompyuter job'lari (Console UI'dan yuborilganlari ham);
    panelimizdan yuborilgani — kim yuborgani bilan.
    """
    try:
        records = get_client().jobs(device_id=str(device.console_id), limit=min(limit, 100))["jobs"]
    except BbaError as exc:
        raise as_domain_error(exc) from exc
    ours = {
        job.console_job_id: job
        for job in BbaJob.objects.filter(device=device).exclude(console_job_id="")
    }
    rows = []
    for record in records:
        if not isinstance(record, dict):
            continue
        job = ours.get(str(record.get("JobID") or ""))
        rows.append({
            "console_job_id": record.get("JobID"),
            "local_id": job.pk if job else None,
            "type": record.get("Type"),
            "status": record.get("Status"),
            "params": record.get("Params"),
            "result": record.get("Result"),
            "issued_at": record.get("IssuedAt"),
            "completed_at": record.get("CompletedAt"),
            "issued_by": job.issued_by_username if job else (record.get("IssuedBy") or ""),
            "from_panel": job is not None,
        })
    return rows


def overview(user) -> dict:
    """Panel sarlavhasi: sozlanganmi, oxirgi sinxronizatsiya, holatlar soni."""
    devices = visible_devices(user).filter(is_visible=True)
    counts = dict(devices.order_by().values_list("status").annotate(n=Count("id")).values_list("status", "n"))
    data = {
        "enabled": settings.BBA_CONSOLE["ENABLED"],
        "configured": is_configured(),
        "state": state(),
        "login_blocked": login_block_reason() or "",
        "poll_seconds": settings.BBA_CONSOLE["STATUS_POLL_SECONDS"],
        "total": sum(counts.values()),
        "by_status": {value: counts.get(value, 0) for value in BbaDevice.Status.values},
        "linked": devices.filter(computer__isnull=False).count(),
        "revoked": devices.filter(revoked_at__isnull=False).count(),
    }
    if not user.is_region_scoped:
        data["unmapped_regions"] = BbaRegion.objects.filter(is_visible=True, region__isnull=True).count()
    return data
