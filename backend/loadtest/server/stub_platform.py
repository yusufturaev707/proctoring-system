"""
Tashqi test platformasining STUB'i (`Exam.site_url`).

    python stub_platform.py --port 8099 --latency-ms 150 --jitter-ms 100 --error-rate 0

`integrations/exam_site.py:check_candidate` kutadigan javobni qaytaradi:
`GET <site_url>?imie=<jshshir>` -> `{"status": 1, "data": {...}}`
(`image_base64` bilan — hujjat surati platformadan keladi va
`candidate/lookup/` javobiga qo'shiladi, ya'ni javob hajmi haqiqiy).

NIMA UCHUN KECHIKISH SOZLANADI: JSHSHIR tekshiruvi SINXRON — gunicorn
thread'i platforma javobini kutib turadi. Sinov kuni platforma ham
yuklama ostida bo'ladi va uning kechikishi bizning login bo'ronimizdagi
thread bandligini to'g'ridan-to'g'ri ko'paytiradi. Stub bilan
kechikishni (masalan 150 ms, 1 s, 5 s) ataylab o'zgartirib, chegarani
topish mumkin. `--error-rate` 5xx ulushi (circuit breaker'ni sinash).

Staging'da bu stub ALOHIDA mashinada (yoki yuklama generatorida)
ishlaydi; production platformasiga sinov so'rovi YUBORILMAYDI.

Faqat standart kutubxona + Pillow (`payloads.py` orqali).
"""

from __future__ import annotations

import argparse
import base64
import json
import random
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from payloads import passport_jpeg  # noqa: E402

_STATS = {"requests": 0, "errors": 0}
_LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    config: argparse.Namespace
    photo: str = ""

    def log_message(self, fmt, *args):  # jim — o'lchovni buzmasin
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/stats":
            return self._send(200, dict(_STATS))
        pinfl = (parse_qs(parsed.query).get("imie") or [""])[0]
        cfg = self.config
        delay = max(0.0, random.gauss(cfg.latency_ms, cfg.jitter_ms)) / 1000.0
        time.sleep(delay)
        with _LOCK:
            _STATS["requests"] += 1
        if cfg.error_rate and random.random() < cfg.error_rate:
            with _LOCK:
                _STATS["errors"] += 1
            return self._send(503, {"status": 0, "message": "stub: unavailable"})
        if not pinfl.startswith("99999"):
            # Sintetik bo'lmagan JSHSHIR — hech qachon "topilmaydi".
            return self._send(200, {"status": 0, "message": "Not found"})
        index = pinfl[-4:]
        return self._send(200, {
            "status": 1,
            "message": "Success",
            "data": {
                "id": int(pinfl[-9:]),
                "abitur_id": int(pinfl[-9:]) + 100000,
                "imie": pinfl,
                "is_finished": 0,
                "image_base64": "data:image/jpeg;base64," + self.photo,
                "lname": "Nomzod",
                "fname": "Test",
                "mname": index,
                "duration_time": 180,
                "test_link": f"https://test-platform.invalid/login?token=lt-{pinfl}",
                "message": "Testga ruxsat! (stub)",
                "status": True,
            },
        })

    def do_POST(self):
        """ntest `report_result` (`POST /api/v1/exam/session-result`) — qabul qilinadi."""
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        time.sleep(max(0.0, random.gauss(self.config.latency_ms, self.config.jitter_ms)) / 1000.0)
        with _LOCK:
            _STATS["results"] = _STATS.get("results", 0) + 1
        return self._send(200, {"status": 1, "message": "accepted (stub)"})

    def _send(self, status: int, body: dict) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--latency-ms", type=float, default=150.0)
    parser.add_argument("--jitter-ms", type=float, default=50.0)
    parser.add_argument("--error-rate", type=float, default=0.0)
    args = parser.parse_args()

    Handler.config = args
    Handler.photo = base64.b64encode(passport_jpeg(0)).decode("ascii")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    print(f"stub platforma: http://{args.host}:{args.port}/api/check?imie=... "
          f"(kechikish {args.latency_ms}±{args.jitter_ms} ms, xato {args.error_rate:.1%})",
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
