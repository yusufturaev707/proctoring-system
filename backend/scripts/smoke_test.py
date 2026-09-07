"""
End-to-end smoke test — butun oqimni bitta process ichida tekshiradi.

    python scripts/smoke_test.py

Nima tekshiriladi:
    1. Xodim autentifikatsiyasi va barcha admin endpointlari
    2. Qurilma + operator JWT (ruxsatsiz so'rov rad etiladimi)
    3. To'liq client oqimi: JSHSHIR -> FaceID -> sessiya -> hodisalar
    4. Redis buffer -> PostgreSQL batch yozish
    5. Proktor amallari (ogohlantirish, chetlashtirish)
    6. Chetlashtirilgan sessiya DARHOL bloklanishi
    7. Audit yozuvlari
    8. Kriptografiya (shifrlash/hash/niqoblash)

DIQQAT: test boshida barcha `ExamSession` yozuvlarini o'chiradi.
Faqat DEV bazasida ishlating.
"""

import json
import os
import sys
from datetime import datetime, time as dtime

sys.path.insert(0, r"C:\Projects\proctoring-system\backend\src")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
os.environ["REQUIRE_DEVICE_ID"] = "true"
os.environ["BASE_API_MOCK"] = "true"

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.test import Client  # noqa: E402
from django.utils import timezone  # noqa: E402

settings.PROCTORING["REQUIRE_DEVICE_ID"] = True
settings.EXTERNAL_PLATFORM["MOCK"] = True

from apps.devices import services as device_services  # noqa: E402
from apps.devices.models import Computer, DeviceToken  # noqa: E402
from django.conf import settings  # noqa: E402
from pathlib import Path  # noqa: E402

from apps.controls.models import AllowedPublicIp, ClientExitPassword  # noqa: E402
from apps.controls.services import invalidate_ip_cache  # noqa: E402
from apps.regions.models import Region, Zone  # noqa: E402
from apps.exams.models import Exam  # noqa: E402
from apps.users.models import Role, User  # noqa: E402

# Rollar NOM bo'yicha izlanadi, kalit bo'yicha emas: kalitlar reliz
# davomida qayta raqamlanishi mumkin (masalan Superadmin olib
# tashlanganda hammasi bir pog'ona surildi) va o'shanda test
# jimgina BOSHQA rol bilan ishlab, noto'g'ri "o'tdi" berardi.

client = Client()
FAILURES = []

# Oldingi ishga tushirishdan qolgan holatni tozalaymiz (Redis qulflari,
# faol sessiyalar) — aks holda "bitta talabgor = bitta sessiya" qoidasi
# testni ikkinchi marta ishga tushirishga to'sqinlik qiladi.
from apps.common.redis_client import get_redis  # noqa: E402
from apps.proctoring.models import AuditLog, ExamSession  # noqa: E402

redis_client = get_redis()
for pattern in ["sess:*", "cb:*"]:
    keys = list(redis_client.scan_iter(match=pattern, count=1000))
    if keys:
        redis_client.delete(*keys)
ExamSession.objects.all().delete()
print("(oldingi test holati tozalandi)")


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}" + (f"  -> {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def body(response):
    try:
        return json.loads(response.content)
    except Exception:
        return {"_raw": response.content[:300].decode("utf-8", "replace")}


print("\n=== 1. Admin auth ===")
admin, _ = User.objects.get_or_create(
    username="smoke_admin",
    defaults={"is_staff": True, "is_superuser": True, "is_active": True},
)
admin.set_password("SmokeTest!2026")
admin.role = Role.objects.filter(name="Administrator").first()
admin.save()

resp = client.post(
    "/api/v1/auth/login/",
    data=json.dumps({"username": "smoke_admin", "password": "SmokeTest!2026"}),
    content_type="application/json",
)
data = body(resp)
check("login 200", resp.status_code == 200, f"{resp.status_code} {data}")
access = data.get("data", {}).get("access", "")
check("access token qaytdi", bool(access))
AUTH = {"HTTP_AUTHORIZATION": f"Bearer {access}"}

resp = client.get("/api/v1/auth/me/", **AUTH)
check("/auth/me/ 200", resp.status_code == 200, str(resp.status_code))
check("konvert formati", body(resp).get("success") is True)

for path in ["/api/v1/users/", "/api/v1/roles/", "/api/v1/regions/", "/api/v1/zones/",
             "/api/v1/computers/", "/api/v1/cameras/", "/api/v1/exams/",
             "/api/v1/settings/", "/api/v1/sessions/", "/api/v1/audit-logs/",
             "/api/v1/dashboard/summary/", "/api/v1/dashboard/zones/",
             "/api/v1/dashboard/devices/"]:
    resp = client.get(path, **AUTH)
    check(f"GET {path}", resp.status_code == 200, f"{resp.status_code} {body(resp)}")

print("\n=== 1b. Preflight — login formasidan oldingi tarmoq tekshiruvi ===")
# Client dastur ishga tushishi bilan shu endpointni chaqiradi va javob
# "yo'q" bo'lsa login formasini umuman ko'rsatmaydi.
# Test O'ZINING ruxsat yozuvi bilan ishlaydi.
#
# Adminning ro'yxati bo'sh ham, to'la ham bo'lishi mumkin va yozuvlar
# boshqa binoga bog'langan bo'lishi mumkin — test esa undan qat'iy
# nazar bir xil natija berishi kerak. Yozuv oxirida ASL holiga
# qaytariladi (`_restore_allowed_ip`), aks holda test adminning
# sozlamasini jimgina o'zgartirib ketardi.
SMOKE_IP = "127.0.0.1"
_ip_orig = (
    AllowedPublicIp.objects.filter(ip_address=SMOKE_IP)
    .values("is_active", "zone_id")
    .first()
)
zone = Zone.objects.filter(deleted_at__isnull=True).order_by("id").first()
AllowedPublicIp.objects.update_or_create(
    ip_address=SMOKE_IP,
    defaults={"name": "SMOKE-TEST", "is_active": True, "zone": zone},
)
invalidate_ip_cache()


def _restore_allowed_ip():
    """Adminning ro'yxatini test boshlangungacha bo'lgan holatga qaytaradi."""
    if _ip_orig is None:
        AllowedPublicIp.objects.filter(ip_address=SMOKE_IP).delete()
    else:
        AllowedPublicIp.objects.filter(ip_address=SMOKE_IP).update(**_ip_orig)
    invalidate_ip_cache()


resp = client.post(
    "/api/v1/client/preflight/",
    data=json.dumps({"public_ip": SMOKE_IP}),
    content_type="application/json",
    REMOTE_ADDR="203.0.113.1",
)
data = body(resp)
check("preflight 200", resp.status_code == 200, f"{resp.status_code} {data}")
_pre = data.get("data") or {}
# Qaror FAQAT client aytgan public IP bo'yicha: manba manzili begona
# bo'lsa ham ruxsat beriladi (server bino ichida turgan holat).
check("ruxsat public IP bo'yicha berildi", _pre.get("allowed") is True, str(_pre))
check("javobda public IP qaytdi", _pre.get("public_ip") == SMOKE_IP, str(_pre))
check("manba manzili farq qilgani belgilandi", _pre.get("matches_observed") is False, str(_pre))

resp = client.post(
    "/api/v1/client/preflight/",
    data=json.dumps({"public_ip": "203.0.113.1"}),
    content_type="application/json",
)
data = body(resp)
check("ro'yxatda yo'q IP -> 403", resp.status_code == 403, f"{resp.status_code} {data}")
_err = data.get("error") or {}
check("kod ip_not_allowed", _err.get("code") == "ip_not_allowed", str(_err))
check(
    "rad etilgan manzil ko'rsatildi",
    (_err.get("details") or {}).get("public_ip") == "203.0.113.1",
    str(_err),
)

resp = client.post(
    "/api/v1/client/preflight/", data=json.dumps({}), content_type="application/json"
)
data = body(resp)
check("public IP siz -> 400", resp.status_code == 400, f"{resp.status_code} {data}")
check(
    "kod public_ip_unknown",
    (data.get("error") or {}).get("code") == "public_ip_unknown",
    str(data.get("error")),
)

# Kirish urinishi jurnalga yoziladi (natijadan qat'iy nazar).
_log_path = Path(settings.CLIENT_ACCESS_LOG)
_before = _log_path.stat().st_size if _log_path.exists() else 0
resp = client.post(
    "/api/v1/client/access-attempt/",
    data=json.dumps(
        {
            "mac_address": "AA:00:00:00:00:01",
            "ip_address": "10.255.255.254",
            "public_ip": "203.0.113.1",
            "hostname": "SMOKE-TEST",
            "app_version": "1.0.0",
            "entered_login": False,
            "code": "ip_not_allowed",
        }
    ),
    content_type="application/json",
)
check("access-attempt 202", resp.status_code == 202, f"{resp.status_code} {body(resp)}")
# BAYT bo'yicha kesiladi, belgi bo'yicha emas: `st_size` baytda, matnda
# esa ko'p baytli belgilar bor (— va o'xshashlari) va belgi bo'yicha
# kesish qatorning boshini yeb qo'yardi.
_written = (
    _log_path.read_bytes()[_before:].decode("utf-8", "replace")
    if _log_path.exists()
    else ""
)
check("jurnalga yozildi", "KIRISH URINISHI" in _written, _written[-200:])
check("jurnalda MAC bor", "AA:00:00:00:00:01" in _written)
check("jurnalda natija bor", "ruxsat=YO'Q" in _written and "login_sahifasi=OCHILMADI" in _written,
      _written[-200:])


print("\n=== 2. Qurilmani ro'yxatga olish ===")
# Test O'ZINING kompyuteridan foydalanadi.
#
# Ilgari bu yerda `Computer.objects.first()` turardi va uning barcha
# qurilma tokenlari o'chirilardi. Natijada test haqiqiy ish stantsiyasini
# "o'g'irlab" ketardi: o'sha kompyuterdagi client saqlab qo'ygan
# `device_id` serverda yo'q bo'lib qolar va u boshqa hech qachon kira
# olmasdi (`device_not_registered`), sababi esa mutlaqo ko'rinmasdi.
#
# `zone` 1b-bo'limda tanlangan va o'sha yerda `AllowedPublicIp` ga
# bog'langan: `check_source_ip` har bir client so'rovida "shu manba IP
# shu binoga ruxsat etilganmi?" deb tekshiradi, ya'ni test kompyuteri
# aynan o'sha binoda turishi shart.
computer, _ = Computer.objects.update_or_create(
    inventory_code="SMOKE-TEST",
    defaults={
        "zone": zone,
        "ip_address": "10.255.255.254",
        "mac_address": "AA:00:00:00:00:01",
        "is_active": True,
        # `deleted_at` NI TIKLASH SHART. `Computer` — `SoftDeleteModel`,
        # ya'ni standart menejer o'chirilgan qatorlarni ham ko'radi:
        # `update_or_create` yumshoq o'chirilgan qatorni topib yangilaydi,
        # lekin `deleted_at` o'z holicha qoladi va `DeviceResolution`
        # keyin `device_computer_inactive` bilan rad etadi.
        "deleted_at": None,
    },
)
DeviceToken.objects.filter(computer=computer).delete()
device = device_services.register_device(
    computer=computer, hardware_fingerprint="smoke-hw", app_version="1.0.0", auto_activate=True
)
check("qurilma faol", device.is_usable)
check("ro'yxatdan sir qaytmaydi", not hasattr(device, "secret"))


# Operator — desktop ilovaga login/parol bilan kiradigan xodim.
operator, _ = User.objects.get_or_create(
    username="smoke_operator", defaults={"is_active": True}
)
operator.set_password("SmokeOp!2026")
operator.role = Role.objects.filter(name="Operator").first()
operator.save()

resp = client.post(
    "/api/v1/auth/login/",
    data=json.dumps({"username": "smoke_operator", "password": "SmokeOp!2026"}),
    content_type="application/json",
)
op_data = body(resp)
check("operator login 200", resp.status_code == 200, f"{resp.status_code} {op_data}")
op_access = op_data.get("data", {}).get("access", "")
op_perms = op_data.get("data", {}).get("user", {}).get("permissions", [])
check("client.operate ruxsati bor", "client.operate" in op_perms, str(op_perms))
check("client.identity ruxsati bor", "client.identity" in op_perms, str(op_perms))
check("chetlashtirish ruxsati YO'Q", "sessions.terminate" not in op_perms, str(op_perms))

OP = {"HTTP_AUTHORIZATION": f"Bearer {op_access}"}


def signed(path, session_token=None):
    """Client so'rovi header'lari: operator JWT + qurilma ID (+ sessiya tokeni)."""
    headers = {**OP, "HTTP_X_DEVICE_ID": device.device_id}
    if session_token is not None:
        headers["HTTP_X_PROCTORING_SESSION"] = session_token
    return headers


print("\n=== 3. Client oqimi ===")
resp = client.post("/api/v1/client/handshake/",
                   data=json.dumps({"app_version": "1.0.0", "monitors": 1}),
                   content_type="application/json", **signed("/api/v1/client/handshake/"))
data = body(resp)
check("handshake 200", resp.status_code == 200, f"{resp.status_code} {data}")
check("config keldi", "config" in data.get("data", {}))

# JWT'siz so'rov rad etilishi kerak
resp = client.post("/api/v1/client/handshake/", data="{}", content_type="application/json",
                   HTTP_X_DEVICE_ID=device.device_id)
check("JWT'siz so'rov rad etildi", resp.status_code == 401, str(resp.status_code))

# Ruxsati yo'q xodim ham o'tmasligi kerak (admin'da client.* bor, shuning uchun
# ataylab ruxsatsiz rol bilan sinaymiz)
noop, _ = User.objects.get_or_create(username="smoke_watcher", defaults={"is_active": True})
noop.set_password("SmokeW!2026")
noop.role = Role.objects.filter(name="Kuzatuvchi").first()
noop.save()
w_access = body(client.post("/api/v1/auth/login/",
    data=json.dumps({"username": "smoke_watcher", "password": "SmokeW!2026"}),
    content_type="application/json")).get("data", {}).get("access", "")
resp = client.post("/api/v1/client/handshake/", data="{}", content_type="application/json",
                   HTTP_X_DEVICE_ID=device.device_id,
                   HTTP_AUTHORIZATION=f"Bearer {w_access}")
check("client.operate'siz rad etildi", resp.status_code == 403, str(resp.status_code))

exam = Exam.objects.filter(is_active=True, deleted_at__isnull=True).first()

# Kirish oynasi ochiq bo'lishi SHART — aks holda JSHSHIR qidiruvi rad etiladi.
# Test DB holatiga bog'liq bo'lmasligi uchun jadvalni o'zimiz ta'minlaymiz.
from apps.exams.models import ExamSchedule  # noqa: E402

_today = timezone.localdate()
_start = timezone.make_aware(datetime.combine(_today, dtime(0, 5)))
_end = timezone.make_aware(datetime.combine(_today, dtime(23, 55)))
ExamSchedule.objects.update_or_create(
    exam=exam, zone=None, exam_date=_today,
    defaults={"starts_at": _start, "ends_at": _end,
              "checkin_lead_minutes": 60, "is_active": True, "deleted_at": None},
)
check("bugungi kirish oynasi ochiq",
      any(s.is_open() for s in ExamSchedule.objects.filter(exam=exam, exam_date=_today)))
path = "/api/v1/client/candidate/lookup/"
resp = client.post(path, data=json.dumps({"pinfl": "31234567890123", "exam_id": exam.pk}),
                   content_type="application/json", **signed(path))
data = body(resp)
check("candidate lookup 200", resp.status_code == 200, f"{resp.status_code} {data}")
challenge = data.get("data", {}).get("challenge", "")
check("challenge qaytdi", bool(challenge))
check("JSHSHIR niqoblangan",
      "*" in data.get("data", {}).get("candidate", {}).get("masked_pinfl", ""))

# Noto'g'ri JSHSHIR validatsiyasi
resp = client.post(path, data=json.dumps({"pinfl": "123", "exam_id": exam.pk}),
                   content_type="application/json", **signed(path))
check("noto'g'ri JSHSHIR rad etildi", resp.status_code == 400, str(resp.status_code))

dim = settings.PROCTORING["FACE_EMBEDDING_DIM"]
embedding = [0.05] * dim
path = "/api/v1/client/face/verify/"
resp = client.post(path, data=json.dumps({"challenge": challenge, "embedding": embedding,
                                          "faces_detected": 1}),
                   content_type="application/json", **signed(path))
data = body(resp)
check("face verify 201", resp.status_code == 201, f"{resp.status_code} {data}")
session_token = data.get("data", {}).get("proctoring_session_token", "")
check("sessiya tokeni qaytdi", bool(session_token))

# Operator tasdiqlamaguncha imtihon OCHILMASLIGI kerak.
path = "/api/v1/client/exam/access/"
resp = client.post(path, data="{}", content_type="application/json",
                   **signed(path, session_token))
check("tasdiqsiz exam access rad etildi", resp.status_code == 403,
      f"{resp.status_code} {body(resp)}")
check("xato kodi identity_not_confirmed",
      body(resp).get("error", {}).get("code") == "identity_not_confirmed", str(body(resp)))

print("\n=== 3b. Operator shaxsni tasdiqlaydi ===")
path = "/api/v1/client/identity/confirm/"
# JWT'siz — ruxsat bo'lmasligi kerak
resp = client.post(path, data=json.dumps({"decision": "confirm", "document_type": "passport",
                                          "document_number": "AA1234567"}),
                   content_type="application/json",
                   HTTP_X_DEVICE_ID=device.device_id, HTTP_X_PROCTORING_SESSION=session_token)
check("JWT'siz tasdiq rad etildi", resp.status_code in (401, 403),
      f"{resp.status_code} {body(resp)}")

# Hujjatsiz tasdiq — validatsiya
resp = client.post(path, data=json.dumps({"decision": "confirm"}),
                   content_type="application/json", **signed(path, session_token))
check("hujjatsiz tasdiq rad etildi", resp.status_code == 400, str(resp.status_code))

resp = client.post(path, data=json.dumps({"decision": "confirm", "document_type": "passport",
                                          "document_number": "AA1234567",
                                          "note": "Hujjat rasmi mos"}),
                   content_type="application/json", **signed(path, session_token))
data = body(resp)
check("tasdiq 200", resp.status_code == 200, f"{resp.status_code} {data}")
check("operator qayd etildi",
      data.get("data", {}).get("identity", {}).get("by") == "smoke_operator", str(data))

# Ikkinchi marta tasdiqlash — audit izini qayta yozib bo'lmaydi
resp = client.post(path, data=json.dumps({"decision": "confirm", "document_type": "passport",
                                          "document_number": "BB7654321"}),
                   content_type="application/json", **signed(path, session_token))
check("qayta tasdiqlash bloklandi", resp.status_code == 409, str(resp.status_code))
check("identity_confirm audit yozildi",
      AuditLog.objects.filter(action="identity_confirm").exists())

print("\n=== 3c. Tasdiqdan keyin imtihon ochiladi ===")
path = "/api/v1/client/exam/access/"
resp = client.post(path, data="{}", content_type="application/json",
                   **signed(path, session_token))
data = body(resp)
check("exam access 200", resp.status_code == 200, f"{resp.status_code} {data}")
check("WebView policy bor", "webview_policy" in data.get("data", {}))
check("tashqi platforma tokeni keldi",
      bool(data.get("data", {}).get("platform_session_token")), str(data)[:160])
check("bizning token bilan chalkashmadi",
      data.get("data", {}).get("platform_session_token") != session_token)
check("token URL'da emas", "token=" not in str(data.get("data", {}).get("login_url", "")))

path = "/api/v1/client/events/"
events = [{"type": "window_blur", "severity": 2, "occurred_at": "2026-08-07T10:00:00Z",
           "payload": {"duration": 3}, "client_event_id": f"e{i}"} for i in range(5)]
events.append({"type": "rdp_detected", "severity": 4,
               "occurred_at": "2026-08-07T10:01:00Z", "payload": {"process": "AnyDesk.exe"}})
resp = client.post(path, data=json.dumps({"events": events}),
                   content_type="application/json", **signed(path, session_token))
data = body(resp)
check("events 202", resp.status_code == 202, f"{resp.status_code} {data}")
check("6 ta hodisa qabul qilindi", data.get("data", {}).get("accepted") == 6)

path = "/api/v1/client/heartbeat/"
resp = client.post(path, data=json.dumps({"monitors": 1, "network_ok": True}),
                   content_type="application/json", **signed(path, session_token))
data = body(resp)
check("heartbeat 200", resp.status_code == 200, f"{resp.status_code} {data}")
risk = data.get("data", {}).get("risk_score", 0)
check("risk_score hisoblandi", risk > 0, f"risk={risk}")

path = "/api/v1/client/face/periodic/"
resp = client.post(path, data=json.dumps({"embedding": embedding, "faces_detected": 1}),
                   content_type="application/json", **signed(path, session_token))
data = body(resp)
check("periodic face 200", resp.status_code == 200, f"{resp.status_code} {data}")
check("server qayta hisobladi", data.get("data", {}).get("score", 0) > 0)

print("\n=== 4. Celery buffer -> PostgreSQL ===")
from apps.proctoring.models import ExamSession, ProctoringEvent  # noqa: E402
from apps.proctoring.tasks import flush_event_buffer, flush_session_state  # noqa: E402

result = flush_event_buffer()
check("event flush ishladi", result["written"] >= 4, str(result))
result = flush_session_state()
check("session state flush", result["updated"] >= 1, str(result))

session = ExamSession.objects.order_by("-id").first()
check("hodisalar DB'da", ProctoringEvent.objects.filter(session=session).count() >= 5)
check("kritik hodisa darhol yozildi",
      ProctoringEvent.objects.filter(session=session, severity=4).exists())
session.refresh_from_db()
check("risk DB'ga ko'chdi", session.risk_score > 0, f"risk={session.risk_score}")

print("\n=== 5. Proktor amallari ===")
resp = client.get(f"/api/v1/sessions/{session.pk}/", **AUTH)
check("sessiya detali 200", resp.status_code == 200, str(resp.status_code))
resp = client.get(f"/api/v1/sessions/{session.pk}/events/", **AUTH)
check("sessiya hodisalari 200", resp.status_code == 200, str(resp.status_code))
resp = client.get("/api/v1/sessions/live/", **AUTH)
check("live monitoring 200", resp.status_code == 200, str(resp.status_code))

resp = client.post(f"/api/v1/sessions/{session.pk}/warn/",
                   data=json.dumps({"message": "Ekranga qarang", "severity": 2}),
                   content_type="application/json", **AUTH)
check("ogohlantirish 200", resp.status_code == 200, f"{resp.status_code} {body(resp)}")

resp = client.post(f"/api/v1/sessions/{session.pk}/terminate/",
                   data=json.dumps({"reason": "Smoke test"}),
                   content_type="application/json", **AUTH)
check("chetlashtirish 200", resp.status_code == 200, f"{resp.status_code} {body(resp)}")

print("\n=== 6. Chetlashtirilgan sessiya darhol bloklanadi ===")
path = "/api/v1/client/heartbeat/"
resp = client.post(path, data="{}", content_type="application/json",
                   **signed(path, session_token))
check("chetlashtirilgandan keyin 404", resp.status_code == 404,
      f"{resp.status_code} {body(resp)}")

print("\n=== 6b. Dasturdan chiqish ===")
path = "/api/v1/client/exit/verify/"

# Viloyat paroli — test o'zinikini yaratadi va oxirida o'chiradi.
_exit_region = zone.region
_exit_row, _exit_created = ClientExitPassword.objects.get_or_create(
    region=_exit_region, defaults={"name": "SMOKE-TEST"}
)
_exit_orig_hash = _exit_row.password
_exit_row.set_password("Viloyat!2026")
_exit_row.is_active = True
_exit_row.save()

resp = client.post(path, data=json.dumps({"password": "notogri"}),
                   content_type="application/json", **signed(path))
check("noto'g'ri parol rad etildi", resp.status_code == 403, str(resp.status_code))
check("kod exit_password_invalid",
      (body(resp).get("error") or {}).get("code") == "exit_password_invalid",
      str(body(resp).get("error")))

resp = client.post(path, data=json.dumps({"password": "SmokeOp!2026"}),
                   content_type="application/json", **signed(path))
check("operator paroli bilan chiqish 200", resp.status_code == 200,
      f"{resp.status_code} {body(resp)}")
check("usul: staff", (body(resp).get("data") or {}).get("method") == "staff",
      str(body(resp).get("data")))
check("chiqish audit yozildi",
      AuditLog.objects.filter(action="client_exit", actor_username="smoke_operator").exists())

# LOGIN QILMASDAN — viloyat paroli. Bu login sahifasidagi yagona yo'l.
resp = client.post(path, data=json.dumps({"password": "Viloyat!2026"}),
                   content_type="application/json",
                   HTTP_X_DEVICE_ID=device.device_id)
check("login qilmasdan viloyat paroli 200", resp.status_code == 200,
      f"{resp.status_code} {body(resp)}")
check("usul: region", (body(resp).get("data") or {}).get("method") == "region",
      str(body(resp).get("data")))

# Boshqa viloyatning paroli O'TMAYDI — hududiy ajratish shu bilan ishlaydi.
_other = Region.objects.exclude(pk=_exit_region.pk).first()
if _other is not None:
    _other_row, _other_created = ClientExitPassword.objects.get_or_create(
        region=_other, defaults={"name": "SMOKE-TEST-2"}
    )
    _other_hash = _other_row.password
    _other_row.set_password("Begona!2026")
    _other_row.is_active = True
    _other_row.save()
    resp = client.post(path, data=json.dumps({"password": "Begona!2026"}),
                       content_type="application/json", HTTP_X_DEVICE_ID=device.device_id)
    check("boshqa viloyat paroli rad etildi", resp.status_code == 403,
          f"{resp.status_code} {body(resp)}")
    if _other_created:
        _other_row.delete()
    else:
        ClientExitPassword.objects.filter(pk=_other_row.pk).update(password=_other_hash)

# Parol umuman sozlanmagan bo'lsa — alohida kod (mashina qulflanib qolmasin).
ClientExitPassword.objects.filter(pk=_exit_row.pk).update(is_active=False)
resp = client.post(path, data=json.dumps({"password": "nimadir"}),
                   content_type="application/json", HTTP_X_DEVICE_ID=device.device_id)
check("parol sozlanmagan -> alohida kod",
      (body(resp).get("error") or {}).get("code") == "exit_password_not_configured",
      str(body(resp).get("error")))

# Parol javobda HECH QACHON qaytmaydi.
resp = client.get("/api/v1/exit-passwords/", **AUTH)
check("chiqish parollari ro'yxati 200", resp.status_code == 200, str(resp.status_code))
_rows = (body(resp).get("data") or {}).get("results") or []
check("javobda parol maydoni yo'q",
      all("password" not in row for row in _rows), str(_rows[:1]))
check("has_password bayrog'i bor",
      all("has_password" in row for row in _rows), str(_rows[:1]))

if _exit_created:
    _exit_row.delete()
else:
    ClientExitPassword.objects.filter(pk=_exit_row.pk).update(
        password=_exit_orig_hash, is_active=True
    )

print("\n=== 7. Audit ===")
from apps.proctoring.models import AuditLog  # noqa: E402

check("terminate audit yozildi",
      AuditLog.objects.filter(action="session_terminate").exists())
check("login audit yozildi", AuditLog.objects.filter(action="login").exists())

print("\n=== 8. Kriptografiya ===")
from apps.common.utils.crypto import (  # noqa: E402
    decrypt, encrypt, hash_token, mask_pinfl, normalize_pinfl, opaque_key,
)

check("shifrlash aylanadi", decrypt(encrypt("kamera-parol")) == "kamera-parol")
check("shifrmatn har safar boshqa", encrypt("test") != encrypt("test"))
check("token hash deterministik", hash_token("abc") == hash_token("abc"))
check("opaque_key deterministik", opaque_key("31234567890123") == opaque_key("31234567890123"))
check("JSHSHIR normallashadi", normalize_pinfl(" 3123-4567 890123 ") == "31234567890123")
check("niqoblash", mask_pinfl("31234567890123") == "3123******0123",
      mask_pinfl("31234567890123"))

print("\n=== 9. Talabgor ma'lumoti sessiyada ===")
session = ExamSession.objects.order_by("-id").first()
check("JSHSHIR sessiyada ochiq", session.pinfl == "31234567890123", str(session.pinfl))
check("F.I.Sh. sessiyada muzlatilgan",
      session.full_name == "Testov Test Testovich", session.full_name)
check("yuz etaloni sessiyaga yozildi", bool(session.reference_embedding))
check("shaxs operator tomonidan tasdiqlangan",
      session.identity_verified, str(session.identity))
check("tasdiqda operator va hujjat qayd etilgan",
      session.identity.get("by") == "smoke_operator"
      and session.identity.get("document_number") == "AA1234567",
      str(session.identity))
check("JSHSHIR bo'yicha qidiruv ishlaydi",
      ExamSession.objects.filter(pinfl__startswith="3123").exists())

print("\n=== 10. Talabgor tarixi ===")
resp = client.get(f"/api/v1/sessions/{session.pk}/history/", **AUTH)
data = body(resp)
check("tarix 200", resp.status_code == 200, f"{resp.status_code} {data}")
check("tarixda shu sessiya bor", data.get("data", {}).get("count", 0) >= 1, str(data))
resp = client.get(f"/api/v1/sessions/?pinfl={session.pinfl}", **AUTH)
check("pinfl bo'yicha filtr", resp.status_code == 200, str(resp.status_code))

_restore_allowed_ip()

print("\n" + "=" * 60)
if FAILURES:
    print(f"XATOLAR ({len(FAILURES)}):")
    for name in FAILURES:
        print(f"  - {name}")
    sys.exit(1)
print("BARCHA TEKSHIRUVLAR MUVAFFAQIYATLI")
