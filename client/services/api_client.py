"""
HTTP transport qatlami — bitta joyda.

Bu modul HECH QANDAY biznes-mantiq bilmaydi: u faqat so'rov yuboradi,
`{success, data, error}` konvertini ochadi, tokenlarni qo'yadi va 401 da
bir marta refresh qiladi. Endpoint nomlari va oqim mantig'i
`repositories.py` da.

Ajratishning sababi: backend konverti yoki auth sxemasi o'zgarsa —
o'zgarish shu faylda qoladi; yangi endpoint qo'shilsa — repository'da.

QAYTA URINISH QOIDASI (`services/net_policy.py`):

  * So'rov serverga YETMAGAN bo'lsa (DNS, ulanish rad etildi, ulanish
    timeout'i) — istalgan metod takrorlanadi: server uni ko'rmagan.
  * So'rov YETGAN bo'lishi mumkin bo'lsa (javob timeout'i, uzilgan
    javob, 502/503/504, 408/429) — faqat IDEMPOTENT so'rov (GET yoki
    chaqiruvchi `idempotent=True` degan POST). `face/verify/`
    challenge'ni sarflaydi, `session/finish/` tokenni bekor qiladi —
    ularni ko'r-ko'rona takrorlash ikkinchi urinishni "sessiya
    topilmadi" bilan yiqitardi.
  * 4xx (408/429 dan tashqari) HECH QACHON takrorlanmaydi.
  * Chaqiruvchi o'z timeout'ini bergan bo'lsa (dasturdan chiqishdagi
    yakun) — takror YO'Q: u vaqt byudjetini o'zi hisoblagan.
  * `Retry-After` (429/503) — shu yo'lga o'sha muddatgacha so'rov
    umuman ketmaydi (`_gate`), davriy yuboruvchilar ham avtomatik
    bo'ysunadi.

Kechikishlar jitter bilan: server qayta ishga tushganda minglab client
bir lahzada urilmasligi kerak.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any, Callable, Optional

import httpx

from config import API_BASE_URL, API_CONNECT_TIMEOUT, API_SSL_VERIFY, API_TIMEOUT
from core.errors import AuthError, ClientError, DeviceNotRegistered, NetworkError, humanize
from core.singleton import SingletonMeta
from services import net_policy

log = logging.getLogger(__name__)

if API_SSL_VERIFY is False:
    log.warning("API_SSL_VERIFY=0 - MITM xavfi. Production'da HTTPS + CA majburiy.")

#: So'rov ichidagi takrorlar soni (birinchi urinishdan TASHQARI).
#
# Kichik va ataylab: bu faqat qisqa uzilishni (keep-alive ulanishi
# yopilgan, proksi bir lahza 502 bergan) yashiradi. Uzoq uzilishni
# davriy yuboruvchilar o'zi kutadi (`net_policy.Backoff`); bu yerda
# ko'p takrorlash esa operatorni "Yuklanmoqda..." oldida ushlab turardi.
_RETRIES_IDEMPOTENT = 2
_RETRIES_UNSAFE = 1

#: So'rov ichidagi kutish (soniya): 0.5 -> 1 -> 2 ..., chegara 4.
_INLINE_BASE_S = 0.5
_INLINE_CAP_S = 4.0

#: `Retry-After` shundan uzun bo'lsa so'rov ichida KUTILMAYDI — xato
#: darhol qaytadi (fon ishchisini daqiqalab band qilish o'rniga).
_INLINE_MAX_RETRY_AFTER_S = 10.0

#: Serverga yetmagan (qayta yuborish xavfsiz) transport xatolari.
_NOT_SENT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)

#: Konvertsiz 5xx (nginx HTML sahifasi) uchun operator tilidagi matn.
_STATUS_MESSAGES = {
    500: ("server_error",
          "Serverda ichki xato ({}). Qaytadan urinib ko'ring; takrorlansa "
          "administratorga murojaat qiling."),
    502: ("server_unavailable",
          "Server vaqtincha javob bermayapti ({}). Birozdan keyin qaytadan urinib ko'ring."),
    503: ("server_unavailable",
          "Server vaqtincha band yoki ishlamayapti ({}). Birozdan keyin qaytadan urinib ko'ring."),
    504: ("server_unavailable",
          "Server javobi kechikdi ({}). Birozdan keyin qaytadan urinib ko'ring."),
}

#: Aloqa "uzildi" deb hisoblanadigan statuslar (proksi bor, backend yo'q).
_GATEWAY_DOWN = frozenset({502, 503, 504})


def _gateway_down(response: httpx.Response) -> bool:
    """
    502/503/504 PROKSIDAN (backend yo'q) — konvertsiz, JSON emas.

    Backendning o'zi ham 503 qaytaradi (masalan `screenshots/presign/`
    "obyekt storage'i o'chirilgan") — bu aloqa uzilishi EMAS, server
    javob berdi. Farq tanada: bizning javoblar doim JSON.
    """
    if response.status_code not in _GATEWAY_DOWN:
        return False
    return "json" not in response.headers.get("content-type", "").lower()


def _error_of(body: Any) -> dict:
    """
    Konvertdagi `error` qismi — HAR DOIM lug'at.

    Server (yoki uning oldidagi proksi) `error` ni satr, ro'yxat yoki
    umuman boshqa shaklda qaytarsa ham bu yerda istisno chiqmasligi
    kerak: `.get()` ning `AttributeError` i fon ishchisida "Kutilmagan
    xato" bo'lib, haqiqiy sababni yashirardi.
    """
    if not isinstance(body, dict):
        return {}
    error = body.get("error")
    if isinstance(error, dict):
        return error
    if isinstance(error, str) and error:
        return {"message": error}
    # DRF'ning konvertsiz shakli: `{"detail": "..."}`.
    detail = body.get("detail")
    if isinstance(detail, str) and detail:
        return {"message": detail}
    return {}


def _json_or_none(response: httpx.Response) -> Any:
    if not response.content:
        return None
    try:
        return response.json()
    except (json.JSONDecodeError, ValueError):
        return None


def _with_retry_after(exc: ClientError, retry_after: Optional[float]) -> ClientError:
    """
    Istisnoga `retry_after` (soniya yoki `None`) qo'shadi.

    `ClientError` imzosi o'zgartirilmadi (`core/errors.py` — umumiy
    fayl): atribut dinamik, o'qish `getattr(exc, "retry_after", None)`.
    """
    exc.retry_after = retry_after
    return exc


def parse_response(response: httpx.Response) -> Any:
    """
    Javobni ochadi: muvaffaqiyatda `data`, aks holda `ClientError`.

    Sof funksiya (holatsiz) — testlanadi. Uchta "kutilmagan" shakl
    ham istisnoga aylanadi, qulashga emas:

      * bo'sh tana — 204/200 da `None`, xatoda status bo'yicha matn;
      * JSON bo'lmagan tana (nginx 502 HTML sahifasi, captive portal) —
        muvaffaqiyatli statusda ham `invalid_response`: tarmoqdagi
        proksi yoki mehmonxona tipidagi "login sahifasi" 200 bilan
        HTML qaytaradi va uni `data` deb o'qish keyinroq `.get()` da
        yiqilardi;
      * konvert buzilgan (`error` satr, `details` ro'yxat).

    Xabar `code` bo'yicha tanlanadi (`core.errors.ERROR_MESSAGES`),
    server matni esa zaxira: `code` barqaror kalit, matn o'zgaradi.
    """
    status = response.status_code
    if status == 204:
        return None

    body = _json_or_none(response)

    if 200 <= status < 300:
        if body is None and response.content:
            raise ClientError(
                "Server kutilmagan javob qaytardi (JSON emas). Tarmoq proksi "
                "yoki server sozlamasini tekshiring.",
                code="invalid_response",
                status=status,
            )
        if isinstance(body, dict) and "success" in body:
            return body.get("data")
        return body

    error = _error_of(body)
    code = str(error.get("code") or "")
    raw_message = error.get("message")
    raw_message = str(raw_message)[:500] if raw_message else ""
    details = error.get("details")
    if details is not None and not isinstance(details, dict):
        # Chaqiruvchilar `details.get(...)` qiladi; ro'yxat (DRF
        # validatsiya xatolari) ham lug'atga o'raladi.
        details = {"items": details}

    if not code and status in _STATUS_MESSAGES:
        code, template = _STATUS_MESSAGES[status]
        message = template.format(status)
    else:
        message = humanize(code, raw_message or "So'rov bajarilmadi ({})".format(status))

    retry_after = net_policy.parse_retry_after(response.headers.get("Retry-After"))

    # Faqat "noma'lum qurilma" alohida turga aylanadi - unga client
    # javob bera oladi (qayta ro'yxatdan o'tish). Qolgan qurilma
    # xatolari (`device_not_approved`, `device_revoked`) - operator
    # hal qiladigan holatlar, ular oddiy `ClientError` bo'lib qoladi.
    if code == "device_not_registered":
        raise DeviceNotRegistered(message, code=code, details=details, status=status)
    if status in (401, 403) and code in (
        "",
        "not_authenticated",
        "permission_denied",
        "authentication_failed",
    ):
        raise AuthError(message, code=code or "unauthorized", details=details, status=status)
    if status == 429:
        text = humanize("throttled", message)
        if retry_after:
            text = "{} ({} soniyadan keyin)".format(text.rstrip("."), int(retry_after + 0.999))
        raise _with_retry_after(
            ClientError(text, code="throttled", details=details, status=429), retry_after
        )
    raise _with_retry_after(
        ClientError(message, code=code, details=details, status=status),
        retry_after if status == 503 else None,
    )


class ApiClient(metaclass=SingletonMeta):
    """
    Backend bilan yagona aloqa nuqtasi.

    Uchta header, uchtasi ham boshqa savolga javob beradi (backend
    `proctoring/authentication.py` dagi model bilan bir xil):

        Authorization        - KIM (xodim JWT'si)
        X-Device-ID          - QAYSI kompyuter
        X-Proctoring-Session - QAYSI imtihon sessiyasi

    Tokenlar FAQAT xotirada (diskka yozilmaydi) va log'ga tushmaydi.
    """

    def __init__(self) -> None:
        self._access: Optional[str] = None
        self._refresh: Optional[str] = None
        self._device_id: Optional[str] = None
        self._session_token: Optional[str] = None
        # Bir nechta worker bir vaqtda 401 olishi mumkin (heartbeat +
        # hodisa flush). Qulfsiz ular refresh tokenni bir necha marta
        # ishlatadi; rotatsiya esa eskisini bekor qiladi, natijada
        # ikkalasi ham 401 oladi va operator sababsiz login sahifasiga
        # tushadi.
        self._refresh_lock = threading.RLock()
        self._auth_expired_handler: Optional[Callable[[], None]] = None
        #: Yopilganda so'rov ichidagi kutishlar darhol uziladi.
        self._closed = threading.Event()
        #: `Retry-After` darvozasi: yo'l -> monoton vaqt.
        self._gate: dict[str, float] = {}
        self._gate_lock = threading.Lock()
        self._client = httpx.Client(
            base_url=API_BASE_URL,
            # Ulanish qisqa, o'qish uzun: server yo'qligi tez bilinsin,
            # sekin javob (JSHSHIR tekshiruvi tashqi platformani kutadi)
            # esa uzilmasin.
            timeout=httpx.Timeout(
                API_TIMEOUT, connect=API_CONNECT_TIMEOUT, pool=API_CONNECT_TIMEOUT
            ),
            verify=API_SSL_VERIFY,
        )

    # ------------------------------------------------------------------
    # Holat
    # ------------------------------------------------------------------
    def set_tokens(self, access: str, refresh: str = "") -> None:
        self._access = access or None
        if refresh:
            self._refresh = refresh

    def set_device_id(self, device_id: str) -> None:
        self._device_id = device_id or None

    def set_session_token(self, token: Optional[str]) -> None:
        self._session_token = token or None

    def set_auth_expired_handler(self, handler: Callable[[], None]) -> None:
        self._auth_expired_handler = handler

    @property
    def has_session(self) -> bool:
        return bool(self._session_token)

    @property
    def access_token(self) -> Optional[str]:
        """Joriy access token — faqat fon chiqishi uchun (`AuthService.logout`)."""
        return self._access

    def clear(self) -> None:
        self._access = None
        self._refresh = None
        self._session_token = None

    def close(self) -> None:
        self._closed.set()
        try:
            self._client.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # So'rov
    # ------------------------------------------------------------------
    def get(self, path: str, **kwargs) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> Any:
        return self.request("POST", path, **kwargs)

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: Optional[dict] = None,
        files: Optional[dict] = None,
        data: Optional[dict] = None,
        with_auth: bool = True,
        timeout: Optional[float] = None,
        idempotent: Optional[bool] = None,
        retries: Optional[int] = None,
        auth_token: Optional[str] = None,
        _retry: bool = True,
    ) -> Any:
        """
        `idempotent` — standart: metod bo'yicha (GET ha, POST yo'q).
        `retries` — standart: idempotent 2, qolgani 1 (faqat serverga
        yetmagan xatoda); `timeout` berilgan bo'lsa 0. Davriy
        yuboruvchilar `retries=0` beradi — ularning o'z backoff'i bor.
        `auth_token` — `Authorization` uchun aniq token (joriy holatdan
        mustaqil; fon chiqishi).
        """
        method = method.upper()
        if idempotent is None:
            idempotent = method in net_policy.IDEMPOTENT_METHODS
        if retries is None:
            if timeout is not None:
                retries = 0
            else:
                retries = _RETRIES_IDEMPOTENT if idempotent else _RETRIES_UNSAFE
        self._check_gate(path)

        attempt = 0
        while True:
            headers = self._headers(with_auth=with_auth, auth_token=auth_token)
            sent_access = self._access
            try:
                response = self._client.request(
                    method,
                    path,
                    json=json_body,
                    params=params,
                    files=files,
                    data=data,
                    headers=headers,
                    # `None` - mijozning umumiy qiymati. Qisqasi faqat
                    # kutib bo'lmaydigan joyda beriladi (dasturdan
                    # chiqishda sessiyani yakunlash).
                    timeout=httpx.USE_CLIENT_DEFAULT if timeout is None else timeout,
                )
            except _NOT_SENT_ERRORS as exc:
                self._report_online(False)
                if attempt < retries and self._pause(attempt, method, path, type(exc).__name__):
                    attempt += 1
                    continue
                # Xabarda URL/so'rov tanasi YO'Q: ularda token yoki
                # JSHSHIR bo'lishi mumkin; faqat yo'l va xato turi.
                log.warning("Serverga ulanib bo'lmadi: %s %s (%s)", method, path, type(exc).__name__)
                # `code="network"` - sahifalar buni domen xatosidan
                # ajratadi: server javob bergan xato (masalan
                # `ip_not_allowed`) va serverga umuman yetib bo'lmagani
                # turli harakat talab qiladi.
                raise NetworkError(
                    "Serverga ulanib bo'lmadi. Tarmoq kabeli yoki Wi-Fi ni tekshiring; "
                    "aloqa tiklangach qaytadan urinib ko'ring.",
                    code="network",
                ) from exc
            except httpx.TimeoutException as exc:
                # Javob timeout'i: so'rov serverga YETGAN bo'lishi mumkin.
                self._report_online(False)
                if idempotent and attempt < retries and self._pause(
                    attempt, method, path, type(exc).__name__
                ):
                    attempt += 1
                    continue
                log.warning("Server javob bermadi: %s %s (%s)", method, path, type(exc).__name__)
                raise NetworkError(
                    "Server javob bermadi (timeout). Tarmoqni tekshiring va qaytadan urinib ko'ring.",
                    code="network",
                ) from exc
            except httpx.RequestError as exc:
                # Uzilgan javob, protokol xatosi (masalan keep-alive
                # ulanishi server tomonda yopilgan) — yetgan bo'lishi mumkin.
                self._report_online(False)
                if idempotent and attempt < retries and self._pause(
                    attempt, method, path, type(exc).__name__
                ):
                    attempt += 1
                    continue
                log.warning("Tarmoq xatosi: %s %s (%s)", method, path, type(exc).__name__)
                raise NetworkError(
                    "Server bilan aloqa uzildi. Tarmoqni tekshiring va qaytadan urinib ko'ring.",
                    code="network",
                ) from exc

            status = response.status_code
            self._report_online(not _gateway_down(response))
            retry_after = net_policy.parse_retry_after(response.headers.get("Retry-After"))
            if status in (429, 503) and retry_after:
                self._set_gate(path, retry_after)

            if (
                net_policy.is_retryable_status(status)
                and idempotent
                and attempt < retries
                and (retry_after is None or retry_after <= _INLINE_MAX_RETRY_AFTER_S)
                and self._pause(attempt, method, path, str(status), retry_after)
            ):
                attempt += 1
                continue
            break

        # 401 - access token eskirgan bo'lishi mumkin. BIR MARTA refresh
        # qilib qayta yuboramiz; ikkinchi 401 haqiqiy chiqish demak.
        #
        # Lekin HAR QANDAY 401 token muammosi emas: `device_not_registered`
        # ham 401 bilan keladi (qurilma admin tasdig'ini kutyapti).
        # Bunda refresh mutlaqo befoyda va zararli - `ROTATE_REFRESH_TOKENS`
        # tufayli har urinish refresh tokenni almashtiradi.
        if (
            status == 401
            and with_auth
            and auth_token is None
            and _retry
            and self._is_token_problem(response)
        ):
            if self._try_refresh(sent_access):
                return self.request(
                    method,
                    path,
                    json_body=json_body,
                    params=params,
                    files=files,
                    data=data,
                    with_auth=with_auth,
                    timeout=timeout,
                    idempotent=idempotent,
                    retries=retries,
                    _retry=False,
                )
            self._notify_auth_expired()

        try:
            return parse_response(response)
        except ClientError as exc:
            log.warning(
                "API xatosi %s %s -> %s (%s)", method, path, status, exc.code or "-"
            )
            raise

    def put_binary(self, url: str, data: bytes, content_type: str) -> None:
        """
        Presigned URL'ga to'g'ridan-to'g'ri PUT (obyekt storage'iga).

        BIZNING header'larimiz YUBORILMAYDI va bu majburiy: presigned
        URL imzosi so'rov parametrlarida yashaydi, `Authorization`
        header'i esa S3 uchun ikkinchi, ziddiyatli autentifikatsiya
        usuli - u bo'lsa so'rov rad etiladi. `X-Device-ID` va sessiya
        tokeni ham bu yerda begona: ular bizning backendimiz uchun va
        uchinchi tomon storage'iga oshkor qilinmasligi kerak.

        `base_url` bu chaqiruvga TA'SIR QILMAYDI: httpx absolyut URL'ni
        o'zgartirmasdan ishlatadi.

        Javob tanasi o'qilmaydi - S3 muvaffaqiyatda bo'sh tana va ETag
        qaytaradi, bizga esa faqat statusi kerak. URL LOG'GA YOZILMAYDI:
        uning so'rov qatorida imzo turadi.
        """
        try:
            response = self._client.put(
                url,
                content=data,
                headers={"Content-Type": content_type},
                # Skrinshot ~150 KB va sekin kanalda ham tez ketadi;
                # umumiy `API_TIMEOUT` (30 s) bu yerda ham yetarli.
                timeout=httpx.Timeout(API_TIMEOUT, connect=API_CONNECT_TIMEOUT),
            )
        except httpx.TimeoutException as exc:
            raise NetworkError(
                "Obyekt storage'i javob bermadi (timeout).", code="network"
            ) from exc
        except httpx.RequestError as exc:
            raise NetworkError(
                "Obyekt storage'iga ulanib bo'lmadi.", code="network"
            ) from exc

        if response.is_success:
            return

        # S3 xatosi XML qaytaradi, bizning konvertimizda emas. Faqat
        # `<Code>` log'ga ketadi: `SignatureDoesNotMatch` javobida
        # `StringToSign` va kalit identifikatori ham bor.
        match = re.search(r"<Code>([^<]{1,64})</Code>", response.text or "")
        log.warning(
            "Obyekt storage'iga yuklab bo'lmadi: %s %s",
            response.status_code,
            match.group(1) if match else "-",
        )
        raise ClientError(
            "Skrinshotni saqlab bo'lmadi (storage {})".format(response.status_code),
            code="storage_upload_failed",
            status=response.status_code,
        )

    # ------------------------------------------------------------------
    # Ichki
    # ------------------------------------------------------------------
    def _headers(self, *, with_auth: bool, auth_token: Optional[str] = None) -> dict:
        headers = {"Accept": "application/json"}
        token = auth_token or self._access
        if with_auth and token:
            headers["Authorization"] = "Bearer " + token
        if self._device_id:
            headers["X-Device-ID"] = self._device_id
        if self._session_token:
            headers["X-Proctoring-Session"] = self._session_token
        return headers

    def _pause(self, attempt: int, method: str, path: str, reason: str,
               retry_after: Optional[float] = None) -> bool:
        """
        Takrordan oldin kutadi. `False` — dastur yopilmoqda, takror yo'q.

        FON THREAD'IDA chaqiriladi (`ApiClient` UI thread'da
        ishlatilmaydi — `services/workers.py`), ya'ni uxlash oynani
        muzlatmaydi.
        """
        delay = net_policy.backoff_delay(attempt, base=_INLINE_BASE_S, cap=_INLINE_CAP_S)
        if retry_after is not None:
            delay = max(delay, retry_after)
        log.info(
            "Qayta urinish %s %s (%s) - %.1f s dan keyin (%s-urinish)",
            method, path, reason, delay, attempt + 2,
        )
        return not self._closed.wait(delay)

    def _check_gate(self, path: str) -> None:
        with self._gate_lock:
            until = self._gate.get(path)
            if until is None:
                return
            remaining = until - time.monotonic()
            if remaining <= 0:
                self._gate.pop(path, None)
                return
        # Server "kuting" degan yo'lga so'rov umuman YUBORILMAYDI: davriy
        # yuboruvchilar (presence, heartbeat, yuklash) buni bilmasa ham
        # serverni urmaydi.
        raise _with_retry_after(
            ClientError(
                "{} ({} soniyadan keyin)".format(
                    humanize("throttled", "").rstrip("."), int(remaining + 0.999)
                ),
                code="throttled",
                status=429,
            ),
            remaining,
        )

    def _set_gate(self, path: str, seconds: float) -> None:
        with self._gate_lock:
            self._gate[path] = time.monotonic() + float(seconds)
        log.info("Server %s uchun %.0f s kutishni so'radi (Retry-After)", path, seconds)

    @staticmethod
    def _report_online(online: bool) -> None:
        try:
            from services.network_status import network_status

            network_status().report(online)
        except Exception:
            log.debug("Aloqa holatini yangilab bo'lmadi", exc_info=True)

    @staticmethod
    def _is_token_problem(response: httpx.Response) -> bool:
        """
        401 javobi AYNAN token haqidami?

        Backend domen xatolarini ham 401 bilan qaytaradi (masalan
        `device_not_registered`). Ularni `code` bo'yicha ajratamiz:
        kod yo'q yoki simplejwt/DRF kodlaridan biri bo'lsa - token
        muammosi, aks holda domen xatosi va refresh yordam bermaydi.
        """
        code = str(_error_of(_json_or_none(response)).get("code") or "")
        return code in ("", "not_authenticated", "authentication_failed", "token_not_valid")

    def _try_refresh(self, stale_access: Optional[str] = None) -> bool:
        """
        Access tokenni yangilaydi. `False` — server refresh'ni RAD ETDI.

        TARMOQ XATOSI `False` EMAS — `NetworkError`. Farq hal qiluvchi:
        `False` "sessiya muddati tugadi" (login sahifasiga qaytish,
        imtihon sahifasi to'xtaydi), holbuki refresh paytidagi bir
        soniyalik uzilish xodimni tizimdan chiqarmasligi kerak.

        `stale_access` — 401 olgan so'rovdagi token. Qulfni kutib
        turganda boshqa thread allaqachon yangilagan bo'lsa, ikkinchi
        refresh yuborilmaydi (rotatsiya uni keraksiz almashtirardi).
        """
        with self._refresh_lock:
            if stale_access is not None and self._access and self._access != stale_access:
                return True
            if not self._refresh:
                return False
            try:
                # Refresh IDEMPOTENT EMAS (rotatsiya) — takror yo'q.
                response = self._client.post(
                    "/auth/refresh/", json={"refresh": self._refresh},
                    timeout=httpx.Timeout(15.0, connect=API_CONNECT_TIMEOUT),
                )
            except httpx.RequestError as exc:
                self._report_online(False)
                log.warning("Tokenni yangilab bo'lmadi - tarmoq (%s)", type(exc).__name__)
                raise NetworkError(
                    "Serverga ulanib bo'lmadi. Tarmoqni tekshiring.", code="network"
                ) from exc
            self._report_online(not _gateway_down(response))
            if response.status_code >= 500 or response.status_code == 429:
                # Server vaqtincha ishlamayapti — bu ham "muddat tugadi"
                # EMAS.
                log.warning("Refresh: server xatosi (%s)", response.status_code)
                raise NetworkError(
                    "Server vaqtincha javob bermayapti ({}). Birozdan keyin qaytadan "
                    "urinib ko'ring.".format(response.status_code),
                    code="server_unavailable",
                    status=response.status_code,
                )
            if response.status_code != 200:
                log.info("Refresh rad etildi (%s)", response.status_code)
                return False
            payload = self._payload(response)
            access = payload.get("access")
            if not access:
                return False
            self._access = access
            # `ROTATE_REFRESH_TOKENS=True` - javobda YANGI refresh keladi va
            # eskisi blacklist'ga tushadi. Saqlamasak, keyingi refresh bekor
            # qilingan token bilan ketadi va sessiya uziladi.
            if payload.get("refresh"):
                self._refresh = payload["refresh"]
            return True

    def _notify_auth_expired(self) -> None:
        if self._auth_expired_handler is not None:
            try:
                self._auth_expired_handler()
            except Exception:
                log.exception("auth_expired handler xatosi")

    @staticmethod
    def _payload(response: httpx.Response) -> dict:
        body = _json_or_none(response)
        if isinstance(body, dict) and "success" in body:
            data = body.get("data")
            return data if isinstance(data, dict) else {}
        return body if isinstance(body, dict) else {}
