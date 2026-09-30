"""
Sintetik so'rov tanalari — client aynan qanday shaklda yuborsa, shunday.

Manba (client kodi, o'zgartirilmaydi):

* skrinshot  — `client/services/screen_capture.py:encode_jpeg`
  (1920 px, sifat 80, optimallashtirilgan progressiv JPEG) + kamera
  tasmasi ostida (`camera_overlay._compose`: kenglikning 16% i,
  kamera 16:9 → tasma ~190 px). Natija ~1920x1270.
* yuz kadri  — `client/services/camera_worker.py:encode_jpeg`
  (butun kamera kadri 1280x720, sifat 85, OpenCV).
* hujjat rasmi — platforma `image_base64` (3x4 surat, ~300x400).
* embedding  — 512 ta float, `json.dumps(list)` (multipart ichida satr).
* hodisa     — `client/services/monitoring.py:push_event` shakli.

RASM MAZMUNI SINTETIK: JPEG hajmi mazmunga bog'liq. Test sahifasining
skrinshoti (oq fon, matn) va shovqinli kamera kadri taqlid qilinadi;
haqiqiy qiymat bilan farqni `tools/measure_payloads.py` ko'rsatadi
(client izohidagi o'lchov: 1920/80 da ~157 KB).

Faqat Pillow (Locust venv'ida ham bor) — numpy/cv2 shart emas.
"""

from __future__ import annotations

import io
import json
import random
import struct
import uuid
from datetime import datetime, timezone
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SCREEN_W, SCREEN_H = 1920, 1080
CAMERA_W, CAMERA_H = 1280, 720


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _noise_tile(width: int, height: int, sigma: float, seed: int) -> Image.Image:
    """Kamera kadri: gradient fon + sensor shovqini + "yuz" ovali."""
    rnd = random.Random(seed)
    base = Image.linear_gradient("L").resize((width, height)).convert("RGB")
    tint = Image.new("RGB", (width, height), (rnd.randint(60, 120), rnd.randint(60, 110), rnd.randint(50, 100)))
    img = Image.blend(base, tint, 0.6)
    draw = ImageDraw.Draw(img)
    cx, cy = width // 2, int(height * 0.47)
    fw, fh = int(height * 0.32), int(height * 0.42)
    draw.ellipse((cx - fw // 2, cy - fh // 2, cx + fw // 2, cy + fh // 2), fill=(200, 160, 140))
    draw.rectangle((cx - fw, cy + fh // 2, cx + fw, height), fill=(40, 50, 90))
    noise = Image.effect_noise((width, height), sigma).convert("RGB")
    img = Image.blend(img, noise, 0.18)
    return img.filter(ImageFilter.GaussianBlur(0.6))


def _jpeg(img: Image.Image, quality: int, *, progressive: bool) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=progressive, progressive=progressive)
    return buf.getvalue()


def _screen(seed: int) -> Image.Image:
    """Test platformasi sahifasi: sarlavha, savol matni, variantlar."""
    rnd = random.Random(seed)
    img = Image.new("RGB", (SCREEN_W, SCREEN_H), (246, 247, 250))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, SCREEN_W, 72), fill=(24, 63, 128))
    d.text((32, 22), f"Test platformasi — savol {rnd.randint(1, 100)} / 100", fill="white", font=_font(28))
    d.rectangle((1600, 90, 1900, 1060), fill=(255, 255, 255), outline=(210, 214, 222))
    for n in range(100):  # savollar navigatsiyasi
        x, y = 1620 + (n % 5) * 56, 110 + (n // 5) * 46
        d.rectangle((x, y, x + 44, y + 36), outline=(150, 160, 175),
                    fill=(210, 235, 215) if rnd.random() < 0.5 else (255, 255, 255))
        d.text((x + 8, y + 8), str(n + 1), fill=(40, 40, 40), font=_font(16))
    d.rectangle((24, 90, 1580, 1060), fill=(255, 255, 255), outline=(210, 214, 222))
    words = ("hisoblang funksiya qiymati tenglama berilgan uchburchak tomoni burchak "
             "sonlar ketma-ketligi javobni toping agar bo'lsa u holda quyidagilardan "
             "qaysi biri to'g'ri matn asosida xulosa").split()
    y = 120
    for _ in range(14):
        line = " ".join(rnd.choice(words) for _ in range(rnd.randint(9, 16)))
        d.text((60, y), line, fill=(30, 30, 30), font=_font(24))
        y += 38
    for k, label in enumerate("ABCD"):
        top = 700 + k * 80
        d.rounded_rectangle((60, top, 1540, top + 62), 10, outline=(180, 186, 196),
                            fill=(232, 240, 255) if k == 1 else (255, 255, 255))
        text = " ".join(rnd.choice(words) for _ in range(rnd.randint(4, 9)))
        d.text((90, top + 18), f"{label})  {text}", fill=(30, 30, 30), font=_font(24))
    return img


def _with_camera_strip(screen: Image.Image, seed: int) -> Image.Image:
    """`camera_overlay._compose`: ekran OSTIGA tasma, ikki kamera + vaqt."""
    box_w = int(round(SCREEN_W * 0.16))
    box_h = int(box_w * CAMERA_H / CAMERA_W)
    margin = 8
    strip_h = box_h + 2 * margin
    canvas = Image.new("RGB", (SCREEN_W, SCREEN_H + strip_h), (18, 18, 20))
    canvas.paste(screen, (0, 0))
    cam = _noise_tile(box_w, box_h, 40, seed)
    canvas.paste(cam, (SCREEN_W - box_w - margin, SCREEN_H + margin))
    canvas.paste(_noise_tile(box_w, box_h, 40, seed + 1), (margin, SCREEN_H + margin))
    ImageDraw.Draw(canvas).text(
        (SCREEN_W // 2 - 120, SCREEN_H + strip_h // 2 - 8), now_iso()[:19],
        fill=(230, 230, 230), font=_font(16),
    )
    return canvas


@lru_cache(maxsize=16)
def screenshot_jpeg(variant: int = 0, quality: int = 80) -> bytes:
    """Savol kadri (1920 px, sifat 80, progressiv) — ~server qabul qiladigan shakl."""
    return _jpeg(_with_camera_strip(_screen(variant), variant), quality, progressive=True)


@lru_cache(maxsize=8)
def face_frame_jpeg(variant: int = 0, quality: int = 85) -> bytes:
    """Butun kamera kadri 1280x720, sifat 85 (OpenCV standarti — progressiv EMAS)."""
    return _jpeg(_noise_tile(CAMERA_W, CAMERA_H, 40, 1000 + variant), quality, progressive=False)


@lru_cache(maxsize=4)
def passport_jpeg(variant: int = 0) -> bytes:
    """Platforma bergan hujjat surati (3x4, ~300x400)."""
    return _jpeg(_noise_tile(300, 400, 20, 2000 + variant), 85, progressive=False)


def embedding(seed: int = 0) -> list[float]:
    """512 o'lchamli birlik vektor; float32 -> float (client `tolist()` kabi)."""
    rnd = random.Random(seed)
    raw = [rnd.gauss(0, 1) for _ in range(512)]
    norm = sum(v * v for v in raw) ** 0.5
    return [struct.unpack("f", struct.pack("f", v / norm))[0] for v in raw]


def embedding_json(seed: int = 0) -> str:
    return json.dumps(embedding(seed))


# --- Hodisalar ----------------------------------------------------------
#: AI kuzatuvsiz (standart `ProctoringPolicy.is_enabled=False`) client
#: yuboradigan turlar va jiddiylik (`exam_webview_page.py`, `device_watch.py`).
EVENT_MIX = (
    ("face_not_found", 2, {}),
    ("window_blur", 2, {}),
    ("window_focus", 0, {}),
    ("hotkey_blocked", 1, {"key": "alt+tab", "repeats": 1}),
    ("multiple_faces", 3, {}),
)


def event(event_type: str = "face_not_found", severity: int = 2, payload=None) -> dict:
    return {
        "client_event_id": uuid.uuid4().hex,
        "type": event_type,
        "severity": int(severity),
        "occurred_at": now_iso(),
        "payload": payload or {},
    }


def event_batch(count: int, rnd: random.Random | None = None) -> list[dict]:
    rnd = rnd or random
    items = []
    for _ in range(max(1, count)):
        kind, severity, payload = rnd.choices(EVENT_MIX, weights=(50, 25, 20, 4, 1))[0]
        items.append(event(kind, severity, payload))
    return items


def heartbeat_body(face_checks: int = 0) -> dict:
    """`monitoring.SessionMonitor._send_heartbeat` shakli."""
    return {
        "network_ok": True,
        "queued_events": 0,
        "face_checks": face_checks,
        "cpu_percent": 23.5,
        "memory_percent": 61.2,
    }


def camera_check_body(exam_id: int | None = None) -> dict:
    """Bitta lokal veb-kamera (primary) — xom o'lchovlar (`camera_panel.run_check`)."""
    body = {
        "cameras": [
            {
                "role": "primary", "source": "local", "label": "USB2.0 HD UVC WebCam",
                "local_index": 0, "measured": True, "available": True, "opened": True,
                "is_virtual": False, "frames": 90, "fps": 29.6, "width": 1280,
                "height": 720, "latency_ms": 45, "faces": 1, "face_width_px": 240,
                "brightness": 128, "face_offset": 0.05,
            }
        ]
    }
    if exam_id:
        body["exam_id"] = int(exam_id)
    return body


def handshake_body(ident: dict) -> dict:
    """`ProctoringRepository.handshake` + `AuthService.handshake` shakli."""
    return {
        "app_version": "1.0.0",
        "app_hash": "",
        "hardware_fingerprint": f"muid:{ident['machine_uuid']}",
        "public_ip": ident["public_ip"],
        "monitors": 1,
        "cameras": 1,
        "machine_uuid": ident["machine_uuid"],
        "mac_address": ident["mac"],
        "ip_address": ident["lan_ip"],
        "gpu_name": "",
        "performance_profile": "cpu",
        "info_pc": {
            "hostname": ident["inventory_code"], "os": "Windows 10 Pro 22H2",
            "cpu": "Intel(R) Core(TM) i5-10400 CPU @ 2.90GHz", "ram_gb": 16,
            "hardware": {"providers": ["CPUExecutionProvider"], "cores": 12},
        },
    }


def recording_body(session_public_id: str, duration_ms: int) -> dict:
    """`register_recording(kind="screen")` — faqat MANZIL, fayl emas."""
    return {
        "kind": "screen",
        "local_path": "D:\\ProctoringArchive\\LT\\LT Yuklama imtihoni\\screen.mp4",
        "captured_at": now_iso(),
        "size_bytes": 620_000_000,
        "duration_ms": int(duration_ms),
        "width": 1600, "height": 900,
        "frames": int(duration_ms / 200), "frames_dropped": 0,
        "event_type": "", "camera_role": "", "confidence": 0,
        "session_id": session_public_id,
    }
