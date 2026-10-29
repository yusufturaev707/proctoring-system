"""
Console inventory'sidan mashina identifikatorlari (`bba_agent_api.md` §5).

Bizning kanonik shakllar ishlatiladi (`normalize_machine_uuid`, `normalize_mac`
— handshake, Excel import va panel bilan bir xil): Console MAC'ni
`C4-62-37-01-DE-1A`, client `c4:62:...` yozadi — solishtirish faqat bitta
shaklda ma'noli.

Placeholder'lar ("System Serial Number", nollar) ID EMAS: ular minglab
mashinada bir xil va o'nlab kompyuterni bitta qilib qo'yardi.
"""

from __future__ import annotations

import re

from apps.common.utils.validators import normalize_mac, normalize_machine_uuid

PLACEHOLDERS = frozenset({
    "to be filled by o.e.m.", "default string", "system serial number",
    "system product name", "system manufacturer", "base board serial number",
    "chassis serial number", "not specified", "not applicable", "none", "o.e.m.",
    "oem", "invalid", "123456789", "00000000-0000-0000-0000-000000000000",
    "ffffffff-ffff-ffff-ffff-ffffffffffff", "03000200-0400-0500-0006-000700080009",
})

_SEPARATORS = re.compile(r"[-_.\s]")
_HEX12 = re.compile(r"^[0-9A-F]{12}$")


def clean_id(value) -> str:
    """Seriya/xesh: katta harf, chetdagi `{}`/bo'shliqsiz; placeholder — bo'sh satr."""
    text = str(value or "").strip().strip("{}").strip()
    core = _SEPARATORS.sub("", text.lower())
    if not text or text.lower() in PLACEHOLDERS or not core:
        return ""
    if set(core) <= {"0"} or set(core) <= {"f"}:
        return ""
    return text.upper()


def canonical_mac(value) -> str:
    """`C4-62-...`, `c4:62:...`, `C46237...` -> `C4:62:37:01:DE:1A`; yaroqsiz — ``""``."""
    raw = re.sub(r"[^0-9A-Fa-f]", "", str(value or "")).upper()
    if not _HEX12.match(raw) or not clean_id(raw):
        return ""
    return normalize_mac(":".join(raw[i:i + 2] for i in range(0, 12, 2))) or ""


def _unique(values) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen


def physical_macs(snapshot: dict) -> list[str]:
    """
    Jismoniy adapterlar MAC'lari (`Hardware.ids.network_adapters`).

    `NetworkConfig` — faqat `ids` yo'q eski agentda (< 0.1.96): unga virtual
    adapterlar ham kiradi.
    """
    hardware = snapshot.get("Hardware") or {}
    ids = hardware.get("ids") or {}
    adapters = ids.get("network_adapters") or []
    if not adapters:
        adapters = snapshot.get("NetworkConfig") or []
    return _unique(canonical_mac(item.get("mac")) for item in adapters if isinstance(item, dict))


def primary_mac(snapshot: dict) -> str:
    """
    Client handshake'da yuboradigan MAC'ga eng yaqin taxmin.

    Client marshrut o'tgan adapter MAC'ini yuboradi: yoqilgan, IPv4 manzili
    va shlyuzi bor adapter. Shunday jismoniy adapter bo'lmasa — birinchi
    jismoniy MAC. Faqat TAKLIF: import dialogida administrator boshqasini
    tanlay oladi.
    """
    physical = physical_macs(snapshot)
    for nic in snapshot.get("NetworkConfig") or []:
        if not isinstance(nic, dict) or nic.get("enabled") is False or not nic.get("gateway"):
            continue
        has_ipv4 = any(re.match(r"^\d+\.\d+\.\d+\.\d+/", str(addr)) for addr in nic.get("addrs") or [])
        mac = canonical_mac(nic.get("mac"))
        if has_ipv4 and mac and (not physical or mac in physical):
            return mac
    return physical[0] if physical else ""


def extract(snapshot: dict | None) -> dict:
    """Bitta inventory snapshot'idan saqlanadigan identifikatorlar."""
    if not snapshot:
        return {
            "system_uuid": "", "macs": [], "primary_mac": "", "baseboard_serial": "",
            "tpm_ek_hash": "", "machine_guid": "",
        }
    ids = (snapshot.get("Hardware") or {}).get("ids") or {}
    return {
        "system_uuid": normalize_machine_uuid(ids.get("system_uuid")),
        "macs": physical_macs(snapshot),
        "primary_mac": primary_mac(snapshot),
        "baseboard_serial": clean_id(ids.get("baseboard_serial"))[:128],
        "tpm_ek_hash": clean_id(ids.get("tpm_ek_hash"))[:128],
        "machine_guid": clean_id(ids.get("machine_guid"))[:64],
    }
