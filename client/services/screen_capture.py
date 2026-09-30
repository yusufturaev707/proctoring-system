"""
Ekran suratlari: BUYRUQ bilan olish, mahalliy arxiv va serverga yuborish.

TAYMER YO'Q. Kadr faqat test platformasi buyurganda olinadi: talabgor
savolga javob belgilaganda platforma frontendi lokal xizmatga
`POST /api/capture_screen` yuboradi (`services/local_service.py`).
Ilgari skrinshot har N soniyada olinardi va uning katta qismi ishsiz
edi - talabgor o'ylayotgan paytdagi bir xil ekran (shuning uchun dedup
kerak bo'lgan). Endi har kadr MA'NOLI lahzada: javob belgilangan
ekran. Dedup ham shu sababdan yo'q - buyurilgan kadr o'xshash
bo'lsa ham dalil.

SAVOL KADRI. Buyruq odatda savolni aytadi (`{"q_id": "1", "q_n": 3}`):
kadr nomi savoldan yasaladi (`q003_id1_14-05-33.jpg`) va talabgor
savolga qaytib javobni o'zgartirsa, shu savolning kadri ALMASHADI -
mashinada ham (`local_archive.save_question_shot`), serverda ham
(`question_id` bo'yicha yangilash). Har bosqichda eski kadr yangisi
bilan almashtiriladi va hech qachon yangisini bosmaydi:

    kodlash navbati   shu savolning kodlanmagan kadri tashlanadi
    yuklash navbati   shu savolning yuborilmagan kadri tashlanadi
    server            `captured_at` eskiroq kadr yangisini almashtirmaydi

KECHIKTIRISH YO'Q: kadr buyruq LAHZASIDA olinadi. Ilgari buyruqlar 1 s
ichida bittaga yig'ilardi - savolli rejimda bu xato: yig'ilgan kadr
kechroq olinadi va o'sha paytda ekranda KEYINGI savol turgan bo'lishi
mumkin (kadr noto'g'ri savol nomi bilan saqlanardi). Spam chegarasi
lokal xizmatda (sekundiga 20 buyruq).

IKKI MANZIL (`Setting.is_screenshot_upload` -> `config.capture.upload`):

    mahalliy arxiv   HAR DOIM (`services/local_archive.py`)
    server           faqat `upload` yoqilgan bo'lsa, FONDA

Serverga yuborishning ikki yo'lini bu modul biladi va o'rnatish
profiliga qarab bittasini tanlaydi (`_resolve_mode`):

    S3/MinIO    presign -> PUT (binary backend'dan O'TMAYDI) -> commit
    Fayl tizimi upload/ (binary Django worker'idan o'tadi)

Client qaysi biri yoqilganini OLDINDAN bilmaydi: rejim sessiya boshida
BIR MARTA aniqlanadi - `presign/` 503 qaytarsa fayl tizimi yo'li.

Kamera kadri ALOHIDA RASM bo'lib yuborilmaydi: u skrinshot OSTIGA
qo'shilgan tasmaga chiziladi (`services/camera_overlay.py`) - bitta
rasm "ekranda nima bo'ldi" va "oldida kim o'tirgan edi" degan ikkala
savolga javob beradi va test sahifasining hech bir qismi yopilmaydi.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from PyQt6.QtCore import QBuffer, QIODevice, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QImageWriter, QPainter
from PyQt6.QtWidgets import QApplication

from config import (
    LOCAL_ARCHIVE_ENABLED,
    SCREENSHOT_ENABLED,
    SCREENSHOT_RETRY_QUEUE,
)
from core.errors import ClientError
from services import local_archive, net_policy, runtime_settings
from services.api_client import ApiClient
from services.network_status import on_power_resumed
from services.repositories import ProctoringRepository
from services.workers import ApiWorker, WorkerHolder

log = logging.getLogger(__name__)

#: Server sozlamasi kelmasa ishlatiladigan qiymatlar.
#:
#: `controls.Setting` modelidagi standartlar bilan BIR XIL bo'lishi
#: shart - aks holda sozlamasi o'chirilgan tizimda client boshqacha
#: ishlaydi va farqni tushuntirish qiyin bo'ladi.
_FALLBACK = {
    "quality": 80,
    "max_width": 1920,
}

#: Bir marta nechta presigned URL so'raladi.
#:
#: Har kadr uchun alohida `presign/` chaqirish - bitta skrinshotga uchta
#: so'rov (presign + PUT + commit) degani. Pool bilan bu ~1.4 ga tushadi.
#: Muddati tugagan URL ishlatilmaydi (`_PRESIGN_SAFETY_S`), ya'ni
#: buyruqlar siyrak bo'lsa pool shunchaki qayta to'ldiriladi.
_PRESIGN_POOL = 5

#: Shuncha yig'ilgach `commit/` batch bilan yuboriladi.
_COMMIT_BATCH = 5

#: Presigned URL muddati tugashiga shuncha qolganda ishlatilmaydi.
_PRESIGN_SAFETY_S = 30

#: Kodlanishini kutayotgan kadrlar chegarasi. Kodlash ~40 ms, ya'ni
#: navbat odatda bo'sh; shu savolning eski kadri baribir almashtiriladi.
_MAX_PENDING_ENCODES = 8

#: Yuklash xatosidan keyin qayta urinish (soniya): 15 -> 30 -> 60 ...
#: chegara 300, jitter bilan (`net_policy.Backoff`). Ilgari qat'iy 15 s
#: edi: server tushganda butun bino har 15 s da bir xil ritmda urardi,
#: u turganda esa hamma to'plangan navbatini BIR LAHZADA yuborardi.
_RETRY_BASE_S = 15.0
_RETRY_CAP_S = 300.0

# --------------------------------------------------------------------------
# Konfiguratsiya
# --------------------------------------------------------------------------
@dataclass
class CaptureConfig:
    """Handshake konfiguratsiyasidagi `capture` bo'limi."""

    quality: int
    max_width: int
    #: Serverga ham yuboriladimi (`capture.upload`). `False` - faqat
    #: mahalliy arxiv: trafik yoki server diski masalasida imtihon
    #: egasi shuni tanlaydi.
    upload: bool = True
    #: Skrinshot ostiga kamera tasmasi qo'shiladimi va ramka ulushi
    #: (0..1). Imtihon profilidan (`capture.camera_overlay*`), zaxira -
    #: `.env`: tasma har kadrni ~24% og'irlashtiradi, ya'ni bu trafik
    #: bilan kelishuv va uni imtihon egasi hal qiladi.
    camera_overlay: bool = True
    camera_overlay_ratio: float = 0.16

    @classmethod
    def from_server(cls, config: Optional[dict]) -> "CaptureConfig":
        capture = (config or {}).get("capture") or {}

        def value(name: str) -> int:
            try:
                raw = int(capture.get(name, _FALLBACK[name]))
            except (TypeError, ValueError):
                return _FALLBACK[name]
            return raw if raw > 0 else _FALLBACK[name]

        return cls(
            quality=max(20, min(95, value("quality"))),
            max_width=max(320, value("max_width")),
            upload=runtime_settings.get(config, "capture.upload"),
            camera_overlay=runtime_settings.get(config, "capture.camera_overlay"),
            camera_overlay_ratio=runtime_settings.get(
                config, "capture.camera_overlay_percent"
            ),
        )


@dataclass
class Frame:
    """Kodlangan, yuborishga tayyor kadr."""

    data: bytes
    width: int
    height: int
    captured_at: str
    sha256: str
    #: Test platformasidagi savol (`q_id`, `q_n`); bo'sh - savolsiz kadr.
    question_id: str = ""
    question_number: Optional[int] = None


# --------------------------------------------------------------------------
# Kadr olish (FAQAT UI thread'dan)
# --------------------------------------------------------------------------
def grab_screens() -> Optional[QImage]:
    """
    Barcha monitorlarni bitta rasmga yig'adi.

    Ikkinchi monitor ATAYLAB qamrab olinadi: aynan u chetlashtirish
    sababi bo'ladigan holat. `multi_monitor` hodisasi buni AYTADI,
    skrinshot esa KO'RSATADI - faqat asosiy ekranni olish dalilning
    yarmini tashlab yuborish demak.

    Ekranlar gorizontal joylashtiriladi: haqiqiy koordinatalarni saqlash
    monitorlar turli balandlikda bo'lganda katta bo'sh maydon beradi va
    u JPEG'da faqat joy egallaydi.

    Qt'da ekran nusxasi GUI thread'iga bog'langan, shuning uchun bu
    funksiya fon thread'idan chaqirilmaydi.
    """
    app = QApplication.instance()
    if app is None:
        return None

    screens = app.screens()
    if not screens:
        return None

    images = []
    for screen in screens:
        try:
            pixmap = screen.grabWindow(0)
        except Exception:
            log.debug("Ekranni olishda xato: %s", screen.name(), exc_info=True)
            continue
        if pixmap is None or pixmap.isNull():
            continue
        images.append(pixmap.toImage())

    if not images:
        return None
    if len(images) == 1:
        return images[0]

    total_width = sum(image.width() for image in images)
    max_height = max(image.height() for image in images)
    canvas = QImage(total_width, max_height, QImage.Format.Format_RGB32)
    canvas.fill(0)

    painter = QPainter(canvas)
    try:
        offset = 0
        for image in images:
            painter.drawImage(offset, 0, image)
            offset += image.width()
    finally:
        # `QPainter` yopilmasa `QImage` qulflangan holda qoladi va uni
        # fon thread'iga uzatib bo'lmaydi.
        painter.end()
    return canvas


# --------------------------------------------------------------------------
# Kadr olish (FAQAT UI thread'dan)
# --------------------------------------------------------------------------
def grab_screens() -> Optional[QImage]:
    """
    Barcha monitorlarni bitta rasmga yig'adi.

    Ikkinchi monitor ATAYLAB qamrab olinadi: aynan u chetlashtirish
    sababi bo'ladigan holat. `multi_monitor` hodisasi buni AYTADI,
    skrinshot esa KO'RSATADI - faqat asosiy ekranni olish dalilning
    yarmini tashlab yuborish demak.

    Ekranlar gorizontal joylashtiriladi: haqiqiy koordinatalarni saqlash
    monitorlar turli balandlikda bo'lganda katta bo'sh maydon beradi va
    u JPEG'da faqat joy egallaydi.

    Qt'da ekran nusxasi GUI thread'iga bog'langan, shuning uchun bu
    funksiya fon thread'idan chaqirilmaydi.
    """
    app = QApplication.instance()
    if app is None:
        return None

    screens = app.screens()
    if not screens:
        return None

    images = []
    for screen in screens:
        try:
            pixmap = screen.grabWindow(0)
        except Exception:
            log.debug("Ekranni olishda xato: %s", screen.name(), exc_info=True)
            continue
        if pixmap is None or pixmap.isNull():
            continue
        images.append(pixmap.toImage())

    if not images:
        return None
    if len(images) == 1:
        return images[0]

    total_width = sum(image.width() for image in images)
    max_height = max(image.height() for image in images)
    canvas = QImage(total_width, max_height, QImage.Format.Format_RGB32)
    canvas.fill(0)

    painter = QPainter(canvas)
    try:
        offset = 0
        for image in images:
            painter.drawImage(offset, 0, image)
            offset += image.width()
    finally:
        # `QPainter` yopilmasa `QImage` qulflangan holda qoladi va uni
        # fon thread'iga uzatib bo'lmaydi.
        painter.end()
    return canvas


# --------------------------------------------------------------------------
# Kodlash
# --------------------------------------------------------------------------
def encode_jpeg(image: QImage, *, max_width: int, quality: int,
                cameras=None, overlay_ratio: float = 0.16,
                captured_at: Optional[str] = None) -> Optional[Frame]:
    """
    Kadrni miqyoslaydi, kamera ramkasini qo'yadi va JPEG'ga kodlaydi.

    Fon thread'ida bajariladi - `QImage` (`QPixmap` dan farqli) GUI
    thread'iga bog'lanmagan.

    Ramka MIQYOSLASHDAN KEYIN qo'yiladi: uning o'lchami yakuniy rasmga
    nisbatan hisoblanadi (4K ekranda ham, 1366 da ham bir xil ulush)
    va kichik rasmga chizish arzonroq.
    """
    if image.width() > max_width:
        image = image.scaledToWidth(
            max_width, Qt.TransformationMode.SmoothTransformation
        )
    if cameras:
        from services.camera_overlay import overlay_cameras

        image = overlay_cameras(image, cameras, ratio=overlay_ratio)

    buffer = QBuffer()
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        return None
    try:
        # Optimallashtirilgan Huffman + progressiv yozuv — bir xil
        # sifatda ~15% kichik fayl (1920/80 da 185 -> 157 KB, o'lchangan),
        # narxi ~25 ms kodlash, u esa fon thread'ida.
        writer = QImageWriter(buffer, b"jpeg")
        writer.setQuality(quality)
        writer.setOptimizedWrite(True)
        writer.setProgressiveScanWrite(True)
        if not writer.write(image):
            return None
        data = bytes(buffer.data())
    finally:
        buffer.close()

    if not data:
        return None
    return Frame(
        data=data,
        width=image.width(),
        height=image.height(),
        # Vaqt - BUYRUQ lahzasi (kodlash paytidagisi emas): navbatda
        # kutgan kadr ham o'z vaqtini aytadi.
        captured_at=captured_at or datetime.now(timezone.utc).isoformat(),
        sha256=hashlib.sha256(data).hexdigest(),
    )


# --------------------------------------------------------------------------
# Xizmat
# --------------------------------------------------------------------------
class ScreenshotService(QObject):
    """
    Sessiya davomidagi skrinshot xizmati — BUYRUQ bilan ishlaydi.

    `start(config)` sessiya tokeni olingandan KEYIN chaqiriladi (yuklash
    endpointlari `X-Proctoring-Session` talab qiladi). Shundan keyin kadr
    faqat `request_capture()` da olinadi — uni lokal xizmat chaqiradi
    (`services/local_service.py`, test platformasining buyrug'i).

    UCH BOSQICH, UCHTASI ALOHIDA va hech biri boshqasini kutmaydi:

        olish      UI thread, ~20 ms   ekran + kamera kadri, AYNAN buyruq lahzasi
        kodlash    fon, ~40 ms         JPEG + mahalliy arxiv (DOIM)
        yuklash    fon, tarmoqqa bog'liq  serverga (faqat `capture.upload`)

    Ilgari bitta "uchuvchi" ish bor edi va yuklash tugamaguncha keyingi
    kadr TASHLANARDI. Taymerda bu kelishuv edi (10 s dan keyin yana
    kadr keladi), buyruqda esa yo'q: tashlangan kadr — javobi
    belgilangan savolning YAGONA dalili. Endi tarmoq osilib qolsa ham
    kadr olinadi va mashinaga yoziladi, faqat yuklash navbati kutadi.
    """

    #: Yuborildi (jami soni) - status satri uchun.
    sent = pyqtSignal(int)
    #: Yuborib bo'lmadi. Faqat log/status uchun - oqim to'xtamaydi.
    failed = pyqtSignal(str)

    def __init__(self, repo: Optional[ProctoringRepository] = None, parent=None) -> None:
        super().__init__(parent)
        self._repo = repo or ProctoringRepository()
        self._api = ApiClient()
        self._workers = WorkerHolder()

        self._config = CaptureConfig.from_server(None)
        self._active = False
        self._total_sent = 0
        self._total_captured = 0

        #: Olingan, hali kodlanmagan kadrlar. Kodlash ~40 ms, ya'ni
        #: odatda bo'sh; chegara faqat CPU qotib qolgan holat uchun
        #: (siqilmagan 1920 kadr ~8 MB).
        self._jobs: deque = deque(maxlen=_MAX_PENDING_ENCODES)
        self._encoding = False
        #: Yuborilmagan kadrlar (kodlangan). Cheklangan - RAM uchun;
        #: tushib qolgani baribir mahalliy arxivda bor.
        self._queue = deque(maxlen=max(1, SCREENSHOT_RETRY_QUEUE))
        self._uploading = False
        #: Sessiya yopildi (token bekor) - yuklash to'xtaydi.
        self._upload_closed = False
        #: S3 yo'li uchun: tayyor presigned URL'lar va kutayotgan commit'lar.
        self._presigned = deque()
        self._commits: list[dict] = []
        #: `None` - hali aniqlanmagan; keyin `"s3"` yoki `"filesystem"`.
        self._mode: Optional[str] = None
        #: Skrinshotga qo'yiladigan kamera kadrlari manbai
        #: (`[(rol, kadr | None)]`). Sahifa beradi: kamera qayerda
        #: ekanini (supervisor yoki FaceID ishchisi) faqat u biladi.
        self._camera_provider = None

        # Tarmoq xatosidan keyin qayta urinish. Ilgari keyingi taymer
        # kadri navbatni o'zi "itarardi"; buyruqli rejimda keyingi
        # buyruq kelmasligi mumkin (oxirgi savol).
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self._kick_upload)
        self._backoff = net_policy.Backoff(base=_RETRY_BASE_S, cap=_RETRY_CAP_S)
        on_power_resumed(self._on_power_resumed)

    # ------------------------------------------------------------------
    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def pending(self) -> int:
        return len(self._queue)

    @property
    def total_sent(self) -> int:
        return self._total_sent

    # ------------------------------------------------------------------
    def start(self, config: Optional[dict], *, camera_provider=None) -> bool:
        """Buyruq qabul qilishga tayyorlanadi. Kadr OLINMAYDI."""
        if self._active:
            return True
        if not SCREENSHOT_ENABLED:
            # Lokal VETO (dev bayrog'i) - server nima desa ham ustun.
            log.info("Skrinshot olish o'chirilgan (SCREENSHOT_ENABLED=0)")
            return False

        self._config = CaptureConfig.from_server(config)
        # Tasma yoqilganmi - IMTIHON PROFILIDAN, shuning uchun provayder
        # sozlama o'qilgandan KEYIN qo'yiladi.
        self._camera_provider = camera_provider if self._config.camera_overlay else None
        self._active = True
        self._total_sent = 0
        self._total_captured = 0
        self._jobs.clear()
        self._queue.clear()
        self._presigned.clear()
        self._commits.clear()
        self._mode = None
        self._upload_closed = False
        self._backoff.success()
        log.info(
            "Skrinshot: buyruq bilan, maks. kenglik %s px, sifat %s, serverga %s",
            self._config.max_width,
            self._config.quality,
            "yuboriladi" if self._config.upload else "YUBORILMAYDI (faqat mashinada)",
        )
        if not self._config.upload and not LOCAL_ARCHIVE_ENABLED:
            # Ikkala manzil ham yopiq - kadr hech qayerga yozilmaydi.
            log.warning("Skrinshot na serverga, na mahalliy arxivga yoziladi")
        return True

    def stop(self) -> None:
        """
        Yangi buyruq qabul qilinmaydi. UI'ni KUTTIRMAYDI.

        Olingan kadrlar yo'qolmaydi: kodlash va yuklash fonda davom etadi
        - sessiya tokeni tirik ekan navbat bo'shaydi, u bekor bo'lsa
        kadrlar baribir mashinada.
        """
        if not self._active:
            return
        self._active = False
        log.info(
            "Skrinshot xizmati to'xtadi: %s ta olindi, %s tasi yuborildi%s",
            self._total_captured,
            self._total_sent,
            f", {len(self._queue)} tasi navbatda" if self._queue else "",
        )

    def request_capture(self, question: Optional[dict] = None) -> bool:
        """
        Buyruq: ekranni HOZIR suratga olish. Faqat UI thread'idan.

        `question` - lokal xizmat tekshirgan `{"q_id": str, "q_n": int}`
        yoki bo'sh. `False` - xizmat faol emas (imtihon yo'q yoki dalil
        yig'ish oynasi tugagan).
        """
        if not self._active:
            return False
        try:
            self._capture_now(question or {})
        except Exception:
            # Buyruq qanday bo'lmasin UI thread'ini yiqitmasligi kerak.
            log.exception("Skrinshot olinmadi")
        return True

    # ------------------------------------------------------------------
    # 1. Olish (UI thread)
    # ------------------------------------------------------------------
    def _capture_now(self, question: dict) -> None:
        question_id = str(question.get("q_id") or "")
        question_number = question.get("q_n") or None
        image = grab_screens()
        if image is None or image.isNull():
            log.warning("Ekran nusxasini olib bo'lmadi")
            return
        # Kamera kadri va vaqt ekran bilan BIR LAHZADA: kodlash
        # paytidagi odam emas, buyruq paytidagisi kerak.
        job = (
            image,
            self._camera_slots(),
            local_archive.context(),
            datetime.now(timezone.utc).isoformat(),
            question_id,
            question_number,
        )
        if question_id:
            # Shu savolning hali KODLANMAGAN kadri eskirdi - tashlanadi
            # (navbat faqat UI thread'ida o'zgaradi).
            for stale in [item for item in self._jobs if item[4] == question_id]:
                self._jobs.remove(stale)
        if len(self._jobs) == self._jobs.maxlen:
            log.warning("Skrinshot: kodlash orqada qoldi - eng eski kadr tashlandi")
        self._jobs.append(job)
        self._total_captured += 1
        self._kick_encode()

    def _camera_slots(self) -> list:
        """Kamera kadrlari. Xato skrinshotni HECH QACHON to'xtatmaydi."""
        if self._camera_provider is None:
            return []
        try:
            return list(self._camera_provider() or [])
        except Exception:
            log.debug("Kamera kadrini olib bo'lmadi", exc_info=True)
            return []

    # ------------------------------------------------------------------
    # 2. Kodlash + mahalliy arxiv (fon)
    # ------------------------------------------------------------------
    def _kick_encode(self) -> None:
        if self._encoding or not self._jobs:
            return
        self._encoding = True
        worker = ApiWorker(self._encode_and_store, self._jobs.popleft(), parent=self)
        worker.succeeded.connect(self._on_encoded)
        worker.failed.connect(self._on_encode_failed)
        self._workers.run(worker)

    def _encode_and_store(self, job) -> Frame:
        image, cameras, archive_context, captured_at, question_id, question_number = job
        frame = encode_jpeg(
            image,
            max_width=self._config.max_width,
            quality=self._config.quality,
            cameras=cameras,
            overlay_ratio=self._config.camera_overlay_ratio,
            captured_at=captured_at,
        )
        if frame is None:
            raise ClientError("Skrinshotni kodlab bo'lmadi", code="encode_failed")
        frame.question_id = question_id
        frame.question_number = question_number
        # MAHALLIY ARXIV — HAR DOIM va yuklashdan OLDIN
        # (`services/local_archive.py`). Kontekst buyruq paytidagi:
        # sessiya shu orada yopilgan bo'lsa ham kadr o'z papkasiga
        # tushadi. Yozish xatosi yutiladi - arxiv qulaylik.
        if archive_context:
            if question_id:
                local_archive.save_question_shot(
                    frame.data,
                    question_id=question_id,
                    question_number=question_number,
                    captured_at=datetime.fromisoformat(captured_at),
                    **archive_context,
                )
            else:
                local_archive.save(frame.data, extension="jpg", prefix="shot", **archive_context)
        return frame

    def _on_encoded(self, frame: Frame) -> None:
        self._encoding = False
        if self._config.upload and not self._upload_closed:
            if frame.question_id:
                # Shu savolning hali YUBORILMAGAN kadri keraksiz: serverda
                # baribir almashtiriladi, trafik esa ikki barobar bo'lardi.
                # Yuklanayotgani (`popleft` qilingan) navbatda yo'q.
                for stale in [item for item in list(self._queue)
                              if item.question_id == frame.question_id]:
                    try:
                        self._queue.remove(stale)
                    except ValueError:
                        pass  # ishchi shu orada olib ketdi
            if len(self._queue) == self._queue.maxlen:
                log.warning("Skrinshot navbati to'ldi - eng eski kadr tashlandi (mashinada bor)")
            self._queue.append(frame)
            self._kick_upload()
        self._kick_encode()

    def _on_encode_failed(self, message: str, code: str) -> None:
        self._encoding = False
        log.warning("Skrinshot kodlanmadi: %s", message)
        self._kick_encode()

    # ------------------------------------------------------------------
    # 3. Yuklash (fon, bitta uchuvchi so'rov)
    # ------------------------------------------------------------------
    def _kick_upload(self) -> None:
        """
        Navbatni bo'shatuvchi BITTA ishchi. Tarmoq uzilganda so'rov
        `API_TIMEOUT` gacha osilishi mumkin - har kadrga thread ochilsa
        ular to'planib RAM'ni yerdi.
        """
        if self._uploading or self._upload_closed or not self._queue:
            return
        if self._retry.isActive():
            # Backoff kutilmoqda: yangi kadr navbatga tushdi, lekin
            # yuklash muddatidan oldin boshlanmaydi (aks holda har
            # buyruq backoff'ni bekor qilib, uzilgan tarmoqni urardi).
            return
        self._uploading = True
        worker = ApiWorker(self._drain_queue, parent=self)
        worker.succeeded.connect(self._on_sent)
        worker.failed_error.connect(self._on_upload_failed)
        self._workers.run(worker)

    def _drain_queue(self) -> dict:
        """
        Navbatni TARTIB bilan bo'shatadi: skrinshotlar vaqt ketma-ketligida
        dalil va tartib buzilsa bayonnomani o'qish qiyinlashadi.

        Kadr AVVAL navbatdan olinadi (UI thread shu savolning eski
        kadrlarini navbatdan olib tashlaydi - yuklanayotganiga tegmasligi
        kerak). Xatoda u navbat BOSHIGA qaytadi, agar shu savolning
        yangiroq kadri kelmagan bo'lsa va navbat to'la bo'lmasa
        (`appendleft` to'la navbatda ENG YANGISINI tushirib yuborardi).
        """
        sent = 0
        while True:
            try:
                frame = self._queue.popleft()
            except IndexError:
                break
            try:
                self._upload(frame)
            except ClientError as exc:
                if net_policy.is_poison_payload(exc.status):
                    # Server kadrni o'zini rad etdi (buzilgan fayl, hajm):
                    # takror ham xuddi shunday tugaydi va navbat boshida
                    # qolsa orqasidagi kadrlar ABADIY kutardi. Kadr
                    # mahalliy arxivda bor.
                    log.error(
                        "Skrinshot server tomonidan rad etildi (%s %s) - tashlandi "
                        "(mashinada bor)", exc.status, exc.code or "-",
                    )
                    continue
                superseded = bool(frame.question_id) and any(
                    item.question_id == frame.question_id for item in list(self._queue)
                )
                if not superseded and len(self._queue) < (self._queue.maxlen or 0):
                    self._queue.appendleft(frame)
                raise
            except Exception:
                superseded = bool(frame.question_id) and any(
                    item.question_id == frame.question_id for item in list(self._queue)
                )
                if not superseded and len(self._queue) < (self._queue.maxlen or 0):
                    self._queue.appendleft(frame)
                raise
            sent += 1
        if self._commits:
            self._flush_commits()
        return {"sent": sent}

    def _upload(self, frame: Frame) -> None:
        if self._mode is None:
            self._resolve_mode()

        if self._mode == "s3":
            entry = self._take_presigned()
            if entry is None:
                # Presign ishlamay qoldi (masalan MinIO tushdi). Fayl
                # tizimi yo'li yoqilgan bo'lsa u ishlaydi; bo'lmasa
                # so'rov baribir xato beradi va kadr navbatda qoladi.
                log.warning("Presigned URL olinmadi - fayl tizimi yo'liga o'tilmoqda")
                self._mode = "filesystem"
                self._repo.upload_screenshot(
                    data=frame.data, captured_at=frame.captured_at,
                    question_id=frame.question_id, question_number=frame.question_number,
                )
                return

            self._api.put_binary(entry["url"], frame.data, "image/jpeg")
            self._commits.append(
                {
                    "object_key": entry["key"],
                    "kind": "screen",
                    "sha256": frame.sha256,
                    "size_bytes": len(frame.data),
                    "width": frame.width,
                    "height": frame.height,
                    "captured_at": frame.captured_at,
                    **({"question_id": frame.question_id} if frame.question_id else {}),
                    **({"question_number": frame.question_number}
                       if frame.question_number else {}),
                }
            )
            if len(self._commits) >= _COMMIT_BATCH:
                self._flush_commits()
            return

        self._repo.upload_screenshot(
            data=frame.data, captured_at=frame.captured_at,
            question_id=frame.question_id, question_number=frame.question_number,
        )

    def _resolve_mode(self) -> None:
        """
        Qaysi yo'l yoqilgan - sessiya boshida bir marta.

        `presign/` 503 qaytarsa obyekt storage'i o'chirilgan degani
        (`ScreenshotPresignView`), demak fayl tizimi yo'li ishlatiladi.
        Boshqa xatoda rejim aniqlanmagan holicha QOLADI va keyingi
        urinishda qayta so'raladi: bir martalik tarmoq uzilishi tufayli
        butun sessiyani sekinroq yo'lga o'tkazish noto'g'ri bo'lardi.
        """
        try:
            self._fill_presign_pool()
        except ClientError as exc:
            if exc.status == 503:
                self._mode = "filesystem"
                log.info("Obyekt storage'i o'chirilgan - fayl tizimi yo'li")
                return
            raise
        self._mode = "s3"
        log.info("Obyekt storage'i yoqilgan - presigned yo'li")

    def _fill_presign_pool(self) -> None:
        result = self._repo.presign_screenshots(count=_PRESIGN_POOL) or {}
        now = time.monotonic()
        for entry in result.get("uploads") or []:
            if not entry.get("url") or not entry.get("key"):
                continue
            ttl = int(entry.get("expires_in") or 300)
            self._presigned.append({**entry, "expires_at": now + ttl})

    def _take_presigned(self) -> Optional[dict]:
        """Muddati o'tmagan birinchi URL; pool bo'shasa qayta to'ldiriladi."""
        now = time.monotonic()
        while self._presigned:
            entry = self._presigned.popleft()
            if entry["expires_at"] - now > _PRESIGN_SAFETY_S:
                return entry
            log.debug("Presigned URL muddati tugadi - tashlandi")

        try:
            self._fill_presign_pool()
        except ClientError as exc:
            log.warning("Presign xatosi: %s", exc.message)
            return None
        return self._presigned.popleft() if self._presigned else None

    def _flush_commits(self) -> dict:
        """
        Metadata'ni serverga tasdiqlaydi.

        Xatoda ro'yxat SAQLANADI va keyingi urinishda qayta yuboriladi:
        commit qilinmagan yozuv "S3'da fayl bor, DB'da yozuv yo'q"
        degani va bunday fayl retention'ga ham tushmaydi.
        """
        if not self._commits:
            return {"committed": 0}
        batch = list(self._commits)
        try:
            self._repo.commit_screenshots(batch)
        except ClientError as exc:
            if not net_policy.is_poison_payload(exc.status):
                raise
            # Server batch'ni tuzilishi uchun rad etdi — takror abadiy
            # xuddi shunday tugardi va keyingi commit'larni ham ushlardi.
            log.error(
                "Skrinshot commit'i rad etildi (%s %s) - %s ta yozuv tashlandi",
                exc.status, exc.code or "-", len(batch),
            )
        del self._commits[: len(batch)]
        return {"committed": len(batch)}

    # ------------------------------------------------------------------
    def _on_sent(self, result) -> None:
        self._uploading = False
        self._backoff.success()
        count = int((result or {}).get("sent") or 0)
        if count:
            self._total_sent += count
            self.sent.emit(self._total_sent)
        # Yuklash paytida yangi kadr kelgan bo'lishi mumkin.
        self._kick_upload()

    def _on_upload_failed(self, exc) -> None:
        self._uploading = False
        message = getattr(exc, "message", "") or str(exc)
        code = getattr(exc, "code", "") or ""
        # Sessiya yopilgan bo'lsa qayta urinishning ma'nosi yo'q (token
        # bekor): navbat tashlanadi - kadrlar mahalliy arxivda qoladi.
        if code in ("session_not_found", "session_forbidden"):
            self._upload_closed = True
            if self._queue:
                log.warning(
                    "Sessiya yopildi - %s ta skrinshot serverga yuborilmadi (mashinada bor)",
                    len(self._queue),
                )
            self._queue.clear()
        elif self._queue:
            delay = self._backoff.failure(getattr(exc, "retry_after", None))
            self._retry.start(int(delay * 1000))
            log.warning(
                "Skrinshot yuborilmadi (%s): %s - %.0f s dan keyin qayta",
                code or "-", message, delay,
            )
        else:
            log.warning("Skrinshot yuborilmadi (%s): %s", code or "-", message)
        self.failed.emit(message)

    def _on_power_resumed(self) -> None:
        """Uyg'onish: backoff qisqaradi (jitter bilan), navbat bir necha daqiqa kutmaydi."""
        if self._upload_closed or not self._queue or not self._retry.isActive():
            return
        self._backoff.nudge(5.0)
        self._retry.start(int(self._backoff.remaining() * 1000))

    def shutdown(self) -> None:
        """Dasturdan chiqish: qolgan ish CHEGARALANGAN vaqt kutiladi."""
        self.stop()
        self._retry.stop()
        if self._commits and not self._upload_closed:
            # Commit qilinmagan S3 fayli proktorga ko'rinmaydi va
            # retention'ga tushmaydi - best-effort.
            worker = ApiWorker(self._flush_commits, parent=self)
            self._workers.run(worker)
        self._workers.wait_all(5_000)
