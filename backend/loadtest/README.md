# Yuklama sinovi — model, skriptlar, runbook (maqsad: 5000 talabgor bir smenada)

Belgilar: **[o']** — o'lchangan (qayerda — ko'rsatilgan), **[h]** — hisoblangan (formula).
Lokal o'lchovlar: Windows 11, i9-10900K (20 mantiqiy yadro), PostgreSQL 17 + Redis 7 lokal,
Django `runserver` (BITTA jarayon) — production sig'imi haqida xulosa EMAS, faqat
so'rov narxi va skriptlarni tekshirish uchun.

## 1. Fayllar

| Fayl | Vazifa |
|---|---|
| `locustfile.py` | `ExamClient` (to'liq client oqimi + barqaror holat + `ws/client`), `PanelUser` (proktor + `ws/monitor`), `ProctoringShape` (stages/storm/steady/finish/reconnect) |
| `payloads.py` | sintetik tanalar: skrinshot 1920 px q80 progressiv, yuz kadri 1280x720 q85, hujjat surati, 512-float embedding, hodisalar |
| `server/stub_platform.py` | tashqi platforma (`?imie=`) va ntest (`POST /api/v1/exam/session-result`) stub'i, kechikish/xato sozlanadi |
| `server/loadtest_settings.py` | LOKAL ajratilgan sozlama: baza `proctoring_loadtest`, Redis 6–10, production throttle qiymatlari, `TRUSTED_PROXY_COUNT=1` |
| `tools/profile_endpoints.py` | har endpoint narxi: vaqt, SQL (turi bo'yicha), Redis buyruqlari, `group_send`, so'rov/javob hajmi |
| `tools/stage_report.py` | `*_by_stage_*.json` -> bosqich bo'yicha CSV/HTML (p50/p95/p99, RPS, xato %, SLO belgisi) |
| `tools/local_stack.ps1` | lokal stend (stub + HTTP 8012 + WS 8013 + Celery) start/stop |
| `results/endpoint_profile.json` | [o'] endpoint profili (20 oqim, concurrency 1) |
| `results/local_run1/` | [o'] lokal Locust natijasi (20→50→100) |
| `../src/apps/common/management/commands/seed_loadtest.py`, `cleanup_loadtest.py` | sintetik ma'lumot (7500) va to'liq tozalash, idempotent, `--allow-db` himoyasi |

Sintetik ma'lumot: JSHSHIR `99999xxxxxxxxx`, ism "Nomzod Test NNNN", bino NAT IP `100.64.<b>.1`
(CGNAT — marshrutlanmaydi, Python uni xususiy deb hisoblamaydi), MAC `02:4C:54:...`.

## 2. Bitta sessiya profili [o' `results/endpoint_profile.json`]

| Bosqich | So'rov | Tana, B | Javob, B | SQL S/I/U | Median ms |
|---|---|---|---|---|---|
| ishga tushish | preflight + access-attempt | 28 + 235 | 354 + 41 | 6/0/0 | 8 + 4 |
| login | auth/login | 59 | 1243 | 5/2/1 | **746** (PBKDF2 1.2M iter = 0.75 s CPU [o']) |
| handshake | client/handshake | 533 | 4898 | 7/0/2 | 11 |
| tayyorgarlik | presence, camera/config, camera/check, exam/config | ≤341 | ≤4135 | 19/0/2 | 6–8 |
| JSHSHIR | candidate/lookup (+platforma) | 133 | **18 398** | 9/0/0 | 17 (+platforma kechikishi) |
| FaceID | face/attempt (20%) / face/verify | 141 282 / 152 681 | 101 / 270 | 6/1/0 / 6/2/3 | 16 / 23 |
| shaxs | identity/confirm, exam/access, proctoring/start | ≤23 | ≤977 | 15/2/5 | 8–12 |
| barqaror | heartbeat (30 s) | 103 | 140 | 5/0/**1** | 11 |
| barqaror | presence in_exam (45 s) | 17 | 132 | 4/0/1 | 7 |
| barqaror | events (5 s, bo'sh bo'lsa yo'q): 1 / 10 / 50 ta sev2 | 176/1652/8212 | 52 | 5/0/0 | 18 / 79 / **351** |
| barqaror | screenshots/upload (har javob) | 293 101 (sintetik) | 259 | 7/1/0 | 17 |
| barqaror | face/periodic (faqat xato, 10 s da tekshiruv) | 127 907 | 129 | 5/2/0 | 25 |
| barqaror | auth/refresh (30 daq) | 282 | 595 | 7/2/0 | 6 |
| yakun | recordings + session/finish | 371 + 33 | 62 + 322 | 13/2/5 | 10 + 25 |

Skrinshot hajmi: sintetik zich matnli sahifa **270–308 KB [o' payloads.py]**; client kodidagi
o'lchov **157 KB** (`client/services/screen_capture.py:316` izohi). Model ikkalasini beradi.

## 3. 5000 talabgor — jami [h]

Chastotalar koddan: heartbeat 30 s (`Setting.heartbeat_interval`), presence 45 s
(`PRESENCE_PING_INTERVAL`, imtihon davomida HAM — `client/main_window.py:326-350`),
events 5 s, `ws/client` ping 25 s, davriy FaceID 10 s, JWT 30 daq, 100 savol / 180 daq.
Noma'lum parametrlar ochiq: `p_ev` — 5 s oynada hodisa bo'lish ehtimoli, `p_fail` — davriy
FaceID xatosi ulushi (modelda 0.2 va 0.02; staging'da real client log'idan o'lchang).

| Stsenariy | RPS | Kiruvchi trafik | DB | Boshqa |
|---|---|---|---|---|
| Barqaror (180 daq) | heartbeat 167 + presence 111 + skrinshot 46–51 + events 1000·p_ev (=200) + face 500·p_fail (=10) + refresh 3 ≈ **540** | skrinshot 46.3/s × 157–293 KB = **58–109 Mbit/s**; face 10 Mbit/s; jami ≈ 70–120 Mbit/s | UPDATE ≈ 278 (DeviceToken har heartbeat/presence) + 83 (Computer, 1/daq) = **~360/s**; INSERT 46/s skrinshot + face 20/s; SELECT ≈ 5×540 = **~2700/s**; hodisalar Celery `bulk_create` 5 s da | `ws/client` 5000 ulanish, 200 ping/s; disk **26–49 GB/soat**, smenada 78–147 GB |
| Login bo'roni (5000 × ~14.2 so'rov) | 60 s: **1183**; 300 s: **237** | FaceID 181 KB/kishi → 60 s: 121 Mbit/s, 300 s: 24 Mbit/s | 60 s: SELECT ~5750/s, INSERT ~520/s, UPDATE ~1080/s | **PBKDF2: 5000×0.75 s = 3750 yadro·s** → 60 s da 62 yadro (20 bor — imkonsiz), 300 s da 12.5 yadro (63%); platforma: 83/s (60 s) yoki 17/s; thread = tezlik × kechikish |
| Yakun cho'qqisi (60 s) | recordings+finish 2×83 = 167 | — | UPDATE ~420/s | 5000 `report_session_result` -> ntest |
| Panel (50 proktor) | live 5 + dashboard 6.7 + tafsilot 5 + ro'yxat ≈ **20** | seats javobi 298 KB [o'] | `device-tokens` sahifasi 30 SELECT [o'] | 50 `ws/monitor` |
| Reconnect (60 s uzilish) | WS jittersiz: 5000 ulanish **bitta soniyada** (backoff 1,2,4,8,15,30 — tasodifsiz, `client/services/realtime.py:55`); jitter ±50% bilan ~167/s. HTTP: hodisa backlog'i 5 s ichida 1000 rps; skrinshot navbati 46/s×60 s ≈ 2780 kadr → ~15 s da ≈ 185 rps ≈ **300 Mbit/s** | | | |

Gunicorn: `(2×20+1)=41` worker × 8 thread = **328 parallel so'rov** va shuncha DB ulanishi
(`CONN_MAX_AGE`) — PgBouncer shart. Talablar (o'lchanmagan, ochiq savol): ilova serveri tarmog'i
≥ 300 Mbit/s cho'qqi (tavsiya 1 Gbit/s), disk ≥ 15 MB/s barqaror yozish + 40 MB/s cho'qqi, ≥ 150 GB bo'sh joy smenaga.

## 4. Vosita: Locust

Jamoa Python'da, `payloads.py` va manifest server kodi bilan bir tilda; multipart va WS
(`websocket-client`, gevent) oddiy; `FastHttpUser` bir yadroda ~1–3 ming RPS, 7500 foydalanuvchi
asosan kutadi (≈0.1 RPS/foydalanuvchi) — 2–3 generator yetadi; `--master/--worker` taqsimlangan
rejim. k6 samaraliroq, lekin JS va payload/model kodini ikki tilda yuritish kerak bo'lardi.

## 5. Lokal ishga tushirish (skriptni tekshirish)

```powershell
cd backend
$env:PYTHONPATH="loadtest\server"; $env:DJANGO_SETTINGS_MODULE="loadtest_settings"
$env:CELERY_BROKER_URL="redis://127.0.0.1:6379/8"   # .env dagi dev brokeri Celery'da USTUN!
.venv\Scripts\python.exe manage.py migrate; .venv\Scripts\python.exe manage.py setup_partitions --apply --days 3
.venv\Scripts\python.exe manage.py seed_base_data
.venv\Scripts\python.exe manage.py seed_loadtest --users 7500 --allow-db proctoring_loadtest --manifest loadtest\results\manifest.json
powershell -File loadtest\tools\local_stack.ps1 start
cd loadtest; python -m venv .venv; .venv\Scripts\pip install -r requirements.txt
$env:LT_HTTP_CLIENT="requests"   # runserver geventhttpclient bilan GET'da ulanishni uzadi
.venv\Scripts\locust -f locustfile.py --headless --host http://127.0.0.1:8012 --lt-scenario stages `
  --lt-stages 20,50,100 --lt-stage-minutes 1.5 --lt-spawn-rate 5 --lt-exam-minutes 4 --lt-questions 20 `
  --lt-think-scale 0.1 --lt-proctors 3 --csv results/local_run1/lt --html results/local_run1/lt.html
..\.venv\Scripts\python.exe tools\stage_report.py results/local_run1/lt
powershell -File tools\local_stack.ps1 stop
```
Har yurishdan OLDIN: `cleanup_loadtest --keep-seed --yes` + `seed_loadtest` (yakun bronni bo'shatadi).
DIQQAT: toza bazada `setup_partitions --apply` `proctoring_event` ni 5 ustunsiz yaratadi (6-bo'lim, 1-muammo) —
tuzatilguncha lokal bazaga ustunlarni qo'lda qo'shing.

## 6. Staging (production nusxasi) — runbook

1. **Topologiya**: ilova serveri (20 yadro/15 GB, production bilan bir xil systemd/nginx/gunicorn/uvicorn/Celery,
   `config.settings.production`), ALOHIDA DB serveri (PostgreSQL + PgBouncer, production spetsifikatsiyasi),
   ≥3 yuklama generatori (har biri 8 yadro; ilova serverida HECH QACHON), stub platforma — generatorlardan birida.
   Production'ga va haqiqiy platforma/ntest'ga so'rov YO'Q: `Exam.site_url` va `BASE_API_URL` stub'ga.
2. **IP va throttling**: production throttle kaliti — manba IP (preflight 30/min, access-attempt 30/min,
   login IP+login 10/min). Haqiqatda bino = bitta NAT IP. Staging nginx'da FAQAT generator manzillaridan
   `set_real_ip_from <gen_ip>; real_ip_header X-Real-IP;` (generator `--lt-real-ip 1` bilan bino IP'sini yuboradi),
   `TRUSTED_PROXY_COUNT=1`. Natija: throttle va `AllowedPublicIp` production'dagi kabi bino bo'yicha ishlaydi.
   Bu sozlama production'ga KO'CHIRILMAYDI (aks holda IP'ni istalgan client soxtalaydi).
3. **Ma'lumot**: `migrate`, `setup_partitions --apply --days 30`, `seed_base_data`,
   `seed_loadtest --users 7500 --allow-db <staging_db> --platform-url http://<stub>:8099/api/check --manifest manifest.json`;
   manifestni generatorlarga nusxalang.
4. **Bosqichlar** (master + 3 worker):
   `locust -f locustfile.py --master --expect-workers 3 --headless --host https://<staging> --lt-scenario stages --lt-stages 500,1000,2500,5000,7500 --lt-stage-minutes 15 --lt-spawn-rate 20 --lt-worker-stride 3 --lt-proctors 50 --csv results/stg/lt --html results/stg/lt.html`;
   worker: `locust -f locustfile.py --worker --master-host <m> --lt-worker-stride 3 ...` (bir xil `--lt-*`).
   So'ng `storm` (`--lt-storm-users 5000 --lt-storm-seconds 60`, keyin 300), `finish`
   (`--lt-finish-at-minutes 20`), `reconnect` (`--lt-reconnect-jitter 0` va `1`), stub kechikishi 150 ms / 1 s / 5 s.
5. **Kuzatish**: `backend/deploy/MONITORING.md` (L2) bo'yicha — CPU/RAM/swap, gunicorn thread bandligi,
   PgBouncer `cl_waiting`, Postgres ulanish/lock/WAL, Redis `proctoring:events` lag va PEL, `:dead` oqimi,
   Celery navbati, disk yozish/IOPS, tarmoq Mbit/s, `ws` ulanishlar soni.
6. **Tozalash**: `cleanup_loadtest --allow-db <db> --yes` (Celery ishlab turganda, 15 s kutib).

### SLO jadvali (to'ldiring)

| Foydalanuvchi | RPS | p95 login/lookup | p95 heartbeat | Xato % | CPU o'rt. | RAM | Swap | Natija |
|---|---|---|---|---|---|---|---|---|
| 500 | | < 2 s | < 500 ms | < 0.1 | < 70% | < 80% | 0 | |
| 1000 | | | | | | | | |
| 2500 | | | | | | | | |
| 5000 | | | | < 0.1 | | | | |
| 7500 | | | | yiqilmaslik | | | | |
| Sinovdan keyin | — | — | — | — | bazaviy | bazaviy | 0 | ulanishlar bazaviyga qaytdi |

### Sinov kuni tavsiyalari
- Kirishni binolar bo'yicha guruhlarga bo'ling (masalan 10 daqiqada 1000 kishi) — PBKDF2 va FaceID
  yuklamasi [h] 60 s da ko'tarib bo'lmaydi; client'larni 30–60 daqiqa oldin ishga tushirib, operatorlarni oldindan login qildiring.
- Isitish: 15 daqiqa oldin `/healthz/`, `/readyz/`, 20–50 sinov oqimi; stub emas — platforma javob vaqtini tekshiring.
- Zaxira: platforma sekinlashsa circuit breaker ochiladi (10 xato/60 s) — kirish to'xtaydi; qaror tartibi va
  rollback (oldingi reliz, `deploy.sh`) oldindan yozilgan bo'lsin; Celery beat faqat BITTA.
