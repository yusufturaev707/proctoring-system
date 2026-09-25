"""
Yozishdagi hudud chegarasi.

O'qishdagi chegara har bir viewset'ning `get_queryset()` ida va u
TAHRIRLASH/O'CHIRISHNI ham qamraydi (begona qator `get_object()` da
404 beradi). YARATISH va MAYDONNI ALMASHTIRISH esa querysetdan
o'tmaydi: viloyat administratori boshqa viloyatning binosiga kompyuter
qo'shishi yoki o'z kompyuterini begona binoga "ko'chirishi" mumkin edi —
keyin u yozuvni o'zi ham ko'rmaydi, lekin u o'sha viloyatning
ro'yxatlariga, bronlariga va proktoriga tushadi.

Qoida bitta joyda, serializer'lar uni `validate()` da chaqiradi.
"""

from __future__ import annotations

from collections.abc import Callable

from rest_framework import serializers

DEFAULT_MESSAGE = "Faqat o'z viloyatingiz doirasida ishlay olasiz"


def request_user(serializer):
    request = serializer.context.get("request")
    user = getattr(request, "user", None)
    return user if user is not None and user.is_authenticated else None


def ensure_in_region(
    serializer,
    attrs: dict,
    field: str,
    *,
    region_of: Callable,
    allow_null: bool = False,
    message: str = DEFAULT_MESSAGE,
    null_message: str | None = None,
) -> None:
    """
    `attrs[field]` foydalanuvchining viloyatiga tegishli bo'lishi shart.

    Tekshiruv FAQAT maydon yozilayotganda: tahrirda maydon yuborilmagan
    bo'lsa, qator allaqachon `get_queryset()` chegarasidan o'tgan.
    `allow_null=False` da bo'sh qiymat ham rad etiladi — viloyat
    foydalanuvchisi uchun "bo'sh bino" odatda "barcha binolar" degani
    (umumiy seans, umumiy IP) va u respublika darajasidagi qaror.
    """
    user = request_user(serializer)
    if user is None or not user.is_region_scoped:
        return
    if field in attrs:
        value = attrs[field]
    elif serializer.instance is None:
        value = None
    else:
        return

    if value is None:
        if allow_null:
            return
        raise serializers.ValidationError({field: null_message or message})
    if region_of(value) != user.region_id:
        raise serializers.ValidationError({field: message})


def zone_region(zone) -> int | None:
    return zone.region_id


def region_pk(region) -> int | None:
    return region.pk
