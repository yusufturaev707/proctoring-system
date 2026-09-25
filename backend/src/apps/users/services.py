"""Foydalanuvchi bilan bog'liq biznes logika."""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.common.utils.vectors import normalize
from apps.users.models import FaceProfile, User

logger = logging.getLogger(__name__)


@transaction.atomic
def create_user(*, username: str, password: str, **fields) -> User:
    user = User.objects.create_user(username=username, password=password, **fields)
    logger.info("Foydalanuvchi yaratildi: %s", user.username)
    return user


@transaction.atomic
def set_password(user: User, raw_password: str) -> User:
    user.set_password(raw_password)
    user.save(update_fields=["password", "updated_at"])
    return user


def record_login(user: User, ip_address: str | None) -> None:
    """
    Login vaqtini yozadi.

    `update()` — `save()` emas: signal va to'liq UPDATE keraksiz.
    `SIMPLE_JWT.UPDATE_LAST_LOGIN` ham shu sababdan o'chirilgan.
    """
    User.objects.filter(pk=user.pk).update(
        last_login_at=timezone.now(), last_login_ip=ip_address
    )


@transaction.atomic
def upsert_face_profile(
    *, user: User, embedding: list[float] | None, photo_key: str = "", model_name: str = ""
) -> FaceProfile:
    """Xodimning yuz profilini saqlaydi (vektor normalizatsiya qilinadi)."""
    defaults = {"photo_key": photo_key, "embedding_model": model_name, "is_active": True}
    if embedding:
        defaults["embedding"] = normalize(embedding)

    profile, _ = FaceProfile.objects.update_or_create(user=user, defaults=defaults)
    return profile


DEFAULT_PERMISSIONS: list[tuple[str, str, str]] = [
    # (code, name, group)
    ("dashboard.view", "Dashboard ko'rish", "dashboard"),
    ("sessions.view", "Sessiyalarni ko'rish", "sessions"),
    ("sessions.warn", "Ogohlantirish yuborish", "sessions"),
    ("sessions.terminate", "Sessiyani chetlashtirish", "sessions"),
    ("sessions.export", "Sessiyalarni eksport qilish", "sessions"),
    ("technical.view", "Texnik muammolarni ko'rish", "technical"),
    ("technical.resolve", "Texnik muammoga qaror", "technical"),
    ("users.view", "Foydalanuvchilarni ko'rish", "users"),
    ("users.manage", "Foydalanuvchilarni boshqarish", "users"),
    ("devices.view", "Qurilmalarni ko'rish", "devices"),
    ("devices.manage", "Qurilmalarni boshqarish", "devices"),
    ("regions.view", "Hududlarni ko'rish", "regions"),
    ("regions.manage", "Hududlarni boshqarish", "regions"),
    ("exams.view", "Imtihonlarni ko'rish", "exams"),
    ("exams.manage", "Imtihonlarni boshqarish", "exams"),
    # Kompyuter broni — imtihon SOZLAMASIDAN alohida ruxsat. Bronni
    # binodagi administrator yoki tashqi taqsimlash tizimi (JWT bilan)
    # yuritadi; ularga platforma kredensiali va imtihon vaqtini
    # o'zgartirish huquqi (`exams.manage`) kerak emas.
    ("bookings.view", "Kompyuter bronlarini ko'rish", "exams"),
    ("bookings.manage", "Kompyuter bronlarini boshqarish", "exams"),
    ("controls.view", "Sozlamalarni ko'rish", "controls"),
    ("controls.manage", "Sozlamalarni boshqarish", "controls"),
    # Tarmoq chegarasi — client siyosatidan ALOHIDA ruxsat.
    #
    # `AllowedPublicIp` "client qaysi tarmoqdan ulana oladi" degan
    # savolni hal qiladi va qurilma ro'yxatdan o'tishda binoni
    # aniqlaydi. Bu FaceID chegarasi yoki taqiqlangan obyektlar
    # ro'yxatidan boshqa turdagi qaror: bitta noto'g'ri yozuv butun
    # markazni tizimdan uzib qo'yadi.
    ("controls.ip_view", "Ruxsat etilgan IP'larni ko'rish", "controls"),
    ("controls.ip_manage", "Ruxsat etilgan IP'larni boshqarish", "controls"),
    # Chiqish paroli — yana bir ALOHIDA ruxsat.
    #
    # Bu parol kiosk qulfini ochadi, ya'ni uni bilgan odam imtihon
    # o'rtasida dasturni yopa oladi. "Sozlamalarni boshqarish" bilan
    # bitta ruxsatga qo'shib yuborilsa, YOLO modelini almashtirish
    # huquqi bilan birga kiosk kalitini ham berib qo'yardik.
    ("controls.exit_password_view", "Chiqish parollarini ko'rish", "controls"),
    ("controls.exit_password_manage", "Chiqish parollarini boshqarish", "controls"),
    # AI kuzatuv siyosati - yana bir ALOHIDA ruxsat.
    #
    # Bu yerdagi qiymatlar chetlashtirish statistikasiga bevosita
    # ta'sir qiladi: xavf chegarasini pasaytirish ko'proq talabgorni
    # "yuqori xavf" ro'yxatiga chiqaradi, dalil to'plashni o'chirish
    # esa keyinchalik hech narsani tekshirib bo'lmaydigan qiladi.
    # Skrinshot oralig'ini o'zgartirish bilan bir xil ruxsatga
    # qo'shib bo'lmaydi.
    ("controls.proctoring_view", "Kuzatuv siyosatini ko'rish", "controls"),
    ("controls.proctoring_manage", "Kuzatuv siyosatini boshqarish", "controls"),
    # Dalil (kadr va video klip) - talabgorning tasviri.
    #
    # `sessions.view` dan ALOHIDA: sessiyalar ro'yxatini ko'rish
    # statistik ish, talabgorning videosini ochish esa shaxsiy
    # ma'lumotga kirish. Ikkinchisi tor doiraga beriladi va har bir
    # ochish audit izida qoladi.
    ("evidence.view", "Dalillarni ko'rish", "sessions"),
    ("audit.view", "Audit yozuvlarini ko'rish", "audit"),
    # Desktop client (operator ish o'rni)
    ("client.operate", "Desktop client'da ishlash", "client"),
    ("client.identity", "Talabgor shaxsini tasdiqlash", "client"),
    ("client.exit", "Desktop client'dan chiqish", "client"),
]


def sync_default_permissions() -> int:
    """`manage.py seed_permissions` uchun."""
    from apps.users.models import Permission

    created = 0
    for code, name, group in DEFAULT_PERMISSIONS:
        _, was_created = Permission.objects.update_or_create(
            code=code, defaults={"name": name, "group": group}
        )
        created += int(was_created)
    return created
