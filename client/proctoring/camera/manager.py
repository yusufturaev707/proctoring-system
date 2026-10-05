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
from proctoring.camera.liveness import DEAD_STREAM_MESSAGE, FrameLiveness
from proctoring.camera.liveness import applies as liveness_applies

log = logging.getLogger(__name__)

#: Qayta ulanish kechikishlari (soniya). Oxirgisi takrorlanadi.
#:
#: `services/realtime.py` dagi WebSocket backoff bilan AYNAN bir xil
#: va bu ataylab: ikkala joyda ham muammo bitta — server yoki qurilma
#: qayta ishga tushganda barcha clientlar bir vaqtda urilib, uni yana
#: yiqitadi.
_BACKOFF_S = (1, 2, 4, 8, 15, 30)

#: LOKAL kamera uchun qisqaroq qator.
#:
#: Yuqoridagi sabab (hamma bir vaqtda serverga/kameraga urilishi)
#: USB kameraga tegishli emas: uni faqat shu mashina ochadi va
#: urinish arzon (qurilma yo'q bo'lsa DirectShow darhol rad etadi).
#: 30 s kutish esa imtihon paytida kabel qayta ulangandan keyin
#: yarim daqiqa kuzatuvsiz qolish degani bo'lardi.
_LOCAL_BACKOFF_S = (1, 2, 3, 5)

#: Ketma-ket shuncha bo'sh kadrdan keyin uzilish deb hisoblanadi.
#:
#: Bitta o'tkazib yuborilgan kadr USB kamerada ODATIY hol va uni
#: uzilish deb hisoblash hodisa oqimini soxta `camera_lost` bilan
#: to'ldirardi. 30 kadr ~1 soniya.
_EMPTY_FRAMES_BEFORE_LOST = 30

#: Qurilma hali tizimdami - shu oraliqda (s). DirectShow ro'yxati
#: (~ms), kameraga tegmaydi.
_PRESENCE_CHECK_S = 2.0

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
        #: Qayta ulanish so'raldi (kompyuter uyqudan uyg'ondi). Sikl
        #: joriy ulanishni yopib, KUTMASDAN qaytadan ochadi.
        self._reconnect_requested = False
        #: Uzilish davom etyapti (FAILED aytilgan, tirik kadr hali yo'q).
        self._outage = False
        _connect_power_resumed(self.request_reconnect)

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
        # Osilgan `open()`/`read()` kutishini ham darhol uzadi
        # (`guard.GuardedSource`) — aks holda `_retire` UI thread'ida
        # o'sha chaqiruvning vaqt chegarasigacha kutardi.
        abort = getattr(self._source, "abort", None)
        if abort is not None:
            try:
                abort()
            except Exception:
                log.debug("[%s] abort xatosi", self._role, exc_info=True)

    def request_reconnect(self) -> None:
        """
        Joriy ulanishni yopib, darhol qaytadan ochish (uyqudan keyin).

        Uyg'onishdan keyin DirectShow qurilmasi ko'pincha "ochiq"
        bo'lib qoladi, lekin qora yoki qotgan kadr beradi — o'qish
        xato qaytarmaguncha uzilish sezilmasdi. Signal asosiy
        thread'dan keladi; bayroq oddiy `bool` (GIL ostida atomik).
        """
        if self._running:
            log.info("[%s] qayta ulanish so'raldi (uyqudan uyg'onish)", self._role)
            self._reconnect_requested = True

    # ------------------------------------------------------------------
    def run(self) -> None:
        # `start()` dan keyin darhol `stop()` chaqirilgan bo'lishi
        # mumkin — unda kamerani umuman ochmaymiz.
        if not self._running:
            return

        # BUTUN SIKL HIMOYALANGAN. Thread ichidagi tutilmagan istisno
        # oqimni jimgina o'ldirardi: holat "online" da qotib qolar,
        # kuzatuv esa kadrsiz ishlayverardi va hech kim buni sezmasdi.
        # Kutilmagan xato ham oddiy uzilish kabi — qayta ulanish bilan.
        attempt = 0
        try:
            while self._running:
                try:
                    attempt = self._cycle(attempt)
                except Exception as exc:
                    log.exception("[%s] kamera oqimida kutilmagan xato", self._role)
                    self._health.last_error = "Kamera oqimida xato: {}".format(str(exc)[:120])
                    if attempt == 0:
                        # Faqat birinchi marta — takroriy xato hodisa
                        # oqimini bir xil `camera_lost` bilan to'ldirmasin.
                        self._set_state(CameraState.FAILED)
                    self._safe_close()
                    if not self._sleep_backoff(attempt):
                        break
                    attempt += 1
        finally:
            self._safe_close()
            self._set_state(CameraState.CLOSED)
            log.info("[%s] kamera oqimi yopildi", self._role)

    def _cycle(self, attempt: int) -> int:
        """Bitta "ochish -> o'qish -> uzilish" aylanishi. Keyingi `attempt`."""
        self._set_state(CameraState.OPENING if attempt == 0 else CameraState.RECONNECTING)
        self._reconnect_requested = False

        if not self._source.open():
            self._health.last_error = self._source.last_error
            log.warning("[%s] %s", self._role, self._source.last_error)
            # Holat bu yerda O'ZGARTIRILMAYDI (RECONNECTING da qoladi):
            # supervisor har `failed` ni `camera_lost` HODISASIGA
            # aylantiradi va har urinishda holatni almashtirish uzoq
            # uzilishda bayonnomani bir xil hodisalar bilan to'ldirardi.
            if not self._sleep_backoff(attempt):
                return attempt
            self._health.reconnects += 1
            return attempt + 1

        # ONLINE - ochilishda EMAS, birinchi TIRIK kadrda (`_read_loop`):
        # qayta ulangan USB kamera "ochildi", lekin qora bufer berdi -
        # bu "kamera qayta ulandi" emas edi (`liveness.py`).
        reason = self._read_loop()

        self._safe_close()
        if not self._running:
            return 0
        self._health.reconnects += 1
        if reason == "dead":
            # Manba YOPILGANDAN keyin: keyingi ochilish usuli yoki qurilmani
            # qayta ishga tushirish (`WebcamSource.recover_dead_stream`).
            step = _recover(self._source)
            if step:
                log.warning("[%s] o'lik oqim - keyingi urinish: %s", self._role, step)
            # Kechikish O'SADI: har soniyada ochib-yopish qurilmani
            # tayyorlanishga qo'ymasdi.
            if not self._sleep_backoff(attempt):
                return attempt
            return attempt + 1
        # Sikl uzilish sababli tugadi — qayta ulanamiz. Uyg'onishdan
        # keyingi so'rovda kutilmaydi: qurilma allaqachon tayyor.
        if not self._reconnect_requested:
            self._sleep_backoff(0)
        return 0

    def _mark_lost(self) -> None:
        """
        FAILED - bitta uzilishga BIR MARTA (supervisor har `failed` ni
        `camera_lost` hodisasiga aylantiradi). O'lik oqim qayta ochilib
        yana o'lik bo'lsa, hodisa takrorlanmaydi; tirik kadr kelguncha
        uzilish davom etyapti.
        """
        if self._outage:
            return
        self._outage = True
        self._set_state(CameraState.FAILED)

    def _safe_close(self) -> None:
        try:
            self._source.close()
        except Exception:
            log.debug("[%s] kamerani yopishda xato", self._role, exc_info=True)

    # ------------------------------------------------------------------
    def _read_loop(self) -> str:
        """Kadrlar sikli. Qaytadi: nega tugadi ("dead" - o'lik oqim, "" - boshqa)."""
        empty_streak = 0
        last_preview = 0.0
        last_health = 0.0
        last_presence = time.monotonic()
        liveness = FrameLiveness() if liveness_applies(self._source) else None

        while self._running:
            if self._reconnect_requested:
                self._health.last_error = "Uyqudan keyin qayta ulanish"
                return ""
            started = time.monotonic()
            if started - last_presence >= _PRESENCE_CHECK_S:
                last_presence = started
                # `read()` ga tayanmaymiz: USB sug'urilganda DirectShow
                # kadr qaytaraverishi mumkin (`WebcamSource.is_present`).
                if self._source.is_present() is False:
                    self._health.last_error = _explain_lost(self._source)
                    log.warning("[%s] kamera tizimdan yo'qoldi (uzilgan): %s",
                                self._role, self._health.last_error)
                    self._mark_lost()
                    return ""
            frame = self._source.read()
            elapsed = time.monotonic() - started

            if frame is None:
                empty_streak += 1
                self._health.frames_dropped += 1
                if empty_streak >= _EMPTY_FRAMES_BEFORE_LOST:
                    self._health.last_error = _explain_lost(self._source)
                    log.warning("[%s] %s", self._role, self._health.last_error)
                    self._mark_lost()
                    return ""
                # Qisqa kutish: bo'sh siklda protsessorni yemaslik uchun.
                self.msleep(30)
                continue

            empty_streak = 0
            now = time.monotonic()
            if liveness is not None:
                state = liveness.observe(frame, elapsed, now)
                summary = liveness.report(now)
                if summary:
                    log.info("[%s] kamera oqimi: %s", self._role, summary)
                if state == "dead":
                    self._health.last_error = DEAD_STREAM_MESSAGE
                    log.warning("[%s] %s", self._role, DEAD_STREAM_MESSAGE)
                    self._mark_lost()
                    return "dead"
                if state != "live":
                    continue  # qora/qotgan bufer - kadr sifatida berilmaydi
            if self._health.state != CameraState.ONLINE:
                self._outage = False
                self._set_state(CameraState.ONLINE)
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
        schedule = _LOCAL_BACKOFF_S if self._source.info.source == "local" else _BACKOFF_S
        delay = schedule[min(attempt, len(schedule) - 1)]
        deadline = time.monotonic() + delay
        while self._running and time.monotonic() < deadline:
            if self._reconnect_requested:
                # Uyg'onish — kutishning ma'nosi qolmadi.
                break
            self.msleep(100)
        return self._running

    def _set_state(self, state: CameraState) -> None:
        if self._health.state == state:
            return
        self._health.state = state
        self.state_changed.emit(self._role, state.value)


def _recover(source) -> str:
    recover = getattr(source, "recover_dead_stream", None)
    if recover is None:
        return ""
    try:
        return recover() or ""
    except Exception:  # noqa: BLE001
        log.warning("Kamera tiklash qadamida xato", exc_info=True)
        return ""


def _explain_lost(source) -> str:
    """
    Kadr kelmay qo'ydi — operatorga tushunarli sabab.

    Lokal kamerada sabab aniqlanadi (maxfiylik / uzilgan / javob
    bermayapti, `diagnose.py`); vaqt chegarasi (`guard.py`) o'z matnini
    allaqachon yozgan bo'lsa, o'shanisi aniqroq va u ustun.
    """
    error = getattr(source, "last_error", "") or ""
    if "javob bermayapti" in error:
        return error
    inner = getattr(source, "inner", source)
    explain = getattr(inner, "explain_lost", None)
    if explain is not None:
        try:
            return explain()
        except Exception:
            log.debug("Uzilish sababi aniqlanmadi", exc_info=True)
    return "Kameradan kadr kelmayapti"


def _connect_power_resumed(slot) -> None:
    """
    Uyqudan uyg'onish signaliga ulanadi (`core/system_events.py`).

    Modul yoki signal bo'lmasa — jimgina o'tadi: qayta ulanish
    baribir bo'sh kadrlar orqali (sekinroq) ishlaydi.
    """
    try:
        from core.system_events import system_events

        system_events().power_resumed.connect(slot)
    except Exception:
        log.debug("power_resumed signaliga ulanib bo'lmadi", exc_info=True)


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


#: Ishlab turgan aniqlash thread'lari (`CameraManager.discover_async`).
_DISCOVERY_LIVE: set = set()


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

        # OTA-OBYEKTSIZ va modul registrida (`_DISCOVERY_LIVE`):
        # aniqlash kamerani OCHADI va band/nosoz qurilmada DirectShow
        # uni uzoq ushlab turishi mumkin. Menejer shu payt yo'q qilinsa,
        # ota-obyekt bilan birga ishlab turgan thread ham yo'q qilinib,
        # Qt butun dasturni qulatardi ("Destroyed while thread is still
        # running") — `camera_worker._LIVE` dagi bilan bir xil sabab.
        thread = _DiscoveryThread()
        thread.found.connect(self._on_discovered)
        thread.finished.connect(self._on_discovery_finished)
        thread.finished.connect(lambda: _DISCOVERY_LIVE.discard(thread))
        _DISCOVERY_LIVE.add(thread)
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
