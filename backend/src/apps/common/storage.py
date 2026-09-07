"""
Object storage (MinIO / S3) — skrinshotlar va yuz rasmlari uchun.

Asosiy g'oya: **binary backend orqali o'tmaydi**. Client presigned URL oladi
va faylni to'g'ridan-to'g'ri storage'ga yuboradi, keyin faqat metadata'ni
backend'ga commit qiladi.

10 000 talaba × 10s interval × 120 KB = ~120 MB/s. Bu oqim Django'dan o'tsa,
hech qanday worker soni yetmaydi. Presigned bilan backend trafigi ~0 bo'ladi.
"""

from __future__ import annotations

import datetime as dt
import functools
import logging
import uuid

from django.conf import settings

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def get_s3_client():
    import boto3
    from botocore.config import Config

    conf = settings.STORAGE
    return boto3.client(
        "s3",
        endpoint_url=conf["ENDPOINT_URL"],
        aws_access_key_id=conf["ACCESS_KEY"],
        aws_secret_access_key=conf["SECRET_KEY"],
        region_name=conf["REGION"],
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 2, "mode": "standard"},
            connect_timeout=3,
            read_timeout=5,
            max_pool_connections=100,
        ),
    )


def build_object_key(session_public_id: str, kind: str, extension: str = "jpg") -> str:
    """
    Kalit sanaga qarab bo'linadi: `2026/08/07/<session>/screen/<uuid>.jpg`

    Sana prefiksi eski ma'lumotni lifecycle qoidasi bilan ommaviy o'chirish
    va listing'ni tez qilish imkonini beradi.
    """
    today = dt.datetime.now(dt.timezone.utc)
    return (
        f"{today:%Y/%m/%d}/{session_public_id}/{kind}/"
        f"{uuid.uuid4().hex}.{extension.lstrip('.')}"
    )


def presign_put(object_key: str, content_type: str = "image/jpeg") -> dict | None:
    """Client shu URL'ga to'g'ridan-to'g'ri PUT qiladi."""
    if not settings.STORAGE["ENABLED"]:
        return None
    try:
        url = get_s3_client().generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.STORAGE["BUCKET"],
                "Key": object_key,
                "ContentType": content_type,
            },
            ExpiresIn=settings.STORAGE["PRESIGN_TTL"],
        )
    except Exception as exc:
        logger.error("Presigned PUT yaratib bo'lmadi (%s): %s", object_key, exc)
        return None

    return {
        "url": url,
        "key": object_key,
        "method": "PUT",
        "headers": {"Content-Type": content_type},
        "expires_in": settings.STORAGE["PRESIGN_TTL"],
    }


def presign_get(object_key: str, expires_in: int | None = None) -> str | None:
    """Proktor dashboard'i skrinshotni shu URL orqali ko'radi."""
    if not settings.STORAGE["ENABLED"] or not object_key:
        return None
    try:
        return get_s3_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.STORAGE["BUCKET"], "Key": object_key},
            ExpiresIn=expires_in or settings.STORAGE["PRESIGN_TTL"],
        )
    except Exception as exc:
        logger.error("Presigned GET yaratib bo'lmadi (%s): %s", object_key, exc)
        return None


def delete_objects(keys: list[str]) -> int:
    """Retention siyosati bo'yicha ommaviy o'chirish (1000 tadan)."""
    if not settings.STORAGE["ENABLED"] or not keys:
        return 0

    client = get_s3_client()
    bucket = settings.STORAGE["BUCKET"]
    deleted = 0
    for index in range(0, len(keys), 1000):
        chunk = keys[index : index + 1000]
        try:
            response = client.delete_objects(
                Bucket=bucket,
                Delete={"Objects": [{"Key": key} for key in chunk], "Quiet": True},
            )
            deleted += len(chunk) - len(response.get("Errors", []))
        except Exception as exc:
            logger.error("Obyektlarni o'chirishda xato: %s", exc)
    return deleted
