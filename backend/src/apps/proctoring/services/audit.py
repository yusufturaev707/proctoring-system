"""Audit yozuvlari — huquqiy himoya uchun."""

from __future__ import annotations

import logging

from apps.common.throttling import client_ip
from apps.proctoring.models import AuditLog

logger = logging.getLogger(__name__)


def record_audit(
    *,
    actor,
    action: str,
    object_type: str = "",
    object_id=None,
    meta: dict | None = None,
    request=None,
) -> AuditLog | None:
    """
    Audit yozuvi yaratadi.

    Ataylab xatoni yutadi: audit yozib bo'lmagani asosiy amalni
    (masalan chetlashtirishni) bekor qilmasligi kerak. Lekin bunday
    holat log'da ERROR sifatida qoladi.
    """
    try:
        return AuditLog.objects.create(
            actor=actor if getattr(actor, "pk", None) else None,
            actor_username=getattr(actor, "username", "system"),
            action=action,
            object_type=object_type or "",
            object_id=str(object_id) if object_id is not None else "",
            ip_address=client_ip(request) if request is not None else None,
            user_agent=(request.META.get("HTTP_USER_AGENT", "")[:500] if request else ""),
            request_id=getattr(request, "request_id", "") if request else "",
            meta=meta or {},
        )
    except Exception as exc:
        logger.error("Audit yozib bo'lmadi (%s/%s): %s", action, object_type, exc)
        return None
