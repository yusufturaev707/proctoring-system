# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Til

Kod izohlari, docstring'lar va UI matnlari **o'zbek tilida**. Izoh "nima
qilinyapti"ni emas, **"nima uchun aynan shunday"**ni tushuntiradi — deyarli
har bir arxitektura qarori mavjud fayllarda izohda asoslangan. Bu faylda
qoida va qisqa sabab turadi; to'liq tarix — kod izohlarida va git'da.

## Buyruqlar

Backend buyruqlari `backend/` dan (`manage.py` `src/` ni `sys.path` ga o'zi
qo'shadi). Virtual muhit: `backend/.venv`.

```bash
# Backend (Windows)
cd backend && .venv/Scripts/activate
python manage.py migrate
python manage.py setup_partitions --apply --days 30   # proctoring_event partitsiyalari
python manage.py seed_base_data --demo                # rol/ruxsat matritsasi + demo data
python manage.py runserver 8002                       # HTTP API

# WebSocket — ALOHIDA process, `src/` dan
cd backend/src && uvicorn config.asgi:application --port 8003

# Celery — `backend/` dan
celery -A config worker -Q ingest -c 4
celery -A config worker -Q maintenance,default -c 2
celery -A config beat                                 # AYNAN BITTA instansiya

# Frontend
cd frontend && npm install && npm run dev             # :5173, /api va /ws proxy qilinadi
npm run build
```

* **Windows'da Celery `threads` pool bilan** (`config/celery.py` o'zi
  qo'yadi, `-P` ustun). `prefork` Windows'da vazifalarni JIMGINA
  bajarmaydi (`inspect stats` da `"total": {}`). Belgilari: sessiya
  "aloqa yo'q" bo'ladi, xavf balli faqat yakunda chiqadi, Redis
  `proctoring:events` da `lag` o'sadi.
* `DJANGO_SETTINGS_MODULE` standarti `config.settings.local`. **`.env`
  kirish nuqtalarida sozlama tanlanishidan OLDIN yuklanadi**
  (`config/env.py` → `manage.py`, `wsgi.py`, `asgi.py`, `celery.py`);
  muhit o'zgaruvchisi (systemd `Environment=`, `--settings`) har doim ustun.
* **Production deploy — `backend/deploy/`**: `deploy.sh` (takroriy,
  atomik frontend, `check --deploy --fail-level WARNING`),
  `env.production.example`, `systemd/` (5 servis + `proctoring.target`),
  `nginx.conf.example` + `proxy_common.conf`; tartib — `deploy/README.md`.
  Statik fayllar `STORAGES` orqali (`STATICFILES_STORAGE` Django 5.1 da
  yo'q). Frontend API/WS'ni sahifaning o'z manzilidan oladi
  (`.env.production` bo'sh qiymatlari `.env.local` dan ustun).
* Muhitlar: `local` (throttling o'chiq, `REQUIRE_DEVICE_ID=false`,
  BrowsableAPI), `production` (majburiy sirlarni ishga tushishda
  tekshiradi), `test` (locmem cache, in-memory channel layer, eager
  Celery, throttling o'chiq).

### Test

```bash
cd backend
python manage.py test --settings=config.settings.test          # hammasi
python manage.py test apps.proctoring --settings=config.settings.test
cd backend && python scripts/smoke_test.py                     # end-to-end
cd client && venv/Scripts/python -m unittest discover -s tests # client sof mantig'i
```

* Label berilmasa `apps` paketi qidiriladi (`config/test_runner.py`) —
  standart runner hech narsa topmay "o'tdi" derdi.
* **PostgreSQL kerak.** Redis ixtiyoriy: unga tayanadigan testlar
  `skip` bo'ladi (`apps/common/tests/utils.py:RedisStateMixin`). Test
  Redis'i **15-baza** (dev — 2-baza).
* Testlar: `apps/<app>/tests/test_*.py`; yasovchilar —
  `apps/proctoring/tests/factories.py`.
* **`smoke_test.py` barcha `ExamSession` yozuvlarini va `sess:*` Redis
  kalitlarini o'chiradi** — faqat dev bazasida. Unda absolyut yo'l
  (`C:\Projects\...`) hardcode.
* `.env` test sozlamalariga ham o'tadi. Muhitga xos bayroqlarni
  (`REQUIRE_COMPUTER_BOOKING`, `ALLOW_PRIVATE_SOURCE_IP`,
  `REQUIRE_DEVICE_ID`) `settings/test.py` O'ZI mahkamlaydi — yangi
  shunday bayroqni ham u yerda mahkamlang; `.env` da muhitga xos
  kalitni bo'sh qoldiring.
* `npm run lint` bor, lekin `frontend/` da ESLint konfiguratsiyasi YO'Q.

## Arxitektura

### To'rt process, uch ma'lumot qatlami

HTTP API (WSGI), WebSocket (ASGI/Channels), Celery `ingest`, Celery `beat`
alohida ishlaydi — yuklama profillari mos kelmaydi.

**Ikki bosqichli yozish**: client so'rovi Redis Stream'ga `XADD` qilinadi
va darhol javob oladi; Celery har 5 s da buferni `bulk_create` bilan bitta
tranzaksiyada yozadi. Yangi yuqori chastotali endpoint DB'ga to'g'ridan-
to'g'ri yozmaydi — shu yo'ldan (`proctoring/services/ingest.py` +
`services/stream.py`).

* **Hot** — Redis: sessiya holati, heartbeat, hisoblagichlar
  (`proctoring/services/state.py`, write-behind 10 s da bir marta)
* **Warm** — skrinshot, dalil va yuz rasmlari
* **Cold** — PostgreSQL: sessiya, hodisa, audit (huquqiy dalil)

Kritik hodisalar (chetlashtirish, FaceID xatosi, `CRITICAL` jiddiylik)
write-behind EMAS — darhol DB'ga.

**Redis o'chsa imtihon to'xtamaydi** (`tests/test_redis_outage.py`):
sessiya tokeni DB'dan (`SessionTokenAuthentication`, `RedisError` →
`_from_database`), heartbeat `last_heartbeat_at` ga to'g'ridan-to'g'ri,
hodisalar DB'ga, yakun Redis'ni tozalamasdan. Zaxirasiz yo'l — 503 +
tasodifiy `Retry-After` (`BackendUnavailable`, DB `OperationalError` ham),
500 emas. Yangi client yo'li Redis'ga tayansa, shu qoidaga moslang.

**`close_stale_sessions` DB vaqtiga ishonmaydi**: `last_heartbeat_at` ni
faqat ingest ishchisi yozadi, u to'xtasa barcha sessiyalar "eskiradi".
Yopishdan oldin Redis `hb` tekshiriladi (tirigi yopilmaydi, DB vaqti
tuzatiladi); Redis ishlamasa shu yurishda hech kim yopilmaydi.

`services/stream.py` uch yo'qotish stsenariysini qamraydi: `XAUTOCLAIM`
bilan osilgan PEL yozuvlari, batch yiqilsa qator-ma-qator yozish, yozib
bo'lmaganini `:dead` oqimiga ko'chirish. **Soddalashtirmang** — "dalil
yo'qoldi" holati bo'lmasligi kerak.

### Skrinshot storage — IKKI yo'l

Ikkalasi parallel yashaydi, o'rnatish profiliga qarab bittasi yoqiladi
(production'da kamida bittasi — `production.py` tekshiradi):

| | S3/MinIO | Fayl tizimi |
|---|---|---|
| Model | `ScreenshotMeta` (`object_key`) | `ProctoringScreenshot` (`file_path`) |
| Yuklash | `client/screenshots/presign/` + `commit/` | `client/screenshots/upload/` |
| Binary backenddan | **o'tmaydi** (presigned PUT) | **o'tadi** (multipart) |
| Ko'rsatish | presigned GET URL | `screenshots/{id}/file/` → `X-Accel-Redirect` |
| Retention | `purge_expired_artifacts` (`purge_after`) | `purge_expired_screenshots` (`captured_at`) |
| Ko'lami | 10 000 client | ~bitta bino (~500 client) |
| Yoqish | `S3_ENABLED=true` | `SCREENSHOT_FILESYSTEM_ENABLED=true` |

**Fayl tizimi qoidalari** (dalil va FaceID rasmlariga ham tegishli):

* **DB'da faqat nisbiy yo'l** (root `SCREENSHOT_STORAGE["ROOT"]`) — root
  ko'chsa buzilmaydi va server strukturasi oshkor bo'lmaydi.
* **Fayl turi baytlardan** (Pillow), `Content-Type`/kengaytmadan emas —
  aks holda saqlangan XSS.
* **Yozish: avval fayl, keyin qator** (qator yozilmasa fayl o'chiriladi).
  **O'chirish: avval fayl, keyin qator** (`screenshot_delete`).
* **Storage'ga faqat interfeys orqali** (`common/screenshot_storage.py`:
  `save`/`delete`/`exists`/`serve`/`prune_empty_dirs`). Service/view
  ichida `open()`/`os.unlink()` yozmang.
* **`serve` HTTP javob qaytaradi** (`X-Accel-Redirect`, baytlar Python'dan
  o'tmaydi). Dev'da `SCREENSHOT_SERVE_DIRECTLY=true` (production'da taqiq).
  nginx `internal` location'siz himoya yo'q — `deploy/nginx.conf.example`.

Panel IKKALA ro'yxatni so'raydi (`SessionDetail.jsx`: `screenshots/` +
`stored-screenshots/`, `captured_at` bo'yicha birlashtiriladi). Fayl
tizimidagi rasm blob sifatida olinadi (`screenshotFile`) — `<img>`
`Authorization` qo'shmaydi.

Client (`client/services/screen_capture.py`) qaysi yo'l yoqilganini
oldindan bilmaydi: sessiya boshida `presign/` 503 qaytarsa fayl tizimi
yo'liga o'tadi. Bu shartnomani buzmang.

**Skrinshot taymersiz — test platformasi buyurganda** (`controls.0013`
`screenshot_interval`/`dedup_threshold` ni olib tashladi). Talabgor javob
belgilaganda platforma `POST http://localhost:8050/api/capture_screen`
yuboradi. Buyruq kadri DEDUP QILINMAYDI. Kadr mashinada HAR DOIM
saqlanadi; serverga yuborish — `Setting.is_screenshot_upload`.

`screen_capture.py` da uch mustaqil bosqich: olish (UI thread, kamera kadri
bilan bir lahzada) → kodlash + mahalliy arxiv (fon) → yuklash (fon, bitta
uchuvchi so'rov, xatoda 15 s dan keyin qayta). Kadr hech qachon tashlanmaydi.
Arxiv konteksti BUYRUQ paytida olinadi (`local_archive.context()`).

**Savol kadri — savolga bitta, qayta belgilansa almashadi.** Tana
`{"q_id": "1", "q_n": "3"}`. Eskisi yangisini hech qachon bosmaydi:

| Qatlam | Qanday |
|---|---|
| mashina | `q003_id1_14-05-33.jpg`; yangi fayl (`.tmp` → `os.replace`), keyin eskilari (`local_archive.save_question_shot`) |
| client navbatlari | shu savolning yuborilmagan kadri tashlanadi |
| server, fayl tizimi | `unique_screenshot_session_question`; qator o'rnida yangilanadi: yangi fayl → qator → eski fayl `on_commit`; eskiroq `captured_at` rad |
| server, S3 | `tasks._drop_replaced_question_shots` (avval obyekt, keyin qator) |

* Kechiktirish (coalescing) YO'Q va qaytarmang — kechikkan kadrda keyingi
  savol turgan bo'lardi. Spam chegarasi lokal xizmatda (20/s, 429).
* `q_id` `[A-Za-z0-9_.-]{1,64}` IKKI TOMONDA bir xil
  (`local_service.QUESTION_ID_RE`, `ScreenshotUploadSerializer`) — fayl
  nomiga boradi. `q_id` siz `q_n` — 400.
* `check_frozen_frames` bitta savoldagi bir xil kadrni anomaliya
  hisoblamaydi; turli savollarda — shubhali.

**Lokal xizmat** (`client/services/local_service.py`, `MainWindow` da,
`http.server` fon thread'ida):

| So'rov | Javob |
|---|---|
| `GET /api/device_info` | `{"machine_uuid", "ip", "mac", "number"}` — SHARTNOMA, kalitlarni o'zgartirmang |
| `POST /api/capture_screen` | 202 darhol; 400 yaroqsiz tana; 409 `no_active_exam`; 429 >20/s |

* `machine_uuid` — SMBIOS 1-tur, hech qachon bo'sh emas, doim
  `normalize_machine_uuid` dan o'tgan. Manbalar zanjiri
  (`system_info.machine_uuid`): `smbios` → `registry` → `cim` → `wmic` →
  `derived` (UUIDv5, WARNING bilan); `wmic csproduct` bilan bir xil satr.
  `MachineGuid` asosiy manba EMAS (obraz bilan ko'chadi). `ip`/`mac` —
  handshake yuborgan juftlik (`AppState.machine`), `mac` kichik harf;
  `number` — satr, login'gacha `null`.
* Faqat loopback (`127.0.0.1` va `::1`), `Host` loopback bo'lishi shart
  (DNS rebinding). `Origin` — `webview_policy.allowed_domains` +
  `.env` `LOCAL_SERVICE_ALLOWED_ORIGINS` (`*` faqat dev). CORS va Private
  Network Access preflight'iga javob beriladi.
* WebView domen filtri AYNAN shu portni o'tkazadi
  (`DomainAllowlistInterceptor(local_port=)`).
* Port band bo'lsa dastur to'xtamaydi — ERROR log, skrinshot yo'q.

**Skrinshot standarti 1920 px / 80 sifat** (`Setting.screenshot_max_width`
/ `screenshot_quality`) — 960/65 da test matni o'qilmasdi. Client
`QImageWriter` bilan optimallashtirilgan progressiv JPEG yozadi. Paneldagi
trafik bahosi `Settings.jsx:shotKb` shu o'lchovga moslangan.

### FaceID: solishtirish CLIENTDA, qaror SERVERDA

Ikkala embedding clientda uchrashadi (`client/services/face_engine.py:compare`),
serverga BALL keladi — 512 float emas (10 000 talaba × 6 tekshiruv/daq).

| Bosqich | Etalon | Nima tekshiriladi |
|---|---|---|
| Kirish (FaceID sahifasi) | pasport rasmi (`image_base64`) | shu odam hujjatdagi odammi |
| Test davomida | kirishda TASDIQLANGAN kadr (`AppState.face_reference`) | odam almashtirilmadimi |
| Server | `ExamSession.reference_embedding` | — (solishtirmaydi) |

**Ball shkalasi ikki tomonda bir xil**: `max(0, cos) × 100`, butun son —
`client/services/face_engine.py:similarity_score` va
`apps/common/utils/vectors.py:similarity_score`. Bir odam: odatda 40–70,
boshqa odam: 0–15. Shkala o'zgarsa chegaralar va yozilgan ballar
MIGRATSIYA bilan ko'chirilishi SHART (`controls.0008_score_scale`,
`proctoring.0016_score_scale` — namuna).

**Chegara imtihon sozlamasidan**: `Setting.faceid_min_score_student`
(kirish), `faceid_min_score_exam` (test). Client `client/exam/config/?exam=`
dan (`AppState.config.face`), server `get_client_config(session.exam)`
dan. `FACE_MATCH_THRESHOLD` (42) — faqat sozlama kelmaganda.

| Holat | Endpoint | Sessiya | Nima ketadi |
|---|---|---|---|
| Kirish: mos | `client/face/verify/` | YARATILADI | embedding + ball + kadr |
| Kirish: mos emas | `client/face/attempt/` | YO'Q | ball + kadr |
| Test: mos | — | — | hech nima (heartbeat'da son) |
| Test: mos emas | `client/face/periodic/` | mavjud | ball + kadr + `passed_since_last` |

* **Ekrandagi ball qarordan keyin muzlaydi** va serverdagi yozuv bilan
  aynan bir xil: `_verified_score` (`face/verify/` ga ketgani).
  `_best_score` faqat muvaffaqiyatsiz urinishda.
* **Hujjat tasdig'ida faqat «Davom etish»** (sarlavha, matn, "Rad etish"
  yo'q — 1366x768 da rasmni siqardi). `_on_reject` kodi va endpoint joyida.
* **"Yuz yo'q" / "bir nechta yuz" — epizod, kadr EMAS**
  (`services/face_presence.py:FaceEpisodes`, AI o'chiq yo'l). Qoida AI
  qatlamidagi bilan bir xil (`config.proctoring.temporal`): `no_face_warn_s`
  → jiddiylik 2, `no_face_suspicious_s` → 3, bir nechta yuz 1 s → 3,
  uzoq yuz (`far`) `Setting.faceid_far_warn_s` (10) → `face_too_far` 1,
  `faceid_far_unverified_s` (120) → 2 (shaxs solishtirilmayapti; bu ikkisi
  `Setting` da, siyosatda EMAS — AI o'chiq yo'lda siyosat ko'pincha yo'q);
  epizod yuz 1 s qaytgandagina tugaydi. Ilgari har
  kadr (≈10/s) hodisa edi. Hodisa bergan epizod yopilganda — o'sha tur,
  jiddiylik 0, `closed: true` + `duration_ms` (AI `_closed_event` bilan
  bir xil); server `closed` ni ballga QO'SHMAYDI (`ingest._is_closing`).
  Davriy FaceID yuzsiz/ko'p yuzli/uzoq kadrda `face/periodic/` YUBORMAYDI
  ("solishtirib bo'lmadi", `_run_face_check`) — aks holda har oraliqda
  jurnal qatori + JPEG + `face_fails` va oxiri `high_suspicion_identity`.
* **`faceid_max_fail` — chetlashtirish EMAS, xabar**: server
  `high_suspicion_identity` KRITIK hodisasini AYNAN chegaraga yetilganda
  bir marta yuboradi, sessiyani to'xtatmaydi. Qaror proktorda
  (`sessions/{id}/terminate/`).
* **Enrollment rejimi o'chiq** (`faceid_page._ENROLLMENT_ENABLED = False`):
  rasmsiz javob — nosozlik, talabgorni jimgina kiritish mumkin emas. Kod
  va server tomoni (`verify_initial_face` ballsiz so'rov) saqlangan.
* Muvaffaqiyatsiz kirish `challenge` ni **sarflamaydi**
  (`state.peek_pending`); client uni bir marta yuboradi, operator
  "Qaytadan urinish" ni bosadi.

**Tekshiruvdan oldin — oval va sanoq** (`Setting.faceid_guide_seconds`, 5 s;
zaxira `FACE_GUIDE_SECONDS`, `CameraView.start_guide`). Sanoq paytida yuz
aniqlanmaydi va solishtirilmaydi; keyin oval xira uzuq chiziq bo'lib qoladi.

* Sanoq BIRINCHI KADRDAN boshlanadi (Windows'da kamera 2–4 s ochiladi).
* Aniqlash ISHCHIDA o'chadi (`CameraWorker(detect=False)`,
  `set_detection_enabled`); sahifa ham sanoqdagi natijani rad etadi (`_on_face`).
* Har urinishda qaytadan. `0` — sanoq yo'q, oval baribir qoladi.
* **`take_camera` aniqlashni YOQIB uzatadi** — davriy FaceID unga tayanadi.
* Oval o'lchami (`_GUIDE_HEIGHT` 72%, nisbat 0.76, markaz 47%) ichidagi
  yuz `MIN_FACE_WIDTH_PX` dan katta bo'lishini kafolatlaydi.

**Yuz atrofida ramka YO'Q — holatni oval rangi aytadi** (yashil mos, qizil
mos emas/bir nechta odam, sariq yaqinroq keling, xira — yuz yo'q yoki
natija eskirgan `_DETECTION_TTL_MS`); foiz oval tepasida.
`CameraView.set_detection` yuz koordinatalarini qabul qilmaydi.

**Kadrda kim talabgor** — `camera_worker.select_candidate_face`:
`width < MIN_FACE_WIDTH_PX` tushadi → eng kattasi asosiy → ikkinchisi
> 0.7 × asosiy bo'lsa `multiple`. Uchinchi qadam MAJBURIY: usiz kameraga
egilgan suflyor "talabgor" bo'lib solishtirilardi. Qoida
`identity/face_identity.py` (eng katta yuz) bilan bir xil bo'lishi shart.
Chetlatilgan yuzlar belgilanmaydi. Serverga `faces_detected` har doim `1`
(`verify_initial_face` boshqasini qabul qilmaydi).

* Urinish yopilishi uchun IKKALA shart: `faceid_fail_streak` ketma-ket
  mos kelmagan kadr VA `faceid_fail_min_seconds`. Yuz ko'rinmay qolsa
  seriya UZILADI ("solishtirib bo'lmadi", "mos kelmadi" emas).
* Operator xabari ikki xil: chegaradan biroz past — sifat masalasi,
  ancha past (`_FAR_MISS_GAP`) — "bu umuman shu odammi?".

**`FaceVerificationLog.session` NULL bo'lishi mumkin** (kira olmagan
urinish) — qator `pinfl`, `exam`, `zone` ni o'zida saqlaydi.

**Ikki hisoblagich, ikki egasi** — aralashtirmang:
* `face_checks` — **client** yozadi (heartbeat, `hset`); server faqat
  xatolarni ko'radi.
* `face_fails` — **server** oshiradi (`incr`, atomik); "ketma-ket" qoidasi
  `passed_since_last` orqali.

**Jonli kadr dalil** (`services/face_images.py`, storage'ning `faceid/`
shoxi). Tozalash FAYLNI oladi, QATORNI qoldiradi
(`purge_expired_face_images`). Panelda `face-logs/{id}/file/`
(`evidence.view`). Kadr kelmasa/buzilgan bo'lsa tekshiruv baribir davom
etadi, qator rasmsiz yoziladi.

**Server ballni qayta hisoblay olmaydi** (serverda ML runtime yo'q) — ball
ishonchsiz qiymat; yagona haqiqiy kafolat — operatorning hujjat tasdig'i.

### AI proktorlik (kamera qatlami)

Kompyuter ko'ruvi **client tomonda** (markaziy GPU klasteri qimmat).
`Setting.faceid_audit_rate` maydoni bor, lekin **ishlatilmaydi**.

**Kamera rollari almashtirilmaydi**, ikkitadan ortiq rol yo'q:

| Rol | Nimaga qaraydi | Nimani hal qiladi |
|---|---|---|
| `primary` | talabgorning yuziga | shaxs, nigoh, bosh holati |
| `secondary` | stol / qo'l / xonaga | obyektlar, ikkinchi odam |

Rollarni aralashtirish tahlilni jimgina buzadi — har hodisada `camera_role`.

**Rolni operator tanlaydi, server emas.** `CameraAssignment` modeli olib
tashlangan (`devices.0006_drop_camera_assignment`) — 500 mashinani qo'lda
biriktirish amalda qilinmasdi. Serverda inventarizatsiya (`Camera` —
bino, manzil, kredensial) va **qaysi kamera qaysi kompyuterniki**
(`Computer.cameras`, panelda; ROLSIZ). Manba: IP kamera (RTSP, kredensial
`client/camera/stream/` dan) yoki lokal veb-kamera (OS indeksi; `Camera`
qatori YARATILMAYDI).

**Taxmin qoidasi** (`proctoring/camera/roles.py`): avval lokal veb-kameralar
(yuzga qaraydi), keyin IP kameralar (xonani ko'radi); faqat IP bo'lsa u
yuz rolini oladi. Virtual qurilma (OBS, ManyCam) oxiriga — taqiq esa
siyosatda (`allow_virtual_camera`), server majburlaydi.

Taxmin operatordan yashirilmaydi va tuzatiladi
(`ui/widgets/camera_panel.py:RoleSegmentedControl`):

* faqat kamida ikkita ishlaydigan kamerada;
* tanlov QURILMAGA bog'lanadi (`ResolvedCamera.key`) — "Yangilash" dan
  keyin ham saqlanadi (`roles.apply_choices`);
* kartalar QURILMA tartibida chiziladi (`camera_panel._by_device`), rol
  tartibida emas;
* rol almashtirilganda oqim va tekshiruv natijasi BEKOR qilinadi.

**Hamma qurilma ro'yxatda qoladi, ikkitadan ortig'i ZAXIRA** (`role == ""`,
«Ishlatilmaydi»):

| | Rolli | Zaxira |
|---|---|---|
| Tekshiruv sahifasida | ha | ha |
| Oldindan ko'rish oqimi | ha (slot = rol) | ha (slot = `spare:<kalit>`) |
| Server tekshiruvi (`camera/check/`) | ha | yo'q |
| Imtihon kuzatuvi (`as_slots`) | ha | yo'q |
| Siyosat tekshiruvi | ha (`layout.in_use`) | yo'q |

`layout.preview_slots()` (ko'rish) va `layout.as_slots()` (kuzatuv)
ATAYLAB alohida. Har kartada uch segment (`roles.assign`): vazifani olgan
qurilma eskisini oldingi egasiga beradi; YUZ ROLI BO'SH QOLMAYDI (o'rniga
avval zaxira, keyin obyekt kamerasi ko'tariladi); yolg'iz kamerani o'chirib
bo'lmaydi. Zaxiradagi IP kamera kredensiali `role="preview"` bilan
so'raladi. **IP kamera faqat shu kompyuterga biriktirilgan bo'lsa**
ishlatiladi (`camera/config/` ro'yxati va `camera/stream/` kredensiali —
bitta qoida, `devices.services._computer_cameras`: biriktirilgan + faol +
kompyuter binosida). Biriktirilmagan mashinada IP kamera YO'Q (faqat lokal
veb-kamera) — "binodagilarning hammasi" zaxirasini qaytarmang: boshqa
xonaning kamerasi tanlanardi.

**`Setting` va `ProctoringPolicy` bir-birini takrorlamaydi**: obyekt
aniqlashning "yoqilganmi/ishonch/klasslar" — `Setting`; siyosat faqat
qo'shimcha (kadrlar, davomiylik, oyna, ball pasayishi). Client'ga BITTA
qiymat: `modules.objects` = ikkalasining VA'si
(`controls.services._serialize_proctoring`).

**YOLO = `Setting.is_enable_detect` VA `ProctoringPolicy.is_enabled` VA
`enable_objects`.** Siyosat profil bilan avtomatik yaratilmaydi (siyosatsiz
profil `_default_proctoring()` — `enabled=False`). Panel buni profil
sahifasida ko'rsatadi: `SettingSerializer.ai_proctoring` +
`Settings.jsx:AiProctoringNotice` («AI kuzatuvni yoqish»,
`controls.proctoring_manage`).

**YOLO modeli fayli alohida**: `client/models/yolo/yolov8{n,s,m}.onnx`
(`client/models/README.md`), eksport `dynamic=True` (640/512/416/320).
Fayl yo'q bo'lsa modul jimgina o'chadi va `proctoring_degraded` chiqadi.
YOLOv8 — AGPL-3.0.

**"Odam" (COCO 0) oddiy obyekt emas** (`behavior_analyzer._observe_objects`):
talabgorning o'zi `object_detected` bo'lmaydi. Boshqa odam faqat yuzasi
talabgornikining ≥ chorak qismi bo'lsa (`_SECOND_PERSON_AREA_RATIO`)
`second_person` beradi. Qaror kodga (`Track.code`) tayanadi, nomga emas.

**O'rindiq kalibrlashi** (`behavior/seat_anchor.py`) — obyekt kamerasi
bitta ish joyi tepasida turadi, ramka o'lchami esa masofani bildiradi.
Sessiya boshidagi 15 s (`CALIBRATION_SECONDS`) da uzluksiz (≥80%) va
qimirlamaydigan (markaz tarqoqligi ≤ 0.04) odam — talabgor; ramka markazi
"o'rindiq" bo'lib muzlatiladi. Keyin talabgor — o'sha iz, uzilsa
o'rindiqqa eng yaqin odam (radius 0.22).

* Noaniq kalibrlash (ikki barqaror odam, farq < 1.5x) RAD etiladi, oyna
  qayta boshlanadi; shu vaqt zaxirasi — markazga yaqinlik × yuza.
* Dastlabki 15 s da `second_person` chiqmaydi (chegarali sukut).
* Talabgor o'rindiqda bo'lmasa `second_person` chiqmaydi (`no_face` aytadi).
* Tayanch — ramka markazi (pose emas); kalibrlash va keyingi kadrlar bir
  xil nuqta turini ishlatadi.
* `hand_below_desk` ham o'rindiq bo'yicha tanlangan pozani oladi.
* Rol bo'yicha va har sessiyada qaytadan (`reset`).
* **Zal kamerasi uchun bu qoida yaroqsiz**; "zal" bayrog'i ataylab
  qo'shilmagan — kerak bo'lsa ish joyi zonalarini chizish.

**`ExamSession.proctoring_state` `status` dan MUSTAQIL** ("kuzatuv qanday"
vs "imtihon qanday"). `degraded` imtihonni to'xtatmaydi; qaror
`ProctoringPolicy.camera_lost_action` da.

### Tashqi test platformasi — backend KO'PRIK

**Client platformaga hech qachon o'zi murojaat qilmaydi.** JSHSHIR
kiritilganda backend so'raydi (`integrations/exam_site.py`):
`GET {Exam.site_url}?imie=<jshshir>` + `Exam.site_header_encrypted` dagi
sarlavha. Sabab: kredensial serverda qoladi, javob sxemasi BITTA joyda
talqin qilinadi.

```json
{"status": 1, "message": "Success",
 "data": {"id": …, "abitur_id": …, "imie": …, "is_finished": 1,
          "image_base64": "data:image/jpeg;base64,…",
          "lname": "…", "fname": "…", "mname": "…",
          "duration_time": 180,
          "test_link": "https://test.uz/login?token=…",
          "message": "Testga ruxsat!", "status": true}}
```

| Javob | Kod | Operator nima qiladi |
|---|---|---|
| `status != 1` | `candidate_not_found` | JSHSHIR ni tekshiradi |
| `data.status` false | `candidate_not_eligible` | platforma matnini o'qiydi |
| `test_link` bo'sh | `candidate_not_eligible` | administratorga murojaat |

* **`is_finished` TO'SIQ EMAS** (namunada `1` bilan ham "Testga ruxsat!");
  u `ExamSession.meta` da dalil sifatida saqlanadi. `external_status`
  ga yozmang — `_CLOSED_PLATFORM_STATUSES` imtihonni to'sardi.
* **`test_link` JSHSHIR tekshiruvida client'ga BERILMAYDI**: sessiyaga
  shifrlab yoziladi (`external_test_link_enc`), faqat `exam/access/` da,
  shaxs tasdiqlangach qaytadi.
* **WebView allowlist'i `test_link` domenidan**, `site_url` dan emas.
* `image_base64` FaceID etaloniga aylanadi (`data:` prefiksi olinadi).
* **F.I.Sh. va `duration_time` ixtiyoriy**: yo'q bo'lsa oqim to'liq
  ishlaydi (ism o'rniga niqoblangan JSHSHIR — `Candidate.display_name`;
  vaqt maydoni chizilmaydi). Buzilgan `duration_time` — 0, istisno emas.
  Ism `_NAME_ALIASES` dan (familiya, ism, otasining ismi; zaxira `fio`,
  `surname`...). Vaqt DAQIQADA saqlanadi (`duration_minutes`),
  formatlash CLIENTDA (`Candidate.duration_label`), sessiyaga muzlatiladi
  (`ExamSession.meta.platform.duration_minutes`). Ikkalasi talabgor
  kartasida VA FaceID sahifasida ko'rinadi.

`integrations/exam_platform.py` da faqat `report_result` va
`platform_health` qoldi.

### Kompyuter raqami va inventar kodi — IKKI BOSHQA SAVOL

| | `Computer.number` | `inventory_code` |
|---|---|---|
| Nimani belgilaydi | XONADAGI O'RIN (stolda) | MASHINANING O'ZI |
| Mashina almashtirilsa | qoladi | o'zgaradi |
| Kim ishlatadi | operator, talabgor | buxgalteriya, administrator |
| Unikal | **bino ichida** | tizim bo'ylab |

Kompyuter jadvalidagi unikallik (hammasi shartli — tirik yozuvlar orasida):

| Cheklov | Maydonlar | Ko'lam |
|---|---|---|
| `unique_computer_zone_number` | `zone`, `number` | bino ichida, `number IS NOT NULL` |
| `unique_computer_zone_ip` | `zone`, `ip_address` | bino ichida |
| `unique_computer_inventory_code` | `inventory_code` | tizim bo'ylab |
| `unique_computer_uuid_mac` | `machine_uuid`, `mac_address` | tizim bo'ylab, ikkalasi bo'sh emas |
| `unique_computer_mac` | `mac_address` | tizim bo'ylab, bo'sh emas |

`machine_uuid` O'ZI unikal EMAS (bir partiyadagi platalarda bir xil) —
`unique_computer_machine_uuid` olib tashlangan (migratsiya serverda yaratiladi).

* Raqam ro'yxatlarda birinchi, saralash `["zone", "number", "inventory_code"]`.
* **Raqam ixtiyoriy**, `0` qabul qilinmaydi.
* `unique_computer_zone_number` shartli (`deleted_at IS NULL AND number IS
  NOT NULL`) — hisobdan chiqarilgan mashina raqamni band qilmaydi.
* **Ekrandagi nom bitta joyda** — `Computer.label` ("№12 · INV-001"):
  server serializer'da beradi, frontend `utils/labels.js:computerLabel`
  (ro'yxatda raqam alohida ustun), client handshake'dagi tayyor qiymat.
  `verify_machine` xabarlari ham shu nomni ishlatadi.
* **Client uni sarlavhada yirik nishonda ko'rsatadi**
  (`ui/widgets/brand.py:SeatBadge`, `header._brand_block`, `set_seat`):
  faqat raqam (raqamsizda inventar kodi), to'liq nom tooltip'da,
  biriktirilmagan bo'lsa yashirin. Kataklarda `pc` YO'Q
  (`WorkstationHeader` — `fields=("region", "zone", "mac", "ip")`).
  Imtihon sahifasida sarlavha yo'q.
* **Logotip — fayl** (`client/resources/images/logo.png`; PyInstaller'da
  `--add-data "resources;resources"`). Topilmasa vidjet yashirinadi.
  Login/tarmoq sahifalarida oq rangda, `BrandBackdrop.make_logo`.
* **Yangi katak IKKI joyga**: `ContextChips.FIELDS` va `set_values` imzosi
  (`*` bilan qat'iy — faqat `FIELDS` ga qo'shish login'dan keyin
  `TypeError` beradi). Ko'rsatilmaydigan katak qiymati jimgina tashlanadi.

**Excel import** (`devices/computer_import.py`, `computers/import/` +
`import-template/`, panel `ComputerImportDialog`). Ustunlar: `dtm_id`,
`zone_number` (tashqi raqamlar), `machine_uuid` va `mac_address` (ikkalasi
MAJBURIY — bo'sh MAC qatori xato), `number`, `inventory_code` (bo'sh —
`AUTO-<UUID hex>-<MAC hex>`). HAMMASI YOKI HECH NARSA (panel avval
`dry_run`). "Allaqachon ro'yxatda" — JUFTLIK bo'yicha (`services.
match_identity`, handshake bilan bitta qoida): ro'yxatdagi juftlik
o'tkazib yuboriladi, UUID bir xil + MAC boshqa qator — YANGI kompyuter.
Shu UUID'li MAC'siz eski yozuv bor bo'lsa — xato (avval unga MAC kiritiladi).
Yagona tahrir: UUID'siz eski yozuv MAC + o'sha bino bo'yicha topilsa unga
faqat `machine_uuid` yoziladi (`to_bind`/`bound`). Viloyat admini faqat o'z
viloyatiga. `Computer.ip_address` ixtiyoriy (`devices.0010`, NULL
`unique_computer_zone_ip` ga tushmaydi).

### Kompyuter broni (`exams.ComputerBooking`)

**"Test sessiyasi" — `ExamSchedule`** (imtihon + vaqt + bino/`NULL` =
barcha binolar), `ExamSession` emas. Bitta qator = sessiyadagi bitta kompyuter:

| Maydon | Ma'nosi |
|---|---|
| `schedule`, `computer` | joy (juftlik unikal) |
| `is_active` | shu sessiyada ISHCHI (`Computer.is_active` dan BOSHQA) |
| `is_booked` + `pinfl` | biriktirilgan talabgor; bazada bog'langan (`CheckConstraint`) |

Bir JSHSHIR bir sessiyada bitta joyda — `unique_booking_schedule_pinfl`.

**Mantiq bitta joyda — `apps/exams/bookings.py`** (panel, tashqi API, Django
admin, client tekshiruvi):

* `generate_seats` (`generate/`) — har ishchi kompyuterga bo'sh qator,
  takroriy chaqiruv xavfsiz (`ignore_conflicts`).
* **Biriktirish PATCH emas — `assign/`** (`schedule`, `pinfl`, ixtiyoriy
  `computer`/`zone`): `computer` yo'q — eng kichik raqamli bo'sh joy
  (`select_for_update(skip_locked)`); talabgorning joyi bo'lsa o'sha
  (idempotent); boshqa `computer` — KO'CHIRISH (auditda `move`). `PATCH`
  faqat `is_active`.
* `bulk-assign/` — har qator alohida tranzaksiya va natija, audit bitta.
* `release/`, `stats/` (`total`/`booked`/`free`/`broken`/`broken_booked`/
  `finished`). Band joyni o'chirib bo'lmaydi.

**Imtihondagi talabgorning joyi qo'lda bo'shatilmaydi/ko'chirilmaydi**
(409 `seat_in_use`; "imtihonda" = shu `schedule` + JSHSHIR bo'yicha
`TERMINAL_STATUSES` dan tashqari sessiya, `ready` ham —
`bookings.active_session`). Qoida servisda; panel tugmalarni o'chiradi
(`SeatMap.seatInExam`). Joy faqat sessiya orqali bo'shaydi:

| Yakun | Joy |
|---|---|
| «Yakunlash» (client, `completed`) | bo'shaydi |
| chetlashtirish (PANEL) | bo'shaydi |
| dasturdan chiqish (Ctrl+Q), `expired`, "shaxs rad etildi" | band |

Bo'shatish yakun bilan BITTA tranzaksiyada (`session._release_seat` →
`bookings.release_after_session`; `finish_session(completed=True)`,
`terminate_session(release_seat=True)` — faqat panelning
`sessions/{id}/terminate/`). `meta.seat_release` + audit; client javobida
`seat_released` + `seat`. `completed` standarti `false` (eski client).

**`finished_count` / `last_finished_at` `bookings_enforced` ga KIRADI** —
aks holda oxirgi talabgor yakunlagach tekshiruv jimgina o'chardi.

Ruxsatlar: `bookings.view` / `bookings.manage`
(`exams.0007_booking_permissions`). Tashqi tizim JWT bilan kiradi.

**JSHSHIR tekshiruvida** (`lookup_candidate` → `resolve_candidate_seat`,
platformaga so'rovdan OLDIN). Bron sessiya darajasida yoqiladi (birorta
biriktirish bo'lsa); `REQUIRE_COMPUTER_BOOKING=true` majburiy qiladi.

| Kod | Holat |
|---|---|
| `seat_not_booked` (403) | joy yo'q |
| `seat_out_of_service` (409) | joyi buzilgan |
| `wrong_computer` (409) | boshqa stolda; `details.seat`, `details.current` |
| `device_binding_mismatch` (409) | stol to'g'ri (juftlik mos), qurilma boshqa kompyuterga biriktirilgan |

"Shu mashina" — client yuborgan (`machine_uuid`, `mac_address`) juftligi
(`bookings._physical_computer` → `find_computer_by_identity`); eski clientda
MAC, ikkalasi yo'q bo'lsa qurilma biriktiruvi. UUID yuborilgan, lekin juftlik
tanilmagan (UUID mos, MAC boshqa) — "shu stol" EMAS, qurilma biriktiruvi
ham uni shu stol qilmaydi (`wrong_computer`, `details.current = null`).
Faqat bino ichida.

**Challenge qurilmaga bog'langan** (`session._require_pending_device`):
`face/verify/`/`face/attempt/` boshqa qurilmadan kelsa `SessionNotFound`,
challenge sarflanmaydi (avval `peek`, keyin `consume`). Muvaffaqiyatda
`seat` `ExamSession.meta.seat` ga muzlatiladi.

**Xato tafsiloti tuzilgan** — `DomainError(extra=...)` → `error.details`.
Client: `ApiWorker.failed_details` → `ui/widgets/seat_notice.py:SeatNotice`.

**Panel** — `/computer-bookings` (`pages/ComputerBookings.jsx`); standart
ko'rinish — joylar xaritasi (`components/bookings/SeatMap.jsx`,
`?view=list` — jadval). Chapda viloyatlar (`groupRegions`, brauzerda
yig'iladi) → binolar (`?region=&zone=`), bino avtomatik tanlanmaydi.
Ustunlar soni kartaning haqiqiy kengligidan (`ResizeObserver`).
**500 o'rindiq tez** (`SeatGrid`): o'rindiq — oddiy `<button>` +
data-atributlar, stil bitta blokda (`seatStyles`), `memo`, bitta tooltip
(`HoverTip`), `content-visibility: auto`. **O'rindiqqa MUI
`Tooltip`/`ButtonBase`/`sx` QAYTARMANG.** Ma'lumot:
`computer-bookings/zones/` (GROUP BY) va `seats/?zone=` (sahifalanmaydi,
2000 chegara), ikkalasi `?schedule=` talab qiladi. Viloyat administratori
umumiy (`zone=NULL`) jadvallarni ko'radi (faqat o'qish).

### FaceID integratsiyasi (`/api/v1/integrations/faceid/`)

Tashqi FaceID tizimi (FastAPI) Face ID'dan o'tgan nomzodni shu yerda bron qiladi.

| Endpoint | Nima |
|---|---|
| `GET schedules/` | tugamagan (`ends_at >= now`) faol sessiyalar |
| `GET schedules/{id}/computers/` | ishchi kompyuterlar (buzilgan/raqamsiz yo'q), band bo'lsa `pinfl` |
| `POST book/` | `bookings.assign` — panel bilan bir xil, idempotent |

* Kirish — `X-API-Key` (`integrations/authentication.py`), JWT qabul
  qilinmaydi. `FACEID_API_KEY` (production'da ≥ 32 belgi), bo'sh kalit
  hammasini rad etadi. So'rov `FACEID_API_USER` nomidan; rol RESPUBLIKA
  darajasida bo'lishi shart (`RepublicLevelIntegration`).
* Bino — `region_dtm_id` + `zone_number`, kompyuter — `Computer.number`
  (ichki ID'lar mos kelmaydi).
* `seat_in_use`/`seat_unavailable` (409) — qaror, qayta urilmaydi.

### Mashina tekshiruvi (Machine UUID + MAC) — ikkinchi darvoza

`X-Device-ID` mashinani EMAS, client nusxasini belgilaydi (obraz bilan
ko'chadi). **Kompyuter identifikatori — (`machine_uuid`, `mac_address`)
JUFTLIGI.** Faqat UUID yetmaydi: arzon platalarda SMBIOS UUID bir partiyada
bir xil — UUID bir xil, MAC boshqa ikki mashina IKKI BOSHQA kompyuter. Faqat
MAC ham yetmaydi (tarmoq kartasi bilan almashadi).

**Qidiruv qoidasi BITTA joyda** — `devices/services.py:find_computer_by_identity`
(sof qismi `match_identity`); handshake (`verify_machine`), ro'yxatdan
o'tish (`resolve_computer`), JSHSHIR tekshiruvidagi stol
(`bookings._physical_computer`), Excel import va panel serializer'i FAQAT
shuni chaqiradi. Tartib: (a) (UUID, MAC) aniq mos yozuv; (b) topilmasa va
shu UUID bilan faqat BITTA yozuv bor, unda MAC yo'q — o'sha eski yozuv
(o'tish davri); (c) aks holda — topilmadi. UUID bo'yicha "eng yaqini"
TANLANMAYDI. Faqat UUID yoki faqat MAC bo'yicha taxminiy moslik QO'SHMANG.

| Qatlam | Qoida |
|---|---|
| model | `unique_computer_uuid_mac` (juftlik), `unique_computer_mac` (MAC tizim bo'ylab); `machine_uuid` NULL mumkin va o'zi unikal EMAS |
| shakl | `normalize_machine_uuid` va `normalize_mac` (katta harf, ikki nuqta) — client bilan AYNAN bir xil; panel, import, Django admin (`ComputerAdminForm`) kanonik shaklda yozadi; eski yozuvlardagi `2c-f0-...` shakli qidiruvda ham tanilanadi (`match_identity`) |
| panel | UUID yangi kompyuterda MAJBURIY (bor UUID'ni o'chirib bo'lmaydi); MAC yangi VA tahrirlanayotgan yozuvda MAJBURIY |
| client | UUID va MAC handshake, `candidate/lookup/`, `devices/register/`, `access-attempt/` da; sarlavhada UUID ko'rsatilmaydi |
| sessiya | `ExamSession.machine_uuid` — kompyuter yozuvidan |
| qurilma | `DeviceToken.reported_machine_uuid` / `reported_mac` — client o'lchagani (`record_handshake`, ishonchsiz, faqat diagnostika) |

* Client WinAPI orqali o'lchaydi (`system_info.machine_identity`,
  `winapi_net.py`); server baholaydi (`devices/services.py:verify_machine`),
  ko'lam — qurilmaning BINOSI.
* **Client `Computer.mac_address` / `machine_uuid` ga HECH QACHON yozmaydi.**
  Yagona istisno — UUID'ni bir marta bog'lash (`bind_machine_uuid`): yozuvda
  UUID yo'q, MAC aynan mos va shu (UUID, MAC) juftligi boshqa yozuvda yo'q
  (`machine_uuid IS NULL` sharti `UPDATE` ichida), audit
  `meta.machine_uuid_bound`. Shu UUID boshqa yozuvda (boshqa MAC bilan)
  bo'lishi bog'lashni to'smaydi.
* UUID yubormaydigan eski client — `_verify_by_mac` (`basis="mac"`, o'zgarmagan).

| `status` | Ma'nosi | Kim tuzatadi |
|---|---|---|
| `ok` | juftlik qurilma biriktirilgan kompyuterniki (yoki `bound`; MAC'siz eski yozuv — `legacy_no_mac: true` + WARNING) | — |
| `mismatch` | juftlik binodagi BOSHQA kompyuterniki (xabarda ikkala nom) | administrator qurilmani qayta biriktiradi |
| `not_found` | UUID mos, MAC boshqa va bunday juftlik binoda yo'q (xabarda yozuvdagi va mashina aytgan MAC) | administrator MAC'ni yangilaydi yoki ortiqcha adapter o'chiriladi |
| `not_found` | client MAC yubormadi ("MAC aniqlanmadi") — maydonni bo'sh yuborish tekshiruvni chetlab o'tmaydi | adapter/dastur |
| `not_found` | UUID binoda yo'q | administrator yozuvni to'g'rilaydi |
| `inactive` | hisobdan chiqarilgan (UUID mos bo'lsa MAC farqidan ham USTUN) | — |
| `unknown` | identifikator yo'q | dasturni yangilash |

`ok` dan boshqasi `allowed=False`. Yumshatish — `REQUIRE_MACHINE_MATCH=false`
(eski nomi `REQUIRE_MAC_MATCH` ham o'qiladi). **Bu kredensial emas,
inventarizatsiya intizomi.** Rad etilgan tekshiruv audit yozmaydi.

**Server ham majburlaydi** (faqat client UI emas): `true` da
`candidate/lookup/` `session.require_machine_match` bilan qayta tekshiradi
— bron xatolaridan KEYIN, platformadan OLDIN — va 409
`machine_not_verified` (`details.status`, matn handshake'niki) qaytaradi.
`face/verify/` alohida tekshirilmaydi: challenge shu qurilmaga bog'langan.
Testlarda lookup juftlik bilan chaqiriladi (`factories.machine_of`);
`settings/test.py` bayroqni `True` ga mahkamlaydi.

**MAC'siz eski yozuvlar (o'tish davri)** — o'chirilmaydi va to'xtatilmaydi:
(b) qoida bo'yicha faqat UUID bilan tanilanadi (`legacy_no_mac`). Shu UUID'li
ikkinchi yozuv (MAC bilan) qo'shilishi bilan moslik TO'XTAYDI — endi UUID
mashinani ajratmaydi va administrator eski yozuvga MAC kiritishi kerak.

* **Tekshiruv**: `python manage.py audit_machine_identity [--zone ID]` (faqat
  o'qiydi): MAC'siz kompyuterlar, bir xil UUID'li guruhlar, oxirgi
  `reported_mac` yozuvdagidan farq qiladiganlar (ular hozir `not_found`).
  Panel `/device-tokens` yon varag'ida ikkala MAC yonma-yon, farq —
  ogohlantirish rangida.
* **Amaliy shartlar**: imtihon mashinasida bitta faol tarmoq adapteri
  (Wi-Fi o'chiq — aks holda marshrut unga o'tganda MAC "o'zgaradi" va
  mashina `not_found` oladi); tarmoq kartasi almashtirilsa MAC'ni panelda
  administrator yangilaydi.

**Apparat izi `muid:<UUID>|mac:<MAC>`** (`system_info.hardware_fingerprint`,
server `services.fingerprint_for`; MAC kanonik; `muid:` prefiksi — ikki
tomonli SHARTNOMA). Iz so'rovdagi `mac_address` bilan BITTA adapterdan.
O'tishlar (`is_fingerprint_upgrade`, etalon JIMGINA yangilanadi):
`MAC|host|OS|arch` → yangi — eski izdagi MAC client MAC'i bilan mos;
`muid:<UUID>` → `muid:<UUID>|mac:<MAC>` — UUID mos VA izdagi MAC KOMPYUTER
YOZUVIDAGI MAC bilan mos (yozuvda MAC yo'q — anomaliya). Aks holda
`fingerprint_changed`. **Administrator juftlikni o'zgartirsa** (panel yoki
Django admin; masalan monoblok Wi-Fi'ga o'tdi) etalon
`services.rebaseline_fingerprints` bilan yangi juftlikka ko'chadi — O'CHIRILMAYDI,
`fingerprint_for` qiymatiga almashtiriladi, faqat etaloni ESKI juftlikka teng
qurilmalar (shubhalisi anomaliyasini saqlaydi); qaysilari — auditda
`fingerprint_rebaselined`. **`devices/register/` da "o'sha mashinami" (eski
`device_id` ni qaytarish) — JUFTLIK bo'yicha** (`views._is_same_machine`):
so'rovdagi (UUID, MAC) == kompyuter yozuvidagi; iz faqat juftlikni
solishtirib bo'lmaydigan eski holatlarda. Aks holda bir xil UUID'li ikkinchi
mashina birinchisining `device_id` sini olardi.

**`mismatch` tuzatishi — panelda qayta biriktirish** (`/device-tokens` →
«Boshqa kompyuterga biriktirish»). `PATCH device-tokens/{id}/` FAQAT
`computer` ni o'zgartiradi (auditda `rebind`; hisobdan chiqarilgan
mashina va boshqa viloyat rad). Holat faqat `approve/` (kutayotganni
tasdiqlaydi / bloklanganni blokdan chiqaradi) va `revoke/` (sabab
majburiy). Sahifada tab sonlari — `stats/`.

**Uchta manzil, uchta ma'no**:

| Qiymat | Kim aytdi | Nimani bildiradi |
|---|---|---|
| `DeviceToken.reported_lan_ip` | client | qaysi MASHINA |
| `DeviceToken.last_ip` | server | so'rov qaysi manzildan kelgan |
| `DeviceToken.reported_public_ip` | client | bino qaysi IP bilan chiqadi |

`ExamSession.ip_address` ga birinchisi (yo'q bo'lsa manba manzili), qolganlari
`meta.network` da. Bu qiymat faqat bayonnoma uchun — ruxsat qarori emas.

### Toza mashina: IKKI TOZALOVCHI

| | `app_closer.py` | `threat_scanner.py` |
|---|---|---|
| Mezon | ko'rinadigan OYNA | dastur KIMLIGI |
| Nishon | har qanday dastur | katalogdagi dastur |
| Oynasizni ko'radimi | yo'q | ha |
| Xizmatga tegadimi | yo'q | to'xtatadi |
| Yopish | `WM_CLOSE`, keyin majburan | darhol majburan |

Tartib: avval `app_closer`, keyin `threat_scanner`.

**`app_closer`** (`CLOSE_OTHER_APPS`, standart = `KIOSK_MODE`): yopiladigan
narsa DASTURLAR — ko'rinadigan, sarlavhali, yuqori darajali oynasi bor,
joriy foydalanuvchi nomidan. Himoya: o'z jarayonlar daraxti (QtWebEngine),
himoyalangan nomlar, boshqa hisoblar.

**`threat_scanner` — nom bo'yicha qidirmaydi.** Belgilar ishonchlilik
tartibida (`process_identity.py`): Authenticode imzo egasi → PE
`OriginalFilename` → `ProductName`/`FileDescription` → Windows xizmat nomi →
tinglanayotgan port → fayl nomi (zaxira).

* Imzo KECHIKTIRILADI (faqat arzon belgilar javob bermasa va
  `%SystemRoot%` dan tashqarida); natija `(yo'l, mtime, hajm)` bo'yicha keshlanadi.
* **Imzo o'qiladi, tekshirilmaydi** — savol "kim imzolagan deb da'vo
  qilinyapti", zanjir tekshiruvi tarmoqqa bog'liq.
* **Keng vendor imzosi katalogga kirmaydi** ("Google LLC" Chrome'ni tutardi);
  Chrome Remote Desktop `OriginalFilename`/`ProductName` bilan.
* **Avval xizmat, keyin jarayon** (aks holda SCM qayta ko'taradi);
  `sweep()` tozalashdan keyin qayta skanerlaydi.
* Qidiruv tartibi: `BUILTIN_RULES` → `Setting.rdp_objects` →
  `FALLBACK_RULES` (keng kalit so'zlar `generic_remote` OXIRIDA — boshqa
  qoidalarni soyalamasligi uchun).
* **`blocking` `category` dan kelib chiqmaydi**: aniq vendor qoidasi
  to'sadi; kalit so'z va paneldagi yozuv to'smaydi (`is_blocking` standart
  `False`) — lekin baribir yopiladi va yoziladi.
* **Kernel darajasida o'ldirish yo'q va bo'lmaydi.** Userland'da o'ldirib
  bo'lmaydigan narsa imtihonni TO'SADI (`check_readiness` → `PolicyIssue`).
* **Admin huquqisiz tozalash yarim qoladi** → `survivors` → to'siq
  (`Setting.is_threat_block_exam=False` ogohlantirishga tushiradi; zaxira
  `THREAT_BLOCK_EXAM`).

Uchta muhit savoli (`process_identity.py`):

* `in_remote_session()` — `SM_REMOTESESSION`: o'z seansimiz masofaviy →
  to'g'ridan-to'g'ri to'siq.
* `foreign_rdp_sessions()` — `WTSEnumerateSessions` +
  `WTSClientProtocolType == 2`. `rdp_foreign_session` faqat IMTIHON DAVOMIDA
  yakunlanadi (`neutralize(end_rdp_sessions=True)`, `WTSLogoffSession`,
  disconnect emas); ishga tushishda va "Davom etish" da faqat qayd + to'siq.
  O'z seansimiz va 0-seans hech qachon yakunlanmaydi. Terminal serverli
  muassasa: `THREAT_SCAN_ALLOW` ga `rdp_foreign_session`.
* `host_virtualization()` — BIOS registrining 7 maydoni; qisqa belgilar
  (`xen`, `kvm`, `qemu`) faqat butun so'z (`detect_vm_marker`). VDI:
  `THREAT_ALLOW_VIRTUAL_HOST=true`.

| Qachon | Nima | Natija |
|---|---|---|
| Ishga tushish (`main`, Qt'dan oldin) | `sweep()` | modulda saqlanadi, imtihon boshida oqimga (`_report_startup_threats`) |
| "Davom etish" | `sweep()` fon thread'ida | `check_readiness` → modal |
| Imtihon davomida (15 s) | `scan()` + yo'q qilish | hodisa oqimi |

Jiddiylik: yo'q qilingan — `HIGH`, qolgan — `CRITICAL` (darhol yoziladi);
`neutralized` bayrog'i proktor uchun hal qiluvchi.

`.env`: `THREAT_SCAN_ENABLED` (standart = `KIOSK_MODE`), `THREAT_SCAN_ALLOW`,
`THREAT_ALLOW_VIRTUAL_HOST`.

### Bitta ekran: ortiqcha monitorlar o'chiriladi

`DeviceWatcher` ikkinchi monitorni `multi_monitor` hodisasi bilan aniqlaydi,
`services/display_control.py` esa uni ish stolidan UZADI.

* **Qt'dan OLDIN** (`main._disable_extra_monitors`) va `app_closer` dan oldin.
* Asosiy monitor va ko'zgu drayverlariga tegilmaydi.
* **Uzishda `dmFields` = `DM_POSITION|DM_PELSWIDTH|DM_PELSHEIGHT`**;
  `DM_BITSPERPEL`/`DM_DISPLAYFREQUENCY` qo'shilsa drayver
  `DISP_CHANGE_BADMODE` (-2) qaytaradi. Qaytarishda beshalasi.
* `CDS_UPDATEREGISTRY` bilan — asl `DEVMODE` saqlanadi va chiqishda
  QAYTARILADI (`finally`). Admin huquqi kerak emas.
* `SetDisplayConfig(SDC_TOPOLOGY_INTERNAL)` faqat noutbukda ishlaydi.
* **Duplicate (klon) rejimi — alohida yo'l**: ikkala monitor BITTA manbada,
  ya'ni `EnumDisplayDevices` ham, Qt `screens()` ham bitta ekran ko'radi.
  Monitorlar `QueryDisplayConfig` faol yo'llari bo'yicha sanaladi
  (`display_control.active_targets`), ortiqchasi `SetDisplayConfig`
  (`SDC_USE_SUPPLIED_DISPLAY_CONFIG | SDC_SAVE_TO_DATABASE`) bilan o'chadi
  (`disable_clones`; qoladi — noutbuk ichki paneli, bo'lmasa birinchisi),
  asl konfiguratsiya `restore` da qaytadi. `DeviceWatcher` sonni
  `max(Qt, fizik)` dan oladi (`display_changed` + 3 s so'rov) va duplicate'ni
  imtihon DAVOMIDA ham o'chiradi (manba o'zgarmaydi — oyna joyida);
  extend esa faqat ishga tushishda uziladi.

`.env`: `DISABLE_EXTRA_MONITORS` (standart = `KIOSK_MODE`),
`RESTORE_MONITORS_ON_EXIT`.

### Qo'shimcha qurilmalar (fleshka, telefon, naushnik...)

Imtihon boshidan yakunigacha (`DeviceWatcher` hayoti) nima ulandi/uzildi —
`peripheral_connected` / `peripheral_removed`, faqat QAYD (to'smaydi), log
va panel (`integrity` turkumi). Client `services/peripherals.py`, fon
thread'i `device_watch._PeripheralScanner` (`WM_DEVICECHANGE` →
`system_events.devices_changed` + 4 s so'rov).

| Manba | Nimani ko'radi |
|---|---|
| SetupAPI, `ContainerId` bo'yicha guruh | USB/SD shinadagi fizik qurilma (fleshka 4-5 tugun = BITTA qurilma) |
| `GetLogicalDrives` | disk harfi (ichki kartaridardagi SD karta, tarmoq diski), kalitda tom seriyasi |
| Core Audio (faol) | jakli naushnik, Bluetooth naushnik |

* "Kompyuter" konteyneri (`ROOT_CONTAINER`) — ichki, tashlanadi; faqat
  BT dagi konteyner tashlanadi (juftlangan BT ulanmagan paytda ham "bor"
  — ulanishni audio manba ko'radi).
* Tur ustuvorligi `KIND_SEVERITY` tartibida; **kamera audiodan oldin**
  (veb-kamerada mikrofon bor). Jiddiylik: disk/telefon 3, tarmoq/kamera/
  audio/BT 2, sichqoncha/boshqa 1; uzilish 0–1.
* Boshida ulanganlar ham (`at_start`), lekin sichqoncha/klaviatura,
  kamera, BT adapter emas; ichki qattiq disklar emas.
* Yangi narsa 2-ko'rinishda tasdiqlanadi; disk/telefon disk harfini
  kutadi (bitta hodisa, `drives` bilan); o'qilmagan manba "uzildi" EMAS.
* Server ballni faqat jiddiylik ≥ 2 da qo'shadi
  (`ingest._PERIPHERAL_RISK_MIN_SEVERITY`).
* Panelda `Setting.is_detect_peripherals`; client faqat server
  `device.detect_peripherals` ni yuborsa yoqadi (yuqoridagi batch qoidasi).
* Aniqlanmaydi: telefonga ulangan mikronaushnik, cho'ntakdagi telefon,
  faqat zaryad kabeli.

### "Client ishlab turibdi" (presence)

`client/presence/` — client har 45 s da yengil signal yuboradi; oraliqni
server aytadi (`config.network.presence_interval` =
`devices.services.PRESENCE_PING_INTERVAL`; zaxira `PRESENCE_PING_MS`).
**Sessiya talab qilinmaydi**; imtihon davomida alohida signal yo'q —
heartbeat presence'ni yangilaydi.

| Qatlam | Nima uchun | Muddat |
|---|---|---|
| Redis `dev:online:{device_id}` | hozir ishlayaptimi, kim kirgan, imtihondami | `PRESENCE_TTL` (100 s, ≥ 2× oraliq) |
| `Computer.status` + `last_seen_at` | panelda SQL saralash/filtr | doimiy |

DB yozuvi daqiqada bir marta (`PRESENCE_DB_INTERVAL`, cheklovchi Redis'da);
`DeviceToken.last_used_at` har signalda. Redis yo'q bo'lsa DB orqali.

Panel: `/device-tokens` («Client» ustuni, «Kirgan xodim», «Oxirgi faollik»,
`?online=true`), `/computers` («Holat», «Oxirgi signal»), Dashboard. Ikkala
ro'yxat 30 s da o'zi yangilanadi (`ResourcePage refetchInterval`).

### Kamera tekshiruvi va kuzatuv darvozasi

**Client O'LCHAYDI, server BAHOLAYDI** (`services/camera_check.py`). Client
serializer'i `ok`/`passed` maydonlarini qabul qilmaydi. 14 tekshiruv
(`camera_check.evaluate`), kodlar `{rol}_{tekshiruv}`:

| Nosozlik | Majburiy kamerada | Ixtiyoriyda |
|---|---|---|
| FPS/rezolyutsiya/oqim | **to'siq** | ogohlantirish |
| kechikish, yorug'lik, burchak | ogohlantirish | ogohlantirish |
| **virtual kamera** | **to'siq** | **to'siq** |

Natija Redis'da (`cam:check:{device_id}`, `CAMERA_CHECK.SNAPSHOT_TTL`) va
`proctoring/start/` da `ExamSession.camera_check` ga ko'chiriladi.

**Har kamera alohida tekshiriladi** (tavsiya — yuz kamerasi):

* `measured` bayrog'i — "bor, lekin tekshirilmadi" (`available=False` dan
  boshqa); tekshirilmagani `{rol}_checked` (majburiyda to'siq);
* server xom o'lchovlarni saqlaydi va birlashtiradi
  (`camera_check._merge_measurements`) — chegaralari: `SNAPSHOT_TTL` va
  qurilma almashgani (`local_index` mos kelmasa).

**`client/proctoring/start/` — yagona darvoza**: `exam/access/` dan keyin,
WebView'dan OLDIN. Rad javoblari: `camera_check_required` (takrorlash) va
`camera_check_failed` (uskunani tuzatish). `REQUIRE_CAMERA_CHECK=false`
birinchisini o'chiradi. Rad etilganda sessiya TIRIK qoladi
(`session_blocked`, `session_lost` dan alohida), client FaceID sahifasiga qaytadi.

**Qaytilganda yuz qayta solishtirilmaydi** (`faceid_page._enter_resume`,
challenge sarflangan). Uch amal: «Imtihonni boshlash» (`exam/access/` +
start qayta), «Kamerani tekshirish» (`_go_to_exam(hold_session=True)`;
boshqa imtihon tanlansa sessiya yopiladi), «Boshqa talabgor» (sessiya
`completed` siz yopiladi, bron saqlanadi).

Majburiylik clientga oldindan aytiladi —
`proctoring.camera.check_required` (`policy.check_readiness` to'siq qiladi).

**"Test ochilmoqda" ekrani** (`ui/widgets/launch_screen.py`, MD3, to'liq
QPainter) — `ExamWebViewPage.start()` dan platformaning BIRINCHI
`LoadSucceeded` igacha; qadamlar: kuzatuv → brauzer → platforma
(`loadProgress` foizi). Xato ekrani chiqqanda (`described` bor, to'silgan
host, renderer qulashi), rad javobi, `stop`/`finish` da yopiladi;
`ERR_ABORTED` (yo'naltirish) uni yopmaydi; 45 s xavfsizlik chegarasi.
Statik qatlam `QPixmap` da keshlanadi, har kadrda faqat qadamlar va
progress (`update(rect)`) — Chromium bilan bitta thread. Chromium konteksti
operator JSHSHIR yozayotganda oldindan ko'tariladi
(`ExamWebViewPage.prewarm_browser`, `_on_exam_selected`; birinchi profil
0.4–1.5 s, keyingilari ~1 ms).

### IP kamera holati va paneldagi jonli ko'rish

**Holat haqiqiy RTSP `DESCRIBE` bilan** (`devices/camera_probe.py`,
`devices.probe_cameras` — 60 s, `maintenance`), client yo'li va
kredensiali bilan (Basic/Digest, `socket`). TCP port yetmaydi.

| `status` | Ma'nosi |
|---|---|
| `online` | 200, oqim bor |
| `error` | javob bor, rad ("Login yoki parol noto'g'ri", "RTSP yo'li topilmadi") |
| `offline` | javob yo'q |

`last_seen_at` — oxirgi ONLINE, `last_checked_at` — oxirgi tekshiruv.
`update()` bilan yoziladi (`save()` emas). Parallel (`check_cameras`).
Server bino tarmog'idan tashqarida bo'lsa `CAMERA_PROBE_ENABLED=false`.

**Jonli ko'rish — MJPEG oqimi** (`devices/camera_live.py`,
`cameras/{id}/live/`, `multipart/x-mixed-replace`, ~10 kadr/s, 1280 px).
Panel `fetch` bilan o'qiydi (`components/cameras/mjpegStream.js` —
`Authorization` saqlanadi) va faqat eng yangi kadrni `createImageBitmap` +
canvas bilan chizadi. O'quvchi qoidalari (kechikish o'smasligi uchun, o'lchangan):

* `CAP_PROP_N_THREADS=4`;
* har kadrda faqat `grab()`, `retrieve()` faqat yuboriladiganida;
* miqyoslash va JPEG alohida thread'da (bir o'rinli pochta qutisi);
* yuborish kamera ritmida (har N-kadr, tezlik `grab()` oraliqlaridan);
* kechikish qo'riqchisi: oxirgi 20 `grab()` medianasi < 12 ms holati 1.5 s
  cho'zilsa oqim qayta ochiladi. `POS_MSEC` ga tayanmang.

Javob `CAMERA_LIVE_STREAM_SECONDS` (60) dan keyin tugaydi, panel darhol qayta
ulanadi. Bir vaqtdagi oqimlar `CAMERA_LIVE_MAX_STREAMS` (2), to'lsa 503
`camera_viewer_busy`. `X-Accel-Buffering: no`. Panel 5 daqiqadan keyin
to'xtaydi. `snapshot/` API qoladi. Ruxsat `devices.manage` (GET ham), audit
`camera_live_view` (10 daqiqada bitta yozuv).

OpenCV (`opencv-python-headless`) serverda faqat shu yerda, dangasa import.
**`requirements.txt` UTF-8** — PowerShell 5.1 da `pip freeze >
requirements.txt` yozmang (UTF-16 qiladi).

### RTSP kredensiali — cheklangan berish

`HandshakeView` kameralarni **kredensialsiz** qaytaradi. Kredensial —
`client/camera/stream/`, `camera_id` bo'yicha (`role` faqat audit uchun):

* faqat shu kompyuterga biriktirilgan, faol, o'sha binodagi kamera
  (`devices.services.camera_for_computer`, ro'yxat bilan bir qoida);
* har berish `AuditLog` da (`camera_credential_issue`,
  `CAMERA_STREAM_GRANT_TTL` 15 daq takrorni to'sadi);
* client faqat xotirada saqlaydi (`RtspSource` manzilni funksiya sifatida oladi).

Kredensialning o'zi muddatsiz — **ekspluatatsiya qoidasi**: kameralarda
faqat o'qish huquqli alohida hisob, davriy almashtiriladi.

### Temporal, fusion va xavf balli

**Bitta kadr hech qachon qaror emas** (`behavior/temporal_engine.py`):
ketma-ket kadr ≥ `min_frames` VA davomiylik ≥ `min_duration_ms` VA o'rtacha
ishonch ≥ `min_confidence`. Tasdiqlangan shart ochiq qoladi (`track_id`
bilan bitta hodisa), yopilish `release_ms` kechikish bilan. Ikki darajali
holatlar (`no_face`, `gaze_away`) — ogohlantirish, keyin shubha; epizod
tugagach bayroq tozalanadi.

**Fusion tarkibiy hodisalarni o'chirmaydi** (`behavior/event_fusion.py`),
"yuqori shubha" ustiga qo'shiladi, `fused_from` zanjirni saqlaydi.

**Xavf balli** (`proctoring/services/risk.py`):

* **Pasayish LAZY** (daqiqasiga N ball, o'qilganda/qo'shilganda
  hisoblanadi; fon vazifasi yo'q). `risk_breakdown` tarkibi PASAYMAYDI.
* Pasayish `now` parametrida, cooldown Redis TTL'da (atomik bo'lishi shart).
* **Cooldown turga xos** (`risk.cooldown_for`): `EventRiskWeight.cooldown_s`
  (>0) → siyosatdagi `risk_event_cooldown_s`. `0` — "siyosatdagi qiymat",
  "cooldown yo'q" emas. Og'irlik va cooldown bitta kesh yozuvida
  (`controls:risk_weights:v2`). Jadval bo'sh — `ingest.RISK_WEIGHTS` zaxira.
* **`EventRiskWeight` da jiddiylik yo'q** (`controls.0011`) — jiddiylikni
  client beradi.

### AI modullari (`client/proctoring/`)

Modullar **xulosa chiqarmaydi** ("telefon, 0.94"); hodisa temporal qatlamda
tug'iladi.

| Modul | Nima beradi | Model |
|---|---|---|
| `identity/` | yuzlar, embedding, 106 nuqta | `buffalo_l` (bundle'da) |
| `detection/` | obyekt ramkalari | `yolo/*.onnx` (yo'q) |
| `pose/` | 17 kalit nuqta | `pose/*.onnx` (yo'q) |
| `gaze/` | yaw/pitch/roll, ko'z ochiqligi | modelsiz (solvePnP) |
| `tracking/` | `track_id` | modelsiz (numpy ByteTrack) |

* **Yangi bog'liqlik qo'shilmaydi** — `numpy`, `cv2`, `onnxruntime`.
  MediaPipe, `scipy`/`lap`/`torch` rad etilgan.
* `InferenceEngine` bitta implementatsiya; provayderlar — parametr, qaror
  `hardware/performance_profile.py` da.
* Model yo'q — modul jimgina o'chadi (`ModelNotFound`).

**Bosh holati ishoralari empirik** (`gaze/head_pose.py`, faqat
`_apply_convention` da o'zgartiring): `yaw > 0` — kadrning o'ng tomoniga,
`pitch < 0` — pastga, frontal ~0 (standart 3D modelda +Y yuqoriga,
solvePnP frontalda `pitch ≈ ±180` berardi).

**Nigoh mutlaq burchakka tayanmaydi**: sessiya boshida ~3 s kalibrlash
nol deb olinadi; tarqoqlik > 12° bo'lsa kalibrlash BEKOR qilinadi.

### Dalil (evidence) — skrinshotdan ALOHIDA

| | Skrinshot | Dalil | FaceID kadri |
|---|---|---|---|
| Model | `ProctoringScreenshot` | `EvidenceArtifact` | `FaceVerificationLog` |
| Yuklash | `client/screenshots/upload/` | `client/evidence/upload/` | `face/verify/`, `attempt/`, `periodic/` |
| Tur | rasm | `frame` yoki `clip` | rasm |
| Sabab | platforma buyrug'i | tasdiqlangan hodisa | yuz tekshiruvi |
| Berish | `screenshots/{id}/file/` | `evidence/{id}/file/` (`evidence.view`) | `face-logs/{id}/file/` (`evidence.view`) |
| Tozalash | `purge_expired_screenshots` | `purge_expired_evidence` | `purge_expired_face_images` (faqat FAYL) |

* **Kamera klipi faqat AI kuzatuv yoqilganda** (hodisa ≥
  `evidence_min_severity`). `ProctoringPolicy.is_enabled=False` bo'lsa
  `evidence.enabled=False` — klip yo'qligi nosozlik emas.
* **Klip serverga yuklanmaydi** — mashinada qoladi, serverga manzili
  (`LocalRecording`). `EvidenceArtifact.Kind.CLIP` obyekt storage uchun qoldirilgan.
* **Kirish tekshiruvida ikki rasm**: jonli kadr (`image_path`) va hujjat
  rasmi (`reference_image_path`), panelda yonma-yon
  (`face-logs/{id}/file/?kind=reference`). Test davomida hujjat rasmi
  yuborilmaydi. Ikkala fayl birga tozalanadi.
* Storage qayta ishlatiladi (`common/screenshot_storage.py`, `evidence/`
  shoxi) — barcha fayl tizimi qoidalari amal qiladi.
* **Video tekshiruvi rasmdan zaif** (serverda ffmpeg yo'q): sehrli baytlar
  (MP4 `ftyp`, WebM `1A 45 DF A3`), hajm chegarasi, nginx `internal`.
* Kadr va klip alohida muddat (`evidence_clip_retention_days` /
  `evidence_frame_retention_days`); muddat YUKLASH paytida qatorga yoziladi.
* Client dalilni vaqtincha DISKKA yozadi va yuborilgach darhol o'chiradi
  (`proctoring/evidence/recorder.py`) — "diskka yozmaymiz" qoidasidan ongli istisno.
* Halqa bufer hodisadan OLDINGI lahzalarni saqlaydi (640 px,
  `capture_fps`, ~20 MB).

#### Dalil kadridagi belgilar (`boxes`)

**Kadr toza, belgi ustida**: JPEG'ga hech narsa chizilmaydi,
`EvidenceArtifact.boxes` ni panel chizadi
(`components/session/EvidenceCard.jsx`). **Koordinata 0..1**:

    {"label": "Telefon", "kind": "object", "box": [x1, y1, x2, y2], "conf": 0.93}

| `kind` | Rang | Qayerdan |
|---|---|---|
| `object` | qizil | `object_detected` |
| `person` | sariq | `second_person`, `multiple_faces`, `hand_below_desk` |
| `face` | ko'k | `face_mismatch`, `gaze_away`, `student_left_frame`... |
| `student` | yashil | talabgorning o'zi (kontekst) |

Belgilar `behavior_analyzer._mark` da, payload'da `marks` bo'lib
`recorder._boxes_of` ga yetadi, SERVER HODISASIGA KETMAYDI
(`BehaviorEvent.as_payload`). Server tozalaydi (`client_serializers._clean_mark`);
eski piksel formati tushib qoladi va chizilmaydi. Sarlavha — `evidenceTitle`.
SVG `viewBox` kadr o'lchamida, `preserveAspectRatio="xMidYMid meet"`
(`<img objectFit: contain>` bilan bir xil).

### Ekran yozuvi va mashinada qoladigan dalil

| | Skrinshot | Kamera klipi | Ekran yozuvi |
|---|---|---|---|
| Qayerda | mashina + server (`is_screenshot_upload`) | faqat mashina | faqat mashina |
| Serverga | fayl | manzil | manzil |
| Hajm | ~150 KB / javob | ~1-3 MB / hodisa | ~0.55-0.7 GB / 3 soat |
| Model | `ProctoringScreenshot` | `LocalRecording` | `LocalRecording` |

**`client/recordings/` fayl qabul qilmaydi** — manzil, hajm, davomiylik;
takroriy so'rov yangilaydi. **Yo'l ABSOLYUT** (fayl boshqa mashinada, ildiz
har mashinada boshqacha) — "faqat nisbiy yo'l" dan ongli istisno.

#### Mahalliy arxiv (`client/services/local_archive.py`)

Serverga yuborishdan mustaqil ikkinchi nusxa (navbat RAM'da; komissiya
mashinadan dalil so'raydi). Yozish xatosi oqimni to'xtatmaydi.

```
<ildiz>/<test turi>/<test>/<sana>/<sessiya>_<jshshir>_<mac>/
    shot_00001.jpg  evidence_00001.jpg  clip_00001.mp4  screen.mp4
```

* Disk — eng bo'shi, FAQAT qat'iy disk (`GetDriveTypeW`; fleshka/tarmoq
  chetlab o'tiladi). `LOCAL_ARCHIVE_ROOT` avtomatik tanlovni o'chiradi.
* Muddat 30 kun (`LOCAL_ARCHIVE_RETENTION_DAYS`), tozalash ISHGA TUSHISHDA,
  sana papkasi nomi bo'yicha.
* Dev'da `LOCAL_ARCHIVE_ENABLED=false`.

#### Skrinshotdagi kamera tasmasi (`client/services/camera_overlay.py`)

Kameralar ekran USTIGA emas, OSTIGA qo'shilgan tasmaga chiziladi (ekran
yopilmaydi). `primary` — pastki O'NG (har doim), `secondary` — pastki CHAP
(AI kuzatuv ochgan bo'lsa); o'rtada olish vaqti.

* Eskirgan kadr qo'yilmaydi (`CAMERA_FRAME_MAX_AGE_S`, 3 s) — "Kamera
  kadri yo'q" yozuvi.
* Rol almashtirilmaydi (`ProctoringSupervisor.camera_slots`).
* Kamera kadri UI thread'ida, ekran bilan bir lahzada.
* Tasma chizilmasa skrinshot tasmasiz ketadi.
  `Setting.is_screenshot_camera_overlay=False` o'chiradi.

#### Ekran yozuvi (`client/services/screen_recorder.py`)

* **5 FPS, 1600 px, butun ish bitta fon thread'ida** (`_CaptureThread`):
  ekran GDI `BitBlt` bilan (`ScreenGrabber`, ctypes) — Qt `grabWindow` UI
  thread'ni tutardi. Navbat yo'q (RAM).
* **Kodek `mp4v`** (o'lchab tanlangan): MSMF H.264 bitreytni qabul qilmaydi
  (~6 GB/3 soat), `openh264` DLL tarqatishni talab qiladi.
* Sichqoncha kursori chiziladi (`DrawIconEx`); faqat asosiy monitor.
* **Vaqt jadvali qat'iy**: kechikkan kadrda oldingisi takrorlanadi
  (`dropped`), bir martada ≤ 10 s (`_MAX_CATCHUP_SECONDS`).
* **PiP o'ng YUQORI, kichik** (`Setting.screen_record_pip_percent`, 12%).
  Kamera kadri yozuvga qo'shiladi, ekranga emas. Manba: supervisor (AI
  yoqilgan) yoki FaceID ishchisi.
* Kamera provayderi fon thread'idan chaqiriladi
  (`exam_webview_page._recording_frame`) — unga UI vidjetlariga murojaat
  qo'shmang.
* Qora kadr (qulflangan seans) ogohlantirish log'i beradi, yozuv to'xtamaydi.

#### Dalil yig'ish oynasi

Yozuv, skrinshot va klip **testga ajratilgan vaqt** davomida
(`Candidate.duration_minutes`); tugagach `_stop_capture()` (takroriy
chaqiruvga chidamli) — kuzatuvning o'zi (heartbeat, hodisalar, davriy
FaceID) davom etadi. Vaqt kelmasa cheklov yo'q; qo'shimcha vaqt oynani uzaytiradi.

**Hodisalar va yozuv manzili `session/finish/` dan OLDIN, bitta fon
chaqiruvida** (`exam_webview_page.finish` → `_finish_with_recording`:
hodisalar → yozuv → yakun) — token yakunda bekor bo'ladi, `monitor.stop()`
esa yakundan keyin. Navbat UI thread'ida olinadi
(`_collect_final_events`): avval manbalar yopiladi (supervisor —
`stop_pipeline` sinxron, yuz epizodlari), keyin
`SessionMonitor.drain_for_finish` (taymerlar to'xtaydi). Xatolar yakunni
to'smaydi. Chiqishda umumiy byudjet `_EXIT_BUDGET_S` (9 s,
`MainWindow._await` 10 s): yordamchi qadamlar yakunga to'liq timeout
qoldiradi, vaqt qolmasa o'tkazib yuboriladi.

**Chetlashtirilgan sessiya — tokensiz yo'l** (`recordings.session_without_token`):
client har qaydda `session_id` (public_id) ham yuboradi; server qabul qiladi:
xodim JWT + `client.operate`, sessiya AYNAN shu qurilmada, yakunlangan
bo'lsa `RECORDING_LATE_REGISTER_SECONDS` (30 daq) ichida. Token va
`session_id` ikkalasi kelsa MOS bo'lishi shart. Barcha rad — bitta
`session_not_found`. Bu endpointda `LenientSessionTokenAuthentication` —
**boshqa endpointlarga KO'CHIRMANG**. `session_id` UI thread'ida oldindan
olinadi (`_recording_fields`, `ProctoringSupervisor.start(session_id=)`).

**Dasturdan chiqish ochiq imtihonni yakunlaydi**
(`ExamWebViewPage.finish_on_exit`, `MainWindow._shutdown`): "ochiq" —
`_open_platform` dan yakungacha (`_exam_open`); yo'l
`_finish_with_recording` bilan bir xil, har so'rov 4 s timeout
(`_EXIT_REQUEST_TIMEOUT_S`), jami 10 s. `ExitDialog(warning=...)` oqibatni
aytadi. `aboutToQuit` ham ulangan (best-effort). Qamrab olinmaydi: jarayon
o'ldirilishi (serverda `close_stale_sessions`) va JWT muddati tugashi.

### Apparat qachon va qayerga xabar qilinadi

Alohida endpoint YO'Q — handshake'da yuboriladi. Aniqlash (`nvidia-smi` +
onnxruntime, ~0.2–2 s) ishga tushishda fon thread'ida
(`hardware_probe.prefetch()`), bir marta; handshake kutmaydi, bo'sh
qiymatga server tegmaydi.

| Nima | Qayerda |
|---|---|
| `gpu_name`, `performance_profile` | `DeviceToken` ustunlari (filtrlanadi) |
| CPU, RAM, VRAM, provayderlar, `gpu_warning` | `Computer.info_pc` (JSON) |

Handshake profili `override` siz ("mashina nima ko'taradi"); "kuzatuv qaysi
profilda ishladi" — `ExamSession.ai_profile`.

**Profillar ro'yxati uch joyda mos bo'lishi shart**:
`client/proctoring/hardware/performance_profile.py:PROFILES`,
`controls.ProctoringPolicy.GpuProfile`,
`HandshakeSerializer.performance_profile` (+ frontend `AI_PROFILE_LABEL`).

### GPU: model QAYERDA yuklanadi

**"GPU bor" va "GPU ishlatiladi" — ikki boshqa fakt**: CUDA DLL'lari
topilmasa ONNX Runtime JIMGINA CPU'ga tushadi.
`proctoring/hardware/cuda_runtime.py`:

* kutubxonalarni (`nvidia-*`, `torch/lib` pip paketlari) TOPADI va to'liq
  yo'l bilan OLDINDAN yuklaydi (`os.add_dll_directory` yetarli emas);
* yetishmayotganini aytadi — ro'yxat provayder DLL'ining PE import
  jadvalidan o'qiladi (qadalmagan).

Provayderlar ro'yxati BITTA joydan — `cuda_runtime.providers()`
(`FaceEngine.providers()`, `OnnxEngine.load()`,
`gpu_detector._detect_runtime`); `select_profile` shunga tayanadi.

CPU'ga tushish jimgina o'tmaydi: ERROR log, ekranda "Model tayyor — CPU
(GPU ishlatilmadi)", `Computer.info_pc.gpu_warning`. `FACE_REQUIRE_GPU=true`
uni ochiq xatoga aylantiradi (standart `false`).

**`onnxruntime-gpu` versiyasi CUDA nashriga qadalgan**: `1.22.x` → CUDA 12 +
cuDNN 9, `1.24+` → CUDA 13 (`client/requirements.txt` izohi). Yechim —
faqat mos nashr.

### Kuzatuv sikli (`client/proctoring/pipeline.py`)

Barcha modullar bitta thread'da, kadrlar buferlanmaydi (har iteratsiyada eng
oxirgi kadr). Modul chastotasi = min(`policy.fps`,
`PerformanceProfile.limit_fps`), `0` har doim o'tadi. Ikki kamera: `primary`
— shaxs va nigoh, `secondary` — obyekt va poza; dalil buferi har rol uchun alohida.

**`services/proctoring_supervisor.py` — yagona ko'prik**: pipeline tarmoqni
ham, sessiyani ham bilmaydi (`proctoring/__init__.py` shartnomasi).

**AI kuzatuv kamerani egallaydi**: FaceID `CameraWorker` bo'shatiladi, davriy
tekshiruv `pipeline.latest_identity` dan.

### Modal dialoglar (`client/ui/dialogs/`)

Qobiq bitta — `base.py:CardDialog` (ramkasiz, shaffof fon, 28 px karta, soya).

* **Proktor ogohlantirishi `exec()` bilan ochilmaydi** — faqat `show()`
  (`warning_dialog.py`, `ApplicationModal`): `exec()` heartbeat va taymerlarni
  to'xtatardi.
* **Soya uchun joy** (`SHADOW_MARGIN`) — aks holda soya qattiq chiziq bo'ladi.
* **O'raladigan matn — `refit()`** (`heightForWidth`), mazmun o'zgarganda ham
  chaqiring — aks holda yorliq ustma-ust chiziladi.
* **Windows ramkasi — `strip_native_frame`** (`DWMWA_BORDER_COLOR =
  COLOR_NONE`, `DWMWA_WINDOW_CORNER_PREFERENCE = DONOTROUND`), har
  `showEvent` da.
* Dialoglar 520–560 px.
* Til almashtirgich dialog ichida yo'q; modal ochiq paytda yagona yo'l
  `alt+shift` (lockdown'da bloklanmagan bo'lishi kerak).
* **`QInputDialog`/`QMessageBox` ishlatilmaydi.** Yakunlash tasdig'i —
  `finish_dialog.py:FinishDialog` (kim, JSHSHIR niqobi, kompyuter, vaqt);
  fokus «Testga qaytish» da, «Yakunlash» — yagona to'ldirilgan qizil tugma
  (`danger_button_style`).
* **Imtihon sahifasida xabar suzadi** (`indicators.Snackbar`, pastki chap);
  `MessageBar` layoutni surardi — faqat boshqa sahifalarda.

### Klaviatura tili — OYNA darajasida

`ui/widgets/language_bar.py` `MainWindow` ga qo'yiladi va `QStackedWidget`
ustida suzadi. Kerak, chunki kioskda `alt+shift` bloklangan bo'lishi mumkin.
`ActivateKeyboardLayout` yetarli emas — oynaga `WM_INPUTLANGCHANGEREQUEST`
yuboriladi (`services/keyboard_layout.py`). Faqat joriy til ko'rinadi,
bosilsa keyingisi (tooltip keyingisini aytadi); holat saqlanmaydi — sekundiga
bir marta OS'dan so'raladi.

### Client kamera qatlami (`client/proctoring/camera/`)

`services/` — imtihon oqimi (proktorliksiz ham ishlaydi), `proctoring/` —
qo'shimcha qatlam; AI qismi faqat `services/monitoring.py` buferiga yozadi.

* `CameraSource` (sinxron `open`/`read`/`close`, vendorga xos) va
  `CameraStream` (thread, FPS, qayta ulanish — vendordan mustaqil). Qayta
  ulanishni vendor sinfiga ko'chirmang.
* `rtsp.py` — `hikvision.py` emas: yo'l/port/transport `Camera` maydonlarida.
* **Qurilmani ochish bitta yo'l** — `camera/factory.py:build_source`
  (`CameraManager` va `services/camera_worker.py`).
* **Sahifa ROLNI so'raydi, indeksni emas**
  (`camera_worker.source_for_role(layout, "primary")`); manba
  `AppState.cameras` dan. `CAMERA_INDEX` — faqat zaxira;
  `FRAME_WIDTH`/`FRAME_HEIGHT` barcha sahifalarda bir xil.
* **Bitta qurilma — bitta ega**: FaceID ishchisi kuzatuv oqimidan OLDIN
  bo'shatiladi (`ProctoringSupervisor.start(before_open=...)`); qarorni
  supervisor qiladi (AI o'chiq bo'lsa kamera FaceID ishchisida qoladi).
* FPS o'lchanadi, e'lon qilinmaydi.
* **Nom va indeks bitta manbadan** — DirectShow sanagichi (`camera/dshow.py`,
  COM/ctypes). PnP ro'yxati faqat zaxira (sonlar mos kelmasa nom berilmaydi).
  `DevicePath` — barqaror kalit (`ResolvedCamera.key`,
  `factory._resolve_index`). Virtual kamera aniqlash nomga tayanadi —
  xavfsizlik chegarasi emas.
* **Qayta ulanish HAR OCHILISHDA indeksni yo'l bo'yicha qayta topadi**
  (`WebcamSource._current_index`): kamera uzilsa qolganlari siljiydi va
  eski indeks BOSHQA kamerani ochardi. Yo'l USB PORTGA bog'liq (seriyasiz
  kamera) — topilmasa YAGONA bir xil nom bo'yicha; aks holda ochilmaydi.
* **Uzilish `read()` dan emas, qurilma ro'yxatidan aniqlanadi**
  (`is_present`, har 2 s, `manager`/`camera_worker` `_PRESENCE_CHECK_S`):
  noutbukda USB sug'urilgach DirectShow `read()` kadr qaytaraverdi — bo'sh
  kadrlar qoidasi uzilishni ko'rmadi, kabel qayta ulanganda ham kamera
  ochilmadi. Faqat `False` uzilish; `None` (ro'yxat o'qilmadi —
  `dshow.enumerate_devices_strict`) — tegilmaydi.
* **O'lik oqim** (`proctoring/camera/liveness.py`): qayta ulangan USB
  kamera "ochildi", lekin DirectShow har `read()` da ~1 s kutib QORA
  bufer berdi. Belgi — kadr nol/oldingisi bilan aynan bir xil VA o'qish
  sekin (≥ 0.5 s), 5 s uzluksiz → qayta ochiladi (kechikish o'sadi).
  Faqat birinchisi emas: yopilgan ob'ektiv ham qora, lekin tez — u tirik.
  ONLINE / `camera_restored` faqat TIRIK kadrda; FAILED bitta uzilishga
  bir marta (`CameraStream._mark_lost`). Muvaffaqiyatsiz ochilishdan
  keyingi urinish 3 s kutadi (`webcam._SETTLE_AFTER_RETURN_S`).
  Ochilishdan 3 s keyin log'da oqim xulosasi (yorqinlik, o'qish ms).
  **Qayta ochish yetmaydi** (holat jarayon qayta ishga tushganda ham
  saqlangan) — `WebcamSource.recover_dead_stream` zinapoyasi, manba
  YOPILGACH: `native` (DirectShow, MJPG/o'lcham majburlanmaydi) →
  `msmf` (faqat yagona fizik kamerada, indeks 0) → `pnputil
  /restart-device` (2 daqiqada bir marta). Ishlagan rejim saqlanadi.
  MSMF uchun `main.py` `OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS=0`
  (usiz ochilish 19 s — qo'riqchi chegarasi 20 s).
* **Abadiy osilgan `read()`** (DirectShow, USB sug'urilganda):
  `GuardedSource` `_REPLACE_AFTER_S` (10 s) dan keyin osilgan I/O
  thread'ni tashlab ketadi va manbani `fresh_copy()` bilan yangi thread'da
  ochadi; eski manba o'z thread'ida yopiladi (har I/O o'z navbati bilan).
  Usiz kabel qayta ulansa ham har `open()` rad etilardi.
* **Uzilishda eski natija ishlatilmaydi**: pipeline `_FRAME_MAX_AGE_S`
  dan eski kadrni tahlil qilmaydi (oqim muzlagan kadrni ushlab qoladi),
  `latest_identity` / `_current_face` eskirganda `(None, None)` —
  davriy FaceID uni "mos" ham, "mos emas" ham sanamaydi.

### Imtihon profili client'ga QACHON yetadi

| Qachon | Endpoint | Qaysi profil |
|---|---|---|
| Preflight (login'dan oldin) | `client/preflight/` | global — faqat `hotkeys` |
| Login | `client/handshake/` | global standart (`get_client_config()`) |
| "Davom etish" | `client/exam/config/?exam=` | **imtihonning o'z profili** |

Uchinchi qadamsiz client global, server imtihon profilini ishlatardi.
`MainWindow._on_exam_selected` `lockdown.apply` ni qayta chaqiradi.

`proctoring/policy.py:check_readiness` — sof funksiya: **to'siq** (siyosat
ochiq talab qilgan narsa yo'q: `primary_required`, `secondary_required`,
virtual kamera; "davom etish" taklif qilinmaydi) va **ogohlantirish**
(qaror operatorniki). Sozlama olinmasa — ogohlantirish, to'siq emas.

### Client sozlamalari: `.env` va panel — ikki qatlam

`client/.env` da faqat: (1) serverdan OLDIN kerak, (2) MASHINAGA xos,
(3) lokal bo'lishi shart bo'lgan xavfsizlik chegarasi. Qolgani — `Setting`
profili (`_serialize` → handshake / `exam/config/`), **server qiymati ustun**,
`.env` faqat zaxira.

**Bitta o'qish nuqtasi** — `client/services/runtime_settings.py`
(`get(config, "face.guide_seconds")`, `SPECS`: zaxira, birlik, chegara).
Zaxira o'zgaruvchini (`config.FACE_GUIDE_SECONDS`) to'g'ridan-to'g'ri
O'QIMANG. **Yangi kalit = `Setting` maydoni + `_serialize` VA
`_default_config` (ikkalasi, testda solishtiriladi) + `SPECS` qatori.**

| Sozlama | Qayerda |
|---|---|
| `API_*`, `WS_BASE_URL`, `INVENTORY_CODE` | `.env` |
| `FACE_MODEL_NAME`, `FACE_DET_THRESH`, `MIN_FACE_WIDTH_PX` | `.env` (model serverdan oldin yuklanadi) |
| `FACE_REQUIRE_GPU`, `CUDA_DLL_DIR`, `CAMERA_INDEX`, `FRAME_*`, `DETECT_EVERY_NTH_FRAME`, `CAMERA_FRAME_MAX_AGE_S`, `SCREENSHOT_RETRY_QUEUE` | `.env` (apparat) |
| `FULLSCREEN`, `KIOSK_MODE`, `*_MONITORS*`, `CLOSE_OTHER_APPS*`, `THREAT_*`, `LOCAL_ARCHIVE_*`, `LOCAL_SERVICE_*` | `.env` (Qt/serverdan oldin, mashina) |
| `SCREENSHOT_ENABLED` | `.env` (dev VETO) |
| `BLOCKED_HOTKEYS` | `.env` (standart) + `Setting.hotkeys` |
| skrinshot yuklash, FaceID oqimi, davriy FaceID, ekran yozuvi, kamera tasmasi, tahdid to'sig'i, heartbeat/batch/oflayn bufer | `Setting` |
| presence oralig'i | server doimiysi `PRESENCE_PING_INTERVAL` |

`ProctoringPolicy` ga hech narsa ko'chmadi (u "kamera nimani ko'radi").
Imtihon qiymatlari "Davom etish" dan keyin o'qiladi (`FaceIDPage.start()`,
`_finish_check`, `ScreenRecorder.start(config=)`, `ScreenshotService.start`,
`SessionMonitor.start(config)`); presence — login'da.

Chegara ikki joyda: server validatorlari (heartbeat ≤ `HEARTBEAT_TIMEOUT`/2 —
`validate_heartbeat_interval`) va client `SPECS.minimum/maximum`.

**Tezkor tugmalar — almashtirish, bo'sh = standart.** Dastur ochilishi bilan
(`MainWindow.show_start`, preflight'dan oldin) `.env` `BLOCKED_HOTKEYS`;
keyingi har bosqich to'liq ro'yxat beradi (`lockdown.resolve_hotkeys`):
server ro'yxati bo'lsa almashtiradi, bo'sh bo'lsa standart qoladi. `ctrl+q`
hech qachon bloklanmaydi (`_NEVER_BLOCKED`), `alt+shift` standartda yo'q.

`client/.env.example`: avval lokal qiymatlar, oxirida «Admin paneldan
boshqariladi (bu yerda faqat ZAXIRA)».

### Client o'rnatuvchisi (`client/installer/`)

PyInstaller `onedir` + Inno Setup, ikki nashr: `-Gpu` va `-Cpu`
(`client/installer/README.md`):

```powershell
cd client
copy installer\env.production.template installer\client.env   # bir marta
powershell -ExecutionPolicy Bypass -File installer\build.ps1 -Gpu   # yoki -Cpu
ProctoringClientSetup-1.0.0-gpu.exe /VERYSILENT [/INVENTORY_CODE=INV-001]
```

* **Server manzili o'rnatishda so'ralmaydi** — build paytida
  `installer/client.env` dan (git'da yo'q, `-EnvFile`) ichiga joylanadi;
  `build.ps1` uni oldindan tekshiradi. O'rnatishda faqat ixtiyoriy inventar
  kodi (`^[A-Za-z0-9_-]{3,50}$`).
* `onefile` emas (har ishga tushishda `%TEMP%` ga ochardi), Nuitka emas.
* **Versiya bitta joyda — `client/version.py`**.
* **`.env` o'rnatilgan dasturda `%ProgramData%\ProctoringClient\.env`**
  (`core/bundle_paths.env_file_candidates`: `PROCTORING_ENV_FILE` →
  ProgramData → `.exe` yoni). Qaysi fayl o'qilgani log'da (`main._log_env_file`).
* **O'rnatilgan dasturda jarayon muhiti ISHONCHSIZ** (`core/env_guard.py`) —
  talabgor `setx` bilan foydalanuvchi o'zgaruvchisini adminsiz yozadi:
  * `config` FAQAT `.env` faylidan + kod standartidan (`config._getenv`,
    `env_guard.config_source`); `os.getenv` ni `config.py` da ishlatmang.
    `override=True` yetmasdi — faylda yo'q kalit (`KIOSK_MODE`) muhitdan
    o'qilardi;
  * `main.py` boshida (Qt/log/`config` dan OLDIN) `sanitize_process_env`:
    `QTWEBENGINE*`, `QT_QPA_*`, `CUDA_PATH*`, `SSL_CERT_FILE/DIR`,
    `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`, `INSIGHTFACE_ROOT` o'chiriladi
    (`.env` dagisi keyin `load_dotenv` bilan qaytadi); `SystemRoot`,
    `windir`, `ProgramData`, `ALLUSERSPROFILE` Windows API'dagi qiymatga
    qaytariladi (foydalanuvchi o'zgaruvchisi tizimnikini soyalaydi);
  * `PROCTORING_ENV_FILE` faqat MASHINA darajasida (HKLM), REG_EXPAND_SZ da
    faqat `%ProgramData%` ochiladi;
  * dev rejimda hammasi o'chiq — muhit odatdagidek ustun.
* Shablon `.env.example` EMAS — `installer/env.production.template`. Mavjud
  `.env` ustiga yozilmaydi (`/FORCEENV` — `.bak` bilan). `%APPDATA%\
  ProctoringClient` uninstall'da o'chirilmaydi.
* **cuDNN `9.10.2.21` ga qadalgan** (`requirements-build-gpu.txt`) + ikkinchi
  himoya `cuda_runtime._preload_cudnn_siblings`. Tutun tekshiruvi
  (`ProctoringClientCheck.exe`, `smoke_check.py`) provayderni inferensiyadan
  keyin o'qiydi.
* Avtostart — Task Scheduler (`installer/autostart.ps1`), `HKLM\Run` emas.
* **Administrator huquqi — vazifa orqali, manifest emas** (`uac_admin=False`
  qoladi — UAC oynasi kioskni to'xtatardi). Oddiy huquqda ochilgan nusxa
  (yorliq, `.exe`) mutex'dan keyin o'zini `schtasks /Run` bilan qayta
  ochadi va chiqadi (`core/elevation.py`): faqat frozen, argumentsiz,
  token `Limited` va vazifa AYNAN shu `.exe` ni ochsa. Yangi nusxa 15 s
  ichida mutex'ni egallamasa — oddiy huquqda davom etadi. Oddiy (standard
  user) hisobda yuqori huquq yo'q. Vazifa nomi `.iss` `TaskName` =
  `elevation.TASK_NAME`. Vazifaga `(A;;GRGX;;;AU)` ruxsati SHART
  (`autostart.ps1`) — usiz oddiy huquqli jarayon vazifani o'qiydi, lekin
  `/Run` "Access is denied" (kod 1) oladi.
* **Bitta nusxa** — `core/single_instance.py` (mutex `Local\ProctoringClient.SingleInstance`,
  `main()` ning birinchi qadami; `--keyboard-hook`/`--watchdog` olmaydi).
  Ikkinchi nusxa JIMGINA yopilmaydi (`notify_running`): birinchisining
  oynasi bor — oldinga chiqaradi, splash ko'rinib turibdi — hech narsa,
  aks holda "kuting" xabari (4 s, o'zi yopiladi, bir vaqtda bitta).
  Asosiy oyna sarlavhasi = `APP_NAME` (ikkinchi nusxa shu bo'yicha
  qidiradi), splash'niki boshqa.
* **Splash — nativ, mutex'dan keyin darhol** (`core/early_splash.py`,
  ~0.15 s): ctypes, o'z thread'i va xabar sikli (asosiy thread band
  bo'lsa ham chiziladi, progress yuguradi), Qt'siz, fokus olmaydi; asosiy
  oyna birinchi chizilgach yopiladi (`QTimer.singleShot(0, ...)`).
  Vazifa orqali qayta ochishda eski nusxa splash'ni yangisi mutex'ni
  olgandan keyin yopadi — uzilish yo'q. Klass nomi
  `single_instance.SPLASH_CLASS_NAME`. Qt splash
  (`ui/widgets/startup_splash.py`) — faqat nativ ishlamasa. `ApiClient`
  tozalash bilan parallel fon thread'ida yaratiladi
  (`main._prewarm_api_client`, TLS to'plami ~0.3 s).
* Yangilash imtihondan TASHQARIDA (o'rnatuvchi `taskkill /F` qiladi).
* Build mashinasida `ProctoringClient.exe` ni `.env` SIZ ochmang — standart
  to'liq kiosk.

### Backend app'lari (`backend/src/apps/`)

| App | Mas'uliyat |
|---|---|
| `common` | Renderer, exception handler, pagination, permissions, throttling, Redis, crypto, DB router, `storage.py` (S3) + `screenshot_storage.py` |
| `users` | Xodimlar (`AUTH_USER_MODEL`), `Role`/`Permission` (code-based) |
| `regions` | Viloyat, Zone (bino) |
| `devices` | Computer, Camera (RTSP parollari shifrlangan), DeviceToken |
| `controls` | IP ro'yxati, COCO/RDP obyektlari, hotkey, model versiyalari, `Setting`, `ProctoringPolicy`, `EventRiskWeight` |
| `exams` | Exam, ExamSchedule, ComputerBooking |
| `proctoring` | ExamSession, ProctoringEvent (partitsiyalangan), FaceVerificationLog, ScreenshotMeta + ProctoringScreenshot, EvidenceArtifact, LocalRecording, TechnicalProblem, AuditLog + consumers/tasks/services |
| `integrations` | Tashqi platforma (`exam_site.py`), FaceID integratsiyasi |

Har app: `models.py` / `selectors.py` (o'qish) / `services.py` (yozish,
biznes-mantiq) / `api/v1/{serializers,views,urls}.py`. View'lar yupqa.

`proctoring/api/v1/` da ikki yuza: `views.py`+`urls.py` (panel, JWT) va
`client_views.py`+`client_urls.py` (`/api/v1/client/...`, boshqa auth va throttling).

### Autentifikatsiya

* Panel — SimpleJWT (`Bearer`), refresh rotatsiya + blacklist.
* Desktop client — uch qatlam (`proctoring/authentication.py`): xodim JWT
  ("kim"), `X-Device-ID` ("qaysi kompyuter", **kredensial emas**), opaque
  sessiya tokeni (Redis'da — chetlashtirish darhol kuchga kiradi).
* **WebSocket**: `MonitorConsumer` (brauzer) tokenni query'dan;
  `ClientConsumer` avval `X-Proctoring-Session` header'dan, keyin query
  (eski client).
* Ruxsatlar — `HasRolePermission` (`required_permission = "sessions.view"`)
  + `RegionScopedPermission` (obyekt darajasida IDOR himoyasi; asosiy filtr
  `get_queryset()` da). Amalga xos ruxsat — `action_permissions`
  (`{"warn": "sessions.warn"}`), POST amallar bitta `required_permission`
  ga tushmasin.
* **Panel yuzasi — `panel.access`** (`User.has_panel_access`): client va
  panel BIR XIL JWT, shuning uchun panelning HAR endpointi `HasPanelAccess`
  (`PermissionRequiredMixin` o'zi qo'shadi; mixin'siz panel view'iga qo'lda,
  `MonitorConsumer` da ham). Panel login'i `surface: "panel"` yuboradi →
  403 `panel_access_denied`; client `surface` yubormaydi. Operator — faqat
  `client.*`. `*` — to'liq huquq (kelajakdagi ruxsatlar ham, `codes_grant`).
  Rol muharriri: o'zida yo'q ruxsatni qo'shib bo'lmaydi, o'z rolidan
  `panel.access`/`users.manage` ni olib bo'lmaydi (`RoleSerializer.validate`).
* **`seed_base_data` (har deploy) rol ruxsatlarini BOSMAYDI**: matritsa faqat
  yangi rolga va YANGI paydo bo'lgan ruxsatga; to'liq qaytarish —
  `--reset-roles`. `panel.access` birinchi paydo bo'lganda panel ruxsatli
  rollarga beriladi, `client.operate` lilarga — yo'q.
* **Viloyat chegarasi — uch qatlam** (`apps/users/tests/test_region_access.py`):
  * **KIM**: `Role.is_global` yoki superuser — respublika; qolganlari —
    `User.region`. Viloyat roli + viloyat yo'q (`User.lacks_region`) —
    panelda HECH NARSA (`HasRegionAssignment` 403 `region_not_assigned`;
    client yuzasiga ulanmagan). Panel `RegionMissingState`;
    `UserWriteSerializer` bunday hisobni rad etadi.
  * **O'QISH**: har `get_queryset()`; so'rovdagi viloyat —
    `common.permissions.scope_region_id`. Audit — `actor__region`.
  * **YOZISH**: serializer'da `common.region_scope.ensure_in_region`. Umumiy
    ma'lumot (rol, viloyatlar, sozlamalar, AI siyosati, imtihonlar) —
    `republic_write_only = True` (`RepublicLevelWrite`, 403
    `republic_level_only`); panelda `ResourcePage shared` /
    `AuthContext.canShared`. Viloyat admini respublika rolini bera olmaydi.
* **`client/preflight/`** (ochiq, JWT'siz) — client aytgan `public_ip`
  `AllowedPublicIp` da bo'lmasa login formasi ko'rsatilmaydi. Bu qulaylik
  to'sig'i; haqiqiy tekshiruv `ClientBaseView.check_source_ip` (server
  ko'rgan manzil).
* **`ALLOW_PRIVATE_SOURCE_IP`**: server bino ichida/dev'da LAN/loopback
  manzilni ko'radi — `false` bilan hamma rad (belgisi: preflight o'tadi,
  keyin 403 `ip_not_allowed`). `local.py` da `true`, production'da `false`.
  Faqat xususiy manzilga tegishli. **Production'da uning o'rniga TARMOQ
  yozuvi** (`AllowedPublicIp.network`, CIDR, binoga bog'langan): server
  joylashgan bino (LAN) va kelajakdagi VPN (har bino o'z subnet'i) uchun.
  Yozuv — IP YOKI tarmoq (`allowed_ip_one_kind`); aniq IP tarmoqdan ustun;
  tarmoqlar kesishmaydi, /8 dan keng emas — qoida bitta joyda
  (`controls.services.clean_allowlist_entry`, panel + Django admin).
  Preflight'da server ko'rgan manzil FAQAT tarmoq yozuviga mos kelsa
  hisoblanadi; binoni aniqlash (`resolve_zone_by_public_ip`) ham tarmoq
  bo'yicha.
* **`REQUIRE_ALLOWED_IP`** (standart `true`): `AllowedPublicIp` bo'sh bo'lsa
  hech kim kirmaydi; `false` da bo'sh ro'yxat = tekshiruv o'chiq.
* **Kiosk rejimi** (`KIOSK_MODE`, standart = `FULLSCREEN`): ramkasiz + doim
  ustda, `services/lockdown.py` orqali tezkor tugma bloklash, parolsiz
  yopilmaslik.
* **Klaviatura qulfi — alohida jarayon, xom hook, modifikatorga tegmaydi.**
  `keyboard` kutubxonasi OLIB TASHLANDI — QAYTARMANG. Qatlamlar:
  `services/keyboard_hook.py` (xom `WH_KEYBOARD_LL`), `lockdown.KeyPolicy`
  (sof, testlanadi), `services/keyboard_hook_process.py` (client o'z exe'sini
  `--keyboard-hook` bilan ko'taradi; `main.py` bayroqni Qt/log/`.env` dan
  OLDIN tekshiradi; stdin/stdout JSON). Testlar —
  `tests/test_lockdown_hook.py`.
  * Alohida jarayon — client ichida GIL tufayli hook tugmalarni ~100–400 ms
    kechiktirardi va Windows hook'ni jimgina o'chirardi.
  * Client o'lsa qulf stdin EOF bilan chiqadi; qulf o'lsa client qayta
    ko'taradi (`hook_lost` → `hook_restored`); ishga tushmasa `_LocalEngine`.
  * Faqat ASOSIY tugma yutiladi; modifikator holati `GetAsyncKeyState` dan;
    yutilgan tugma o'z UP'igacha yutiladi.
  * VK bo'yicha (skan-kod emas); injekt qilingan hodisa ham tekshiriladi.
  * Tiriklik — canary (`KeyboardHook.probe`, 5 s); bo'sh mashinada
    tekshirilmaydi (`IDLE_SKIP_S`) — aks holda ekran saqlagich/auto-lock o'chardi.
  * Yopishgan modifikator (`KeyPolicy.tick`): Alt/Ctrl/Win 20 s, Shift 60 s.
  * Nosozlik — `proctoring_degraded` (`module: keyboard`, `reason: stuck_key
    | hook_restored | hook_lost`), yangi hodisa turi yo'q.
* **Kiosk oynasida System Menu yo'q**: `lockdown.kiosk_window_flags`
  (`WindowSystemMenuHint`, Min/Max/Close olinadi — qolsa Qt ramkani
  qaytaradi) + `install_system_menu_guard` (native filtr: Alt+Space
  `WM_SYSKEYDOWN`, `WM_SYSCHAR ' '`, `SC_KEYMENU`, `SC_MOUSEMENU`).
* **Chiqish**: preflight ekranida parol so'ralmaydi; login sahifasidan
  boshlab yagona yo'l — **Ctrl+Q** + parol ("Chiqish" tugmasi ataylab yo'q).
* **Chiqish paroli** — `client/exit/verify/`: xodimning o'z paroli (JWT
  bo'lsa) yoki `controls.ClientExitPassword` (har viloyat uchun, hash;
  API qaytarmaydi). Endpoint autentifikatsiyasiz (`ExitVerifyThrottle`).
  Parol sozlanmagan — `exit_password_not_configured`, client tasdiqlash
  dialogiga o'tadi.
* **Throttle — ikki qavat, chunki operator hisobi REGIONGA bitta** (bino
  ~500 mashina, bitta NAT IP). Login, JSHSHIR qidiruvi, chiqish paroli:
  `*DeviceThrottle` (bazadagi `X-Device-ID` — mashinaga qat'iy,
  `common/throttling.py:device_user_ident`) + hisob/bino bo'yicha keng
  (`StaffLoginThrottle`, `PinflLookupOperatorThrottle`, `ExitVerifyThrottle`).
  Faqat `user:{pk}` yoki IP kaliti butun binoni bitta byudjetga tiqadi.
  Kenglarini oshirish (`THROTTLE_*`) — mashina chegarasini emas. DRF ro'yxati
  har so'rovda to'liq qayta yoziladi — o'n minglab limit qo'ymang.
* Har urinish `client/access-attempt/` → `backend/logs/client_access.log`
  (`client_access` logger), `AuditLog` ga emas.

> `README.md` dagi qurilma HMAC imzosi (`X-Device-Signature`) **olib
> tashlangan** (sababi `authentication.py` docstring'ida). Client oqimida
> `identity/confirm/` `exam/access/` dan OLDIN keladi.

### JSHSHIR: panelda TO'LIQ, clientda NIQOBLANGAN

Panel javoblari (`SessionListSerializer`, `SessionCandidateSerializer`) to'liq
raqam beradi va qidiruvga kiradi; `masked_pinfl` eski panel uchun.
Clientda niqob qoladi (ekran oldida begonalar bor).

### Javob konverti

Barcha javoblar `ApiJSONRenderer` orqali `{success, data, error}`; xatolar
`apps.common.exceptions.api_exception_handler` dan `code`/`message`/`details`.
Frontend axios interceptor'i konvertni ochadi (`response.data.data` yozilmaydi).
Yangi domen xatosi — `DomainError` merosxo'ri; `code` React'da tarjima kaliti.

### Frontend (`frontend/src/`)

* URL'lar faqat `api/endpoints.js` da.
* **CRUD sahifalari bitta dvigateldan**: `components/data/ResourcePage.jsx` +
  `useResource.js` + `ResourceForm.jsx` + `DataTable.jsx`; yangi sahifa =
  `columns` va `fields` (`pages/crud/*.jsx`). Dvigateldan chetga chiqmang.
* Marshrutlar `App.jsx` da, lazy chunk'lar `layout/navigation.js:ROUTE_LOADERS`
  (menyu prefetch bilan bir xil loader). `Guard` — faqat UI qulayligi.
* **Hodisa turkumlari faqat frontendda** (`utils/events.js`: `integrity` /
  `identity` / `behaviour` / `system`). Yangi hodisa turi —
  `utils/labels.js:EVENT_LABEL` VA `utils/events.js:EVENT_CATEGORY`
  (`ProctoringEvent.Type` bilan to'liq mos, hozir 41 tur).
  **Yangi turni client'da serverdan OLDIN yubormang**: `EventItemSerializer`
  (`ChoiceField`) bitta noma'lum tur uchun BUTUN batch'ni 400 bilan rad
  etadi va client uni tashlaydi — ichidagi boshqa hodisalar bilan. Yangi
  tur client'da server sozlamadagi kalit bilan yoqiladi (namuna:
  `device.detect_peripherals`, client standarti `False`).
* **WebSocket `detail` — oq ro'yxat** (`ingest._BROADCAST_DETAIL_KEYS` va
  `utils/events.js:eventDetail` — ikkala tomonda qo'shing).
* Sessiya tafsiloti: `components/session/ScreenshotGallery.jsx` (blob
  URL'lar bitta joyda — `useShotUrls`; ko'rish oynasi doim qorong'i;
  kartalar `contain`), `LocalRecordings.jsx` (asosiy ma'lumot — mashinadagi
  to'liq yo'l).
* Tema: `theme/palettes.js` (5 sxema × 3 rejim × 2 zichlik),
  `context/UiContext.jsx`, `localStorage`.
* **AppBar yo'q** (`layout/AppLayout.jsx`): profil, viloyat, tungi rejim,
  chiqish — yon panel pastida. `>= lg` to'liq/rail
  (`UiContext.sidebarCollapsed`), `md..lg` rail, `< md` yashirin + 56 px
  mobil satr. Ctrl+K — `layout/CommandPalette.jsx`.
* **Har menyu bandida `description`** (`layout/navigation.js`); bo'lim nomi
  `findNavEntry` dan.
* **Material 3 rollari `theme.palette.m3` da** — palitradan hisoblanadi
  (`theme/index.js:mix`); `sx`: `bgcolor: 'm3.surfaceContainerLow'`.
* **(tuzoq) `sx` dagi son `borderRadius` 12 ga ko'paytiriladi** — aniq qiymat
  uchun satr (`'12px'`), kapsula — `999`.
* Shrift — `@fontsource-variable/inter`, paket ichida (CDN emas).
* **Tafsilot kartasi** (qator bosilganda): `ResourcePage onRowClick` +
  `components/data/DetailDialog.jsx` (qobiq, `StatTiles`, `InfoNote`) va
  `DetailFields` (`Section`/`Field`). Muammo (nima uchun ishlamaydi)
  karta TEPASIDA `problems` bilan. Ro'yxat qiymatlari — JSON matn emas,
  `components/controls/ChipListInput.jsx`.
* **Ommaviy amal — `ResourcePage bulkActions`** (+ `isRowSelectable`).
  Backend `common.mixins.BulkSelectionMixin`: `{"ids": [...]}` yoki
  `{"all": true}` + ro'yxat query parametrlari (`useResource.scopeParams`),
  `get_queryset()`/`filter_queryset()` dan o'tadi. Hozir:
  `computers/bulk-delete/` (imtihondagi mashina o'tkaziladi),
  `device-tokens/bulk-approve/` (faqat kutayotganlar). Audit bitta yozuv.
* **`/device-tokens` jadvali qisqa** — tafsilot va amallar yon varaqda
  (`components/devices/DeviceDetailSheet.jsx`). 1440 px da gorizontal
  skroll chiqmasin.
* **Viloyat → bino filtri** — `pages/crud/shared.jsx:regionZoneFilters`.
  Faqat «Bino» filtrini qo'ymang.
* **Sahifalash**: `DataTable` (server, «Sahifada» `localStorage` da);
  DataGrid'siz ro'yxatlar `DataTable.TablePager`; sessiya tab'lari
  `hooks/useCursorPages` (kursor, 50). **`list({ page_size: N })` bilan
  "hammasini" olmang** — `useOptions` / `listAll`.
* **Telefon (< md)**: filtr maydonlariga `components/data/responsive.js:
  filterFieldSx(min, max, { half })`; `DataTable` `autoHeight`; oddiy
  `<Table>` — `minWidth` + `overflowX: 'auto'`; `ResourceForm` to'liq
  ekran (tema qoidasi `:not(.MuiDialog-paperFullScreen)`); `ToggleButtonGroup`
  surilsin, o'rovchi flex'ga `minWidth: 0`; uzun formada saqlash — extended FAB.

## Tuzoqlar

* **Yuz balli shkalasi** (`max(0, cos)*100`) ikki tomonda bir xil;
  o'zgarsa chegaralar va ballar migratsiya bilan ko'chiriladi.
* **`face_checks` ni serverda oshirmang** — client `hset` bilan yozadi.
* **`multipart/form-data` da `embedding` JSON satr** va DRF uni bir
  elementli ro'yxatda beradi — `EmbeddingField` ikkala shaklni ochadi.
* **`FaceVerificationLog.session` NULL mumkin** — `select_related("session")`
  yoki `session__` filtri kira olmagan urinishlarni jimgina tashlaydi.
* **`filter_backends` ni ViewSet'da qayta e'lon qilmang** — `search_fields`
  / `ordering_fields` jimgina o'chadi.
* **Kursor va offset sahifalash aralash**: sessiya/hodisa/audit `count`
  qaytarmaydi, `?page=2` jimgina e'tiborsiz. Frontend shaklni avtomatik aniqlaydi.
* **Kursor unikal ustunga**: audit — `AuditCursorPagination` (`-id`).
  Skrinshot va dalil ro'yxatlarida `EventCursorPagination` (`-occurred_at`)
  emas, `ScreenshotCursorPagination` (`captured_at`).
* **`204` javobiga tana qo'shilmaydi** (`ApiJSONRenderer` o'tkazib yuboradi).
* **`CHANNEL_LAYERS`: `socket_timeout` (30 s) > `brpop_timeout` (5 s)** —
  redis-py 8 standarti consumer'ni yiqitadi.
* **Channel layer ulanishi `retry` SIZ ishlatilmaydi**
  (`settings.base._channel_layer_host`) — bo'sh ulanish yo'lda o'ladi
  (dev'da WSL2 Redis bilan 45–60 s). Consumer'lar layer xatosida `1011`
  bilan yopiladi; panel (`useLiveMonitor`) "ulangan" deb faqat `subscribed`
  dan keyin ko'rsatadi.
* **Davriy vazifada `expires` MAJBURIY** (`test_celery_config`). Navbatni
  tozalashda bir martalik vazifalarni (`report_session_result`) o'chirmang.
* **`celery beat` bittadan ortiq** — ingest buferida dublikat.
* **(client) WebSocket boshqa jarayon**: `WS_BASE_URL` berilmasa client uni
  API manzilidan chiqaradi va dev tartibini taniydi (`realtime.default_ws_url`);
  noto'g'ri port bilan proktor buyruqlari clientga yetmaydi.
* **Migratsiya fayllari git'da UMUMAN YO'Q** (faqat `__init__.py`;
  `backend/.gitignore`: `**/migrations/*`, `git add -f` QILMANG): lokal
  va production migratsiyalari bir-biriga mos kelmaydi — har muhit
  `makemigrations` ni o'zi bajaradi va o'z fayllariga ega. Repodagi fayl
  serverdagi bir xil nomli faylni bosib ketgan (`0001_initial`) va
  `migrate` `KeyError` bilan yiqilgan. Oqibatlari: migratsiyadagi
  `RunPython` (ma'lumot ko'chirish) serverga yetib bormaydi — uni
  alohida aytish kerak; yangi klonda avval `makemigrations`.
  `src/config/settings/local.py` ham `.gitignore` da.
* **Read replica**: "yozdim va darhol o'qidim" da `.using("default")`
  (`common/db_router.py`).
* **Konfiguratsiya modellari `SoftDeleteModel`** — `.delete()` `deleted_at`
  qo'yadi; ro'yxatlarda `.alive()`.
* **Redis `maxmemory-policy noeviction`** — `allkeys-lru` sessiya tokenlarini
  o'chiradi.
* **Python `203.0.113.0/24` (va boshqa RFC 5737) ni xususiy deb biladi** —
  testda ommaviy manzil uchun `8.8.8.8`.
* **(test) Client yuzasida `force_authenticate` ishlatmang** — yon ta'sirli
  `DeviceResolution`/`SessionTokenAuthentication` ishlamay qoladi. Haqiqiy JWT
  (`tests/test_client_api.py:bearer`).
* **(test) Oqimli javobda `response.close()` ni qo'lda chaqirmang** — test
  DB ulanishini yopadi; `list(response.streaming_content)`.
* **`ProctoringEvent.evidence_id` FK EMAS** (partitsiya + `bulk_create`);
  tartib: fayl → dalil qatori → hodisa.
* **`ProctoringPolicy` yo'qligi — standart qiymatlar** (`_default_proctoring`),
  bo'sh lug'at emas.
* **`FrameFeatures.timestamp` uchun `0.0` haqiqiy qiymat** — `x or default`
  yozmang (`EventFusion` cooldown'ida ham).
* **(client) ByteTrack `min_hits` ni 1 ga tushirmang.**
* **(client) `pyqtSignal` ni `event` deb nomlamang** — `QObject.event()` ni
  bosadi va jarayon jimgina qulaydi.
* **(client) Dalil `boxes` JSON satr sifatida** (`validate_boxes`, ≤ 20 ramka).
* **(client) To'xtatish tartibi: pipeline → monitor** (supervisor ichida:
  pipeline → kameralar) — ochiq hodisalar buferga tushishi kerak.
* **(client) `QThread` "ishlayapti" bayrog'ini `run()` ichida qo'ymang** —
  `start()` da, chaqiruvchi thread'da (`device_watch._ProcessScanner`).
* **(client) Ishlab turgan `CameraWorker` ni `None` qilmang — `retire_camera()`**.
  Egasiz QThread kamerani band qiladi va keyin `0xC0000409` bilan qulaydi
  (`_LIVE` registri faqat qulashni to'sadi).
* **(client) Qat'iy o'lchamli vidjet siqilgan ustunda ustma-ust tushadi** —
  `faceid_page._fit_photo` rasmni karta balandligidan o'lchaydi; yangi
  element qo'shganda 1366x768 da tekshiring.
* **(client) Kamera nomini PnP ro'yxatidan olmang** — `camera/dshow.py`.
* **(client) Otasiz vidjetda `setVisible(True)`/`show()` chaqirmang**
  (`__init__` ichida ham) — Qt uni ALOHIDA OYNA qilib ochadi: ishga
  tushishda chap yuqorida kichik oyna miltillardi (`BrandLogo`). Faqat
  yashiring; ko'rinish otadan meros qoladi.
* **(client) `onnxruntime-gpu` nashri CUDA versiyasiga qadalgan** — nomos
  nashr jimgina CPU'da ishlaydi.
* **(client) `ctypes` da `argtypes` ham SHART** — usiz 64-bit deskriptor
  `OverflowError` beradi (yoki `ctypes.c_void_p(...)` ga o'rang).
* **(client) Windows tizim binarlarining PE resursi `.mui` dan** —
  `OriginalFilename` `mstsc.exe.mui` bo'ladi (`process_identity._strip_mui`).
* **(client) Imtihon sahifasida `MessageBar` emas, `Snackbar`.**
* **Tezkor tugma lug'ati UCH joyda**: client `services/lockdown.py`
  (manba), server `controls/hotkeys.py` (saqlashda tekshiradi, kanonik
  shakl; testda client bilan solishtiriladi), panel `utils/hotkeys.js`.
  Client tanimagan kodni BLOKLAMAYDI — yangi tugma nomi uchalasiga.
  RDP qoidasi kamida bitta belgisiz saqlanmaydi (belgisiz qoida hech
  narsani tutmaydi). Dastur/tugma faqat profilga (`Setting.rdp_objects`
  / `hotkeys`) kirsa client'ga yetadi — API `profiles` maydoni.
* **(frontend) Import qilinmagan komponent build'dan o'tadi**, faqat
  brauzerda `ReferenceError` beradi (ESLint yo'q, Vite `no-undef` ni
  tekshirmaydi). Yangi JSX'da aniqlanmagan identifikatorlarni tekshiring
  (`@babel/parser` + `@babel/traverse` `node_modules` da bor).

## Muhit o'zgaruvchilari

`backend/.env` (namuna `.env.example`) va `frontend/.env.example`.
Production'da majburiy: `SECRET_KEY`, `TOKEN_HASH_KEY`,
`FIELD_ENCRYPTION_KEY`, `JWT_SIGNING_KEY`. `TOKEN_HASH_KEY` o'zgarsa barcha
sessiya tokenlari bekor bo'ladi; `FIELD_ENCRYPTION_KEY` o'zgarsa shifrlangan
maydonlar (`Camera.password_encrypted`, `Exam.site_header_encrypted`)
o'qilmaydi.

Dev: `BASE_API_MOCK=true`, `DISABLE_THROTTLING=true`,
`REQUIRE_DEVICE_ID=false`, `S3_ENABLED=false`.

**Client dev mashinasida `false` bo'lishi kerak** (standarti `KIOSK_MODE`
dan): `CLOSE_OTHER_APPS` (muharrir/terminalni yopadi),
`THREAT_SCAN_ENABLED` (VirtualBox, WSL2, Docker), `DISABLE_EXTRA_MONITORS`
(ikkinchi monitor); shuningdek `LOCAL_ARCHIVE_ENABLED=false`.
