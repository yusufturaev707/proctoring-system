"""
Lokal kamera qurilmalarini aniqlash.

NOM VA INDEKS BITTA MANBADAN. OpenCV Windows'da `CAP_DSHOW` bilan
ishlaydi va indeksni DirectShow'ning tizim qurilma sanagichidan
oladi. Shu ro'yxatni biz ham o'qiymiz (`camera/dshow.py`), ya'ni
"0-indeks qaysi kamera" degan savolga javob TAXMIN emas.

ILGARI ISHLAMAGAN YO'L. Nom Windows PnP ro'yxatidan
(`Get-PnpDevice -Class Camera`) olinar va OpenCV indeksiga TARTIB
bo'yicha juftlanardi. Ikkala ro'yxat ham "kameralar" haqida, lekin
tartiblari bog'liq emas: ishlab chiqish mashinasida PnP
"GRANDSTREAM GUV3100, Logi C270" beradi, DirectShow esa
"Logi C270, GRANDSTREAM GUV3100" — ya'ni ekranda ikkala kameraning
nomi ALMASHIB chiqardi. Operator esa aynan nomga qarab "qaysi biri
yuzga qaraydi" degan qarorni qabul qiladi, ya'ni xato nom uni
noto'g'ri kamerani tanlashga olib borardi va tanlov "hech narsaga
ta'sir qilmaydi" bo'lib ko'rinardi.

PnP ro'yxati ZAXIRA bo'lib qoladi (DirectShow sanog'i ishlamagan
holat uchun) va o'sha yerda eski ehtiyot chorasi ham saqlanadi:
sonlar mos kelmasa nom UMUMAN berilmaydi — xato nom nomsizlikdan
yomonroq.

VIRTUAL KAMERA aniqlash nomga qarab ishlaydi va u XAVFSIZLIK
CHEGARASI EMAS: nomni o'zgartirish mumkin. Bu operator uchun
ogohlantirish va administrator uchun signal — haqiqiy himoya emas.
DirectShow ro'yxati bu yerda ham aniqroq: virtual kamera PnP
qurilmasi emas va eski yo'lda u umuman nomsiz qolardi.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

#: Windows'da konsol oynasi ochilmasligi uchun (`services/system_info.py`
#: dagi bilan bir xil sabab: frozen GUI dasturda qora oyna chaqnaydi).
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

#: Virtual kamera nomidagi belgilar. Ro'yxat to'liq emas va bo'lishi
#: ham mumkin emas — u faqat keng tarqalganlarini ushlaydi.
_VIRTUAL_HINTS = (
    "obs", "manycam", "snap camera", "xsplit", "droidcam", "iriun",
    "e2esoft", "ivcam", "ndi", "virtual", "splitcam", "yawcam",
    "unity video", "vtube", "camtwist", "epoccam",
)

#: Nechta indeks tekshiriladi.
#:
#: Har bir tekshiruv kamerani OCHADI va bu DirectShow'da ~0.8 soniya.
#: 4 ta indeks ~3 soniya degani — kamera tekshiruvi sahifasi uchun
#: maqbul. Bundan ko'pi bo'lgan mashinada operator kerakli indeksni
#: `.env` orqali ko'rsatadi.
MAX_PROBE_INDEX = 4


@dataclass
class DiscoveredCamera:
    index: int
    name: str = ""
    width: int = 0
    height: int = 0
    fps: float = 0.0
    is_virtual: bool = False
    #: DirectShow bergan BARQAROR identifikator (USB VID/PID +
    #: instansiya). Indeksdan farqi: boshqa kamera ulanganda yoki
    #: qurilma qayta sanalganda u siljimaydi, shuning uchun
    #: operator tanlovi aynan shunga bog'lanadi
    #: (`roles.ResolvedCamera.key`). Bo'sh bo'lishi mumkin —
    #: virtual kamera fizik qurilma emas.
    device_path: str = ""

    @property
    def label(self) -> str:
        return self.name or f"Kamera #{self.index}"

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "name": self.label,
            "width": self.width,
            "height": self.height,
            "fps": round(self.fps, 1),
            "is_virtual": self.is_virtual,
            "device_path": self.device_path,
        }


def looks_virtual(name: str) -> bool:
    lowered = (name or "").lower()
    return any(hint in lowered for hint in _VIRTUAL_HINTS)


def device_names() -> list[str]:
    """
    Windows'dagi kamera qurilmalari nomi (tartib bilan).

    Xato holatida BO'SH ro'yxat — nomsiz qolish aniqlashni
    to'xtatmasligi kerak.
    """
    if sys.platform != "win32":
        return []

    # `Get-PnpDevice` WMI'ga qaraganda tezroq va u o'chirilgan
    # qurilmalarni ham ko'rsatadi (`Status` bo'yicha filtrlaymiz).
    #
    # AVVAL `Camera`, KEYIN `Image`. Ilgari ikkalasi BIRGA
    # so'ralardi va bu ro'yxatni jimgina buzardi: `Image` sinfiga
    # skaner va WIA qurilmalari ham kiradi, ya'ni ro'yxatda
    # kameraga aloqasi yo'q yozuv paydo bo'lib, nomlar indeksga
    # NISBATAN SILJIRDI - ekranda ikkita kameraning nomi
    # almashib qolardi. `Image` faqat zaxira: eski mashinalarda
    # ba'zi veb-kameralar hali ham o'sha sinfda ro'yxatdan o'tadi.
    for device_class in ("Camera", "Image"):
        names = _pnp_names(device_class)
        if names:
            return names
    return []


def _pnp_names(device_class: str) -> list[str]:
    command = [
        "powershell", "-NoProfile", "-NonInteractive", "-Command",
        "Get-PnpDevice -Class {} -Status OK "
        "| Select-Object -ExpandProperty FriendlyName".format(device_class),
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, timeout=6.0, creationflags=_NO_WINDOW
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("Kamera nomlarini olib bo'lmadi: %s", exc)
        return []

    text = result.stdout.decode("utf-8", errors="replace")
    if not text.strip():
        text = result.stdout.decode("cp866", errors="replace")

    return [line.strip() for line in text.splitlines() if line.strip()]


def probe(max_index: int = MAX_PROBE_INDEX) -> list[DiscoveredCamera]:
    """
    Mavjud kameralarni aniqlaydi.

    QAYSI INDEKSLAR TEKSHIRILADI. DirectShow ro'yxati bo'lsa — aynan
    unda sanalganlari, ya'ni bekorga ochish yo'q va ro'yxatdagi
    oxirgi kamera ham ko'rinadi. Ro'yxat olinmasa eski yo'l qoladi:
    `0..max_index` ko'r-ko'rona tekshiriladi.

    BLOKLOVCHI: har bir indeks uchun kamera ochiladi (~0.8 s). UI
    thread'idan chaqirmang — `CameraManager.discover_async` dan
    foydalaning.
    """
    import cv2

    from proctoring.camera import dshow

    listed = dshow.enumerate_devices()
    indexes = [item.index for item in listed] if listed else list(range(max(1, max_index)))

    found: list[DiscoveredCamera] = []
    backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY

    for index in indexes:
        capture = None
        try:
            capture = cv2.VideoCapture(index, backend)
            if not capture.isOpened():
                continue

            # Ochilgani yetarli emas: virtual va "arvoh" qurilmalar
            # ochiladi, lekin kadr bermaydi. Bitta kadrni haqiqatda
            # o'qib ko'ramiz.
            ok, frame = capture.read()
            if not ok or frame is None:
                log.info("Kamera %s ochildi, lekin kadr bermadi", index)
                continue

            height, width = frame.shape[:2]
            found.append(
                DiscoveredCamera(
                    index=index,
                    width=width,
                    height=height,
                    fps=float(capture.get(cv2.CAP_PROP_FPS) or 0.0),
                )
            )
        except Exception:
            log.debug("Kamera %s ni tekshirishda xato", index, exc_info=True)
        finally:
            if capture is not None:
                try:
                    capture.release()
                except Exception:
                    pass

    if listed:
        _apply_dshow(found, listed)
    else:
        # ZAXIRA: DirectShow sanog'i ishlamadi (Windows emas yoki COM
        # xatosi). Nom PnP ro'yxatidan keladi va u indeksga
        # kafolatlangan holda mos kelmaydi - shuning uchun u yerda
        # sonlar mos kelmasa nom umuman berilmaydi.
        _apply_names(found, device_names())

    log.info(
        "Aniqlangan kameralar: %s",
        [(item.index, item.label) for item in found],
    )
    return found


def _apply_dshow(found: list, listed: list) -> None:
    """
    Nomni DirectShow ro'yxatidan oladi — INDEKS bo'yicha, tartib
    bo'yicha emas.

    Farqi hal qiluvchi: ochilmagan kamera (band yoki nosoz)
    `found` dan tushib qoladi, indekslar esa o'z joyida qoladi.
    Tartib bo'yicha juftlash o'sha holatda qolgan barcha nomlarni
    bittaga suradi va ekranda nomlar almashib ketardi.
    """
    by_index = {item.index: item for item in listed}
    for camera in found:
        device = by_index.get(camera.index)
        if device is None:
            continue
        camera.name = device.name
        camera.device_path = device.device_path
        camera.is_virtual = looks_virtual(device.name)


def _apply_names(found: list, names: list) -> None:
    """
    Nomlarni qurilmalarga juftlaydi - FAQAT SONLAR MOS KELSA.

    XATO NOM NOMSIZLIKDAN YOMONROQ. Ilgari nom `names[index]` bilan
    olinardi, ya'ni OpenCV indeksi PnP ro'yxatiga to'g'ridan-to'g'ri
    kalit sifatida ishlatilardi. Ro'yxatlar uzunligi farq qilganda
    (o'chirilgan kamera, virtual qurilma, skaner) nomlar SILJIB
    ketardi va ekranda ikkita kameraning nomi almashib qolardi -
    operator esa aynan NOMGA qarab "qaysi biri yuzga qaraydi" degan
    qarorni qabul qiladi, ya'ni xato nom uni noto'g'ri tanlashga
    olib borardi.

    Sonlar mos kelmasa nom umuman berilmaydi: qurilma ekranda
    "Kamera #0" bo'lib ko'rinadi va operator uni kadr bo'yicha
    ajratadi (oldindan ko'rish aynan shuning uchun bor).
    """
    if len(names) != len(found):
        if names:
            log.warning(
                "Kamera nomlari indeks bilan juftlanmadi (%s nom, %s qurilma) - "
                "nomsiz ko'rsatiladi",
                len(names), len(found),
            )
        return
    for camera, name in zip(found, names):
        camera.name = name
        camera.is_virtual = looks_virtual(name)


def first_real_index(cameras: list[DiscoveredCamera]) -> Optional[int]:
    """
    Virtual bo'lmagan birinchi kamera indeksi.

    Biriktirish yo'q bo'lganda ishlatiladi: server `local_index` ni
    bermagan bo'lsa, client eng ehtimolli qurilmani tanlaydi.
    Virtualni chetlab o'tish shu yerda ham EVRISTIK — siyosat
    (`allow_virtual`) haqiqiy qarorni keyin, tekshiruv bosqichida
    chiqaradi.
    """
    for camera in cameras:
        if not camera.is_virtual:
            return camera.index
    return cameras[0].index if cameras else None
