"""
Proktor bilan real vaqtdagi kanal (WebSocket).

NIMA UCHUN KERAK: proktor talabgorni ogohlantirishi, sessiyani
to'xtatishi yoki texnik muammodan keyin davom ettirishi mumkin. HTTP
heartbeat bu buyruqlarni faqat `should_stop` bayrog'i orqali va faqat
keyingi tsiklda (standart 30 s) yetkazadi - ogohlantirish uchun bu
umuman yaramaydi: proktor "telefoningizni oling" deb yozganda talabgor
uni yarim daqiqadan keyin ko'rsa, chora ma'nosini yo'qotadi.

MAS'ULIYAT BO'LINISHI - bu modul HTTP heartbeat'ni almashtirmaydi:

    WebSocket  - TEZLIK qatlami. Buyruqlar darhol yetadi.
    Heartbeat  - KAFOLAT qatlami. WS uzilgan bo'lsa ham sessiya
                 yakunlangani `should_stop` orqali baribir bilinadi.

Shuning uchun WS uzilishi imtihonni to'xtatmaydi va operatorga
ko'rsatilmaydi ham: u fon rejimida qayta ulanadi. Ikkalasi ham
ishlamasa - sessiya `close_stale_sessions` bilan serverda yopiladi.

Heartbeat ATAYLAB WS orqali yuborilmaydi (backend `ClientConsumer` uni
qo'llab-quvvatlasa ham): HTTP javobi `status`, `risk_score` va
`should_stop` ni qaytaradi, ya'ni u nafaqat "tirikman" deydi, balki
serverning qarorini ham olib keladi. Ikkala kanaldan yuborish esa
faqat takrorlash bo'lardi.

TOKEN HEADER'DA, URL'da emas. Brauzer WebSocket API'si header
qo'shishga imkon bermaydi va admin panel shu sababli tokenni query
parametrida yuboradi (`MonitorConsumer`). Qt'ning `QWebSocket` i esa
imkon beradi, demak bu yerda o'sha kelishuvga borishning hojati yo'q:
URL'dagi opaque sessiya tokeni nginx access log'ida qoladi.
"""

from __future__ import annotations

import functools
import json
import logging
import random
import time
from typing import Optional
from urllib.parse import urlparse, urlunparse

from PyQt6.QtCore import QByteArray, QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtNetwork import QNetworkRequest
from PyQt6.QtWebSockets import QWebSocket

from config import API_BASE_URL, WS_BASE_URL
from services import net_policy
from services.network_status import on_power_resumed

log = logging.getLogger(__name__)

#: Qayta ulanish kechikishi (soniya): 1 -> 2 -> 4 ... chegara 60,
#: JITTER bilan (`net_policy.backoff_delay`).
#:
#: Eksponensial: server qayta ishga tushganda minglab client bir vaqtda
#: urilsa, u yana yiqiladi. Jitter esa SHART: hamma bir lahzada uzilgan
#: (server restart) va jitter'siz jadval bir xil bo'lgani uchun ular
#: har to'lqinda yana bir lahzada qaytib kelardi. Kanal ixtiyoriy
#: tezlik qatlami — kafolat heartbeat'da — shuning uchun chegara uzun.
_BACKOFF_BASE_S = 1.0
_BACKOFF_CAP_S = 60.0

#: Ulanish shuncha turgach "barqaror" hisoblanadi va backoff nolga tushadi.
_STABLE_CONNECTION_S = 10.0

#: Uyg'ongandan keyin qayta ulanish shu oraliqda, tasodifiy paytda (ms).
_RESUME_JITTER_MS = 3_000

#: Ulanishni tirik ushlab turish uchun ping oralig'i (ms).
#:
#: nginx `proxy_read_timeout` standarti 60 s: bo'sh kanal shundan keyin
#: uziladi va client buni faqat buyruq kelmaganda sezardi.
_PING_INTERVAL_MS = 25_000


#: Dev tartibi (`CLAUDE.md` -> Buyruqlar): `runserver` 8000 da, WebSocket
#: esa ALOHIDA jarayonda (`uvicorn ... --port 8001`).
_DEV_API_PORT = 8000
_DEV_WS_PORT = 8001
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


# Keshlanadi: har qayta ulanishda chaqiriladi va dev ogohlantirishi
# log'ni to'ldirmasligi kerak.
@functools.lru_cache(maxsize=1)
def default_ws_url() -> str:
    """
    `.env` da `WS_BASE_URL` berilmagan bo'lsa - API manzilidan chiqariladi.

    Production'da nginx HTTP va WebSocket'ni bitta host ostida beradi va
    manzil shunchaki sxemasi almashtirilgan API manzili.

    DEV ISTISNOSI: loopback + 8000-port — bu `runserver`, WebSocket esa
    8001 da. Ilgari port ham ko'chirilardi va client `ws://...:8000` ga
    urilardi: `runserver` WebSocket'ni bilmaydi va 404 qaytaradi
    ("GET /ws/client/ 404"), kanal esa hech qachon ochilmasdi — proktor
    ogohlantirishi va chetlashtirish buyrug'i clientga YETMASDI, holbuki
    boshqa hamma narsa ishlab turgandek ko'rinardi. Aniq tartibni tanib
    to'g'ri portni olamiz va buni log'da ochiq aytamiz.
    """
    parsed = urlparse(API_BASE_URL)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    netloc = parsed.netloc
    if (parsed.hostname or "") in _LOOPBACK and parsed.port == _DEV_API_PORT:
        host = parsed.hostname if ":" not in (parsed.hostname or "") else "[{}]".format(parsed.hostname)
        netloc = "{}:{}".format(host, _DEV_WS_PORT)
        log.warning(
            "WS_BASE_URL berilmagan - dev tartibi taxmin qilindi: %s://%s "
            "(runserver %s, uvicorn %s). Aniq qiymatni .env da bering.",
            scheme, netloc, _DEV_API_PORT, _DEV_WS_PORT,
        )
    return urlunparse((scheme, netloc, "", "", "", ""))


class ProctorChannel(QObject):
    """
    Sessiya davomida ochiq turadigan buyruq kanali.

    `start(token)` sessiya tokeni olinganidan keyin chaqiriladi,
    `stop()` esa sessiya yakunlanganda.
    """

    #: Ulanish holati - faqat diagnostika va nishon uchun.
    online = pyqtSignal(bool)
    #: Proktor ogohlantirishi: (matn, jiddiylik).
    warning = pyqtSignal(str, int)
    #: Proktor sessiyani to'xtatdi: (sabab).
    terminated = pyqtSignal(str)
    #: Texnik muammodan keyin davom ettirish: (qo'shimcha daqiqa).
    resumed = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._socket: Optional[QWebSocket] = None
        self._token = ""
        self._active = False
        self._attempt = 0
        self._connected = False
        self._connected_at = 0.0

        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._open)

        self._ping_timer = QTimer(self)
        self._ping_timer.setInterval(_PING_INTERVAL_MS)
        self._ping_timer.timeout.connect(self._send_ping)

        on_power_resumed(self._on_power_resumed)

    # ------------------------------------------------------------------
    @property
    def is_online(self) -> bool:
        return self._connected

    def start(self, token: str) -> None:
        if not token:
            log.warning("Sessiya tokeni yo'q - WebSocket ochilmadi")
            return
        if self._active:
            return
        self._token = token
        self._active = True
        self._attempt = 0
        self._open()

    def stop(self) -> None:
        """
        Kanalni yopadi.

        `_active = False` BIRINCHI qo'yiladi: aks holda `close()` dan
        keladigan `disconnected` signali qayta ulanishni boshlab
        yuboradi va sessiya tugagandan keyin ham kanal tirilib turadi.
        """
        self._active = False
        self._retry_timer.stop()
        self._ping_timer.stop()
        self._teardown()
        if self._connected:
            self._connected = False
            self.online.emit(False)

    # ------------------------------------------------------------------
    def _open(self) -> None:
        if not self._active:
            return
        self._teardown()

        base = (WS_BASE_URL or default_ws_url()).rstrip("/")
        request = QNetworkRequest(QUrl("{}/ws/client/".format(base)))
        # Token AYNAN shu yerda header'da ketadi. Backend
        # `ClientConsumer` avval header'ni, keyin query parametrini
        # o'qiydi - eski client'lar bilan mos qoladi.
        request.setRawHeader(
            QByteArray(b"X-Proctoring-Session"),
            QByteArray(self._token.encode("ascii", "ignore")),
        )

        socket = QWebSocket()
        socket.connected.connect(self._on_connected)
        socket.disconnected.connect(self._on_disconnected)
        socket.textMessageReceived.connect(self._on_message)
        socket.errorOccurred.connect(self._on_error)
        self._socket = socket

        log.info("WebSocket ulanmoqda: %s/ws/client/", base)
        socket.open(request)

    def _teardown(self) -> None:
        socket, self._socket = self._socket, None
        if socket is None:
            return
        try:
            # Signal uzilmasa, `deleteLater` dan keyin ham `disconnected`
            # kelib qayta ulanishni qo'zg'atishi mumkin.
            socket.disconnected.disconnect()
        except TypeError:
            pass
        try:
            socket.close()
        except Exception:
            log.debug("WebSocket yopishda xato", exc_info=True)
        socket.deleteLater()

    def _schedule_retry(self) -> None:
        if not self._active or self._retry_timer.isActive():
            # `errorOccurred` va `disconnected` ikkalasi kelishi mumkin —
            # ikkinchisi jadvalni qayta boshlab, kutishni uzaytirmasin.
            return
        delay = net_policy.backoff_delay(
            self._attempt, base=_BACKOFF_BASE_S, cap=_BACKOFF_CAP_S
        )
        self._attempt += 1
        log.info("WebSocket qayta ulanish %.1f s dan keyin", delay)
        self._retry_timer.start(int(delay * 1000))

    def _on_power_resumed(self) -> None:
        """
        Uyqudan keyin kanal o'lik (TCP uzilgan, lekin Qt buni hali
        bilmaydi) — backoff'ni kutmay, jitter bilan qayta ulanamiz.
        """
        if not self._active:
            return
        self._attempt = 0
        self._retry_timer.stop()
        self._retry_timer.start(random.randint(0, _RESUME_JITTER_MS))

    # ------------------------------------------------------------------
    def _on_connected(self) -> None:
        # `_attempt` bu yerda NOLGA TUSHIRILMAYDI: server ulanishni qabul
        # qilib darhol yopsa (token bekor), nol har safar 1 s lik siklga
        # olib kelardi. Nol — faqat ulanish barqaror turgach
        # (`_on_disconnected`).
        self._connected_at = time.monotonic()
        self._connected = True
        self._ping_timer.start()
        self.online.emit(True)
        log.info("WebSocket ulandi")

    def _on_disconnected(self) -> None:
        self._ping_timer.stop()
        if self._connected and time.monotonic() - self._connected_at >= _STABLE_CONNECTION_S:
            self._attempt = 0
        if self._connected:
            self._connected = False
            self.online.emit(False)
        self._schedule_retry()

    def _on_error(self, error) -> None:
        # Xato EKRANDA KO'RSATILMAYDI: kanal ixtiyoriy tezlik qatlami va
        # uning uzilishi operator uchun harakat talab qilmaydi. Log'da esa
        # SABAB bilan qoladi — ilgari faqat enum kodi yozilardi va 404
        # ("manzil HTTP API'ga qaragan") oddiy tarmoq uzilishidan farq
        # qilmasdi.
        detail = self._socket.errorString() if self._socket is not None else ""
        if "404" in detail or "Not Found" in detail:
            log.error(
                "WebSocket manzili WebSocket server emas (404): %s. "
                "WS_BASE_URL ni tekshiring - dev'da ws://127.0.0.1:8001",
                detail,
            )
            return
        log.info("WebSocket xatosi: %s (%s)", error, detail)

    def _send_ping(self) -> None:
        if self._socket is None or not self._connected:
            return
        try:
            self._socket.sendTextMessage(json.dumps({"action": "ping"}))
        except Exception:
            log.debug("WebSocket ping yuborilmadi", exc_info=True)

    def _on_message(self, raw: str) -> None:
        # Slot ichidagi istisno Qt hodisa siklida — imtihon oynasida
        # hech qachon chiqib ketmasligi kerak (serverdan kelgan buzilgan
        # xabar dasturni yiqitmasin).
        try:
            self._handle_message(raw)
        except Exception:
            log.exception("WebSocket xabarini qayta ishlashda xato")

    def _handle_message(self, raw: str) -> None:
        try:
            message = json.loads(raw)
        except (TypeError, ValueError):
            log.warning("WebSocket: JSON bo'lmagan xabar")
            return
        if not isinstance(message, dict):
            return

        kind = message.get("type")
        if kind in ("connected", "pong", "heartbeat_ack"):
            return
        if kind != "command":
            log.debug("WebSocket: noma'lum xabar turi %r", kind)
            return

        payload = message.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        command = str(payload.get("command") or "")

        if command == "warning":
            try:
                severity = int(payload.get("severity") or 2)
            except (TypeError, ValueError):
                severity = 2
            self.warning.emit(
                str(payload.get("message") or "Proktor ogohlantirdi"),
                severity,
            )
        elif command == "terminate":
            self.terminated.emit(str(payload.get("reason") or ""))
        elif command == "resume":
            try:
                minutes = int(payload.get("overtime_minutes") or 0)
            except (TypeError, ValueError):
                minutes = 0
            self.resumed.emit(minutes)
        else:
            # Noma'lum buyruq - eski client, yangi server. Jimgina
            # tashlab yuborilmaydi: bu ikkala tomon versiyasi ajralib
            # ketganining yagona belgisi.
            log.warning("WebSocket: noma'lum buyruq %r", command)
