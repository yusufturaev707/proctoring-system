"""
Kadr manbaining umumiy shartnomasi.

`CameraSource` — SINXRON va BLOKLOVCHI interfeys: `open()`, `read()`,
`close()`. Thread, qayta ulanish va FPS o'lchash bu yerda YO'Q va
bu ataylab: ular manbadan qat'i nazar bir xil ishlaydi va
`CameraStream` da bir marta yozilgan (`manager.py`). Aks holda har
bir yangi vendor uchun qayta ulanish mantig'i qaytadan yozilardi va
ular albatta bir-biridan farq qilardi.

Yangi vendor qo'shish = `CameraSource` ning uchta metodini yozish.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np


class CameraState(str, Enum):
    """
    Manbaning joriy holati.

    `DEGRADED` alohida holat va u eng muhimi: kamera ISHLAYAPTI,
    lekin talab qilingan sifatdan past (FPS tushib ketgan, kadrlar
    kech kelyapti). Uni `FAILED` bilan birlashtirish har bir
    vaqtinchalik sekinlashuvni imtihonni to'xtatish sababiga
    aylantirardi; `ONLINE` bilan birlashtirish esa kuzatuv sifati
    pasayganini bayonnomada ko'rinmas qilardi.
    """

    IDLE = "idle"
    OPENING = "opening"
    ONLINE = "online"
    DEGRADED = "degraded"
    RECONNECTING = "reconnecting"
    FAILED = "failed"
    CLOSED = "closed"


@dataclass
class CameraInfo:
    """Manbaning statik tavsifi — tekshiruv sahifasi shuni ko'rsatadi."""

    role: str = ""
    source: str = "local"           # local | ip
    label: str = ""
    #: Lokal kamera uchun OS indeksi, IP uchun `None`.
    index: Optional[int] = None
    #: IP kamera uchun manzil — KREDENSIALSIZ (log va UI uchun).
    address: str = ""
    width: int = 0
    height: int = 0
    #: Qurilma e'lon qilgan FPS. Haqiqiy FPS `CameraHealth` da.
    declared_fps: float = 0.0
    #: Nomga qarab virtual kamera deb taxmin qilindimi.
    is_virtual: bool = False
    backend: str = ""

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}" if self.width else "-"


@dataclass
class CameraHealth:
    """
    O'lchanadigan holat. Har soniyada yangilanadi.

    `fps` — HAQIQIY o'lchangan qiymat, qurilma e'lon qilgani emas.
    Farq muhim: USB kamera 30 FPS deb e'lon qilib, past yorug'likda
    ekspozitsiyani uzaytirgani sababli 7 FPS beradi va bu proktorlik
    uchun butunlay boshqa sifat.
    """

    state: CameraState = CameraState.IDLE
    fps: float = 0.0
    #: Oxirgi kadr olingandan beri o'tgan vaqt (ms).
    frame_age_ms: int = 0
    #: `read()` chaqiruvining o'rtacha davomiyligi (ms).
    read_latency_ms: float = 0.0
    frames_total: int = 0
    frames_dropped: int = 0
    reconnects: int = 0
    last_error: str = ""

    def as_dict(self) -> dict:
        return {
            "state": self.state.value,
            "fps": round(self.fps, 1),
            "frame_age_ms": self.frame_age_ms,
            "read_latency_ms": round(self.read_latency_ms, 1),
            "frames_total": self.frames_total,
            "frames_dropped": self.frames_dropped,
            "reconnects": self.reconnects,
            "last_error": self.last_error[:200],
        }


class CameraSource:
    """
    Kadr manbai.

    Meros oluvchi uchta metodni yozadi. Ularning HAMMASI bloklovchi
    bo'lishi mumkin va shuning uchun ularni HECH QACHON UI thread'idan
    chaqirmang — `CameraStream` buni o'zi ta'minlaydi.
    """

    def __init__(self, info: CameraInfo) -> None:
        self.info = info

    # ------------------------------------------------------------------
    def open(self) -> bool:
        """Manbani ochadi. `False` — ochilmadi (sabab `last_error` da)."""
        raise NotImplementedError

    def read(self) -> Optional[np.ndarray]:
        """
        Keyingi kadr (BGR) yoki `None`.

        `None` XATO EMAS: USB kamerada bitta o'tkazib yuborilgan kadr
        odatiy hol. Ketma-ket nechta `None` dan keyin uzilish deb
        hisoblash — chaqiruvchining qarori (`CameraStream`).
        """
        raise NotImplementedError

    def close(self) -> None:
        """Resursni bo'shatadi. Takroriy chaqiruv xavfsiz bo'lishi shart."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    @property
    def last_error(self) -> str:
        return getattr(self, "_last_error", "")

    def _fail(self, message: str) -> bool:
        self._last_error = message
        return False


@dataclass
class CameraSpec:
    """
    Serverdan kelgan slot tavsifi (`camera/config/` javobidagi bitta slot).

    Kredensial BU YERDA YO'Q. U alohida so'raladi (`camera/stream/`)
    va faqat oqim ochilayotgan paytda, faqat xotirada yashaydi —
    shuning uchun `CameraManager` uni chaqiruvchidan funksiya
    (callable) ko'rinishida oladi, qiymat ko'rinishida emas.
    """

    role: str
    source: str = "local"
    assigned: bool = False
    required: bool = False
    local_index: Optional[int] = None
    label: str = ""
    #: Lokal kameraning DirectShow `DevicePath` i. Indeks SANOQDAGI
    #: o'rin va u qurilmalar qayta sanalganda siljiydi; yo'l esa
    #: qurilmaning o'zi. Ochish paytida ikkalasi bir-birini
    #: tekshiradi (`factory._webcam_source`).
    device_path: str = ""
    address: str = ""
    transport: str = "tcp"
    #: IP kameraning serverdagi identifikatori.
    #:
    #: KREDENSIAL AYNAN SHU BO'YICHA so'raladi (`camera/stream/`).
    #: Ilgari so'rov ROL bo'yicha ketardi va serverda `CameraAssignment`
    #: jadvalidan izlanardi; biriktirish olib tashlangach rolni
    #: faqat client biladi, ya'ni serverga uni yuborishning ma'nosi
    #: qolmadi - kamerani ID belgilaydi.
    camera_id: Optional[int] = None
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_api(cls, role: str, payload: dict) -> "CameraSpec":
        payload = payload or {}
        camera = payload.get("camera") or {}
        return cls(
            role=role,
            source=payload.get("source") or "local",
            assigned=bool(payload.get("assigned")),
            required=bool(payload.get("required")),
            local_index=payload.get("local_index"),
            label=camera.get("name") or "",
            device_path=camera.get("device_path") or "",
            address=camera.get("ip_address") or "",
            transport=camera.get("transport") or "tcp",
            camera_id=camera.get("id"),
            extra={
                "vendor": camera.get("vendor", ""),
                "status": camera.get("status", ""),
                "note": payload.get("note", ""),
            },
        )
