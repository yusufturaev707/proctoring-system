"""
Sozlamalar bilan ishlash.

Faol `Setting` har bir client handshake'ida va har bir event ingest'ida
kerak bo'ladi. 10 000 client × 30s heartbeat = 333 rps faqat sozlama
o'qish uchun. Shuning uchun u keshlanadi va o'zgarganda invalidatsiya
qilinadi.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

SETTING_CACHE_TTL = 300

#: Global standart (o'z sozlamasi yo'q imtihonlar uchun) shu kalitda yotadi.
_GLOBAL = "global"


def _cache_key(setting_id) -> str:
    return f"controls:config:v2:{setting_id or _GLOBAL}"


def _with_relations(queryset):
    """Konfiguratsiya uchun kerakli barcha M2M bitta so'rovda."""
    return queryset.select_related("detect_model").prefetch_related(
        "detect_classes", "rdp_objects", "hotkeys"
    )


def get_active_setting():
    """Global standart `Setting` obyekti (keshlanmagan ORM obyekti)."""
    from apps.controls.models import Setting

    return _with_relations(
        Setting.objects.filter(is_active=True, deleted_at__isnull=True)
    ).first()


def get_client_config(exam=None) -> dict:
    """
    Client'ga yuboriladigan konfiguratsiya (JSON).

    Imtihonning o'z sozlamasi bo'lsa — u ustun; aks holda global standart.
    Har xil imtihonda har xil profil bo'lishi ODATIY hol, shuning uchun
    kesh har bir sozlama uchun ALOHIDA kalitda yotadi. Ilgari faqat
    global sozlama keshlanardi va imtihon profili har chaqiruvda DB'ga
    borardi — davriy FaceID'da bu ~1000 so'rov/sekund degani.
    """
    from apps.controls.models import Setting

    setting_id = exam.setting_id if exam is not None else None
    key = _cache_key(setting_id)

    cached = cache.get(key)
    if cached is not None:
        return cached

    setting = None
    if setting_id:
        # `deleted_at` tekshiruvi SHART: o'chirilgan sozlama biriktirilgan
        # imtihon global standartga qaytishi kerak, o'chirilganini emas.
        setting = _with_relations(
            Setting.objects.filter(pk=setting_id, deleted_at__isnull=True)
        ).first()
        if setting is None:
            logger.warning(
                "Imtihon %s ga biriktirilgan sozlama (%s) topilmadi — "
                "global standart ishlatilmoqda",
                getattr(exam, "pk", None), setting_id,
            )
            return get_client_config()

    if setting is None:
        setting = get_active_setting()

    config = _serialize(setting) if setting is not None else _default_config()
    cache.set(key, config, SETTING_CACHE_TTL)
    return config


def invalidate_setting_cache(setting=None) -> None:
    """
    Sozlama o'zgarganda keshni tozalaydi.

    Global kalit HAR DOIM tozalanadi: `is_active` o'zgarishi qaysi sozlama
    standart ekanini almashtiradi, ya'ni eski global kesh yaroqsiz bo'ladi.
    """
    keys = [_cache_key(None)]
    if setting is not None and getattr(setting, "pk", None):
        keys.append(_cache_key(setting.pk))
    cache.delete_many(keys)


def _serialize(setting) -> dict:
    return {
        "setting_id": setting.pk,
        "name": setting.name,
        "face": {
            "enabled_student": setting.is_faceid_student,
            "enabled_in_exam": setting.is_faceid_exam,
            "interval": setting.faceid_interval,
            "max_fail": setting.faceid_max_fail,
            "warning_timeout": setting.warning_timeout,
            "min_score_initial": setting.faceid_min_score_student,
            "min_score_exam": setting.faceid_min_score_exam,
            "audit_rate": setting.faceid_audit_rate,
        },
        "capture": {
            "screen_record": setting.is_screen_record,
            "screenshot_interval": setting.screenshot_interval,
            "quality": setting.screenshot_quality,
            "max_width": setting.screenshot_max_width,
            "dedup_threshold": setting.screenshot_dedup_threshold,
        },
        "device": {
            "detect_monitor": setting.is_detect_monitor,
            "detect_camera": setting.is_detect_camera,
        },
        "detection": {
            "enabled": setting.is_enable_detect,
            "model": setting.detect_model.code if setting.detect_model_id else "",
            "confidence": setting.detect_confidence,
            "frame_skip": setting.detect_frame_skip,
            "classes": [
                {"code": obj.code, "name": obj.name, "severity": obj.severity}
                for obj in setting.detect_classes.all()
                if obj.is_active
            ],
        },
        "rdp": {
            "enabled": setting.is_enable_rdp_detect,
            "processes": [
                name
                for obj in setting.rdp_objects.all()
                if obj.is_active
                for name in (obj.process_names or [obj.code])
            ],
        },
        "hotkeys": [obj.code for obj in setting.hotkeys.all() if obj.is_active],
        "technical_problem": {"enabled": setting.is_enable_check_tp},
        "network": {
            "heartbeat_interval": setting.heartbeat_interval,
            "event_batch_interval": setting.event_batch_interval,
            "offline_buffer_size": setting.offline_buffer_size,
        },
    }


def _default_config() -> dict:
    """Hech qanday sozlama yaratilmagan bo'lsa — xavfsiz standart."""
    logger.warning("Faol Setting topilmadi, standart konfiguratsiya ishlatilmoqda")
    return {
        "setting_id": None,
        "name": "default",
        "face": {
            "enabled_student": True,
            "enabled_in_exam": True,
            "interval": 10,
            "max_fail": 3,
            "warning_timeout": 5,
            "min_score_initial": 70,
            "min_score_exam": 70,
            "audit_rate": 0.05,
        },
        "capture": {
            "screen_record": False,
            "screenshot_interval": 10,
            "quality": 65,
            "max_width": 960,
            "dedup_threshold": 6,
        },
        "device": {"detect_monitor": True, "detect_camera": True},
        "detection": {"enabled": False, "model": "", "confidence": 0.5, "frame_skip": 20, "classes": []},
        "rdp": {"enabled": True, "processes": []},
        "hotkeys": [],
        "technical_problem": {"enabled": True},
        "network": {
            "heartbeat_interval": 30,
            "event_batch_interval": 5,
            "offline_buffer_size": 5000,
        },
    }


def verify_exit_password(raw: str, *, region_id: int | None = None):
    """
    Chiqish parolini tekshiradi va mos kelgan yozuvni qaytaradi.

    `region_id` berilsa — FAQAT o'sha viloyatning paroli sinaladi.
    Berilmasa (viloyatni aniqlab bo'lmagan holat) barcha faol parollar
    ko'riladi.

    Ikkinchi yo'l ataylab qoldirilgan va uning narxi tushunilgan:
    viloyat noma'lum bo'lganda tekshiruv "biror viloyatning paroli"
    darajasiga tushadi. Muqobili — mashinani umuman yopib bo'lmaydigan
    holatda qoldirish, chunki viloyat aynan eng kerakli paytda
    (preflight rad etgan ekranda) noma'lum bo'ladi. Brute-force'ga
    qarshi himoya `ExitVerifyThrottle` da, urinish esa jurnalga
    tushadi.

    Solishtirish DOIM barcha nomzodlar bo'ylab bajariladi (erta
    `return` yo'q): hash tekshiruvi qimmat amal va birinchi moslikda
    to'xtash javob vaqti orqali "nechanchi viloyat" ekanini oshkor
    qilardi.
    """
    from apps.controls.models import ClientExitPassword

    if not raw:
        return None

    queryset = ClientExitPassword.objects.select_related("region").filter(is_active=True)
    if region_id is not None:
        queryset = queryset.filter(region_id=region_id)

    matched = None
    for row in queryset:
        if row.check_password(raw) and matched is None:
            matched = row
    return matched


def has_exit_password(*, region_id: int | None = None) -> bool:
    """
    Chiqish paroli UMUMAN sozlanganmi?

    Bu savol kerak, chunki "parol noto'g'ri" va "parol hali
    o'rnatilmagan" holatlari client uchun butunlay boshqacha. Ikkinchisi
    sozlash bosqichidagi bo'shliq va u mashinani QULFLAB qo'ymasligi
    kerak: kiosk rejimida chiqishning boshqa yo'li yo'q, ya'ni parolsiz
    viloyatda operator dasturni faqat quvvatdan uzib yopa olardi.
    """
    from apps.controls.models import ClientExitPassword

    queryset = ClientExitPassword.objects.filter(is_active=True)
    if region_id is not None:
        queryset = queryset.filter(region_id=region_id)
    return queryset.exists()


def client_hotkeys() -> list:
    """
    Bloklanishi kerak bo'lgan klaviatura kombinatsiyalari.

    `build_client_config` dagi ro'yxat bilan BIR XIL manba (faol
    `Setting`), lekin u handshake'da, ya'ni login'dan KEYIN keladi.
    Bu funksiya esa preflight uchun: dastur login formasini
    ko'rsatishdan oldin ham qulflangan bo'lishi kerak, aks holda
    kompyuter eng ochiq holatda - operator hali kirmagan, ekranda
    forma turibdi va Win/Alt+Tab ishlayveradi.
    """
    setting = get_active_setting()
    if setting is None:
        return []
    return [obj.code for obj in setting.hotkeys.all() if obj.is_active]


IP_CACHE_KEY = "controls:allowed_ips:v1"


def allowed_ip_map() -> dict:
    """
    `{ip_address: zone_id|None}` — faol ruxsat etilgan manzillar.

    Kesh AYNAN shu yerda, chunki uni ikki joy o'qiydi: har bir client
    so'rovidagi `is_ip_allowed` va ishga tushishdagi preflight. Ikkinchi
    nusxa kesh yozilsa, administrator IP qo'shganda ikkalasi turli
    vaqtda yangilanardi va "panelda qo'shdim, client hali ham
    kiritmayapti" degan tushunarsiz holat paydo bo'lardi.
    """
    from apps.controls.models import AllowedPublicIp

    allowed = cache.get(IP_CACHE_KEY)
    if allowed is None:
        allowed = dict(
            AllowedPublicIp.objects.filter(is_active=True).values_list("ip_address", "zone_id")
        )
        cache.set(IP_CACHE_KEY, allowed, 300)
    return allowed


def require_allowed_ip() -> bool:
    """
    Ro'yxat BO'SH bo'lganda nima qilinadi (`PROCTORING.REQUIRE_ALLOWED_IP`).

    `True` — hech kim kira olmaydi; `False` — tekshiruv o'chirilgan.
    Batafsil sabab sozlama izohida (`config/settings/base.py`).
    """
    return bool(settings.PROCTORING.get("REQUIRE_ALLOWED_IP", True))


def ip_check_enforced() -> bool:
    """
    Tekshiruv umuman kuchdami?

    Faol yozuv bo'lsa — HA. Ro'yxat bo'sh bo'lsa javob sozlamaga
    bog'liq: qat'iy rejimda tekshiruv baribir kuchda qoladi (va hamma
    rad etiladi), yumshoq rejimda esa o'chiriladi.
    """
    return bool(allowed_ip_map()) or require_allowed_ip()


def is_ip_allowed(ip_address: str, zone_id: int | None = None) -> bool:
    """
    Client ruxsat etilgan tarmoqdan ulanayotganini tekshiradi.

    Ro'yxatda FAOL yozuv qolmasa — `REQUIRE_ALLOWED_IP` hal qiladi.
    Ilgari bu holat so'zsiz "ruxsat" degani edi va oqibati kutilmagan
    bo'lardi: ro'yxatdagi yagona manzilni nofaol qilish yoki o'chirish
    butun cheklovni jimgina olib tashlardi.
    """
    allowed = allowed_ip_map()

    if not allowed:
        return not require_allowed_ip()
    if ip_address not in allowed:
        return False

    bound_zone = allowed[ip_address]
    return bound_zone is None or zone_id is None or bound_zone == zone_id


def network_preflight(*, public_ip: str, observed_ip: str = "") -> dict:
    """
    Client ishga tushishdagi tarmoq tekshiruvi.

    Client login formasini KO'RSATISHDAN OLDIN chaqiradi: agar kompyuter
    ro'yxatdagi tarmoqdan ulanmayotgan bo'lsa, operator login/parol
    kiritib, imtihon tanlab, JSHSHIR yozib, faqat o'sha yerda
    `ip_not_allowed` olishi mantiqsiz — to'siq oqimning eng boshida
    ko'rinishi kerak.

    QAROR AYNAN BITTA QIYMAT BO'YICHA: client o'zi aniqlagan tashqi
    (public) IP. Server ko'rgan manzil (`observed_ip`) tekshiruvda
    QATNASHMAYDI, u faqat jurnalga va farqni ko'rsatishga tushadi.

    Buning sababi joylashuvda: server Toshkentdagi binoning ICHIDA
    turadi. O'sha binodagi clientlar unga NAT'siz, ya'ni LAN manzili
    bilan yetib boradi va server ularning tashqi manzilini printsipial
    ravishda ko'ra olmaydi — har bir ish stantsiyasining 192.168.x.x
    manzilini ro'yxatga kiritishga esa hech qanday ma'no yo'q.

    NIMANI ANGLATADI: bu tekshiruv QULAYLIK to'sig'i, himoya emas —
    client aytgan qiymatni o'zgartirish mumkin. Haqiqiy himoya
    o'zgarishsiz qoladi va u har bir client so'rovida
    `ClientBaseView.check_source_ip` orqali, FAQAT server ko'rgan
    manzil bo'yicha ishlaydi.
    """
    allowed_ips = allowed_ip_map()          # FAQAT `is_active=True` yozuvlar
    enforced = ip_check_enforced()

    # Qaror jadvali — boshqa hech qanday shart yo'q:
    #
    #   public_ip ro'yxatda, faol      -> RUXSAT
    #   public_ip ro'yxatda yo'q       -> RAD
    #   public_ip nofaol qilingan      -> RAD (u `allowed_ips` da yo'q)
    #   public_ip umuman aniqlanmadi   -> RAD (tekshirish uchun narsa yo'q)
    #   ro'yxatda faol yozuv YO'Q      -> `REQUIRE_ALLOWED_IP` hal qiladi
    if not allowed_ips:
        allowed = not require_allowed_ip()
    elif not public_ip:
        allowed = False
    else:
        allowed = public_ip in allowed_ips

    result = {
        "allowed": allowed,
        "enforced": enforced,
        # Rad etish sababi ikki xil bo'lishi mumkin va operator uchun
        # ular BUTUNLAY boshqa: "sizning manzilingiz ro'yxatda yo'q"
        # va "ro'yxat umuman to'ldirilmagan". Ikkinchisi administrator
        # xatosi, uni operatorga "IP'ingiz noto'g'ri" deb ko'rsatish
        # nosozlikni soatlab qidirishga olib keladi.
        "allowlist_empty": not allowed_ips,
        "public_ip": public_ip,
        "observed_ip": observed_ip,
        # `None` — solishtirib bo'lmadi (biror manzil noma'lum).
        "matches_observed": (
            (public_ip == observed_ip) if (public_ip and observed_ip) else None
        ),
        "zone": None,
        "region": None,
    }
    if not allowed or not allowed_ips:
        return result

    # Bino nomi FAQAT ko'rsatish uchun: operator "qaysi bino sifatida
    # tanildim?" degan savolga darhol javob oladi va noto'g'ri bino
    # biriktirilgani imtihon boshlangunga qadar ma'lum bo'ladi.
    from apps.controls.models import AllowedPublicIp

    row = (
        AllowedPublicIp.objects.select_related("zone", "zone__region")
        .filter(ip_address=public_ip, is_active=True, zone__isnull=False)
        .first()
    )
    if row is not None and row.zone.deleted_at is None and row.zone.is_active:
        result["zone"] = {"id": row.zone.pk, "name": row.zone.name}
        if row.zone.region_id:
            result["region"] = {"id": row.zone.region_id, "name": row.zone.region.name}
    return result


def invalidate_ip_cache() -> None:
    cache.delete(IP_CACHE_KEY)
