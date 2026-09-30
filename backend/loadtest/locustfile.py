"""
Proctoring backend yuklama sinovi (Locust).

    cd backend/loadtest
    .venv\\Scripts\\locust -f locustfile.py --host http://127.0.0.1:8012 \\
        --lt-manifest results/manifest.json --lt-scenario stages ...

Har `ExamClient` = bitta imtihon kompyuteri (operator + talabgor), client
kodi (`client/services/*`, `client/ui/pages/*`) bilan AYNAN bir xil
ketma-ketlik va chastotada:

    preflight -> access-attempt -> auth/login -> handshake -> presence ->
    camera/config -> camera/check -> exam/config -> candidate/lookup ->
    [face/attempt] -> face/verify -> identity/confirm -> exam/access ->
    proctoring/start -> (ws/client) ->
    BARQAROR HOLAT: heartbeat 30 s, presence 45 s, events 5 s (bo'sh
    bo'lsa yuborilmaydi), savol kadri (imtihon / savollar), davriy
    FaceID xatosi (10 s da bir tekshiruv, faqat mos kelmaganda),
    JWT refresh (30 daq, 401 da) ->
    recordings -> session/finish (completed=True)

`PanelUser` — proktor: dashboard (15 s), jonli kuzatuv (10 s), sessiya
tafsiloti (10 s), ro'yxatlar (30 s) + `ws/monitor/`.

Stsenariylar (`--lt-scenario`): `stages` (500→1000→2500→5000→7500),
`storm` (login bo'roni), `steady`, `finish` (hamma birga yakunlaydi),
`reconnect` (tarmoq uzilishi va qayta ulanish bo'roni). Parametrlar —
pastdagi `init_command_line_parser` va README.md.

Qurilma/IP/mashina tekshiruvlari HAQIQIY: manifestdagi `machine_uuid`,
tasdiqlangan `DeviceToken`, bron qilingan JSHSHIR va binoning NAT IP'si
(`X-Real-IP`, staging'dagi nginx `realip` orqali — README).
"""

from __future__ import annotations

import json
import os
import random
import sys
import threading
import time
import uuid
from itertools import count
from pathlib import Path

import gevent
from locust import FastHttpUser, HttpUser, LoadTestShape, between, events, task
from locust.exception import StopUser

sys.path.insert(0, str(Path(__file__).resolve().parent))
import payloads  # noqa: E402

API = "/api/v1"

#: HTTP mijozi. Staging: `fast` (geventhttpclient, yadro boshiga ~5-10x ko'p
#: so'rov). Lokal Django `runserver` geventhttpclient bilan GET javoblarida
#: ulanishni uzadi (status 0, `Broken pipe`) — lokalda `LT_HTTP_CLIENT=requests`.
BaseHttpUser = HttpUser if os.getenv("LT_HTTP_CLIENT", "fast") == "requests" else FastHttpUser

# --------------------------------------------------------------------------
# Parametrlar
# --------------------------------------------------------------------------
@events.init_command_line_parser.add_listener
def _(parser):
    g = parser.add_argument_group("LT (proctoring)")
    g.add_argument("--lt-manifest", default="results/manifest.json", help="seed_loadtest manifesti")
    g.add_argument("--lt-scenario", default="stages",
                   choices=["stages", "storm", "steady", "finish", "reconnect"])
    g.add_argument("--lt-stages", default="500,1000,2500,5000,7500", help="Bosqichlar (stages)")
    g.add_argument("--lt-stage-minutes", type=float, default=15.0, help="Har bosqichni ushlab turish")
    g.add_argument("--lt-spawn-rate", type=float, default=20.0,
                   help="Yangi client/s (= login tezligi) bosqichlar orasida")
    g.add_argument("--lt-storm-users", type=int, default=5000)
    g.add_argument("--lt-storm-seconds", type=float, default=300.0,
                   help="Login bo'roni oynasi (60..300 s)")
    g.add_argument("--lt-hold-minutes", type=float, default=15.0,
                   help="storm/steady/finish/reconnect: barqaror holat davomiyligi")
    g.add_argument("--lt-exam-minutes", type=float, default=180.0,
                   help="Imtihon davomiyligi (skrinshot oralig'i = shu / savollar)")
    g.add_argument("--lt-questions", type=int, default=100)
    g.add_argument("--lt-reanswer-rate", type=float, default=0.10,
                   help="Savolga qayta javob ulushi (kadr almashtiriladi)")
    g.add_argument("--lt-think-scale", type=float, default=1.0,
                   help="Operator harakatlari orasidagi pauza koeffitsienti (0 = pauzasiz)")
    g.add_argument("--lt-face-attempt-rate", type=float, default=0.2,
                   help="Kirishda kamida bitta muvaffaqiyatsiz urinish ulushi")
    g.add_argument("--lt-periodic-fail-rate", type=float, default=0.02,
                   help="Davriy FaceID tekshiruvining mos kelmaslik ehtimoli (har 10 s)")
    g.add_argument("--lt-event-flush-rate", type=float, default=0.2,
                   help="5 s oynada kamida bitta hodisa bo'lish ehtimoli")
    g.add_argument("--lt-event-batch-mean", type=float, default=3.0,
                   help="Bo'sh bo'lmagan batch'dagi o'rtacha hodisa soni")
    g.add_argument("--lt-ws", type=int, default=1, help="ws/client ulanishi (1/0)")
    g.add_argument("--lt-ws-host", default="", help="WS manzili (standart: host, port+1)")
    g.add_argument("--lt-real-ip", type=int, default=1,
                   help="X-Real-IP = bino NAT IP (staging nginx realip / lokal TRUSTED_PROXY_COUNT=1)")
    g.add_argument("--lt-finish-at-minutes", type=float, default=0.0,
                   help="finish: sinov boshidan shuncha daqiqada HAMMA yakunlaydi")
    g.add_argument("--lt-finish-jitter-s", type=float, default=60.0)
    g.add_argument("--lt-outage-at-minutes", type=float, default=5.0, help="reconnect: uzilish vaqti")
    g.add_argument("--lt-outage-seconds", type=float, default=60.0)
    g.add_argument("--lt-reconnect-jitter", type=int, default=0,
                   help="reconnect: 1 — client backoff'iga tasodifiy jitter (tavsiya), 0 — hozirgi client")
    g.add_argument("--lt-user-offset", type=int, default=0, help="Manifestdagi boshlang'ich indeks")
    g.add_argument("--lt-worker-stride", type=int, default=1,
                   help="Taqsimlangan rejim: worker soni (indekslar to'qnashmasin)")
    g.add_argument("--lt-proctors", type=int, default=20, help="PanelUser soni (fixed)")
    g.add_argument("--lt-conn-close", type=int, default=0,
                   help="1 — har so'rovda `Connection: close` (FAQAT lokal runserver uchun: "
                        "u keep-alive'ni geventhttpclient bilan barqaror ushlamaydi). Staging'da 0.")


_MANIFEST: dict = {}
_COUNTER = count()
_LOCK = threading.Lock()
TEST_STARTED = time.time()


@events.test_start.add_listener
def _load(environment, **_kw):
    global TEST_STARTED
    TEST_STARTED = time.time()
    opts = environment.parsed_options
    path = Path(opts.lt_manifest)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    _MANIFEST.clear()
    _MANIFEST.update(json.loads(path.read_text(encoding="utf-8")))
    PanelUser.fixed_count = opts.lt_proctors


def _next_identity(opts) -> dict:
    worker = 0
    try:
        from locust.runners import WorkerRunner

        runner = _ENV.runner if _ENV else None
        if isinstance(runner, WorkerRunner):
            worker = runner.worker_index
    except Exception:
        pass
    with _LOCK:
        n = next(_COUNTER)
    index = opts.lt_user_offset + n * max(1, opts.lt_worker_stride) + worker
    users = _MANIFEST["users"]
    if index >= len(users):
        raise StopUser()
    return users[index]


_ENV = None


@events.init.add_listener
def _init(environment, **_kw):
    global _ENV
    _ENV = environment


def _multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    out = []
    for name, value in fields.items():
        out.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for name, (filename, data, ctype) in files.items():
        out.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n".encode() + data + b"\r\n"
        )
    out.append(f"--{boundary}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={boundary}"


def _fire_ws(name: str, started: float, exc=None, length: int = 0):
    if _ENV is None:
        return
    _ENV.events.request.fire(
        request_type="WS", name=name, response_time=(time.perf_counter() - started) * 1000,
        response_length=length, exception=exc, context={},
    )


# --------------------------------------------------------------------------
# Imtihon kompyuteri
# --------------------------------------------------------------------------
class ExamClient(BaseHttpUser):
    weight = 100
    # Keyingi taymergacha uxlaydi (heartbeat/presence/events/kadr).
    network_timeout = 30.0
    connection_timeout = 10.0

    def wait_time(self):
        return max(0.05, min(self._due.values()) - time.time()) if getattr(self, "_due", None) else 1.0

    # --- yordamchilar -------------------------------------------------
    def _think(self, low: float, high: float) -> None:
        scale = self.opts.lt_think_scale
        if scale > 0:
            gevent.sleep(random.uniform(low, high) * scale)

    def _headers(self, *, auth=True, session=True) -> dict:
        h = {"Accept": "application/json"}
        if self.opts.lt_conn_close:
            h["Connection"] = "close"
        if self.opts.lt_real_ip:
            h["X-Real-IP"] = self.ident["public_ip"]
        if auth and self.access:
            h["Authorization"] = f"Bearer {self.access}"
            h["X-Device-ID"] = self.ident["device_id"]
        if session and self.session_token:
            h["X-Proctoring-Session"] = self.session_token
        return h

    def call(self, name, method, path, *, json_body=None, body=None, ctype=None,
             expect=(200, 201, 202), auth=True, session=True, retry_auth=True):
        """So'rov + konvertni ochish. 401 token_not_valid -> bitta refresh (client kabi)."""
        if self.offline:
            return None
        headers = self._headers(auth=auth, session=session)
        kwargs = {"headers": headers, "name": name, "catch_response": True}
        if json_body is not None:
            kwargs["json"] = json_body
        elif body is not None:
            headers["Content-Type"] = ctype
            kwargs["data"] = body
        with self.client.request(method, path, **kwargs) as resp:
            status = resp.status_code
            try:
                payload = resp.json() if resp.text else {}
            except Exception:
                payload = {}
            code = ((payload or {}).get("error") or {}).get("code", "") if isinstance(payload, dict) else ""
            if status == 401 and retry_auth and auth and code in ("", "token_not_valid", "not_authenticated", "authentication_failed"):
                resp.success()  # refresh keyin qaytadan — client xatti-harakati
                if self._refresh():
                    return self.call(name, method, path, json_body=json_body, body=body, ctype=ctype,
                                     expect=expect, auth=auth, session=session, retry_auth=False)
                resp.failure("401 va refresh muvaffaqiyatsiz")
                return None
            if status not in expect:
                resp.failure(f"{status} {code or (resp.text or '')[:120]}")
                self.last_error = (status, code)
                return None
            resp.success()
        data = payload.get("data") if isinstance(payload, dict) and "success" in payload else payload
        return data if data is not None else {}

    def _refresh(self) -> bool:
        data = self.call("auth/refresh", "POST", f"{API}/auth/refresh/",
                         json_body={"refresh": self.refresh}, auth=False, session=False, retry_auth=False)
        if not data or not data.get("access"):
            return False
        self.access = data["access"]
        self.refresh = data.get("refresh") or self.refresh
        self._due["jwt"] = time.time() + 29 * 60
        return True

    # --- boshlanish (login oqimi) --------------------------------------
    def on_start(self):
        self.opts = self.environment.parsed_options
        self.ident = _next_identity(self.opts)
        self.access = self.refresh = self.session_token = ""
        self.offline = False
        self.last_error = None
        self._due = {}
        self.ws = None
        self.rnd = random.Random(self.ident["index"])
        manifest = _MANIFEST
        ip = self.ident["public_ip"]

        # Preflight: ishga tushishda. 429 da operator "Qayta urinish" ni bosadi.
        for attempt in range(3):
            if self.call("client/preflight", "POST", f"{API}/client/preflight/",
                         json_body={"public_ip": ip}, auth=False, session=False) is not None:
                break
            self._think(5, 15)
        self.call("client/access-attempt", "POST", f"{API}/client/access-attempt/", json_body={
            "machine_uuid": self.ident["machine_uuid"], "mac_address": self.ident["mac"],
            "ip_address": self.ident["lan_ip"], "public_ip": ip, "hostname": self.ident["inventory_code"],
            "app_version": "1.0.0", "entered_login": True, "code": "",
        }, auth=False, session=False, expect=(202,))
        self._think(5, 20)  # login formasini to'ldirish

        data = self.call("auth/login", "POST", f"{API}/auth/login/", json_body={
            "username": self.ident["username"], "password": manifest["password"],
        }, auth=False, session=False)
        if not data:
            raise StopUser()
        self.access, self.refresh = data["access"], data["refresh"]
        self._due["jwt"] = time.time() + 29 * 60

        if self.call("client/handshake", "POST", f"{API}/client/handshake/",
                     json_body=payloads.handshake_body(self.ident)) is None:
            raise StopUser()
        self.call("client/presence", "POST", f"{API}/client/presence/", json_body={"in_exam": False})
        self.call("client/camera/config", "GET", f"{API}/client/camera/config/")
        exam_id = manifest["exam_id"]
        self._think(3, 10)
        self.call("client/camera/check", "POST", f"{API}/client/camera/check/",
                  json_body=payloads.camera_check_body(exam_id))
        self.call("client/exam/config", "GET", f"{API}/client/exam/config/?exam={exam_id}")
        self._think(10, 30)  # talabgor keladi, JSHSHIR kiritiladi

        look = self.call("client/candidate/lookup", "POST", f"{API}/client/candidate/lookup/", json_body={
            "pinfl": self.ident["pinfl"], "exam_id": exam_id,
            "machine_uuid": self.ident["machine_uuid"], "mac_address": self.ident["mac"],
        })
        if not look:
            raise StopUser()
        self._think(5, 10)  # oval va sanoq (faceid_guide_seconds=5) + solishtirish
        challenge = look["challenge"]
        face = payloads.face_frame_jpeg(self.ident["index"] % 3)
        passport = payloads.passport_jpeg(0)
        files = {"image": ("face.jpg", face, "image/jpeg"),
                 "reference_image": ("passport.jpg", passport, "image/jpeg")}
        if self.rnd.random() < self.opts.lt_face_attempt_rate:
            body, ctype = _multipart({"challenge": challenge, "score": "21", "faces_detected": "1"}, files)
            self.call("client/face/attempt", "POST", f"{API}/client/face/attempt/", body=body, ctype=ctype)
            self._think(5, 10)
        body, ctype = _multipart({
            "challenge": challenge, "score": str(self.rnd.randint(45, 70)), "faces_detected": "1",
            "image_key": "", "embedding": payloads.embedding_json(self.ident["index"] % 50),
        }, files)
        verified = self.call("client/face/verify", "POST", f"{API}/client/face/verify/",
                             body=body, ctype=ctype, expect=(201,))
        if not verified:
            raise StopUser()
        self.session_token = verified["proctoring_session_token"]
        self.public_id = verified["session"]["public_id"]
        self._think(5, 15)  # operator hujjatni tekshiradi
        self.call("client/identity/confirm", "POST", f"{API}/client/identity/confirm/",
                  json_body={"decision": "confirm"})
        if self.call("client/exam/access", "POST", f"{API}/client/exam/access/") is None:
            raise StopUser()
        if self.call("client/proctoring/start", "POST", f"{API}/client/proctoring/start/",
                     json_body={"ai_profile": "cpu"}) is None:
            raise StopUser()

        self.exam_started = time.time()
        self.face_checks = 0
        self.question = 0
        self.passed_since_last = 0
        now = time.time()
        exam_s = self.opts.lt_exam_minutes * 60
        self.shot_interval = exam_s / max(1, self.opts.lt_questions)
        self._due.update({
            "heartbeat": now,                       # birinchisi darhol (monitoring.start)
            "presence": now + 45,
            "events": now + 5,
            "shot": now + self.rnd.uniform(0.3, 1.0) * self.shot_interval,
            "face": now + 10,
            "finish": self._finish_deadline(now, exam_s),
        })
        if self.opts.lt_ws:
            self.ws_greenlet = gevent.spawn(self._ws_loop)

    def _finish_deadline(self, now, exam_s):
        o = self.opts
        if o.lt_scenario == "finish" and o.lt_finish_at_minutes > 0:
            return TEST_STARTED + o.lt_finish_at_minutes * 60 + random.uniform(0, o.lt_finish_jitter_s)
        return now + exam_s

    def on_stop(self):
        if getattr(self, "ws", None) is not None:
            try:
                self.ws.close()
            except Exception:
                pass

    # --- barqaror holat -----------------------------------------------
    @task
    def tick(self):
        now = time.time()
        self._outage_check(now)
        for key in sorted(self._due, key=self._due.get):
            if self._due[key] > now:
                break
            getattr(self, f"_do_{key}")()

    def _do_heartbeat(self):
        self._due["heartbeat"] += 30
        data = self.call("client/heartbeat", "POST", f"{API}/client/heartbeat/",
                         json_body=payloads.heartbeat_body(self.face_checks))
        if data and data.get("should_stop"):
            raise StopUser()

    def _do_presence(self):
        self._due["presence"] += 45
        self.call("client/presence", "POST", f"{API}/client/presence/", json_body={"in_exam": True})

    def _do_events(self):
        self._due["events"] += 5
        backlog = getattr(self, "backlog", 0)
        if backlog or self.rnd.random() < self.opts.lt_event_flush_rate:
            n = backlog or max(1, int(self.rnd.expovariate(1 / self.opts.lt_event_batch_mean)))
            n = min(200, n)  # EVENT_BATCH_MAX
            if self.call("client/events", "POST", f"{API}/client/events/",
                         json_body={"events": payloads.event_batch(n, self.rnd)}) is not None:
                self.backlog = max(0, backlog - n)

    def _do_shot(self):
        self._due["shot"] += self.shot_interval
        if self.question < self.opts.lt_questions and self.rnd.random() >= self.opts.lt_reanswer_rate:
            self.question += 1
            q = self.question
        else:
            q = max(1, self.rnd.randint(1, max(1, self.question)))
        body, ctype = _multipart(
            {"captured_at": payloads.now_iso(), "question_id": str(q), "question_number": str(q)},
            {"file": ("screen.jpg", payloads.screenshot_jpeg(self.ident["index"] % 3), "image/jpeg")},
        )
        if self.call("client/screenshots/upload", "POST", f"{API}/client/screenshots/upload/",
                     body=body, ctype=ctype, expect=(201,)) is None and self.offline is False:
            # screen_capture: xatoda 15 s dan keyin qayta (kadr tashlanmaydi).
            self._due["shot"] = min(self._due["shot"], time.time() + 15)

    def _do_face(self):
        self._due["face"] += 10
        self.face_checks += 1
        if self.rnd.random() >= self.opts.lt_periodic_fail_rate:
            self.passed_since_last += 1
            return
        body, ctype = _multipart(
            {"score": str(self.rnd.randint(5, 35)), "faces_detected": "1",
             "passed_since_last": str(self.passed_since_last)},
            {"image": ("face.jpg", payloads.face_frame_jpeg(self.ident["index"] % 3), "image/jpeg")},
        )
        self.passed_since_last = 0
        self.call("client/face/periodic", "POST", f"{API}/client/face/periodic/", body=body, ctype=ctype)

    def _do_jwt(self):
        self._due["jwt"] = time.time() + 29 * 60
        self._refresh()

    def _do_finish(self):
        elapsed_ms = int((time.time() - self.exam_started) * 1000)
        self.call("client/recordings", "POST", f"{API}/client/recordings/",
                  json_body=payloads.recording_body(self.public_id, elapsed_ms), expect=(201,))
        self.call("client/session/finish", "POST", f"{API}/client/session/finish/",
                  json_body={"reason": "", "completed": True})
        self.session_token = ""
        self._due = {"idle": time.time() + 3600}
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:
                pass
        raise StopUser()

    def _do_idle(self):
        self._due["idle"] = time.time() + 3600

    # --- tarmoq uzilishi (reconnect stsenariysi) ----------------------
    def _outage_check(self, now):
        o = self.opts
        if o.lt_scenario != "reconnect":
            return
        start = TEST_STARTED + o.lt_outage_at_minutes * 60
        end = start + o.lt_outage_seconds
        was = self.offline
        self.offline = start <= now < end
        if self.offline and not was:
            # Uzilish paytida client hodisalarni buferda yig'adi (5 s × ehtimol).
            self.backlog = int(o.lt_outage_seconds / 5 * o.lt_event_flush_rate * o.lt_event_batch_mean) + 1
            if self.ws is not None:
                try:
                    self.ws.close()
                except Exception:
                    pass

    # --- WebSocket (ws/client) ----------------------------------------
    def _ws_url(self) -> str:
        if self.opts.lt_ws_host:
            base = self.opts.lt_ws_host.rstrip("/")
        else:
            from urllib.parse import urlparse

            p = urlparse(self.host)
            port = (p.port or (443 if p.scheme == "https" else 80)) + 1
            base = f"{'wss' if p.scheme == 'https' else 'ws'}://{p.hostname}:{port}"
        return f"{base}/ws/client/"

    def _ws_loop(self):
        import websocket

        backoff = (1, 2, 4, 8, 15, 30)  # client/services/realtime.py:_BACKOFF_S
        attempt = 0
        while self.session_token:
            if self.offline:
                gevent.sleep(backoff[min(attempt, len(backoff) - 1)])
                attempt += 1
                continue
            started = time.perf_counter()
            try:
                headers = [f"X-Proctoring-Session: {self.session_token}"]
                if self.opts.lt_real_ip:
                    headers.append(f"X-Real-IP: {self.ident['public_ip']}")
                ws = websocket.create_connection(self._ws_url(), header=headers, timeout=15)
                first = ws.recv()
                _fire_ws("ws/client connect", started, length=len(first or ""))
                self.ws = ws
                attempt = 0
                last_ping = time.time()
                ws.settimeout(1.0)
                while self.session_token and not self.offline:
                    if time.time() - last_ping >= 25:  # _PING_INTERVAL_MS
                        t0 = time.perf_counter()
                        ws.send(json.dumps({"action": "ping"}))
                        last_ping = time.time()
                        _fire_ws("ws/client ping(send)", t0)
                    try:
                        ws.recv()
                    except websocket.WebSocketTimeoutException:
                        continue
            except Exception as exc:  # noqa: BLE001
                if self.session_token and not self.offline:
                    _fire_ws("ws/client connect", started, exc=exc)
            finally:
                try:
                    if self.ws is not None:
                        self.ws.close()
                except Exception:
                    pass
                self.ws = None
            if not self.session_token:
                break
            delay = backoff[min(attempt, len(backoff) - 1)]
            if self.opts.lt_reconnect_jitter:
                delay = random.uniform(0.5 * delay, 1.5 * delay)
            attempt += 1
            gevent.sleep(delay)


# --------------------------------------------------------------------------
# Admin panel (proktor)
# --------------------------------------------------------------------------
class PanelUser(BaseHttpUser):
    weight = 1
    fixed_count = 20
    wait_time = between(1, 2)

    def on_start(self):
        self.opts = self.environment.parsed_options
        with _LOCK:
            n = next(_PANEL_COUNTER)
        names = _MANIFEST["proctors"]
        self.username = names[n % len(names)]
        resp = self.client.post(f"{API}/auth/login/", json={
            "username": self.username, "password": _MANIFEST["password"]}, name="panel auth/login")
        data = (resp.json() or {}).get("data") or {}
        if not data.get("access"):
            raise StopUser()
        self.h = {"Authorization": f"Bearer {data['access']}"}
        if self.opts.lt_conn_close:
            self.h["Connection"] = "close"
        self.refresh_token = data.get("refresh")
        self.zone = list(_MANIFEST["zones"].values())[n % len(_MANIFEST["zones"])]
        self.due = {"dash": 0, "live": 0, "detail": time.time() + 20, "lists": time.time() + 30,
                    "jwt": time.time() + 29 * 60}
        self.session_id = None
        if self.opts.lt_ws:
            gevent.spawn(self._ws_monitor, data["access"])

    def _get(self, name, path):
        with self.client.get(path, headers=self.h, name=name, catch_response=True) as r:
            if r.status_code != 200:
                r.failure(f"{r.status_code}")
                return None
            try:
                return (r.json() or {}).get("data")
            except Exception:
                return None

    @task
    def loop(self):
        now = time.time()
        sched = _MANIFEST["schedule_id"]
        if now >= self.due["dash"]:  # Dashboard.jsx — 15 s
            self.due["dash"] = now + 15
            self._get("panel dashboard/summary", f"{API}/dashboard/summary/")
            self._get("panel dashboard/zones", f"{API}/dashboard/zones/")
        if now >= self.due["live"]:  # LiveMonitor.jsx — 10 s
            self.due["live"] = now + 10
            data = self._get("panel sessions/live", f"{API}/sessions/live/?limit=200&zone={self.zone}")
            rows = data if isinstance(data, list) else (data or {}).get("results") or []
            if rows and (self.session_id is None or random.random() < 0.1):
                self.session_id = random.choice(rows).get("id")
        if now >= self.due["detail"] and self.session_id:  # SessionDetail.jsx — 10 s
            self.due["detail"] = now + 10
            sid = self.session_id
            self._get("panel sessions/{id}", f"{API}/sessions/{sid}/")
            if random.random() < 0.3:
                self._get("panel sessions/{id}/events", f"{API}/sessions/{sid}/events/")
                self._get("panel sessions/{id}/stored-screenshots", f"{API}/sessions/{sid}/stored-screenshots/")
                self._get("panel sessions/{id}/screenshots", f"{API}/sessions/{sid}/screenshots/")
        if now >= self.due["lists"]:  # DeviceTokens/Computers/ComputerBookings — 30 s
            self.due["lists"] = now + 30
            choice = random.choice(["tokens", "computers", "bookings", "sessions"])
            if choice == "tokens":
                self._get("panel device-tokens", f"{API}/device-tokens/?zone={self.zone}")
            elif choice == "computers":
                self._get("panel computers", f"{API}/computers/?zone={self.zone}")
            elif choice == "bookings":
                self._get("panel computer-bookings/zones", f"{API}/computer-bookings/zones/?schedule={sched}")
                self._get("panel computer-bookings/seats",
                          f"{API}/computer-bookings/seats/?schedule={sched}&zone={self.zone}")
            else:
                self._get("panel sessions (list)", f"{API}/sessions/?zone={self.zone}")
        if now >= self.due["jwt"]:
            self.due["jwt"] = now + 29 * 60
            r = self.client.post(f"{API}/auth/refresh/", json={"refresh": self.refresh_token},
                                 name="panel auth/refresh")
            data = (r.json() or {}).get("data") or {}
            if data.get("access"):
                self.h = {**self.h, "Authorization": f"Bearer {data['access']}"}
                self.refresh_token = data.get("refresh") or self.refresh_token

    def _ws_monitor(self, token):
        import websocket
        from urllib.parse import urlparse

        opts = self.opts
        if opts.lt_ws_host:
            base = opts.lt_ws_host.rstrip("/")
        else:
            p = urlparse(self.host)
            base = f"ws://{p.hostname}:{(p.port or 80) + 1}"
        while True:
            started = time.perf_counter()
            try:
                ws = websocket.create_connection(f"{base}/ws/monitor/?token={token}", timeout=15)
                ws.recv()
                ws.send(json.dumps({"action": "subscribe", "zones": [self.zone]}))
                ws.recv()
                _fire_ws("ws/monitor subscribe", started)
                ws.settimeout(30)
                while True:
                    msg = ws.recv()
                    # Javob vaqti emas (xabarlar orasidagi kutish) — faqat soni va hajmi.
                    _fire_ws("ws/monitor message", time.perf_counter(), length=len(msg or ""))
            except Exception as exc:  # noqa: BLE001
                _fire_ws("ws/monitor connect", started, exc=exc)
                gevent.sleep(5)


_PANEL_COUNTER = count()


# --------------------------------------------------------------------------
# Yuklama shakllari
# --------------------------------------------------------------------------
class ProctoringShape(LoadTestShape):
    """
    `--lt-scenario` bo'yicha shakl. `tick()` -> (foydalanuvchilar, spawn_rate).

    stages   : har bosqichga `--lt-spawn-rate` bilan chiqish, keyin
               `--lt-stage-minutes` ushlab turish. CSV/HTML bosqichma-bosqich
               tahlil uchun bosqich chegaralari `results/*_stages.json` ga yoziladi.
    storm    : `--lt-storm-users` ni `--lt-storm-seconds` ichida (login
               bo'roni), keyin `--lt-hold-minutes` ushlab turish.
    steady / finish / reconnect : xuddi storm, farqi ExamClient ichida
               (yakun vaqti, uzilish oynasi).
    PanelUser `fixed_count` bilan qo'shiladi (umumiy songa kiradi).
    """

    def tick(self):
        opts = self.runner.environment.parsed_options
        proctors = opts.lt_proctors
        t = self.get_run_time()
        if opts.lt_scenario == "stages":
            stages = [int(x) for x in opts.lt_stages.split(",") if x.strip()]
            elapsed = 0.0
            prev = 0
            for target in stages:
                ramp = (target - prev) / max(0.1, opts.lt_spawn_rate)
                hold = opts.lt_stage_minutes * 60
                if t < elapsed + ramp + hold:
                    return target + proctors, opts.lt_spawn_rate
                elapsed += ramp + hold
                prev = target
            return None
        users = opts.lt_storm_users
        rate = users / max(1.0, opts.lt_storm_seconds)
        if t < opts.lt_storm_seconds + opts.lt_hold_minutes * 60:
            return users + proctors, rate
        return None


def stage_boundaries(opts) -> list[dict]:
    """Bosqich chegaralari (soniya, sinov boshidan)."""
    out, elapsed, prev = [], 0.0, 0
    for target in [int(x) for x in opts.lt_stages.split(",") if x.strip()]:
        ramp = (target - prev) / max(0.1, opts.lt_spawn_rate)
        out.append({"users": target, "ramp_start": elapsed, "hold_start": elapsed + ramp,
                    "hold_end": elapsed + ramp + opts.lt_stage_minutes * 60})
        elapsed += ramp + opts.lt_stage_minutes * 60
        prev = target
    return out


def phase_of(t: float, opts) -> str:
    """So'rov qaysi bosqichga tegishli (natijani bosqichlarga bo'lish uchun)."""
    sc = opts.lt_scenario
    if sc == "stages":
        for st in stage_boundaries(opts):
            if t < st["hold_start"]:
                return f"{st['users']:05d}-ramp"
            if t < st["hold_end"]:
                return f"{st['users']:05d}-hold"
        return "tail"
    if sc in ("storm", "steady"):
        return "1-storm" if t < opts.lt_storm_seconds else "2-hold"
    if sc == "finish":
        at = opts.lt_finish_at_minutes * 60
        if t < opts.lt_storm_seconds:
            return "1-login"
        if t < at:
            return "2-steady"
        return "3-finish" if t < at + opts.lt_finish_jitter_s + 60 else "4-after"
    if sc == "reconnect":
        start = opts.lt_outage_at_minutes * 60
        end = start + opts.lt_outage_seconds
        if t < opts.lt_storm_seconds:
            return "1-login"
        if t < start:
            return "2-before"
        if t < end:
            return "3-outage"
        return "4-recovery" if t < end + 120 else "5-after"
    return "all"


# --- bosqich bo'yicha statistika (har jarayon o'z faylini yozadi) --------
_BY_STAGE: dict = {}


def _bucket(ms: float) -> int:
    """Locust bilan bir xil yaxlitlash: <100 ms — 1 ms, <1000 — 10 ms, keyin 100 ms."""
    ms = int(round(ms))
    if ms < 100:
        return ms
    if ms < 1000:
        return int(round(ms, -1))
    return int(round(ms, -2))


@events.request.add_listener
def _on_request(request_type, name, response_time, response_length, exception=None, **_kw):
    if _ENV is None or not getattr(_ENV, "parsed_options", None):
        return
    phase = phase_of(time.time() - TEST_STARTED, _ENV.parsed_options)
    key = (phase, request_type, name)
    row = _BY_STAGE.get(key)
    if row is None:
        row = _BY_STAGE[key] = {"count": 0, "fail": 0, "bytes": 0, "rt": {}, "first": time.time(), "last": 0.0}
    row["count"] += 1
    row["bytes"] += int(response_length or 0)
    row["last"] = time.time()
    if exception is not None:
        row["fail"] += 1
    b = _bucket(response_time or 0)
    row["rt"][b] = row["rt"].get(b, 0) + 1


@events.quitting.add_listener
def _dump_by_stage(environment, **_kw):
    opts = environment.parsed_options
    prefix = getattr(opts, "csv_prefix", None) or "results/lt"
    if not _BY_STAGE:
        return
    from locust.runners import WorkerRunner

    tag = f"w{environment.runner.worker_index}" if isinstance(environment.runner, WorkerRunner) else "local"
    Path(f"{prefix}_by_stage_{tag}.json").write_text(json.dumps({
        "scenario": opts.lt_scenario,
        "test_started": TEST_STARTED,
        "stages": stage_boundaries(opts) if opts.lt_scenario == "stages" else [],
        "rows": [
            {"phase": k[0], "type": k[1], "name": k[2], **v, "rt": {str(a): c for a, c in v["rt"].items()}}
            for k, v in sorted(_BY_STAGE.items())
        ],
    }), encoding="utf-8")
