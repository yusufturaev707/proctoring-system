"""
Console job turlari katalogi — BITTA joyda (server tekshiruvi va panel formasi).

Panel turlarni `bba/job-types/` dan oladi: forma qaysi parametr maydonini
chizishini (`params`) va tasdiq kerakligini (`dangerous`) shu yerdan biladi.
Console'ning o'z formasi bilan bir xil qoidalar (Console UI manbasi,
`JobDispatchForm.jsx`, 2026-10): `lock_system`/`unlock_system` bo'sh
`features` ni rad etadi, parametrsiz turlarga `{}` ketadi.

Xavfli job tasdiqsiz yuborilmaydi (`confirm`) — Console ham aynan shu
bayroqni talab qiladi.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from rest_framework import serializers

#: Bulk job — bitta so'rovda ko'pi bilan.
MAX_BULK_DEVICES = 500
MAX_SCRIPT_CHARS = 64 * 1024
MAX_JSON_CHARS = 16 * 1024

LOCK_FEATURES = ("task_manager", "control_panel", "usb")
SCRIPT_TYPES = ("powershell", "cmd", "sh")


@dataclass(frozen=True)
class JobType:
    code: str
    label: str
    #: Parametr shakli: `none` | `script` | `features` | `startup` | `json`.
    params: str
    dangerous: bool
    detail: str = ""


CATALOG: tuple[JobType, ...] = (
    JobType("collect_inventory", "Inventory'ni yangilash", "none", False,
            "Agent hardware, tarmoq va dasturlar ro'yxatini darhol qayta yuboradi."),
    JobType("restart_computer", "Qayta yuklash", "none", True,
            "Kompyuter zudlik bilan qayta yuklanadi — saqlanmagan ish yo'qoladi."),
    JobType("shutdown_computer", "O'chirish", "none", True,
            "Kompyuter zudlik bilan o'chadi. Qayta yoqish — Wake-on-LAN yoki joyida."),
    JobType("lock_system", "Funksiyalarni bloklash", "features", True,
            "Tanlangan funksiyalar (Task Manager, Control Panel, USB) darhol bloklanadi."),
    JobType("unlock_system", "Blokdan chiqarish", "features", False,
            "Tanlangan funksiyalar blokdan chiqariladi."),
    JobType("run_script", "Skript bajarish", "script", True,
            "Skript kompyuterda SYSTEM huquqida bajariladi. Natija oldindan kafolatlanmaydi."),
    JobType("manage_startup_app", "Avtostart dasturi", "startup", False,
            "Dastur Windows ishga tushganda yoqiladi yoki o'chiriladi."),
    JobType("install_software", "Dastur o'rnatish", "json", True,
            "Ko'rsatilgan manzildan dastur yuklab olinib, SYSTEM huquqida so'roqsiz o'rnatiladi."),
    JobType("uninstall_software", "Dasturni o'chirish", "json", True,
            "Dastur kompyuterdan olib tashlanadi. Console orqali qaytarib bo'lmaydi."),
    JobType("rename_computer", "Windows nomini o'zgartirish", "json", True,
            "Kompyuterning haqiqiy Windows nomi o'zgaradi; restart yoqilgan bo'lsa qayta yuklanadi."),
    JobType("run_interactive", "Interaktiv amal", "json", True,
            "Foydalanuvchi sessiyasida avtomatik UI harakatlari bajariladi."),
    JobType("update_agent", "Agentni yangilash", "none", True,
            "BBA Agent yangilanadi va qisqa vaqtga aloqa uziladi."),
    JobType("uninstall_agent", "Agentni o'chirish", "none", True,
            "BBA boshqaruvi BUTUNLAY olib tashlanadi — Console orqali qaytarib bo'lmaydi."),
)

BY_CODE = {item.code: item for item in CATALOG}


def catalog() -> list[dict]:
    return [
        {
            "code": item.code, "label": item.label, "params": item.params,
            "dangerous": item.dangerous, "detail": item.detail,
        }
        for item in CATALOG
    ]


def _text(params: dict, key: str, *, required: bool, limit: int = 1024) -> str:
    value = params.get(key, "")
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise serializers.ValidationError({"params": f"`{key}` matn bo'lishi kerak"})
    value = value.strip()
    if required and not value:
        raise serializers.ValidationError({"params": f"`{key}` kiritilishi shart"})
    if len(value) > limit:
        raise serializers.ValidationError({"params": f"`{key}` juda uzun"})
    return value


def clean_params(code: str, params) -> dict:
    """Tur bo'yicha tekshirilgan parametrlar (Console'ga aynan shu ketadi)."""
    spec = BY_CODE.get(code)
    if spec is None:
        raise serializers.ValidationError({"job_type": "Noma'lum job turi"})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise serializers.ValidationError({"params": "Parametrlar JSON obyekt bo'lishi kerak"})

    if spec.params == "none":
        return {}
    if spec.params == "script":
        script_type = params.get("script_type") or "powershell"
        if script_type not in SCRIPT_TYPES:
            raise serializers.ValidationError({"params": "Skript turi: powershell, cmd yoki sh"})
        content = params.get("script_content")
        if not isinstance(content, str) or not content.strip():
            raise serializers.ValidationError({"params": "Skript matni kiritilishi shart"})
        if len(content) > MAX_SCRIPT_CHARS:
            raise serializers.ValidationError({"params": "Skript juda uzun (64 KB gacha)"})
        return {"script_type": script_type, "script_content": content}
    if spec.params == "features":
        features = params.get("features")
        if not isinstance(features, list) or not features:
            raise serializers.ValidationError({"params": "Kamida bitta funksiyani tanlang"})
        unknown = [item for item in features if item not in LOCK_FEATURES]
        if unknown:
            raise serializers.ValidationError({"params": f"Noma'lum funksiya: {', '.join(map(str, unknown))}"})
        return {"features": [item for item in LOCK_FEATURES if item in features]}
    if spec.params == "startup":
        action = params.get("action")
        if action not in ("enable", "disable"):
            raise serializers.ValidationError({"params": "`action`: enable yoki disable"})
        cleaned = {"action": action, "name": _text(params, "name", required=True, limit=255)}
        command = _text(params, "command", required=False)
        path = _text(params, "path", required=False)
        if action == "enable" and not (command or path):
            raise serializers.ValidationError({"params": "Dastur yo'li (`command`) kiritilishi shart"})
        for key, value in (("command", command), ("path", path)):
            if value:
                cleaned[key] = value
        for key in ("type", "hive"):
            value = _text(params, key, required=False, limit=64)
            if value:
                cleaned[key] = value
        return cleaned
    # `json` — Console parametrlari turga xos va bizda sxemasi yo'q: shakl
    # (obyekt, hajm) tekshiriladi, mazmunini Console o'zi tekshiradi.
    if len(json.dumps(params, ensure_ascii=False)) > MAX_JSON_CHARS:
        raise serializers.ValidationError({"params": "Parametrlar juda katta (16 KB gacha)"})
    return params


def audit_params(code: str, params: dict) -> dict:
    """Audit uchun: skript matni qisqartiriladi (audit jurnali fayl ombori emas)."""
    if code == "run_script":
        content = params.get("script_content", "")
        return {
            "script_type": params.get("script_type"),
            "script_content": content[:2000] + ("…" if len(content) > 2000 else ""),
        }
    return params
