"""
Bosh holati: yaw / pitch / roll.

USUL: `cv2.solvePnP`. Yuzning 2D nuqtalari va boshning umumlashgan
3D modeli berilganda, kamera qaysi burchakdan ko'rayotganini
hisoblaydi. Bu klassik, bashorat qilinadigan va MODELSIZ usul -
qo'shimcha ONNX fayli talab qilmaydi.

NIMA UCHUN ALOHIDA NEYRON TARMOQ EMAS. Bosh holatini baholaydigan
modellar bor (6DRepNet, WHENet) va ular aniqroq, lekin:

  * yana bitta model fayli, yana bitta yuklash, yana VRAM;
  * bizga ANIQ GRADUS kerak emas. Savol "talabgor ekrandan
    chetga qaradimi?" va uning javobi ~10 gradus aniqlikda ham
    o'zgarmaydi;
  * solvePnP kirishi ALLAQACHON bor: InsightFace `2d106det`
    modeli bundle'da yotibdi (`models/buffalo_l/`) va u har
    kadrda baribir ishlaydi.

CHEKLOV VA UNI BILISH KERAK. solvePnP kamera ichki
parametrlarini (fokus masofasi, optik markaz) talab qiladi.
Ular NOMA'LUM: har bir veb-kamera boshqacha va kalibrlash
imtihon sharoitida mumkin emas. Shuning uchun ular kadr
o'lchamidan TAXMIN qilinadi (fokus ~ kadr kengligi) - bu
standart yondashuv va u BURCHAK O'ZGARISHINI to'g'ri ko'rsatadi,
lekin MUTLAQ qiymati ±10-15 gradusgacha adashishi mumkin.

Shu sababli chegaralar (`gaze_away_*`) mutlaq gradusga emas,
BOSHLANG'ICH HOLATDAN OG'ISHGA nisbatan qo'llanishi kerak -
buni `gaze_estimator.py` bajaradi.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

#: Boshning umumlashgan 3D modeli (mm, burun uchi - koordinata boshi).
#:
#: Qiymatlar antropometrik o'rtachalar. Ular aniq odamga mos
#: kelmaydi va kelishi shart emas: solvePnP nisbatlarga tayanadi.
_MODEL_POINTS = np.array(
    [
        (0.0, 0.0, 0.0),            # burun uchi
        (0.0, -330.0, -65.0),       # iyak
        (-225.0, 170.0, -135.0),    # chap ko'zning tashqi burchagi
        (225.0, 170.0, -135.0),     # o'ng ko'zning tashqi burchagi
        (-150.0, -150.0, -125.0),   # og'izning chap burchagi
        (150.0, -150.0, -125.0),    # og'izning o'ng burchagi
    ],
    dtype=np.float64,
)

#: `2d106det` (InsightFace) modelidagi mos nuqtalar indekslari.
#:
#: Tartib `_MODEL_POINTS` bilan AYNAN bir xil bo'lishi shart -
#: aks holda solvePnP mutlaqo noto'g'ri burchak qaytaradi va
#: hech qanday xato bermaydi.
LANDMARK_106 = (86, 0, 35, 93, 52, 61)

#: 5 nuqtali variant (`kps`, InsightFace har doim qaytaradi).
#:
#: `2d106det` yuklanmagan bo'lsa zaxira yo'l. Aniqlik pastroq
#: (iyak yo'q, og'iz burchaklari o'rniga og'iz chetlari), lekin
#: yaw uchun yetarli.
_MODEL_POINTS_5 = np.array(
    [
        (-225.0, 170.0, -135.0),    # chap ko'z
        (225.0, 170.0, -135.0),     # o'ng ko'z
        (0.0, 0.0, 0.0),            # burun
        (-150.0, -150.0, -125.0),   # og'iz chap
        (150.0, -150.0, -125.0),    # og'iz o'ng
    ],
    dtype=np.float64,
)


@dataclass
class HeadPose:
    """Bosh burchaklari (gradus)."""

    yaw: float = 0.0        # chapga (-) / o'ngga (+) burilish
    pitch: float = 0.0      # pastga (-) / yuqoriga (+)
    roll: float = 0.0       # yon tomonga qiyshayish
    valid: bool = False

    def as_dict(self) -> dict:
        return {
            "yaw": round(self.yaw, 1),
            "pitch": round(self.pitch, 1),
            "roll": round(self.roll, 1),
            "valid": self.valid,
        }


def estimate_head_pose(landmarks: np.ndarray, frame_shape: tuple) -> HeadPose:
    """
    Yuz nuqtalaridan bosh burchaklarini hisoblaydi.

    `landmarks` — `(106, 2)` yoki `(5, 2)` massiv (InsightFace).
    `frame_shape` — `(balandlik, kenglik)`.
    """
    import cv2

    points = np.asarray(landmarks, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] < 2:
        return HeadPose()

    if len(points) >= 106:
        model_points = _MODEL_POINTS
        image_points = points[list(LANDMARK_106), :2]
    elif len(points) == 5:
        model_points = _MODEL_POINTS_5
        image_points = points[:, :2]
    else:
        log.debug("Bosh holati uchun nuqtalar yetarli emas: %s", points.shape)
        return HeadPose()

    height, width = frame_shape[:2]
    # Kamera matritsasi TAXMIN qilinadi - sabab modul docstring'ida.
    focal = float(width)
    camera_matrix = np.array(
        [[focal, 0, width / 2.0], [0, focal, height / 2.0], [0, 0, 1]],
        dtype=np.float64,
    )
    # Distorsiya nolga tenglashtiriladi: uni kalibrlashsiz bilib
    # bo'lmaydi va veb-kameralarda u odatda kichik.
    distortion = np.zeros((4, 1), dtype=np.float64)

    try:
        ok, rotation, _translation = cv2.solvePnP(
            model_points,
            np.ascontiguousarray(image_points),
            camera_matrix,
            distortion,
            flags=cv2.SOLVEPNP_ITERATIVE,
        )
    except Exception:
        log.debug("solvePnP xatosi", exc_info=True)
        return HeadPose()

    if not ok:
        return HeadPose()

    matrix, _ = cv2.Rodrigues(rotation)
    yaw, pitch, roll = _matrix_to_euler(matrix)
    return _apply_convention(yaw, pitch, roll)


def _apply_convention(yaw: float, pitch: float, roll: float) -> HeadPose:
    """
    Xom burchaklarni loyihaning KONVENTSIYASIGA keltiradi.

    KONVENTSIYA (`HeadPose` maydonlari izohi bilan bir xil):

        yaw   > 0  -> kadrning O'NG tomoniga qaradi
        pitch < 0  -> PASTGA qaradi
        frontal    -> ikkalasi ham ~0

    "O'ng" — KADRNI KO'RAYOTGAN ODAM uchun o'ng tomon, talabgorning
    o'ng qo'li tomoni EMAS. Farq muhim: proktor ekranda kadrni
    ko'radi va "o'ngga qaradi" xabari uning ko'zi bilan o'qilishi
    kerak (masalan "o'ngdagi qo'shni stolga qaradi").

    ISHORALAR EMPIRIK ANIQLANGAN. Model nuqtalari to'plami (+Y
    yuqoriga) rasm koordinatalari (+Y pastga) bilan teskari,
    shuning uchun solvePnP xom qiymatlarni HAM siljigan (pitch
    ~±180), HAM teskari ishorada qaytaradi. Sintetik proyeksiya
    bilan o'lchandi:

        burun ko'z markazidan O'NGGA siljisa  -> xom yaw   = -30
        burun ko'z chizig'idan PASTGA siljisa -> xom pitch = -155
                                                 (o'ralgandan keyin -25)

    Ya'ni yaw teskari (inkor qilinadi), pitch esa ±180 dan
    yechilgandan keyin allaqachon to'g'ri. Konventsiyani
    o'zgartirish kerak bo'lsa - FAQAT shu funksiya.
    """
    return HeadPose(
        # Yaw TESKARI (o'lchov: o'ngga qarash xom -30 berdi),
        # pitch esa `_unwrap_pitch` dan keyin allaqachon to'g'ri
        # ishorada (pastga -> manfiy).
        yaw=-yaw,
        pitch=_unwrap_pitch(pitch),
        roll=roll,
        valid=True,
    )


def _unwrap_pitch(pitch: float) -> float:
    """
    Pitch'ni frontal yuz uchun NOL atrofiga keltiradi.

    MUAMMO. Standart 3D model nuqtalari to'plamida +Y YUQORIGA
    yo'nalgan (iyak -330, ko'zlar +170), rasm koordinatalarida esa
    +Y PASTGA. Ya'ni ular bir-biriga teskari va solvePnP frontal
    yuz uchun ~180 gradus qiymat qaytaradi:

        pastga 25 gradus  -> xom pitch +155
        frontal           -> xom pitch +180
        yuqoriga 25       -> xom pitch -155

    Bu ikki narsani buzardi va ikkalasi ham JIMGINA:

      1. Kalibrlash ayirmasi. Frontal (+180) va biroz yuqoriga
         (-179) orasidagi og'ish 359 gradus bo'lib chiqardi -
         holbuki haqiqiy og'ish 1 gradus. `looking_away` hodisasi
         talabgor mutlaqo qimirlamaganda ham chiqaverardi;
      2. Chegara qiyoslash. "|pitch| > 20 bo'lsa pastga qaradi"
         qoidasi frontal yuzda HAR DOIM rost bo'lardi.

    Bu funksiya ikkalasini ham yopadi: frontal -> 0.

    ISHORA bu funksiyada QO'LLANMAYDI - u faqat ±180 siljishini
    olib tashlaydi. Konventsiya `_apply_convention` da.
    """
    return (180.0 - pitch) if pitch > 0 else (-180.0 - pitch)


def _matrix_to_euler(matrix: np.ndarray) -> tuple:
    """
    Aylanish matritsasidan Eyler burchaklariga.

    GIMBAL LOCK holati alohida qaraladi: bosh deyarli tik yuqoriga
    yoki pastga qaraganda `sy` nolga yaqinlashadi va odatiy
    formulalar beqaror bo'ladi (burchaklar sakraydi). Imtihonda bu
    holat kam uchraydi, lekin sakragan qiymat "bosh harakati ko'p"
    degan soxta hodisa berardi.
    """
    sy = math.sqrt(matrix[0, 0] ** 2 + matrix[1, 0] ** 2)
    if sy < 1e-6:
        pitch = math.atan2(-matrix[1, 2], matrix[1, 1])
        yaw = math.atan2(-matrix[2, 0], sy)
        roll = 0.0
    else:
        pitch = math.atan2(matrix[2, 1], matrix[2, 2])
        yaw = math.atan2(-matrix[2, 0], sy)
        roll = math.atan2(matrix[1, 0], matrix[0, 0])

    # XOM qiymatlar. Ishora va ±180 siljishi `_normalize_pitch` da
    # tuzatiladi - bu funksiya faqat matritsani burchaklarga
    # o'giradi va hech qanday konventsiya qo'llamaydi.
    return math.degrees(yaw), math.degrees(pitch), math.degrees(roll)
