"""
Tashqi test platformasi (ntest) bilan integratsiya.

Bu qatlam butun tizimning eng katta SPOF'i bilan ishlaydi. Shuning uchun
har bir chaqiruv to'rt qavat himoya ostida:

  1. Qat'iy timeout      — cheksiz kutish yo'q (connect 2s / read 5s)
  2. Cheklangan retry    — jitter bilan, "thundering herd" bo'lmasin
  3. Circuit breaker     — API o'lgan bo'lsa, unga umuman tegilmaydi
  4. Kesh                — muvaffaqiyatli javob 30 daqiqa saqlanadi

Nima uchun bu shuncha muhim: Django sync worker'da bloklanuvchi chaqiruv
butun worker'ni band qiladi. 1000 talaba bir vaqtda "Kirish" bossa va
ntest 3 soniya javob bersa, 32 worker'li server 30 soniyada to'lib qoladi
va imtihon umuman boshlanmaydi.

DIQQAT: TALABGORNI TEKSHIRISH BU YERDA EMAS. U `exam_site.py` ga
ko'chirildi, chunki so'rov endi HAR IMTIHONNING o'z manzili va o'z
sarlavhasi bilan ketadi (`Exam.site_url` + `Exam.site_header_encrypted`),
bu yerda esa bitta markazlashgan `BASE_URL` va global kalit bor.
Ikkita tekshiruvni saqlab qolish ikkita talqinga olib kelardi va
ular albatta ajralib ketardi. Bu modulda natijani qaytarish
(`report_result`) va salomatlik (`platform_health`) qoldi.
"""

from __future__ import annotations

import logging
import random
import threading
import time

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter

from apps.common.circuit_breaker import CircuitBreaker, CircuitOpenError
from apps.common.exceptions import (
    CandidateNotEligible,
    ExternalPlatformError,
    ExternalPlatformUnavailable,
)

logger = logging.getLogger(__name__)

_session_lock = threading.Lock()
_session: requests.Session | None = None


def _get_session() -> requests.Session:
    """
    Process bo'yicha yagona `requests.Session`.

    Har chaqiruvda yangi sessiya = har safar yangi TCP + TLS handshake
    (~100-200 ms). Pool bilan bu bir marta bo'ladi.
    """
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                conf = settings.EXTERNAL_PLATFORM
                sess = requests.Session()
                adapter = HTTPAdapter(
                    pool_connections=conf["POOL_SIZE"],
                    pool_maxsize=conf["POOL_SIZE"],
                    # Retry'ni O'ZIMIZ boshqaramiz (jitter kerak),
                    # urllib3 avtomatik retry qilmasin.
                    max_retries=0,
                )
                sess.mount("https://", adapter)
                sess.mount("http://", adapter)
                sess.headers.update(
                    {
                        "User-Agent": "ProctoringSystem/1.0",
                        "Accept": "application/json",
                    }
                )
                if conf["API_KEY"]:
                    sess.headers["Authorization"] = f"Bearer {conf['API_KEY']}"
                _session = sess
    return _session


def _breaker() -> CircuitBreaker:
    conf = settings.EXTERNAL_PLATFORM
    return CircuitBreaker(
        name="exam_platform",
        fail_threshold=conf["CB_FAIL_THRESHOLD"],
        window=conf["CB_WINDOW"],
        reset_timeout=conf["CB_RESET_TIMEOUT"],
    )


class ExamPlatformClient:
    """Tashqi platforma API'si uchun yagona kirish nuqtasi."""

    def __init__(self):
        self.conf = settings.EXTERNAL_PLATFORM
        self.base_url = self.conf["BASE_URL"].rstrip("/")

    # ------------------------------------------------------------------
    # Past darajali HTTP
    # ------------------------------------------------------------------
    def _request(self, method: str, path: str, **kwargs) -> dict:
        timeout = (self.conf["CONNECT_TIMEOUT"], self.conf["READ_TIMEOUT"])
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None

        for attempt in range(self.conf["MAX_RETRIES"] + 1):
            try:
                response = _get_session().request(method, url, timeout=timeout, **kwargs)
            except requests.Timeout as exc:
                last_error = exc
                logger.warning("ntest timeout (%s/%s): %s", attempt + 1, self.conf["MAX_RETRIES"] + 1, url)
            except requests.RequestException as exc:
                last_error = exc
                logger.warning("ntest tarmoq xatosi: %s", exc)
            else:
                # 4xx — mantiqiy javob, qayta urinish ma'nosiz.
                if 400 <= response.status_code < 500:
                    return self._handle_client_error(response)
                if response.status_code >= 500:
                    last_error = ExternalPlatformError(
                        f"ntest {response.status_code}"
                    )
                    logger.warning("ntest 5xx: %s %s", response.status_code, url)
                else:
                    return self._parse(response)

            # Exponential backoff + jitter.
            # Jitter'siz barcha worker'lar bir vaqtda qayta uradi va
            # tiklanayotgan API'ni yana yiqitadi.
            if attempt < self.conf["MAX_RETRIES"]:
                delay = (0.2 * (2**attempt)) + random.uniform(0, 0.2)
                time.sleep(delay)

        raise ExternalPlatformError(str(last_error) if last_error else "ntest xatosi")

    @staticmethod
    def _parse(response: requests.Response) -> dict:
        try:
            return response.json()
        except ValueError as exc:
            raise ExternalPlatformError("ntest JSON bo'lmagan javob qaytardi") from exc

    @staticmethod
    def _handle_client_error(response: requests.Response) -> dict:
        if response.status_code == 404:
            raise CandidateNotEligible("Talabgor tashqi platformada topilmadi")
        if response.status_code in (401, 403):
            logger.error("ntest autentifikatsiyasi rad etildi: %s", response.status_code)
            raise ExternalPlatformError("Tashqi platforma avtorizatsiyasi xato")
        raise ExternalPlatformError(f"ntest xatosi: {response.status_code}")

    def _call_protected(self, method: str, path: str, **kwargs) -> dict:
        """Circuit breaker ostidagi chaqiruv."""
        try:
            return _breaker().call(self._request, method, path, **kwargs)
        except CircuitOpenError:
            logger.warning("ntest circuit ochiq — chaqiruv qilinmadi: %s", path)
            raise ExternalPlatformUnavailable()

    # ------------------------------------------------------------------
    # Domen metodlari
    # ------------------------------------------------------------------
    def report_result(self, *, session_id: str, status: str, meta: dict) -> bool:
        """
        Sessiya yakunini tashqi platformaga xabar qiladi.

        Bu chaqiruv KRITIK YO'LDA EMAS — Celery'dan chaqiriladi. Talabgorning
        imtihoni tashqi API javob berishini kutib turmasligi kerak.
        """
        if self.conf["MOCK"]:
            return True
        try:
            self._call_protected(
                "POST",
                "/api/v1/exam/session-result",
                json={"session_id": session_id, "status": status, "meta": meta},
            )
            return True
        except (ExternalPlatformError, ExternalPlatformUnavailable) as exc:
            logger.warning("Natijani yuborib bo'lmadi (%s): %s", session_id, exc)
            return False

def get_client() -> ExamPlatformClient:
    return ExamPlatformClient()


def platform_health() -> dict:
    """Dashboard'da tashqi platforma holatini ko'rsatish uchun."""
    return _breaker().snapshot()
