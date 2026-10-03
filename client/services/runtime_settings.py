"""
Server boshqaradigan sozlamalar — YAGONA o'qish nuqtasi.

IKKI QATLAM (`CLAUDE.md`: "Client sozlamalari: .env va panel"):
`config.py` dagi bir qator qiymatlar endi faqat ZAXIRA, ularning egasi
esa admin paneldagi `Setting` profili (server `AppState.config` da
beradi). Qoida bitta: SERVER QIYMATI USTUN, `.env` faqat server
javob bermagan yoki kalitni bilmaydigan eski server bo'lgan holatda.

NIMA UCHUN MARKAZLASHGAN. Ilgari har sahifa o'z tekshiruvini yozardi
(`face.interval` ni bir sahifa `int(float(...) * 1000)` qilib o'qir,
boshqasi umuman o'qimasdi) va natija bir xil emas edi: panelda
"Heartbeat intervali" turardi, client esa `.env` dagi 30 s bilan
ishlardi. Endi har bir kalit uchun uchta savol SHU YERDA hal
qilinadi va jadvalda ko'rinib turadi:

  * zaxirasi `.env` dagi QAYSI o'zgaruvchi;
  * server birligi -> client birligi (soniya -> ms, foiz -> ulush);
  * qiymat qaysi chegaraga siqiladi (buzilgan yoki eski qiymat
    taymerni 0 ms ga qo'yib, clientni qotirmasligi kerak).

QACHON O'QILADI — chaqiruvchining ishi va u muhim: `AppState.config`
login'da GLOBAL profil bilan to'ladi va "Davom etish" bosilganda
IMTIHON profili bilan almashtiriladi. Imtihonga oid qiymatlar
(FaceID oqimi, yozuv, tahdid to'sig'i) shuning uchun imtihon profili
kelgandan KEYIN o'qiladi; presence esa login'da (u imtihondan
tashqarida ishlaydi va profilga bog'liq emas).

Qt yo'q, tarmoq yo'q — sof funksiya, testda tekshiriladi
(`tests/test_runtime_settings.py`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping, Optional

import config as _env

log = logging.getLogger(__name__)

_MISSING = object()


@dataclass(frozen=True)
class Spec:
    """Bitta server kaliti: zaxirasi, turi, birligi va chegarasi."""

    #: `config.py` dagi zaxira o'zgaruvchi nomi (u CLIENT birligida).
    env: str
    #: `int`, `float` yoki `bool`.
    kind: type
    #: Server qiymati shunga ko'paytiriladi (soniya -> ms: 1000,
    #: foiz -> ulush: 0.01). Zaxiraga QO'LLANMAYDI - u allaqachon
    #: client birligida.
    scale: float = 1.0
    #: Chegara CLIENT birligida (zaxiraga ham qo'llanadi).
    minimum: Optional[float] = None
    maximum: Optional[float] = None


#: Server kaliti (`AppState.config` ichidagi nuqtali yo'l) -> tavsif.
#:
#: Chegaralar serverdagi validatorlar bilan mos (`controls.Setting`),
#: lekin ular bu yerda ikkinchi marta turadi va bu ataylab: eski server
#: yoki qo'lda tahrirlangan baza chegarasiz qiymat yuborishi mumkin, va
#: `QTimer.setInterval(0)` yoki `deque(maxlen=0)` clientni jimgina
#: buzardi.
SPECS: dict[str, Spec] = {
    # --- FaceID (imtihon profili, FaceID sahifasida o'qiladi) ---
    "face.guide_seconds": Spec("FACE_GUIDE_SECONDS", int, minimum=0, maximum=30),
    "face.match_streak": Spec("FACE_MATCH_STREAK", int, minimum=1, maximum=30),
    "face.fail_streak": Spec("FACE_FAIL_STREAK", int, minimum=1, maximum=300),
    "face.fail_min_seconds": Spec("FACE_FAIL_MIN_SECONDS", float, minimum=1, maximum=120),
    # Davriy tekshiruv oralig'i: server soniyada, taymer millisekundda.
    "face.interval": Spec(
        "PERIODIC_FACE_INTERVAL_MS", int, scale=1000, minimum=1000, maximum=600_000
    ),
    # Test davomida yuz juda uzoq (`face_presence.FaceEpisodes`), soniyada.
    "face.far_warn_s": Spec("FACE_FAR_WARN_S", float, minimum=1, maximum=600),
    "face.far_unverified_s": Spec("FACE_FAR_UNVERIFIED_S", float, minimum=1, maximum=3600),
    # --- Ekran yozuvi (imtihon profili, test sahifasi ochilganda) ---
    "capture.screen_record": Spec("SCREEN_RECORD_ENABLED", bool),
    "capture.record_fps": Spec("SCREEN_RECORD_FPS", float, minimum=0.5, maximum=15),
    "capture.record_width": Spec("SCREEN_RECORD_WIDTH", int, minimum=640, maximum=3840),
    "capture.record_pip_percent": Spec(
        "SCREEN_RECORD_PIP_RATIO", float, scale=0.01, minimum=0.05, maximum=0.30
    ),
    # --- Skrinshot: serverga ham yuboriladimi (imtihon profili) ---
    "capture.upload": Spec("SCREENSHOT_UPLOAD", bool),
    # --- Skrinshot kamera tasmasi (imtihon profili) ---
    "capture.camera_overlay": Spec("SCREENSHOT_CAMERA_OVERLAY", bool),
    "capture.camera_overlay_percent": Spec(
        "SCREENSHOT_PIP_RATIO", float, scale=0.01, minimum=0.05, maximum=0.40
    ),
    # --- Tahdid to'sig'i (imtihon profili, "Davom etish" da) ---
    "rdp.block_exam": Spec("THREAT_BLOCK_EXAM", bool),
    # --- Tarmoq (imtihon profili, sessiya boshlanganda) ---
    "network.heartbeat_interval": Spec(
        "HEARTBEAT_INTERVAL_MS", int, scale=1000, minimum=5_000, maximum=300_000
    ),
    "network.event_batch_interval": Spec(
        "EVENT_FLUSH_INTERVAL_MS", int, scale=1000, minimum=1_000, maximum=60_000
    ),
    "network.offline_buffer_size": Spec(
        "OFFLINE_BUFFER_SIZE", int, minimum=100, maximum=50_000
    ),
    # --- Presence (login'da, global profil; server doimiysidan) ---
    "network.presence_interval": Spec(
        "PRESENCE_PING_MS", int, scale=1000, minimum=10_000, maximum=600_000
    ),
}


def fallback(key: str) -> Any:
    """Kalitning `.env` zaxirasi (client birligida, chegaraga siqilgan)."""
    spec = SPECS[key]
    return _clamp(_coerce(getattr(_env, spec.env), spec.kind), spec)


def get(config: Optional[Mapping], key: str, *, default: Any = _MISSING) -> Any:
    """
    `config` dagi server qiymati (client birligida) yoki zaxira.

    `config` - `AppState.config` (handshake yoki imtihon profili).
    Kalit yo'q, `None` yoki o'qib bo'lmaydigan bo'lsa - zaxira:
    `default` berilgan bo'lsa u, aks holda `.env` dagi qiymat.
    Noto'g'ri qiymat ISTISNO BERMAYDI: sozlama imtihonning sharti
    emas va buzilgan bitta maydon sahifani yiqitmasligi kerak.
    """
    spec = SPECS[key]
    base = fallback(key) if default is _MISSING else default

    raw = _lookup(config, key)
    if raw is None:
        return base

    scaled = spec.scale != 1.0 and spec.kind is not bool
    # Birlik o'zgaradigan kalit avval KASR son sifatida o'qiladi:
    # 2.5 s ni butun songa keltirib, keyin ms ga o'girish 2000 ms
    # berardi.
    value = _coerce(raw, float if scaled else spec.kind)
    if value is None:
        log.warning("Sozlama '%s' o'qilmadi (%r) - zaxira ishlatildi", key, raw)
        return base
    if scaled:
        value = value * spec.scale
        value = int(round(value)) if spec.kind is int else round(value, 6)
    return _clamp(value, spec)


# ----------------------------------------------------------------------
def _lookup(config: Optional[Mapping], key: str) -> Any:
    node: Any = config or {}
    for part in key.split("."):
        if not isinstance(node, Mapping):
            return None
        node = node.get(part)
        if node is None:
            return None
    return node


def _coerce(raw: Any, kind: type) -> Any:
    """Qiymatni turga keltiradi; bo'lmasa `None`."""
    if kind is bool:
        # `bool("false")` - True. Server JSON bool beradi, lekin
        # zaxira va eski serverlar satr yoki 0/1 berishi mumkin.
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return bool(raw)
        text = str(raw).strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off", ""):
            return False
        return None
    try:
        if isinstance(raw, bool):
            # `True` ni 1 deb o'qish - aniq xato ma'lumot, qiymat emas.
            return None
        number = float(raw)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return int(round(number)) if kind is int else number


def _clamp(value: Any, spec: Spec) -> Any:
    if value is None or spec.kind is bool:
        return value
    if spec.minimum is not None and value < spec.minimum:
        value = spec.minimum
    if spec.maximum is not None and value > spec.maximum:
        value = spec.maximum
    return spec.kind(value)
