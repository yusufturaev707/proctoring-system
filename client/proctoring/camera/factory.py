"""
Slot tavsifidan KADR MANBAINI yasaydi.

NIMA UCHUN ALOHIDA MODUL. Kamerani ochadigan ikkita chaqiruvchi bor
va ular butunlay boshqa qatlamlarda yashaydi:

    CameraManager          -> kuzatuv oqimi va tekshiruv sahifasi
    services/camera_worker -> FaceID sahifasi (yuz solishtiruvi)

Ilgari ikkinchisi kamerani O'ZI ochardi (`cv2.VideoCapture(CAMERA_INDEX)`)
va shu sababli hech qachon tanlangan rolni bilmasdi: operator yuz
kamerasini almashtirsa ham, FaceID eski indeksni ochaverardi va
tahlil boshqa kameradan ketardi. Bir xil ishni ikkinchi marta yozish
xatosi aynan shu ko'rinishda chiqdi.

Endi qurilmani ochish qoidasi (DirectShow, MJPG, bufer, virtual
kamera belgisi, RTSP kredensiali) BITTA joyda. Yangi vendor
qo'shilganda ham u shu yerga qo'shiladi.
"""

from __future__ import annotations

import logging
from typing import Optional

from config import FRAME_HEIGHT, FRAME_WIDTH
from proctoring.camera.base import CameraSource, CameraSpec

log = logging.getLogger(__name__)


def build_source(
    spec: CameraSpec,
    *,
    stream_url_provider=None,
    discovered: Optional[list] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> Optional[CameraSource]:
    """
    Slot uchun kadr manbai. `None` — ochib bo'lmaydi.

    `stream_url_provider(camera_id=..., role=...) -> dict` — IP kamera
    uchun kredensial SO'RAYDIGAN funksiya. U qiymat sifatida emas, funksiya sifatida
    olinadi va natija saqlanmaydi: kredensial client xotirasida
    qancha kam yashasa, shuncha yaxshi.

    `discovered` — aniqlangan lokal qurilmalar. Server indeks bermagan
    holatda eng ehtimolli qurilmani tanlash uchun kerak.

    `width`/`height` — so'raladigan kadr o'lchami. Berilmasa
    `FRAME_WIDTH`/`FRAME_HEIGHT` ishlatiladi: BARCHA sahifalar bir xil
    o'lchamda ishlashi kerak, aks holda tekshiruvdan o'tgan
    rezolyutsiya bilan imtihondagi rezolyutsiya boshqa-boshqa
    bo'lardi.
    """
    if spec.source == "ip":
        return _rtsp_source(spec, stream_url_provider)
    return _webcam_source(spec, discovered or [], width, height)


# --------------------------------------------------------------------------
def _rtsp_source(spec: CameraSpec, stream_url_provider) -> Optional[CameraSource]:
    if stream_url_provider is None:
        log.error("[%s] IP kamera uchun manzil manbai berilmagan", spec.role)
        return None

    from proctoring.camera.rtsp import RtspSource

    role = spec.role
    camera_id = spec.camera_id
    if not camera_id:
        # ID KERAK: server oqimni aynan shu bo'yicha beradi. Usiz
        # so'rov yuborish 400 olib kelardi va sabab log'da
        # "camera_id majburiy" bo'lib ko'rinardi - kamera esa
        # oddiygina ro'yxatdan tushib qolgan bo'lardi.
        log.error("[%s] IP kamera identifikatorsiz - oqim ochilmaydi", role)
        return None

    def provider() -> str:
        # Kredensial HAR OCHILISHDA qaytadan so'raladi. Uni bir marta
        # olib saqlash oson bo'lardi, lekin o'shanda u dastur umri
        # davomida xotirada yashardi va administrator kamera parolini
        # almashtirsa, client eskisi bilan urinib qolardi.
        payload = stream_url_provider(camera_id=camera_id, role=role) or {}
        return payload.get("url") or ""

    return RtspSource(
        provider,
        role=spec.role,
        label=spec.label,
        address=spec.address,
        transport=spec.transport,
    )


def _webcam_source(
    spec: CameraSpec,
    discovered: list,
    width: Optional[int],
    height: Optional[int],
) -> Optional[CameraSource]:
    from proctoring.camera.discovery import first_real_index, looks_virtual
    from proctoring.camera.webcam import WebcamSource

    index = _resolve_index(spec, discovered)
    if index is None:
        # Server indeks bermagan — eng ehtimolli qurilmani tanlaymiz.
        # Bu FAQAT qulaylik: siyosat virtual kamerani taqiqlagan
        # bo'lsa, tekshiruv bosqichi baribir rad etadi.
        index = first_real_index(discovered)
    if index is None:
        log.error("[%s] lokal kamera topilmadi", spec.role)
        return None

    found = next((item for item in discovered if item.index == index), None)
    return WebcamSource(
        index,
        role=spec.role,
        label=found.label if found else spec.label,
        is_virtual=found.is_virtual if found else looks_virtual(spec.label),
        width=int(width or FRAME_WIDTH),
        height=int(height or FRAME_HEIGHT),
    )


def _resolve_index(spec: CameraSpec, discovered: list) -> Optional[int]:
    """
    Qaysi indeks ochiladi: QURILMA YO'LI indeksdan ustun.

    Indeks - DirectShow sanog'idagi O'RIN, ya'ni bitta kamera
    uzilsa yoki yangisi ulansa qolganlariniki siljiydi. Taqsimot
    esa undan oldin hisoblangan bo'lishi mumkin (tekshiruv
    sahifasida ko'rilgan holat FaceID sahifasigacha yashaydi).
    Eski indeksni ko'r-ko'rona ochish o'sha holatda BOSHQA
    kamerani ochardi - aynan shaxs tekshiruvida, va model
    "yuz topilmadi" deb xabar berardi.

    Qurilmalar ro'yxati berilmagan bo'lsa (FaceID sahifasining
    `source_for_role` i uni bermaydi) DirectShow sanog'i
    o'qiladi: u kamerani OCHMAYDI, ya'ni bir necha millisekund
    oladi - sanoqsiz qolish esa aynan eng qimmat joyda (shaxs
    tekshiruvida) noto'g'ri kamerani ochish demak.
    """
    if not spec.device_path:
        return spec.local_index

    index = _index_by_path(spec.device_path, discovered)
    if index is None:
        from proctoring.camera.dshow import enumerate_devices

        index = _index_by_path(spec.device_path, enumerate_devices())
    if index is None:
        return spec.local_index

    if index != spec.local_index:
        log.warning(
            "[%s] kamera indeksi siljigan (%s -> %s), qurilma yo'li bo'yicha "
            "tuzatildi: %s",
            spec.role, spec.local_index, index, spec.label or "-",
        )
    return index


def _index_by_path(device_path: str, devices: list) -> Optional[int]:
    """Qurilma yo'li bo'yicha indeks. `None` — ro'yxatda yo'q."""
    for item in devices or []:
        if getattr(item, "device_path", "") == device_path:
            return item.index
    return None
