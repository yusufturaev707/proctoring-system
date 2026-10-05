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

from apps.common.utils.network import is_private_ip

logger = logging.getLogger(__name__)

SETTING_CACHE_TTL = 300

#: Global standart (o'z sozlamasi yo'q imtihonlar uchun) shu kalitda yotadi.
_GLOBAL = "global"


def _cache_key(setting_id) -> str:
    return f"controls:config:v2:{setting_id or _GLOBAL}"


def _with_relations(queryset):
    """Konfiguratsiya uchun kerakli barcha bog'lanish bitta so'rovda."""
    return queryset.select_related("detect_model", "proctoring").prefetch_related(
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
            # Kirish tekshiruvi oqimi - client `.env` dagi zaxiradan
            # USTUN (`client/services/runtime_settings.py`).
            "guide_seconds": setting.faceid_guide_seconds,
            "match_streak": setting.faceid_match_streak,
            "fail_streak": setting.faceid_fail_streak,
            "fail_min_seconds": setting.faceid_fail_min_seconds,
            # Test davomida yuz juda uzoq (`client/services/face_presence.py`).
            "far_warn_s": setting.faceid_far_warn_s,
            "far_unverified_s": setting.faceid_far_unverified_s,
        },
        "capture": {
            "screen_record": setting.is_screen_record,
            # Skrinshot BUYRUQ bilan (interval yo'q); `upload` - serverga
            # ham yuborilsinmi, mashinada esa har doim saqlanadi.
            "upload": setting.is_screenshot_upload,
            "quality": setting.screenshot_quality,
            "max_width": setting.screenshot_max_width,
            # Foizda (5..40), client ulushga o'zi o'giradi: panel ham,
            # model ham administrator tushunadigan birlikda qoladi.
            "record_fps": setting.screen_record_fps,
            "record_width": setting.screen_record_width,
            "record_pip_percent": setting.screen_record_pip_percent,
            "camera_overlay": setting.is_screenshot_camera_overlay,
            "camera_overlay_percent": setting.screenshot_pip_percent,
        },
        "device": {
            "detect_monitor": setting.is_detect_monitor,
            "detect_camera": setting.is_detect_camera,
            "detect_peripherals": setting.is_detect_peripherals,
        },
        "detection": {
            "enabled": setting.is_enable_detect,
            "model": setting.detect_model.code if setting.detect_model_id else "",
            "confidence": setting.detect_confidence,
            "frame_skip": setting.detect_frame_skip,
            "classes": [
                {
                    "code": obj.code,
                    "name": obj.name,
                    "severity": obj.severity,
                    # Xavf og'irligi client tomonda ham kerak: ball
                    # SESSIYA davomida hisoblanadi va operator uni
                    # ekranda ko'radi. Server baribir o'zi qayta
                    # hisoblaydi - client bergan ball ISHONCHSIZ va u
                    # hech qachon `ExamSession.risk_score` ga
                    # to'g'ridan-to'g'ri yozilmaydi.
                    "risk_weight": obj.risk_weight,
                }
                for obj in setting.detect_classes.all()
                if obj.is_active
            ],
        },
        "rdp": {
            "enabled": setting.is_enable_rdp_detect,
            # `processes` — ESKI CLIENTLAR uchun saqlanadi. U faqat
            # fayl nomlarini beradi, ya'ni qayta nomlangan binarni
            # ko'rmaydi; yangi client `rules` ni o'qiydi va nomni
            # eng oxirgi belgi sifatida ishlatadi.
            "processes": [
                name
                for obj in setting.rdp_objects.all()
                if obj.is_active
                for name in (obj.process_names or [obj.code])
            ],
            "rules": [
                {
                    "code": obj.code,
                    "label": obj.name,
                    "category": obj.category,
                    "blocking": obj.is_blocking,
                    "publishers": obj.publishers or [],
                    "originals": obj.original_filenames or [],
                    "products": obj.products or [],
                    "names": obj.process_names or [],
                    "services": obj.service_names or [],
                    "ports": obj.ports or [],
                }
                for obj in setting.rdp_objects.all()
                if obj.is_active
            ],
            # Yo'q qilinmagan tahdid imtihonni to'sadimi - imtihon
            # siyosati (`Setting.is_threat_block_exam` izohi).
            "block_exam": setting.is_threat_block_exam,
        },
        # BO'SH RO'YXAT = "administrator tanlamagan": client o'z
        # `.env` standartini (`BLOCKED_HOTKEYS`) qoldiradi
        # (`client/services/lockdown.py:resolve_hotkeys`).
        "hotkeys": [obj.code for obj in setting.hotkeys.all() if obj.is_active],
        "technical_problem": {"enabled": setting.is_enable_check_tp},
        "network": {
            "heartbeat_interval": setting.heartbeat_interval,
            "event_batch_interval": setting.event_batch_interval,
            "offline_buffer_size": setting.offline_buffer_size,
            "presence_interval": _presence_interval(),
        },
        "proctoring": _serialize_proctoring(setting),
    }


def _serialize_proctoring(setting) -> dict:
    """
    AI kuzatuv sozlamalari (`ProctoringPolicy`).

    IKKI MANBADAN BITTA JAVOB. Obyekt aniqlashning "yoqilganmi",
    "qanday ishonch bilan" va "qaysi klasslar" degan savollari
    ALLAQACHON `Setting` da bor (`is_enable_detect`, `detect_confidence`,
    `detect_classes`) va ular u yerda qoladi. Siyosat ularni
    TAKRORLAMAYDI - u faqat qo'shimcha savollarga javob beradi:
    qancha kadr ketma-ket kelsin, qancha davom etsin, hodisalar
    qanday birlashtirilsin, ball qanday pasaysin.

    Client'ga esa BITTA qiymat ketadi: `modules.objects` ikkalasining
    mantiqiy VA'si. Ikki bayroqni clientga berib, "qaysi biri
    ustun?" degan savolni unga yuklash - bu savol albatta ikki
    joyda ikki xil hal qilinardi.

    Siyosat YO'Q bo'lsa standart qiymatlar qaytadi va bu ataylab:
    yangi `Setting` yaratgan administrator kuzatuvni bilmagan holda
    o'chirib qo'ymasligi kerak.
    """
    policy = getattr(setting, "proctoring", None)
    if policy is None:
        return _default_proctoring()

    return {
        "enabled": policy.is_enabled,
        "camera": {
            "count": policy.camera_count,
            "primary_kind": policy.primary_camera_kind,
            "secondary_kind": policy.secondary_camera_kind,
            "primary_required": policy.primary_required,
            "secondary_required": policy.secondary_required,
            "allow_virtual": policy.allow_virtual_camera,
            "min_fps": policy.min_fps,
            "min_width": policy.min_width,
            "min_height": policy.min_height,
            "lost_grace_s": policy.camera_lost_grace_s,
            "lost_action": policy.camera_lost_action,
            **_camera_check_flag(),
        },
        "modules": {
            "identity": policy.enable_identity and setting.is_faceid_exam,
            # Yagona manba: siyosat VA sozlama. Yuqoridagi izohga qarang.
            "objects": policy.enable_objects and setting.is_enable_detect,
            "pose": policy.enable_pose,
            "gaze": policy.enable_gaze,
            "tracking": policy.enable_tracking,
        },
        "fps": {
            "identity": policy.identity_fps,
            "objects": policy.object_fps,
            "pose": policy.pose_fps,
            "gaze": policy.gaze_fps,
        },
        "gpu_profile": policy.gpu_profile_override,
        "temporal": {
            "no_face_warn_s": policy.no_face_warn_s,
            "no_face_suspicious_s": policy.no_face_suspicious_s,
            "gaze_away_warn_s": policy.gaze_away_warn_s,
            "gaze_away_suspicious_s": policy.gaze_away_suspicious_s,
            "object_min_frames": policy.object_min_frames,
            "object_min_conf": policy.object_min_conf,
            "object_min_duration_ms": policy.object_min_duration_ms,
        },
        "fusion": {"window_ms": policy.fusion_window_ms},
        "risk": {
            "decay_per_min": policy.risk_decay_per_min,
            "cooldown_s": policy.risk_event_cooldown_s,
            "low": policy.threshold_low,
            "medium": policy.threshold_medium,
            "high": policy.threshold_high,
        },
        "evidence": {
            "enabled": policy.evidence_enabled,
            "clip_seconds": policy.evidence_clip_seconds,
            "min_severity": policy.evidence_min_severity,
            # Saqlash muddati client'ga ham ketadi: u dalilni
            # yuborganda serverga uzatiladi va qatorga yoziladi.
            # Tozalash vazifasi siyosatni qayta o'qimasligi kerak -
            # sessiya tugagach u o'zgargan bo'lishi mumkin.
            "clip_retention_days": policy.evidence_clip_retention_days,
            "frame_retention_days": policy.evidence_frame_retention_days,
        },
    }


def _camera_check_flag() -> dict:
    """
    Server kamera tekshiruvini MAJBURLAYDIMI (`REQUIRE_CAMERA_CHECK`).

    Client buni oldindan bilishi shart: ilgari tayyorlik oynasi
    "tekshiruv o'tkazilmagan" ni OGOHLANTIRISH deb ko'rsatardi, operator
    uni tasdiqlab o'tar va to'siq faqat `proctoring/start/` da —
    talabgor JSHSHIR, FaceID va shaxs tasdig'idan o'tib bo'lgach —
    `camera_check_required` bo'lib chiqardi. Endi client uni imtihon
    tanlash sahifasida TO'SIQ qiladi (`policy.check_readiness`).
    """
    return {"check_required": bool(settings.PROCTORING["REQUIRE_CAMERA_CHECK"])}


def _presence_interval() -> int:
    """
    "Client ishlab turibdi" signalining oralig'i (s) - PANEL MAYDONI EMAS.

    U profilga (imtihonga) emas, serverdagi presence kalitining
    muddatiga (`devices.services.PRESENCE_TTL`) bog'langan: TTL
    oraliqdan kamida IKKI BAROBAR katta bo'lishi shart, aks holda
    bitta kechikkan signal mashinani panelda "offline" qilib
    qo'yardi. Ikkala son bitta joyda (`devices/services.py`) turadi
    va client oraliqni serverdan oladi - ilgari u har mashinaning
    `.env` ida edi (`PRESENCE_PING_MS`) va TTL o'zgarsa 500 mashinani
    qo'lda tahrirlash kerak bo'lardi. Presence imtihondan tashqarida
    ishlaydi, shuning uchun uni imtihon profiliga qo'yishning ma'nosi
    yo'q edi.
    """
    from apps.devices.services import PRESENCE_PING_INTERVAL

    return PRESENCE_PING_INTERVAL


def _default_proctoring() -> dict:
    """
    Siyosat biriktirilmagan profil uchun.

    `enabled=False` - AI kuzatuv OCHIQ yoqilishi kerak. Bu qasddan
    qilingan: pipeline GPU va kamera talab qiladi, uni bilmagan holda
    yoqib qo'yish zaif mashinalarda imtihonni sekinlashtiradi.
    Qolgan qiymatlar esa modeldagi standartlar bilan bir xil - client
    ularni siyosat keyin yoqilganda ham qayta o'rganmasligi kerak.
    """
    return {
        "enabled": False,
        "camera": {
            "count": 1,
            "primary_kind": "auto",
            "secondary_kind": "auto",
            "primary_required": True,
            "secondary_required": False,
            "allow_virtual": False,
            "min_fps": 12,
            "min_width": 640,
            "min_height": 480,
            "lost_grace_s": 30,
            "lost_action": "warn",
            **_camera_check_flag(),
        },
        "modules": {
            "identity": True,
            "objects": False,
            "pose": False,
            "gaze": False,
            "tracking": False,
        },
        "fps": {"identity": 10, "objects": 6, "pose": 8, "gaze": 10},
        "gpu_profile": "auto",
        "temporal": {
            "no_face_warn_s": 2,
            "no_face_suspicious_s": 5,
            "gaze_away_warn_s": 2,
            "gaze_away_suspicious_s": 5,
            "object_min_frames": 5,
            "object_min_conf": 0.80,
            "object_min_duration_ms": 1200,
        },
        "fusion": {"window_ms": 3000},
        "risk": {"decay_per_min": 5, "cooldown_s": 60, "low": 20, "medium": 40, "high": 70},
        "evidence": {
            "enabled": False, "clip_seconds": 5, "min_severity": 2,
            "clip_retention_days": 30, "frame_retention_days": 90,
        },
    }


# v2: qiymat shakli o'zgardi (`{tur: og'irlik}` -> `{tur: [og'irlik,
# cooldown]}`). Kalit almashmasa, relizdan keyin 5 daqiqa davomida
# eski shakldagi kesh yangi kod tomonidan o'qilib, yiqilardi.
RISK_WEIGHT_CACHE_KEY = "controls:risk_weights:v2"


def _risk_rows() -> dict:
    """
    `{hodisa_turi: [og'irlik, cooldown_s]}` - faol `EventRiskWeight`.

    Har bir hodisa qabul qilishda o'qiladi (sekundiga minglab marta),
    shuning uchun keshlanadi. Og'irlik ham, cooldown ham BITTA kesh
    yozuvida: ikkalasi ham har hodisada kerak va ikkita kalit ikkita
    round-trip hamda ikki xil eskirish degani bo'lardi.
    """
    from apps.controls.models import EventRiskWeight

    rows = cache.get(RISK_WEIGHT_CACHE_KEY)
    if rows is None:
        rows = {
            event_type: [weight, cooldown_s]
            for event_type, weight, cooldown_s in EventRiskWeight.objects.filter(
                is_active=True
            ).values_list("event_type", "weight", "cooldown_s")
        }
        cache.set(RISK_WEIGHT_CACHE_KEY, rows, SETTING_CACHE_TTL)
    return rows


def risk_weight_map() -> dict:
    """
    `{hodisa_turi: og'irlik}`.

    Jadval BO'SH bo'lsa bo'sh lug'at qaytadi va chaqiruvchi kodidagi
    zaxira qiymatlarga tushadi - `ingest.RISK_WEIGHTS`. "Sozlanmagan
    tizim ballni umuman hisoblamaydi" holati bo'lmasligi kerak.
    """
    return {event_type: row[0] for event_type, row in _risk_rows().items()}


def risk_cooldown_map() -> dict:
    """
    `{hodisa_turi: cooldown_s}` - FAQAT alohida qiymat berilgan turlar.

    `0` "cooldown yo'q" degani EMAS, "siyosatdagi umumiy qiymat"
    degani, shuning uchun u lug'atga tushmaydi. Aks holda turi uchun
    qator yaratilgan (faqat og'irligini o'zgartirish uchun) har bir
    hodisa cooldown'siz qolib, ballni ikki marta sanab yuborardi.
    """
    return {
        event_type: row[1] for event_type, row in _risk_rows().items() if row[1] > 0
    }


def invalidate_risk_weight_cache() -> None:
    cache.delete(RISK_WEIGHT_CACHE_KEY)


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
            "min_score_initial": 40,
            "min_score_exam": 40,
            "audit_rate": 0.05,
            "guide_seconds": 5,
            "match_streak": 3,
            "fail_streak": 15,
            "fail_min_seconds": 8,
            "far_warn_s": 10,
            "far_unverified_s": 120,
        },
        "capture": {
            # Modeldagi standart bilan bir xil (`True`): sozlamasi yo'q
            # tizim dalilni jimgina yozmay qo'ymasligi kerak.
            "screen_record": True,
            "upload": True,
            "quality": 80,
            "max_width": 1920,
            "record_fps": 5,
            "record_width": 1600,
            "record_pip_percent": 12,
            "camera_overlay": True,
            "camera_overlay_percent": 16,
        },
        "device": {"detect_monitor": True, "detect_camera": True, "detect_peripherals": True},
        "detection": {"enabled": False, "model": "", "confidence": 0.5, "frame_skip": 20, "classes": []},
        # Sozlama umuman yo'q bo'lsa ham aniqlash YOQILGAN qoladi va
        # ro'yxatning bo'shligi "himoya yo'q" degani EMAS: client'da
        # ichki katalog bor (`threat_rules.BUILTIN_RULES`) va u
        # serverdan mustaqil ishlaydi.
        "rdp": {"enabled": True, "processes": [], "rules": [], "block_exam": True},
        # Bo'sh = client `.env` standartini qoldiradi (yuqoriga qarang).
        "hotkeys": [],
        "technical_problem": {"enabled": True},
        "network": {
            "heartbeat_interval": 30,
            "event_batch_interval": 5,
            "offline_buffer_size": 5000,
            "presence_interval": _presence_interval(),
        },
        "proctoring": _default_proctoring(),
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


#: v2: yozuv IP YOKI tarmoq bo'lishi mumkin (keshdagi shakl o'zgardi —
#: eski jarayonlar qoldirgan v1 qiymati o'qilmasin).
IP_CACHE_KEY = "controls:allowed_ips:v2"

#: Tarmoq qanchalik keng bo'lishi mumkin. `0.0.0.0/0` yoki `10.0.0.0/4`
#: kabi yozuv tekshiruvni amalda o'chirardi — bu ataylab qaror bo'lsa,
#: `REQUIRE_ALLOWED_IP=false` yoki global IP aniqroq yo'l.
MIN_PREFIX = {4: 8, 6: 32}


def _allowlist() -> dict:
    """
    Faol yozuvlar, keshda: `{"hosts": {ip: zone_id|None}, "networks": [[cidr, zone_id|None]]}`.

    Kesh AYNAN shu yerda, chunki uni ikki joy o'qiydi: har bir client
    so'rovidagi `is_ip_allowed` va ishga tushishdagi preflight. Ikkinchi
    nusxa kesh yozilsa, administrator IP qo'shganda ikkalasi turli
    vaqtda yangilanardi va "panelda qo'shdim, client hali ham
    kiritmayapti" degan tushunarsiz holat paydo bo'lardi.
    """
    from apps.controls.models import AllowedPublicIp

    data = cache.get(IP_CACHE_KEY)
    if data is None:
        hosts: dict = {}
        networks: list = []
        rows = AllowedPublicIp.objects.filter(is_active=True).values_list(
            "ip_address", "network", "zone_id"
        )
        for ip_address, network, zone_id in rows:
            if ip_address:
                hosts[ip_address] = zone_id
            elif network:
                networks.append([network, zone_id])
        data = {"hosts": hosts, "networks": networks}
        cache.set(IP_CACHE_KEY, data, 300)
    return data


def allowed_ip_map() -> dict:
    """`{ip_address: zone_id|None}` — faol yozuvlarning faqat bitta IP'lisi."""
    return _allowlist()["hosts"]


def allowlist_empty() -> bool:
    data = _allowlist()
    return not data["hosts"] and not data["networks"]


def allowed_zones_for(ip_address: str, *, networks_only: bool = False) -> list:
    """
    Manzilga mos yozuvlarning binolari (`None` — barcha binolar uchun).

    Bo'sh ro'yxat — manzil ro'yxatda yo'q. Aniq IP tarmoqdan USTUN: u
    topilsa tarmoqlarga qaralmaydi. Tarmoqlar kesishmaydi (validatsiya),
    ya'ni javobda ko'pi bilan bitta yozuv. `networks_only` — faqat
    tarmoq yozuvlari (preflight'da server ko'rgan manzil uchun).
    """
    import ipaddress

    data = _allowlist()
    value = str(ip_address or "").strip()
    if not networks_only and value in data["hosts"]:
        return [data["hosts"][value]]
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return []
    zones = []
    for cidr, zone_id in data["networks"]:
        try:
            network = ipaddress.ip_network(cidr)
        except ValueError:
            continue
        if address.version == network.version and address in network:
            zones.append(zone_id)
    return zones


def clean_allowlist_entry(
    *, ip_address=None, network: str = "", exclude_pk=None
) -> tuple[str | None, str]:
    """
    Yozuvni tekshiradi va kanonik shaklga keltiradi: `(ip_address, network)`.

    Panel serializer'i va Django admin (`AllowedPublicIp.clean`) SHU
    funksiyani chaqiradi — qoida ikki joyda yashasa ajralib ketadi.
    Xato — `django.core.exceptions.ValidationError` (maydon bo'yicha).

    * aynan bittasi: IP yoki tarmoq;
    * tarmoq kanonik (`192.168.0.15/24` -> `192.168.0.0/24`), juda keng
      emas (`MIN_PREFIX`) va bitta manzildan iborat emas (u — IP);
    * tarmoqlar o'zaro KESISHMAYDI: aks holda bitta manzil ikki binoga
      tegishli bo'lib qolardi va qaysi biri hal qilishi noaniq edi.
    """
    import ipaddress

    from django.core.exceptions import ValidationError

    from apps.controls.models import AllowedPublicIp

    ip_value = str(ip_address or "").strip() or None
    raw_network = str(network or "").strip()

    if bool(ip_value) == bool(raw_network):
        message = "IP manzil YOKI tarmoqdan (CIDR) aynan bittasini kiriting"
        raise ValidationError({"ip_address": message, "network": message})

    if ip_value:
        return ip_value, ""

    try:
        parsed = ipaddress.ip_network(raw_network, strict=False)
    except ValueError:
        raise ValidationError(
            {"network": "Tarmoq CIDR ko'rinishida bo'lishi kerak, masalan 192.168.0.0/24"}
        )
    if parsed.num_addresses == 1:
        raise ValidationError(
            {"network": "Bitta manzil uchun «IP manzil» maydonidan foydalaning"}
        )
    if parsed.prefixlen < MIN_PREFIX[parsed.version]:
        raise ValidationError(
            {"network": "Tarmoq juda keng: kamida /{} bo'lishi kerak".format(
                MIN_PREFIX[parsed.version]
            )}
        )

    others = AllowedPublicIp.objects.exclude(network="")
    if exclude_pk is not None:
        others = others.exclude(pk=exclude_pk)
    for other_cidr in others.values_list("network", flat=True):
        try:
            other = ipaddress.ip_network(other_cidr)
        except ValueError:
            continue
        if other.version == parsed.version and other.overlaps(parsed):
            raise ValidationError(
                {"network": "Bu tarmoq mavjud {} yozuvi bilan kesishadi".format(other_cidr)}
            )
    return None, parsed.compressed


def zone_id_for_ip(ip_address: str):
    """
    Manzil qaysi BINOGA tegishli (`None` — noma'lum yoki global yozuv).

    Qurilmani ro'yxatdan o'tkazishda binoni aniqlash uchun
    (`devices.services.resolve_zone_by_public_ip`): VPN'da server binoni
    tashqi IP bilan emas, bino tarmog'i bilan taniydi.
    """
    zones = [zone for zone in allowed_zones_for(ip_address) if zone is not None]
    return zones[0] if len(zones) == 1 else None


def require_allowed_ip() -> bool:
    """
    Ro'yxat BO'SH bo'lganda nima qilinadi (`PROCTORING.REQUIRE_ALLOWED_IP`).

    `True` — hech kim kira olmaydi; `False` — tekshiruv o'chirilgan.
    Batafsil sabab sozlama izohida (`config/settings/base.py`).
    """
    return bool(settings.PROCTORING.get("REQUIRE_ALLOWED_IP", True))


def allow_private_source() -> bool:
    """
    Xususiy (LAN/loopback) manba manzili tekshiruvdan o'tadimi.

    Sabab va ikki topologiya `PROCTORING["ALLOW_PRIVATE_SOURCE_IP"]`
    izohida (`config/settings/base.py`).
    """
    return bool(settings.PROCTORING.get("ALLOW_PRIVATE_SOURCE_IP", False))


def ip_check_enforced() -> bool:
    """
    Tekshiruv umuman kuchdami?

    Faol yozuv bo'lsa — HA. Ro'yxat bo'sh bo'lsa javob sozlamaga
    bog'liq: qat'iy rejimda tekshiruv baribir kuchda qoladi (va hamma
    rad etiladi), yumshoq rejimda esa o'chiriladi.
    """
    return not allowlist_empty() or require_allowed_ip()


def is_ip_allowed(ip_address: str, zone_id: int | None = None) -> bool:
    """
    Client ruxsat etilgan tarmoqdan ulanayotganini tekshiradi.

    Ro'yxatda FAOL yozuv qolmasa — `REQUIRE_ALLOWED_IP` hal qiladi.
    Ilgari bu holat so'zsiz "ruxsat" degani edi va oqibati kutilmagan
    bo'lardi: ro'yxatdagi yagona manzilni nofaol qilish yoki o'chirish
    butun cheklovni jimgina olib tashlardi.

    Manzil ikki xil yozuvga mos kelishi mumkin: aniq IP (bino internet
    orqali, NAT manzili bilan keladi) yoki TARMOQ (server bino ichida
    yoki binolar VPN'da — server xususiy manzilni ko'radi). Ikkalasi
    ham binoga bog'lanadi: boshqa binoga biriktirilgan qurilma o'tmaydi.

    `ALLOW_PRIVATE_SOURCE_IP` — eski, qo'pol yo'l: istalgan xususiy
    manzilni binoga bog'lamasdan o'tkazadi. Tarmoq yozuvi uning o'rnini
    bosadi; sozlama orqaga moslik uchun qoladi.
    """
    if allowlist_empty():
        return not require_allowed_ip()

    # Tekshiruv ro'yxat BO'SH EMASLIGIDAN keyin turadi: ro'yxat
    # to'ldirilmagan bo'lsa, "hali hech kimga ruxsat berilmagan"
    # qoidasi kuchda qoladi va u LAN uchun ham amal qiladi.
    if allow_private_source() and is_private_ip(ip_address):
        return True

    zones = allowed_zones_for(ip_address)
    if not zones:
        return False
    return any(bound is None or zone_id is None or bound == zone_id for bound in zones)


def _matching_zone(ip_address: str):
    """Preflight'da ko'rsatish uchun: manzil tegishli bo'lgan faol bino."""
    from apps.regions.models import Zone

    zone_id = zone_id_for_ip(ip_address)
    if zone_id is None:
        return None
    zone = Zone.objects.select_related("region").filter(pk=zone_id).first()
    if zone is None or zone.deleted_at is not None or not zone.is_active:
        return None
    return zone


def network_preflight(*, public_ip: str, observed_ip: str = "") -> dict:
    """
    Client ishga tushishdagi tarmoq tekshiruvi.

    Client login formasini KO'RSATISHDAN OLDIN chaqiradi: agar kompyuter
    ro'yxatdagi tarmoqdan ulanmayotgan bo'lsa, operator login/parol
    kiritib, imtihon tanlab, JSHSHIR yozib, faqat o'sha yerda
    `ip_not_allowed` olishi mantiqsiz — to'siq oqimning eng boshida
    ko'rinishi kerak.

    IKKI MANZIL, BITTASI YETARLI:

      * client aytgan tashqi (public) IP — IP yoki tarmoq yozuviga mos;
      * server ko'rgan manzil (`observed_ip`) — FAQAT TARMOQ yozuviga mos
        kelsa. Tarmoq yozuvi aynan server xususiy manzilni ko'radigan
        topologiya uchun (server bino ichida, binolar VPN'da): bunday
        bino o'z tashqi IP'sini ro'yxatga kiritmaguncha login formasini
        ko'rmasdi, holbuki keyingi haqiqiy tekshiruv aynan server ko'rgan
        manzil bo'yicha o'tardi. Aniq IP yozuvlari uchun qaror avvalgidek
        client aytgan manzil bo'yicha (`test_observed_ip_alone_is_not_enough`).

    NIMANI ANGLATADI: bu tekshiruv QULAYLIK to'sig'i, himoya emas —
    client aytgan qiymatni o'zgartirish mumkin. Haqiqiy himoya
    o'zgarishsiz qoladi va u har bir client so'rovida
    `ClientBaseView.check_source_ip` orqali, FAQAT server ko'rgan
    manzil bo'yicha ishlaydi.
    """
    empty = allowlist_empty()
    enforced = ip_check_enforced()

    # Qaror jadvali — boshqa hech qanday shart yo'q:
    #
    #   public_ip ro'yxatda (IP yoki tarmoq)          -> RUXSAT
    #   observed_ip ro'yxatdagi TARMOQda              -> RUXSAT
    #   boshqa holat (jumladan noma'lum manzillar)    -> RAD
    #   nofaol yozuv                                     -> hisoblanmaydi
    #   ro'yxatda faol yozuv YO'Q                        -> `REQUIRE_ALLOWED_IP`
    matched_ip = ""
    if empty:
        allowed = not require_allowed_ip()
    else:
        if public_ip and allowed_zones_for(public_ip):
            matched_ip = public_ip
        elif observed_ip and allowed_zones_for(observed_ip, networks_only=True):
            matched_ip = observed_ip
        allowed = bool(matched_ip)

    result = {
        "allowed": allowed,
        "enforced": enforced,
        # Rad etish sababi ikki xil bo'lishi mumkin va operator uchun
        # ular BUTUNLAY boshqa: "sizning manzilingiz ro'yxatda yo'q"
        # va "ro'yxat umuman to'ldirilmagan". Ikkinchisi administrator
        # xatosi, uni operatorga "IP'ingiz noto'g'ri" deb ko'rsatish
        # nosozlikni soatlab qidirishga olib keladi.
        "allowlist_empty": empty,
        "public_ip": public_ip,
        "observed_ip": observed_ip,
        # `None` — solishtirib bo'lmadi (biror manzil noma'lum).
        "matches_observed": (
            (public_ip == observed_ip) if (public_ip and observed_ip) else None
        ),
        "zone": None,
        "region": None,
    }
    if not matched_ip:
        return result

    # Bino nomi FAQAT ko'rsatish uchun: operator "qaysi bino sifatida
    # tanildim?" degan savolga darhol javob oladi va noto'g'ri bino
    # biriktirilgani imtihon boshlangunga qadar ma'lum bo'ladi.
    zone = _matching_zone(matched_ip)
    if zone is not None:
        result["zone"] = {"id": zone.pk, "name": zone.name}
        if zone.region_id:
            result["region"] = {"id": zone.region_id, "name": zone.region.name}
    return result


def invalidate_ip_cache() -> None:
    cache.delete(IP_CACHE_KEY)
