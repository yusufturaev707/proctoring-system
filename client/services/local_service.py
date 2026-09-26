"""
Lokal xizmat: test platformasi frontendi uchun `127.0.0.1:8050`.

Test platformasi client ICHIDAGI WebView'da ochiladi, lekin u client
bilan gaplasha olmaydi - boshqa domen, boshqa dastur. Ikki ehtiyoj bor:

    GET  /api/device_info     shu mashina kim (UUID, IP, MAC, raqam)
    POST /api/capture_screen  ekranni HOZIR suratga ol (javob belgilandi)

Ikkinchisi skrinshotning YAGONA manbai - taymer yo'q
(`services/screen_capture.py`). Platforma talabgor javobni belgilagan
lahzani biladi, client esa bilmaydi.

JAVOB SHAKLI (platforma bilan SHARTNOMA - kalitlarni o'zgartirmang):

    {"machine_uuid": "4C4C4544-...", "ip": "192.168.0.194",
     "mac": "2c:f0:5d:77:bb:eb", "number": "13"}

`machine_uuid` - SMBIOS UUID, HAR DOIM to'ldirilgan va tekshirilgan
(`system_info.machine_uuid`: besh manbali zanjir + validatsiya).
`number` - xonadagi raqam, SATR (handshake'dan; login'gacha `null`).
`mac` - kichik harf, `:` bilan. Aniqlanmagan qiymat - `null`.

`capture_screen` TANASI - `{"q_id": "1", "q_n": "3"}` ("shu savolga javob
belgilandi"; satr ham, son ham; JSON, forma yoki query). Kadr savol
nomi bilan saqlanadi va savolga qayta belgilansa ALMASHADI
(`services/screen_capture.py`). Tana bo'sh - savolsiz kadr.

| Javob | Qachon |
|---|---|
| 202 `{"ok": true, "accepted": true, "q_id", "q_n"}` | qabul qilindi - kadr fonda |
| 400 `invalid_json` / `invalid_q_id` / `invalid_q_n` / `q_id_required` | tana yaroqsiz |
| 409 `no_active_exam` | imtihon ochiq emas / dalil yig'ish vaqti tugagan |
| 429 `too_many_requests` | sekundiga 20 dan ko'p buyruq |

202 DARHOL qaytadi - suratga olish UI thread'ida, kodlash va yuborish
fonda. Platforma javobni kutib turmasligi kerak: talabgorning keyingi
bosishi sekinlashardi.

XAVFSIZLIK - to'rt qatlam, hammasi arzon:

  * faqat LOOPBACK (`127.0.0.1` va `::1`) - tarmoqdan ko'rinmaydi;
  * `Host` sarlavhasi loopback bo'lishi shart - DNS rebinding
    (begona sayt o'z domenini 127.0.0.1 ga yo'naltirib MAC'ni
    o'qishi) shu bilan yopiladi;
  * `Origin` - imtihondagi platforma domeni (`allowed_domains`, WebView
    allowlist'i bilan BIR XIL qoida) yoki `.env` ro'yxati. Origin'siz
    so'rov (brauzer emas) o'tadi - lokal jarayonni baribir to'xtatib
    bo'lmaydi;
  * tana 16 KB, `q_id` qat'iy belgilar to'plami (fayl nomiga boradi -
    `..\` kabi yo'l qismlari o'tmaydi), sekundiga 20 buyruq.

Bu KREDENSIAL EMAS: MAC va raqam maxfiy emas, skrinshot esa baribir
kuzatuv qismi. Maqsad - begona sahifa buyruq yubora olmasligi.

CHROMIUM TALABLARI: `https://` sahifadan `http://localhost` ga so'rov
"aralash kontent" hisoblanmaydi (loopback ishonchli), lekin CORS va
Private Network Access preflight'i (`Access-Control-Allow-Private-
Network`) kerak - ikkalasiga ham javob beriladi. `localhost` Chromium'da
avval `::1` ga uriladi, shuning uchun ikkala oila ham tinglanadi.

Qt'siz HTTP (`http.server`, fon thread'i): so'rovni qabul qilish UI
thread'iga bog'liq bo'lmasligi kerak - WebView og'ir sahifani chizayotgan
paytda ham `device_info` darhol javob beradi. UI bilan aloqa faqat
signal orqali (navbatli ulanish).
"""

from __future__ import annotations

import json
import logging
import re
import socket
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Iterable, Optional
from urllib.parse import parse_qsl, urlsplit

from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)

_MAX_BODY = 16 * 1024
_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]", "::1")

#: Savol ID'si: fayl nomiga ham, serverga ham boradi. Belgilar to'plami
#: backend bilan BIR XIL (`ScreenshotUploadSerializer.question_id`) va
#: Windows fayl nomi uchun xavfsiz (`\ / : * ? " < > |` yo'q).
QUESTION_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")
QUESTION_NUMBER_MAX = 100_000

#: Sekundiga ko'pi bilan shuncha skrinshot buyrug'i (sirpanuvchi oyna).
#: Odam bundan tez bosa olmaydi; chegara buzilgan yoki begona skript
#: diskni to'ldirishiga qarshi. Oshsa - 429 (platforma qayta urishi mumkin).
_MAX_CAPTURES_PER_SECOND = 20


class PayloadError(ValueError):
    """Buyruq tanasi yaroqsiz - 400, `code` platformaga qaytadi."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------
# Sof qoidalar (testda tekshiriladi)
# ---------------------------------------------------------------------
def origin_allowed(origin: str, *, extra: Iterable[str], exam_domains: Optional[list]) -> bool:
    """
    `Origin` ruxsat etilganmi.

    `exam_domains`:
      * `None` - imtihon ochiq emas: faqat `.env` ro'yxati;
      * `[]`   - imtihon ochiq, lekin serverda domen cheklovi yo'q
                 (WebView allowlist'i ham hech narsani to'smaydi) - hammasi;
      * ro'yxat - domen yoki uning subdomeni (`DomainAllowlistInterceptor`
                 bilan AYNAN bir xil qoida).
    """
    if not origin:
        return True
    origin = origin.strip().lower()
    extra = [item.strip().lower().rstrip("/") for item in extra if item]
    if "*" in extra or origin.rstrip("/") in extra:
        return True
    if exam_domains is None:
        return False
    if not exam_domains:
        return True
    host = (urlsplit(origin).hostname or "").lower()
    if not host:
        return False
    for domain in exam_domains:
        domain = (domain or "").lower().strip()
        if domain and (host == domain or host.endswith("." + domain)):
            return True
    return False


def host_allowed(host_header: str, port: int) -> bool:
    """`Host` sarlavhasi loopback manzilimi (DNS rebinding'ga qarshi)."""
    host = (host_header or "").strip().lower()
    if not host:
        return True  # HTTP/1.0 mijozi - brauzer emas
    for name in _LOOPBACK_HOSTS:
        if host in (name, f"{name}:{port}"):
            return True
    return False


def parse_capture_payload(body: bytes, content_type: str = "", query: str = "") -> dict:
    """
    `POST /api/capture_screen` tanasi -> `{"q_id": str, "q_n": int}` (yoki `{}`).

    Platforma `{"q_id": "1", "q_n": "3"}` yuboradi: "shu ID va raqamli
    savolga javob belgilandi". Qiymat satr ham, son ham bo'lishi mumkin -
    JavaScript'da ikkalasi odatiy. JSON bo'lmasa forma
    (`application/x-www-form-urlencoded`) yoki query satri ham qabul
    qilinadi: `navigator.sendBeacon` va oddiy `fetch(url + "?q_id=")`
    ham ishlashi kerak.

    Bo'sh tana - savolsiz buyruq (kadr umumiy nom bilan saqlanadi).
    `q_n` bo'lib `q_id` bo'lmasa - XATO: fayl va server yozuvi savol
    ID'si bo'yicha almashtiriladi, raqam esa savolni ajratmaydi (bitta
    raqam turli variantlarda boshqa savol bo'lishi mumkin).
    """
    raw = (body or b"").strip()
    fields: dict = {}
    if raw:
        text = raw.decode("utf-8", errors="strict") if isinstance(raw, bytes) else str(raw)
        if "json" in (content_type or "").lower() or text[:1] in "{[":
            try:
                data = json.loads(text)
            except ValueError:
                raise PayloadError("invalid_json", "Tana JSON emas")
            if not isinstance(data, dict):
                raise PayloadError("invalid_json", "Tana JSON obyekt bo'lishi kerak")
            fields = data
        else:
            fields = dict(parse_qsl(text, keep_blank_values=True))
    if not fields and query:
        fields = dict(parse_qsl(query, keep_blank_values=True))

    q_id = fields.get("q_id")
    q_n = fields.get("q_n")
    if q_id in (None, "") and q_n in (None, ""):
        return {}
    if q_id in (None, ""):
        raise PayloadError("q_id_required", "q_n bilan birga q_id ham yuborilishi kerak")
    if isinstance(q_id, bool) or not isinstance(q_id, (str, int)):
        raise PayloadError("invalid_q_id", "q_id satr yoki butun son bo'lishi kerak")
    q_id = str(q_id).strip()
    if not QUESTION_ID_RE.match(q_id):
        raise PayloadError(
            "invalid_q_id", "q_id: 1-64 belgi, faqat lotin harfi, raqam, '_', '-', '.'"
        )

    result = {"q_id": q_id}
    if q_n not in (None, ""):
        if isinstance(q_n, bool):
            raise PayloadError("invalid_q_n", "q_n musbat butun son bo'lishi kerak")
        if isinstance(q_n, float) and q_n.is_integer():
            q_n = int(q_n)
        text = str(q_n).strip()
        if not text.isdigit() or not 1 <= int(text) <= QUESTION_NUMBER_MAX:
            raise PayloadError("invalid_q_n", f"q_n 1..{QUESTION_NUMBER_MAX} oralig'idagi butun son bo'lishi kerak")
        result["q_n"] = int(text)
    return result


def device_payload(*, machine_uuid: str, ip: str, mac: str, number) -> dict:
    """Platforma kutgan shakl (modul izohidagi SHARTNOMA)."""
    return {
        "machine_uuid": machine_uuid or None,
        "ip": ip or None,
        "mac": (mac or "").replace("-", ":").lower() or None,
        "number": str(number) if number not in (None, "", 0) else None,
    }


# ---------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------
class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # Port boshqa jarayonda band bo'lsa XATO bo'lsin: Windows'da
    # `SO_REUSEADDR` ikkinchi jarayonga shu portni "o'g'irlash"ga
    # ruxsat beradi va so'rovlar tasodifiy jarayonga tushardi.
    allow_reuse_address = False

    def __init__(self, address, family, owner: "LocalDeviceService") -> None:
        self.address_family = family
        self.owner = owner
        super().__init__(address, _Handler)


class _Server6(_Server):
    address_family = socket.AF_INET6


class _Handler(BaseHTTPRequestHandler):
    server_version = "ProctoringLocal/1.0"
    # HTTP/1.0 - har so'rovdan keyin ulanish yopiladi: xato javobida
    # o'qilmagan tana keyingi so'rovni buzmaydi, lokal ulanish esa arzon.
    protocol_version = "HTTP/1.0"

    # --- javob yordamchilari -------------------------------------------
    def _cors_headers(self) -> None:
        origin = self.headers.get("Origin")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _guard(self) -> bool:
        """Host va Origin tekshiruvi. `False` - javob allaqachon yuborilgan."""
        owner: LocalDeviceService = self.server.owner
        if not host_allowed(self.headers.get("Host", ""), owner.port):
            self._json(403, {"ok": False, "error": "bad_host"})
            return False
        if not owner.origin_allowed(self.headers.get("Origin", "")):
            log.warning("Lokal xizmat: begona Origin rad etildi: %s", self.headers.get("Origin"))
            self._json(403, {"ok": False, "error": "origin_not_allowed"})
            return False
        return True

    # --- metodlar --------------------------------------------------------
    def do_OPTIONS(self) -> None:  # noqa: N802 - http.server nomlash qoidasi
        if not self._guard():
            return
        self.send_response(204)
        self._cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            self.headers.get("Access-Control-Request-Headers") or "Content-Type",
        )
        # Private Network Access: ommaviy sahifadan loopback'ga so'rov.
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if not self._guard():
            return
        if self.path.split("?", 1)[0].rstrip("/") == "/api/device_info":
            try:
                self._json(200, self.server.owner.device_info())
            except Exception:
                log.exception("device_info yig'ilmadi")
                self._json(500, {"ok": False, "error": "internal"})
            return
        self._json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._guard():
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > _MAX_BODY:
            self._json(413, {"ok": False, "error": "body_too_large"})
            return
        body = self.rfile.read(length) if length else b""
        path, _, query = self.path.partition("?")
        if path.rstrip("/") != "/api/capture_screen":
            self._json(404, {"ok": False, "error": "not_found"})
            return
        try:
            question = parse_capture_payload(
                body, self.headers.get("Content-Type", ""), query
            )
        except (PayloadError, UnicodeDecodeError) as exc:
            code = getattr(exc, "code", "invalid_body")
            message = getattr(exc, "message", "Tana UTF-8 emas")
            log.warning("Lokal xizmat: yaroqsiz buyruq (%s): %s", code, message)
            self._json(400, {"ok": False, "error": code, "message": message})
            return

        status = self.server.owner.request_capture(question)
        if status == "accepted":
            self._json(202, {"ok": True, "accepted": True, **question})
        elif status == "throttled":
            self._json(429, {"ok": False, "error": "too_many_requests"})
        else:
            self._json(409, {
                "ok": False, "error": "no_active_exam",
                "message": "Imtihon ochiq emas yoki dalil yig'ish vaqti tugagan",
            })

    def log_message(self, fmt, *args) -> None:
        # Standart yozuv stderr'ga - frozen GUI dasturda u yo'q. Har
        # javob belgilanishi log faylini ham to'ldirmasligi kerak.
        log.debug("Lokal xizmat: " + fmt, *args)


# ---------------------------------------------------------------------
# Xizmat
# ---------------------------------------------------------------------
class LocalDeviceService(QObject):
    """
    Dastur ishga tushganda ochiladi va chiqishda yopiladi.

    `device_info` imtihondan TASHQARIDA ham javob beradi (platforma uni
    sahifa yuklanishi bilan so'rashi mumkin); `capture_screen` esa faqat
    imtihon sahifasi `set_capture_target(True, ...)` qilganda.
    """

    #: HTTP thread'idan chiqariladi, UI thread'ida qabul qilinadi
    #: (navbatli ulanish - Qt emitter thread'ini o'zi aniqlaydi).
    #: Argument - `parse_capture_payload` natijasi (`{}` yoki savol).
    capture_requested = pyqtSignal(object)

    def __init__(self, info_provider: Callable[[], dict], *, port: int,
                 extra_origins: Iterable[str] = (), parent=None) -> None:
        super().__init__(parent)
        self._info_provider = info_provider
        self.port = port
        self._extra_origins = list(extra_origins)
        self._lock = threading.Lock()
        self._capture_enabled = False
        #: `None` - imtihon ochiq emas (`origin_allowed` izohi).
        self._exam_domains: Optional[list] = None
        self._servers: list = []
        self._recent: deque = deque()

    # ------------------------------------------------------------------
    def start(self) -> bool:
        """
        Tinglashni boshlaydi. Port band bo'lsa dastur TO'XTAMAYDI - faqat
        ERROR: imtihon oqimi xizmatsiz ham ishlaydi, faqat skrinshot
        olinmaydi va buni log aytadi.
        """
        for family, cls, host in (
            (socket.AF_INET, _Server, "127.0.0.1"),
            (socket.AF_INET6, _Server6, "::1"),
        ):
            try:
                server = cls((host, self.port), family, self)
            except OSError as exc:
                level = logging.ERROR if family == socket.AF_INET else logging.INFO
                log.log(level, "Lokal xizmat %s:%s da ochilmadi: %s", host, self.port, exc)
                continue
            thread = threading.Thread(
                target=server.serve_forever, name=f"local-service-{host}", daemon=True
            )
            thread.start()
            self._servers.append(server)
        if self._servers:
            log.info("Lokal xizmat: http://localhost:%s/api/device_info", self.port)
        return bool(self._servers)

    def stop(self) -> None:
        for server in self._servers:
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                log.debug("Lokal xizmat yopilmadi", exc_info=True)
        self._servers.clear()

    @property
    def is_running(self) -> bool:
        return bool(self._servers)

    # ------------------------------------------------------------------
    def set_capture_target(self, enabled: bool, exam_domains: Optional[list] = None) -> None:
        """Imtihon sahifasi chaqiradi (UI thread)."""
        with self._lock:
            self._capture_enabled = bool(enabled)
            self._exam_domains = list(exam_domains) if enabled and exam_domains is not None else None
        log.info("Lokal xizmat: skrinshot buyrug'i %s", "qabul qilinadi" if enabled else "o'chirildi")

    # --- HTTP thread'idan ----------------------------------------------
    def origin_allowed(self, origin: str) -> bool:
        with self._lock:
            domains = self._exam_domains
        return origin_allowed(origin, extra=self._extra_origins, exam_domains=domains)

    def request_capture(self, question: Optional[dict] = None) -> str:
        """`accepted` / `throttled` / `disabled` (HTTP thread'idan)."""
        now = time.monotonic()
        with self._lock:
            if not self._capture_enabled:
                return "disabled"
            while self._recent and now - self._recent[0] > 1.0:
                self._recent.popleft()
            if len(self._recent) >= _MAX_CAPTURES_PER_SECOND:
                return "throttled"
            self._recent.append(now)
        self.capture_requested.emit(dict(question or {}))
        return "accepted"

    def device_info(self) -> dict:
        return self._info_provider()
