"""
Ekran suratlarini olish, siqish va serverga yuborish.

Bu modul backendning IKKI xil skrinshot yo'lini ham biladi va o'rnatish
profiliga qarab bittasini tanlaydi (`_resolve_mode`):

    S3/MinIO    presign -> PUT (binary backend'dan O'TMAYDI) -> commit
    Fayl tizimi upload/ (binary Django worker'idan o'tadi)

Client qaysi biri yoqilganini OLDINDAN bilmaydi: handshake
konfiguratsiyasi buni aytmaydi va aytmasligi ham to'g'ri - bu server
infratuzilmasining tafsiloti. Shuning uchun rejim sessiya boshida BIR
MARTA aniqlanadi: `presign/` 503 qaytarsa ("Object storage yoqilmagan"),
qolgan hamma narsa fayl tizimi yo'lidan ketadi.

Yuklama bo'yicha uchta qaror:

  1. DEDUP. Talabgor asosan qimirlamaydi va ketma-ket kadrlar deyarli
     bir xil bo'ladi. Har birini yuborish trafikni bekorga ~10 barobar
     oshiradi. Kadr oldingisi bilan pertseptual hash (dHash) orqali
     solishtiriladi va farq chegaradan kichik bo'lsa - YUBORILMAYDI.

  2. ISH BO'LINISHI. Kadr olish va hash hisoblash UI thread'da (Qt'da
     ekran nusxasi GUI thread'iga bog'langan), miqyoslash, JPEG kodlash
     va yuborish esa fon thread'ida. Kodlash ~30 ms va u UI thread'da
     bo'lsa, WebView har 10 soniyada seziladigan darajada tutilib
     qolardi.

  3. BITTA UCHUVCHI SO'ROV. Ayni paytda faqat bitta yuklash ketadi.
     Tarmoq uzilganda so'rov `API_TIMEOUT` (30 s) gacha osilib turishi
     mumkin; bu paytda har bir yangi kadr uchun thread ochilsa, ular
     to'planib RAM'ni yeb qo'yardi.

NIMA UCHUN KADR YO'QOLISHI MUMKIN va bu ongli kelishuv: yuborib
bo'lmagan kadrlar CHEKLANGAN navbatda saqlanadi
(`SCREENSHOT_RETRY_QUEUE`). Uzoq uzilishda eng eskisi tushib qoladi.
Muqobili - diskka yozish, lekin u imtihon mashinasida talabgor
ekranining nusxasini qoldiradi va bu skrinshotni umuman yubormaslikdan
battar.

Veb-kamera kadrlari BU YERDA yuborilmaydi: ularning o'z kanali bor
(davriy FaceID, `image_key`), fayl tizimi yo'li esa `kind` maydonini
umuman qabul qilmaydi - `ProctoringScreenshot` da bunday ustun yo'q.
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
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QApplication

from config import SCREENSHOT_ENABLED, SCREENSHOT_RETRY_QUEUE
from core.errors import ClientError
from services.api_client import ApiClient
from services.repositories import ProctoringRepository
from services.workers import ApiWorker, WorkerHolder

log = logging.getLogger(__name__)

#: Server sozlamasi kelmasa ishlatiladigan qiymatlar.
#:
#: `controls.Setting` modelidagi standartlar bilan BIR XIL bo'lishi
#: shart - aks holda sozlamasi o'chirilgan tizimda client boshqacha
#: ishlaydi va farqni tushuntirish qiyin bo'ladi.
_FALLBACK = {
    "screenshot_interval": 10,
    "quality": 65,
    "max_width": 960,
    "dedup_threshold": 6,
}

#: Bir marta nechta presigned URL so'raladi.
#:
#: Har kadr uchun alohida `presign/` chaqirish - bitta skrinshotga uchta
#: so'rov (presign + PUT + commit) degani. Pool bilan bu ~1.4 ga tushadi.
#: Pool o'lchami `S3_PRESIGN_TTL` (300 s) bilan cheklanadi: 10 soniyalik
#: intervalda 5 ta URL 50 soniyaga yetadi, ya'ni ular ishlatilgunga
#: qadar muddati tugamaydi.
_PRESIGN_POOL = 5

#: Shuncha yig'ilgach `commit/` batch bilan yuboriladi.
_COMMIT_BATCH = 5

#: Presigned URL muddati tugashiga shuncha qolganda ishlatilmaydi.
_PRESIGN_SAFETY_S = 30

#: Ketma-ket shuncha kadr dedup bilan o'tkazib yuborilgach, keyingisi
#: MAJBURIY yuboriladi.
#:
#: Ikki sabab, ikkalasi ham dalilga tegishli:
#:
#:   1. dHash 64 bitga siqilgan tuzilma va u yo'qotishli. Katta tekis
#:      maydonli ekranlarda (oq hujjat sahifasi) turli mazmun bir xil
#:      hash berishi MUMKIN. Dedup - trafik optimizatsiyasi, u dalilda
#:      ko'r oyna yarata olmasligi kerak.
#:   2. Muntazam kadr client tirikligining dalili. Umuman skrinshot
#:      kelmasa, "ekran o'zgarmadi" va "nazorat ishlamay qoldi"
#:      holatlarini bayonnomada ajratib bo'lmaydi.
#:
#: 10 soniyalik intervalda 6 - kamida daqiqada bitta kadr degani.
_FORCE_SEND_AFTER_SKIPS = 6


# --------------------------------------------------------------------------
# Konfiguratsiya
# --------------------------------------------------------------------------
@dataclass
class CaptureConfig:
    """Handshake konfiguratsiyasidagi `capture` bo'limi."""

    interval_s: int
    quality: int
    max_width: int
    dedup_threshold: int

    @classmethod
    def from_server(cls, config: Optional[dict]) -> "CaptureConfig":
        capture = (config or {}).get("capture") or {}

        def value(name: str) -> int:
            try:
                raw = int(capture.get(name, _FALLBACK[name]))
            except (TypeError, ValueError):
                return _FALLBACK[name]
            return raw if raw > 0 else _FALLBACK[name]

        try:
            dedup = int(capture.get("dedup_threshold", _FALLBACK["dedup_threshold"]))
        except (TypeError, ValueError):
            dedup = _FALLBACK["dedup_threshold"]

        return cls(
            # Interval juda kichik bo'lsa `client_ingest` chegarasini
            # (600/min) yeb qo'yadi: 1 soniya = daqiqasiga 180 so'rov
            # faqat skrinshot uchun. Pastki chegara shuning uchun.
            interval_s=max(3, value("screenshot_interval")),
            quality=max(20, min(95, value("quality"))),
            max_width=max(320, value("max_width")),
            # `0` - dedup butunlay o'chirilgan, har kadr yuboriladi.
            dedup_threshold=max(0, min(64, dedup)),
        )


@dataclass
class Frame:
    """Kodlangan, yuborishga tayyor kadr."""

    data: bytes
    width: int
    height: int
    captured_at: str
    sha256: str


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
# Dedup
# --------------------------------------------------------------------------
def dhash(image: QImage) -> int:
    """
    Pertseptual hash (difference hash), 64 bit.

    Rasm 9x8 kul rangga siqiladi va qo'shni piksellar solishtiriladi:
    natija YORUG'LIKKA emas, TUZILISHGA bog'liq bo'ladi. Shuning uchun
    monitor yorqinligining o'zgarishi yoki JPEG shovqini hash'ni
    o'zgartirmaydi, oynadagi haqiqiy o'zgarish esa o'zgartiradi.

    Nima uchun sha256 emas: siqilgan kadrlarning bayt-hash'i deyarli HAR
    DOIM boshqacha bo'ladi (o'sha JPEG shovqini), ya'ni u dedup uchun
    umuman yaramaydi. sha256 boshqa vazifa uchun kerak - u serverga
    yaxlitlik dalili sifatida yuboriladi.
    """
    small = image.scaled(
        9,
        8,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    ).convertToFormat(QImage.Format.Format_Grayscale8)

    bits = 0
    for y in range(8):
        for x in range(8):
            # Grayscale8 da r == g == b, shuning uchun istalgan kanal.
            left = small.pixelColor(x, y).red()
            right = small.pixelColor(x + 1, y).red()
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def hamming(left: int, right: int) -> int:
    return bin(left ^ right).count("1")


# --------------------------------------------------------------------------
# Kodlash
# --------------------------------------------------------------------------
def encode_jpeg(image: QImage, *, max_width: int, quality: int) -> Optional[Frame]:
    """
    Kadrni miqyoslaydi va JPEG'ga kodlaydi.

    Fon thread'ida bajariladi - `QImage` (`QPixmap` dan farqli) GUI
    thread'iga bog'lanmagan.
    """
    if image.width() > max_width:
        image = image.scaledToWidth(
            max_width, Qt.TransformationMode.SmoothTransformation
        )

    buffer = QBuffer()
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        return None
    try:
        if not image.save(buffer, "JPEG", quality):
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
        captured_at=datetime.now(timezone.utc).isoformat(),
        sha256=hashlib.sha256(data).hexdigest(),
    )


# --------------------------------------------------------------------------
# Xizmat
# --------------------------------------------------------------------------
class ScreenshotService(QObject):
    """
    Sessiya davomida ishlaydigan skrinshot oquvchisi.

    `start(config)` sessiya tokeni olingandan KEYIN chaqiriladi: ikkala
    endpoint ham `X-Proctoring-Session` talab qiladi.
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
        self._inflight = False
        self._total_sent = 0
        self._last_hash: Optional[int] = None
        #: Ketma-ket dedup bilan o'tkazib yuborilgan kadrlar soni.
        self._skipped = 0

        #: Yuborilmagan kadrlar (kodlangan). Cheklangan - RAM uchun.
        self._queue = deque(maxlen=max(1, SCREENSHOT_RETRY_QUEUE))
        #: S3 yo'li uchun: tayyor presigned URL'lar va kutayotgan commit'lar.
        self._presigned = deque()
        self._commits: list[dict] = []
        #: `None` - hali aniqlanmagan; keyin `"s3"` yoki `"filesystem"`.
        self._mode: Optional[str] = None

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

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
    def start(self, config: Optional[dict]) -> None:
        if self._active:
            return
        if not SCREENSHOT_ENABLED:
            log.info("Skrinshot olish o'chirilgan (SCREENSHOT_ENABLED=0)")
            return

        self._config = CaptureConfig.from_server(config)
        self._active = True
        self._last_hash = None
        self._skipped = 0
        self._total_sent = 0
        self._queue.clear()
        self._presigned.clear()
        self._commits.clear()
        self._mode = None

        self._timer.setInterval(self._config.interval_s * 1000)
        self._timer.start()
        # Birinchi kadr DARHOL: imtihon boshlangan payt eng muhim
        # daqiqalardan biri va uni interval oxirigacha kutish shart emas.
        self._tick()
        log.info(
            "Skrinshot: har %s s, maks. kenglik %s px, sifat %s, dedup %s bit",
            self._config.interval_s,
            self._config.max_width,
            self._config.quality,
            self._config.dedup_threshold,
        )

    def stop(self) -> None:
        if not self._active:
            return
        self._active = False
        self._timer.stop()

        # Qolgan commit'lar best-effort yuboriladi: ularsiz S3'ga
        # yuklangan fayllar metadata'siz qoladi, ya'ni proktor ularni
        # umuman ko'rmaydi va retention ham ularga yetmaydi.
        if self._commits:
            worker = ApiWorker(self._flush_commits, parent=self)
            worker.failed.connect(
                lambda message, code: log.warning("Commit yuborilmadi: %s", message)
            )
            self._workers.run(worker)

        self._workers.wait_all(10_000)
        if self._queue:
            log.warning("%s ta skrinshot yuborilmay qoldi (tarmoq)", len(self._queue))
        log.info("Skrinshot xizmati to'xtadi (jami %s ta)", self._total_sent)

    # ------------------------------------------------------------------
    def _tick(self) -> None:
        """
        Bitta kadr: olish -> dedup -> fon thread'iga uzatish.

        Bu yerda kodlash YO'Q: u ~30 ms va UI thread'ini tutib qoladi.
        """
        if not self._active:
            return
        if self._inflight:
            # Oldingi yuklash hali tugamagan (odatda tarmoq sekin).
            # Yangi thread ochish o'rniga bu kadr tashlab yuboriladi:
            # navbat baribir cheklangan va eng yangi kadr qimmatliroq.
            log.debug("Skrinshot: oldingi yuklash tugamagan, kadr o'tkazildi")
            return

        image = grab_screens()
        if image is None or image.isNull():
            log.warning("Ekran nusxasini olib bo'lmadi")
            return

        if self._is_duplicate(image):
            return

        self._inflight = True
        worker = ApiWorker(self._encode_and_send, image, parent=self)
        worker.succeeded.connect(self._on_sent)
        worker.failed.connect(self._on_failed)
        self._workers.run(worker)

    def _is_duplicate(self, image: QImage) -> bool:
        """
        Kadr oldingisidan sezilarli farq qiladimi.

        `dedup_threshold` - dHash'dagi FARQLI BITLAR soni (0..64).
        Standart 6: 64 bitdan oltitasining o'zgarishi kursor siljishi
        yoki soat raqamining almashishi darajasidagi o'zgarish; sahifa
        almashsa yoki yangi oyna ochilsa farq bundan ancha katta bo'ladi.

        `0` - dedup o'chirilgan, har kadr yuboriladi.

        `_FORCE_SEND_AFTER_SKIPS` ta ketma-ket o'tkazishdan keyin kadr
        chegaradan qat'i nazar yuboriladi.
        """
        if self._config.dedup_threshold <= 0:
            return False
        try:
            current = dhash(image)
        except Exception:
            # Hash hisoblab bo'lmasa kadr YUBORILADI: dedup - trafik
            # optimizatsiyasi va uning nosozligi dalilni yo'qotmasligi
            # kerak.
            log.debug("dHash hisoblanmadi", exc_info=True)
            self._skipped = 0
            return False

        previous = self._last_hash
        self._last_hash = current
        if previous is None:
            self._skipped = 0
            return False

        if hamming(previous, current) > self._config.dedup_threshold:
            self._skipped = 0
            return False

        self._skipped += 1
        if self._skipped >= _FORCE_SEND_AFTER_SKIPS:
            log.debug(
                "Skrinshot: %s ta bir xil kadrdan keyin majburiy yuborish",
                self._skipped,
            )
            self._skipped = 0
            return False
        return True

    # ------------------------------------------------------------------
    # Fon thread'i
    # ------------------------------------------------------------------
    def _encode_and_send(self, image: QImage) -> dict:
        """
        Kodlaydi, navbatga qo'yadi va navbatni to'liq bo'shatishga urinadi.

        Navbat TARTIB bilan bo'shatiladi (`popleft`): skrinshotlar vaqt
        ketma-ketligida dalil bo'lib xizmat qiladi va tartibning buzilishi
        bayonnomani o'qishni qiyinlashtiradi.
        """
        frame = encode_jpeg(
            image, max_width=self._config.max_width, quality=self._config.quality
        )
        if frame is None:
            raise ClientError("Skrinshotni kodlab bo'lmadi", code="encode_failed")

        if len(self._queue) == self._queue.maxlen:
            log.warning("Skrinshot navbati to'ldi - eng eski kadr tashlandi")
        self._queue.append(frame)

        sent = 0
        while self._queue:
            # Navbat boshidagi kadr yuboriladi va FAQAT muvaffaqiyatdan
            # keyin olib tashlanadi. Xatoda istisno ko'tariladi va kadr
            # o'z o'rnida qoladi.
            self._upload(self._queue[0])
            self._queue.popleft()
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
                    data=frame.data, captured_at=frame.captured_at
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
                }
            )
            if len(self._commits) >= _COMMIT_BATCH:
                self._flush_commits()
            return

        self._repo.upload_screenshot(data=frame.data, captured_at=frame.captured_at)

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
        self._repo.commit_screenshots(batch)
        del self._commits[: len(batch)]
        return {"committed": len(batch)}

    # ------------------------------------------------------------------
    def _on_sent(self, result) -> None:
        self._inflight = False
        count = int((result or {}).get("sent") or 0)
        if count:
            self._total_sent += count
            self.sent.emit(self._total_sent)

    def _on_failed(self, message: str, code: str) -> None:
        self._inflight = False
        # Sessiya yo'qolgan bo'lsa qayta urinishning ma'nosi yo'q:
        # `SessionMonitor` buni allaqachon aniqlaydi va oqimni yopadi.
        if code in ("session_not_found", "session_forbidden"):
            self._active = False
            self._timer.stop()
        log.warning("Skrinshot yuborilmadi (%s): %s", code or "-", message)
        self.failed.emit(message)

    def shutdown(self) -> None:
        self.stop()
        self._workers.wait_all(5_000)
