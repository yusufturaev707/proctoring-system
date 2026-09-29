"""Qurilmalar bilan ishlash: ro'yxatdan o'tkazish, holat, kamera sirlari."""

from __future__ import annotations

import logging
import secrets
from urllib.parse import quote

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.common.utils.crypto import decrypt, encrypt
from apps.common.utils.validators import normalize_mac, normalize_machine_uuid
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
def approve_device(device: DeviceToken) -> DeviceToken:
    """
    Qurilmani faollashtiradi — kutayotganini ham, bloklanganini ham.

    Blok izi TOZALANADI: ilgari `approve` faqat holatni o'zgartirardi
    va blokdan chiqarilgan qurilma panelda "Faol" bo'lib turib, eski
    blok sababini ko'rsatardi. Blok tarixi yo'qolmaydi — u audit
    jurnalida (`device_revoke` + keyingi `update`).
    """
    device.status = DeviceToken.Status.ACTIVE
    device.revoked_at = None
    device.revoke_reason = ""
    device.save(update_fields=["status", "revoked_at", "revoke_reason", "updated_at"])
    return device


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
    reported_lan_ip: str = "",
    reported_machine_uuid: str = "",
    reported_mac: str = "",
    gpu_name: str = "",
    performance_profile: str = "",
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
    gpu_name = (gpu_name or "")[:120]
    performance_profile = (performance_profile or "")[:8]

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
    if reported_lan_ip and reported_lan_ip != device.reported_lan_ip:
        updates["reported_lan_ip"] = reported_lan_ip
    reported_machine_uuid = normalize_machine_uuid(reported_machine_uuid)
    if reported_machine_uuid and reported_machine_uuid != device.reported_machine_uuid:
        updates["reported_machine_uuid"] = reported_machine_uuid
    normalized_mac = normalize_mac(reported_mac) or ""
    if normalized_mac and normalized_mac != device.reported_mac:
        updates["reported_mac"] = normalized_mac

    # Versiya anomaliya EMAS — client yangilanishi normal holat. Lekin u
    # faqat ro'yxatdan o'tishda yozilsa, "qaysi bino eski build'da"
    # degan savolga javob bera olmaydi, shuning uchun yangilanadi.
    if app_version and app_version != device.app_version:
        updates["app_version"] = app_version

    # Apparat imkoniyati ANOMALIYA EMAS, lekin uni bilish shart:
    # administrator qaysi mashinalar AI kuzatuvni ko'tara olishini
    # imtihon KUNIDAN oldin ko'rishi kerak. Aks holda "nega bu
    # binoda hech narsa aniqlanmadi?" degan savolga javob faqat
    # client log'idan topilardi.
    #
    # Profil har handshake'da yangilanadi: GPU drayveri yangilansa
    # yoki `onnxruntime` CPU build'iga almashsa, qiymat o'zgaradi va
    # eski qiymat panelda yolg'on va'da bo'lib qolardi.
    if gpu_name and gpu_name != device.gpu_name:
        updates["gpu_name"] = gpu_name
    if performance_profile and performance_profile != device.performance_profile:
        updates["performance_profile"] = performance_profile

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
        elif is_fingerprint_upgrade(device.hardware_fingerprint, hardware_fingerprint, reported_mac):
            # Iz formati MAC'dan Machine UUID'ga o'tdi. Eski izdagi MAC
            # client aytgani bilan mos - bu O'SHA mashina, etalon JIMGINA
            # yangilanadi. Aks holda yangilangan har client eski etalonga
            # qarshi har handshake'da `fingerprint_changed` berardi.
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


#: Apparat izining YANGI formati: `muid:<Machine UUID>` (client
#: `system_info.hardware_fingerprint`). Eskisi `MAC|host|OS|arch` edi va
#: MAC almashganda (tarmoq kartasi, adapter tartibi) yoki kompyuter nomi
#: o'zgarganda soxta `fingerprint_changed` anomaliyasi berardi.
FINGERPRINT_UUID_PREFIX = "muid:"


def _legacy_fingerprint_mac(fingerprint: str) -> str:
    """Eski formatdagi izning MAC qismi (`AA:BB:..|host|...`)."""
    if not fingerprint or fingerprint.startswith(FINGERPRINT_UUID_PREFIX):
        return ""
    return normalize_mac(fingerprint.split("|", 1)[0]) or ""


def is_fingerprint_upgrade(stored: str, received: str, reported_mac: str) -> bool:
    """
    Eski (MAC) izdan yangi (UUID) izga O'SHA mashinada o'tishmi.

    Isbot - eski izdagi MAC client hozir aytgan MAC bilan bir xil. MAC
    ham mos kelmasa bu ko'chirilgan `device_id` bo'lishi mumkin va u
    avvalgidek anomaliya bo'lib qoladi.
    """
    if not (received or "").startswith(FINGERPRINT_UUID_PREFIX):
        return False
    legacy_mac = _legacy_fingerprint_mac(stored)
    return bool(legacy_mac) and legacy_mac == (normalize_mac(reported_mac) or "")


def fingerprint_matches(stored: str, received: str, reported_mac: str = "") -> bool:
    """So'rov etalon izdagi mashinadan kelyaptimi (format o'tishi hisobga olingan)."""
    if not stored or not received:
        return False
    return stored == received or is_fingerprint_upgrade(stored, received, reported_mac)


def resolve_computer(
    *,
    machine_uuid: str = "",
    mac_address: str = "",
    ip_address: str = "",
    inventory_code: str = "",
    zone=None,
):
    """
    Client yuborgan ma'lumot bo'yicha kompyuterni topadi.

    Belgilar ISHONCHLILIK tartibida sinaladi:

      1. Machine UUID - ASOSIY belgi. Ona plataga bog'langan, tizim
         bo'ylab unikal (`unique_computer_machine_uuid`), tarmoq
         kartasi almashsa ham, OS qayta o'rnatilsa ham o'zgarmaydi.
      2. MAC - UUID'si hali yozilmagan (eski) yozuvlar va eski
         client'lar uchun.
      3. Inventar kodi - global unikal, lekin uni client bilishi shart
         emas (ixtiyoriy `.env` qiymati).
      4. LAN IP + BINO - oxirgi chora. LAN IP faqat bino ichida unikal
         (`unique_computer_zone_ip`): bino noma'lum bo'lsa IP bo'yicha
         qidiruv UMUMAN qilinmaydi - aks holda client jimgina BOSHQA
         binoga biriktirilib, sessiya noto'g'ri hududda hisoblanardi.
    """
    queryset = Computer.objects.select_related("zone", "zone__region").filter(
        deleted_at__isnull=True, is_active=True
    )

    uuid_value = normalize_machine_uuid(machine_uuid)
    if uuid_value:
        computer = queryset.filter(machine_uuid=uuid_value).first()
        if computer:
            return computer

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


def auto_inventory_code(*, machine_uuid: str = "", mac_address: str = "") -> str:
    """
    Inventar kodi berilmaganda: `AUTO-<UUID hex>` (MAC bo'lmasa ham unikal).

    UUID TO'LIQ olinadi (32 belgi): qisqartirilgan qism bir ishlab
    chiqaruvchining ketma-ket platalarida to'qnashishi mumkin, kod esa
    tizim bo'ylab unikal (`unique_computer_inventory_code`).
    """
    uuid_value = normalize_machine_uuid(machine_uuid)
    if uuid_value:
        return "AUTO-" + uuid_value.replace("-", "")
    mac = normalize_mac(mac_address)
    return "AUTO-" + mac.replace(":", "") if mac else ""


@transaction.atomic
def auto_create_computer(
    *, zone, machine_uuid: str = "", mac_address: str = "", ip_address: str = "",
    inventory_code: str = "",
):
    """
    Ro'yxatda yo'q mashinani avtomatik inventarizatsiya qiladi.

    FAQAT `AUTO_REGISTER_COMPUTERS` yoqilganda va bino tashqi IP orqali
    ANIQLANGANDA chaqiriladi. Xavfsizlik pasaymaydi, chunki uch qavat
    to'siq joyida qoladi: so'rov ro'yxatga olingan tashqi IP dan kelishi
    kerak, endpoint throttled, va yaratilgan qurilma baribir `PENDING`
    bo'lib qoladi.

    Takroriy so'rov yangi qator yaratmaydi: `resolve_computer` uni UUID
    (eski client'da MAC) bo'yicha topadi.
    """
    uuid_value = normalize_machine_uuid(machine_uuid)
    mac = normalize_mac(mac_address) or ""
    if zone is None or not (uuid_value or mac):
        return None

    code = (inventory_code or "").strip() or auto_inventory_code(
        machine_uuid=uuid_value, mac_address=mac
    )

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
    # MAC boshqa (UUID'li) yozuvda band bo'lsa - MAC'siz yaratiladi: u
    # endi ixtiyoriy belgi va eskirgan MAC yangi mashinani to'smasligi kerak.
    if mac and Computer.objects.alive().filter(mac_address=mac).exists():
        mac = ""

    computer = Computer.objects.create(
        zone=zone,
        inventory_code=code,
        ip_address=ip_address or None,
        machine_uuid=uuid_value or None,
        mac_address=mac,
        is_active=True,
    )
    logger.info(
        "Kompyuter avtomatik ro'yxatga olindi: %s (%s, %s)",
        code, uuid_value or mac, zone,
    )
    return computer


# --------------------------------------------------------------------------
# Mashina tekshiruvi (Machine UUID)
# --------------------------------------------------------------------------
#
# NIMA UCHUN BU ALOHIDA TEKSHIRUV. `X-Device-ID` mashinani EMAS,
# client NUSXASINI belgilaydi: u diskda oddiy fayl bo'lib yotadi va
# mashina obrazi ko'chirilganda (imtihon markazlarida odatiy amaliyot)
# u ham ko'chadi. Natijada o'nlab mashina bitta `device_id` bilan
# ishlaydi va sessiyalarning hammasi bitta kompyuterga yozilardi.
#
# Javob ona platadagi Machine UUID'da va uni administrator KIRITADI
# (`Computer.machine_uuid`, panel yoki Excel). Ilgari bu MAC edi va u
# amalda o'zgaradi (tarmoq kartasi, USB adapter, marshrut boshqa
# adapterga o'tishi) - ishlab turgan mashina "ro'yxatda yo'q" bo'lib
# qolardi.
#
# TEKSHIRUV SOLISHTIRADI. Bitta istisno - UUID'NI BIR MARTA BOG'LASH:
# kompyuter yozuvida UUID hali YO'Q (UUID'dan oldingi yozuv) va client
# aytgan MAC administrator kiritgan MAC bilan AYNAN mos bo'lsa, UUID
# yozuvga yoziladi. Bu ilgari MAC bo'yicha "ok" bo'ladigan mashinaning
# O'ZI, ya'ni ishonch darajasi o'zgarmaydi - faqat mavjud yuzlab
# mashinaga qo'lda UUID yozib chiqish kerak bo'lmaydi. UUID bor yozuvga
# client HECH QACHON tegmaydi: aks holda har qanday mashina o'zini
# "ro'yxatga olingan" holga keltirib olardi.

#: Tekshiruv natijalari. Client shu kodlarga qarab qaror qabul
#: qiladi, matn esa serverdan keladi - chegara ham, sabab ham
#: bitta joyda (`camera_check.py` dagi bilan bir xil qoida).
MACHINE_OK = "ok"
MACHINE_UNKNOWN = "unknown"
MACHINE_NO_COMPUTER = "no_computer"
MACHINE_NOT_FOUND = "not_found"
MACHINE_MISMATCH = "mismatch"
MACHINE_INACTIVE = "inactive"
MACHINE_MAC_MISMATCH = "mac_mismatch"


# MAC - QAT'IY REJIMDA IKKINCHI BELGI (`REQUIRE_MACHINE_MAC`). Qoida
# shu ikki funksiyada: handshake (`verify_machine`) ham, JSHSHIR
# tekshiruvi (`exams.bookings.ensure_machine_mac`) ham shularni
# chaqiradi - ikki joyda yashagan qoida albatta ajralib ketadi va
# operator bir ekranda "o'tdi", keyingisida "mos emas" ko'rardi.
def mac_check_required() -> bool:
    return bool(settings.PROCTORING.get("REQUIRE_MACHINE_MAC"))


def mac_matches(computer: Computer, reported_mac: str) -> bool:
    """
    Client aytgan MAC kompyuter yozuvidagiga mos keladimi.

    Yozuvda MAC YO'Q - `True` (faqat UUID): MAC'ni administrator
    kiritadi, client hech qachon yozmaydi; aks holda birinchi kelgan
    mashina o'z MAC'ini "etalon" qilib qo'yardi.

    Client MAC yubormagan - `False`: aks holda qat'iy rejimni maydonni
    bo'sh yuborib chetlab o'tish mumkin bo'lardi (`unknown` ni to'siq
    qilgan sabab bilan bir xil).
    """
    expected = normalize_mac(computer.mac_address)
    if not expected:
        return True
    return normalize_mac(reported_mac) == expected


def mac_mismatch_message(computer: Computer, reported_mac: str) -> str:
    # Ikkala qiymat BIR XIL shaklda (kichik harf, ikki nuqta): yozuvda
    # `2C-F0-...`, mashinada `2c:f0:...` turgan bo'lsa, administrator
    # farqni format farqi deb o'ylab qolardi.
    def shown(value):
        mac = normalize_mac(value)
        return mac.lower() if mac else ""

    return (
        "«{label}» kompyuterining MAC manzili yozuvdagiga mos kelmadi: "
        "yozuvda {expected}, mashinada {actual}. Tarmoq kartasi "
        "almashtirilgan bo'lsa administrator yozuvni yangilashi kerak; "
        "mashinada bir nechta adapter yoqilgan bo'lsa, ortiqchasini "
        "(Wi-Fi) o'chiring.".format(
            label=computer.label,
            expected=shown(computer.mac_address),
            actual=shown(reported_mac) or "MAC aniqlanmadi",
        )
    )


def bind_machine_uuid(computer: Computer, value: str) -> bool:
    """
    UUID'si yo'q kompyuterga UUID yozadi. `False` - yozilmadi.

    Faqat BO'SH maydonga (`machine_uuid IS NULL` sharti `UPDATE` ichida -
    parallel handshake'lar ikki xil qiymat yoza olmaydi) va UUID boshqa
    tirik kompyuterda band bo'lmasa (unikal cheklov poygada ham ushlaydi).
    """
    value = normalize_machine_uuid(value)
    if not value or computer.machine_uuid:
        return False
    if Computer.objects.alive().filter(machine_uuid=value).exclude(pk=computer.pk).exists():
        return False
    try:
        with transaction.atomic():
            updated = Computer.objects.filter(
                pk=computer.pk, machine_uuid__isnull=True
            ).update(machine_uuid=value, updated_at=timezone.now())
    except IntegrityError:
        return False
    if updated:
        computer.machine_uuid = value
        logger.info("Machine UUID bog'landi: %s -> %s", computer.label, value)
    return bool(updated)


def _matched(result: dict, computer: Computer, *, check_mac: bool = False) -> dict:
    """
    Mashina - qurilma biriktirilgan kompyuterning O'ZI.

    `check_mac` faqat UUID bo'yicha moslikda: bog'lash va eski client
    yo'lida MAC allaqachon solishtirilgan. "Hisobdan chiqarilgan" MAC'dan
    OLDIN - u yakuniy qaror, MAC'ni tuzatish esa foyda bermaydi.
    """
    result["computer_code"] = computer.inventory_code
    if not computer.is_active:
        result["status"] = MACHINE_INACTIVE
        result["message"] = (
            "«{}» kompyuteri hisobdan chiqarilgan — imtihon o'tkazib "
            "bo'lmaydi.".format(computer.label)
        )
        return result
    if check_mac and mac_check_required() and not mac_matches(computer, result["mac_address"]):
        result["status"] = MACHINE_MAC_MISMATCH
        result["message"] = mac_mismatch_message(computer, result["mac_address"])
        return result
    result["status"] = MACHINE_OK
    return result


def verify_machine(
    device: DeviceToken | None, *, machine_uuid: str = "", mac_address: str = ""
) -> dict:
    """
    Client ishlab turgan mashina - qurilma biriktirilgan kompyuterning
    O'ZImi va u shu bino ro'yxatidami.

    Asos - Machine UUID. MAC faqat ikki joyda: UUID'ni bir marta
    bog'lash (yuqoridagi izoh) va UUID yubormaydigan ESKI client
    (`basis="mac"`). `REQUIRE_MACHINE_MAC=true` da uchinchisi: UUID mos
    kelgan mashinada MAC ham yozuvdagiga mos bo'lishi shart
    (`mac_matches`, aks holda `mac_mismatch`).

    Qidiruv KO'LAMI - qurilmaning binosi: savol "shu mashina umuman
    bazada bormi?" emas, "AYNAN SHU binoda bormi?". Boshqa binodagi
    kompyuterning jadvali, kameralari va proktori boshqa.

    Javob TAVSIF, qaror emas: `allowed` ni chaqiruvchi
    (`HandshakeView`) sozlama bilan birga hisoblaydi.
    """
    reported_uuid = normalize_machine_uuid(machine_uuid)
    reported_mac = normalize_mac(mac_address) or ""
    computer = device.computer if device is not None else None
    zone = computer.zone if computer is not None else None

    result = {
        "status": MACHINE_UNKNOWN,
        "basis": "uuid" if reported_uuid else "mac",
        "machine_uuid": reported_uuid,
        "expected_uuid": (computer.machine_uuid or "") if computer is not None else "",
        "mac_address": reported_mac,
        "expected_mac": computer.mac_address if computer is not None else "",
        #: UUID shu tekshiruvda kompyuter yozuviga BOG'LANDI (audit uchun).
        "bound": False,
        "zone_name": zone.name if zone is not None else "",
        "region_name": (
            zone.region.name if zone is not None and zone.region_id else ""
        ),
        "computer_code": "",
        #: Xonadagi raqam — client sarlavhada ko'rsatadi.
        "computer_number": computer.number if computer is not None else None,
        "message": "",
    }

    if not reported_uuid and not reported_mac:
        # Tekshiruvni majburiy qilish qarori sozlamada
        # (`REQUIRE_MACHINE_MATCH`) va u yerda "noma'lum" ni qanday
        # hisoblash ham hal qilinadi.
        result["message"] = (
            "Dastur mashinaning Machine UUID'ini aniqlay olmadi — dasturni "
            "yangilang yoki administratorga murojaat qiling."
        )
        return result

    if computer is None:
        result["status"] = MACHINE_NO_COMPUTER
        result["message"] = (
            "Bu qurilma hech qaysi kompyuterga biriktirilmagan — administrator "
            "kompyuterni {} bilan qo'shishi kerak.".format(
                "Machine UUID {}".format(reported_uuid) if reported_uuid
                else "{} MAC manzili".format(reported_mac)
            )
        )
        return result

    if not reported_uuid:
        return _verify_by_mac(result, computer, zone, reported_mac)

    if computer.machine_uuid == reported_uuid:
        return _matched(result, computer, check_mac=True)

    if (
        not computer.machine_uuid
        and reported_mac
        and normalize_mac(computer.mac_address) == reported_mac
        and bind_machine_uuid(computer, reported_uuid)
    ):
        result["bound"] = True
        result["expected_uuid"] = reported_uuid
        return _matched(result, computer)

    # UUID mos kelmadi. Ikki holat bor va operator uchun ular
    # BOSHQA-BOSHQA: mashina shu binoda ro'yxatda yo'q (administrator
    # qo'shadi yoki yozuvni to'g'rilaydi) yoki ro'yxatda bor, lekin
    # qurilma boshqa kompyuterga biriktirilgan (obraz ko'chirilgan -
    # qurilmani qayta biriktirish kerak).
    other = (
        Computer.objects.alive()
        .filter(machine_uuid=reported_uuid, zone_id=zone.pk if zone else None)
        .first()
    )
    if other is not None:
        result["status"] = MACHINE_MISMATCH
        result["computer_code"] = other.inventory_code
        result["message"] = (
            "Qurilma identifikatori «{expected}» kompyuteriga biriktirilgan, "
            "lekin dastur «{actual}» mashinasida ishlayapti. Administrator "
            "qurilmani qayta biriktirishi kerak.".format(
                expected=computer.label, actual=other.label,
            )
        )
        return result

    # Xabar KUTILGAN qiymatni ham aytadi: usiz administrator "men bu
    # mashinani qo'shganman-ku" deb qolardi va qaysi ikki qiymat farq
    # qilayotganini topish uchun bazani qo'lda solishtirardi.
    scope = "«{}» binosida".format(zone.name) if zone is not None else "bazada"
    result["status"] = MACHINE_NOT_FOUND
    if computer.machine_uuid:
        hint = (
            "unda {} yozilgan — administrator yozuvdagi Machine UUID'ni "
            "to'g'rilashi kerak".format(computer.machine_uuid)
        )
    else:
        hint = (
            "unda Machine UUID yo'q va MAC ham mos kelmadi — administrator "
            "kompyuter yozuviga shu UUID'ni kiritishi kerak"
        )
    result["message"] = (
        "Bu mashinaning Machine UUID'i ({uuid}) {scope} ro'yxatdagi hech bir "
        "kompyuterga mos kelmadi. Qurilma «{label}» kompyuteriga "
        "biriktirilgan, {hint}.".format(
            uuid=reported_uuid, scope=scope, label=computer.label, hint=hint,
        )
    )
    return result


def _verify_by_mac(result: dict, computer: Computer, zone, reported: str) -> dict:
    """
    ESKI client (UUID yubormaydi) - MAC bo'yicha, avvalgi qoida.

    Yangilangan client'da bu yo'l ishlamaydi; u faqat o'rnatishlar
    bosqichma-bosqich yangilanguncha eski nusxalarni to'xtatmaslik uchun.
    """
    if normalize_mac(computer.mac_address) == reported:
        return _matched(result, computer)

    other = (
        Computer.objects.alive()
        .filter(mac_address__iexact=reported, zone_id=zone.pk if zone else None)
        .first()
    )
    if other is not None:
        result["status"] = MACHINE_MISMATCH
        result["computer_code"] = other.inventory_code
        result["message"] = (
            "Qurilma identifikatori «{expected}» kompyuteriga biriktirilgan, "
            "lekin dastur «{actual}» mashinasida ishlayapti ({mac}). "
            "Administrator qurilmani qayta biriktirishi kerak.".format(
                expected=computer.label, actual=other.label, mac=reported,
            )
        )
        return result

    scope = "«{}» binosida".format(zone.name) if zone is not None else "bazada"
    result["status"] = MACHINE_NOT_FOUND
    result["message"] = (
        "Bu mashinaning MAC manzili ({mac}) {scope} ro'yxatdagi hech bir "
        "kompyuterga mos kelmadi. Qurilma «{code}» kompyuteriga biriktirilgan "
        "va unda {expected} yozilgan. Dasturni yangilang — yangi nusxa "
        "mashinani Machine UUID bo'yicha aniqlaydi.".format(
            mac=reported,
            scope=scope,
            code=computer.inventory_code,
            expected=computer.mac_address or "MAC ko'rsatilmagan",
        )
    )
    return result


def mark_online(
    computer: Computer, *, in_exam: bool = False, info_pc: dict | None = None
) -> None:
    """
    Kompyuterni "onlayn" deb belgilaydi.

    `info_pc` handshake'da keladi va SHU YERDA yoziladi, alohida
    `update()` bilan emas: kompyuter qatori handshake'da baribir
    yangilanadi va ikkinchi so'rov bekorga bo'lardi. Bo'sh kelsa
    maydonga tegilmaydi — eski client'lar uni yubormaydi va ular
    mavjud tavsifni o'chirib yuborishi kerak emas.
    """
    updates: dict = {
        "status": Computer.Status.IN_EXAM if in_exam else Computer.Status.ONLINE,
        "last_seen_at": timezone.now(),
    }
    if info_pc:
        updates["info_pc"] = info_pc
    Computer.objects.filter(pk=computer.pk).update(**updates)


# --------------------------------------------------------------------------
# Client dasturining "tirikligi" (presence)
# --------------------------------------------------------------------------
#: Client signalining oralig'i (soniya) - clientga SERVER aytadi
#: (`config.network.presence_interval`, `controls.services._presence_interval`).
#:
#: Ilgari u har mashinaning `.env` ida edi (`PRESENCE_PING_MS`) va
#: pastdagi TTL bilan bog'liqligi hech qayerda tekshirilmasdi. Endi
#: ikkala son SHU YERDA yonma-yon va ular orasidagi qoida testda
#: (`controls/tests/test_client_runtime_settings.py`).
PRESENCE_PING_INTERVAL = 45

#: Presence kaliti shuncha yashaydi (soniya).
#:
#: TTL signal oralig'idan kamida IKKI BAROBAR katta: bitta o'tkazib
#: yuborilgan signal (tarmoq sakradi, mashina bir zumda band bo'ldi)
#: mashinani darhol "offline" qilib qo'ymasligi kerak - panelda bu
#: miltillash bo'lib ko'rinardi.
PRESENCE_TTL = 100

#: DB'ga yozish oralig'i (soniya).
#:
#: Presence Redis'da yashaydi, `Computer.last_seen_at` esa panel uchun
#: DB'da kerak (ro'yxatni saralash va filtrlash SQL'da bo'ladi). Har
#: signalda UPDATE qilish 10 000 mashinada 220 yozuv/sekund bo'lardi -
#: "men tirikman" degan xabar uchun juda qimmat. Shuning uchun yozuv
#: daqiqada bir martaga cheklanadi va cheklovchi ham Redis'da
#: (`issue_camera_stream` dagi grant kaliti bilan bir xil naqsh).
PRESENCE_DB_INTERVAL = 60


def _presence_key(device_id: str) -> str:
    return f"dev:online:{device_id}"


def _presence_write_key(device_id: str) -> str:
    return f"dev:online:db:{device_id}"


def touch_presence(device, *, staff=None, in_exam: bool = False) -> None:
    """
    "Client shu mashinada ishlab turibdi" belgisi.

    NIMA UCHUN UMUMAN KERAK. Ilgari `Computer.status` faqat uch
    nuqtada yangilanardi: handshake (login), imtihon boshlanishi va
    yakunlanishi. Oradagi vaqtda hech kim `last_seen_at` ga
    tegmasdi, `refresh_device_status` esa 120 soniyadan keyin
    mashinani OFFLINE deb belgilardi — natijada panelda ishlab
    turgan client ham, imtihon o'rtasidagi mashina ham "offline"
    bo'lib ko'rinardi va butun ustun ma'nosini yo'qotgan edi.

    IKKI QATLAM: Redis (tez, aniq, TTL bilan o'zi so'nadi) va DB
    (panel ro'yxati uchun, daqiqada bir marta). Redis yo'q bo'lsa
    ham DB yo'li ishlaydi — presence diagnostika, imtihonning
    sharti emas.
    """
    if device is None:
        return

    computer = getattr(device, "computer", None)
    write_db = True
    try:
        from apps.common.redis_client import get_redis

        client = get_redis()
        client.set(
            _presence_key(device.device_id),
            "|".join(
                [
                    getattr(staff, "username", "") or "",
                    "exam" if in_exam else "idle",
                    timezone.now().isoformat(),
                ]
            ),
            ex=PRESENCE_TTL,
        )
        # `nx=True` — mavjud kalit uzaytirilmaydi, ya'ni DB yozuvi
        # aynan daqiqada bir marta bo'ladi.
        write_db = bool(
            client.set(
                _presence_write_key(device.device_id),
                "1",
                ex=PRESENCE_DB_INTERVAL,
                nx=True,
            )
        )
    except Exception:
        # Redis yo'q: presence faqat DB orqali ko'rinadi. Yozuvni
        # o'tkazib yuborish "mashina offline" degan yolg'on xabar
        # berardi, shuning uchun bu holatda HAR signalda yoziladi.
        logger.debug("Presence Redis'ga yozilmadi", exc_info=True)

    DeviceToken.objects.filter(pk=device.pk).update(last_used_at=timezone.now())
    if write_db and computer is not None:
        mark_online(computer, in_exam=in_exam)


def presence_map(device_ids) -> dict:
    """
    `device_id -> {"online", "staff", "state", "since"}`.

    BITTA `MGET` bilan: ro'yxat sahifasida 25 ta qurilma bor va har
    biri uchun alohida so'rov yuborish panelni Redis'ga 25 marta
    murojaat qilishga majbur qilardi.

    Redis yo'q bo'lsa BO'SH lug'at qaytadi va panel DB'dagi
    `last_seen_at` ga tushadi — u kechroq, lekin yolg'on emas.
    """
    ids = [str(value) for value in device_ids if value]
    if not ids:
        return {}
    try:
        from apps.common.redis_client import get_redis

        raw = get_redis().mget([_presence_key(value) for value in ids])
    except Exception:
        logger.debug("Presence o'qilmadi", exc_info=True)
        return {}

    result = {}
    for device_id, value in zip(ids, raw):
        if not value:
            continue
        text = value.decode() if isinstance(value, bytes) else str(value)
        parts = text.split("|")
        result[device_id] = {
            "online": True,
            "staff": parts[0] if parts else "",
            "state": parts[1] if len(parts) > 1 else "idle",
            "since": parts[2] if len(parts) > 2 else "",
        }
    return result


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


def build_rtsp_url(camera: Camera, *, with_credentials: bool = True) -> str:
    """
    To'liq RTSP URL.

    ADMIN PANELGA HECH QACHON QAYTARILMAYDI: u yerda parol React
    DevTools va network tab'da ochiq ko'rinardi. Desktop client uchun
    esa alohida, cheklangan yo'l bor - `issue_camera_stream` ga qarang.

    `with_credentials=False` - diagnostika va log uchun: manzil
    ko'rinadi, sir ko'rinmaydi.

    Port va transport ALOHIDA maydonlardan olinadi. Ilgari ikkalasi
    ham qadab qo'yilgan edi (554/TCP) va nostandart portdagi kamera
    umuman ulanmasdi - xato esa client tomonda "oqim ochilmadi" degan
    umumiy xabar bo'lib ko'rinardi.
    """
    credentials = ""
    if with_credentials and camera.login:
        password = get_camera_password(camera)
        # Parolda `@`, `:` yoki `/` bo'lishi mumkin - ular URL'ni
        # buzadi va autentifikatsiya jimgina muvaffaqiyatsiz tugaydi.
        credentials = f"{quote(camera.login, safe='')}:{quote(password, safe='')}@"

    port = camera.port or 554
    path = camera.rtsp_path or "/"
    if not path.startswith("/"):
        path = "/" + path

    url = f"rtsp://{credentials}{camera.ip_address}:{port}{path}"

    # Transport RTSP URL'ning o'zida uzatilmaydi - u client tomonidagi
    # FFmpeg parametri (`rtsp_transport`). Shuning uchun u `camera`
    # obyektidan alohida beriladi va bu yerda faqat URL qaytadi.
    return url


#: Kamera oqimi uchun berilgan ruxsatning yashash muddati (soniya).
#:
#: Bu MUDDAT KREDENSIALNI BEKOR QILMAYDI. Buni ochiq aytish kerak:
#: RTSP paroli kameraning o'zida yashaydi va uni serverdan "muddati
#: tugadi" deb e'lon qilib bo'lmaydi. Muddat ikki narsani beradi:
#:
#:   * client uni RAM'da shuncha vaqt ushlab, keyin tashlashi shart
#:     (dasturiy majburiyat, kafolat emas);
#:   * shu oyna ichida takroriy so'rov YANGI audit yozuvi yaratmaydi,
#:     ya'ni jurnal "har kadrda so'radi" bilan to'lib ketmaydi.
#:
#: HAQIQIY himoya boshqa joyda va u to'rt qatlam:
#:   1. faqat SHU BINODAGI kamera (`cameras_for_computer`);
#:   2. faqat kamera tekshiruvi yoki faol sessiya paytida;
#:   3. har bir berish `AuditLog` da qoladi;
#:   4. ekspluatatsiya qoidasi - kamerada FAQAT O'QISH huquqiga ega
#:      alohida hisob bo'lishi va u davriy almashtirilishi kerak.
#:
#: To'rtinchisi eng muhimi va u kodda emas, ekspluatatsiyada. Agar
#: kameralarda administrator hisobi ishlatilsa, bu endpoint o'sha
#: hisobni har bir imtihon mashinasiga tarqatadi.
CAMERA_STREAM_GRANT_TTL = 15 * 60


def _grant_key(device_id: str, camera_id: int) -> str:
    return f"cam:grant:{device_id}:{camera_id}"


def issue_camera_stream(*, device, camera: Camera, transport: str = "") -> dict:
    """
    Desktop client uchun kamera oqimi ma'lumoti.

    Chaqiruvchi (client view) AVVAL doirani tekshiradi
    (`camera_for_computer`) - bu funksiya "bu kamera shu
    kompyuterga tegishlimi" degan savolga javob bermaydi, u faqat
    ma'lumotni yig'adi.

    Qaytadi: `{url, transport, ttl, is_new}`. `is_new=False` - shu
    oyna ichida allaqachon berilgan, ya'ni audit yozuvi takrorlanmaydi.
    """
    from apps.common.redis_client import get_redis

    is_new = True
    try:
        client = get_redis()
        key = _grant_key(device.device_id, camera.pk)
        # `nx=True` - mavjud kalitni uzaytirmaydi: aks holda har
        # so'rov muddatni cho'zib, oyna hech qachon yopilmasdi.
        is_new = bool(client.set(key, "1", ex=CAMERA_STREAM_GRANT_TTL, nx=True))
    except Exception:
        # Redis yo'q bo'lsa oqim BERILADI, faqat takroriy audit
        # yozuvlari paydo bo'ladi. Teskarisi (kredensialni bermaslik)
        # imtihonni to'xtatardi - kesh nosozligi buni qilmasligi kerak.
        logger.warning("Kamera ruxsatini Redis'da qayd etib bo'lmadi", exc_info=True)

    return {
        "url": build_rtsp_url(camera),
        "transport": transport or camera.transport,
        "ttl": CAMERA_STREAM_GRANT_TTL,
        "is_new": is_new,
    }


def cameras_for_computer(computer) -> list:
    """
    Kompyuter ISHLATA OLADIGAN IP kameralar (bino doirasi).

    ILGARI BU BIRIKTIRISH EDI (`CameraAssignment`): administrator har
    bir kompyuterga qaysi kamera qaysi rolda ishlashini qo'lda
    yozardi. U olib tashlandi va sabab amaliyotda: 500 mashinani
    qo'lda biriktirib chiqish kunlab vaqt oladi, rolni esa client
    tomonda operator ALLAQACHON tanlaydi - u ikkala kadrni ekranda
    ko'rib turibdi, administrator esa jadvalda faqat nomni ko'radi.

    DOIRA QOLDI va u endi BINO: kredensial faqat kompyuter turgan
    binoning kameralari uchun beriladi. Boshqa binoning kamerasi
    boshqa jadval va boshqa proktorga tegishli, ya'ni bu yerda unga
    ehtiyoj yo'q. "Hamma kameralar" doirasi esa bitta buzilgan
    mashinadan butun tarmoqni ochib berardi.
    """
    if computer is None or computer.zone_id is None:
        return []
    return list(
        Camera.objects.filter(
            zone_id=computer.zone_id, is_active=True, deleted_at__isnull=True
        ).order_by("name", "pk")
    )


def camera_for_computer(computer, camera_id):
    """Bino doirasidagi BITTA kamera (`None` - doiradan tashqarida)."""
    if computer is None or computer.zone_id is None or not camera_id:
        return None
    return (
        Camera.objects.filter(
            pk=camera_id,
            zone_id=computer.zone_id,
            is_active=True,
            deleted_at__isnull=True,
        )
        .first()
    )


# --------------------------------------------------------------------------
# IP kamera holati va jonli ko'rish (admin panel)
# --------------------------------------------------------------------------
def check_camera(camera: Camera):
    """
    Kamerani tekshiradi va holatini YOZADI (`camera_probe.probe`).

    Faqat holat maydonlari yangilanadi (`update`, `save` emas): tekshiruv
    davriy va administrator shu payt kamerani tahrirlayotgan bo'lishi
    mumkin - to'liq `save()` uning o'zgarishini eski qiymat bilan
    ustidan yozib yuborardi.
    """
    from apps.devices import camera_probe

    result = camera_probe.probe(
        host=str(camera.ip_address),
        port=camera.port or 554,
        path=camera.rtsp_path or "/",
        login=camera.login,
        password=get_camera_password(camera) if camera.login else "",
        timeout=float(getattr(settings, "CAMERA_PROBE_TIMEOUT", 3.0)),
    )
    now = timezone.now()
    fields = {
        "status": result.status,
        "status_message": result.message[:200],
        "last_checked_at": now,
    }
    if result.status == Camera.Status.ONLINE:
        fields["last_seen_at"] = now
    Camera.objects.filter(pk=camera.pk).update(**fields)
    for name, value in fields.items():
        setattr(camera, name, value)
    return result


def check_cameras(cameras, *, workers: int = 16) -> dict:
    """
    Ko'p kamerani PARALLEL tekshiradi.

    Ketma-ket tekshiruv javob bermaydigan har kamerada `timeout`
    soniya kutadi: 60 ta offline kamera 3 minut degani va davriy
    vazifa keyingi ishga tushishigacha tugamasdi. Tekshiruv tarmoqni
    kutish, protsessor emas - thread'lar bu yerda to'g'ri vosita.
    """
    from concurrent.futures import ThreadPoolExecutor

    from django.db import close_old_connections

    def run(camera):
        try:
            return check_camera(camera).status
        except Exception:
            logger.exception("Kamera tekshiruvida xato: camera=%s", camera.pk)
            return "failed"
        finally:
            # Har thread o'z DB ulanishini ochadi - uni yopmaslik
            # ulanishlar sonini thread soniga ko'paytirib qo'yardi.
            close_old_connections()

    cameras = list(cameras)
    counts: dict = {}
    if not cameras:
        return counts
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(cameras)))) as pool:
        for status in pool.map(run, cameras):
            counts[status] = counts.get(status, 0) + 1
    return counts
