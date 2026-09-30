"""
Har endpointning SERVER TOMONIDAGI narxi — concurrency 1, in-process.

    cd backend
    $env:PYTHONPATH="loadtest\\server"; $env:DJANGO_SETTINGS_MODULE="loadtest_settings"
    .venv\\Scripts\\python.exe loadtest\\tools\\profile_endpoints.py --users 20 \\
        --out loadtest\\results\\endpoint_profile.json

Nima o'lchanadi (har endpoint uchun, N ta so'rov bo'yicha):

* vaqt (median, p95, ms) — Django test client orqali, HTTP server va
  tarmoqsiz. Bu "bitta so'rov server CPU/IO'ga qancha tushadi" ning
  yuqori bahosi (DB va Redis kutishi ham ichida). Windows dev mashinasi,
  bitta jarayon — production'ga ekstrapolyatsiya uchun, SLO uchun EMAS;
* SQL so'rovlar soni turi bo'yicha (SELECT/INSERT/UPDATE/DELETE) —
  `CaptureQueriesContext`, aniq qiymat;
* Redis buyruqlari soni — redis-py `execute_command` va pipeline'ni
  o'rab sanaladi (channel layer'ning async `group_send` i alohida);
* so'rov va javob hajmi (bayt) — haqiqiy kodlangan tana.

Stub platforma shu jarayonning ichida ishga tushadi (`--platform-port`).
`seed_loadtest` oldin bajarilgan bo'lishi SHART (manifest kerak) va
har yurishdan oldin qayta bajariladi: `session/finish/` (`completed=True`)
joyni bo'shatadi, seed uni qaytadan biriktiradi.

Ishlatiladigan identifikatorlar manifestning OXIRIDAN olinadi — Locust
boshidan oladi, ikkalasi to'qnashmaydi.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve()
BACKEND = HERE.parents[2]
sys.path.insert(0, str(BACKEND / "src"))
sys.path.insert(0, str(HERE.parents[1] / "server"))
sys.path.insert(0, str(HERE.parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "loadtest_settings")
# `.env` dagi dev brokeri (`/0`) Celery'da sozlamadan ustun — qayta yozamiz.
os.environ["CELERY_BROKER_URL"] = "redis://127.0.0.1:6379/8"
os.environ["CELERY_RESULT_BACKEND"] = "redis://127.0.0.1:6379/9"

import django  # noqa: E402

django.setup()

from django.db import connection  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.client import BOUNDARY, encode_multipart  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402

import payloads  # noqa: E402

API = "/api/v1"


# --------------------------------------------------------------------------
# Redis buyruqlarini sanash
# --------------------------------------------------------------------------
class RedisCounter:
    def __init__(self):
        self.count = 0
        self.group_sends = 0
        self._lock = threading.Lock()

    def install(self):
        import redis
        from redis.client import Pipeline

        counter = self
        original = redis.Redis.execute_command
        original_pipe = Pipeline.execute

        def execute_command(self_, *args, **kwargs):
            with counter._lock:
                counter.count += 1
            return original(self_, *args, **kwargs)

        def pipe_execute(self_, *args, **kwargs):
            with counter._lock:
                counter.count += max(1, len(self_.command_stack))
            return original_pipe(self_, *args, **kwargs)

        redis.Redis.execute_command = execute_command
        Pipeline.execute = pipe_execute
        # `Pipeline.execute_command` o'z klassida qayta aniqlangan (buyruqni
        # stack'ga qo'yadi) — yuqoridagi o'ram unga tegmaydi, ikki marta
        # sanalmaydi.

        try:
            from channels_redis.core import RedisChannelLayer

            original_send = RedisChannelLayer.group_send

            async def group_send(self_, group, message):
                with counter._lock:
                    counter.group_sends += 1
                return await original_send(self_, group, message)

            RedisChannelLayer.group_send = group_send
        except Exception:  # pragma: no cover
            pass

    def snapshot(self):
        return self.count, self.group_sends


# --------------------------------------------------------------------------
class Recorder:
    def __init__(self, redis_counter: RedisCounter):
        self.rows = defaultdict(list)
        self.redis = redis_counter
        self.errors = defaultdict(int)

    def call(self, name: str, client: Client, method: str, path: str, *,
             json_body=None, multipart=None, headers=None, expect=(200, 201, 202)):
        headers = headers or {}
        if multipart is not None:
            body = encode_multipart(BOUNDARY, multipart)
            req_bytes = len(body)
            kwargs = {"data": body, "content_type": f"multipart/form-data; boundary={BOUNDARY}"}
        elif json_body is not None:
            body = json.dumps(json_body)
            req_bytes = len(body)
            kwargs = {"data": body, "content_type": "application/json"}
        else:
            req_bytes = 0
            kwargs = {}
        r0, g0 = self.redis.snapshot()
        with CaptureQueriesContext(connection) as ctx:
            started = time.perf_counter()
            response = getattr(client, method)(path, **kwargs, headers=headers)
            elapsed = (time.perf_counter() - started) * 1000
        r1, g1 = self.redis.snapshot()
        kinds = defaultdict(int)
        for q in ctx.captured_queries:
            verb = q["sql"].lstrip().split(" ", 1)[0].upper()
            if verb in ("SAVEPOINT", "RELEASE", "ROLLBACK"):
                continue
            kinds[verb] += 1
        content = response.content if not getattr(response, "streaming", False) else b""
        self.rows[name].append({
            "ms": elapsed,
            "status": response.status_code,
            "req_bytes": req_bytes,
            "resp_bytes": len(content),
            "sql": dict(kinds),
            "redis": r1 - r0,
            "group_send": g1 - g0,
        })
        if response.status_code not in expect:
            self.errors[f"{name}:{response.status_code}"] += 1
            print(f"  ! {name} -> {response.status_code}: {content[:300]!r}", flush=True)
            return None
        try:
            data = json.loads(content or b"{}")
        except ValueError:
            return {}
        return data.get("data") if isinstance(data, dict) and "success" in data else data

    def summary(self) -> dict:
        out = {}
        for name, rows in self.rows.items():
            ok = [r for r in rows if r["status"] < 400] or rows
            ms = sorted(r["ms"] for r in ok)
            sql = defaultdict(list)
            for r in ok:
                for verb in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    sql[verb].append(r["sql"].get(verb, 0))
            out[name] = {
                "n": len(rows),
                "errors": len(rows) - len([r for r in rows if r["status"] < 400]),
                "ms_median": round(statistics.median(ms), 2),
                "ms_p95": round(ms[min(len(ms) - 1, int(len(ms) * 0.95))], 2),
                "req_bytes": int(statistics.median(r["req_bytes"] for r in ok)),
                "resp_bytes": int(statistics.median(r["resp_bytes"] for r in ok)),
                "sql": {k: round(statistics.mean(v), 2) for k, v in sql.items()},
                "redis_cmds": round(statistics.mean(r["redis"] for r in ok), 1),
                "group_sends": round(statistics.mean(r["group_send"] for r in ok), 1),
            }
        return out


# --------------------------------------------------------------------------
def start_stub(port: int, latency_ms: float) -> None:
    import stub_platform
    from http.server import ThreadingHTTPServer

    args = argparse.Namespace(latency_ms=latency_ms, jitter_ms=0.0, error_rate=0.0)
    stub_platform.Handler.config = args
    import base64

    stub_platform.Handler.photo = base64.b64encode(payloads.passport_jpeg(0)).decode()
    server = ThreadingHTTPServer(("127.0.0.1", port), stub_platform.Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()


def run_client_flow(rec: Recorder, ident: dict, manifest: dict, args) -> None:
    ip = ident["public_ip"]
    anon = Client(HTTP_X_REAL_IP=ip)
    rec.call("preflight", anon, "post", f"{API}/client/preflight/", json_body={"public_ip": ip})
    rec.call("access_attempt", anon, "post", f"{API}/client/access-attempt/", json_body={
        "machine_uuid": ident["machine_uuid"], "mac_address": ident["mac"],
        "ip_address": ident["lan_ip"], "public_ip": ip, "hostname": ident["inventory_code"],
        "app_version": "1.0.0", "entered_login": True, "code": "",
    })
    data = rec.call("login", anon, "post", f"{API}/auth/login/", json_body={
        "username": ident["username"], "password": manifest["password"],
    })
    if not data:
        return
    access, refresh = data["access"], data["refresh"]
    h = {"Authorization": f"Bearer {access}", "X-Device-ID": ident["device_id"]}
    cli = Client(HTTP_X_REAL_IP=ip)
    rec.call("handshake", cli, "post", f"{API}/client/handshake/",
             json_body=payloads.handshake_body(ident), headers=h)
    rec.call("presence", cli, "post", f"{API}/client/presence/", json_body={"in_exam": False}, headers=h)
    rec.call("camera_config", cli, "get", f"{API}/client/camera/config/", headers=h)
    exam_id = manifest["exam_id"]
    rec.call("camera_check", cli, "post", f"{API}/client/camera/check/",
             json_body=payloads.camera_check_body(exam_id), headers=h)
    rec.call("exam_config", cli, "get", f"{API}/client/exam/config/?exam={exam_id}", headers=h)
    look = rec.call("candidate_lookup", cli, "post", f"{API}/client/candidate/lookup/", json_body={
        "pinfl": ident["pinfl"], "exam_id": exam_id,
        "machine_uuid": ident["machine_uuid"], "mac_address": ident["mac"],
    }, headers=h)
    if not look:
        return
    challenge = look["challenge"]
    face = payloads.face_frame_jpeg(ident["index"] % 3)
    passport = payloads.passport_jpeg(0)
    from django.core.files.uploadedfile import SimpleUploadedFile

    def files():
        return {
            "image": SimpleUploadedFile("face.jpg", face, "image/jpeg"),
            "reference_image": SimpleUploadedFile("passport.jpg", passport, "image/jpeg"),
        }

    rec.call("face_attempt", cli, "post", f"{API}/client/face/attempt/", multipart={
        "challenge": challenge, "score": "18", "faces_detected": "1", **files(),
    }, headers=h)
    verified = rec.call("face_verify", cli, "post", f"{API}/client/face/verify/", multipart={
        "challenge": challenge, "score": "63", "faces_detected": "1", "image_key": "",
        "embedding": payloads.embedding_json(ident["index"]), **files(),
    }, headers=h)
    if not verified:
        return
    hs = {**h, "X-Proctoring-Session": verified["proctoring_session_token"]}
    public_id = verified["session"]["public_id"]
    rec.call("identity_confirm", cli, "post", f"{API}/client/identity/confirm/",
             json_body={"decision": "confirm"}, headers=hs)
    rec.call("exam_access", cli, "post", f"{API}/client/exam/access/", headers=hs)
    rec.call("proctoring_start", cli, "post", f"{API}/client/proctoring/start/",
             json_body={"ai_profile": "cpu"}, headers=hs)

    for n in range(args.heartbeats):
        rec.call("heartbeat", cli, "post", f"{API}/client/heartbeat/",
                 json_body=payloads.heartbeat_body(n * 3), headers=hs)
    rec.call("presence_in_exam", cli, "post", f"{API}/client/presence/",
             json_body={"in_exam": True}, headers=hs)
    for size in (1, 10, 50):
        severity_batch = [payloads.event("face_not_found", 2) for _ in range(size)]
        rec.call(f"events_{size}_sev2", cli, "post", f"{API}/client/events/",
                 json_body={"events": severity_batch}, headers=hs)
    rec.call("events_10_sev1", cli, "post", f"{API}/client/events/",
             json_body={"events": [payloads.event("hotkey_blocked", 1, {"key": "alt+tab"})
                                   for _ in range(10)]}, headers=hs)
    for q in range(1, args.shots + 1):
        rec.call("screenshot_upload", cli, "post", f"{API}/client/screenshots/upload/", multipart={
            "file": SimpleUploadedFile("screen.jpg", payloads.screenshot_jpeg(q % 3), "image/jpeg"),
            "captured_at": payloads.now_iso(), "question_id": str(q), "question_number": str(q),
        }, headers=hs)
    # Savolga qayta javob — eski kadr almashtiriladi (`unique_screenshot_session_question`).
    rec.call("screenshot_replace", cli, "post", f"{API}/client/screenshots/upload/", multipart={
        "file": SimpleUploadedFile("screen.jpg", payloads.screenshot_jpeg(1), "image/jpeg"),
        "captured_at": payloads.now_iso(), "question_id": "1", "question_number": "1",
    }, headers=hs)
    rec.call("face_periodic_fail", cli, "post", f"{API}/client/face/periodic/", multipart={
        "score": "12", "faces_detected": "1", "passed_since_last": "5",
        "image": SimpleUploadedFile("face.jpg", face, "image/jpeg"),
    }, headers=hs)
    rec.call("session_state", cli, "get", f"{API}/client/session/state/", headers=hs)
    rec.call("jwt_refresh", anon, "post", f"{API}/auth/refresh/", json_body={"refresh": refresh})
    rec.call("recording", cli, "post", f"{API}/client/recordings/",
             json_body=payloads.recording_body(public_id, 10_800_000), headers=hs)
    rec.call("session_finish", cli, "post", f"{API}/client/session/finish/",
             json_body={"reason": "", "completed": True}, headers=hs)


def run_panel(rec: Recorder, manifest: dict, repeats: int) -> None:
    anon = Client()
    for name in manifest["proctors"][:max(1, repeats)]:
        data = rec.call("panel_login", anon, "post", f"{API}/auth/login/",
                        json_body={"username": name, "password": manifest["password"]})
        if not data:
            return
        cli = Client(HTTP_AUTHORIZATION=f"Bearer {data['access']}")
        sched = manifest["schedule_id"]
        zone = manifest["zones"]["1"]
        rec.call("panel_me", cli, "get", f"{API}/auth/me/")
        rec.call("panel_dashboard_summary", cli, "get", f"{API}/dashboard/summary/")
        rec.call("panel_dashboard_zones", cli, "get", f"{API}/dashboard/zones/")
        rec.call("panel_sessions_live", cli, "get", f"{API}/sessions/live/?limit=200")
        rec.call("panel_sessions_list", cli, "get", f"{API}/sessions/")
        sessions = rec.call("panel_sessions_live_zone", cli, "get",
                            f"{API}/sessions/live/?limit=200&zone={zone}")
        rows = sessions if isinstance(sessions, list) else (sessions or {}).get("results") or []
        if rows:
            sid = rows[0].get("id")
            rec.call("panel_session_detail", cli, "get", f"{API}/sessions/{sid}/")
            rec.call("panel_session_events", cli, "get", f"{API}/sessions/{sid}/events/")
            rec.call("panel_session_stored_screens", cli, "get",
                     f"{API}/sessions/{sid}/stored-screenshots/")
        rec.call("panel_device_tokens", cli, "get", f"{API}/device-tokens/")
        rec.call("panel_computers", cli, "get", f"{API}/computers/")
        rec.call("panel_booking_zones", cli, "get", f"{API}/computer-bookings/zones/?schedule={sched}")
        rec.call("panel_booking_seats", cli, "get",
                 f"{API}/computer-bookings/seats/?schedule={sched}&zone={zone}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(HERE.parents[1] / "results" / "manifest.json"))
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--heartbeats", type=int, default=5)
    parser.add_argument("--shots", type=int, default=5)
    parser.add_argument("--panel", type=int, default=5)
    parser.add_argument("--platform-port", type=int, default=8099)
    parser.add_argument("--platform-latency-ms", type=float, default=0.0)
    parser.add_argument("--out", default=str(HERE.parents[1] / "results" / "endpoint_profile.json"))
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    counter = RedisCounter()
    counter.install()
    start_stub(args.platform_port, args.platform_latency_ms)
    rec = Recorder(counter)

    idents = manifest["users"][-args.users:]
    started = time.time()
    for n, ident in enumerate(idents, 1):
        run_client_flow(rec, ident, manifest, args)
        if n % 5 == 0:
            print(f"  {n}/{len(idents)} oqim", flush=True)
    run_panel(rec, manifest, args.panel)

    result = {
        "measured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "environment": "Windows 11 dev, in-process Django test client, concurrency 1, "
                       "PostgreSQL 17 + Redis 7 lokal (localhost)",
        "users": len(idents),
        "wall_seconds": round(time.time() - started, 1),
        "endpoints": rec.summary(),
        "errors": dict(rec.errors),
    }
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result["errors"], indent=2))
    width = max(len(k) for k in result["endpoints"])
    print(f"{'endpoint':<{width}}  n   med_ms  p95_ms  req_B    resp_B  SELECT INS UPD DEL redis gsend")
    for name, row in result["endpoints"].items():
        sql = row["sql"]
        print(f"{name:<{width}} {row['n']:>3} {row['ms_median']:>7} {row['ms_p95']:>7} "
              f"{row['req_bytes']:>7} {row['resp_bytes']:>7}  {sql.get('SELECT', 0):>5} "
              f"{sql.get('INSERT', 0):>3} {sql.get('UPDATE', 0):>3} {sql.get('DELETE', 0):>3} "
              f"{row['redis_cmds']:>5} {row['group_sends']:>5}")


if __name__ == "__main__":
    main()
