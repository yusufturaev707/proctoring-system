"""
Kadr manbaini VAQT CHEGARASI bilan o'rash.

MUAMMO. `cv2.VideoCapture` ning `open`/`read`/`grab` chaqiruvlari
NATIV kodda bloklanadi va ularni Python'dan to'xtatib bo'lmaydi:
USB kabel sug'urilganda ba'zi drayverlar `read()` dan umuman
qaytmaydi, o'chirilgan IP kamera esa FFmpeg'ni o'nlab soniya ushlab
turadi. Chaqiruvchi thread (FaceID ishchisi yoki kuzatuv oqimi) shu
payt `stop()` bayrog'ini o'qiy olmaydi va:

  * UI "kamera yo'qoldi" degan xabarni hech qachon olmaydi — oxirgi
    kadr ekranda qotib turadi;
  * sahifa almashganda `retire_camera` UI thread'ida kutadi, ya'ni
    oyna qotadi;
  * qurilma "bitta ega" qoidasi bo'yicha keyingi egaga o'tmaydi.

YECHIM. Manbaning BARCHA chaqiruvlari bitta alohida I/O thread'ida
bajariladi, chaqiruvchi esa natijani CHEGARALANGAN vaqt kutadi.
Muddat o'tsa chaqiruvchi darhol "kadr yo'q" oladi va o'z siklini
(qayta ulanish, xabar, to'xtash) davom ettiradi. Osilgan chaqiruv
fon thread'ida qoladi — uni o'ldirishning xavfsiz yo'li yo'q.

NIMA UCHUN BITTA THREAD, HAR CHAQIRUVGA YANGI EMAS. Osilgan `read()`
davom etayotganda o'sha `VideoCapture` ga boshqa thread'dan
`release()` qilish nativ darajada qulashga olib kelishi mumkin
(bufer ikki joydan bo'shatiladi). Shuning uchun manbaga FAQAT bitta
thread tegadi va chaqiruvlar navbat bilan bajariladi: yopish so'rovi
osilgan o'qish TUGAGANDAN keyin bajariladi. DirectShow ham (COM)
qurilmani ochgan thread'ning o'zida ishlashni afzal ko'radi.

Osilgan chaqiruv davomida yangi `open()` RAD ETILADI (navbatga
qo'yilmaydi): u baribir o'sha qurilmani ochishga urinardi va
osilgan chaqiruv qaytgach hech kim kutmayotgan kamerani ochib,
qurilmani band qilib qo'yardi.

OSILISH ABADIY BO'LSA (`_REPLACE_AFTER_S`). DirectShow'da USB kabel
sug'urilganda `read()` UMUMAN qaytmasligi mumkin - o'shanda yuqoridagi
qoida kamerani imtihon oxirigacha o'chiq qoldirardi: kabel qayta
ulangan, lekin har `open()` "javob bermayapti" bilan rad. Shuning uchun
shuncha vaqtdan keyin osilgan I/O thread TASHLAB KETILADI (o'z navbati
va eski manba bilan; qaytsa, eski manbani O'ZI yopadi) va qurilma YANGI
manba nusxasi (`fresh_copy`) bilan, yangi thread'da ochiladi. Ikki
thread bitta `VideoCapture` ga tegmaydi - har biri o'zinikiga.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Callable, Optional

import numpy as np

from proctoring.camera.base import CameraSource

log = logging.getLogger(__name__)

#: Kutish bo'laklari (s). To'xtatish so'rovi (`abort`) shuncha
#: kechikish bilan seziladi.
_WAIT_SLICE_S = 0.1

#: Manba yopiq va navbat bo'sh bo'lsa I/O thread shuncha kutib chiqadi.
_IDLE_EXIT_S = 30.0

#: Chaqiruv shuncha vaqt qaytmasa osilgan I/O tashlab ketiladi va manba
#: yangi nusxa bilan ochiladi (modul docstring'i). O'qish chegarasidan
#: (5 s) ancha katta: sekin, lekin tirik qurilma almashtirilmasin.
_REPLACE_AFTER_S = 10.0


def normalize_frame(frame) -> Optional[np.ndarray]:
    """
    Kadrni 3 kanalli, `uint8`, uzluksiz BGR massivga keltiradi.

    Butun dastur (oldindan ko'rish, InsightFace, JPEG) aynan shu
    shaklni kutadi. Ba'zi qurilmalar (IR kamera, virtual kamera,
    `CONVERT_RGB` ni e'tiborsiz qoldiradigan drayver) kulrang yoki
    4 kanalli kadr beradi: `frame[:, :, ::-1]` kulrangda `IndexError`
    beradi, 4 kanallida esa `QImage` qatorni noto'g'ri o'qiydi.
    Tuzatib bo'lmaydigan kadr — `None` ("kadr yo'q"), istisno emas.
    """
    if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
        return None
    try:
        import cv2

        if frame.dtype != np.uint8:
            # 16 bitli (chuqurlik) kadr — bizga yaroqsiz.
            return None
        if frame.ndim == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        elif frame.ndim == 3 and frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        elif frame.ndim == 3 and frame.shape[2] == 1:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        elif not (frame.ndim == 3 and frame.shape[2] == 3):
            return None
        if frame.shape[0] < 2 or frame.shape[1] < 2:
            return None
        return np.ascontiguousarray(frame)
    except Exception:
        log.debug("Kadrni normallashtirib bo'lmadi", exc_info=True)
        return None


class _Job:
    __slots__ = ("name", "fn", "inner", "done", "result", "error", "abandoned", "started_at")

    def __init__(self, name: str, fn: Callable, inner: Optional[CameraSource] = None) -> None:
        self.name = name
        self.fn = fn
        #: Chaqiruv QAYSI manbaga tegishli - osilgan I/O almashtirilgach
        #: kechikkan ochilish yangisini emas, o'zinikini yopsin.
        self.inner = inner
        self.done = threading.Event()
        self.result = None
        self.error: Optional[BaseException] = None
        #: Chaqiruvchi natijani kutmay ketdi (muddat o'tdi).
        self.abandoned = False
        self.started_at = 0.0


class GuardedSource(CameraSource):
    """
    Istalgan `CameraSource` ni vaqt chegarasi bilan o'raydi.

    Tashqi shartnoma o'zgarmaydi (`open`/`read`/`close`,
    `last_error`, `info`) — `CameraStream` va `CameraWorker` farqni
    sezmaydi. Qo'shimchasi: `abort()` (kutishni darhol to'xtatadi) va
    `hung` (manba hozir javob bermayapti).
    """

    def __init__(
        self,
        inner: CameraSource,
        *,
        open_timeout: float = 20.0,
        read_timeout: float = 5.0,
        close_timeout: float = 2.0,
    ) -> None:
        # `info` UMUMIY obyekt: ichki manba ochilganda yozgan
        # rezolyutsiya/FPS tashqarida ham darhol ko'rinadi.
        super().__init__(inner.info)
        self._inner = inner
        self._open_timeout = float(open_timeout)
        self._read_timeout = float(read_timeout)
        self._close_timeout = float(close_timeout)
        self._jobs: "queue.Queue[_Job]" = queue.Queue()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        #: Hozir bajarilayotgan chaqiruv (`None` — I/O thread bo'sh).
        self._current: Optional[_Job] = None
        #: Ichki manba ochiq (thread uni tashlab ketmasligi kerak).
        self._opened = False
        self._abort = threading.Event()

    # ------------------------------------------------------------------
    @property
    def inner(self) -> CameraSource:
        return self._inner

    @property
    def hung(self) -> bool:
        """Oldingi chaqiruv muddatidan oshib, hali ham qaytmagan."""
        job = self._current
        return job is not None and job.abandoned

    def is_present(self) -> Optional[bool]:
        """
        Ichki manbaga O'TADI, I/O thread'ga emas: bu qurilmalar ro'yxati
        (`VideoCapture` ga tegmaydi) va osilgan `read()` paytida aynan
        shu savolga javob kerak.
        """
        try:
            return self._inner.is_present()
        except Exception:  # noqa: BLE001
            log.debug("Kamera borligini tekshirib bo'lmadi", exc_info=True)
            return None

    def recover_dead_stream(self) -> str:
        """Ichki manbaga o'tadi (`WebcamSource.recover_dead_stream`); yo'q bo'lsa ""."""
        recover = getattr(self._inner, "recover_dead_stream", None)
        if recover is None:
            return ""
        try:
            return recover() or ""
        except Exception:  # noqa: BLE001 - tiklash urinishi kuzatuvni to'xtatmaydi
            log.warning("[%s] kamera tiklash qadamida xato", self.info.role or "-", exc_info=True)
            return ""

    def abort(self) -> None:
        """
        Kutayotgan `open`/`read` darhol qaytadi (egasi to'xtayapti).

        Keyingi `open()` bayroqni tozalaydi. `close()` bunga
        bog'liq emas: qurilmani keyingi egaga bo'shatib berish
        uchun u baribir qisqa muddat kutadi.
        """
        self._abort.set()

    # ------------------------------------------------------------------
    def open(self) -> bool:
        self._abort.clear()
        job = self._current
        if job is not None and job.abandoned:
            # Oldingi chaqiruv to'xtatish (`abort`) tufayli tashlab
            # ketilgan bo'lishi mumkin — u odatda millisekundlarda
            # qaytadi. Qisqa kutamiz; haqiqatan osilgan bo'lsa rad.
            job.done.wait(1.0)
        if self.hung and self._stalled_seconds() >= _REPLACE_AFTER_S:
            self._replace_stuck_io()
        if self.hung:
            return self._fail(
                "Kamera javob bermayapti (oldingi chaqiruv {} s dan beri "
                "qaytmadi). Qayta urinish davom etadi.".format(self._stalled_for())
            )
        done, result = self._call("open", self._inner.open, self._open_timeout)
        if not done:
            return self._fail(
                "Kamera {} s ichida ochilmadi — qurilma javob bermayapti. "
                "Qayta urinish davom etadi.".format(int(self._open_timeout))
            )
        if result:
            self._opened = True
            self._last_error = ""
            return True
        return self._fail(self._inner.last_error or "Kamera ochilmadi.")

    def read(self) -> Optional[np.ndarray]:
        if self._abort.is_set():
            return None
        if self.hung:
            # Navbatga qo'yilmaydi: osilgan o'qish ustiga yangisini
            # yig'ish faqat navbatni cheksiz o'stirardi.
            self._last_error = (
                "Kameradan {} s davomida kadr kelmadi — qurilma javob "
                "bermayapti.".format(self._stalled_for())
            )
            return None
        done, frame = self._call("read", self._inner.read, self._read_timeout)
        if not done:
            self._last_error = (
                "Kameradan {} s davomida kadr kelmadi — qurilma javob "
                "bermayapti.".format(int(self._read_timeout))
            )
            log.warning("[%s] %s", self.info.role or "-", self._last_error)
            return None
        return normalize_frame(frame)

    def close(self) -> None:
        if not self._opened and self._current is None and self._jobs.empty():
            return
        self._opened = False
        # Yopish NAVBATGA qo'yiladi va qisqa kutiladi: odatda oldingi
        # chaqiruv millisekundlarda tugaydi va qurilma keyingi egaga
        # (kuzatuv oqimi) shu yerda bo'shaydi. Oldingi chaqiruv
        # osilgan bo'lsa, yopish u QAYTGANDAN keyin bajariladi —
        # `release()` ni boshqa thread'dan chaqirish xavfli.
        done, _ = self._call("close", self._inner.close, self._close_timeout, abortable=False)
        if not done:
            log.warning(
                "[%s] kamera osilgan holatda yopildi — qurilma chaqiruv "
                "qaytgach bo'shatiladi", self.info.role or "-",
            )

    # ------------------------------------------------------------------
    def _replace_stuck_io(self) -> bool:
        """
        Abadiy osilgan I/O ni tashlab, manbani yangi nusxa bilan almashtiradi.

        `fresh_copy` yo'q manba (masalan RTSP - FFmpeg o'z timeout'i bilan
        qaytadi) almashtirilmaydi - eski qoida qoladi.
        """
        fresh = getattr(self._inner, "fresh_copy", None)
        if fresh is None:
            return False
        try:
            replacement = fresh()
        except Exception:  # noqa: BLE001
            log.warning("[%s] kamera manbasini yangilab bo'lmadi", self.info.role or "-", exc_info=True)
            return False
        # Ma'lumot obyekti UMUMIY qoladi (rezolyutsiya, nom - tashqarida ko'rinadi).
        replacement.info = self.info
        with self._lock:
            old_inner, old_jobs = self._inner, self._jobs
            stalled = self._stalled_seconds()
            self._inner = replacement
            self._jobs = queue.Queue()
            self._thread = None
            self._current = None
            self._opened = False
        # Eski manba O'Z thread'ida yopiladi - osilgan chaqiruv qaytsa.
        old_jobs.put(_Job("close", old_inner.close, old_inner))
        log.warning(
            "[%s] kamera chaqiruvi %d s dan beri qaytmayapti - u tashlab ketildi, "
            "qurilma yangi ulanish bilan ochiladi", self.info.role or "-", stalled,
        )
        return True

    def _stalled_seconds(self) -> float:
        job = self._current
        if job is None or not job.started_at:
            return 0.0
        return time.monotonic() - job.started_at

    def _stalled_for(self) -> int:
        job = self._current
        if job is None or not job.started_at:
            return int(self._read_timeout)
        # Kamida o'qish chegarasi: "0 s dan beri" degan xabar
        # operatorni chalg'itardi (osilish chegara o'tgach aniqlanadi).
        return max(int(self._read_timeout), int(time.monotonic() - job.started_at))

    def _call(self, name: str, fn: Callable, timeout: float, *, abortable: bool = True):
        """`(bajarildimi, natija)`. Istisno natija `None`/`False` bo'ladi."""
        job = _Job(name, fn, self._inner)
        self._submit(job)
        deadline = time.monotonic() + max(0.05, timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if job.done.wait(min(_WAIT_SLICE_S, remaining)):
                break
            if abortable and self._abort.is_set():
                break
        if not job.done.is_set():
            job.abandoned = True
            # Poyga: aynan shu lahzada tugagan bo'lishi mumkin.
            if not job.done.is_set():
                return False, None
        if job.error is not None:
            log.warning(
                "[%s] kamera chaqiruvida xato (%s): %s",
                self.info.role or "-", name, str(job.error)[:200],
            )
            return True, (False if name == "open" else None)
        return True, job.result

    def _submit(self, job: _Job) -> None:
        with self._lock:
            self._jobs.put(job)
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._loop,
                    # Navbat ARGUMENT: almashtirilgan (`_replace_stuck_io`)
                    # eski thread yangi navbatdan ish olmasligi kerak.
                    args=(self._jobs,),
                    name="camera-io-{}".format(self.info.role or "src"),
                    # DAEMON: osilgan nativ chaqiruv dastur yopilishini
                    # to'smasligi kerak.
                    daemon=True,
                )
                self._thread.start()

    def _loop(self, jobs: "queue.Queue[_Job]") -> None:
        while True:
            try:
                job = jobs.get(timeout=_IDLE_EXIT_S)
            except queue.Empty:
                with self._lock:
                    if jobs is not self._jobs:
                        return  # tashlab ketilgan I/O - ishi tugadi
                    # Ochiq manba thread'siz qolmaydi: DirectShow
                    # qurilmasi ochilgan thread'da ishlashi kerak.
                    if jobs.empty() and not self._opened:
                        self._thread = None
                        return
                continue

            current = jobs is self._jobs
            if current:
                self._current = job
            job.started_at = time.monotonic()
            try:
                job.result = job.fn()
            except BaseException as exc:  # noqa: BLE001 — thread yiqilmasin
                job.error = exc
            finally:
                if self._current is job:
                    self._current = None
                job.done.set()

            if job.abandoned:
                log.info(
                    "[%s] kechikkan kamera chaqiruvi qaytdi (%s, %.1f s)",
                    self.info.role or "-", job.name,
                    time.monotonic() - job.started_at,
                )
                if job.name == "open" and job.result:
                    # Hech kim kutmayotgan ochilish — qurilma band
                    # qolmasligi uchun darhol yopiladi (O'Z manbasi).
                    try:
                        (job.inner or self._inner).close()
                    except Exception:
                        log.debug("Kechikkan ochilishni yopishda xato", exc_info=True)
