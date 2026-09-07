"""
HTTP transport qatlami — bitta joyda.

Bu modul HECH QANDAY biznes-mantiq bilmaydi: u faqat so'rov yuboradi,
`{success, data, error}` konvertini ochadi, tokenlarni qo'yadi va 401 da
bir marta refresh qiladi. Endpoint nomlari va oqim mantig'i
`repositories.py` da.

Ajratishning sababi: backend konverti yoki auth sxemasi o'zgarsa —
o'zgarish shu faylda qoladi; yangi endpoint qo'shilsa — repository'da.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable, Optional

import httpx

from config import API_BASE_URL, API_SSL_VERIFY, API_TIMEOUT
from core.errors import AuthError, ClientError, DeviceNotRegistered, NetworkError, humanize
from core.singleton import SingletonMeta

log = logging.getLogger(__name__)

if API_SSL_VERIFY is False:
    log.warning("API_SSL_VERIFY=0 - MITM xavfi. Production'da HTTPS + CA majburiy.")


class ApiClient(metaclass=SingletonMeta):
    """
    Backend bilan yagona aloqa nuqtasi.

    Uchta header, uchtasi ham boshqa savolga javob beradi (backend
    `proctoring/authentication.py` dagi model bilan bir xil):

        Authorization        - KIM (xodim JWT'si)
        X-Device-ID          - QAYSI kompyuter
        X-Proctoring-Session - QAYSI imtihon sessiyasi
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
        self._client = httpx.Client(
            base_url=API_BASE_URL, timeout=API_TIMEOUT, verify=API_SSL_VERIFY
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

    def clear(self) -> None:
        self._access = None
        self._refresh = None
        self._session_token = None

    def close(self) -> None:
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
        _retry: bool = True,
    ) -> Any:
        headers = self._headers(with_auth=with_auth)
        try:
            response = self._client.request(
                method,
                path,
                json=json_body,
                params=params,
                files=files,
                data=data,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            log.warning("Timeout: %s %s (%s)", method, path, exc)
            raise NetworkError(
                "Server javob bermadi (timeout). Tarmoqni tekshiring.", code="network"
            ) from exc
        except httpx.RequestError as exc:
            log.warning("Tarmoq xatosi: %s %s (%s)", method, path, exc)
            # `code="network"` - sahifalar buni domen xatosidan ajratishi
            # kerak: server javob bergan xato (masalan `ip_not_allowed`)
            # va serverga umuman yetib bo'lmagani turli harakat talab
            # qiladi.
            raise NetworkError(
                "Serverga ulanib bo'lmadi. Tarmoqni tekshiring.", code="network"
            ) from exc

        # 401 - access token eskirgan bo'lishi mumkin. BIR MARTA refresh
        # qilib qayta yuboramiz; ikkinchi 401 haqiqiy chiqish demak.
        #
        # Lekin HAR QANDAY 401 token muammosi emas: `device_not_registered`
        # ham 401 bilan keladi (qurilma admin tasdig'ini kutyapti).
        # Bunda refresh mutlaqo befoyda va zararli - `ROTATE_REFRESH_TOKENS`
        # tufayli har urinish refresh tokenni almashtiradi.
        if (
            response.status_code == 401
            and with_auth
            and _retry
            and self._is_token_problem(response)
        ):
            if self._try_refresh():
                return self.request(
                    method,
                    path,
                    json_body=json_body,
                    params=params,
                    files=files,
                    data=data,
                    with_auth=with_auth,
                    _retry=False,
                )
            self._notify_auth_expired()

        return self._unwrap(response)

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
        qaytaradi, bizga esa faqat statusi kerak.
        """
        try:
            response = self._client.put(
                url,
                content=data,
                headers={"Content-Type": content_type},
                # Skrinshot ~100 KB va sekin kanalda ham tez ketadi;
                # umumiy `API_TIMEOUT` (30 s) bu yerda ham yetarli.
                timeout=API_TIMEOUT,
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

        # S3 xatosi XML qaytaradi, bizning konvertimizda emas. Uni
        # tahlil qilmaymiz: client bu xato bilan hech nima qila
        # olmaydi, faqat qayta urinadi.
        log.warning(
            "Obyekt storage'iga yuklab bo'lmadi: %s %s",
            response.status_code,
            response.text[:200],
        )
        raise ClientError(
            "Skrinshotni saqlab bo'lmadi (storage {})".format(response.status_code),
            code="storage_upload_failed",
            status=response.status_code,
        )

    # ------------------------------------------------------------------
    # Ichki
    # ------------------------------------------------------------------
    def _headers(self, *, with_auth: bool) -> dict:
        headers = {"Accept": "application/json"}
        if with_auth and self._access:
            headers["Authorization"] = "Bearer " + self._access
        if self._device_id:
            headers["X-Device-ID"] = self._device_id
        if self._session_token:
            headers["X-Proctoring-Session"] = self._session_token
        return headers

    @staticmethod
    def _is_token_problem(response: httpx.Response) -> bool:
        """
        401 javobi AYNAN token haqidami?

        Backend domen xatolarini ham 401 bilan qaytaradi (masalan
        `device_not_registered`). Ularni `code` bo'yicha ajratamiz:
        kod yo'q yoki simplejwt/DRF kodlaridan biri bo'lsa - token
        muammosi, aks holda domen xatosi va refresh yordam bermaydi.
        """
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError):
            return True
        error = body.get("error") or {} if isinstance(body, dict) else {}
        code = str(error.get("code") or "")
        return code in ("", "not_authenticated", "authentication_failed", "token_not_valid")

    def _try_refresh(self) -> bool:
        with self._refresh_lock:
            if not self._refresh:
                return False
            try:
                response = self._client.post(
                    "/auth/refresh/", json={"refresh": self._refresh}, timeout=15.0
                )
            except httpx.RequestError:
                return False
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
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError):
            return {}
        if isinstance(body, dict) and "success" in body:
            return body.get("data") or {}
        return body if isinstance(body, dict) else {}

    def _unwrap(self, response: httpx.Response) -> Any:
        """
        Konvertni ochadi va xatoni `ClientError` ga aylantiradi.

        Xabar `code` bo'yicha tanlanadi (`core.errors.ERROR_MESSAGES`),
        server matni esa zaxira: `code` barqaror kalit, matn esa
        o'zgarishi mumkin.
        """
        if response.status_code == 204:
            return None

        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError):
            body = None

        if response.is_success:
            if isinstance(body, dict) and "success" in body:
                return body.get("data")
            return body

        error = body.get("error") or {} if isinstance(body, dict) else {}
        code = str(error.get("code") or "")
        message = humanize(code, str(error.get("message") or "So'rov bajarilmadi"))
        details = error.get("details")

        log.warning(
            "API xatosi %s %s -> %s (%s)",
            response.request.method,
            response.url.path,
            response.status_code,
            code or "-",
        )

        # Faqat "noma'lum qurilma" alohida turga aylanadi - unga client
        # javob bera oladi (qayta ro'yxatdan o'tish). Qolgan qurilma
        # xatolari (`device_not_approved`, `device_revoked`) - operator
        # hal qiladigan holatlar, ular oddiy `ClientError` bo'lib qoladi.
        if code == "device_not_registered":
            raise DeviceNotRegistered(
                message, code=code, details=details, status=response.status_code
            )
        if response.status_code in (401, 403) and code in (
            "",
            "not_authenticated",
            "permission_denied",
            "authentication_failed",
        ):
            raise AuthError(
                message,
                code=code or "unauthorized",
                details=details,
                status=response.status_code,
            )
        if response.status_code == 429:
            raise ClientError(
                humanize("throttled", message), code="throttled", details=details, status=429
            )
        raise ClientError(message, code=code, details=details, status=response.status_code)
