"""
Kamera oqimlari va ularni boshqarish.

IKKI DARAJA:

    CameraStream  — bitta manba uchun thread: o'qish sikli, FPS
                    o'lchash, uzilishni aniqlash va qayta ulanish.
                    Manba turini BILMAYDI.
    CameraManager — ikkita slot (`primary` / `secondary`), serverdan
                    kelgan tavsifdan manba yasash, umumiy holat.

Bu bo'linish ataylab: qayta ulanish mantig'i har bir vendor uchun
qaytadan yozilsa, ular albatta bir-biridan farq qiladi va nosozlik
"ba'zi kameralarda ishlaydi, ba'zilarida yo'q" ko'rinishini oladi —
proktorlikda eng qimmat turdagi xato.

THREAD QOIDALARI (ikkalasi ham loyihada allaqachon qulash sababi
bo'lgan, `CLAUDE.md` tuzoqlariga qarang):

  * "ishlayapti" bayrog'i KONSTRUKTORDA `True` qilinadi va faqat
    `stop()` uni o'chiradi. `run()` ichida qo'yilsa, `start()` dan
    keyin darhol `stop()` chaqirilganda sikl abadiy ishlaydi;
  * signal `event` deb NOMLANMAYDI — `QObject.event()` Qt'ning
    markaziy virtual metodi va uni bosib qo'yish jarayonni jimgina
    o'ldiradi.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Callable, Optional

import numpy as np
from PyQt6.QtCore import QMutex, QMutexLocker, QObject, QThread, pyqtSignal

from proctoring.camera.base import (
    CameraHealth,
    CameraInfo,
    CameraSource,
    CameraSpec,
    CameraState,
)

log = logging.getLogger(__name__)

#: Qayta ulanish kechikishlari (soniya). Oxirgisi takrorlanadi.
#:
#: `services/realtime.py` dagi WebSocket backoff bilan AYNAN bir xil
#: va bu ataylab: ikkala joyda ham muammo bitta — server yoki qurilma
#: qayta ishga tushganda barcha clientlar bir vaqtda urilib, uni yana
#: yiqitadi.
_BACKOFF_S = (1, 2, 4, 8, 15, 30)

#: Ketma-ket shuncha bo'sh kadrdan keyin uzilish deb hisoblanadi.
#:
#: Bitta o'tkazib yuborilgan kadr USB kamerada ODATIY hol va uni
#: uzilish deb hisoblash hodisa oqimini soxta `camera_lost` bilan
#: to'ldirardi. 30 kadr ~1 soniya.
_EMPTY_FRAMES_BEFORE_LOST = 30

#: FPS shuncha oxirgi kadr bo'yicha hisoblanadi.
_FPS_WINDOW = 30

#: Sog'liq ma'lumoti shuncha ms da bir marta chiqariladi.
#:
#: Har kadrda emas: 30 FPS x 2 kamera = sekundiga 60 ta signal va
#: ularning har biri UI'da nishonni qayta chizardi.
_HEALTH_INTERVAL_MS = 1000


class CameraStream(QThread):
    """
    Bitta kamera manbaining o'qish sikli.

    Signallar:
        frame_ready(str role, object frame) — oldindan ko'rish uchun kadr
        health_changed(str role, dict)      — o'lchangan holat
        state_changed(str role, str state)  — holat o'zgardi
    """

    frame_ready = pyqtSignal(str, object)
    health_changed = pyqtSignal(str, dict)
    state_changed = pyqtSignal(str, str)

    def __init__(
        self,
        source: CameraSource,
        *,
        preview_fps: int = 15,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._source = source
        self._role = source.info.role or "primary"
        # `True` KONSTRUKTORDA. Sabab yuqoridagi modul izohida.
        self._running = True
        self._preview_interval = 1.0 / max(1, preview_fps)

        self._health = CameraHealth()
        self._frame_times: deque = deque(maxlen=_FPS_WINDOW)
        self._read_times: deque = deque(maxlen=_FPS_WINDOW)

        # Oxirgi kadr AI pipeline uchun. Signal orqali emas, chunki
        # pipeline kadrni O'ZI so'raganda oladi (u o'z chastotasida
        # ishlaydi va har kadrni ko'rishi shart emas). Signal bilan
        # bo'lsa, pipeline navbatida kerak bo'lmagan kadrlar
        # to'planardi.
        self._latest: Optional[np.ndarray] = None
        self._latest_at: float = 0.0
        self._mutex = QMutex()

    # ------------------------------------------------------------------
    @property
    def role(self) -> str:
        return self._role

    @property
    def info(self) -> CameraInfo:
        return self._source.info

    @property
    def health(self) -> CameraHealth:
        return self._health

    def latest_frame(self) -> tuple[Optional[np.ndarray], float]:
        """
        Oxirgi kadr va uning vaqti.

        Kadr NUSXALANMAYDI: pipeline uni faqat o'qiydi va o'qish
        siklidagi keyingi kadr yangi massiv bo'ladi (OpenCV har
        `read()` da yangi buferni qaytaradi). Nusxa olish 1080p da
        ~6 MB/kadr keraksiz ko'chirish bo'lardi.
        """
        with QMutexLocker(self._mutex):
            return self._latest, self._latest_at

    def stop(self) -> None:
        """
        To'xtatish so'rovi.

        `terminate()` ISHLATILMAYDI: u kamera deskriptorini ochiq
        qoldiradi va Windows'da qurilma keyingi safar umuman
        ochilmaydi.
        """
        self._running = False

    # ------------------------------------------------------------------
    def run(self) -> None:
        # `start()` dan keyin darhol `stop()` chaqirilgan bo'lishi
        # mumkin — unda kamerani umuman ochmaymiz.
        if not self._running:
            return

        attempt = 0
        while self._running:
            self._set_state(CameraState.OPENING if attempt == 0 else CameraState.RECONNECTING)

            if not self._source.open():
                self._health.last_error = self._source.last_error
                log.warning("[%s] %s", self._role, self._source.last_error)
                if not self._sleep_backoff(attempt):
                    break
                attempt += 1
                self._health.reconnects += 1
                continue

            attempt = 0
            self._set_state(CameraState.ONLINE)
            self._read_loop()

            self._source.close()
            if not self._running:
                break
            # Sikl uzilish sababli tugadi — qayta ulanamiz.
            self._health.reconnects += 1
            if not self._sleep_backoff(0):
                break

        self._source.close()
        self._set_state(CameraState.CLOSED)
        log.info("[%s] kamera oqimi yopildi", self._role)

    # ------------------------------------------------------------------
    def _read_loop(self) -> None:
        empty_streak = 0
        last_preview = 0.0
        last_health = 0.0

        while self._running:
            started = time.monotonic()
            frame = self._source.read()
            elapsed = time.monotonic() - started

            if frame is None:
                empty_streak += 1
                self._health.frames_dropped += 1
                if empty_streak >= _EMPTY_FRAMES_BEFORE_LOST:
                    self._health.last_error = "Kameradan kadr kelmayapti"
                    self._set_state(CameraState.FAILED)
                    return
                # Qisqa kutish: bo'sh siklda protsessorni yemaslik uchun.
                self.msleep(30)
                continue

            empty_streak = 0
            now = time.monotonic()
            self._health.frames_total += 1
            self._frame_times.append(now)
            self._read_times.append(elapsed * 1000.0)

            with QMutexLocker(self._mutex):
                self._latest = frame
                self._latest_at = now

            if now - last_preview >= self._preview_interval:
                last_preview = now
                # Kadr NUSXASI: signal boshqa thread'ga o'tadi va u
                # yerda chizilguncha o'qish sikli massivni qayta
                # ishlatishi mumkin (ba'zi backendlar shunday qiladi).
                # Oldindan ko'rish uchun bu yagona nusxa va u
                # miqyoslangan emas — hajmi kichik.
                self.frame_ready.emit(self._role, frame.copy())

            if (now - last_health) * 1000.0 >= _HEALTH_INTERVAL_MS:
                last_health = now
                self._publish_health(now)

    def _publish_health(self, now: float) -> None:
        self._health.fps = self._measured_fps(now)
        self._health.frame_age_ms = int((now - self._latest_at) * 1000)
        self._health.read_latency_ms = (
            sum(self._read_times) / len(self._read_times) if self._read_times else 0.0
        )
        self.health_changed.emit(self._role, self._health.as_dict())

    def _measured_fps(self, now: float) -> float:
        """
        HAQIQIY FPS.

        Qurilma e'lon qilgan qiymat ishlatilmaydi: USB kamera 30 FPS
        deb e'lon qilib, past yorug'likda ekspozitsiyani uzaytirgani
        sababli 7 FPS beradi — proktorlik uchun butunlay boshqa sifat
        va aynan shu farqni tekshiruv sahifasi ko'rsatishi kerak.
        """
        if len(self._frame_times) < 2:
            return 0.0
        span = self._frame_times[-1] - self._frame_times[0]
        if span <= 0:
            return 0.0
        return (len(self._frame_times) - 1) / span

    def _sleep_backoff(self, attempt: int) -> bool:
        """
        Qayta urinishdan oldingi kutish. `False` — to'xtatish so'raldi.

        Kutish KICHIK bo'laklarda: bitta uzun `msleep(30000)` da
        `stop()` bayrog'i 30 soniya davomida o'qilmasdi va dastur
        yopilishida shuncha kutishga majbur bo'lardi.
        """
        delay = _BACKOFF_S[min(attempt, len(_BACKOFF_S) - 1)]
        deadline = time.monotonic() + delay
        while self._running and time.monotonic() < deadline:
            self.msleep(100)
        return self._running

    def _set_state(self, state: CameraState) -> None:
        if self._health.state == state:
            return
        self._health.state = state
        self.state_changed.emit(self._role, state.value)


class _DiscoveryThread(QThread):
    """
    Lokal kameralarni sanab chiquvchi bir martalik thread.

    MODUL DARAJASIDA, metod ichida emas: `QObject` merosxo'ri har
    e'lon qilinganda Qt metaobyekti quriladi. Uni funksiya ichida
    yozish har chaqiruvda yangi sinf (va yangi metaobyekt) yaratardi -
    xotira sekin o'sardi va PyQt ba'zi versiyalarida bu ogohlantirish
    beradi.
    """

    found = pyqtSignal(list)

    def run(self) -> None:
        from proctoring.camera import discovery

        try:
            self.found.emit(discovery.probe())
        except Exception:
            # Aniqlash muvaffaqiyatsiz tugashi imtihonni to'xtatmaydi:
            # zaxira indeks (`CAMERA_INDEX`) baribir ochiladi va
            # operator kadrni ko'rib qaror qabul qiladi.
            log.exception("Kameralarni aniqlashda xato")
            self.found.emit([])


class CameraSlot:
    """Bitta rol: tavsif + oqim. Oqim hali ochilmagan bo'lishi mumkin."""

    def __init__(self, spec: CameraSpec) -> None:
        self.spec = spec
        self.stream: Optional[CameraStream] = None

    @property
    def role(self) -> str:
        return self.spec.role

    @property
    def is_running(self) -> bool:
        return self.stream is not None and self.stream.isRunning()


class CameraManager(QObject):
    """
    Ikkita kamera sloti va ularning hayot sikli.

    NIMA UCHUN AYNAN IKKITA: rollar ma'noga ega va ular
    almashtirilmaydi. Birlamchi kamera talabgorning YUZIGA qaraydi
    (shaxs, nigoh, bosh holati), ikkilamchisi stol/qo'l/xonaga.
    Uchinchi kamera qo'shish uchun uning VAZIFASI aniqlanishi kerak —
    "yana bitta kamera" o'z-o'zicha hech narsa bermaydi va faqat
    yuklamani oshiradi.
    """

    frame_ready = pyqtSignal(str, object)
    health_changed = pyqtSignal(str, dict)
    state_changed = pyqtSignal(str, str)
    #: Aniqlangan lokal kameralar ro'yxati tayyor bo'lganda.
    devices_discovered = pyqtSignal(list)

    ROLES = ("primary", "secondary")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._slots: dict[str, CameraSlot] = {}
        self._stream_url_provider: Optional[Callable[[str], dict]] = None
        self._discovered: list = []
        self._discovery_thread: Optional[QThread] = None
        self._retired: list = []

    # ------------------------------------------------------------------
    # Sozlash
    # ------------------------------------------------------------------
    def configure(self, slots_payload: dict, *, stream_url_provider=None) -> None:
        """
        Serverdan kelgan `camera/config/` javobini qabul qiladi.

        `stream_url_provider(role) -> dict` — IP kamera uchun
        kredensialni SO'RAYDIGAN funksiya. Manager uni faqat oqim
        ochilayotganda chaqiradi va natijani SAQLAMAYDI: kredensial
        client xotirasida qancha kam yashasa, shuncha yaxshi.

        TAKRORIY CHAQIRUV XAVFSIZ: slotlar almashtirilishidan oldin
        ishlab turgan oqimlar to'xtatiladi. Aks holda eski
        `CameraSlot` obyektlari almashtirilar va ularning
        thread'lariga referens YO'QOLARDI — kamera ochiq qolib,
        keyingi ochish "qurilma band" bilan tugardi (va Qt tugamagan
        thread yo'q qilinganda dasturni qulatardi).
        """
        self.stop()
        self._stream_url_provider = stream_url_provider
        payload = slots_payload or {}
        # Asosiy rollar HAR DOIM bor (bo'sh bo'lsa ham - "kamera yo'q"
        # holatini ifodalash uchun). Ularga qo'shimcha - tekshiruv
        # sahifasidagi ZAXIRA qurilmalar (`spare:<kalit>`): ular faqat
        # oldindan ko'rish uchun ochiladi, kuzatuvga kirmaydi.
        names = list(self.ROLES) + [name for name in payload if name not in self.ROLES]
        self._slots = {
            name: CameraSlot(CameraSpec.from_api(name, payload.get(name)))
            for name in names
        }

    def spec(self, role: str) -> Optional[CameraSpec]:
        slot = self._slots.get(role)
        return slot.spec if slot else None

    def stream(self, role: str) -> Optional[CameraStream]:
        slot = self._slots.get(role)
        return slot.stream if slot else None

    def latest_frame(self, role: str):
        stream = self.stream(role)
        return stream.latest_frame() if stream is not None else (None, 0.0)

    @property
    def discovered(self) -> list:
        return list(self._discovered)

    # ------------------------------------------------------------------
    # Lokal qurilmalarni aniqlash
    # ------------------------------------------------------------------
    def discover_async(self) -> None:
        """
        Lokal kameralarni FON rejimida aniqlaydi.

        Bloklovchi (~0.8 s har bir indeks uchun) va UI thread'ida
        bo'lsa, kamera tekshiruvi sahifasi ochilishida oyna bir necha
        soniya muzlab qolardi.
        """
        if self._discovery_thread is not None and self._discovery_thread.isRunning():
            return

        thread = _DiscoveryThread(self)
        thread.found.connect(self._on_discovered)
        thread.finished.connect(self._on_discovery_finished)
        self._discovery_thread = thread
        thread.start()

    def _on_discovery_finished(self) -> None:
        self._discovery_thread = None

    def _on_discovered(self, cameras: list) -> None:
        self._discovered = cameras
        self.devices_discovered.emit([item.as_dict() for item in cameras])

    # ------------------------------------------------------------------
    # Oqimlar
    # ------------------------------------------------------------------
    def start(self, roles=None, *, preview_fps: int = 15) -> None:
        """Berilgan rollar uchun oqimni ochadi (standart — hammasi)."""
        for role in roles or list(self._slots):
            self._start_role(role, preview_fps=preview_fps)

    def _start_role(self, role: str, *, preview_fps: int) -> None:
        slot = self._slots.get(role)
        if slot is None or not slot.spec.assigned:
            return
        if slot.is_running:
            return

        source = self._build_source(slot.spec)
        if source is None:
            return

        stream = CameraStream(source, preview_fps=preview_fps, parent=self)
        stream.frame_ready.connect(self.frame_ready)
        stream.health_changed.connect(self.health_changed)
        stream.state_changed.connect(self.state_changed)
        slot.stream = stream
        stream.start()

    def _build_source(self, spec: CameraSpec) -> Optional[CameraSource]:
        """
        Manba yasash `camera/factory.py` da — BU YERDA EMAS.

        Sabab: kamerani ochadigan ikkinchi chaqiruvchi ham bor
        (FaceID sahifasining `CameraWorker` i) va u ilgari qurilmani
        o'zi ochardi. Natijada tanlangan rol e'tiborsiz qolar va
        FaceID boshqa kamerani ochardi. Qoida bitta joyda bo'lishi
        kerak.
        """
        from proctoring.camera.factory import build_source

        return build_source(
            spec,
            stream_url_provider=self._stream_url_provider,
            discovered=self._discovered,
        )

    # ------------------------------------------------------------------
    def stop(self, roles=None, *, timeout_ms: int = 8000) -> None:
        for role in roles or list(self._slots):
            slot = self._slots.get(role)
            if slot is None or slot.stream is None:
                continue
            self._retire(slot.stream, timeout_ms)
            slot.stream = None

    def _retire(self, stream: CameraStream, timeout_ms: int) -> None:
        """
        Oqimni to'xtatadi va tugashini kutadi.

        Tugamagan thread SAQLANADI (`_retired`). Sabab
        `services/camera_worker.retire_camera` dagi bilan bir xil:
        `cv2.VideoCapture` konstruktori bloklovchi va kamera band
        bo'lsa bir necha soniya ushlab turadi. Shunday thread obyekti
        yo'q qilinsa, Qt "Destroyed while thread is still running"
        bilan BUTUN DASTURNI qulatadi.
        """
        stream.stop()
        if stream.wait(timeout_ms):
            stream.deleteLater()
            return

        log.warning(
            "[%s] kamera thread'i %s ms ichida tugamadi — kutish davom etadi",
            stream.role, timeout_ms,
        )
        if stream not in self._retired:
            self._retired.append(stream)
            stream.finished.connect(
                lambda: self._retired.remove(stream) if stream in self._retired else None
            )

    def shutdown(self, timeout_ms: int = 10000) -> None:
        """Dastur yopilishidan oldingi oxirgi tozalash."""
        self.stop()

        if self._discovery_thread is not None and self._discovery_thread.isRunning():
            self._discovery_thread.wait(3000)

        for stream in list(self._retired):
            if stream.isRunning() and not stream.wait(timeout_ms):
                # Oxirgi chora: jarayon baribir yakunlanyapti, ishlab
                # turgan thread bilan chiqish esa qulash demak.
                log.error("[%s] kamera thread'i to'xtamadi — terminate", stream.role)
                stream.terminate()
                stream.wait(2000)
        self._retired.clear()
