"""
IP kamera holati - RTSP `DESCRIBE` orqali (yangi bog'liqliksiz).

NIMA UCHUN FAQAT TCP ULANISH YETMAYDI. 554-port ochiq bo'lishi
"kamera ishlayapti" degani emas: login/parol noto'g'ri yoki oqim
yo'li (`rtsp_path`) boshqa bo'lsa, port javob beradi, client esa
imtihon kuni "oqim ochilmadi" bilan qoladi. `DESCRIBE` aynan client
so'raydigan oqimni, aynan o'sha kredensial bilan so'raydi - ya'ni
"online" javobi "client ham ulanadi" degani.

UCH NATIJA va ular administrator uchun uch xil ish:

    online   kamera javob berdi, oqim bor           -> hech narsa
    error    kamera javob berdi, lekin rad etdi     -> login/parol yoki yo'lni tuzatish
    offline  umuman javob yo'q                      -> tarmoq, quvvat, IP

Kadr DEKODLANMAYDI - bu yengil tekshiruv (bitta so'rov, ~50 ms) va
u har daqiqada barcha kameralar uchun ishlaydi. Tasvirni ko'rish
alohida (`camera_live.py`).

SERVER NUQTAI NAZARIDAN. Natija "server kameraga yetib boradimi?"
degan savolga javob beradi. Server bino tarmog'idan tashqarida
(markazlashgan o'rnatish, NAT) bo'lsa, ishlab turgan kamera ham
"offline" ko'rinadi - bu holatda tekshiruvni o'chirish kerak
(`CAMERA_PROBE_ENABLED=false`).
"""

from __future__ import annotations

import base64
import hashlib
import re
import socket
import time
from dataclasses import dataclass

ONLINE = "online"
OFFLINE = "offline"
ERROR = "error"

_USER_AGENT = "ProctoringServer/1.0"
_MAX_RESPONSE = 16 * 1024


@dataclass
class ProbeResult:
    status: str
    message: str = ""
    latency_ms: int = 0


def probe(*, host: str, port: int, path: str, login: str = "", password: str = "",
          timeout: float = 3.0) -> ProbeResult:
    """
    Kameraga `DESCRIBE` yuboradi va natijani uch holatdan biriga keltiradi.

    Istisno TASHLAMAYDI: tekshiruv davriy vazifada yuzlab kamera uchun
    ishlaydi va bitta nostandart javob butun siklni to'xtatmasligi kerak.
    """
    path = path if path.startswith("/") else "/" + (path or "")
    url = "rtsp://{}:{}{}".format(host, port, path)
    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout) as conn:
            conn.settimeout(timeout)
            status, headers = _request(conn, url, cseq=1, auth="")
            if status == 401 and login:
                auth = _authorization(headers.get("www-authenticate", ""), login, password, url)
                if auth:
                    status, headers = _request(conn, url, cseq=2, auth=auth)
    except (socket.timeout, TimeoutError):
        return ProbeResult(OFFLINE, "Javob yo'q ({} s)".format(int(timeout)))
    except ConnectionRefusedError:
        return ProbeResult(OFFLINE, "Port {} yopiq".format(port))
    except OSError as exc:
        return ProbeResult(OFFLINE, "Tarmoq xatosi: {}".format(_short(exc)))
    except ValueError as exc:
        return ProbeResult(ERROR, "Kamera javobi tushunarsiz: {}".format(_short(exc)))

    latency = int((time.monotonic() - started) * 1000)
    if status == 200:
        return ProbeResult(ONLINE, "", latency)
    if status == 401:
        return ProbeResult(
            ERROR,
            "Login yoki parol noto'g'ri" if login else "Kamera login/parol talab qiladi",
            latency,
        )
    if status == 404:
        return ProbeResult(ERROR, "RTSP yo'li topilmadi: {}".format(path), latency)
    if status == 403:
        return ProbeResult(ERROR, "Kirish taqiqlangan (hisobda ko'rish huquqi yo'q)", latency)
    return ProbeResult(ERROR, "Kamera {} javob berdi".format(status), latency)


# --------------------------------------------------------------------------
def _request(conn: socket.socket, url: str, *, cseq: int, auth: str):
    lines = [
        "DESCRIBE {} RTSP/1.0".format(url),
        "CSeq: {}".format(cseq),
        "Accept: application/sdp",
        "User-Agent: {}".format(_USER_AGENT),
    ]
    if auth:
        lines.append("Authorization: {}".format(auth))
    conn.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("utf-8"))
    return _read_response(conn)


def _read_response(conn: socket.socket):
    """Faqat sarlavhalar o'qiladi - SDP tanasi bizga kerak emas."""
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(4096)
        if not chunk:
            break
        data += chunk
        if len(data) > _MAX_RESPONSE:
            raise ValueError("javob juda katta")
    head = data.split(b"\r\n\r\n", 1)[0].decode("latin-1")
    lines = head.split("\r\n")
    match = re.match(r"RTSP/\d\.\d\s+(\d{3})", lines[0] if lines else "")
    if not match:
        raise ValueError(lines[0][:60] if lines and lines[0] else "bo'sh javob")
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            # Bir nechta `WWW-Authenticate` bo'lishi mumkin (Basic +
            # Digest). Digest afzal - u parolni ochiq yubormaydi.
            key = key.strip().lower()
            value = value.strip()
            if key == "www-authenticate" and key in headers:
                if value.lower().startswith("digest"):
                    headers[key] = value
                continue
            headers[key] = value
    return int(match.group(1)), headers


def _authorization(challenge: str, login: str, password: str, url: str) -> str:
    scheme = challenge.split(" ", 1)[0].lower()
    if scheme == "basic":
        token = base64.b64encode("{}:{}".format(login, password).encode("utf-8")).decode("ascii")
        return "Basic " + token
    if scheme != "digest":
        return ""
    params = dict(re.findall(r'(\w+)="?([^",]*)"?', challenge))
    realm, nonce = params.get("realm", ""), params.get("nonce", "")
    ha1 = hashlib.md5("{}:{}:{}".format(login, realm, password).encode("utf-8")).hexdigest()
    ha2 = hashlib.md5("DESCRIBE:{}".format(url).encode("utf-8")).hexdigest()
    response = hashlib.md5("{}:{}:{}".format(ha1, nonce, ha2).encode("utf-8")).hexdigest()
    return (
        'Digest username="{}", realm="{}", nonce="{}", uri="{}", response="{}"'
        .format(login, realm, nonce, url, response)
    )


def _short(exc: Exception) -> str:
    text = str(exc) or exc.__class__.__name__
    return text[:120]
