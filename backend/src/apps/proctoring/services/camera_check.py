"""
Kamera tekshiruvi: client O'LCHAYDI, server BAHOLAYDI.

MAS'ULIYAT BO'LINISHINING SABABI. Client kadrni ko'radi va faqat u
o'lchay oladi: FPS, rezolyutsiya, kechikish, kadrdagi yuz, yorug'lik.
Lekin "bu yetarlimi?" degan savol o'lchov emas, QAROR — va u siyosatga
bog'liq (`ProctoringPolicy.min_fps` va h.k.). Qarorni client'ga
qoldirish ikki narsani buzardi:

  * client'ga ishonib bo'lmaydi. O'zgartirilgan nusxa "hammasi
    joyida" deb aytardi va server buni tekshira olmasdi;
  * qoida ikki joyda yashardi — siyosatda va client kodida. Ular
    albatta ajralib ketardi va farq faqat imtihon kuni ko'rinardi.

Shuning uchun bu yerga XOM O'LCHOVLAR keladi va barcha chegaralar shu
yerda qo'llanadi. Client faqat natijani ko'rsatadi.

Bu naqsh loyihada allaqachon bor: `AccessAttemptView` ham client
aytgan xulosani qabul qilmaydi, balki o'z xulosasini qaytadan
hisoblaydi.

TEKSHIRUVLAR RO'YXATI (texnik topshiriqdagi 14 ta):

     1. Kamera mavjudmi            -> `available`
     2. Kamera ochildimi           -> `accessible`
     3. Oqim yaroqlimi             -> `stream`
     4. FPS yetarlimi              -> `fps`
     5. Rezolyutsiya yetarlimi     -> `resolution`
     6. Kadr kechikishi            -> `latency`
     7. Yuz aniqlandimi            -> `face` (faqat birlamchi)
     8. Yuz yetarli ko'rinadimi    -> `face_size` (faqat birlamchi)
     9. Yorug'lik maqbulmi         -> `lighting` (faqat birlamchi)
    10. Kamera burchagi maqbulmi   -> `angle` (faqat birlamchi)
    11. IP kamera javob beradimi   -> `accessible` (manba `ip`)
    12. Veb-kamera ochiladimi      -> `accessible` (manba `local`)
    13. Birlamchi kamera yaroqlimi -> `primary_ready` (yakuniy)
    14. Ikkilamchi kamera yaroqli  -> `secondary_ready` (yakuniy)

11 va 12 ALOHIDA tekshiruv emas: ikkalasi ham "kamera ochildimi"
degan bitta savol va farq faqat sababda (`detail` da manba ko'rsatiladi).
Ularni ajratish ro'yxatni uzaytirardi, lekin operatorga hech narsa
qo'shmasdi.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from apps.common.redis_client import get_redis

logger = logging.getLogger(__name__)

#: Tekshiruv natijasining darajalari.
READY = "ready"
WARNING = "warning"
FAILED = "failed"

#: Yakuniy holat og'irlik tartibida — eng yomoni yutadi.
_SEVERITY = {READY: 0, WARNING: 1, FAILED: 2}

ROLE_LABEL = {"primary": "Birlamchi (yuz)", "secondary": "Ikkilamchi (stol/xona)"}


def _limits() -> dict:
    return settings.PROCTORING["CAMERA_CHECK"]


# --------------------------------------------------------------------------
# Baholash
# --------------------------------------------------------------------------
def evaluate(*, cameras: list, policy: dict, previous: dict | None = None) -> dict:
    """
    Xom o'lchovlardan tekshiruv natijasini yig'adi.

    `cameras` — client yuborgan o'lchovlar ro'yxati.
    `policy` — `config["proctoring"]` bloki.
    `previous` — shu qurilmaning oldingi suratchasi (Redis'dan).

    HAR KAMERA ALOHIDA TEKSHIRILADI. Operator odatda avval yuz
    kamerasini tekshiradi (tavsiya etilgani ham shu: aynan u
    shaxsni aniqlaydi), ikkinchisini esa siyosat talab qilsagina.
    Shuning uchun bu yerga BITTA rol ham kelishi mumkin va o'shanda
    ikkinchisining oldingi natijasi `previous` dan olinadi —
    aks holda har tekshiruv ikkinchi kamerani "tekshirilmagan"
    holatiga qaytarardi va operator ularni har safar birga
    tekshirishga majbur bo'lardi.

    Qaytadi: `{status, can_start, checks, blockers, cameras, measurements}`.
    """
    camera_policy = (policy or {}).get("camera") or {}
    by_role = _merge_measurements(cameras or [], previous)

    checks: list[dict] = []
    for role in ("primary", "secondary"):
        required = bool(
            camera_policy.get(
                "primary_required" if role == "primary" else "secondary_required",
                role == "primary",
            )
        )
        expected = role == "primary" or int(camera_policy.get("count") or 1) > 1
        checks.extend(
            _check_camera(
                role=role,
                measured=by_role.get(role),
                camera_policy=camera_policy,
                required=required,
                expected=expected,
            )
        )

    blockers = [item for item in checks if item["status"] == FAILED and item["blocking"]]
    status = _worst(checks)

    return {
        "status": status,
        # Client'ning o'z xulosasi QABUL QILINMAYDI — bu qiymat faqat
        # shu yerda hisoblanadi va aynan u imtihon boshlanishini hal
        # qiladi (`proctoring.start`).
        "can_start": not blockers,
        "checks": checks,
        "blockers": [item["code"] for item in blockers],
        "cameras": {
            role: _camera_summary(role, by_role.get(role), checks)
            for role in ("primary", "secondary")
        },
        # XOM O'LCHOVLAR SAQLANADI: keyingi tekshiruv faqat bitta
        # kamerani qamrasa, qolganining natijasi shu yerdan olinadi.
        # Ular dalil sifatida ham qoladi (`ExamSession.camera_check`):
        # "nega bu mashinada ikkinchi kamerasiz boshlandi?" degan
        # savolga faqat o'lchovlarning o'zi javob beradi.
        "measurements": by_role,
    }


def _merge_measurements(cameras: list, previous: dict | None) -> dict:
    """
    Yangi o'lchovlarni oldingilari ustiga qo'yadi.

    UCH QOIDA:

      * `measured=False` — kamera bor, lekin bu safar tekshirilmadi.
        O'shanda oldingi o'lchov ishlatiladi;
      * oldingi o'lchov ESKIRGAN bo'lsa (`SNAPSHOT_TTL` dan katta)
        tashlanadi. Aks holda ikkinchi kamerani qayta-qayta
        tekshirish orqali birinchisining eskirgan natijasini cheksiz
        "yangi" holda ushlab turish mumkin bo'lardi;
      * QURILMA ALMASHGAN bo'lsa ham tashlanadi. Operator rollarni
        almashtirishi mumkin va o'shanda "birlamchi" roli boshqa
        jismoniy kameraga tegishli bo'ladi — eski o'lchovni unga
        yopishtirib qo'yish soxta "tekshirildi" degani bo'lardi.
    """
    now = timezone.now()
    stale_before = now - timedelta(seconds=int(_limits()["SNAPSHOT_TTL"]))
    kept = (previous or {}).get("measurements") or {}

    merged: dict = {}
    for item in cameras:
        role = item.get("role")
        if not role:
            continue
        if item.get("measured", True):
            merged[role] = {**item, "measured": True, "measured_at": now.isoformat()}
            continue

        earlier = kept.get(role)
        if _is_reusable(earlier, item, stale_before):
            merged[role] = earlier
        else:
            # Oldingi natija yaroqsiz — kamera "tekshirilmagan"
            # holatida qoladi. Uni o'lchov sifatida ko'rsatish
            # tekshirilmagan kamerani tekshirilgan qilib ko'rsatardi.
            merged[role] = {**item, "measured": False, "measured_at": ""}
    return merged


def _is_reusable(earlier: dict | None, current: dict, stale_before) -> bool:
    """Oldingi o'lchov shu rolga hali ham tegishlimi."""
    if not earlier or not earlier.get("measured"):
        return False

    stamp = earlier.get("measured_at") or ""
    try:
        measured_at = datetime.fromisoformat(stamp)
    except ValueError:
        return False
    if timezone.is_naive(measured_at):
        measured_at = timezone.make_aware(measured_at)
    if measured_at < stale_before:
        return False

    # Qurilma AYNAN o'shami. Lokal kamerada indeks hal qiladi (nom
    # takrorlanishi mumkin - bir xil modeldagi ikkita kamera), IP
    # kamerada esa nom.
    if earlier.get("source") != current.get("source"):
        return False
    if (current.get("source") or "local") == "local":
        return earlier.get("local_index") == current.get("local_index")
    return (earlier.get("label") or "") == (current.get("label") or "")

def _check_camera(*, role, measured, camera_policy, required, expected) -> list:
    """Bitta rol uchun barcha tekshiruvlar."""
    label = ROLE_LABEL.get(role, role)
    checks: list[dict] = []

    def add(code, title, status, detail="", blocking=None):
        checks.append(
            {
                "code": "{}_{}".format(role, code),
                "role": role,
                "title": "{} — {}".format(label, title),
                "status": status,
                "detail": detail,
                # To'siq FAQAT siyosat shu kamerani TALAB qilganda.
                # Ikkilamchi kamera yo'qligi odatiy hol va u imtihonni
                # to'xtatmasligi kerak.
                "blocking": required if blocking is None else blocking,
            }
        )

    # --- 1. Mavjudmi ---
    if measured is None or not measured.get("available"):
        if not expected:
            # Siyosat bu kamerani kutmaydi — tekshiruv ham qilinmaydi.
            return []
        add(
            "available",
            "kamera topilmadi",
            FAILED,
            (measured or {}).get("error") or "Qurilma aniqlanmadi yoki biriktirilmagan",
        )
        add("ready", "yaroqli emas", FAILED, "Kamera topilmagani sababli")
        return checks

    add("available", "kamera topildi", READY, measured.get("label", ""))

    # --- Bu safar TEKSHIRILDIMI ---
    #
    # "Kamera topilmadi" va "kamera bor, lekin tekshirilmagan" —
    # BOSHQA-BOSHQA holatlar: birinchisini operator kabel bilan hal
    # qiladi, ikkinchisini tugmani bosib. Kameralar alohida
    # tekshirilgani uchun ikkinchi holat endi odatiy va uni "topilmadi"
    # deb ko'rsatish operatorni mavjud bo'lmagan nosozlikni qidirishga
    # majbur qilardi.
    if not measured.get("measured", True):
        add(
            "checked",
            "hali tekshirilmadi",
            FAILED if required else WARNING,
            "Shu kamera uchun «Tekshirish» tugmasini bosing",
        )
        add(
            "ready",
            "tekshirilmagan",
            FAILED if required else WARNING,
            "",
            blocking=required,
        )
        return checks

    source = measured.get("source") or "local"
    source_label = "IP kamera" if source == "ip" else "veb-kamera"

    # --- 2/11/12. Ochildimi (manba turi `detail` da) ---
    if not measured.get("opened"):
        add(
            "accessible",
            "ochilmadi",
            FAILED,
            measured.get("error") or "{} javob bermadi".format(source_label),
        )
        add("ready", "yaroqli emas", FAILED, "Oqim ochilmagani sababli")
        return checks
    add("accessible", "ochildi", READY, source_label)

    # --- 3. Oqim yaroqlimi ---
    frames = int(measured.get("frames") or 0)
    if frames <= 0:
        add("stream", "kadr kelmadi", FAILED, "Oqim ochildi, lekin kadr olinmadi")
        add("ready", "yaroqli emas", FAILED, "Kadr kelmagani sababli")
        return checks
    add("stream", "oqim yaroqli", READY, "{} kadr o'lchandi".format(frames))

    # --- 4. FPS ---
    fps = float(measured.get("fps") or 0.0)
    min_fps = int(camera_policy.get("min_fps") or 0)
    if min_fps and fps < min_fps:
        add(
            "fps",
            "FPS past",
            FAILED,
            "o'lchandi {:.1f}, talab {} — kuzatuv uzuq-yuluq bo'ladi".format(fps, min_fps),
        )
    else:
        add("fps", "FPS yetarli", READY, "{:.1f}".format(fps))

    # --- 5. Rezolyutsiya ---
    width = int(measured.get("width") or 0)
    height = int(measured.get("height") or 0)
    min_width = int(camera_policy.get("min_width") or 0)
    min_height = int(camera_policy.get("min_height") or 0)
    if width < min_width or height < min_height:
        add(
            "resolution",
            "rezolyutsiya past",
            FAILED,
            "{}x{}, talab {}x{}".format(width, height, min_width, min_height),
        )
    else:
        add("resolution", "rezolyutsiya yetarli", READY, "{}x{}".format(width, height))

    # --- Virtual qurilma ---
    #
    # Bu YAGONA tekshiruv, u kamera majburiy bo'lmasa ham TO'SIQ:
    # qolganlari sifat masalasi, bu esa xavfsizlik qoidasi. Virtual
    # kamera — oldindan yozilgan videoni jonli oqim sifatida
    # ko'rsatishning eng oson yo'li.
    if measured.get("is_virtual") and not camera_policy.get("allow_virtual", False):
        add(
            "virtual",
            "virtual qurilma",
            FAILED,
            "«{}» virtual kamera va bu imtihonda taqiqlangan".format(
                measured.get("label") or "?"
            ),
            blocking=True,
        )

    # --- 6. Kechikish ---
    latency = int(measured.get("latency_ms") or 0)
    max_latency = int(_limits()["MAX_FRAME_LATENCY_MS"])
    if latency > max_latency:
        # OGOHLANTIRISH: yuqori kechikish kuzatuvni buzmaydi, faqat
        # hodisa vaqtini siljitadi. Uni to'siqqa aylantirish sekin
        # mashinalarda imtihonni umuman boshlatmasdi.
        add(
            "latency",
            "kadr kechikmoqda",
            WARNING,
            "{} ms (chegara {} ms)".format(latency, max_latency),
            blocking=False,
        )
    else:
        add("latency", "kechikish maqbul", READY, "{} ms".format(latency))

    if role == "primary":
        checks.extend(_check_face(measured, required))

    # --- 13/14. Yakuniy xulosa ---
    worst = _worst(checks)
    add(
        "ready",
        {READY: "yaroqli", WARNING: "yaroqli (ogohlantirish bilan)", FAILED: "yaroqli emas"}[worst],
        worst,
        "",
        blocking=required and worst == FAILED,
    )
    return checks


def _check_face(measured: dict, required: bool) -> list:
    """
    Yuzga oid tekshiruvlar — FAQAT birlamchi kamerada.

    Ikkilamchi kamera stolga qaragan va unda yuz BO'LMASLIGI normal
    holat. Uni ham tekshirish har bir to'g'ri o'rnatilgan tizimda
    soxta xato berardi.
    """
    limits = _limits()
    checks: list[dict] = []

    def add(code, title, status, detail="", blocking=False):
        checks.append(
            {
                "code": "primary_{}".format(code),
                "role": "primary",
                "title": "{} — {}".format(ROLE_LABEL["primary"], title),
                "status": status,
                "detail": detail,
                "blocking": blocking,
            }
        )

    faces = measured.get("faces")
    if faces is None:
        # Client yuz tekshiruvini o'tkazmagan (model yuklanmagan yoki
        # modul o'chirilgan). "Aniqlanmadi" va "yuz yo'q" BOSHQA
        # holatlar va ularni aralashtirish soxta xato berardi.
        add("face", "yuz tekshirilmadi", WARNING, "Model hali tayyor emas")
        return checks

    faces = int(faces)
    if faces == 0:
        # TO'SIQ EMAS: tekshiruv paytida talabgor hali kelmagan
        # bo'lishi mumkin — operator kamerani kun boshida sozlaydi.
        # Haqiqiy shaxs tekshiruvi FaceID sahifasida va u alohida
        # to'siq.
        add("face", "yuz topilmadi", WARNING, "Kadrda odam yo'q")
        return checks
    if faces > 1:
        add("face", "kadrda bir nechta odam", WARNING, "{} ta yuz".format(faces))
    else:
        add("face", "yuz aniqlandi", READY)

    # --- 8. Yuz yetarli ko'rinadimi ---
    face_width = int(measured.get("face_width_px") or 0)
    min_face = int(limits["MIN_FACE_WIDTH_PX"])
    if face_width and face_width < min_face:
        add(
            "face_size",
            "yuz juda uzoqda",
            WARNING,
            "{} px (kamida {} px) — kamerani yaqinlashtiring".format(face_width, min_face),
        )
    elif face_width:
        add("face_size", "yuz yetarli ko'rinadi", READY, "{} px".format(face_width))

    # --- 9. Yorug'lik ---
    brightness = measured.get("brightness")
    if brightness is not None:
        brightness = int(brightness)
        low, high = int(limits["MIN_BRIGHTNESS"]), int(limits["MAX_BRIGHTNESS"])
        if brightness < low:
            add("lighting", "yorug'lik yetishmaydi", WARNING, "{}/255".format(brightness))
        elif brightness > high:
            add("lighting", "yorug'lik ortiqcha", WARNING, "{}/255".format(brightness))
        else:
            add("lighting", "yorug'lik maqbul", READY, "{}/255".format(brightness))

    # --- 10. Kamera burchagi ---
    #
    # Burchak TO'G'RIDAN-TO'G'RI o'lchanmaydi (buning uchun bosh
    # holatini baholash kerak, u esa AI pipeline'ning ishi). Bu
    # yerda uning O'RNIGA yuzning kadrdagi joylashuvi ishlatiladi:
    # kamera noto'g'ri qaratilgan bo'lsa, yuz markazdan uzoqda yoki
    # chekkada turadi.
    offset = measured.get("face_offset")
    if offset is not None:
        offset = float(offset)
        limit = float(limits["MAX_FACE_OFFSET"])
        if offset > limit:
            add(
                "angle",
                "kamera burchagi noto'g'ri",
                WARNING,
                "yuz markazdan {:.0f}% chetda — kamerani to'g'rilang".format(offset * 100),
            )
        else:
            add("angle", "kamera burchagi maqbul", READY)
    return checks


def _worst(checks: list) -> str:
    if not checks:
        return READY
    return max((item["status"] for item in checks), key=lambda value: _SEVERITY[value])


def _camera_summary(role: str, measured, checks: list) -> dict:
    """
    Bitta kameraning qisqacha holati.

    `checked` endi "shu kamera O'LCHANDIMI" degan savolga javob
    beradi (ilgari "shu rol baholandimi" edi). Farq kameralar alohida
    tekshirila boshlagach paydo bo'ldi: rol baholanadi, lekin
    o'lchovi bo'lmasligi mumkin — va aynan shu farqni operator
    ekranda ko'rishi kerak.
    """
    role_checks = [item for item in checks if item["role"] == role]
    return {
        "checked": bool((measured or {}).get("measured")),
        "evaluated": bool(role_checks),
        "status": _worst(role_checks) if role_checks else READY,
        "label": (measured or {}).get("label", ""),
        "source": (measured or {}).get("source", ""),
        "measured_at": (measured or {}).get("measured_at", ""),
    }


# --------------------------------------------------------------------------
# Redis'dagi suratcha
# --------------------------------------------------------------------------
def snapshot_key(device_id: str) -> str:
    return "cam:check:{}".format(device_id)


def store(device_id: str, snapshot: dict) -> None:
    """
    Tekshiruv natijasini saqlaydi.

    NIMA UCHUN REDIS, DB EMAS. Tekshiruv sessiya YARATILISHIDAN oldin
    o'tadi (login'dan keyin, talabgor tanlanishidan oldin), ya'ni uni
    yozib qo'yadigan qator hali yo'q. Qurilmaga bog'lash mumkin
    (`DeviceToken`), lekin bu har bir tekshiruvda UPDATE degani va
    imtihon kunining boshida 500 mashina bir vaqtda uni bajaradi.

    Suratcha `proctoring/start/` da o'qiladi va o'sha yerda
    `ExamSession.camera_check` ga KO'CHIRILADI — dalil sifatida
    doimiy qoladigan nusxa aynan o'sha.
    """
    try:
        get_redis().set(
            snapshot_key(device_id),
            json.dumps(snapshot),
            ex=int(_limits()["SNAPSHOT_TTL"]),
        )
    except Exception:
        # Redis yo'q bo'lsa tekshiruv NATIJASI yo'qoladi va
        # `proctoring/start/` uni "eskirgan" deb hisoblaydi. Bu
        # to'g'ri xulq: tekshirilmagan mashinada imtihon boshlanmasin.
        logger.warning("Kamera tekshiruvini saqlab bo'lmadi", exc_info=True)


def load(device_id: str) -> dict | None:
    try:
        raw = get_redis().get(snapshot_key(device_id))
    except Exception:
        logger.warning("Kamera tekshiruvini o'qib bo'lmadi", exc_info=True)
        return None
    return json.loads(raw) if raw else None


def clear(device_id: str) -> None:
    try:
        get_redis().delete(snapshot_key(device_id))
    except Exception:
        logger.debug("Kamera tekshiruvini o'chirib bo'lmadi", exc_info=True)
