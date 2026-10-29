"""
BBA Console API client (`bba_agent_api.md`).

Console — boshqa tizim: biz uning faqat mijozimiz. Qoidalar shu yerda,
chaqiruvchilarda emas:

* Token 24 soat yashaydi va UMUMIY keshda saqlanadi (`TOKEN_KEY`) — har
  so'rovda login qilinmaydi, HTTP/Celery jarayonlari bitta tokenni
  ishlatadi. 401 kelsa bir marta qayta login va so'rov qaytariladi.
* Console 15 daqiqada 5 noto'g'ri paroldan keyin login'ni 15 daqiqaga
  bloklaydi. Shuning uchun rad etilgan login keshda ESLAB qolinadi
  (`LOGIN_BLOCK_KEY`, 5 daqiqa — 15 daqiqada ko'pi bilan 3 urinish): har
  15 s dagi holat so'rovi va har panel ochilishi parolni qayta sinasa,
  hisob o'zimiz tufayli bloklanardi.
* GET 5xx/tarmoq xatosida qisqa qayta urinish oladi; POST (job) — YO'Q:
  javobi yo'qolgan job Console'da yaratilgan bo'lishi mumkin va qayta
  yuborish uni ikki marta bajarardi (`shutdown`, `run_script`).
* Sertifikat Console'ning ichki CA'si bilan tekshiriladi (`CA_FILE`).
"""

from __future__ import annotations

import hashlib
import logging
import math
import ssl
import threading
import time
from pathlib import Path
from urllib.parse import quote

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

TOKEN_KEY = "bba:token"
LOGIN_BLOCK_KEY = "bba:login_blocked"
LOGIN_BLOCK_SECONDS = 5 * 60
#: `limit` > 500 Console'da xato bermaydi — JIMGINA 50 ga tushadi.
PAGE_LIMIT = 500
#: GET uchun qo'shimcha urinishlar (5xx, uzilish).
GET_RETRIES = 2


class BbaError(Exception):
    """Console bilan ishlashdagi xato. Matn — administrator uchun, o'zbekcha."""

    code = "bba_error"
    default_message = "BBA Console bilan ishlashda xato"

    def __init__(self, message: str = "", *, status: int | None = None):
        super().__init__(message or self.default_message)
        self.status = status


class BbaNotConfigured(BbaError):
    code = "bba_not_configured"
    default_message = "BBA Console integratsiyasi sozlanmagan (BBA_ENABLED, BBA_USERNAME, BBA_PASSWORD)"


class BbaUnavailable(BbaError):
    code = "bba_unavailable"
    default_message = "BBA Console javob bermayapti"


class BbaAuthError(BbaError):
    code = "bba_auth_failed"
    default_message = "BBA Console login'i rad etildi"


class BbaForbidden(BbaError):
    code = "bba_forbidden"
    default_message = "BBA Console bu amalga ruxsat bermadi (hisobda huquq yo'q)"


class BbaNotFound(BbaError):
    code = "bba_not_found"
    default_message = "BBA Console'da topilmadi"


class BbaRateLimited(BbaError):
    code = "bba_rate_limited"
    default_message = "BBA Console so'rovlar limiti oshdi, biroz kuting"

    def __init__(self, message: str = "", *, status: int | None = 429, retry_after: int = 30):
        super().__init__(message, status=status)
        self.retry_after = retry_after


class BbaRejected(BbaError):
    """Console so'rovni qabul qilmadi (400/409/422) — masalan job parametri."""

    code = "bba_rejected"
    default_message = "BBA Console so'rovni rad etdi"


def config() -> dict:
    return settings.BBA_CONSOLE


def is_configured(cfg: dict | None = None) -> bool:
    cfg = cfg or config()
    return bool(cfg["ENABLED"] and cfg["BASE_URL"] and cfg["USERNAME"] and cfg["PASSWORD"])


def ca_path(cfg: dict | None = None) -> Path | None:
    raw = (cfg or config())["CA_FILE"]
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else settings.ROOT_DIR / path


def _verify(cfg: dict):
    if not cfg["VERIFY_TLS"]:
        return False
    path = ca_path(cfg)
    if path is None:
        return True
    if not path.is_file():
        raise BbaNotConfigured(f"BBA_CA_FILE topilmadi: {path} (python manage.py bba_console fetch-ca)")
    return str(path)


def _message(response) -> str:
    """Console xato matni: JSON `{"error": ...}` yoki oddiy matn (`404 page not found`)."""
    try:
        data = response.json()
    except ValueError:
        data = None
    if isinstance(data, dict) and data.get("error"):
        text = str(data["error"])
    else:
        text = (response.text or "").strip()
    return text[:300]


def _json(response):
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise BbaUnavailable("BBA Console javobi JSON emas", status=response.status_code) from exc


def _error_for(response) -> BbaError:
    status = response.status_code
    text = _message(response)
    if status == 403:
        if "password change" in text.lower():
            return BbaAuthError(
                "BBA Console parolni almashtirishni talab qilyapti — Console "
                "administratori parolni qayta o'rnatsin", status=status,
            )
        return BbaForbidden(f"BBA Console ruxsat bermadi: {text}" if text else "", status=status)
    if status == 404:
        return BbaNotFound(status=status)
    if status == 429:
        try:
            retry_after = int(response.headers.get("Retry-After") or 30)
        except ValueError:
            retry_after = 30
        return BbaRateLimited(retry_after=max(1, min(retry_after, 300)))
    if status >= 500:
        return BbaUnavailable(f"BBA Console xatosi ({status})", status=status)
    return BbaRejected(f"BBA Console rad etdi: {text}" if text else "", status=status)


def _token_ttl(expires_at) -> int:
    """Token muddati tugashidan 5 daqiqa OLDIN keshdan chiqadi."""
    parsed = parse_datetime(expires_at) if isinstance(expires_at, str) else None
    if parsed is None:
        return 12 * 3600
    seconds = (parsed - timezone.now()).total_seconds() - 300
    return int(max(60, min(seconds, 23 * 3600)))


class BbaClient:
    def __init__(self, cfg: dict | None = None, session: requests.Session | None = None):
        self.cfg = cfg or config()
        self.session = session or requests.Session()

    # --- Past daraja ---
    def path(self, name: str, **ids) -> str:
        template = self.cfg["ENDPOINTS"][name]
        return template.format(**{key: quote(str(value), safe="") for key, value in ids.items()})

    def _send(self, method: str, path: str, *, params=None, body=None, token: str | None = None):
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            return self.session.request(
                method,
                self.cfg["BASE_URL"] + path,
                params=params,
                json=body,
                headers=headers,
                timeout=(self.cfg["CONNECT_TIMEOUT"], self.cfg["READ_TIMEOUT"]),
                verify=_verify(self.cfg),
                # Yo'naltirish token'ni boshqa hostga olib ketmasin.
                allow_redirects=False,
            )
        except requests.exceptions.SSLError as exc:
            raise BbaUnavailable(
                "BBA Console sertifikati tekshiruvdan o'tmadi (BBA_CA_FILE)"
            ) from exc
        except requests.RequestException as exc:
            raise BbaUnavailable(
                f"BBA Console'ga ulanib bo'lmadi ({exc.__class__.__name__})"
            ) from exc

    def _token(self, *, force: bool = False) -> str:
        if not force:
            token = cache.get(TOKEN_KEY)
            if token:
                return token
        blocked = cache.get(LOGIN_BLOCK_KEY)
        if blocked:
            raise BbaAuthError(blocked)
        return self._login()

    def _login(self) -> str:
        if not is_configured(self.cfg):
            raise BbaNotConfigured()
        response = self._send(
            "POST",
            self.path("login"),
            body={"username": self.cfg["USERNAME"], "password": self.cfg["PASSWORD"]},
        )
        status = response.status_code
        if status == 200:
            data = _json(response) or {}
            token = data.get("token") if isinstance(data, dict) else None
            if not token:
                raise BbaUnavailable("BBA Console login javobida token yo'q")
            if data.get("must_change_password"):
                return self._block(
                    "BBA Console parolni almashtirishni talab qilyapti — Console "
                    "administratori parolni qayta o'rnatsin"
                )
            cache.set(TOKEN_KEY, token, _token_ttl(data.get("expires_at")))
            return token
        if status in (400, 401, 403):
            return self._block("BBA Console login yoki paroli noto'g'ri (BBA_USERNAME / BBA_PASSWORD)")
        if status == 429:
            return self._block("BBA Console login'i vaqtincha bloklangan (ko'p noto'g'ri urinish)")
        raise _error_for(response)

    @staticmethod
    def _block(message: str):
        cache.set(LOGIN_BLOCK_KEY, message, LOGIN_BLOCK_SECONDS)
        logger.error("BBA Console: %s", message)
        raise BbaAuthError(message)

    def request(self, method: str, path: str, *, params=None, body=None):
        token = self._token()
        response = self._send(method, path, params=params, body=body, token=token)
        if response.status_code == 401:
            # Muddati tugagan yoki Console'da bekor qilingan token: bir marta
            # yangisi. Ikkinchi 401 — sikl emas, xato.
            if cache.get(TOKEN_KEY) == token:
                cache.delete(TOKEN_KEY)
            token = self._token(force=True)
            response = self._send(method, path, params=params, body=body, token=token)
            if response.status_code == 401:
                cache.delete(TOKEN_KEY)
                raise BbaAuthError("BBA Console token'ni qabul qilmadi", status=401)
        if response.status_code >= 400:
            raise _error_for(response)
        return _json(response)

    def get(self, path: str, params=None):
        for attempt in range(GET_RETRIES + 1):
            try:
                return self.request("GET", path, params=params)
            except BbaUnavailable:
                if attempt == GET_RETRIES:
                    raise
                time.sleep(0.5 * 2**attempt)
        raise AssertionError("unreachable")

    def post(self, path: str, body=None):
        return self.request("POST", path, body=body if body is not None else {})

    # --- Daraxt ---
    def regions(self) -> list:
        data = self.get(self.path("regions"))
        return data if isinstance(data, list) else []

    def rooms(self) -> list:
        data = self.get(self.path("rooms"))
        return data if isinstance(data, list) else []

    def devices_page(self, *, offset: int = 0, limit: int = PAGE_LIMIT, **filters) -> dict:
        params = {key: value for key, value in filters.items() if value not in (None, "")}
        params.update(limit=min(limit, PAGE_LIMIT), offset=offset)
        data = self.get(self.path("devices"), params) or {}
        return {"devices": data.get("devices") or [], "total": int(data.get("total") or 0)}

    def iter_devices(self, **filters):
        """Hamma sahifalar. Sahifalar soni boshidagi `total` bilan cheklangan."""
        offset = 0
        page = self.devices_page(offset=0, **filters)
        max_pages = math.ceil(page["total"] / PAGE_LIMIT) + 1
        for _ in range(max_pages):
            yield from page["devices"]
            offset += PAGE_LIMIT
            if not page["devices"] or offset >= page["total"]:
                return
            page = self.devices_page(offset=offset, **filters)

    def device(self, console_id: str) -> dict | None:
        devices = self.devices_page(id=console_id, limit=1)["devices"]
        return devices[0] if devices else None

    def inventory(self, console_id: str) -> dict:
        return self.get(self.path("inventory", id=console_id)) or {}

    def connectivity(self, console_id: str, limit: int = 50) -> list:
        data = self.get(self.path("connectivity", id=console_id), {"limit": min(limit, 200)}) or {}
        return data.get("events") or []

    def stats(self) -> dict:
        return self.get(self.path("stats")) or {}

    def me(self) -> dict:
        return self.get(self.path("me")) or {}

    # --- Job'lar ---
    def jobs(self, **filters) -> dict:
        params = {key: value for key, value in filters.items() if value not in (None, "")}
        data = self.get(self.path("jobs"), params) or {}
        return {"jobs": data.get("jobs") or [], "total": int(data.get("total") or 0)}

    def create_job(self, console_id: str, body: dict) -> dict:
        return self.post(self.path("device_jobs", id=console_id), body) or {}

    def bulk_create_jobs(self, console_ids: list[str], body: dict) -> dict:
        return self.post(self.path("bulk_jobs"), {"device_ids": list(console_ids), **body}) or {}

    def cancel_job(self, job_id: str) -> dict:
        return self.post(self.path("job_cancel", id=job_id)) or {}

    def resend_job(self, job_id: str) -> dict:
        return self.post(self.path("job_resend", id=job_id)) or {}

    def wake(self, console_id: str) -> dict:
        return self.post(self.path("device_wake", id=console_id)) or {}

    def wake_many(self, console_ids: list[str]) -> dict:
        return self.post(self.path("bulk_wake"), {"device_ids": list(console_ids)}) or {}


_local = threading.local()


def get_client() -> BbaClient:
    """
    Thread'ga bitta client (`requests.Session` thread'lar orasida ulashilmaydi:
    gunicorn `gthread` va Windows Celery `threads` pool'i).
    """
    client = getattr(_local, "client", None)
    if client is None or client.cfg is not config():
        client = BbaClient()
        _local.client = client
    return client


def fetch_ca(base_url: str, timeout: float = 10.0) -> tuple[bytes, str]:
    """
    `GET /ca` — Console CA sertifikati (PEM) va uning SHA-256 izi.

    Bir martalik va TEKSHIRUVSIZ (tovuq-tuxum: CA'siz Console'ni tekshirib
    bo'lmaydi). Shuning uchun iz chiqariladi — administrator uni Console
    administratoridagi qiymat bilan solishtiradi.
    """
    try:
        response = requests.get(base_url.rstrip("/") + "/ca", timeout=timeout, verify=False)  # noqa: S501
        response.raise_for_status()
    except requests.exceptions.ConnectTimeout as exc:
        # Odatda tarmoq yo'li/firewall: Console ishlayapti, lekin bu serverdan
        # unga yo'l yo'q (`bba_agent_api.md` §1 — 8443 porti ochilishi kerak).
        raise BbaUnavailable(
            f"{base_url} ga ulanib bo'lmadi (timeout) — serverdan Console'ga tarmoq yo'li "
            "yoki firewall ruxsati yo'q. Tekshiring: nc -vz -w 5 <host> <port>"
        ) from exc
    except requests.RequestException as exc:
        raise BbaUnavailable(f"CA sertifikatini olib bo'lmadi: {exc.__class__.__name__}: {exc}") from exc
    pem = response.content
    if b"BEGIN CERTIFICATE" not in pem:
        raise BbaError("Javob PEM sertifikat emas")
    der = ssl.PEM_cert_to_DER_cert(pem.decode("ascii", errors="strict"))
    fingerprint = hashlib.sha256(der).hexdigest().upper()
    return pem, ":".join(fingerprint[i:i + 2] for i in range(0, len(fingerprint), 2))


def login_block_reason() -> str | None:
    """Panel uchun: login blokda bo'lsa matni (keshdan)."""
    return cache.get(LOGIN_BLOCK_KEY)


def clear_login_block() -> None:
    cache.delete(LOGIN_BLOCK_KEY)
    cache.delete(TOKEN_KEY)


__all__ = [
    "BbaAuthError", "BbaClient", "BbaError", "BbaForbidden", "BbaNotConfigured",
    "BbaNotFound", "BbaRateLimited", "BbaRejected", "BbaUnavailable", "PAGE_LIMIT",
    "clear_login_block", "config", "fetch_ca", "get_client", "is_configured",
    "login_block_reason",
]
