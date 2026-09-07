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
"""

from __future__ import annotations

import logging
import random
import threading
import time

import requests
from django.conf import settings
from django.core.cache import cache
from requests.adapters import HTTPAdapter

from apps.common.circuit_breaker import CircuitBreaker, CircuitOpenError
from apps.common.exceptions import (
    CandidateNotEligible,
    ExternalPlatformError,
    ExternalPlatformUnavailable,
)
from apps.common.utils.crypto import opaque_key

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
    def lookup_candidate(self, pinfl: str, exam_key: str = "") -> dict:
        """
        JSHSHIR bo'yicha talabgorni tekshiradi.

        Javob endi JONLI holat olib keladi: platformaning sessiya tokeni,
        test statusi va kirish oynasi. Shuning uchun kesh QISQA
        (`BASE_CACHE_TTL`, standart 60s) — u faqat ikki marta bosish va
        qayta urinishlarni yutish uchun. Uzoq kesh eskirgan token yoki
        "allaqachon tugatilgan" statusni berib, talabgorni kirita olmay
        qo'yardi.

        Kesh kaliti — JSHSHIR'ning qaytarilmaydigan hosilasi, ochiq raqam
        emas: kesh kalitlari `SCAN` bilan ro'yxatlanadi.
        """
        if self.conf["MOCK"]:
            return self._mock_candidate(pinfl, exam_key)

        cache_key = f"ntest:cand:{opaque_key(pinfl)}:{exam_key}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        data = self._call_protected(
            "POST", "/api/v1/candidate/check", json={"pinfl": pinfl, "exam": exam_key}
        )
        normalized = self._normalize_candidate(data)

        # Faqat muvaffaqiyatli natijani keshlaymiz. "Topilmadi" ni keshlash
        # ro'yxatga endigina qo'shilgan talabgorni bloklab qo'yishi mumkin.
        if normalized.get("eligible"):
            cache.set(cache_key, normalized, self.conf["CACHE_TTL"])
        return normalized

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

    # ------------------------------------------------------------------
    #: Tashqi API maydon nomlari uchun muqobillar.
    #
    #: DIQQAT: bu xarita ntest hujjatiga qarab ANIQLANISHI kerak. Hozircha
    #: eng ehtimolli nomlar sinaladi — noto'g'ri nom jimgina bo'sh qiymat
    #: beradi, shuning uchun integratsiya paytida `lookup_candidate`
    #: javobini bir marta log'ga chiqarib tekshiring.
    _FIELD_ALIASES = {
        "session_token": ("session_token", "token", "access_token"),
        "status": ("status", "test_status", "exam_status"),
        "access_from": ("access_from", "start_time", "started_at", "begin_at"),
        "access_until": ("access_until", "end_time", "finished_at", "expire_at"),
        # Pasport/hujjat rasmi. Ba'zi o'rnatishlarda URL, ba'zilarida
        # bevosita base64 keladi — ikkalasi ham qo'llab-quvvatlanadi.
        "photo_base64": ("photo_base64", "photo", "image", "image_base64"),
    }

    @classmethod
    def _pick(cls, payload: dict, key: str):
        for alias in cls._FIELD_ALIASES[key]:
            value = payload.get(alias)
            if value not in (None, ""):
                return value
        return None

    def _normalize_candidate(self, raw: dict) -> dict:
        """
        Tashqi API sxemasini ichki shaklga keltiradi.

        Eng muhim maydon — `session_token`. Bu TASHQI platformaning o'z
        sessiya tokeni; WebView aynan shu bilan ochiladi. U bizning
        proktorlik tokenimiz bilan hech qanday aloqasi yo'q va ular
        bir-birini almashtira olmaydi.
        """
        payload = raw.get("data", raw) or {}
        return {
            "eligible": bool(payload.get("is_have_perm", payload.get("eligible", False))),
            "external_id": str(payload.get("id", "")),
            "last_name": payload.get("last_name", ""),
            "first_name": payload.get("first_name", ""),
            "middle_name": payload.get("middle_name", ""),
            "photo_url": payload.get("photo_url", ""),
            # Etalon rasm client'ga o'tadi (kirishdagi FaceID uni kameradagi
            # yuz bilan solishtiradi), shuning uchun `data:` prefiksi
            # olib tashlanadi — client toza base64 kutadi.
            "photo_base64": _strip_data_uri(self._pick(payload, "photo_base64") or ""),
            # --- Tashqi platformadagi sessiya ---
            "session_token": self._pick(payload, "session_token") or "",
            "status": self._pick(payload, "status") or "",
            "access_from": self._pick(payload, "access_from"),
            "access_until": self._pick(payload, "access_until"),
            "login_url": payload.get("login_url", ""),
        }

    @staticmethod
    def _mock_candidate(pinfl: str, exam_key: str) -> dict:
        """Dev/test rejimi — tashqi API'siz to'liq oqimni sinash uchun."""
        from datetime import timedelta

        from django.utils import timezone

        now = timezone.now()
        return {
            "eligible": True,
            "external_id": f"mock-{pinfl[-6:]}",
            "last_name": "Testov",
            "first_name": "Test",
            "middle_name": "Testovich",
            "photo_url": "",
            # Mock'da etalon rasm YO'Q — client bu holatda "enrollment"
            # rejimiga tushadi (solishtirmaydi, faqat yuzni qayd etadi).
            "photo_base64": "",
            "session_token": f"ntest-sess-{pinfl[-6:]}",
            "status": "not_started",
            "access_from": (now - timedelta(minutes=30)).isoformat(),
            "access_until": (now + timedelta(hours=3)).isoformat(),
            "login_url": "",
        }


def _strip_data_uri(value: str) -> str:
    """`data:image/jpeg;base64,XXXX` -> `XXXX`."""
    text = str(value or "")
    if text.startswith("data:") and "," in text:
        return text.split(",", 1)[1]
    return text


def get_client() -> ExamPlatformClient:
    return ExamPlatformClient()


def platform_health() -> dict:
    """Dashboard'da tashqi platforma holatini ko'rsatish uchun."""
    return _breaker().snapshot()
