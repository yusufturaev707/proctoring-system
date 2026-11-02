"""
"Yuborilgan = bazadagi" tekshiruvi (SLO: dalil yo'qolmaydi).

Locust har worker'da server QABUL QILGAN (2xx) hodisa, savol kadri va
sessiyalarni `<csv>_accepted_<worker>.json` ga yozadi (`locustfile.ACCEPTED`).
Bu skript ularni jamlab, bazadagi son bilan solishtiradi. Sinov tugagach
Celery ingest buferni yozib ulgurishi kerak — skript Redis oqimi bo'shaguncha
(`lag` + `pending` = 0) kutadi.

    cd backend
    .venv\\Scripts\\python.exe loadtest\\tools\\verify_accepted.py loadtest\\results\\smoke10\\lt --since "2026-11-02 11:15"

Staging'da: `DJANGO_SETTINGS_MODULE=config.settings.production` va o'sha bazaga
ulanish bilan, manifest sinov oralig'i (`--since`) bilan. Sintetik sessiyalar —
JSHSHIR `99999...` (`seed_loadtest.PINFL_PREFIX`).

Hodisa — faqat client yuborgani (`client_event_id <> ''`); server o'zi
yaratadigan hodisalar (`high_suspicion_identity` va h.k.) sanalmaydi.
Skrinshot — (sessiya, savol) juftligi: qayta javob kadri qatorni almashtiradi,
ya'ni qabul qilingan yuklashlar soni emas, noyob juftliklar solishtiriladi.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
sys.path.insert(0, str(BACKEND / "src"))
sys.path.insert(0, str(HERE.parents[0] / "server"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "loadtest_settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.utils import timezone  # noqa: E402

from apps.common.redis_client import get_redis  # noqa: E402
from apps.proctoring.models import ExamSession, ProctoringEvent, ProctoringScreenshot  # noqa: E402
from apps.proctoring.services.stream import CONSUMER_GROUP, dead_letter_key  # noqa: E402

PINFL_PREFIX = "99999"


def _stream_backlog(client, stream: str, since_ms: int) -> tuple[int, int, int]:
    """
    (lag, pending, dead) — guruh yo'q bo'lsa (0, 0, dead).

    `dead` — faqat sinov boshidan keyin tushganlari (yozuv ID'si = ms vaqt):
    oqim tozalanmaydi va oldingi yurishlarning izi natijani buzardi.
    """
    lag = pending = 0
    try:
        for group in client.xinfo_groups(stream):
            name = group.get("name")
            name = name.decode() if isinstance(name, bytes) else name
            if name == CONSUMER_GROUP:
                lag = int(group.get("lag") or 0)
                pending = int(group.get("pending") or 0)
    except Exception:  # noqa: BLE001 — oqim hali yaratilmagan
        pass
    dead = len(client.xrange(dead_letter_key(stream), min=f"{since_ms}-0", max="+"))
    return lag, pending, dead


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_prefix", help="Locust --csv prefiksi (masalan results/run/lt)")
    parser.add_argument("--since", required=True, help="Sinov boshlangan vaqt (YYYY-MM-DD HH:MM, mahalliy)")
    parser.add_argument("--wait", type=float, default=120.0, help="Oqim bo'shashini kutish (s)")
    args = parser.parse_args()

    files = glob.glob(f"{args.csv_prefix}_accepted_*.json")
    if not files:
        print(f"Fayl topilmadi: {args.csv_prefix}_accepted_*.json")
        return 2
    sent = {"events": 0, "screenshots": 0, "sessions_started": 0, "sessions_finished": 0}
    for path in files:
        for key, value in json.loads(Path(path).read_text(encoding="utf-8")).items():
            sent[key] = sent.get(key, 0) + int(value)

    since = timezone.make_aware(datetime.strptime(args.since, "%Y-%m-%d %H:%M"))
    since_ms = int(since.timestamp() * 1000)
    stream = settings.PROCTORING["EVENT_STREAM_KEY"]
    client = get_redis()
    deadline = time.time() + args.wait
    while True:
        lag, pending, dead = _stream_backlog(client, stream, since_ms)
        if lag + pending == 0 or time.time() > deadline:
            break
        time.sleep(2)

    sessions = ExamSession.objects.filter(pinfl__startswith=PINFL_PREFIX, created_at__gte=since)
    stored = {
        "events": ProctoringEvent.objects.filter(session__in=sessions).exclude(client_event_id="").count(),
        "screenshots": ProctoringScreenshot.objects.filter(session__in=sessions).count(),
        "sessions_started": sessions.exclude(started_at=None).count(),
        "sessions_finished": sessions.exclude(finished_at=None).count(),
    }

    ok = True
    print(f"{'':20} {'qabul (Locust)':>15} {'bazada':>10}  natija")
    for key in sent:
        verdict = "OK" if stored[key] >= sent[key] else f"YO'QOLDI {sent[key] - stored[key]}"
        ok &= stored[key] >= sent[key]
        print(f"{key:20} {sent[key]:>15} {stored[key]:>10}  {verdict}")
    print(f"Redis {stream}: lag={lag} pending={pending} dead={dead}")
    if lag + pending:
        ok = False
        print(f"DIQQAT: oqim {args.wait:.0f} s ichida bo'shamadi — Celery ingest ishlayaptimi?")
    if dead:
        ok = False
        print("DIQQAT: :dead oqimida yozuv bor — `manage.py` dead_letters bilan tekshiring")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
