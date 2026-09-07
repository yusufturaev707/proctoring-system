"""Qurilmalar bilan ishlash: ro'yxatdan o'tkazish, holat, kamera sirlari."""

from __future__ import annotations

import logging
import secrets

from django.db import transaction
from django.utils import timezone

from apps.common.utils.crypto import decrypt, encrypt
from apps.devices.models import Camera, Computer, DeviceToken

logger = logging.getLogger(__name__)


@transaction.atomic
def register_device(
    *,
    computer: Computer,
    hardware_fingerprint: str = "",
    app_version: str = "",
    app_hash: str = "",
    reported_public_ip: str | None = None,
    auto_activate: bool = False,
) -> DeviceToken:
    """
    Kompyuter uchun qurilma identifikatorini yaratadi.

    Sir qaytarilmaydi — `device_id` kredensial emas. Client so'rovlarini
    xodim JWT'si himoyalaydi, `device_id` esa faqat "qaysi mashina"
    degan savolga javob beradi.

    `auto_activate=False` (standart): qurilma admin tasdig'ini kutadi.
    Bu "kimdir uydan client o'rnatdi" stsenariysini yopadi — tasdiqlanmagan
    qurilma bilan hech qanday so'rov qabul qilinmaydi.
    """
    device = DeviceToken.objects.create(
        computer=computer,
        device_id=f"dev_{secrets.token_hex(16)}",
        hardware_fingerprint=hardware_fingerprint[:128],
        app_version=app_version[:32],
        app_hash=app_hash[:64],
        reported_public_ip=reported_public_ip or None,
        status=DeviceToken.Status.ACTIVE if auto_activate else DeviceToken.Status.PENDING,
    )
    logger.info("Qurilma ro'yxatdan o'tdi: %s (pc=%s)", device.device_id, computer.pk)
    return device


@transaction.atomic
def revoke_device(device: DeviceToken, *, reason: str = "") -> DeviceToken:
    device.status = DeviceToken.Status.REVOKED
    device.revoked_at = timezone.now()
    device.revoke_reason = reason[:255]
    device.save(update_fields=["status", "revoked_at", "revoke_reason", "updated_at"])
    return device


def record_handshake(
    device: DeviceToken,
    *,
    ip_address: str | None = None,
    app_version: str = "",
    app_hash: str = "",
    hardware_fingerprint: str = "",
    reported_public_ip: str = "",
) -> list[dict]:
    """
    Handshake izini yozadi va client nusxasining butunligini tekshiradi.

    Yozish bitta `update()` bilan (`save()` emas): bu `SELECT` ni
    o'tkazib yuboradi va faqat o'zgargan ustunlarni tegadi.

    Anomaliyalar RO'YXAT sifatida qaytariladi — ular bilan nima qilish
    (audit izi, ogohlantirish) chaqiruvchining ishi. Bu yerdan
    `ProctoringEvent` yozib bo'lmaydi: handshake paytida sessiya hali
    yo'q, `ProctoringEvent.session` esa majburiy maydon.
    """
    app_version = (app_version or "")[:32]
    app_hash = (app_hash or "")[:64]
    hardware_fingerprint = (hardware_fingerprint or "")[:128]

    anomalies: list[dict] = []
    updates: dict = {
        "last_used_at": timezone.now(),
        "last_ip": ip_address or device.last_ip,
    }
    # Client aytgan tashqi manzil - har handshake'da yangilanadi:
    # bino rezerv kanalga o'tsa, panelda eski manzil qolib ketmasligi
    # kerak. Ishonchsiz qiymat, faqat diagnostika uchun.
    if reported_public_ip and reported_public_ip != device.reported_public_ip:
        updates["reported_public_ip"] = reported_public_ip

    # Versiya anomaliya EMAS — client yangilanishi normal holat. Lekin u
    # faqat ro'yxatdan o'tishda yozilsa, "qaysi bino eski build'da"
    # degan savolga javob bera olmaydi, shuning uchun yangilanadi.
    if app_version and app_version != device.app_version:
        updates["app_version"] = app_version

    if app_hash:
        if not device.app_hash:
            # Birinchi handshake — etalon shu yerda qayd etiladi.
            updates["app_hash"] = app_hash
        elif app_hash != device.app_hash:
            anomalies.append(
                {
                    "kind": "app_hash_changed",
                    "expected": device.app_hash[:12],
                    "received": app_hash[:12],
                }
            )

    if hardware_fingerprint:
        if not device.hardware_fingerprint:
            updates["hardware_fingerprint"] = hardware_fingerprint
        elif hardware_fingerprint != device.hardware_fingerprint:
            # `device_id` kredensial emas, ya'ni uni boshqa mashinaga
            # ko'chirib qo'yish texnik jihatdan mumkin. Apparat izi —
            # buni ko'rsatadigan yagona signal.
            anomalies.append(
                {
                    "kind": "fingerprint_changed",
                    "expected": device.hardware_fingerprint[:16],
                    "received": hardware_fingerprint[:16],
                }
            )

        # Bitta apparat ostida bir nechta bekor qilinmagan qurilma —
        # client klonlangan yoki bitta mashina o'zini bir necha kompyuter
        # deb ko'rsatyapti. `hardware_fingerprint` indekslangan, so'rov
        # esa handshake'da bir marta ketadi.
        shared = list(
            DeviceToken.objects.filter(hardware_fingerprint=hardware_fingerprint)
            .exclude(pk=device.pk)
            .exclude(status=DeviceToken.Status.REVOKED)
            .values_list("device_id", flat=True)[:5]
        )
        if shared:
            anomalies.append({"kind": "fingerprint_shared", "others": shared})

    DeviceToken.objects.filter(pk=device.pk).update(**updates)

    if anomalies:
        logger.warning(
            "Client anomaliyasi: device=%s %s",
            device.device_id,
            [item["kind"] for item in anomalies],
        )
    return anomalies


def resolve_zone_by_public_ip(public_ip: str):
    """
    Binoni tashqi (NAT) IP bo'yicha aniqlaydi.

    Ma'lumot manbai - `controls.AllowedPublicIp`. Alohida `Zone.public_ip`
    maydoni ATAYLAB kiritilmagan: u ikkinchi haqiqat manbasi bo'lar va
    ikkalasi zid kelganda qaysi biri ustunligi noaniq qolardi. Bir zonaga
    bir nechta tashqi IP biriktirish ham shu jadval orqali ishlaydi
    (rezerv kanal).

    `zone=NULL` yozuv - "barcha binolar uchun ruxsat etilgan" degani, u
    binoni ANIQLAMAYDI, shuning uchun bunday qatorlar hisobga olinmaydi.
    """
    if not public_ip:
        return None

    from apps.controls.models import AllowedPublicIp

    row = (
        AllowedPublicIp.objects.select_related("zone", "zone__region")
        .filter(ip_address=public_ip, is_active=True, zone__isnull=False)
        .first()
    )
    if row is None or row.zone.deleted_at is not None or not row.zone.is_active:
        return None
    return row.zone


def resolve_computer(
    *,
    mac_address: str = "",
    ip_address: str = "",
    inventory_code: str = "",
    zone=None,
):
    """
    Client yuborgan ma'lumot bo'yicha kompyuterni topadi.

    Belgilar ISHONCHLILIK tartibida sinaladi:

      1. MAC manzil - ASOSIY belgi. Global unikal
         (`unique_computer_mac`), apparatga bog'langan va DHCP'da
         o'zgarmaydi.
      2. Inventar kodi - global unikal, lekin uni client bilishi shart
         emas (ixtiyoriy `.env` qiymati).
      3. LAN IP + BINO - oxirgi chora. LAN IP faqat bino ichida unikal
         (`unique_computer_zone_ip`): turli binolarda `192.168.1.10`
         normal holat. Shuning uchun bino noma'lum bo'lsa, IP bo'yicha
         qidiruv UMUMAN qilinmaydi - aks holda client jimgina BOSHQA
         binoga biriktirilib, sessiya noto'g'ri hududda hisoblanardi.
    """
    from apps.common.utils.validators import normalize_mac

    queryset = Computer.objects.select_related("zone", "zone__region").filter(
        deleted_at__isnull=True, is_active=True
    )

    normalized = normalize_mac(mac_address)
    if normalized:
        computer = queryset.filter(mac_address=normalized).first()
        if computer:
            return computer

    if inventory_code:
        computer = queryset.filter(inventory_code=inventory_code.strip()).first()
        if computer:
            return computer

    if ip_address and zone is not None:
        return queryset.filter(zone=zone, ip_address=ip_address).first()
    return None


@transaction.atomic
def auto_create_computer(*, zone, mac_address: str, ip_address: str, inventory_code: str = ""):
    """
    Ro'yxatda yo'q mashinani avtomatik inventarizatsiya qiladi.

    FAQAT `AUTO_REGISTER_COMPUTERS` yoqilganda va bino tashqi IP orqali
    ANIQLANGANDA chaqiriladi. Xavfsizlik pasaymaydi, chunki uch qavat
    to'siq joyida qoladi: so'rov ro'yxatga olingan tashqi IP dan kelishi
    kerak, endpoint throttled, va yaratilgan qurilma baribir `PENDING`
    bo'lib qoladi.

    Inventar kodi MAC dan hosil qilinadi - takroriy so'rov yangi qator
    yaratmasligi uchun (`resolve_computer` uni MAC bo'yicha topadi).
    """
    from apps.common.utils.validators import normalize_mac

    normalized = normalize_mac(mac_address)
    if zone is None or not normalized:
        return None

    code = (inventory_code or "").strip() or "AUTO-{}".format(normalized.replace(":", "")[-6:])

    # `unique_computer_zone_ip` - bino ichida IP band bo'lsa, yangi qator
    # yaratib bo'lmaydi. Bu odatda eskirgan yozuv (DHCP manzilni boshqa
    # mashinaga bergan) va uni administrator hal qilishi kerak.
    if ip_address and Computer.objects.filter(
        deleted_at__isnull=True, zone=zone, ip_address=ip_address
    ).exists():
        logger.warning(
            "Avtomatik inventarizatsiya to'xtatildi: %s binosida %s IP band",
            zone, ip_address,
        )
        return None

    if Computer.objects.filter(deleted_at__isnull=True, inventory_code=code).exists():
        logger.warning("Avtomatik inventarizatsiya: %s kodi allaqachon band", code)
        return None

    computer = Computer.objects.create(
        zone=zone,
        inventory_code=code,
        ip_address=ip_address or "0.0.0.0",
        mac_address=normalized,
        is_active=True,
    )
    logger.info(
        "Kompyuter avtomatik ro'yxatga olindi: %s (%s, %s)",
        code, normalized, zone,
    )
    return computer


def mark_online(computer: Computer, *, in_exam: bool = False) -> None:
    status = Computer.Status.IN_EXAM if in_exam else Computer.Status.ONLINE
    Computer.objects.filter(pk=computer.pk).update(
        status=status, last_seen_at=timezone.now()
    )


# --------------------------------------------------------------------------
# Kamera sirlari
# --------------------------------------------------------------------------
def set_camera_password(camera: Camera, raw_password: str) -> None:
    """
    RTSP paroli shifrlanadi.

    Eski modelda u `CharField` da ochiq yotardi — DB o'qilsa, barcha
    kameralarga to'liq kirish ochilardi.
    """
    camera.password_encrypted = encrypt(raw_password) or ""


def get_camera_password(camera: Camera) -> str:
    return decrypt(camera.password_encrypted) or ""


def build_rtsp_url(camera: Camera) -> str:
    """
    To'liq RTSP URL. Faqat serverda ishlatiladi va API orqali QAYTARILMAYDI —
    aks holda parol React DevTools'da ko'rinadi.
    """
    password = get_camera_password(camera)
    credentials = f"{camera.login}:{password}@" if camera.login else ""
    return f"rtsp://{credentials}{camera.ip_address}{camera.rtsp_path}"
