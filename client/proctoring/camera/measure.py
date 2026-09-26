"""
Kamera o'lchovlari - serverga yuboriladigan XOM qiymatlar.

BU MODUL HECH NARSANI BAHOLAMAYDI. U "FPS 24.5" deydi, "FPS yetarli"
demaydi. Chegaralar siyosatda va ular serverda qo'llanadi
(`proctoring/services/camera_check.py`). Sabab ikkita:

  * client'ga ishonib bo'lmaydi - o'zgartirilgan nusxa "hammasi
    joyida" deb aytardi va server buni tekshira olmasdi;
  * qoida ikki joyda yashardi va ular albatta ajralib ketardi.

BLOKLOVCHI: yuz aniqlash ~50-200 ms oladi. UI thread'idan
chaqirmang - `ApiWorker` orqali fon thread'ida bajariladi.
"""

from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)

#: Yorqinlikni hisoblashda kadr shu qadam bilan siyraklashtiriladi.
#:
#: 1080p kadr uchun to'liq o'rtacha ~2 M piksel bo'yicha yuradi va
#: bu har tekshiruvda bir necha o'n millisekund. Har 4-piksel
#: yetarli: yorug'lik bahosi uchun aniqlik emas, kattalik tartibi
#: muhim.
_BRIGHTNESS_STEP = 4


def measure_all(manager, layout, *, with_face: bool = True, roles=None) -> list:
    """
    Rollar uchun o'lchovlar.

    Oqim ochilmagan kamera ham ro'yxatga TUSHADI (`opened=False`) -
    uni tashlab yuborish server tomonda "kamera umuman yo'q" va
    "kamera bor, lekin ochilmadi" holatlarini aralashtirib
    yuborardi: birinchisini administrator, ikkinchisini operator
    hal qiladi.

    `roles` - faqat shu rollar HAQIQATDA o'lchanadi. Qolganlari
    ro'yxatda `measured=False` bilan qoladi: ular "yo'q" emas,
    "bu safar tekshirilmadi" degani va server ularning oldingi
    natijasini suratchadan oladi (`camera_check._merge_measurements`).
    Ro'yxatdan butunlay chiqarib tashlash server tomonda kamerani
    yo'qolgan qilib ko'rsatardi.
    """
    wanted = set(roles) if roles else None
    return [
        measure_one(
            manager,
            camera,
            with_face=with_face and camera.role == "primary",
            measured=wanted is None or camera.role in wanted,
        )
        # Zaxiradagi qurilma O'LCHANMAYDI: server faqat `primary` va
        # `secondary` ni baholaydi va imtihonda faqat ular ishlaydi.
        for camera in layout.cameras
        if camera.in_use
    ]


def measure_one(manager, camera, *, with_face: bool, measured: bool = True) -> dict:
    """Bitta rolning o'lchovlari."""
    result = {
        "role": camera.role,
        "source": camera.source,
        "label": camera.label,
        # Qurilma KALITI serverga ham ketadi: u oldingi o'lchovni
        # shu rolga bog'lash mumkinligini aynan shundan biladi
        # (rollar almashtirilgan bo'lishi mumkin).
        "local_index": camera.local_index,
        "measured": bool(measured),
        "available": bool(camera.available),
        "opened": False,
        "is_virtual": bool(camera.is_virtual),
        "error": "" if camera.available else camera.reason,
        "frames": 0,
        "fps": 0.0,
        "width": 0,
        "height": 0,
        "latency_ms": 0,
    }
    if not measured:
        # O'LCHANMAYDI: oqim ham ochilmagan bo'lishi mumkin va
        # undan qiymat olish "0 FPS" degan soxta natija berardi.
        return result
    if camera.role == "primary":
        # `None` va `0` FARQ QILADI: birinchisi "o'lchanmadi",
        # ikkinchisi "o'lchandi va nol". Server ularni boshqacha
        # talqin qiladi (model tayyor emas / kadrda odam yo'q).
        result.update({"faces": None, "face_width_px": None, "brightness": None,
                       "face_offset": None})

    stream = manager.stream(camera.role)
    if stream is None:
        return result

    health = stream.health
    result.update(
        {
            "opened": health.state in ("online", "degraded"),
            "frames": int(health.frames_total),
            "fps": round(float(health.fps), 1),
            "latency_ms": int(health.read_latency_ms),
            "error": health.last_error or result["error"],
        }
    )

    frame, _captured_at = stream.latest_frame()
    if frame is None:
        return result

    height, width = frame.shape[:2]
    result["width"], result["height"] = int(width), int(height)
    result["opened"] = True

    if camera.role != "primary":
        return result

    result["brightness"] = _brightness(frame)
    if with_face:
        result.update(_face_metrics(frame))
    return result


# --------------------------------------------------------------------------
def _brightness(frame: np.ndarray) -> int:
    """
    Kadrning o'rtacha yorqinligi (0-255).

    Yorug'lik BGR o'rtachasi bilan emas, luma bo'yicha hisoblanadi:
    ko'z yashil kanalga ancha sezgir va oddiy o'rtacha ko'k fonli
    xonani "yorug'" deb ko'rsatardi.
    """
    sample = frame[::_BRIGHTNESS_STEP, ::_BRIGHTNESS_STEP]
    # BGR tartibi (OpenCV), koeffitsiyentlar ITU-R BT.601.
    luma = (
        sample[:, :, 0] * 0.114 + sample[:, :, 1] * 0.587 + sample[:, :, 2] * 0.299
    )
    return int(max(0, min(255, float(luma.mean()))))


def _face_metrics(frame: np.ndarray) -> dict:
    """
    Kadrdagi yuz: soni, kengligi va markazdan chetlashishi.

    Model tayyor bo'lmasa qiymatlar `None` bo'lib qoladi -
    "tekshirilmadi" degani. Uni `0` bilan almashtirish server
    tomonda "yuz topilmadi" degan XATO xulosaga olib kelardi.
    """
    from services.face_engine import FaceEngine

    engine = FaceEngine()
    if not engine.is_ready:
        return {}

    try:
        faces = engine.detect(frame)
    except Exception:
        log.exception("Tekshiruvda yuz aniqlashda xato")
        return {}

    metrics: dict = {"faces": len(faces)}
    if not faces:
        return metrics

    # Bir nechta yuz bo'lsa - eng kattasi asosiy (u kameraga eng
    # yaqin odam). `face_engine.embed_image_bytes` da ham shu qoida.
    faces.sort(key=lambda item: item["bbox"][2] - item["bbox"][0], reverse=True)
    x1, y1, x2, y2 = faces[0]["bbox"]

    height, width = frame.shape[:2]
    metrics["face_width_px"] = int(x2 - x1)

    # Markazdan chetlashish: 0 - aynan markazda, 1 - kadr chekkasida.
    # Kamera burchagini TO'G'RIDAN-TO'G'RI o'lchash uchun bosh
    # holatini baholash kerak (AI pipeline'ning ishi), bu esa uning
    # amaliy o'rinbosari: noto'g'ri qaratilgan kamerada yuz
    # markazdan uzoqda turadi.
    center_x = (x1 + x2) / 2
    center_y = (y1 + y2) / 2
    offset = max(
        abs(center_x - width / 2) / (width / 2),
        abs(center_y - height / 2) / (height / 2),
    )
    metrics["face_offset"] = round(min(1.0, float(offset)), 3)
    return metrics
