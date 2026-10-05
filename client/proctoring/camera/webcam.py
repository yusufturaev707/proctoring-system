"""
Lokal veb-kamera (OpenCV + DirectShow).

Mavjud `services/camera_worker.py` da to'plangan ikkita amaliy
tajriba shu yerga ko'chirildi va ular tekshirilgan:

  * `CAP_DSHOW` Windows'da MSMF'dan ANCHA tez ochiladi (o'lchandi:
    0.8 s va 6.9 s). Imtihon oqimida bu farq sezilarli — operator
    har talabgor uchun kamerani qayta ochadi;
  * `release()` HAR QANDAY chiqish yo'lida chaqirilishi shart, aks
    holda Windows qurilmani band qoldiradi va keyingi ochish umuman
    ishlamaydi.
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Optional

import numpy as np

from proctoring.camera.base import CameraInfo, CameraSource

log = logging.getLogger(__name__)

#: Muvaffaqiyatsiz ochilishdan keyingi urinishda qurilmaga beriladigan
#: tayyorlanish vaqti (s) - `open` dagi izoh.
_SETTLE_AFTER_RETURN_S = 3.0

#: Ochilish usullari (`recover_dead_stream`).
_MODE_TEXT = {
    "dshow": "DirectShow, MJPG",
    "native": "DirectShow, drayver formati",
    "msmf": "Media Foundation",
}
#: Bitta qurilmani qayta ishga tushirish oralig'i (s) - jarayon bo'yicha.
_RESTART_COOLDOWN_S = 120.0
_LAST_RESTART: dict = {}


def instance_id_from_path(device_path: str) -> str:
    """
    DirectShow `DevicePath` -> PnP instansiya ID (`pnputil` uchun).

    `\\\\?\\usb#vid_046d&pid_0825&mi_00#6&1e2afdec&1&0000#{65e8...}\\global`
    -> `USB\\VID_046D&PID_0825&MI_00\\6&1E2AFDEC&1&0000`.
    """
    path = (device_path or "").strip()
    if path.startswith("\\\\?\\"):
        path = path[4:]
    parts = path.split("#")
    if len(parts) < 3 or not all(parts[:3]):
        return ""
    return "\\".join(parts[:3]).upper()


class WebcamSource(CameraSource):
    """USB yoki o'rnatilgan veb-kamera."""

    def __init__(
        self,
        index: int,
        *,
        role: str = "",
        width: int = 1280,
        height: int = 720,
        label: str = "",
        is_virtual: bool = False,
        device_path: str = "",
    ) -> None:
        super().__init__(
            CameraInfo(
                role=role,
                source="local",
                label=label or f"Veb-kamera #{index}",
                index=index,
                is_virtual=is_virtual,
                backend="dshow" if sys.platform == "win32" else "default",
            )
        )
        self._index = index
        #: DirectShow `DevicePath` — ochilmaganda sababni aniqlash uchun
        #: ("qurilma ro'yxatda bormi?", `diagnose.py`). Indeks
        #: qurilmalar qayta sanalganda siljiydi, yo'l esa yo'q.
        self._device_path = device_path or ""
        self._want_width = width
        self._want_height = height
        self._capture = None
        #: Oldingi ochilish muvaffaqiyatsiz - keyingisidan oldin kutiladi.
        self._settle_pending = False
        #: Ochilish usuli (`_MODE_TEXT`) va tiklash zinapoyasidagi qadam.
        self._mode = "dshow"
        self._recovery_step = 0

    # ------------------------------------------------------------------
    def open(self) -> bool:
        import cv2

        self.close()

        if self._current_index() is None:
            self._settle_pending = True
            return self._fail(self._explain(lost=False))
        if self._settle_pending:
            # Qurilma endigina QAYTDI (oldingi urinish ochilmagan edi).
            # Amalda: USB kamera Windows'ga qaytganidan ~2 s keyin
            # ochilganda DirectShow grafi qurildi, lekin kadr bermadi -
            # qora bufer (`liveness.py`). Kamera+mikrofon kompozit
            # qurilma to'liq tayyorlanishiga vaqt beriladi.
            self._settle_pending = False
            time.sleep(_SETTLE_AFTER_RETURN_S)

        mode = self._mode
        if sys.platform != "win32":
            backend = cv2.CAP_ANY
        elif mode == "msmf":
            backend = cv2.CAP_MSMF
        else:
            backend = cv2.CAP_DSHOW
        # MSMF o'z sanog'ida faqat FIZIK kameralarni ko'radi - u faqat
        # yagona fizik kamerada tanlanadi (`_msmf_safe`), ya'ni indeks 0.
        index = 0 if mode == "msmf" else self._index
        capture = None
        try:
            capture = cv2.VideoCapture(index, backend)
            opened = capture.isOpened()
        except Exception as exc:
            # `cv2.error` drayver xatosida chiqadi (masalan qurilma
            # ochilish paytida sug'urildi). Istisno chaqiruvchining
            # siklini (qayta ulanish) buzmasligi kerak — oddiy
            # "ochilmadi" bo'lib qaytadi.
            log.warning("Kamerani ochishda istisno (indeks %s): %s", self._index, exc)
            opened = False
        if not opened:
            if capture is not None:
                try:
                    capture.release()
                except Exception:
                    pass
            self._settle_pending = True
            return self._fail(self._explain(lost=False))

        if mode == "native":
            # Tiklash rejimi (`recover_dead_stream`): drayverga HECH NARSA
            # majburlanmaydi - o'zining standart formati va o'lchami.
            # Sekinroq (YUY2) bo'lishi mumkin, lekin tasvir bor.
            return self._finish_open(capture, mode)

        try:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._want_width)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._want_height)
        except Exception:
            log.debug("Rezolyutsiya so'rovi qabul qilinmadi (indeks %s)", self._index)
        if mode == "msmf":
            return self._finish_open(capture, mode)

        # MJPG SO'RALADI va u REZOLYUTSIYADAN KEYIN qo'yiladi.
        #
        # Sababi o'lchangan: DirectShow standart holatda siqilmagan
        # YUY2 formatini beradi va 1280x720 da bu USB kanaliga
        # sig'maydi — kamera 30 FPS e'lon qilib, amalda ~7 FPS
        # beradi. O'sha kameraning o'zi MJPG da 29 FPS ishlaydi
        # (bir xil mashinada: YUY2 7.5, MJPG 29.2).
        #
        # Bu server tomondagi "FPS past" xatosining eng ko'p
        # uchraydigan sababi edi va u ayblovni noto'g'ri joyga
        # yo'naltirardi: kamera ham, yorug'lik ham aybdor emas,
        # client noto'g'ri format so'ragan.
        #
        # TARTIB HAL QILUVCHI: FOURCC rezolyutsiyadan OLDIN
        # qo'yilsa, keyingi `CAP_PROP_FRAME_WIDTH` drayverni
        # standart formatga QAYTARADI va qiymat jimgina YUY2
        # bo'lib qoladi (o'lchandi: 7.1 FPS).
        #
        # Kamera MJPG ni qo'llab-quvvatlamasa `set()` shunchaki
        # ishlamaydi va eski format qoladi — bu xato emas, pastdagi
        # log o'sha holatni ko'rsatadi.
        try:
            capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        except Exception:
            log.debug("MJPG so'rovi qo'llab-quvvatlanmadi (indeks %s)", self._index)
        return self._finish_open(capture, mode)

    def _finish_open(self, capture, mode: str) -> bool:
        import cv2

        # Bufer 1 kadr: proktorlikda ESKI kadr yaroqsiz. Standart
        # buferda kadr bir necha yuz ms kechikadi va "hozir nima
        # bo'lyapti" degan savolga javob bermaydi.
        try:
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            # Ba'zi drayverlar bu xususiyatni qo'llab-quvvatlamaydi -
            # bu xato emas, faqat kechikish biroz kattaroq bo'ladi.
            log.debug("CAP_PROP_BUFFERSIZE qo'llab-quvvatlanmadi (indeks %s)", self._index)

        self._capture = capture
        # HAQIQIY qiymatlarni qurilmadan o'qiymiz: so'ralgan
        # rezolyutsiya berilmagan bo'lishi mumkin va tekshiruv
        # sahifasi so'ralganini emas, olinganini ko'rsatishi kerak.
        try:
            self.info.width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            self.info.height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            self.info.declared_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        except Exception:
            log.debug("Kamera xususiyatlari o'qilmadi (indeks %s)", self._index)

        # Format LOG'GA yoziladi: "FPS past" xatosini tekshirishda
        # birinchi savol aynan shu bo'ladi — kamera MJPG bermadimi?
        log.info(
            "Veb-kamera ochildi: indeks=%s %s @%.0f FPS, format=%s%s",
            self._index, self.info.resolution, self.info.declared_fps,
            self._fourcc(capture) or "?",
            "" if mode == "dshow" else ", rejim=" + _MODE_TEXT[mode],
        )
        return True

    # ------------------------------------------------------------------
    def recover_dead_stream(self) -> str:
        """
        O'lik oqimdan (`liveness.py`) keyin KEYINGI ochilish usuli.

        Chaqiruvchi (`CameraStream`/`CameraWorker`) manbani YOPGANDAN
        keyin, qayta ochishdan oldin chaqiradi. Qaytadi: log uchun tavsif.

        NIMA UCHUN ZINAPOYA (amalda topilgan): noutbukda USB kamera
        qayta ulangach DirectShow grafi qurildi, lekin kadr bermadi -
        har `read()` ~1 s kutib qora bufer. Holat jarayon qayta
        ishga tushganda ham saqlandi, ya'ni oddiy qayta ochish yordam
        bermaydi. Navbat bilan:

          1. `native`  - DirectShow, MJPG/o'lcham MAJBURLANMAYDI (formatni
                         drayver tanlaydi - kelishmovchilik sababi bo'lsa);
          2. `msmf`    - Media Foundation (boshqa stek; faqat yagona fizik
                         kamerada - `_msmf_safe`);
          3. `restart` - qurilmani qayta ishga tushirish (`pnputil`) -
                         kabelni sug'urib-ulashning dasturiy o'rni.

        Ishlagan rejim SAQLANADI (keyingi ochilishlar ham shu bilan).
        """
        ladder = ["native"]
        if self._msmf_safe():
            ladder.append("msmf")
        ladder.append("restart")
        step = ladder[self._recovery_step % len(ladder)]
        self._recovery_step += 1
        if step != "restart":
            self._mode = step
            return _MODE_TEXT[step]
        self._mode = "dshow"
        return self._restart_device()

    def _msmf_safe(self) -> bool:
        """MSMF indeksi 0 aynan shu kamerami: ro'yxatda YAGONA fizik kamera."""
        from proctoring.camera.discovery import looks_virtual
        from proctoring.camera.dshow import enumerate_devices

        physical = [
            item for item in enumerate_devices()
            if item.device_path and not looks_virtual(item.name)
        ]
        return len(physical) == 1 and (
            not self._device_path or physical[0].device_path == self._device_path
        )

    def _restart_device(self) -> str:
        instance = instance_id_from_path(self._device_path)
        if not instance:
            return "qurilmani qayta ishga tushirib bo'lmaydi (yo'l noma'lum)"
        now = time.monotonic()
        last = _LAST_RESTART.get(instance)
        if last is not None and now - last < _RESTART_COOLDOWN_S:
            return "qurilma yaqinda qayta ishga tushirilgan - oddiy rejimda qayta ochiladi"
        _LAST_RESTART[instance] = now
        import subprocess

        try:
            result = subprocess.run(
                ["pnputil", "/restart-device", instance],
                capture_output=True, timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            code = result.returncode
        except Exception as exc:  # noqa: BLE001 - tiklash urinishi, xato emas
            return "qurilmani qayta ishga tushirib bo'lmadi: {}".format(str(exc)[:120])
        # Qurilma qayta sanaladi - ochishdan oldin tayyorlanish vaqti.
        self._settle_pending = True
        return "qurilma qayta ishga tushirildi (pnputil {}, kod {})".format(instance, code)

    def _current_index(self) -> Optional[int]:
        """
        Qaysi indeks ochiladi — HAR OCHILISHDA qurilma yo'li bo'yicha.

        Indeks DirectShow sanog'idagi O'RIN: kamera uzilsa qolganlari
        siljiydi. `factory._resolve_index` uni faqat manba YARATILGANDA
        to'g'rilaydi, qayta ulanish esa shu obyektning `open()` ini
        chaqiradi. Eski indeks bilan noutbukda (ichki + USB kamera,
        USB #0) USB uzilganda ichki kamera #0 ga surilib OCHILARDI va
        "Kamera qayta ulandi" bo'lib, kuzatuv boshqa kamera bilan davom
        etardi.

        `None` — qurilma ro'yxatda yo'q, boshqalari bor: OCHILMAYDI
        (qayta ulanish sikli o'zini kutadi). Ro'yxat bo'sh bo'lsa eski
        indeks qoladi: bo'sh ro'yxat COM xatosi ham bo'lishi mumkin
        (`dshow.enumerate_devices`), kamera umuman yo'q bo'lsa esa
        `VideoCapture` baribir ochilmaydi.
        """
        if not self._device_path:
            return self._index
        from proctoring.camera.dshow import enumerate_devices

        devices = enumerate_devices()
        if not devices:
            return self._index
        found = next(
            (item for item in devices if getattr(item, "device_path", "") == self._device_path),
            None,
        )
        if found is None:
            # YO'L PORTGA BOG'LIQ: seriya raqamsiz kamerada (Logi C270)
            # yo'lda USB port izi bor (`...#6&1e2afdec&1&...`) - boshqa
            # portga qayta ulansa yo'l o'zgaradi. Shunda NOM bo'yicha,
            # faqat YAGONA moslik bo'lsa: ikkita bir xil kamerada
            # taxmin boshqasini ochishi mumkin.
            same_name = [
                item for item in devices
                if self.info.label and getattr(item, "name", "") == self.info.label
            ]
            if len(same_name) != 1:
                return None
            found = same_name[0]
            log.warning(
                "[%s] kamera boshqa USB portga ulangan - nom bo'yicha topildi: %s",
                self.info.role, self.info.label,
            )
            self._device_path = found.device_path
        if found.index != self._index:
            log.warning(
                "[%s] kamera indeksi siljigan (%s -> %s), qurilma yo'li bo'yicha "
                "tuzatildi: %s",
                self.info.role, self._index, found.index, self.info.label,
            )
            self._index = found.index
            self.info.index = found.index
        return self._index

    def is_present(self) -> Optional[bool]:
        """
        Ochilgan qurilma hali Windows ro'yxatidami.

        NIMA UCHUN KERAK (amalda topilgan): noutbukda USB kamera
        sug'urilgandan keyin DirectShow `read()` XATO BERMADI va kadr
        qaytaraverdi (log'da 3 daqiqa bitta ham ogohlantirish yo'q) -
        ya'ni "ketma-ket bo'sh kadr" qoidasi uzilishni hech qachon
        ko'rmadi va kabel qayta ulanganda ham qayta ochilmadi.

        Faqat ANIQ yo'l (`_current_index` dagi nom zaxirasisiz): kamera
        uzilib boshqa portga tez ulansa ham eski ulanish o'lik.
        `None` - bilib bo'lmadi (yo'l yo'q yoki ro'yxat o'qilmadi).
        """
        if not self._device_path:
            return None
        from proctoring.camera.dshow import enumerate_devices_strict

        devices = enumerate_devices_strict()
        if devices is None:
            return None
        return any(getattr(item, "device_path", "") == self._device_path for item in devices)

    def fresh_copy(self) -> "WebcamSource":
        """
        Shu qurilma uchun YANGI manba (ochilmagan).

        `guard.GuardedSource` osilgan `read()` ni tashlab ketganda
        ishlatadi: eski `VideoCapture` osilgan thread'da qoladi, yangisi
        alohida ochiladi (`guard._replace_stuck_io`).
        """
        copy = WebcamSource(
            self._index,
            role=self.info.role,
            width=self._want_width,
            height=self._want_height,
            label=self.info.label,
            is_virtual=self.info.is_virtual,
            device_path=self._device_path,
        )
        # Osilish odatda qurilma uzilganda - qaytgach tayyorlanish vaqti.
        copy._settle_pending = True
        copy._mode = self._mode
        copy._recovery_step = self._recovery_step
        return copy

    @staticmethod
    def _fourcc(capture) -> str:
        """Qurilma HAQIQATDA bergan piksel formati (`MJPG`, `YUY2`...)."""
        import cv2

        try:
            raw = int(capture.get(cv2.CAP_PROP_FOURCC))
        except Exception:
            return ""
        if raw <= 0:
            return ""
        return "".join(chr((raw >> (8 * shift)) & 0xFF) for shift in range(4)).strip()

    def _explain(self, *, lost: bool) -> str:
        """Operatorga tushunarli sabab (`diagnose.py`). Xato — umumiy matn."""
        try:
            from proctoring.camera.diagnose import explain_local_failure

            return explain_local_failure(self._index, self._device_path, lost=lost)
        except Exception:
            log.debug("Kamera nosozligi sababi aniqlanmadi", exc_info=True)
            return "Kamera ochilmadi (indeks {}).".format(self._index)

    def explain_lost(self) -> str:
        """Kadr kelmay qo'ydi — sababi (chaqiruvchi sikldan so'raydi)."""
        return self._explain(lost=True)

    def read(self) -> Optional[np.ndarray]:
        if self._capture is None:
            return None
        try:
            ok, frame = self._capture.read()
        except Exception as exc:
            # USB sug'urilganda ba'zi drayverlar `cv2.error` beradi.
            # Bu "kadr yo'q" — uzilishni ketma-ket bo'sh kadrlar
            # bo'yicha chaqiruvchi aniqlaydi.
            self._last_error = "Kadr o'qishda xato: {}".format(str(exc)[:120])
            return None
        return frame if ok else None

    def close(self) -> None:
        capture, self._capture = self._capture, None
        if capture is None:
            return
        try:
            capture.release()
        except Exception:
            log.debug("Kamerani yopishda xato (indeks %s)", self._index, exc_info=True)
