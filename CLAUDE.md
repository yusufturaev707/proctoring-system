# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Til

Kod izohlari, docstring'lar va UI matnlari **o'zbek tilida**. Yangi kod
yozganda shu uslubni saqlang: izoh "nima qilinyapti"ni emas, **"nima uchun
aynan shunday"**ni tushuntiradi — deyarli har bir arxitektura qarori mavjud
fayllarda izohda asoslangan.

## Buyruqlar

Barcha backend buyruqlari `backend/` dan (`manage.py` `src/` ni `sys.path` ga
o'zi qo'shadi). Virtual muhit: `backend/.venv`.

```bash
# Backend (Windows)
cd backend && .venv/Scripts/activate
python manage.py migrate
python manage.py setup_partitions --apply --days 30   # proctoring_event partitsiyalari
python manage.py seed_base_data --demo                # rol/ruxsat matritsasi + demo data
python manage.py runserver 8002                           # HTTP API :8000

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

**WINDOWS'DA CELERY `threads` POOL BILAN ISHLAYDI** (`config/celery.py`
buni o'zi qo'yadi, `-P` bilan berilgani ustun). Standart `prefork`
Windows'da vazifalarni JIMGINA BAJARMAYDI: ishchi "ready" deydi,
navbatdan oladi, lekin `celery -A config inspect stats` da `"total": {}`.
Belgilari: jonli kuzatuvda sessiya bir necha daqiqadan keyin "aloqa
yo'q" bo'ladi (`last_heartbeat_at` write-behind bilan yoziladi), xavf
balli faqat sessiya yakunida paydo bo'ladi, hodisalar DB'ga tushmaydi
(Redis `proctoring:events` da `lag` o'sib boradi). Tekshirish:
`inspect stats` dagi `"implementation"` va `"total"`.

`DJANGO_SETTINGS_MODULE` standart qiymati `config.settings.local`.
**`.env` KIRISH NUQTALARIDA sozlama tanlanishidan OLDIN yuklanadi**
(`config/env.py` → `manage.py`, `wsgi.py`, `asgi.py`, `celery.py`). Ilgari
uni faqat `settings/base.py` o'qirdi — juda kech: `.env` dagi
`DJANGO_SETTINGS_MODULE=config.settings.production` jimgina e'tiborsiz
qolib, gunicorn/uvicorn/Celery LOCAL sozlamalar bilan ishlardi. Muhit
o'zgaruvchisi (systemd `Environment=`, `--settings`) har doim ustun.

**PRODUCTION DEPLOY — `backend/deploy/`**: `deploy.sh` (takroriy, atomik
frontend, `check --deploy --fail-level WARNING`), `env.production.example`,
`systemd/` (5 servis + `proctoring.target`), `nginx.conf.example` +
`proxy_common.conf`. Tartib va qoidalar — `deploy/README.md`. Production
statik fayllari `STORAGES` orqali (`STATICFILES_STORAGE` Django 5.1 da olib
tashlangan va jimgina e'tiborsiz qolardi); frontend API/WS'ni sahifaning
o'z manzilidan oladi (`.env.production` bo'sh qiymatlar — `.env.local`
dan ustun).

Muhitlar: `local` (throttling o'chirilgan, `REQUIRE_DEVICE_ID=false`,
BrowsableAPI yoqilgan), `production` (majburiy sirlarni ishga tushishda
tekshiradi), `test` (locmem cache, in-memory channel layer, eager Celery,
throttling o'chirilgan).

### Test

```bash
cd backend
python manage.py test --settings=config.settings.test          # hammasi
python manage.py test apps.proctoring --settings=config.settings.test
```

Label berilmasa `apps` paketi qidiriladi (`config/test_runner.py`) —
standart `DiscoverRunner` `backend/` dan qidirib hech nima topmasdi va
buni "testlar o'tdi" deb o'qish oson edi.

**PostgreSQL kerak** (test bazasi migratsiyalardan yaratiladi).
**Redis ixtiyoriy**: unga tayanadigan testlar u yo'q bo'lsa
`skip` qilinadi (`apps/common/tests/utils.py:RedisStateMixin`). Test
Redis'i **15-baza** — dev holatiga (2-baza) tegilmaydi.

Testlar joylashuvi: `apps/<app>/tests/test_*.py`. Ma'lumot yasovchilar
`apps/proctoring/tests/factories.py` da.

Alohida end-to-end smoke test ham bor:

```bash
cd backend && python scripts/smoke_test.py
```

Client'ning sof mantiqli qismlari (Qt va modelsiz) uchun testlar
`client/tests/` da:

```bash
cd client && venv/Scripts/python -m unittest discover -s tests
```

**DIQQAT:** u boshida barcha `ExamSession` yozuvlarini va `sess:*` Redis
kalitlarini o'chiradi — faqat dev bazasida ishlating. Faylda absolyut yo'l
(`C:\Projects\...`) hardcode qilingan.

`npm run lint` script'i bor, lekin `frontend/` da ESLint konfiguratsiyasi
YO'Q — konfiguratsiya qo'shilmaguncha u ishlamaydi.

## Arxitektura

### To'rt process, uch ma'lumot qatlami

HTTP API (WSGI), WebSocket (ASGI/Channels), Celery `ingest`, Celery `beat`
alohida ishlaydi — yuklama profillari mos kelmaydi (batafsil:
`backend/deploy/README.md`).

Markaziy qaror — **ikki bosqichli yozish**: client so'rovi Redis Stream'ga
`XADD` qilinadi va darhol javob oladi; Celery har 5 soniyada buferni
`bulk_create` bilan bitta tranzaksiyada yozadi. Yangi yuqori chastotali
endpoint qo'shsangiz, DB'ga to'g'ridan-to'g'ri yozmang — shu yo'ldan boring
(`proctoring/services/ingest.py` + `services/stream.py`).

* **Hot** — Redis: sessiya holati, heartbeat, hisoblagichlar
  (`proctoring/services/state.py`, write-behind 10s da bir marta)
* **Warm** — skrinshot va yuz rasmlari (pastdagi "Skrinshot storage")
* **Cold** — PostgreSQL: sessiya, hodisa, audit (huquqiy dalil)

Istisno: kritik hodisalar (chetlashtirish, FaceID muvaffaqiyatsizligi)
write-behind EMAS — darhol DB'ga yoziladi.

`services/stream.py` uchta yo'qotish stsenariysini qamrab olgan:
`XAUTOCLAIM` bilan osilib qolgan PEL yozuvlarini qaytarish, batch yiqilsa
qator-ma-qator yozish, yozib bo'lmagan qatorni `:dead` oqimiga ko'chirish.
Bu mantiqni soddalashtirmang — proktorlikda "dalil yo'qoldi" holati
bo'lmasligi kerak.

### Skrinshot storage — IKKI yo'l

Ikkalasi parallel yashaydi, o'rnatish profiliga qarab bittasi yoqiladi.
Ular alohida model, alohida endpoint va alohida retention'ga ega:

| | S3/MinIO | Fayl tizimi |
|---|---|---|
| Model | `ScreenshotMeta` (`object_key`) | `ProctoringScreenshot` (`file_path`) |
| Yuklash | `client/screenshots/presign/` + `commit/` | `client/screenshots/upload/` |
| Binary backenddan | **o'tmaydi** (presigned PUT) | **o'tadi** (multipart) |
| Ko'rsatish | presigned GET URL | `screenshots/{id}/file/` → `X-Accel-Redirect` |
| Retention | `purge_expired_artifacts` (`purge_after`) | `purge_expired_screenshots` (`captured_at`) |
| Ko'lami | 10 000 client (~120 MB/s) | ~bitta bino (~500 client) |
| Yoqish | `S3_ENABLED=true` | `SCREENSHOT_FILESYSTEM_ENABLED=true` |

Production'da kamida bittasi yoqilgan bo'lishi shart (`production.py`
ishga tushishda tekshiradi).

Fayl tizimi yo'lining qat'iy qoidalari:

* **DB'da faqat nisbiy yo'l.** Root `SCREENSHOT_STORAGE["ROOT"]` da;
  qatorda absolyut yo'l saqlansa, root ko'chganda hammasi yaroqsiz
  bo'ladi va API javobida server strukturasi oshkor bo'ladi.
* **Fayl turi baytlardan aniqlanadi** (Pillow), `Content-Type` va
  kengaytmadan EMAS — `.jpg` niqobidagi HTML `internal` location'dan
  berilsa, bu saqlangan XSS.
* **Yozish tartibi: avval fayl, keyin DB qatori.** Qator yozilmasa fayl
  darhol o'chiriladi. Teskarisida ochilmaydigan "dalil" qoladi.
* **O'chirish tartibi: avval fayl, keyin qator** (`screenshot_delete`).
  Teskarisida hech kim biladigan yetim fayl qoladi.
* **Storage'ga faqat interfeys orqali murojaat qilinadi**
  (`common/screenshot_storage.py`: `save`/`delete`/`exists`/`serve`/
  `prune_empty_dirs`). `open()` yoki `os.unlink()` ni service yoki view
  ichida yozmang — S3-mos backend qo'shish shu bilan bir faylga
  jamlanadi.
* **`serve` HTTP javobini qaytaradi, baytlarni emas.** Fayl tizimida bu
  `X-Accel-Redirect`, ya'ni baytlar Python'dan o'tmaydi. Dev'da nginx
  yo'q, shuning uchun `SCREENSHOT_SERVE_DIRECTLY=true` (production'da
  bu qiymat ishga tushishni to'xtatadi).
* nginx `internal` location'siz butun himoya yo'q — `deploy/nginx.conf.example`.

PANEL IKKALA RO'YXATNI HAM SO'RAYDI (`SessionDetail.jsx`:
`screenshots/` + `stored-screenshots/`, `captured_at` bo'yicha
birlashtiriladi). Ilgari faqat birinchisi so'ralardi va fayl
tizimli o'rnatishda skrinshotlar bazada turgan holda tab doim bo'sh
edi. Fayl tizimidagi rasm blob sifatida olinadi (`screenshotFile`):
`<img>` so'roviga brauzer `Authorization` qo'shmaydi.

Client tomoni (`client/services/screen_capture.py`) qaysi yo'l yoqilganini
**oldindan bilmaydi** — handshake buni aytmaydi. Rejim sessiya boshida bir
marta aniqlanadi: `presign/` 503 qaytarsa, fayl tizimi yo'liga o'tiladi.
Yangi sozlama qo'shganda shu shartnomani buzmang.

**SKRINSHOT TAYMERSIZ — TEST PLATFORMASI BUYURGANDA** (`controls.0013`:
`screenshot_interval` va `screenshot_dedup_threshold` OLIB TASHLANDI).
Talabgor javob belgilaganda platforma frontendi client'ning lokal
xizmatiga `POST http://localhost:8050/api/capture_screen` yuboradi
(pastdagi "Lokal xizmat"). Taymer kadrlarining katta qismi o'ylayotgan
talabgorning bir xil ekrani edi (dedup shuning uchun bor edi); buyruq
kadri esa ma'noli lahza va DEDUP QILINMAYDI. Kadr mashinada HAR DOIM
saqlanadi; serverga yuborish — `Setting.is_screenshot_upload` (panel
«Saqlash joyi»: faqat mashinada / mashinada + serverga, fonda).

`services/screen_capture.py` da UCH MUSTAQIL BOSQICH: olish (UI thread,
buyruq lahzasi, kamera kadri bilan) -> kodlash + mahalliy arxiv (fon) ->
yuklash (fon, BITTA uchuvchi so'rov, xatoda 15 s dan keyin qayta). Ilgari
yuklash tugamaguncha keyingi kadr TASHLANARDI — buyruqda bu javob
belgilangan savolning yagona dalilini yo'qotish. Arxiv konteksti BUYRUQ
paytida olinadi (`local_archive.context()`) — kodlash tugaguncha sessiya
yopilishi mumkin.

**SAVOL KADRI — SAVOLGA BITTA, QAYTA BELGILANSA ALMASHADI.** Buyruq
tanasi `{"q_id": "1", "q_n": "3"}` (satr yoki son). Uch qatlamda bir xil
qoida — eskisi yangisi bilan almashadi, eskisi yangisini HECH QACHON
bosmaydi:

| Qatlam | Qanday |
|---|---|
| mashina | `q003_id1_14-05-33.jpg`; yangi fayl (`.tmp` -> `os.replace`), keyin shu `q_id` ning eski fayllari (`local_archive.save_question_shot`, nom oxiridan regex bilan ajratiladi) |
| client navbatlari | shu savolning kodlanmagan / yuborilmagan kadri tashlanadi (trafik 1x) |
| server, fayl tizimi | `unique_screenshot_session_question`; qator O'RNIDA yangilanadi: yangi fayl -> qator -> eski fayl `on_commit`; eskiroq `captured_at` rad etiladi |
| server, S3 | yozilgandan keyin `tasks._drop_replaced_question_shots` (avval obyekt, keyin qator) |

KECHIKTIRISH (coalescing) YO'Q va qaytarmang: kechiktirilgan kadr olinganda
ekranda KEYINGI savol turgan bo'lishi mumkin va kadr noto'g'ri savol nomi
bilan saqlanardi. Spam chegarasi — lokal xizmatda (sekundiga 20, 429).
`q_id` belgilar to'plami `[A-Za-z0-9_.-]{1,64}` IKKI TOMONDA bir xil
(`local_service.QUESTION_ID_RE`, `ScreenshotUploadSerializer`) — u fayl
nomiga boradi. `q_n` siz `q_id` mumkin, `q_id` siz `q_n` — 400.
`check_frozen_frames` bitta savolga qayta bosishdagi bir xil kadrni
anomaliya hisoblamaydi (kamera tasmasi o'chiq bo'lsa ekran piksel-piksel
bir xil bo'lishi mumkin); turli savollarda bir xil kadr avvalgidek shubhali.

**LOKAL XIZMAT** (`client/services/local_service.py`, `MainWindow` da
dastur ochilishi bilan, `http.server` fon thread'ida — UI band bo'lsa
ham javob beradi):

| So'rov | Javob |
|---|---|
| `GET /api/device_info` | `{"machine_uuid", "ip", "mac", "number"}` — SHARTNOMA, kalitlarni o'zgartirmang |
| `POST /api/capture_screen` | 202 darhol (kadr fonda); 400 yaroqsiz tana; 409 `no_active_exam`; 429 sekundiga 20 dan ko'p |

* `machine_uuid` — SMBIOS 1-tur, HECH QACHON BO'SH EMAS va doim
  `normalize_machine_uuid` dan o'tgan (format, "to'ldirilmagan" qiymatlar
  ro'yxati, past entropiya). Manbalar zanjiri (`system_info.machine_uuid`):
  `smbios` (`GetSystemFirmwareTable`, ~1 ms, har qanday hisob/xizmat) ->
  `registry` (`HKLM\SYSTEM\HardwareConfig\LastConfig`) -> `cim`
  (PowerShell, ~0.3-1.5 s) -> `wmic` (Win11 24H2+ da yo'q) -> `derived`
  (UUIDv5: MAC -> MachineGuid -> kompyuter nomi, WARNING bilan). Hammasi
  `wmic csproduct` bilan bir xil satr (SMBIOS 2.6+ da `bytes_le`). Windows
  `MachineGuid` ASOSIY manba EMAS: u obraz bilan ko'chadi.
  `ip`/`mac` — handshake yuborgan juftlikning O'ZI (`AppState.machine`),
  `mac` kichik harf; `number` — SATR, login'gacha `null`.
* Faqat LOOPBACK (`127.0.0.1` va `::1` — Chromium `localhost` ni avval
  IPv6 ga uradi). `Host` loopback bo'lishi shart (DNS rebinding).
  `Origin` — imtihondagi `webview_policy.allowed_domains` (WebView
  allowlist'i bilan BIR XIL qoida) + `.env` `LOCAL_SERVICE_ALLOWED_ORIGINS`
  (`*` — faqat dev). CORS va Private Network Access preflight'iga javob
  beriladi.
* **WEBVIEW DOMEN FILTRI LOKAL PORTNI O'TKAZADI**
  (`DomainAllowlistInterceptor(local_port=)`) — aks holda platformaning
  `localhost` so'rovi WebView ichida jimgina bloklanardi. Faqat AYNAN o'sha
  port.
* Port band bo'lsa dastur to'xtamaydi — log'da ERROR, skrinshot olinmaydi.

**SKRINSHOT STANDARTI 1920 px / 80 SIFAT** (`Setting.screenshot_max_width`
/ `screenshot_quality`, `controls.0010_screenshot_quality`). Ilgari
960/65 edi va 1920 li ekranda test matni ~6 px harfga aylanib
O'QILMASDI. Xiralikning asosiy sababi KICHRAYTIRISH, sifat ikkinchi
darajali — o'lchangan (optimallashtirilgan progressiv JPEG, bu
mashinaning ekrani): 960/65 ~42 KB, 1600/85 ~128 KB, 1920/80 ~157 KB.
Client JPEG'ni `QImageWriter` bilan optimallashtirilgan Huffman +
progressiv yozadi (bir xil sifatda ~15% kichik). Migratsiya faqat AYNAN
eski standart juftligida (65, 960) turgan profillarni ko'chiradi —
ataylab o'zgartirilgan qiymatga tegilmaydi. Paneldagi trafik bahosi
(`Settings.jsx:shotKb`) ham shu o'lchovga moslangan: ilgari u kenglikni
umuman hisobga olmasdi.

### FaceID: solishtirish CLIENTDA, qaror SERVERDA

**Ikkala embedding ham clientda uchrashadi** va cosine o'sha yerda
hisoblanadi (`client/services/face_engine.py:compare`). Serverga
BALL keladi — 512 float emas. Sabab ko'lamda: 10 000 talaba × 6
tekshiruv/daqiqa = 1000 so'rov/sekund va ularning 99% i "hammasi
joyida" degan xabar edi.

Etalon uch bosqichda uch xil bo'ladi va bu ataylab:

| Bosqich | Etalon | Nima tekshiriladi |
|---|---|---|
| Kirish (FaceID sahifasi) | pasport rasmi (`image_base64`) | shu odam hujjatdagi odammi |
| Test davomida | kirishda TASDIQLANGAN kadr | odam almashtirilmadimi |
| Server | `ExamSession.reference_embedding` (= kirishdagi kadr) | — (solishtirmaydi) |

Test davomida pasport rasmi ISHLATILMAYDI: bir xil kamera va bir xil
yorug'likdagi ikki kadr ancha barqaror ball beradi, pasport bilan
solishtirish esa kirishdagi qiyinchilikni har 10 soniyada qaytadan
boshdan kechirardi. Etalon `AppState.face_reference` orqali FaceID
sahifasidan WebView sahifasiga o'tadi.

**BALL SHKALASI IKKI TOMONDA BIR XIL BO'LISHI SHART**:
`max(0, cos) × 100`, butun songa yaxlitlangan —
`client/services/face_engine.py:similarity_score` va
`apps/common/utils/vectors.py:similarity_score`. Ball
to'g'ridan-to'g'ri "necha foiz o'xshash" degan savolga javob beradi:
bir xil odamning hujjat rasmi va jonli kadri odatda 40–70, butunlay
boshqa odam 0–15.

MANFIY COSINE 0 GA SIQILADI va bu ma'lumot yo'qotmaydi: manfiy
o'xshashlik "boshqa odam" degan xulosadan nariga hech narsa
qo'shmaydi.

Shkala ikki marta o'zgargan va sabab har safar bir xil — ball QAROR
qabul qila boshlagani: `sqrt(cos)×100` (faqat ekran uchun edi) →
`(cos+1)/2×100` (butunlay boshqa odamga ~50 ball berardi va panelda
"yarmi o'xshash" bo'lib ko'rinardi; 70 ball aslida 0.40 cosine edi) →
hozirgisi. Oxirgi o'zgarishda mavjud chegaralar va yozuvlar
MIGRATSIYA bilan ko'chirilgan (`controls.0008_score_scale`,
`proctoring.0016_score_scale`, formula `yangi = eski × 2 − 100`),
aks holda o'zgarish jimgina qattiqlashtirish bo'lardi.

**CHEGARA IMTIHONGA BIRIKTIRILGAN SOZLAMADAN**:
`Setting.faceid_min_score_student` (kirish) va `faceid_min_score_exam`
(test davomida). Client uni `client/exam/config/?exam=` dan oladi
(`AppState.config.face`), server esa `get_client_config(session.exam)`
dan — bitta manba, ikkita o'quvchi. Zaxira qiymat
`FACE_MATCH_THRESHOLD` (0.42 cosine = 42 ball) faqat sozlama umuman
kelmagan holat uchun.

**Serverga nima yuboriladi:**

| Holat | Endpoint | Sessiya | Nima ketadi |
|---|---|---|---|
| Kirish: mos keldi | `client/face/verify/` | YARATILADI | embedding + ball + kadr |
| Kirish: mos kelmadi | `client/face/attempt/` | YO'Q | ball + kadr |
| Test: mos keldi | — | — | **hech nima** (heartbeat'da son) |
| Test: mos kelmadi | `client/face/periodic/` | mavjud | ball + kadr + `passed_since_last` |

**EKRANDAGI BALL QAROR QABUL QILINGACH MUZLAYDI** va u
serverdagi yozuv bilan AYNAN bir xil bo'lishi shart. Moslik
tasdiqlangach client solishtirishni umuman to'xtatadi: sessiyani
ochgan ball dalil bo'lib ketdi, ekranda esa undan keyin yugurib
turgan son "nega 47% da kiritdi?" degan javobsiz savol
tug'dirardi. Ko'rsatiladigan qiymat — `_verified_score`, ya'ni
`face/verify/` ga yuborilgani; `_best_score` (urinish davomidagi
eng yuqorisi) faqat MUVAFFAQIYATSIZ urinishda ishlatiladi, chunki
u yerda savol boshqa ("eng yaxshi holatda qancha chiqdi?") va
serverga ham aynan o'sha ketadi. Ilgari tasdiqdan keyin nishon
`_best_score` ga o'tardi va bitta hodisa uchun ekranda ikkita,
panelda uchinchi raqam bo'lib qolardi.

**HUJJAT TASDIG'IDA BITTA AMAL QOLDI.** Tasdiq kartasida sarlavha
ham, tushuntirish matni ham, "Rad etish" tugmasi ham yo'q —
«Davom etish» dan boshqa hech narsa. Matnlar ekranda allaqachon
javob berilgan savolni takrorlardi (chapda jonli kadr, o'ngda
hujjat rasmi, ustida xabar qatori) va yon ustunni 1366x768 ekranda
siqib, aynan solishtiriladigan rasmni kichraytirardi. Rad etish
esa bu qadamda ortiqcha: hujjat mos kelmasa operator "Qaytadan
urinish" ga qaytadi yoki proktor sessiyani paneldan to'xtatadi —
u yerda qaror ko'proq ma'lumot bilan qabul qilinadi.
`_on_reject` kodi olib tashlanmagan (`_ENROLLMENT_ENABLED`
bilan bir xil naqsh): endpoint joyida va tugmani qayta ulash
kifoya.

**KETMA-KET MUVAFFAQIYATSIZLIKLAR CHEGARASI — CHETLASHTIRISH EMAS,
XABAR.** `faceid_max_fail` ga yetilganda server sessiyani
TO'XTATMAYDI: u `high_suspicion_identity` KRITIK hodisasini yuboradi
(kritik hodisalar write-behind emas, ya'ni panelda o'sha zahoti
ko'rinadi) va client faqat holat qatorini yangilaydi. Qarorni
proktor qabul qiladi — u kadrni va dalil rasmlarini ko'rib turibdi,
client esa faqat ballni biladi. Yorug'lik o'zgarishi yoki ko'zoynak
tufayli ketma-ket uchta past ball butun imtihonni bekor qilishi
mumkin emas. Chetlashtirish yo'li yo'qolmagan — u proktorning ochiq
amali (`sessions/{id}/terminate/`).

Hodisa AYNAN CHEGARAGA yetilganda bir marta chiqadi: undan keyingi
har bir xato yana kritik hodisa bergani panelni bir xil xabar bilan
to'ldirardi (tarkibiy `face_mismatch` hodisalari esa avvalgidek
kelaveradi).

**ENROLLMENT REJIMI HOZIRCHA O'CHIRILGAN**
(`faceid_page._ENROLLMENT_ENABLED = False`). U shunday ishlardi:
platforma hujjat rasmini bermasa, solishtirish o'rniga sifatli kadr
yetarli deb hisoblanardi va javobgarlik butunlay operatorning hujjat
tekshiruviga o'tardi. Hozirgi o'rnatishda platforma rasmni har doim
beradi, ya'ni "rasm yo'q" amalda NOSOZLIK belgisi (javob buzilgan,
rasm bo'sh) — bunday holatda talabgorni jimgina kiritib yuborish
tekshiruvning o'zini bekor qilardi. Kod olib tashlanmagan: rasmsiz
platforma bilan integratsiya kelajakda paydo bo'lishi mumkin va
o'shanda bayroq `True` qilinadi (server tomoni ham joyida —
`verify_initial_face` ballsiz so'rovni qabul qiladi).

Muvaffaqiyatsiz kirish urinishi `challenge` ni **sarflamaydi**
(`state.peek_pending`): qayta urinish kutilgan xulq. Client uni BIR
MARTA yuboradi va operator "Qaytadan urinish" ni bosadi.

**TEKSHIRUVDAN OLDIN — OVAL VA SANOQ** (`Setting.faceid_guide_seconds`,
5 s; zaxira `.env` `FACE_GUIDE_SECONDS`).
Kamera ochilgach yuz na aniqlanadi, na solishtiriladi: ekranda yuz
shaklidagi oval, atrofi xiralashgan fon, oval bo'ylab to'ladigan
progress yoyi va qolgan soniyalar turadi (`CameraView.start_guide`).
Sanoq tugagach tekshiruv boshlanadi, oval esa xira uzuq chiziq bo'lib
QOLADI — talabgor sanoq tugashi bilan qimirlab ketmasligi kerak.

Sabab: kamera ochilishi bilan tekshiruv boshlansa, talabgor hali
o'tirib ulgurmagan yoki boshini burgan bo'ladi va urinish "Yaqinroq
keling", "Yuz topilmadi" yoki past ball bilan buzilgan holatda
boshlanardi. Oval so'zsiz tushuniladi: ko'z xiralashmagan joyga
o'zi boradi.

Qoidalar:

* **SANOQ BIRINCHI KADRDAN boshlanadi**, kamera ishga tushirilganda
  EMAS. Windows'da qurilma 2-4 soniyada ochiladi va sanoqning yarmi
  bo'sh ekranda o'tib ketardi.
* **ANIQLASH ISHCHIDA O'CHADI** (`CameraWorker(detect=False)`,
  `set_detection_enabled`), natija sahifada e'tiborsiz qoldirilmaydi:
  aks holda GPU baribir band bo'lardi. Sahifa ham sanoq paytida
  kelgan natijani RAD ETADI (`_on_face`) — qayta urinishda
  navbatga tushib qolgan eski natija bo'lishi mumkin.
* **HAR URINISHDA qaytadan** — "Qaytadan urinish" ham, kuzatuv rad
  etilib qaytish ham.
* **`take_camera` aniqlashni YOQIB uzatadi**: davriy FaceID unga
  tayanadi va o'chiq holda uzatilgan kamera test davomida jimgina
  "yuz yo'q" berardi.
* Oval o'lchami aniqlash chegarasiga mos (`_GUIDE_HEIGHT` 72%,
  nisbat 0.76, markaz 47%): ovalga joylashgan yuz `MIN_FACE_WIDTH_PX`
  dan ancha katta, ya'ni "Yaqinroq keling" olmaydi. 72% dan
  kattasi kerak emas: tepadagi ko'rsatma va pastdagi sanoq kadrdan
  chiqib ketardi.
* sanoq `0` — o'chadi, tekshiruv darhol. Oval
  baribir QOLADI (u holat ko'rsatkichi, pastga qarang).

**YUZ ATROFIDA TO'RTBURCHAK RAMKA YO'Q — HOLATNI OVAL KO'RSATADI.**
Sanoqdan keyin oval rangi holatni aytadi (yashil — mos, qizil — mos
emas yoki bir nechta odam, sariq — yaqinroq keling, xira uzuq
chiziq — yuz yo'q yoki natija eskirgan, `_DETECTION_TTL_MS`),
o'xshashlik foizi esa oval tepasidagi yozuvda. Ramka yuz bilan birga
sakrab yurar va talabgorning e'tiborini ovaldan o'ziga tortardi; oval
esa joyida turadi va "qayerda bo'lishim kerak" degan savolga javob
berishda davom etadi. `CameraView.set_detection` shuning uchun yuz
koordinatalarini umuman qabul qilmaydi.

**KADRDA KIM TALABGOR** — `camera_worker.select_candidate_face`.
Imtihon zalida kadrga talabgordan boshqa odamlar ham tushadi: orqa
qatordagi talabgorlar, o'tib ketayotgan operator, eshik oldidagi
navbat. Ilgari bunday kadr `multiple` bo'lib, solishtirish UMUMAN
bajarilmasdi va ikkala seriya ham uzilardi — ya'ni zal qanchalik
to'la bo'lsa, tasdiqdan o'tish shunchalik qiyin edi va operator
sababni ekrandan topa olmasdi.

Uch bosqich:

    uzoqdagilar tushadi   -> width < MIN_FACE_WIDTH_PX
    eng kattasi asosiy    -> kameraga eng yaqin odam
    dominantlik tekshiruvi-> ikkinchisi > 0.7 x asosiy => `multiple`

Uchinchi qadam MAJBURIY. Usiz tanlash xavfli bo'lardi: talabgor
orqaga suriladi, suflyor kameraga yaqinroq egiladi va tizim AYNAN
SUFLYORNI "talabgor" deb solishtirardi — natija esa oddiy "mos
kelmadi" bo'lib ko'rinardi. Nisbat (piksel emas) tanlangani ham
shundan: yuz kengligi masofaga teskari proporsional va nisbat
kameraning ko'rish burchagidan ham, rezolyutsiyasidan ham
mustaqil.

QOIDA AI QATLAMIDAGI BILAN BIR XIL — `identity/face_identity.py`
allaqachon eng katta yuzni tanlaydi ("uzoqdagi odam talabgorning
o'rnini egallamasligi kerak"). Ikki joyda ikki xil javob bo'lsa,
FaceID bir odamni, kuzatuv boshqasini "talabgor" deb hisoblardi.

Chetlatilgan yuzlar ekranda BELGILANMAYDI — yuz ramkalari umuman
olib tashlangan (yuqoridagi "HOLATNI OVAL KO'RSATADI"). Faqat
fondagi odamlarni belgilash ham to'g'ri bo'lmasdi: talabgorda ramka
yo'q, orqadagida bor — operator buni "tizim orqadagini tanladi" deb
o'qirdi. Tanlov natijasi (`select_candidate_face`: asosiy yuz va
chetlatilganlar) ishchi natijasida qoladi va testda tekshiriladi;
kadrda raqobatchi yuz bo'lsa buni "Kadrda bir nechta odam" yozuvi
va qizil oval aytadi.

Serverga yuboriladigan `faces_detected` bundan MUSTAQIL va u har
doim `1`: server savoli "qaror nechta yuz ustida qabul qilindi?"
va `verify_initial_face` boshqa qiymatni umuman qabul qilmaydi.

Urinish yopilishi uchun IKKALA shart ham kerak: `faceid_fail_streak`
ta ketma-ket mos kelmagan kadr VA `faceid_fail_min_seconds` soniya —
temporal qatlamdagi bilan bir xil qoida ("bitta kadr hech qachon
qaror emas"). Faqat kadr soniga tayanish tez kamerada 2-3 soniyada
xulosa chiqarardi va ko'zoynagini to'g'rilayotgan HAQIQIY talabgor
ham "kira olmadi" bo'lib qolardi. Yuz umuman ko'rinmay qolsa
(uzoq, bir nechta, yo'q) seriya UZILADI: u "mos kelmadi" emas,
"solishtirib bo'lmadi" degani.

Operatorga xabar IKKI XIL bo'ladi va farq hal qiluvchi: chegaradan
biroz past ball — sifat masalasi (yorug'lik, burchak, ko'zoynak),
chegaradan ANCHA past ball (`_FAR_MISS_GAP`) esa butunlay boshqa
savol — kadrdagi odam umuman shu talabgormi? Bitta umumiy matn
("kameraga to'g'ri qarang") ikkinchi holatda operatorni mavjud
bo'lmagan nosozlikni qidirishga majbur qilardi: kamerani
qanchalik to'g'rilamasin, boshqa odamning yuzi hujjatdagi rasmga
mos kelmaydi.

**`FaceVerificationLog.session` NULL bo'lishi mumkin** — aynan
"kira olmadi" holati uchun. Sessiya faqat moslik tasdiqlangach
ochiladi, ya'ni eng qimmatli yozuvni (kadrda boshqa odam turgan
bo'lishi mumkin) bog'laydigan sessiya yo'q. Shuning uchun qator
`pinfl`, `exam` va `zone` ni o'zida saqlaydi.

**IKKI HISOBLAGICH, IKKI EGASI** va ularni aralashtirmang:

* `face_checks` — **client** yozadi (heartbeat, `hset`). Server faqat
  xatolarni ko'radi, ya'ni jami sonni u bila olmaydi; sanashga
  urinsa, toza sessiyada "0 tekshiruv" chiqib, kuzatuv ishlamagandek
  ko'rinardi.
* `face_fails` — **server** oshiradi (`incr`). Chetlashtirish qarori
  shunga tayanadi va u atomik bo'lishi shart. "Ketma-ket" qoidasi
  `passed_since_last` orqali saqlanadi: oradagi muvaffaqiyatlar
  zanjirni uzadi.

**Jonli kadr DALIL sifatida saqlanadi** (`services/face_images.py`,
storage'ning `faceid/` shoxi — `evidence.py` bilan bir xil qoidalar:
nisbiy yo'l, avval fayl keyin qator, tur baytlardan aniqlanadi).
Muddat dalil kadriniki bilan bir xil; tozalash FAYLNI oladi,
QATORNI qoldiradi (`purge_expired_face_images`) — ball va vaqt
bayonnomaning qismi va rasm muddati tugagani uchun yo'qolmasligi
kerak. Panelda rasm `face-logs/{id}/file/` orqali va u
`evidence.view` ruxsatini talab qiladi: bu ham talabgorning yuzi.

**RASM TO'SIQ EMAS.** Kadr kelmasa yoki buzilgan bo'lsa tekshiruv
baribir davom etadi va qator rasmsiz yoziladi — aks holda buzilgan
JPEG butun imtihonni to'xtatardi.

**Server ballni QAYTA HISOBLAY OLMAYDI** va buni bilish kerak:
buning uchun rasmdan embedding olish, ya'ni serverda ML runtime
kerak — arxitektura esa ataylab boshqacha. Ya'ni ball clientdan
kelgan ishonchsiz qiymat va yagona haqiqiy shaxs kafolati
avvalgidek operatorning hujjat bo'yicha tasdig'i.

### AI proktorlik (kamera qatlami)

Kompyuter ko'ruvi **client tomonda** ishlaydi — Django request sikli
ichida emas. Sabab ko'lamda: 1000+ qurilma uchun markazlashgan GPU
klasteri ~$500k, mavjud arxitektura esa allaqachon shu qarorga
qurilgan. `Setting.faceid_audit_rate` maydoni qolgan, lekin
**ishlatilmaydi**: server auditi rasmdan embedding olishni talab
qiladi va bu yerda uni bajaradigan hech narsa yo'q.

**Kamera rollari ALMASHTIRILMAYDI** va ikkitadan ortiq rol yo'q:

| Rol | Nimaga qaraydi | Nimani hal qiladi |
|---|---|---|
| `primary` | talabgorning yuziga | shaxs, nigoh, bosh holati |
| `secondary` | stol / qo'l / xonaga | obyektlar, ikkinchi odam |

Rollarni almashtirish tahlilni **jimgina** buzadi: yuz modeli stol
ustidan yuz qidiradi, obyekt modeli yuz kadridan telefon — ikkalasi
ham "hech narsa topilmadi" deb xabar beradi. Shuning uchun har bir
hodisada `camera_role` yoziladi.

**ROLNI OPERATOR TANLAYDI, SERVER EMAS.** Ilgari bu `CameraAssignment`
jadvali edi: administrator har bir kompyuter uchun qaysi kamera qaysi
rolda ishlashini panelda yozardi. Model **butunlay olib tashlandi**
(`devices.0006_drop_camera_assignment`) va sabab amaliyotda ko'rindi —
500 mashinani qo'lda biriktirib chiqish kunlab vaqt oladi, ya'ni
jadval deyarli har doim bo'sh qolar va client baribir zaxira qoidaga
tushardi. Operator esa rolni bir bosishda tuzatadi: u ikkala kadrni
ekranda ko'rib turibdi, administrator jadvalda faqat nomni ko'rardi.

Serverda faqat **inventarizatsiya** qoladi (`Camera` — bino, manzil,
kredensial), rol esa client tomonda va u hech qayerga yozilmaydi.

Manba ikki xil:

* IP kamera — kadr RTSP orqali, kredensial `client/camera/stream/` dan;
* lokal veb-kamera — OS'dagi indeks bo'yicha ochiladi. Uning uchun
  `Camera` qatori **yaratilmaydi**: veb-kameraning IP'si ham, MAC'i ham
  yo'q va u markazlashgan inventarizatsiyaga tegishli emas — u
  kompyuterning qismi, tarmoq qurilmasi emas.

Bu ikkilik oltita kombinatsiyani (webcam+webcam, webcam+ip, ip+webcam,
ip+ip, faqat ip, faqat webcam) maxsus holatsiz qoplaydi.

**TAXMIN QOIDASI** (`proctoring/camera/roles.py`): birinchi kamera yuz
tekshiruvi, ikkinchisi obyekt aniqlash. Tartib: avval lokal
veb-kameralar, keyin IP kameralar — veb-kamera monitorga o'rnatilgan
va YUZGA qaraydi, IP kamera esa (`Camera` izohi: "Zonani kuzatadi")
XONANI ko'radi. Faqat IP kamera bo'lsa u yuz rolini oladi. Virtual
qurilma (OBS, ManyCam) ro'yxatning OXIRIGA suriladi: uni yuz roliga
qo'yish shaxs nazoratini bekor qilardi — model yozuvdagi yuzni ko'rib
har safar "mos keldi" derdi. Bu taqiq emas, taqiq siyosatda
(`allow_virtual_camera`) va uni server majburlaydi.

Taxmin operatordan YASHIRILMAYDI va u TUZATSA BO'LADI: panel rollar
taxmin qilinganini ochiq yozadi, har bir kadr ustida esa vazifani
tanlash turadi (`ui/widgets/camera_panel.py:RoleSegmentedControl`
→ `roles.reassign`). Sabab oddiy: OS'dagi indeks jismoniy joylashuvni
bilmaydi — monitorga o'rnatilgan kamera 1-indeksda, stolga qaragan USB
kamera esa 0-indeksda bo'lishi mumkin. O'shanda taxmin teskari chiqadi
va tahlil JIMGINA buziladi.

Tanlov QOIDALARI:

* **kamida ikkita ishlaydigan kamerada** — bittasida tanlaydigan
  narsa yo'q;
* **tanlov qurilmaga bog'lanadi** (`ResolvedCamera.key`), rolga emas.
  Shu tufayli "Yangilash" dan keyin ham saqlanadi: qurilmalar
  qaytadan aniqlanadi, rollar noldan taqsimlanadi, tanlov esa
  qoladi;
* **kartalar QURILMA tartibida chiziladi**, rol tartibida emas
  (`camera_panel._by_device`). Rol bo'yicha tartiblansa, operator
  o'ng kartada "Yuz tekshiruvi" ni tanlashi bilan o'sha karta CHAPGA
  sakrardi va ekranda bu "tanlov teskari ishladi, nomlar almashdi"
  bo'lib ko'rinardi;
* **rol almashtirilganda oqim va tekshiruv natijasi BEKOR QILINADI.**
  Oqimlar rol bo'yicha ochilgan va eski natija endi boshqa kameraga
  tegishli — uni ekranda qoldirish "birlamchi kamera tekshiruvdan
  o'tdi" degan yolg'on xabar bo'lardi.

**HAMMA QURILMA RO'YXATDA QOLADI — ikkitadan ortig'i ZAXIRA.**
Ilgari taqsimot faqat birinchi ikkita qurilmani olardi
(`candidates[:2]`) va ikkita veb-kamerali mashinada binodagi IP
kamera ro'yxatdan TUSHIB QOLARDI — operator uni ko'rmas, ishga
tushirmas va unga vazifa bera olmasdi. Endi uchinchi va keyingilari
rolsiz (`role == ""`, vazifa `spare` — «Ishlatilmaydi»):

| | Rolli (`primary`/`secondary`) | Zaxira |
|---|---|---|
| Tekshiruv sahifasida ko'rinadi | ha | ha |
| Oldindan ko'rish oqimi | ha (slot = rol) | ha (slot = `spare:<kalit>`) |
| Server tekshiruvi (`camera/check/`) | ha | yo'q |
| Imtihon kuzatuvi (`as_slots`) | ha | yo'q |
| Siyosat tekshiruvi (virtual, sifat) | ha (`layout.in_use`) | yo'q |

Ko'rish uchun `layout.preview_slots()`, kuzatuv uchun
`layout.as_slots()` — ular ATAYLAB alohida: zaxiradagi OBS virtual
kamerasi imtihonni to'smasligi, IP kamera esa operator ko'rib turib
vazifa berishi uchun ochilishi kerak.

Har kartada UCH segment — Yuz tekshiruvi / Obyekt aniqlash /
Ishlatilmaydi (`roles.assign`). ALMASHTIRISH QOIDASI: vazifani olgan
qurilma o'zining eski vazifasini oldingi egasiga beradi. YUZ ROLI
BO'SH QOLMAYDI: yuz kamerasi "Ishlatilmaydi" qilinsa, o'rniga avval
ZAXIRADAGI kamera (qurilma tartibida), u bo'lmasa obyekt kamerasi
ko'tariladi — teskarisi xonani ko'rayotgan IP kamerani yuzga o'tkazib,
obyekt aniqlashni bo'sh qoldirardi. Yolg'iz kamerani o'chirib bo'lmaydi.
Tanlov `{kalit: vazifa}` bo'lib saqlanadi va "Yangilash" dan keyin
qayta qo'llanadi (`roles.apply_choices`).

Zaxiradagi IP kamera oqimi uchun kredensial `role="preview"` bilan
so'raladi (`client/camera/stream/` — rol faqat audit uchun va server
faqat `primary`/`secondary`/`preview` ni qabul qiladi).

**Binodagi har bir IP kamera ishlatsa bo'ladi.** Biriktirish
bo'lmagani uchun doira endi BINO: server `camera/config/` da shu
binodagi faol kameralar ro'yxatini beradi va `camera/stream/`
ularning har biri uchun kredensial beradi (pastdagi bo'limga qarang).

**`Setting` va `ProctoringPolicy` bir-birini takrorlamaydi.** Obyekt
aniqlashning "yoqilganmi", "qanday ishonch bilan", "qaysi klasslar"
savollari `Setting` da qoladi; siyosat faqat qo'shimchasini beradi
(necha kadr, qancha davomiylik, birlashtirish oynasi, ball pasayishi).
Client'ga esa **bitta** qiymat ketadi — `modules.objects` ikkalasining
mantiqiy VA'si (`controls.services._serialize_proctoring`). Ikki
bayroqni clientga berish "qaysi biri ustun?" savolini u yerda ikkinchi
marta hal qilishga majbur qilardi.

**YOLO IKKI KALITGA BOG'LIQ va panel buni PROFIL SAHIFASIDA
ko'rsatadi.** Obyekt aniqlash = `Setting.is_enable_detect` VA
`ProctoringPolicy.is_enabled` VA `enable_objects`. Siyosat ALOHIDA
bo'limda («AI kuzatuv → Kuzatuv siyosati») va u profil bilan birga
avtomatik YARATILMAYDI — siyosatsiz profil `_default_proctoring()`
ni oladi, ya'ni `enabled=False`. Amalda shunday bo'lgan:
administrator profilda YOLO ni yoqdi, siyosat yaratilmadi va client
"AI kuzatuv o'chirilgan" deb ishlayverdi — panelda buni aytadigan
hech narsa yo'q edi. Endi `SettingSerializer.ai_proctoring`
(`policy_id`, `enabled`, `objects`, `evidence` — client formulasi
bilan AYNAN bir xil) YOLO kaliti yonida ogohlantirish va «AI
kuzatuvni yoqish» tugmasini beradi (`Settings.jsx:AiProctoringNotice`,
ruxsat `controls.proctoring_manage`). Tugma siyosatni standart
qiymatlar bilan yaratadi yoki mavjudini yoqadi.

**YOLO MODELI FAYLI ALOHIDA SHART**: `client/models/yolo/yolov8{n,s,m}.onnx`
(`client/models/README.md`). Fayl yo'q bo'lsa modul jimgina o'chadi
va `proctoring_degraded` hodisasi chiqadi — siyosatdagi `objects=True`
o'zi hech narsa aniqlamaydi. Ultralytics YOLOv8 AGPL-3.0 litsenziyasida.
Eksport `dynamic=True` bilan bo'lishi SHART: kirish o'lchami profilga
qarab 640/512/416/320.

**"ODAM" (COCO 0) ODDIY OBYEKT EMAS** (`behavior_analyzer._observe_objects`).
Talabgorning o'zi har kadrda odam va uni `object_detected` ga
aylantirish sozlamada "Odam" tanlangan har imtihonda uzluksiz soxta
hodisa, klip va xavf balli berardi. Talabgor — O'RINDIQDAGI odam
(pastdagi "O'rindiq kalibrlashi"); boshqa odam faqat YUZASI
talabgornikining kamida chorak qismi bo'lsa
(`_SECOND_PERSON_AREA_RATIO`) `second_person` beradi — orqa qatordagi
odamlar kichik ko'rinadi va hisobga olinmaydi. Qaror KODGA tayanadi
(`Track.code`), nomga emas: nom serverdagi sozlamada ("Odam")
o'zgarishi mumkin.

**O'RINDIQ KALIBRLASHI** (`behavior/seat_anchor.py`). Obyekt kamerasi
BITTA ish joyi tepasida qat'iy turadi (o'rnatish qoidasi). Ilgari
talabgor "eng baland ramka" edi, tepadan qaragan kamerada esa ramka
o'lchami odamning bo'yini emas, KAMERAGACHA MASOFANI bildiradi: stol
yonida tik turgan odam kattaroq chiqar, o'tirgan talabgorning o'zi esa
«Begona odam» bo'lib belgilanardi (dalil belgilari buni ko'rsatib
qo'ydi). Kadrdagi o'rin (markaz) ham yetmaydi — kamera stolga qiya
qaraydi va talabgor kadr chetida o'tirishi mumkin.

Nigoh kalibrlashi bilan bir xil naqsh: sessiya boshidagi
`CALIBRATION_SECONDS` (15 s) ichida kadrda UZLUKSIZ bor (>=80%) va
deyarli QIMIRLAMAYDIGAN (markaz tarqoqligi <= 0.04) odam — talabgor;
uning ramka markazi "o'rindiq" bo'lib sessiyaga muzlatiladi. Imtihon
boshida yonida turgan operator bir necha soniyada ketadi yoki
harakatlanadi va nomzod bo'lmaydi. Keyin talabgor — avval o'sha iz,
iz uzilsa o'rindiqqa eng yaqin odam (radius 0.22).

* **Noaniq kalibrlash RAD ETILADI** (ikki barqaror odam, ball farqi
  < 1.5x) va oyna qaytadan boshlanadi; shu vaqt ichida zaxira —
  markazga yaqinlik x yuza. Noto'g'ri o'rindiq butun imtihonga
  noto'g'ri talabgorni yopishtirardi.
* **Kalibrlash sukuti**: dastlabki 15 s da `second_person` chiqmaydi
  (operator yonida bo'lishi kutilgan). Sukut CHEGARALI — kalibrlash
  noaniq qolsa ham undan keyin zaxira qoida bilan ishlaydi.
* **Talabgor o'rindiqda bo'lmasa** `second_person` chiqmaydi: "joyida
  yo'q" ni asosiy kamera (`no_face`) aytadi.
* **Tayanch — ramka markazi**, pose nuqtasi emas: izlar har kadrda
  ramka beradi, pose esa boshqa chastotada. Kalibrlash va keyingi
  kadrlar BIR XIL nuqta turini ishlatishi shart.
* **`hand_below_desk` ham o'rindiq bilan** tanlangan pozani oladi —
  ilgari `poses[0]` (birinchi aniqlangan odam) edi va yonidagi odamning
  qo'llari talabgorga yozilishi mumkin edi.
* O'rindiq kamera ROLI bo'yicha va HAR SESSIYADA qaytadan (`reset`).

**ZAL KAMERASI UCHUN BU QOIDA YAROQSIZ** (kadrda ko'p o'tirgan odam —
hammasi "barqaror"). Kamerada "bitta ish joyi / zal" bayrog'i ataylab
QO'SHILMADI: u almashtiradigan to'g'ri qoida hali yo'q, qoidasiz bayroq
esa hech narsani hal qilmaydi. Zal kamerasi kerak bo'lsa — adminkada
ish joyi zonalarini chizish (kompyuter raqami bilan).

**`ExamSession.proctoring_state` `status` dan MUSTAQIL.** Birinchisi
"kuzatuv qanday ishlayapti", ikkinchisi "imtihon qanday ketyapti".
Ularni birlashtirish "kamera uzildi = imtihon tugadi" degan noto'g'ri
xulosaga olib kelardi — holbuki kamera uzilishi ko'pincha 15
soniyalik USB nosozligi. `degraded` holati imtihonni **to'xtatmaydi**;
qaror `ProctoringPolicy.camera_lost_action` da.

### Tashqi test platformasi — backend KO'PRIK

**Client platformaga hech qachon o'zi murojaat qilmaydi.** JSHSHIR
kiritilganda so'rovni backend yuboradi
(`integrations/exam_site.py`):

```
GET  {Exam.site_url}?imie=<jshshir>
     {Exam.site_header_encrypted dagi sarlavha}
```

Javob konverti:

```json
{"status": 1, "message": "Success",
 "data": {"id": …, "abitur_id": …, "imie": …, "is_finished": 1,
          "image_base64": "data:image/jpeg;base64,…",
          "lname": "TO‘RAYEV", "fname": "YUSUF", "mname": "JUMMA O‘G‘LI",
          "duration_time": 180,
          "test_link": "https://test.uz/login?token=…",
          "message": "Testga ruxsat!", "status": true}}
```

Sabab ikkita va ikkalasi ham qat'iy: kredensial serverda qoladi
(500 mashinaga tarqalgan token bekor ham qilinmaydi, kuzatilmaydi
ham), va javob sxemasi BITTA joyda talqin qilinadi — client'da
talqin qilinsa, sxema o'zgarganda barcha mashinalarni yangilash
kerak bo'lardi.

**Uchta javob — uchta xil holat** va ular ATAYLAB ajratilgan,
chunki operator har birida boshqa ish qiladi:

| Javob | Kod | Operator nima qiladi |
|---|---|---|
| `status != 1` | `candidate_not_found` | JSHSHIR ni tekshiradi |
| `data.status` false | `candidate_not_eligible` | platforma matnini o'qiydi |
| `test_link` bo'sh | `candidate_not_eligible` | administratorga murojaat |

**`is_finished` TO'SIQ EMAS.** Platformaning o'z namunasida u `1`
bo'lgani holda `status: true` va "Testga ruxsat!" qaytadi — ya'ni
u "test tugagan" degani emas. Uni `external_status="finished"` deb
yozish `_CLOSED_PLATFORM_STATUSES` orqali imtihonni jimgina
to'sardi. Qiymat `ExamSession.meta` da dalil sifatida saqlanadi.

**`test_link` JSHSHIR tekshiruvida client'ga BERILMAYDI.** U
sessiyaga shifrlab yoziladi (`external_test_link_enc`) va faqat
`exam/access/` da, shaxs tasdiqlangandan keyin qaytariladi.
Aks holda havolani nusxalab, FaceID va operator tasdig'ini
butunlay chetlab o'tish mumkin bo'lardi.

**WebView allowlist'i `test_link` domenidan olinadi**, `site_url`
dan emas: `site_url` endi API manzili (`api.test.uz`), test esa
boshqa domenda ochilishi mumkin (`test.uz`). Eski manbani
qoldirish butun sahifani bloklardi.

`image_base64` FaceID etaloniga aylanadi (`data:` prefiksi olib
tashlanadi — client toza base64 kutadi).

**F.I.Sh. VA TEST VAQTI — KEYIN QO'SHILGAN MAYDONLAR.** Javob
sxemasi ilgari faqat identifikatorlardan iborat edi, shuning uchun
ikkalasi ham YO'Q BO'LSA HAM oqim to'liq ishlaydi: ism kelmasa
client niqoblangan JSHSHIR ko'rsatadi (`Candidate.display_name`),
vaqt kelmasa maydon umuman chizilmaydi ("0 daqiqa" yozuvi yolg'on
bo'lardi). Aynan shu sababdan ularning hech biri tekshiruvni
to'sa olmaydi: buzilgan `duration_time` istisno emas, 0.

Ism `lname`/`fname`/`mname` dan yig'iladi (`_NAME_ALIASES`, tartib
hujjatdagidek — familiya, ism, otasining ismi); zaxira nomlar
(`fio`, `surname`, …) qoldirilgan, chunki o'rnatishlar bir xil
emas.

`duration_time` DAQIQADA keladi va shu birlikda saqlanadi
(`duration_minutes`). Formatlash — CLIENT tomonda
(`Candidate.duration_label`: "3 soat", "1 soat 30 daqiqa"): serverda
matn yasash uni tarjima qilib bo'lmaydigan holga keltirardi, ikki
sahifada ikki xil yozish esa ("180 daqiqa" va "3 soat") bir xil
qiymatni ikki xil ko'rsatardi. Qiymat sessiyaga ham MUZLATILADI
(`ExamSession.meta.platform.duration_minutes`) — platforma uni
keyin o'zgartirsa ham, bayonnomada talabgorga aynan qancha vaqt
berilgani qolishi kerak.

Ikkalasi ham IKKI SAHIFADA ko'rinadi — talabgor kartasida va
FaceID sahifasida. Sabab: savol ("qancha vaqtim bor?") aynan
kamera oldida turganda beriladi va javob uchun oldingi sahifaga
qaytish kerak bo'lardi, u yerda esa keyingi talabgorning
ma'lumoti ochilardi.

`integrations/exam_platform.py` (markazlashgan ntest API'si)
saqlanib qoldi, lekin unda faqat natijani qaytarish
(`report_result`) va salomatlik (`platform_health`) qoladi —
talabgorni tekshirish butunlay `exam_site.py` ga o'tdi.

### Kompyuter raqami va inventar kodi — IKKI BOSHQA SAVOL

`Computer.number` xonadagi TARTIB RAQAMI (stolga yozilgan),
`inventory_code` esa buxgalteriya kodi. Ikkalasi ham kerak va
ularni birlashtirish mumkin emas:

| | `number` | `inventory_code` |
|---|---|---|
| Nimani belgilaydi | XONADAGI O'RIN | MASHINANING O'ZI |
| Mashina almashtirilsa | **qoladi** | o'zgaradi |
| Kim ishlatadi | operator, talabgor | buxgalteriya, administrator |
| Qayerda yozilgan | stolda | stikerning orqasida |
| Unikal | **bino ichida** | tizim bo'ylab |

Amalda operator "12-kompyuterga o'ting" deydi va inventar kodini
hech qachon aytmaydi. Shuning uchun raqam ro'yxatlarda BIRINCHI
ustun, saralash ham u bo'yicha (`ordering = ["zone", "number",
"inventory_code"]`; raqamsizlar oxirida qoladi).

**RAQAM IXTIYORIY.** Hamma markazda ham mashinalar raqamlanmagan
va majburiy qilish mavjud yozuvlarni migratsiyada to'ldirishga
majbur qilardi — to'g'ri javobni esa faqat o'sha markaz biladi.
`0` esa QABUL QILINMAYDI: "0-kompyuter" degan o'rin yo'q va bo'sh
maydon o'rniga tushgan nol jimgina yolg'on raqam yaratardi.

**UNIKALLIK BINO ICHIDA** (`unique_computer_zone_number`, shartli:
`deleted_at IS NULL AND number IS NOT NULL`). "12-kompyuter" har
binoda bor — tizim bo'ylab unikal qilish ikkinchi binoni
13-raqamdan boshlashga majbur qilardi. Hisobdan chiqarilgan
mashina raqamni band qilmaydi: stol o'z joyida qoladi va yangi
mashina o'sha raqamni oladi.

**EKRANDAGI NOM BITTA JOYDA YASALADI** — `Computer.label`
("№12 · INV-001"). Server uni serializerda beradi, frontend
`utils/labels.js:computerLabel` orqali (ro'yxat ustunlarida raqam
alohida maydon: matn ichiga qo'shilsa saralash "10, 11, 2"
tartibida chiqardi), client esa handshake'dagi tayyor qiymatni
oladi. Uch joyda alohida yasalsa, bittasi raqamsiz mashinada
"№None" chiqarardi.

**CLIENT UNI SARLAVHADA YIRIK NISHONDA KO'RSATADI**
(`ui/widgets/brand.py:SeatBadge`, o'ng tomonda — imtihon tanlash,
talabgor va FaceID sahifalarida). Ilgari raqam `ContextChips` ning
bitta katagi edi — MAC va IP bilan bir xil o'lchamda, ya'ni texnik
ma'lumot orasida yo'qolardi; bron tekshiruvi esa operatorga "talabgor
№12 ga biriktirilgan" deydi va u o'z raqamini bir qarashda ko'rishi
kerak. Kataklarda endi `pc` YO'Q (`WorkstationHeader` —
`fields=("region", "zone", "mac", "ip")`).

Nishonda FAQAT RAQAM (raqamsiz mashinada inventar kodi), to'liq nom
tooltip'da; kompyuter biriktirilmagan bo'lsa nishon yashiriladi.
Chap yuqori burchakda — LOGOTIP (`BrandLogo`, 44 px). Ikkalasi ham
sarlavha vidjetida (`header._brand_block`, `set_seat`), sahifalarda
emas. Imtihon (test platformasi) sahifasida sarlavha yo'q.

**LOGOTIP — FAYL** (`client/resources/images/logo.png`): muassasa
belgisini almashtirish kod o'zgarishi bo'lmasligi kerak. PyInstaller
paketida `--add-data "resources;resources"` SHART. Fayl topilmasa
dastur to'xtamaydi — vidjet o'zini yashiradi. Login va tarmoq
tekshiruvi sahifalarida u kartaning USTIDA, OQ rangda (to'q yashil
fonda asl rangi ko'rinmasdi) va balandligi oynaga moslashadi
(`BrandBackdrop.make_logo`: balandlikning 9.5%, 56–112 px).

**YANGI KATAK IKKI JOYGA QO'SHILADI**: `ContextChips.FIELDS`
(chiziladigan kataklar) va `set_values` IMZOSI (qiymatlar).
Imzo `*` bilan qat'iy, ya'ni faqat `FIELDS` ga qo'shish
`TypeError: unexpected keyword argument` beradi — va u aynan
login'dan keyin, imtihon tanlash sahifasi ochilganda chiqadi.
Ko'rsatilmaydigan katakning qiymati esa JIMGINA tashlanadi
(talabgor va FaceID sahifalarida `pc` yo'q), shuning uchun
chaqiruvchi qaysi kataklar yoqilganini bilishi shart emas.

Mashina tekshiruvi matnlari ham raqamli nomni ishlatadi
(`verify_machine`): "«№12 · PC-0012» kompyuteri hisobdan
chiqarilgan" — operator uni stolda ko'rib turibdi, inventar kodi
esa unga hech narsa aytmasdi.

**EXCEL IMPORT** (`devices/computer_import.py`, `computers/import/` +
`import-template/`, panel `ComputerImportDialog`). Ustunlar: `dtm_id`,
`zone_number` (TASHQI raqamlar, ichki ID emas), `machine_uuid` (MAJBURIY),
`mac_address` (ixtiyoriy), `number`, `inventory_code` (ixtiyoriy — bo'sh
bo'lsa `AUTO-<UUID hex>`). Sarlavha va qiymatdagi qavs ichi tashlanadi.
HAMMASI YOKI HECH NARSA: bitta xato = hech narsa yozilmaydi, panel avval
`dry_run` qiladi. Ro'yxatdagi UUID — xato emas, O'TKAZIB YUBORILADI
(tuzatilgan faylni qayta yuklash odatiy). YAGONA TAHRIR — UUID'siz ESKI
yozuv qatordagi MAC va O'SHA bino bo'yicha topilsa, unga FAQAT
`machine_uuid` yoziladi (`to_bind`/`bound`, raqam va kod o'zgarmaydi):
eski faylga bitta ustun qo'shib qayta yuklash binoni UUID'ga o'tkazadi.
Viloyat admini faqat o'z viloyatiga. `Computer.ip_address` shu sababli
IXTIYORIY (`devices.0010`): Excel'da IP yo'q, NULL esa
`unique_computer_zone_ip` ga tushmaydi (ilgari "0.0.0.0" binoda bittadan
ortiq bo'lolmasdi).

### Kompyuter broni (`exams.ComputerBooking`)

**"TEST SESSIYASI" — `ExamSchedule`** (imtihon + vaqt + bino/`NULL`
= barcha binolar), `ExamSession` EMAS: talabgor sessiyasi FaceID'dan
keyin tug'iladi, bron esa undan oldin tuziladi. Bitta qator = shu
sessiyadagi bitta kompyuter:

| Maydon | Ma'nosi |
|---|---|
| `schedule`, `computer` | joy (juftlik unikal) |
| `is_active` | shu sessiyada ISHCHI (buzilgan = `False`); `Computer.is_active` (hisobdan chiqarilgan) dan BOSHQA |
| `is_booked` + `pinfl` | biriktirilgan talabgor (tashqi platformada `imie`); ikkalasi BAZADA bog'langan (`CheckConstraint`) |

Bitta JSHSHIR bitta sessiyada BITTA joyda — cheklov bazada
(`unique_booking_schedule_pinfl`), chunki tashqi tizim so'rovlarni
parallel yuboradi.

**MANTIQ BITTA JOYDA** — `apps/exams/bookings.py`: panel, tashqi API,
Django admin va client tekshiruvi shu funksiyalarni chaqiradi.

* **Joylar YIG'ILADI** (`generate_seats`, `generate/`): sessiya
  doirasidagi har ishchi kompyuter uchun bo'sh qator. Takroriy
  chaqiruv xavfsiz (`ignore_conflicts`). Viloyat administratori
  umumiy sessiyada faqat o'z viloyatini yig'adi.
* **Biriktirish PATCH EMAS** — `assign/` (`schedule`, `pinfl`,
  ixtiyoriy `computer`/`zone`). `computer` yo'q bo'lsa — eng kichik
  raqamli bo'sh ishchi joy (`select_for_update(skip_locked)`,
  parallel so'rovlar bir joyni olmaydi); talabgorning joyi bo'lsa
  o'sha qaytadi (idempotent). `computer` bor va talabgorning boshqa
  joyi bo'lsa — KO'CHIRISH (eskisi bo'shatiladi, auditda `move`).
  `PATCH` faqat `is_active` ni yozadi.
* `bulk-assign/` — tashqi tizim uchun, HAR QATOR alohida tranzaksiya
  va alohida natija (`ok`/`code`/`message`), audit bitta yozuv.
* `release/`, `stats/` (`total`/`booked`/`free`/`broken`/
  `broken_booked`/`finished`). Band joyni o'chirib bo'lmaydi.

**IMTIHONDAGI TALABGORNING JOYI QO'LDA BO'SHATILMAYDI VA KO'CHIRILMAYDI**
(`bookings.release` / `assign` → 409 `seat_in_use`). "Imtihonda" =
shu `schedule` + JSHSHIR bo'yicha YAKUNLANMAGAN sessiya bor
(`bookings.active_session`: `TERMINAL_STATUSES` dan tashqari hammasi,
`ready` ham — kuzatuv rad etilib FaceID sahifasida kutayotgan talabgor).
Qoida servisda, view'da emas: panel, Django admin (xabar bilan), tashqi
`bulk-assign/` (qator `seat_in_use`) bitta funksiyani chaqiradi. Panel
tugmalarni o'chiradi (`SeatMap.seatInExam`, server sharti bilan bir xil),
himoya esa serverda. Imtihon davomida joy faqat SESSIYA orqali bo'shaydi:

| Yakun | Joy | Sabab |
|---|---|---|
| «Yakunlash» (client, `completed`) | **bo'shaydi** | talabgor testni topshirdi |
| chetlashtirish (PANEL, administrator) | **bo'shaydi** | administrator qarori |
| dasturdan chiqish (Ctrl+Q) | band | talabgor topshirmagan |
| `expired` (client o'ldi, tok) | band | talabgor O'SHA stolga qaytadi |
| "shaxs rad etildi" (client) | band | administrator qarori emas |

Bo'shatish yakun bilan BITTA TRANZAKSIYADA (`session._release_seat` →
`bookings.release_after_session`): `finish_session(completed=True)` va
`terminate_session(release_seat=True)` — ikkinchisini faqat panelning
`sessions/{id}/terminate/` beradi. Alohida qadam yiqilsa qayta urinib
bo'lmasdi (token yakunda bekor bo'ladi). Joy talabgor bo'yicha topiladi,
`meta.seat_release` ga (`by`: `finish`/`terminate`) va auditga yoziladi;
client javobida `seat_released` + `seat` ("«№12» bo'shatildi").

`completed` standarti `false` — eski client nusxalari joyni
bo'shatmaydi; ularning yakunidan keyin sessiya yopiq, ya'ni panelda
qo'lda bo'shatish ishlaydi.

**`finished_count` / `last_finished_at` — bo'shatilgan joyning izi**
(topshirgan va chetlashtirilgan — ikkalasi) va u `bookings_enforced`
ga KIRADI. Faqat `is_booked` ga qaralsa, oxirgi talabgor yakunlagach
sessiyada band joy qolmas va tekshiruv JIMGINA o'chib, yakunlagan yoki
chetlashtirilgan talabgor ham, bronsiz begona ham qayta kirardi.
* Ruxsatlar ALOHIDA: `bookings.view` / `bookings.manage`
  (`exams.0007_booking_permissions` mavjud rollarga beradi — seed'ni
  qayta ishga tushirish qo'lda o'zgartirilgan rollarni buzardi).
  Tashqi tizim oddiy xodim kabi JWT bilan kiradi.

**JSHSHIR TEKSHIRUVIDA** (`lookup_candidate` →
`resolve_candidate_seat`) — tashqi platformaga so'rovdan OLDIN.
BRON SESSIYA DARAJASIDA YOQILADI: sessiyada birorta ham talabgor
biriktirilmagan bo'lsa tekshiruv o'chiq (mavjud o'rnatishlar
to'xtamaydi); `REQUIRE_COMPUTER_BOOKING=true` uni majburiy qiladi.

| Kod | Holat |
|---|---|
| `seat_not_booked` (403) | talabgorning joyi yo'q |
| `seat_out_of_service` (409) | joyi buzilgan — administrator ko'chiradi |
| `wrong_computer` (409) | boshqa stolda; `details.seat` — qayerga borish, `details.current` — shu mashina |
| `device_binding_mismatch` (409) | stol TO'G'RI (UUID mos), lekin qurilma boshqa kompyuterga biriktirilgan |

"Shu mashina" — client yuborgan `machine_uuid` (jismoniy stol,
`bookings._physical_computer`); eski client'da MAC, ikkalasi ham
topilmasa qurilmaning `Computer` biriktiruvi. UUID berilgan-u bazada
topilmasa MAC faqat UUID'SIZ yozuvlarda qidiriladi (UUID'i boshqa
mashina MAC bo'yicha "shu stol" bo'lib qolmasin). FAQAT BINO ICHIDA
(qurilmaning binosi, qurilma yo'q bo'lsa talabgor joyiniki) —
`verify_machine` bilan bir xil savol.

**CHALLENGE QURILMAGA BOG'LANGAN** (`session._require_pending_device`).
Bron qarori JSHSHIR tekshiruvini yuborgan qurilma uchun chiqariladi;
`face/verify/` va `face/attempt/` boshqa qurilmadan kelsa
`SessionNotFound` (muddati tugagan bilan BIR XIL javob). Ilgari
`device_id` pending'ga yozilar, lekin solishtirilmasdi — bron faqat
"JSHSHIR to'g'ri stolda kiritildi" ni isbotlardi. Begona so'rov
challenge'ni SARFLAMAYDI (avval `peek`, keyin `consume`). Oxirgi qatordagi holat
`wrong_computer` DEB KO'RSATILMAYDI: operator talabgorni o'zi turgan
stolga yuborib qo'yardi. Muvaffaqiyatda javobda `seat` keladi va u
`ExamSession.meta.seat` ga MUZLATILADI.

**XATO TAFSILOTI TUZILGAN** — `DomainError(extra=...)` →
`error.details`. Client raqamni matndan ajratmaydi:
`ApiWorker.failed_details` (uchinchi signal, `failed` imzosi
o'zgarmadi) → `ui/widgets/seat_notice.py:SeatNotice` — yirik "bu
kompyuter → borishi kerak" plitalari. Muvaffaqiyatda natija kartasida
«JOY TASDIQLANDI №12» paneli.

Panel: `/computer-bookings` (`pages/ComputerBookings.jsx`) — seans
tanlash (standart: hozir ochiq yoki eng yaqin), MD3 statistika
plitalari, holat filtri, biriktirish/ko'chirish dialogi (bo'sh joylar
BRON endpointidan — `devices.view` shart emas).

**STANDART KO'RINISH — JOYLAR XARITASI** (poyezd bronlash naqshi,
`components/bookings/SeatMap.jsx`; `?view=list` — jadval): chapda
IKKI BOSQICH — viloyatlar (`region_dtm_id` tartibida, statistika
binolardan brauzerda yig'iladi — `groupRegions`, qo'shimcha so'rovsiz),
keyin tanlangan viloyatning binolari (`?region=&zone=` URL'da). Bino
AVTOMATIK tanlanmaydi (yagona tanlovdan tashqari) — o'ngda
`PickPrompt`. O'ngda zal —
o'rindiqlar raqam tartibida, o'rtada yo'lak, tepada «Oldi · proktor
stoli». Holat rang + ikonka + shakl bilan (buzilgan — qiya chiziq).
Ustunlar soni kartaning haqiqiy kengligidan (`ResizeObserver`), ekran
nuqtasidan emas. Ko'chirish ikki bosqichli (panel → bo'sh o'rindiq).
**500 O'RINDIQ TEZ** (`SeatGrid`): o'rindiq — oddiy `<button>` +
data-atributlar, butun stil BITTA blokda (`seatStyles`), `memo` bilan
(tanlovda 2 ta qayta chiziladi), tooltip bitta (`HoverTip`),
ekrandan tashqaridagi qator `content-visibility: auto`. O'rindiqqa
MUI `Tooltip`/`ButtonBase`/`sx` QAYTARMANG — har biri 500 marta
ko'payadi. Statistika (`StatsStrip`) katta ekranda BITTA ixcham qator:
aks holda proktor stoli ekrandan pastga tushadi.
Ma'lumot: `computer-bookings/zones/` (bino kesimida sonlar, bitta
GROUP BY) va `seats/?zone=` (bitta binoning barcha joylari,
sahifalanmaydi, 2000 chegara) — ikkalasi ham `?schedule=` talab qiladi
va `get_queryset()` viloyat chegarasidan o'tadi. Viloyat
administratori umumiy (`zone=NULL`) jadvallarni ham KO'RADI
(`ExamScheduleViewSet`, faqat o'qish) — aks holda o'z kompyuterlariga
bron qila olmasdi.

### FaceID integratsiyasi (`/api/v1/integrations/faceid/`)

FaceID tizimi (alohida FastAPI loyiha) kompyuterlarni nomzodlarga
biriktiradi va Face ID'dan o'tgan nomzodni SHU YERDA bron qiladi — client
JSHSHIR tekshiruvida aynan shu bronni talab qiladi.

| Endpoint | Nima |
|---|---|
| `GET schedules/` | tugamagan (`ends_at >= now`) faol sessiyalar |
| `GET schedules/{id}/computers/` | ishchi kompyuterlar (buzilgan va raqamsiz yo'q), band bo'lsa `pinfl` bilan; hech narsa YOZMAYDI |
| `POST book/` | `bookings.assign` — panel bilan bir xil qoidalar, idempotent |

* **KIRISH — `X-API-Key`** (`integrations/authentication.py`), JWT bu
  yuzada QABUL QILINMAYDI. Kalit `.env` da (`FACEID_API_KEY`, production'da
  >= 32 belgi), bo'sh kalit HAR QANDAY qiymatni rad etadi. So'rov
  `FACEID_API_USER` servis xodimi nomidan: ruxsatlar (`bookings.view` /
  `bookings.manage`) paneldagi rolda, rol RESPUBLIKA darajasida bo'lishi
  shart (`RepublicLevelIntegration`) — viloyat roli boshqa viloyatlarning
  kompyuterlarini jimgina "yo'q" qilardi.
* **BINO TASHQI RAQAMLAR BILAN** — `region_dtm_id` + `zone_number`
  (FaceID'da `regions.number` + `zone.number`), kompyuter — `Computer.number`.
  Ichki ID'lar ikki tizimda mos kelmaydi.
* FaceID o'rinni `students.sp_n` ga yozadi va bronni Celery'da qayta
  urinishlar bilan yuboradi; `seat_in_use`/`seat_unavailable` (409) — qaror,
  qayta urilmaydi.

### Mashina tekshiruvi (Machine UUID) — ikkinchi darvoza

**`X-Device-ID` mashinani EMAS, client nusxasini belgilaydi.** U
diskda oddiy fayl bo'lib yotadi va mashina obrazi ko'chirilganda
(imtihon markazlarida odatiy amaliyot) u ham ko'chadi — o'nlab
mashina bitta `device_id` bilan ishlab, barcha sessiyalar bitta
kompyuterga yozilardi. Shuning uchun handshake'da ikkinchi savol
ham beriladi: **dastur qaysi apparatda ishlayapti?**

**JAVOB — `Computer.machine_uuid` (SMBIOS, ona plata), MAC EMAS.**
Ilgari MAC edi va u amalda o'zgaradi: tarmoq kartasi almashadi, USB/
Wi-Fi adapter ulanadi, marshrut boshqa adapterga o'tadi — ishlab turgan
mashina "ro'yxatda yo'q" bo'lib qolardi. UUID ona plata bilan yashaydi,
OS qayta o'rnatilsa ham o'zgarmaydi (client qanday o'qishi — "Lokal
xizmat" bo'limidagi manbalar zanjiri). MAC endi IKKILAMCHI va ixtiyoriy
(`blank`, shartli unikal faqat bo'sh bo'lmaganda).

| Qatlam | Qoida |
|---|---|
| model | `machine_uuid` NULL bo'lishi mumkin (UUID'dan oldingi yozuvlar), `unique_computer_machine_uuid` (tirik + NOT NULL) |
| shakl | `common.utils.validators.normalize_machine_uuid` — client bilan AYNAN bir xil (katta harf, `{}` siz, "to'ldirilmagan" ro'yxat, entropiya). Serializer'lar KANONIK shaklga keltiradi |
| panel | yangi kompyuterda MAJBURIY, eski yozuvni UUID'siz tahrirlash mumkin, bor UUID'ni o'chirib bo'lmaydi |
| client | handshake, `candidate/lookup/`, `devices/register/`, `access-attempt/` da `machine_uuid` HAR DOIM; sarlavhada KO'RSATILMAYDI (kataklar MAC/IP — o'zgarmagan) |
| sessiya | `ExamSession.machine_uuid` — kompyuter yozuvidan (bayonnoma) |
| qurilma | `DeviceToken.reported_machine_uuid` — client o'lchagani (ishonchsiz); panel yon varag'ida yozuvdagi UUID bilan yonma-yon |

* **Client WinAPI orqali o'lchaydi** (`system_info.machine_identity` —
  `machine_uuid` + marshrut tanlagan adapterning MAC/IP'si,
  `winapi_net.py`).
* **Server baholaydi** (`devices/services.py:verify_machine`).
  Qidiruv ko'lami — qurilmaning BINOSI: savol "bu mashina bazada
  bormi?" emas, "shu binoda bormi?".
* **Tekshiruv SOLISHTIRADI. YAGONA YOZUV — UUID'NI BIR MARTA
  BOG'LASH** (`bind_machine_uuid`): yozuvda UUID YO'Q va client aytgan
  MAC administrator kiritgan MAC bilan AYNAN mos bo'lsa, UUID yoziladi
  (`machine_uuid IS NULL` sharti `UPDATE` ichida, band UUID
  bog'lanmaydi) va auditda `update` + `meta.machine_uuid_bound`. Bu
  ilgari MAC bo'yicha "ok" bo'ladigan mashinaning O'ZI — ishonch
  o'zgarmaydi, lekin yuzlab mavjud mashinaga qo'lda UUID yozish shart
  emas. UUID BOR yozuvga client HECH QACHON tegmaydi.
* **UUID yubormaydigan ESKI client** — avvalgi MAC qoidasi
  (`_verify_by_mac`, `basis="mac"`), to'xtatmaslik uchun.

| `status` | Ma'nosi | Kim tuzatadi |
|---|---|---|
| `ok` | UUID mos (yoki shu tekshiruvda bog'landi — `bound`) | — |
| `not_found` | shu UUID binoda yo'q; xabarda yozuvdagi qiymat | administrator yozuvni to'g'rilaydi / qo'shadi |
| `mismatch` | UUID boshqa kompyuterniki (obraz ko'chirilgan) | administrator qurilmani QAYTA BIRIKTIRADI |
| `unknown` | client identifikator yubormadi | dasturni yangilash |

`ok` dan boshqasi `allowed=False` beradi va client "Davom etish"
ni bloklaydi. Yumshatish — `REQUIRE_MACHINE_MATCH=false` (eski nomi
`REQUIRE_MAC_MATCH` zaxira sifatida o'qiladi).

**Bu KREDENSIAL EMAS, inventarizatsiya intizomi.** UUID ni client
yuboradi, ya'ni uni o'zgartirish mumkin. Haqiqiy chegara
avvalgidek qurilma tasdig'i, xodim JWT'si va IP ro'yxatida.

**APPARAT IZI `muid:<UUID>`** (`client system_info.hardware_fingerprint`).
Eskisi `MAC|host|OS|arch` edi va MAC/kompyuter nomi o'zgarganda soxta
`fingerprint_changed` berardi. O'tish: saqlangan eski izdagi MAC client
aytgan MAC bilan mos bo'lsa etalon JIMGINA yangilanadi
(`is_fingerprint_upgrade`); aks holda avvalgidek anomaliya.
`devices/register/` dagi "o'sha mashinami" tekshiruvi ham shu qoida
bilan (`fingerprint_matches`). `muid:` prefiksi — ikki tomonli shartnoma.

Audit yozuvi rad etilgan tekshiruvdan CHIQMAYDI: ko'chirilgan qurilma
`record_handshake` da allaqachon `fingerprint_changed` anomaliyasini
beradi, operator esa nosozlikni ko'rib "Yangilash" ni ketma-ket bosadi
— har bosishda yozuv qoldirish jurnalni foydasiz qilardi.

**`mismatch` NING TUZATISHI — PANELDA QAYTA BIRIKTIRISH**
(`/device-tokens` → «Boshqa kompyuterga biriktirish»). `PATCH
device-tokens/{id}/` endi FAQAT `computer` ni o'zgartiradi: ilgari
`status`, `app_version`, `hardware_fingerprint`, `app_hash` ham
yozilardi va `PATCH {"status": "active"}` tasdiqlashni ham, uning
auditini ham chetlab o'tardi. Qayta biriktirish hisobdan chiqarilgan
mashinaga va boshqa viloyatga (viloyat administratori uchun) rad
etiladi va auditda `rebind` bo'lib qoladi. Holat faqat ikki amal
orqali: `approve/` (kutayotganni TASDIQLAYDI, bloklanganni BLOKDAN
CHIQARADI va blok izini tozalaydi; faol qurilmada hech narsa qilmaydi)
va `revoke/` (sabab MAJBURIY). Sahifa tab'lardagi sonlar bilan
(`stats/`) BARCHA qurilmalarda ochiladi — kutayotganlar alohida banner
bilan ko'rsatiladi.

**UCHTA MANZIL, UCHTA MA'NO** va ular aralashtirilmaydi:

| Qiymat | Kim aytdi | Nimani bildiradi |
|---|---|---|
| `DeviceToken.reported_lan_ip` | client | qaysi MASHINA |
| `DeviceToken.last_ip` | server | so'rov qaysi manzildan kelgan |
| `DeviceToken.reported_public_ip` | client | bino qaysi IP bilan chiqadi |

`ExamSession.ip_address` ga BIRINCHISI yoziladi (u yo'q bo'lsa —
manba manzili), qolgan ikkitasi `meta.network` da qoladi. Ilgari u
yerda server ko'rgan manzil turardi va panelda foydasiz bo'lib
chiqdi: bino ichidagi serverda u LAN manzil, dev'da `127.0.0.1`,
NAT ortida esa butun bino uchun bitta. Client aytgan qiymat
ISHONCHSIZ, lekin bu yerda hech qanday ruxsat qarori qabul
qilinmaydi — u faqat bayonnomaga yoziladi.

### Toza mashina: IKKI TOZALOVCHI, bitta ham ortiqcha emas

Ular bir-birini almashtira olmaydi va mezonlari BUTUNLAY boshqa:

| | `app_closer.py` | `threat_scanner.py` |
|---|---|---|
| Mezon | ko'rinadigan OYNA | dastur KIMLIGI |
| Nishon | har qanday dastur | katalogdagi dastur |
| Oynasizni ko'radimi | **yo'q** | **ha** |
| Xizmatga tegadimi | yo'q | **to'xtatadi** |
| Yopish usuli | `WM_CLOSE`, keyin majburan | darhol majburan |

AnyDesk xizmati, `VBoxSVC.exe` va `remoting_host.exe` ning
KO'RINADIGAN OYNASI YO'Q — birinchisi ularni umuman ko'rmaydi.
Katalogda yo'q messenjerni esa faqat birinchisi yopadi. Tartib:
avval `app_closer` (oynalar ketadi), keyin `threat_scanner` (oynasiz
qism qoladi); teskarisida ikkinchisi birinchisining natijasini
"qayta paydo bo'ldi" deb o'qishi mumkin edi.

**NOM BO'YICHA QIDIRMAYMIZ.** `AnyDesk.exe` ni `notepad.exe` deb
qayta nomlash bir soniyalik ish, ya'ni nom ro'yxati eng sodda
hujumga ham dosh bermaydi. Qaror to'rtta belgidan chiqadi va ular
ishonchlilik bo'yicha tartiblangan (`process_identity.py`):

| Belgi | Qayta nomlash ta'sir qiladimi | Narxi |
|---|---|---|
| Authenticode **imzo egasi** | yo'q | ~2–10 ms |
| PE **`OriginalFilename`** | **yo'q** | ~0.3 ms |
| `ProductName`/`FileDescription` | yo'q | o'sha resursdan |
| Windows **xizmat** nomi | yo'q | xizmatlar ro'yxati |
| tinglanayotgan **port** | yo'q | `net_connections` |
| fayl nomi | **ha** | — (zaxira, oxirgi) |

IMZO KECHIKTIRILADI: u faqat arzon belgilar javob bermagan va
`%SystemRoot%` dan TASHQARIDAGI fayllar uchun o'qiladi. Aks holda
322 jarayonli mashinada har skaner bir necha soniya olardi.
Natija `(yo'l, mtime, hajm)` bo'yicha keshlanadi — birinchi skaner
~1 s, keyingilari ~0.24 s.

**IMZO O'QILADI, TEKSHIRILMAYDI.** Savol "bu imzo ishonchlimi?"
emas, "kim imzolagan deb da'vo qilinyapti?" — o'zini "AnyDesk
Software GmbH" deb imzolagan soxta sertifikat ham bizga KERAKLI
javobni beradi. Zanjirni tekshirish har fayl uchun CRL/OCSP
so'rovi degani: tarmoqqa bog'liq va imtihon mashinasida ko'pincha
timeout. Faqat PE ichiga joylashgan imzo ko'rinadi; Windows tizim
binarlari KATALOG bilan imzolanadi va ular uchun bo'sh qaytadi —
nishonlarimiz baribir uchinchi tomon o'rnatuvchilari.

**KENG VENDOR IMZOSI KATALOGGA KIRMAYDI.** "Google LLC" ni
`publishers` ga yozish Chrome'ning o'zini tutardi. Chrome Remote
Desktop `OriginalFilename` (`remoting_host.exe`) va `ProductName`
bilan tutiladi — ular ham qayta nomlashdan himoyalangan.

**XIZMATNI TO'XTATMASDAN JARAYONNI O'LDIRISH FOYDASIZ**: SCM uni
bir necha soniyada QAYTA KO'TARADI. Tartib qat'iy — avval xizmat,
keyin jarayon. Shuning uchun `sweep()` uchinchi qadamni ham
bajaradi: tozalashdan keyin QAYTA skanerlaydi va qaytib kelganini
"yo'q qilinmagan" deb belgilaydi.

**TO'RTTA QATLAM, UCHTA TARTIB.** Qidiruv birinchi mos kelgan
qoidada to'xtaydi, shuning uchun tartib mantiqning qismi:

```
aniq ichki qoidalar -> serverdagi ro'yxat -> kalit so'z tori
(BUILTIN_RULES)        (Setting.rdp_objects)  (FALLBACK_RULES)
```

`generic_remote` ("remote desktop", "remote access"...) OXIRIDA va
ALOHIDA ro'yxatda: keng kalit so'z undan keyingi har qanday aniq
qoidani jimgina soyalab qo'yardi. Ichki katalog OLDINDA, chunki
uning belgilari kuchliroq va `blocking` bayrog'i tekshirilgan —
panelga yozilgan bir nomli, faqat jarayon nomi bilan berilgan
dublikat oldinda tursa, u AnyDesk'ni "to'smaydigan" qilib qo'yardi.

**`blocking` `category` DAN KELIB CHIQMAYDI** va bu ataylab. Aniq
vendor qoidasi to'sadi (xato ehtimoli deyarli nol); kalit so'z
qoidasi va panelga qo'shilgan yozuv **to'sMAYDI** (`is_blocking`
standart `False`) — ular muassasaning o'z IT agentini tutishi
mumkin va butun imtihonni bloklab qo'ymasligi kerak. Dastur
baribir yopiladi va hodisa yoziladi.

**KERNEL DARAJASIDA O'LDIRISH YO'Q va bo'lmaydi.** Buning uchun
imzolangan kernel-mode drayver kerak: u Defender uchun zararli
xulq bo'lib ko'rinadi, PPL-himoyalangan jarayonga baribir tegmaydi
va ishlab turgan gipervizor drayverini majburan tushirish BSOD
beradi. Chegara ochiq qilingan: userland'da o'ldirib bo'lmaydigan
narsa **IMTIHONNI TO'SADI** (`check_readiness` → `PolicyIssue`),
mashina esa ishlab turadi. Natija xuddi shunday qat'iy.

**ADMIN HUQUQI YO'Q BO'LSA TOZALASH YARIM QOLADI** va bu jimgina
o'tmaydi: xizmatlarni to'xtatish ham, boshqa hisob jarayonini
o'ldirish ham administrator huquqini talab qiladi. "Topdim, lekin
qo'limdan kelmadi" holati `survivors` ga tushadi va to'siq beradi
(imtihon profilida `Setting.is_threat_block_exam=False` uni
ogohlantirishga tushiradi; zaxira `.env` `THREAT_BLOCK_EXAM`).

**UCHTA MUHIT SAVOLI** jarayonlardan MUSTAQIL (`process_identity.py`):

* `in_remote_session()` — `SM_REMOTESESSION`. "Masofaviy boshqaruv
  dasturi o'rnatilgan" emas, "mashinani HOZIR kimdir masofadan
  boshqaryapti". `mstsc.exe` ni qayta nomlash ham, uni boshqa
  client bilan almashtirish ham bunga ta'sir qilmaydi. O'Z seansimiz —
  uni "o'ldirib" bo'lmaydi, to'g'ridan-to'g'ri to'siq.
* `foreign_rdp_sessions()` — `WTSEnumerateSessions` +
  `WTSClientProtocolType == 2`: mashinadagi BOSHQA faol RDP seansi
  (Windows Server, RDPWrap; yordamchi `mstsc /shadow` bilan talabgor
  ekranini ko'radi — o'shanda talabgor seansi "lokal" va birinchi
  savol JIM). Admin huquqisiz, ~1 ms. `rdp_foreign_session` topilmasi
  (`kind="rdp_session"`) faqat IMTIHON DAVOMIDA yakunlanadi
  (`neutralize(end_rdp_sessions=True)` — `device_watch`, `WTSLogoffSession`,
  admin kerak; disconnect EMAS — u qayta ulanadi). Ishga tushishda va
  "Davom etish" da faqat qayd + TO'SIQ: imtihondan tashqarida o'ldirish
  texnikning xizmat seansini uzardi. Yakunlab bo'lmasa — to'siq (KRITIK).
  O'z seansimiz va 0-seans hech qachon yakunlanmaydi (`logoff_session`
  o'zi ham tekshiradi). Terminal serverli muassasa: `THREAT_SCAN_ALLOW`
  ga `rdp_foreign_session`.
* `host_virtualization()` — BIOS registridagi 7 maydon (`SystemManufacturer`,
  `SystemProductName`, `SystemFamily`, `BIOSVendor`, `BIOSVersion`,
  `BaseBoardManufacturer`, `BaseBoardProduct`; Hyper-V belgisi aynan
  `BIOSVersion` da). Qisqa belgilar (`xen`, `kvm`, `qemu`) faqat BUTUN SO'Z
  — soxta VM to'sig'i butun imtihonni to'xtatardi (`detect_vm_marker`).
  Client virtual mashina ICHIDA ishlayaptimi: kiosk rejimi ham, tezkor
  tugmalar bloki ham mehmon tizimdan tashqariga chiqmaydi. VDI
  o'rnatishlarida `THREAT_ALLOW_VIRTUAL_HOST=true` kerak, aks
  holda butun sinf imtihonni boshlay olmaydi.

**UCH NUQTADA ISHLAYDI:**

| Qachon | Nima qiladi | Natija qayerga |
|---|---|---|
| Ishga tushish (`main`) | `sweep()`, Qt'dan oldin | modul darajasida saqlanadi |
| "Davom etish" bosilganda | `sweep()` fon thread'ida | `check_readiness` → modal |
| Imtihon davomida (15 s) | `scan()` + darhol yo'q qilish | hodisa oqimi |

Ikkinchisi SHART: dastur ochilgandan imtihon boshlanishigacha
soatlar o'tishi mumkin va shu oraliqda AnyDesk qayta ishga
tushirilgan bo'lishi mumkin. Teskarisi ham muhim — operator
dasturni KO'RSATILGANIDEK o'chirgan bo'lsa, eski hisobot bilan
imtihon baribir to'silib turardi.

Ishga tushishdagi hisobot hodisa oqimiga IMTIHON BOSHLANGANDA
qo'shiladi (`exam_webview_page._report_startup_threats`): tozalash
paytida na sessiya, na bufer mavjud edi. Yopilgan dastur ham
yoziladi — "mashinada masofaviy boshqaruv o'rnatilgan" tekshiruv
komissiyasi uchun ma'lumot.

Jiddiylik natijaga qarab: yo'q qilingan — `HIGH` (3), qolgan —
`CRITICAL` (4). Ikkinchisi write-behind buferini chetlab o'tib
darhol yoziladi va proktor ekranida o'sha zahoti ko'rinadi.
Proktor uchun `neutralized` bayrog'i HAL QILUVCHI: "AnyDesk topildi
va yopildi" bayonnomaga yozuv, "yopib bo'lmadi" esa darhol
aralashuvni talab qiladi — ekran hozir ham ochiq bo'lishi mumkin.

`.env`: `THREAT_SCAN_ENABLED` (standart = `KIOSK_MODE`),
`THREAT_SCAN_ALLOW`, `THREAT_ALLOW_VIRTUAL_HOST` — skaner Qt'dan va
serverdan OLDIN ishlaydi, shuning uchun lokal. To'sish qarori esa
IMTIHON siyosati: `Setting.is_threat_block_exam` (panel «Himoya»).
**Dev mashinasida
`THREAT_SCAN_ENABLED=false`** — aks holda VirtualBox, WSL2 va
Docker Desktop yopilishga uriniladi.

### Bitta ekran: ortiqcha monitorlar o'chiriladi

Ikkinchi monitor kiosk rejimining butun mantig'ini bekor qiladi:
oynamiz asosiy ekranda to'liq ochiladi, talabgor esa yonidagi
ekranda ochiq qolgan hujjatni yoki masofadan ulangan odamning
kursorini ko'rib turadi. Skrinshot ham faqat ASOSIY ekranni oladi
(`services/screen_capture.py`), ya'ni bayonnomada bundan iz
qolmaydi.

`DeviceWatcher` ikkinchi monitorni allaqachon ANIQLAYDI
(`multi_monitor`), lekin u HODISA — proktor ekranidagi qator.
Qator paydo bo'lguncha talabgor uni allaqachon ishlatgan bo'ladi.
Shuning uchun `services/display_control.py` ikkinchi qadamni
bajaradi: ekran ish stolidan UZILADI va Windows unga umuman
chizmaydi. Hodisa qatlami saqlanadi — u imtihon O'RTASIDA
ulangan monitorni ko'radi.

Qoidalar:

* **Qt'dan OLDIN** (`main._disable_extra_monitors`) va dasturlarni
  yopishdan ham oldin. `QApplication` ekranlar ro'yxatini ishga
  tushishda o'qiydi; keyin o'chirilsa, oyna mavjud bo'lmagan
  ekranga qo'yilgan bo'lishi mumkin. Tartib ham muhim: monitor
  uzilganda undagi oynalar asosiy ekranga ko'chadi va `app_closer`
  ularni "ko'rinadigan oyna" sifatida ko'radi.
* **Asosiy monitorga va ko'zgu drayverlariga tegilmaydi.**
  Birinchisiz oynani ko'rsatadigan joy qolmasdi; ikkinchisi esa ish
  stolining kengaytmasi emas, nusxasi.
* **UZISH MAYDONLARI QAYTARISHNIKIDAN FARQ QILADI.** Uzish —
  nol o'lchamli `DEVMODE`, lekin `dmFields` da `DM_BITSPERPEL`
  yoki `DM_DISPLAYFREQUENCY` bo'lsa drayver `DISP_CHANGE_BADMODE`
  (-2) qaytaradi: nol rang chuqurligi va nol chastota u uchun
  yaroqsiz GRAFIK REJIM, holbuki biz rejim so'ramayapmiz.
  Uzishda `DM_POSITION|DM_PELSWIDTH|DM_PELSHEIGHT`, qaytarishda
  esa beshalasi (qiymatlar haqiqiy). Bu mashinada o'lchab
  aniqlangan — xato JIMGINA emas, lekin "drayver rad etdi" degan
  kod sababni aytmaydi.
* **Uzish `CDS_UPDATEREGISTRY` bilan**, ya'ni qayta yuklashdan
  keyin ham saqlanadi — shuning uchun asl `DEVMODE` xotirada
  saqlanadi va chiqishda QAYTARILADI (`finally`). Qaytarmaslik
  mashinani imtihondan keyin ham bitta ekranda qoldirardi.
* **Administrator huquqi kerak emas**: konfiguratsiya joriy
  interaktiv seans doirasida o'zgaradi.
* `SetDisplayConfig(SDC_TOPOLOGY_INTERNAL)` qisqaroq bo'lardi,
  lekin u faqat noutbukda ishlaydi ("ichki panel") — imtihon
  mashinasi odatda statsionar kompyuter.

`.env`: `DISABLE_EXTRA_MONITORS` (standart = `KIOSK_MODE`),
`RESTORE_MONITORS_ON_EXIT`. **Dev mashinasida
`DISABLE_EXTRA_MONITORS=false`** — aks holda ikkinchi monitoringiz
client ishga tushganda o'chadi.

### "Client ishlab turibdi" (presence)

Panelda `Computer.status` ustuni bor edi, lekin u YOLG'ON ko'rsatardi.
Holat faqat uch nuqtada yangilanardi — handshake (login), imtihon
boshlanishi va yakuni; oradagi vaqtda hech kim `last_seen_at` ga
tegmasdi, `refresh_device_status` esa 120 soniyadan keyin mashinani
OFFLINE deb belgilardi. Natijada ishlab turgan client ham, imtihon
o'rtasidagi mashina ham "o'chirilgan" bo'lib ko'rinardi.

Yechim — **`client/presence/`**: client har 45 soniyada yengil
signal yuboradi. Oraliqni SERVER aytadi
(`config.network.presence_interval` =
`devices.services.PRESENCE_PING_INTERVAL`, TTL bilan yonma-yon);
`.env` `PRESENCE_PING_MS` — zaxira.

**SESSIYA TALAB QILINMAYDI** va butun gap shunda: sessiya
heartbeat'i faqat imtihon davomida ketadi, client esa kunning katta
qismini sessiyasiz o'tkazadi (operator kirgan, talabgor kutilmoqda).
Imtihon davomida esa alohida signal YUBORILMAYDI — heartbeat baribir
kelib turibdi va presence o'sha yerdan yangilanadi.

**IKKI QATLAM:**

| Qatlam | Nima uchun | Muddat |
|---|---|---|
| Redis `dev:online:{device_id}` | "hozir ishlayaptimi", kim kirgan, imtihondami | `PRESENCE_TTL` (100 s) |
| `Computer.status` + `last_seen_at` | panel ro'yxatini SQL'da saralash/filtrlash | doimiy |

TTL signal oralig'idan IKKI BAROBAR katta: bitta o'tkazib
yuborilgan signal (tarmoq sakradi) mashinani darhol "offline"
qilmasligi kerak — panelda bu miltillash bo'lib ko'rinardi.

**DB YOZUVI DAQIQADA BIR MARTA** (`PRESENCE_DB_INTERVAL`) va
cheklovchi ham Redis'da (`issue_camera_stream` dagi grant kaliti
bilan bir xil naqsh): 10 000 mashina har signalda `UPDATE` qilsa,
"men tirikman" degan xabar uchun 220 yozuv/sekund bo'lardi.
`DeviceToken.last_used_at` esa HAR signalda yangilanadi — u bitta
arzon `UPDATE` va "oxirgi marta qachon ko'rindi" degan boshqa
savolga javob beradi.

Redis yo'q bo'lsa presence DB orqali ko'rinadi (kechroq, lekin
yolg'on emas) — signal imtihonning sharti emas, diagnostika.

**PANELDA QAYERDA KO'RINADI:**

* `/device-tokens` — «Client» ustuni (Online / Imtihonda / Offline),
  «Kirgan xodim», «Oxirgi faollik» va `?online=true` filtri;
* `/computers` — «Holat» va «Oxirgi signal» (endi haqiqiy);
* Dashboard — bino kesimidagi "online" hisoblagichlari o'sha
  `Computer.status` dan oziqlanadi.

Ikkala ro'yxat ham 30 soniyada O'ZI yangilanadi
(`ResourcePage refetchInterval`): holat 45 soniyada o'zgaradi va
operatordan sahifani qo'lda yangilashni kutish mumkin emas.

### Kamera tekshiruvi va kuzatuv darvozasi

**Client O'LCHAYDI, server BAHOLAYDI.** Client xom qiymatlarni
yuboradi (FPS, rezolyutsiya, kechikish, kadrdagi yuz, yorug'lik),
chegaralarni esa server qo'llaydi (`services/camera_check.py`).
Sabab ikkita: client'ga ishonib bo'lmaydi (o'zgartirilgan nusxa
"hammasi joyida" derdi), va qoida ikki joyda yashab, albatta
ajralib ketardi. Client serializer'i `ok`/`passed` kabi maydonlarni
umuman **qabul qilmaydi**.

14 ta tekshiruv `camera_check.evaluate` da va ularning kodlari
`{rol}_{tekshiruv}` shaklida — ya'ni natija ALLAQACHON kamera
bo'yicha ajratilgan. Bitta qoida hal qiluvchi:

| Nosozlik | Majburiy kamerada | Ixtiyoriyda |
|---|---|---|
| FPS/rezolyutsiya/oqim | **to'siq** | ogohlantirish |
| kechikish, yorug'lik, burchak | ogohlantirish | ogohlantirish |
| **virtual kamera** | **to'siq** | **to'siq** |

Oxirgisi istisno va u ataylab: qolganlari sifat masalasi, virtual
qurilma esa xavfsizlik qoidasi (oldindan yozilgan videoni jonli
oqim sifatida ko'rsatish).

Tekshiruv sessiya YARATILISHIDAN oldin o'tadi, shuning uchun natija
Redis'da qurilma bo'yicha saqlanadi (`cam:check:{device_id}`,
`CAMERA_CHECK.SNAPSHOT_TTL`) va `proctoring/start/` da
`ExamSession.camera_check` ga **ko'chiriladi** — dalil sifatida
qoladigan nusxa aynan o'sha.

**HAR KAMERA ALOHIDA TEKSHIRILADI.** Kadr ostidagi tugma faqat
o'sha kamerani o'lchaydi; panel tugmasi hammasini. Tavsiya —
**yuz kamerasi**: aynan u shaxsni aniqlaydi va uning nosozligi
imtihonni to'xtatadi, ikkinchisi esa siyosat talab qilsagina
majburiy (`secondary_required`). Ikkinchi kamerani har safar birga
tekshirish qo'shimcha ~4 soniya kutish va ko'pincha keraksiz.

Buning uchun uchta narsa kerak bo'ldi va ular birga ishlaydi:

* o'lchovda `measured` bayrog'i — "kamera bor, lekin bu safar
  tekshirilmadi". U `available=False` ("topilmadi") dan BOSHQA
  holat: birinchisini operator tugmani bosib hal qiladi,
  ikkinchisini kabelni ulab;
* server suratchada XOM O'LCHOVLARNI saqlaydi (`measurements`) va
  yangi tekshiruvni ularning ustiga qo'yadi
  (`camera_check._merge_measurements`) — aks holda bitta kamerani
  tekshirish ikkinchisining natijasini o'chirib yuborardi;
* birlashtirishning ikki chegarasi bor: eskirgan o'lchov
  (`SNAPSHOT_TTL`) va **qurilma almashgani** (`local_index` mos
  kelmasa). Ikkinchisi rollarni almashtirgandan keyin eski
  o'lchovni yangi kameraga yopishtirib qo'yishni to'sadi.

Tekshirilmagan kamera `{rol}_checked` kodini beradi: majburiy
bo'lsa **to'siq**, aks holda ogohlantirish.

**`client/proctoring/start/` — yagona darvoza.** U `exam/access/`
dan keyin va WebView ochilishidan **oldin** turadi:

* undan oldingi qadamlarni (FaceID, shaxs tasdig'i) to'sish
  operatorga nosozlikni KO'RSATADIGAN ekranga yetib borishga ham
  imkon bermasdi;
* undan keyin to'sish kech — talabgor testni allaqachon ko'rgan
  bo'ladi va platformada urinish ochilgan.

Rad javobi ikki xil va operator uchun ular boshqa-boshqa:
`camera_check_required` (tekshiruv yo'q/eskirgan → takrorlash) va
`camera_check_failed` (bor, lekin talablarga mos emas → uskunani
tuzatish). `REQUIRE_CAMERA_CHECK=false` birinchisini o'chiradi —
dastlabki joylashtirishda kameralar hali ulanmagan bo'lishi mumkin.

Rad etilganda sessiya **TIRIK qoladi** (`session_blocked` signali,
`session_lost` dan ajratilgan): client FaceID sahifasiga qaytadi va
operator kamerani tuzatib qayta uradi. Sessiyani yopish talabgorni
qaytadan JSHSHIR bilan qidirishga majbur qilardi.

**QAYTILGANDA YUZ QAYTA SOLISHTIRILMAYDI** (`faceid_page._enter_resume`).
Challenge `face/verify/` da SARFLANGAN — ilgari sahifa solishtirishni
noldan boshlar va har ~300 ms da `face/verify/` → 404
`session_not_found` olardi (rad javobidan keyin ham urinish yopilmasdi).
Endi uch amal: «Imtihonni boshlash» (`exam/access/` + start qayta),
«Kamerani tekshirish» (imtihon tanlash sahifasi,
`_go_to_exam(hold_session=True)` — oqim tozalanmaydi, o'sha imtihon
tanlansa FaceID'ga qaytib imtihon darhol ochiladi; boshqasi tanlansa
sessiya yopiladi) va «Boshqa talabgor» (sessiya `completed` SIZ yopiladi
— qulf bo'shaydi, bron saqlanadi).

**TEKSHIRUV MAJBURIYLIGI CLIENTGA OLDINDAN AYTILADI** —
`proctoring.camera.check_required` (= `REQUIRE_CAMERA_CHECK`). Client
tayyorlik oynasida "tekshiruv o'tkazilmagan" ni shu bayroq va kamera
talab qilinganda TO'SIQ qiladi (`policy.check_readiness`); ilgari u
ogohlantirish edi va to'siq talabgor FaceID'dan o'tgach chiqardi.

### IP kamera holati va paneldagi jonli ko'rish

**HOLAT HAQIQIY RTSP SO'ROVI BILAN** (`devices/camera_probe.py`,
`devices.probe_cameras` — har 60 s, `maintenance` navbati). Ilgari
`Camera.status` HECH QAYERDA yangilanmasdi va panelda doim standart
"Offline" turardi. Tekshiruv — `DESCRIBE`, aynan client so'raydigan
yo'l va kredensial bilan (Basic/Digest, `socket`, yangi
bog'liqliksiz). Faqat TCP port ochiqligi yetmaydi: noto'g'ri parol
yoki yo'lda port javob beradi, client esa imtihon kuni "oqim
ochilmadi" bilan qoladi.

| `status` | Ma'nosi | `status_message` misoli |
|---|---|---|
| `online` | 200, oqim bor | — |
| `error` | javob bor, lekin rad | "Login yoki parol noto'g'ri", "RTSP yo'li topilmadi" |
| `offline` | javob yo'q | "Port 554 yopiq", "Javob yo'q (3 s)" |

`last_seen_at` — oxirgi marta ONLINE bo'lgan payt (xatolikda
o'zgarmaydi), `last_checked_at` — oxirgi tekshiruv (tekshiruv
umuman ishlamay qolganini shundan bilish mumkin). Holat maydonlari
`update()` bilan yoziladi, `save()` emas: administrator shu payt
kamerani tahrirlayotgan bo'lishi mumkin. Tekshiruv PARALLEL
(`check_cameras`, thread'lar) — 60 ta offline kamera ketma-ket 3 minut
olardi.

**SERVER NUQTAI NAZARIDAN.** Server bino tarmog'idan tashqarida
(markazlashgan o'rnatish, NAT) bo'lsa, ishlab turgan kamera ham
"offline" ko'rinadi — u holda `CAMERA_PROBE_ENABLED=false`.

**JONLI KO'RISH — MJPEG OQIMI, 2 S DAN KAM KECHIKISH**
(`devices/camera_live.py`, `cameras/{id}/live/`). Brauzer RTSP ni
o'ynata olmaydi, shuning uchun server oqimni ochadi va bitta uzun HTTP
javobda JPEG kadrlarni yangi kelishi bilan yuboradi
(`multipart/x-mixed-replace`, ~10 kadr/s, 1280 px). Panel uni
`fetch` bilan o'qiydi (`components/cameras/mjpegStream.js` —
`Authorization` sarlavhasi saqlanadi, `<img src>` esa uni qo'ya
olmasdi) va FAQAT ENG YANGI kadrni `createImageBitmap` + canvas bilan
chizadi: dekodlash band bo'lsa oraliqdagi kadrlar tashlanadi.

Ilgari panel har kadr uchun alohida so'rov yuborardi (~4 kadr/s) va
tasvir qotardi. ASL SABAB esa o'quvchida edi va O'LCHANGAN: kamera
HEVC 2688x1520 ~22.5 kadr/s beradi, 1 threadli dekodlash ~28 kadr/s,
har kadrni BGR ga o'girish (~16 ms) bilan esa kameradan SEKIN — FFmpeg
buferi to'lib, kechikish daqiqasiga ~10 s o'sardi. Endi:

* `CAP_PROP_N_THREADS=4` (quvvat ~38 kadr/s);
* har kadrda FAQAT `grab()`, `retrieve()` faqat yuboriladiganida;
* miqyoslash va JPEG ALOHIDA thread'da (bitta o'rinli pochta qutisi);
* yuborish kamera RITMIDA — har N-kadr (tezlik `grab()` oraliqlaridan
  o'lchanadi; e'lon qilingan 25 FPS yolg'on). "83 ms o'tdimi?" qoidasi
  notekis ~8 kadr/s berardi;
* KECHIKISH QO'RIQCHISI: jonli chegarada `grab()` tarmoqni kutadi
  (median ~47 ms), buferdan esa darhol qaytadi (~0 ms). Oxirgi 20 ta
  `grab()` medianasi 12 ms dan kam holat 1.5 s cho'zilsa — oqim qayta
  ochiladi. `POS_MSEC` ga TAYANMANG: RTSP'da u kadr sonidan hisoblanadi
  va siljiydi.

O'lchangan natija: 62 s da 0 qayta ulanish, 10 kadr/s, server ichida
~8 ms, kamera soatidan kechikish boshida ham, oxirida ham ~0.4-1.4 s
(o'smaydi).

Javob `CAMERA_LIVE_STREAM_SECONDS` (60) dan keyin tugaydi va panel
DARHOL qayta ulanadi (o'quvchi issiq, uzilish sezilmaydi) — cheksiz
so'rov gunicorn thread'ini abadiy band qilardi. Jarayon ichida bir
vaqtdagi oqimlar `CAMERA_LIVE_MAX_STREAMS` (2) bilan cheklangan
(`gthread`, 8 thread — ko'ruvchilar oddiy API'ni to'smasligi kerak),
to'lsa 503 `camera_viewer_busy`. `X-Accel-Buffering: no` — nginx
kadrlarni to'plab uzatmasligi uchun. Panel 5 daqiqadan keyin o'zi
to'xtaydi.

(test) Oqimli javobda `response.close()` ni QO'LDA chaqirmang — u
`request_finished` orqali test tranzaksiyasining DB ulanishini yopadi
va keyingi testlar "connection already closed" bilan yiqiladi;
`list(response.streaming_content)` bilan oxirigacha o'qing.

`snapshot/` (bitta kadr) API sifatida qoladi.

OpenCV (`opencv-python-headless`) serverda FAQAT shu yerda va dangasa
import qilinadi — dekodlash uchun, ML uchun emas. `requirements.txt`
**UTF-8** (ilgari BOM'siz UTF-16 edi va Linux'dagi pip paket nomlarini
`\x00D\x00j...` deb o'qib yiqilardi). PowerShell 5.1 da
`pip freeze > requirements.txt` yozmang — u yana UTF-16 qiladi.

RUXSAT `devices.manage` (GET bo'lsa ham) — bu imtihon xonasining JONLI
tasviri, ro'yxatni ko'rish huquqi (`devices.view`) uni ochmaydi. Har
ko'rish audit'da (`camera_live_view`), takrorlar 10 daqiqada bitta
yozuvga yig'iladi.

### RTSP kredensiali — cheklangan berish

`HandshakeView` kameralar ro'yxatini **kredensialsiz** qaytaradi va bu
qoida kuchda qoladi. Client kadr olishi kerak bo'lgani uchun alohida
endpoint bor: `client/camera/stream/`.

So'rov **KAMERA ID bo'yicha** ketadi (`camera_id`), rol bo'yicha emas:
biriktirish olib tashlangach rolni faqat client biladi va uni serverga
yuborishning ma'nosi qolmadi. ID handshake bergan ro'yxatdan keladi,
ya'ni client o'ylab topgan qiymat emas. `role` ham yuboriladi, lekin
faqat AUDIT uchun — jurnalda "qaysi vazifa uchun so'raldi" degan yozuv
qolishi kerak.

Nima beradi:

* kredensial faqat **kompyuter turgan binodagi** faol kamera uchun
  (`devices.services.camera_for_computer`). Ilgari doira biriktirish
  edi; u olib tashlangach yagona chegara BINO bo'lib qoldi — boshqa
  binoning kamerasi boshqa jadval va boshqa proktorga tegishli;
* har bir berish `AuditLog` da (`camera_credential_issue`);
* client uni faqat xotirada saqlaydi (`RtspSource` manzilni **satr
  emas, funksiya** ko'rinishida oladi — u har ochilishda qaytadan
  so'raladi).

Nima **bermaydi**: kredensialning o'zi muddatsiz. RTSP paroli
kameraning ichida yashaydi va uni serverdan bekor qilib bo'lmaydi.
`CAMERA_STREAM_GRANT_TTL` (15 daq) faqat takroriy audit yozuvlarini
to'sadi. Shuning uchun **ekspluatatsiya qoidasi kodning bir qismi**:
kameralarda faqat o'qish huquqiga ega alohida hisob bo'lishi va u
davriy almashtirilishi kerak. Administrator hisobi ishlatilsa, bu
endpoint uni butun binoga tarqatadi.

### Temporal, fusion va xavf balli

**BITTA KADR HECH QACHON QAROR EMAS.** Har bir shart tasdiqlanishi
uchun **uchta** talabga birdan javob berishi kerak
(`behavior/temporal_engine.py`):

```
ketma-ket kadr   >= min_frames
davomiylik       >= min_duration_ms
o'rtacha ishonch >= min_confidence
```

Uchalasi ham kerak: yuqori FPS da 5 kadr 0.2 s (juda qisqa), CPU
rejimida esa 5 kadr 2 s (yetarli). Faqat kadrga tayanish hodisani
CPU'da cheksiz kechiktirardi, faqat vaqtga tayanish esa bitta
tasodifiy aniqlanishni tasdiqlab yuborardi.

Tasdiqlangach shart **ochiq qoladi** va yangi hodisa tug'ilmaydi —
`track_id` bilan bog'langan telefon 100 kadr ko'rinsa ham bitta
hodisa bo'ladi. Yopilish `release_ms` kechikish bilan: obyekt qo'l
bilan vaqtincha yopilganda iz saqlanadi.

**Ikki darajali holatlar** (`no_face`, `gaze_away`) — ogohlantirish
keyin shubha. Jiddiylashgan hodisa ham davom etgan sayin **ochiq
qoladi**: uni bir marta kuzatib qo'yish nol davomiylikli keraksiz
yozuv berardi. Epizod tugagach bayroq tozalanadi — ikkinchi uzoq
chalg'ish ham qayd etiladi.

**Fusion tarkibiy hodisalarni O'CHIRMAYDI**
(`behavior/event_fusion.py`). "Yuqori shubha" ularning ustiga
qo'shiladi: apellyatsiyada "nima uchun?" degan savolga faqat
tarkibiy hodisalar javob bera oladi. `fused_from` payload'da
zanjirni saqlaydi.

#### Xavf balli (`proctoring/services/risk.py`)

Ilgari oddiy hisoblagich edi. Uchta narsa qo'shildi va ularsiz
chetlashtirish qarori asossiz qolardi:

| | Ilgari | Endi |
|---|---|---|
| pasayish | yo'q | daqiqasiga N ball, **lazy** |
| takror | har safar sanardi | tur bo'yicha cooldown |
| tushuntirish | yo'q | `risk_breakdown` |

**Pasayish LAZY**: fon vazifasi yo'q, oxirgi o'zgarish vaqti
saqlanadi va pasayish o'qilganda yoki keyingi qo'shilganda
hisoblanadi. 10 000 sessiyani har 10 soniyada kamaytirish bekorga
yuk bo'lardi.

**Tarkib PASAYMAYDI** — u "nima bo'lgan" degan savolga javob
beradi, "hozir qanchalik xavfli" degan savolga emas.
Pasaytirilsa, "40 ball telefon uchun edi" degan da'voni
tasdiqlab bo'lmasdi.

**IKKI SOAT**: pasayish `now` parametrida (testda almashtiriladi),
cooldown esa Redis TTL'da (haqiqiy soat). Cooldown ataylab TTL'da —
u **atomik** bo'lishi shart, aks holda bir vaqtda kelgan ikkita bir
xil hodisa ikkalasi ham sanalardi.

Og'irliklar `controls.EventRiskWeight` dan; jadval bo'sh bo'lsa
`ingest.RISK_WEIGHTS` zaxira sifatida ishlaydi.

**COOLDOWN TURGA XOS** (`risk.cooldown_for`): `EventRiskWeight.cooldown_s`
(>0) → siyosatdagi `risk_event_cooldown_s`. Turniki siyosatdagi `0`
(o'chirilgan) dan ham ustun. `0` — "siyosatdagi qiymat", "cooldown yo'q"
EMAS (`risk_cooldown_map` uni tashlab ketadi). Sabab: `window_blur`,
`looking_away` shovqinli (uzun oyna), telefon, ikkinchi odam kam va
jiddiy (qisqa oyna) — bitta son ularni sozlashga imkon bermasdi.
Og'irlik va cooldown BITTA kesh yozuvida (`controls:risk_weights:v2`).

**`EventRiskWeight` DA JIDDIYLIK YO'Q** (`controls.0011`). Uni client
beradi va u darhol yozish, proktor ekrani, dalil yig'ishni hal qiladi.
Ustun ilgari bor edi, lekin hech qayerda o'qilmasdi; uni ustun qilish
esa paneldagi bitta raqam bilan kritik hodisani oddiyga aylantirardi.

(test) `.env` test sozlamalariga ham o'tadi. Muhitga xos bayroqlarni
(`REQUIRE_COMPUTER_BOOKING`, `ALLOW_PRIVATE_SOURCE_IP`, `REQUIRE_DEVICE_ID`)
`settings/test.py` O'ZI mahkamlaydi — ilgari lokal `true` qiymat sessiya va
IP ro'yxati testlarini yiqitardi. Yangi shunday bayroq qo'shsangiz uni ham
`test.py` da mahkamlang; `.env` da esa muhitga xos kalitni BO'SH qoldiring
(har modul o'z standartini oladi).

### AI modullari (`client/proctoring/`)

Barcha modullar bitta qoidaga bo'ysunadi: **ular xulosa
chiqarmaydi**. Detektor "telefon, ishonch 0.94" deydi; "telefon
ishlatildi" degan hodisa temporal qatlamda tug'iladi va siyosat
chegaralariga tayanadi.

| Modul | Nima beradi | Model |
|---|---|---|
| `identity/` | yuzlar, embedding, 106 nuqta | `buffalo_l` (bundle'da) |
| `detection/` | obyekt ramkalari | `yolo/*.onnx` (yo'q) |
| `pose/` | 17 kalit nuqta | `pose/*.onnx` (yo'q) |
| `gaze/` | yaw/pitch/roll, ko'z ochiqligi | modelsiz (solvePnP) |
| `tracking/` | `track_id` | modelsiz (sof numpy) |

**Yangi bog'liqlik QO'SHILMADI.** Hammasi `numpy`, `cv2` va
`onnxruntime` ustida — ular allaqachon `requirements.txt` da.
MediaPipe rad etildi (ikkinchi runtime, GPU'ni bo'lishmaydi,
PyInstaller bilan konflikt), `scipy`/`lap`/`torch` ham (ByteTrack
~200 qator numpy bilan yozildi — `face_engine.py` da torch aynan
shu sababdan olib tashlangan).

**`InferenceEngine` bitta implementatsiya.** Rejada
`CudaInferenceEngine`/`CpuInferenceEngine` bor edi; amalda ular
faqat provayderlar ro'yxati bilan farq qilardi va soxta
abstraksiya bo'lardi. Provayderlar — parametr, qaror
`hardware/performance_profile.py` da.

**Model yo'q bo'lsa modul jimgina o'chadi** (`ModelNotFound`),
dastur to'xtamaydi. Tafsilot: `client/models/README.md`.

#### Bosh holati: ishoralar EMPIRIK aniqlangan

`gaze/head_pose.py` standart 3D model nuqtalari to'plamini
ishlatadi va unda **+Y yuqoriga**, rasm koordinatalarida esa
pastga. Natijada solvePnP frontal yuz uchun `pitch ≈ ±180`
qaytaradi va yaw teskari ishorada chiqadi. Ikkalasi ham JIMGINA
buzilish berardi:

* kalibrlash ayirmasi: frontal (+180) va biroz yuqoriga (−179)
  orasidagi og'ish **359 gradus** bo'lib chiqardi;
* `|pitch| > 20 → pastga qaradi` qoidasi frontal yuzda HAR DOIM
  rost bo'lardi.

Konventsiya bitta funksiyada (`_apply_convention`) va u sintetik
proyeksiya bilan o'lchab aniqlangan:

    yaw   > 0  -> KADRNING o'ng tomoniga qaradi (proktor ko'zi bilan)
    pitch < 0  -> pastga qaradi
    frontal    -> ikkalasi ~0

Ishorani o'zgartirish kerak bo'lsa — faqat o'sha funksiya.

**Nigoh MUTLAQ burchakka tayanmaydi.** Kamera kalibrlanmagan
(fokus kadr kengligidan taxmin qilinadi, xato ±10–15 gradus) va
kamera monitor tepasida/yonida turishi mumkin. Shuning uchun
sessiya boshida ~3 soniya davomida boshlang'ich holat o'lchanadi
va u NOL deb qabul qilinadi; barcha chegaralar shu noldan
og'ishga qo'llanadi. Talabgor kalibrlash paytida qimirlab tursa
(tarqoqlik > 12 gradus), kalibrlash BEKOR qilinadi — noto'g'ri
nolga tayanish mutlaq qiymatdan battar.

### Dalil (evidence) — skrinshotdan ALOHIDA

Skrinshot test platformasi BUYRUG'I bilan (javob belgilanganda) va u
"talabgor qaysi ekranda qanday javob berdi" degan manzarani beradi. Dalil esa HODISAGA bog'langan
va "aynan nima ko'rindi" degan savolga javob beradi — u proktor
ekranida hodisa yonida turadi va apellyatsiyada asosiy hujjat
bo'ladi. Shuning uchun ular alohida model, alohida endpoint va
alohida retention'ga ega.

| | Skrinshot | Dalil | FaceID kadri |
|---|---|---|---|
| Model | `ProctoringScreenshot` | `EvidenceArtifact` | `FaceVerificationLog` |
| Yuklash | `client/screenshots/upload/` | `client/evidence/upload/` | `face/verify/`, `face/attempt/`, `face/periodic/` |
| Tur | rasm | rasm (`frame`) yoki video (`clip`) | rasm |
| Sabab | taymer | tasdiqlangan hodisa | yuz tekshiruvi |
| Berish | `screenshots/{id}/file/` | `evidence/{id}/file/` (`evidence.view`) | `face-logs/{id}/file/` (`evidence.view`) |
| Tozalash | `purge_expired_screenshots` | `purge_expired_evidence` | `purge_expired_face_images` (faqat FAYL) |

**KAMERA KLIPI FAQAT AI KUZATUV YOQILGANDA YOZILADI.** Klip —
hodisa dalili: u temporal qatlam tasdiqlagan hodisadan (yuz yo'q,
ikkinchi odam, nigoh chetda, telefon...) va `evidence_min_severity`
dan past bo'lmagan jiddiylikda tug'iladi. Imtihonga biriktirilgan
sozlamada `ProctoringPolicy.is_enabled=False` bo'lsa, client
`AI kuzatuv siyosatda o'chirilgan` deb yozadi, `evidence.enabled`
ham `False` bo'ladi va birorta klip paydo bo'lmaydi — bu nosozlik
emas. Uzluksiz kamera videosi alohida fayl sifatida YO'Q: kamera
tasviri ekran yozuvining PiP'ida.

**KLIP ENDI SERVERGA YUKLANMAYDI** — u mashinada qoladi va
serverga manzili boradi (`LocalRecording`, yuqoridagi "Ekran
yozuvi va mashinada qoladigan dalil" bo'limi). Yuqoridagi jadval
KADR uchun kuchda qoladi: u ~150 KB va proktorga hodisa yonida,
real vaqtda kerak. `EvidenceArtifact.Kind.CLIP` olib
tashlanmagan: obyekt storage'li o'rnatishda klipni yuklash
mantiqiy bo'lib qolaveradi.

Uchinchi ustun storage'ning `faceid/` shoxida yashaydi va uning
qatori fayldan UZOQROQ yashaydi: ball, chegara va vaqt bayonnomaning
qismi (batafsil: "FaceID: solishtirish CLIENTDA" bo'limi).

**KIRISH TEKSHIRUVIDA IKKITA RASM SAQLANADI** — jonli kadr
(`image_path`) va hujjat rasmi (`reference_image_path`). Ikkinchisi
ilgari hech qayerda saqlanmasdi: platformadan kelib, client
xotirasida solishtirishga ishlatilar va yo'qolardi. Panelda esa
ballning O'ZI hech narsani isbotlamaydi — apellyatsiyada "47 ball"
degan yozuv emas, hujjatdagi odam va kameradagi odam YONMA-YON
kerak bo'ladi. Shuning uchun client kirish tekshiruvida ikkala
kadrni ham yuboradi (muvaffaqiyatli ham, muvaffaqiyatsiz ham) va
panel ularni birga ko'rsatadi (`face-logs/{id}/file/?kind=reference`).

TEST DAVOMIDA hujjat rasmi YUBORILMAYDI va bu ataylab: u yerda
etalon pasport rasmi emas, kirishda tasdiqlangan kadr — uni har
tekshiruvda qayta saqlash bir xil rasmni yuzlab marta diskka
yozardi. Ikkala fayl bir vaqtda tozalanadi: bittasini qoldirish
yarim dalil berardi.

**MAHALLIY ARXIV** (`client/services/local_archive.py`) — serverga
yuborishdan MUSTAQIL ikkinchi nusxa. Skrinshot ham, dalil ham
yuborilishidan oldin mashinaning eng bo'sh diskiga yoziladi:
`<disk>/ProctoringArchive/<test turi>/<test>/<sana>/` va fayl nomi
`<sessiya>_<jshshir>_<mac>_<tartib>.<ext>`. Sabab ikkita: yuborish
navbati RAM'da (dastur yopilsa u bilan ketadi) va tekshiruv
komissiyasi ko'pincha mashinaning O'ZIDAN dalil so'raydi. Yozish
xatosi HECH QACHON oqimni to'xtatmaydi — arxiv qulaylik, kuzatuvning
sharti emas. Dev mashinasida `LOCAL_ARCHIVE_ENABLED=false`.

**Storage QAYTA ISHLATILADI** (`common/screenshot_storage.py`),
dalillar o'sha ildizning `evidence/` shoxida. Ikkinchi storage
yozish `X-Accel-Redirect` konfiguratsiyasini, yo'l tekshiruvini va
bo'sh katalog tozalashni ikki marta yozish degani bo'lardi. Fayl
tizimi yo'lining barcha qoidalari (nisbiy yo'l, avval fayl keyin
qator, avval fayl keyin o'chirish) shu yerda ham amal qiladi.

**Video tekshiruvi rasmdan ZAIFROQ va buni bilish kerak.** Rasm
Pillow bilan to'liq ochiladi (dekompressiya bombasi ham shu yerda
ushlanadi), videoni esa ochib ko'rib bo'lmaydi — buning uchun
ffmpeg kerak va u serverda yo'q. Video uchun uch qavat: sehrli
baytlar (MP4 `ftyp`, WebM `1A 45 DF A3`), hajm chegarasi va nginx
`internal` location. MP4 sarlavhasi bilan boshlanadigan ixtiyoriy
fayl o'tadi, lekin u `video/mp4` sifatida beriladi va brauzer uni
skript sifatida bajarmaydi.

**Kadr va klip ALOHIDA muddat bilan saqlanadi**
(`evidence_clip_retention_days` / `evidence_frame_retention_days`).
Klip kadrdan ~10 barobar katta: 500 mashinali bino kuniga ~5 GB
klip yig'adi. Bitta muddat diskni klip hisobiga to'ldirib,
kadrlarni ham birga olib ketardi. Muddat YUKLASH PAYTIDA
hisoblanadi va qatorga yoziladi — tozalash vazifasi siyosatni
qayta o'qimasligi kerak, chunki u sessiya tugagach o'zgargan
bo'lishi mumkin.

**Client tomonda dalil DISKKA yoziladi** va bu `screen_capture.py`
dagi "diskka yozmaymiz" qoidasidan ongli istisno. Skrinshot
talabgorning ekrani va u mashinada iz qoldirmasligi kerak; klip esa
hodisaga bog'langan va uni qayta yig'ib bo'lmaydi. Tarmoq
uzilganda klipni RAM'da ushlash 4 GB li mashinani o'ldirardi,
shuning uchun u vaqtinchalik faylga yoziladi va yuborilgach
DARHOL o'chiriladi (`proctoring/evidence/recorder.py`).

**Halqa bufer hodisadan OLDINGI lahzalarni saqlaydi.** Temporal
qatlam hodisani 5 kadr va ~1.2 soniyadan keyin ochadi — eng
qimmatli harakat (telefonni chiqarish) o'shanda allaqachon o'tib
ketgan bo'ladi. Bufer qat'iy cheklangan: kadrlar 640 px ga
kichraytiriladi va sekundiga `capture_fps` tasi saqlanadi
(720p da 5 soniya ~79 MB bo'lardi, shu ikki chora bilan ~20 MB).

#### Dalil kadridagi belgilar (`boxes`)

**KADR TOZA, BELGI USTIDA.** JPEG'ga hech narsa chizilmaydi; nima
topilgani `EvidenceArtifact.boxes` da keladi va panel uni rasm USTIDA
chizadi (`components/session/EvidenceCard.jsx`, yashirsa bo'ladi).
Apellyatsiyada dalil — asl kadr; unga kuydirilgan ramka tasvirning bir
qismini yopardi va "rasm o'zgartirilgan" degan e'tirozga yo'l ochardi.

**KOORDINATA KADRGA NISBATAN (0..1)**, piksel emas. Ramka detektor
kadrida hisoblanadi (IP kamerada 2688x1520), dalil kadri esa halqa
buferdan, 640 px ga kichraytirilgan. Ilgari piksel yuborilardi va
panelda ramkani to'g'ri joyga qo'yishning imkoni yo'q edi. Shakl:

    {"label": "Telefon", "kind": "object", "box": [x1, y1, x2, y2], "conf": 0.93}

| `kind` | Rang | Qayerdan |
|---|---|---|
| `object` | qizil | `object_detected` — nom serverdagi klassdan ("Telefon") |
| `person` | sariq | `second_person`, `multiple_faces`, `hand_below_desk` |
| `face` | ko'k | `face_mismatch`, `gaze_away`, `student_left_frame`... |
| `student` | yashil | talabgorning o'zi — XAVF EMAS, kontekst |

Belgilar `behavior_analyzer._mark` da yasaladi, hodisa payload'ida
`marks` bo'lib dalil yozuvchisiga yetadi (`recorder._boxes_of`) va
SERVER HODISASIGA KETMAYDI (`BehaviorEvent.as_payload` olib tashlaydi).
Server ularni qat'iy tozalaydi (`client_serializers._clean_mark`):
ma'lum kalitlar, 0..1 ga siqish, nom 48 belgi; yaroqsiz belgi faqat
o'zini yo'qotadi, dalilni emas. Eski piksel formati ham shu yerda
tushib qoladi va panel uni CHIZMAYDI — noto'g'ri joydagi ramka
ramkasizlikdan yomonroq.

Sarlavha topilgan narsani aytadi: «Taqiqlangan obyekt · Telefon»
(`evidenceTitle`). SVG `viewBox` kadr o'lchamida va
`preserveAspectRatio="xMidYMid meet"` — `<img objectFit: contain>`
bilan AYNAN bir xil joylashuv, ya'ni ramka har qanday karta o'lchamida
rasmga yopishib turadi.

Yashil (`student`) belgi proktorga qaysi odam talabgor deb
olinganini ko'rsatadi — aynan u "eng baland ramka" qoidasining xatosini
ochib bergan edi (endi o'rindiq kalibrlashi, "AI proktorlik" bo'limi).

### Ekran yozuvi va mashinada qoladigan dalil

**UCH OQIM, IKKI MANZIL.** Test sahifasi ochilgandan imtihon
yakunigacha uchta dalil yig'iladi va ular BIR XIL joyga bormaydi:

| | Skrinshot | Kamera klipi | Ekran yozuvi |
|---|---|---|---|
| Qayerda | mashina + **server** (`is_screenshot_upload`) | faqat mashina | faqat mashina |
| Serverga | fayl (~60 KB) | **manzil** | **manzil** |
| Hajm | ~150 KB / javob | ~1-3 MB / hodisa | ~0.55-0.7 GB / 3 soat |
| Model | `ProctoringScreenshot` | `LocalRecording` | `LocalRecording` |

Chegara ko'lamda: 500 mashinali bino kuniga ~5 GB klip va ~500 GB
ekran yozuvi yig'adi — bu hech qanday kanalga ham, server diskiga
ham sig'maydi. Skrinshot esa qoladi: u kichik va proktorga imtihon
DAVOMIDA, real vaqtda kerak. Klip va yozuv apellyatsiya hujjati —
ular real vaqtda deyarli hech qachon ko'rilmaydi.

**`client/recordings/` FAYL QABUL QILMAYDI.** Endpoint faqat
manzilni, hajmni va davomiylikni yozadi (`LocalRecording`).
Takroriy so'rov yangilaydi, ikkinchi qator yaratmaydi: client
tarmoq xatosida qayta uradi va panelda bu "ikkita video bor"
bo'lib ko'rinardi.

**YO'L ABSOLYUT** va bu `ProctoringScreenshot.file_path` /
`EvidenceArtifact.file_path` dagi "faqat nisbiy yo'l" qoidasidan
ongli istisno: u yerda ildiz BIZNIKI va bitta, bu yerda esa fayl
boshqa mashinada yotibdi va uning ildizi har mashinada boshqacha
(eng bo'sh disk tanlanadi). Nisbiy yo'l "qayerdan qidiray?" degan
savolni javobsiz qoldirardi.

#### Mahalliy arxiv — sessiya papkasi

```
<ildiz>/<test turi>/<test>/<sana>/<sessiya>_<jshshir>_<mac>/
    shot_00001.jpg      skrinshot (serverga ham ketadi)
    evidence_00001.jpg  dalil kadri (serverga ham ketadi)
    clip_00001.mp4      kamera klipi (faqat shu yerda)
    screen.mp4          ekran yozuvi (faqat shu yerda)
```

Ilgari fayllar sana papkasida yonma-yon yotardi va nom bilan
ajratilardi — kuniga o'nlab talabgorda papkada minglab fayl
to'planardi. Endi bitta imtihonning hamma dalili bitta papkada:
komissiyaga uni butunlay berish kifoya.

**DISK ENG BO'SHI, LEKIN FAQAT QAT'IY DISK** (`GetDriveTypeW`).
Olinadigan va tarmoq disklari chetlab o'tiladi: ularda odatda eng
ko'p bo'sh joy bo'ladi, ya'ni avtomatik tanlov aynan fleshkani
tanlardi va talabgorlar ekranining nusxasi mashinadan chiqib
ketardi. `LOCAL_ARCHIVE_ROOT` berilsa avtomatik tanlov umuman
ishlamaydi.

**MUDDAT 30 KUN** (`LOCAL_ARCHIVE_RETENTION_DAYS`), tozalash dastur
ISHGA TUSHGANDA. Imtihon davomida diskni kezish skrinshot oqimi va
uzluksiz yozuv bilan bitta diskda raqobatlashardi. O'chirish SANA
papkasi bo'yicha: `os.stat` ni har faylda chaqirish o'n minglab
chaqiruv, papka nomidagi sana esa tayyor javob.

#### Skrinshotdagi kamera tasmasi (`client/services/camera_overlay.py`)

Proktor imtihon DAVOMIDA faqat skrinshotni ko'radi (yozuv mashinada
qoladi), shuning uchun "o'sha paytda kompyuter oldida KIM edi?"
degan savolga skrinshotning o'zi javob beradi: ishlab turgan
kameraning kadri rasmga qo'shiladi.

**KAMERALAR EKRAN USTIGA EMAS, OSTIGA QO'SHILGAN TASMAGA chiziladi.**
Birinchi variant ekran ustiga chizardi va sinovda javob
variantlarining ikkitasini butunlay yopdi — test platformasida
pastki qism eng zich joy. Tasma bilan ekran tasviri bir piksel ham
yopilmaydi; narxi — rasm ~24% balandroq, JPEG ~24% og'irroq.

| Rol | Burchak | Qachon chiziladi |
|---|---|---|
| `primary` (yuz) | pastki O'NG | kamera ochiq bo'lsa (har doim) |
| `secondary` (xona) | pastki CHAP | faqat AI kuzatuv uni ochgan bo'lsa |

O'ng burchak ekran yozuvidagi PiP bilan bir xil. Tasma o'rtasida
olish vaqti turadi — paneldan yuklab olingan rasm kontekstsiz ham
o'z vaqtini aytadi.

Qoidalar:

* **ESKIRGAN KADR QO'YILMAYDI** (`CAMERA_FRAME_MAX_AGE_S`, 3 s).
  Kamera ochiq, lekin kadr eski bo'lsa ramka "Kamera kadri yo'q"
  yozuvi bilan chiziladi: o'tgan daqiqadagi odam hozirgi ekran
  bilan birga dalil bo'lib ketmasligi kerak, kadr yo'qligi esa
  o'zi dalil.
* **ROL ALMASHTIRILMAYDI** (`ProctoringSupervisor.camera_slots`).
  `latest_frame` ning "istalgan rol" zaxirasi bu yerda noto'g'ri
  bo'lardi — yuz kadri xona burchagiga tushib qolardi.
* Kamera kadri UI thread'ida, ekran bilan BIR LAHZADA olinadi —
  kodlash paytidagi kadr boshqa odamni ko'rsatishi mumkin.
* Tasmani chizib bo'lmasa skrinshot TASMASIZ ketadi: ekran — asosiy
  dalil. `Setting.is_screenshot_camera_overlay=False` uni butunlay o'chiradi.

#### Ekran yozuvi (`client/services/screen_recorder.py`)

**5 FPS, 1600 px, BUTUN ISH BITTA FON THREAD'IDA** (`_CaptureThread`).
Ilgari 1 FPS edi va yozuv "qotib-qotib" ko'rinardi (har soniyada
bitta kadr). Chastotani oshirish uchun ekran nusxasini UI thread'idan
chiqarish SHART bo'ldi: Qt `grabWindow` faqat UI thread'da ishlaydi
va bu mashinada ~27 ms (eng ko'pi 55 ms) — 5 FPS da har soniyaning
~14% ida WebView tutilardi. Endi ekran GDI `BitBlt` bilan olinadi
(`ScreenGrabber`, `ctypes`, yangi bog'liqliksiz): u istalgan
thread'dan ishlaydi va DWM kompozitsiya qilgan tasvirni beradi.
O'lchangan: 20 s yozuv davomida UI siklidagi eng katta uzilish
19.5 ms (16 ms taymerda).

KODEK `mp4v` va u O'LCHAB tanlangan (`screen_recorder` docstring'idagi
jadval): Windows H.264 (MSMF) OpenCV orqali bitreyt sozlamasini
QABUL QILMAYDI va 3 soatga ~6 GB yozadi; `openh264` DLL tarqatishni
talab qiladi. `mp4v` 5 FPS da 1 FPS dagidan TINIQROQ ham (matn PSNR
39.8 -> 48 dB): ekran o'zgarmagan kadrlarda kodlovchi tasvirni
aniqlashtirib boradi.

**SICHQONCHA KURSORI CHIZILADI** (`DrawIconEx`): ekran nusxasi uni
o'zi olmaydi, usiz esa "qaysi javob bosildi" degan savolga yozuv
javob bermasdi. Faqat ASOSIY monitor yoziladi — kursor ikkinchi
monitorda bo'lsa kadrda ko'rinmaydi (kiosk rejimida u baribir
o'chirilgan).

**VAQT JADVALI QAT'IY.** Kadrlar monoton soat bo'yicha yoziladi:
kadr kechiksa oldingisi TAKRORLANADI (`dropped` da hisoblanadi) —
aks holda 3 soatlik imtihon qisqaroq videoga siqilib, "11:42 da nima
bo'lgan?" degan savolga yozuvdagi vaqt noto'g'ri javob berardi.
Bir martada ko'pi bilan 10 s to'ldiriladi (`_MAX_CATCHUP_SECONDS`):
mashina uxlab qolgandan keyingi daqiqalik bo'shliqni bir zumda
minglab kadr bilan yozish diskni band qilardi.

**PiP O'NG YUQORI BURCHAKDA VA KICHIK** (`Setting.screen_record_pip_percent`,
12%: 1600 px yozuvda ~192x144). Ilgari o'ng pastda va 20% edi — test
platformasining eng zich qismini (javob variantlari, "Keyingi"
tugmasi) yopardi, ya'ni yozuvdagi dalilning aynan shu qismi
ko'rinmasdi.

**KAMERA KADRI YOZUVGA QO'SHILADI (PiP), EKRANGA EMAS.** Yozuvda
ekrandagi jarayon ko'rinadi, lekin "o'sha paytda kompyuter oldida
KIM o'tirgan edi?" degan savol ochiq qolardi. Ekranga chizilgan
element esa yozuvga ham tushardi (o'z-o'zini suratga olish) va
talabgorga kuzatuv qayerga qaratilganini ko'rsatib qo'yardi.
Kadr ishlab turgan manbadan olinadi: AI kuzatuv yoqilgan bo'lsa
supervisor'dan, aks holda FaceID ishchisidan — ikkalasi ham
operator tekshiruv sahifasida ko'rgan kameraning O'ZI.

**NAVBAT YO'Q**: olish, miqyoslash, PiP va kodlash bitta thread'da
ketma-ket (~45 ms, 5 FPS da 200 ms byudjet). Navbat RAM'da siqilmagan
kadrlarni to'plardi (1600 px kadr ~4 MB) va imtihon mashinasi
ko'pincha 4 GB; orqada qolish esa vaqt jadvali bilan hal bo'ladi.

**KAMERA PROVAYDERI FON THREAD'IDAN CHAQIRILADI**
(`exam_webview_page._recording_frame`): u faqat O'QIYDI — sahifadagi
oxirgi kadr havolasi yoki supervisor oqimi (mutex ostida). Unga UI
vidjetlariga murojaat qo'shmang.

**QORA KADR OGOHLANTIRISH BERADI.** GDI ekran nusxasi jarayonda
ko'rinadigan oyna bo'lmaguncha va qulflangan seansda qop-qora
qaytaradi. Yozuv to'xtatilmaydi (ekran keyinroq paydo bo'lishi
mumkin), lekin log'da iz qoladi: aks holda 360 MB li qop-qora
fayl apellyatsiya kunida ochilardi.

#### Dalil yig'ish OYNASI

Yozuv, skrinshot va klip **testga ajratilgan vaqt** davomida
yig'iladi (`Candidate.duration_minutes`). Vaqt tugagach
`_stop_capture()` ishlaydi va uchalasi ham to'xtaydi —
**kuzatuvning o'zi esa davom etadi**: heartbeat, hodisalar va
davriy FaceID. Sessiya hali ochiq va proktor uni ko'rib turishi
kerak; to'xtaydigan narsa faqat dalil yig'ish. Aks holda talabgor
javoblarini topshirgach ekranda turgan yakuniy sahifa soatlab
yozilardi — soatiga ~120 MB.

Uch nuqtadan kelinadi va tartib kafolatlanmagan, shuning uchun
`_stop_capture()` takroriy chaqiruvga chidamli: vaqt tugadi,
talabgor "Imtihonni yakunlash" ni bosdi, sahifa yopildi.

**VAQT KELMAGAN BO'LSA CHEKLOV QO'YILMAYDI.** `duration_time`
platformada keyin qo'shilgan maydon va u bo'lmasligi mumkin
(`CLAUDE.md` dagi "F.I.SH. VA TEST VAQTI" bo'limi) — ixtiyoriy
raqamga bog'lash yozuvni imtihon o'rtasida jimgina to'xtatardi.
Proktor qo'shimcha vaqt bersa oyna ham UZAYADI: aks holda aynan
"nega qo'shimcha vaqt berildi?" degan savol tug'ilgan oraliq
yozuvsiz qolardi.

**YOZUV MANZILI `session/finish/` DAN OLDIN KETADI** va u bilan
BITTA fon chaqiruvida (`exam_webview_page.finish` →
`_finish_with_recording`). `client/recordings/` sessiya tokenini
talab qiladi va u yakunda bekor bo'ladi: ilgari qayd `stop()` da,
yakundan KEYIN yuborilar va 404 (`session_not_found`) olardi —
fayl mashinada qolar, panelda esa «Mashinadagi yozuvlar» doim bo'sh
turardi. Ikki alohida fon chaqiruvi ham yetmaydi: tartibi
kafolatlanmagan. Qayd xatosi yakunni TO'SMAYDI.

**CHETLASHTIRILGAN SESSIYA — TOKENSIZ YO'L.** Proktor
chetlashtirganda yoki server sessiyani yopganda token client
bilmasdan bekor bo'ladi, ekran yozuvi esa aynan o'shanda
yakunlanadi. Shuning uchun client har bir qaydda sessiyaning
`public_id` sini (`session_id`) ham yuboradi va server tokensiz
so'rovni UCH shart bilan qabul qiladi
(`recordings.session_without_token`):

* xodim JWT'si va `client.operate` ruxsati;
* sessiya AYNAN SHU qurilmada ochilgan — boshqa mashina birovning
  sessiyasiga yozuv qo'sha olmaydi;
* yakunlangan sessiyada — yakundan keyin
  `RECORDING_LATE_REGISTER_SECONDS` (standart 30 daqiqa) ichida.
  Yakunlanmagan sessiya (operator imtihon o'rtasida hisobdan
  chiqdi) cheklanmaydi.

Token ham, `session_id` ham kelsa, ular MOS bo'lishi shart — aks
holda tirik token bilan boshqa sessiyaga yozuv qo'shish mumkin
bo'lardi. Barcha rad javoblari bitta `session_not_found`: "bor,
lekin boshqa qurilmaniki" degan javob identifikatorlarni sanab
chiqishga yo'l ochardi.

**Bu endpointda token tekshiruvi YUMSHOQ**
(`LenientSessionTokenAuthentication`): client chetlashtirishdan
xabar topguncha so'rov ESKI token bilan ketadi, qat'iy
tekshiruv esa uni view'ga yetkazmasdan `session_not_found` bilan
qaytarardi va tokensiz yo'l hech qachon ishlamasdi. Begona
qurilmaning tokeni (`SessionForbidden`) avvalgidek rad etiladi.
Bu yumshoqlikni boshqa endpointlarga KO'CHIRMANG: ular uchun
yakunlangan token — yopiq eshik.

`session_id` sessiya holati tozalanishidan OLDIN, UI thread'ida
olinadi (`_recording_fields`): fon so'rovi ketguncha
`AppState.session` allaqachon `None` bo'lishi mumkin. Kamera
klipi ham xuddi shunday (`ProctoringSupervisor.start(session_id=)`):
navbatdagi klip chetlashtirishdan keyin yetib kelishi mumkin.

**DASTURDAN CHIQISH OCHIQ IMTIHONNI YAKUNLAYDI**
(`ExamWebViewPage.finish_on_exit`, `MainWindow._shutdown`). Ilgari
chiqish (Ctrl+Q + parol, oyna yopilishi, Windows o'chishi) faqat
mahalliy tozalash qilardi — token unutilar, sessiya esa serverda
`in_progress` bo'lib qolar va uni `close_stale_sessions` ~15 daqiqadan
keyin yig'ardi: talabgor boshqa mashinada qayta kira olmasdi, proktor
esa bo'sh mashinani "faol" deb ko'rardi.

* "Ochiq imtihon" — `_open_platform` dan (talabgor testni ko'rdi)
  yakun/uzilishgacha (`_exam_open`).
* Yo'l "Imtihonni yakunlash" bilan BIR XIL (`_finish_with_recording`:
  avval yozuv manzili, keyin yakun), lekin har so'rov QISQA timeout
  bilan (`_EXIT_REQUEST_TIMEOUT_S`, 4 s; `ApiClient.request(timeout=)`)
  va kutish chegaralangan (10 s): oyna allaqachon yashirilgan, server
  javob bermasa sessiyani baribir `close_stale_sessions` yopadi.
* Chiqish dialogi imtihon sahifasida oqibatni OLDINDAN aytadi
  (`ExitDialog(warning=...)`).
* `aboutToQuit` ham ulangan: OS seansi yakunlanganda (o'chirish,
  hisobdan chiqish) Qt `closeEvent` ni kafolatlamaydi, kioskda esa u
  baribir rad etilardi. Bu BEST-EFFORT — Windows jarayonni bir necha
  soniyada o'ldiradi.
* Qamrab OLINMAYDI: jarayon o'ldirilishi / quvvat uzilishi (serverda
  `close_stale_sessions`) va imtihon o'rtasida JWT muddati tugashi
  (`session/finish/` xodim JWT'sini talab qiladi).

### Apparat qachon va qayerga xabar qilinadi

Apparat uchun ALOHIDA endpoint YO'Q va bo'lmasligi ham kerak:
u har handshake'da baribir yuboriladi, ikkinchi endpoint esa
faqat ikkinchi autentifikatsiya yuzasini ochardi.

Aniqlash BLOKLAYDI (`nvidia-smi` + `onnxruntime` provayderlari,
~0.2–2 s), shuning uchun u dastur ishga tushganda fon thread'ida
boshlanadi (`hardware_probe.prefetch()`, naqsh
`PublicIpResolver` dan) va natija BIR MARTA hisoblanadi — apparat
imtihon o'rtasida o'zgarmaydi. Handshake uni KUTMAYDI: tayyor
bo'lmasa maydonlar bo'sh ketadi, server esa bo'sh qiymatga
tegmaydi va keyingi handshake yozadi.

Qiymatlar ikki joyga ajratilgan va bu ataylab:

| Nima | Qayerda | Nega |
|---|---|---|
| `gpu_name`, `performance_profile` | `DeviceToken` ustunlari | qidiriladi/filtrlanadi: "qaysi mashinalar CPU rejimida?" |
| CPU, RAM, VRAM, provayderlar, `gpu_warning` | `Computer.info_pc` (JSON) | tafsilot — faqat bitta mashinaga qaralganda kerak |

Handshake'dagi profil `override` SIZ tanlanadi: u login paytida,
imtihon tanlashdan oldin ketadi va o'sha paytda
`gpu_profile_override` hali ma'lum emas. Ya'ni u "mashina nima
ko'taradi" degan savolga javob beradi; "kuzatuv qaysi profilda
ishladi" degan savolga esa `ExamSession.ai_profile` javob beradi
va u yerda override ham hisobga olingan.

**Profillar ro'yxati uch joyda mos bo'lishi shart**:
`client/proctoring/hardware/performance_profile.py:PROFILES`,
`controls.ProctoringPolicy.GpuProfile` va
`HandshakeSerializer.performance_profile` (+ frontendda
`AI_PROFILE_LABEL`). Client'dagi `minimal` profil ro'yxatdan
tushib qolsa, xato eng yomon joyda chiqadi — aynan eng zaif
mashinaning handshake'i 400 oladi.

### GPU: model QAYERDA yuklanadi

**"GPU BOR" va "GPU ISHLATILADI" — ikki boshqa fakt.**
`onnxruntime.get_available_providers()` ro'yxatida
`CUDAExecutionProvider` turgani u ISHLAYDI degani emas: provayder
alohida DLL va u CUDA kutubxonalariga bog'liq (`cudart`, `cublas`,
`cublasLt`, `cufft`, `cudnn`). Ular topilmasa ONNX Runtime log'ga
bitta qator yozib JIMGINA CPU'ga tushadi — dastur ishlayveradi,
faqat bir necha barobar sekin, va buni hech kim sezmaydi.

Aynan shu holat loyihaning ishlab chiqish mashinasida bor edi:
GTX 1660 SUPER, drayver joyida, `onnxruntime-gpu` o'rnatilgan —
lekin paketning CUDA 13 uchun yig'ilgan nashri, mashinada esa
CUDA 12 kutubxonalari. InsightFace CPU'da yuklanardi.

`proctoring/hardware/cuda_runtime.py` ikki ishni qiladi:

* **kutubxonalarni TOPADI va jarayonga yuklaydi.** Ular `pip`
  paketlari ichida yotadi (`nvidia-*`, `torch/lib`) va Windows
  ularni o'z-o'zidan topmaydi. `os.add_dll_directory` YETARLI
  EMAS — ONNX Runtime provayder DLL'ini to'liq yo'l bilan
  yuklaydi va uning yashirin importlari boshqa qoidalar bo'yicha
  qidiriladi. Shuning uchun kutubxonalar OLDINDAN, to'liq yo'l
  bilan yuklanadi: jarayonda allaqachon yuklangan modul qayta
  qidirilmaydi;
* **yetishmayotganini AYTADI.** Kerakli DLL ro'yxati qadab
  qo'yilmagan — u provayder DLL'ining O'ZIDAN, PE import
  jadvalidan o'qiladi. Sabab: ro'yxat `onnxruntime` versiyasiga
  qarab o'zgaradi (CUDA 12 → 13 o'tishida hamma nomlar o'zgardi),
  ya'ni qadab qo'yilgan ro'yxat keyingi yangilanishda jimgina
  eskirardi.

**RO'YXAT BITTA JOYDAN.** `FaceEngine.providers()`,
`OnnxEngine.load()` va `gpu_detector._detect_runtime` uchalasi ham
`cuda_runtime.providers()` dan oladi. Bu diagnostika emas:
`select_profile` aynan `cuda_available` ga qarab GPU yoki CPU
profilini tanlaydi va yolg'on "CUDA bor" modellarni GPU
sozlamalari bilan CPU'da ishga tushirardi — eng yomon
kombinatsiya.

**CPU'GA TUSHISH JIMGINA O'TMAYDI**: log'da `ERROR`, ekranda
"Model tayyor — CPU (GPU ishlatilmadi)", handshake'da esa
`Computer.info_pc.gpu_warning` — administrator panelda ko'radi.
`FACE_REQUIRE_GPU=true` uni ochiq xatoga aylantiradi ("Model
yuklanmadi" + sabab); standart `false`, chunki CPU'da kuzatuv
sekin, lekin ishlaydi va butun imtihonni videokarta nosozligi
tufayli to'xtatish bundan battar.

**`onnxruntime-gpu` VERSIYASI CUDA NASHRI BILAN BOG'LIQ** va ular
almashtirilmaydi: `1.22.x` → CUDA 12 + cuDNN 9, `1.24+` → CUDA 13.
Tafsilotlar `client/requirements.txt` dagi izohda.

### Kuzatuv sikli (`client/proctoring/pipeline.py`)

Barcha modullar BITTA thread'da, ketma-ket ishlaydi va kadrlar
BUFERLANMAYDI: har iteratsiyada kameradan eng oxirgi kadr olinadi.
Orqada qolgan pipeline eski kadrlarni qayta ishlashi mumkin emas —
proktorlikda "10 soniya oldingi telefon" haqidagi ogohlantirish
foydasiz.

Har modulning chastotasi IKKI manbadan: siyosat qancha so'ragani
(`policy.fps`) va profil qancha ko'tara olgani
(`PerformanceProfile.limit_fps`). **Pastrog'i yutadi**, `0` esa
har doim o'tadi — siyosat modulni o'chirsa, apparat uni yoqa
olmaydi.

Ikkita kamera bo'lsa ish bo'linadi (`primary` — shaxs va nigoh,
`secondary` — obyekt va poza); bitta bo'lsa hammasi unda ishlaydi.
Dalil buferi HAR ROL uchun alohida: bitta umumiy bufer "telefon
stolda" hodisasiga yuz kadrini biriktirardi.

**`services/proctoring_supervisor.py` — yagona ko'prik.** Pipeline
tarmoqni ham, sessiyani ham bilmaydi (`proctoring/__init__.py`
shartnomasi): u hodisa va dalil TAKLIF qiladi, yuborishni
supervisor hal qiladi. Shu tufayli butun AI qismini tarmoqsiz
sinash mumkin.

**AI kuzatuv KAMERANI EGALLAYDI.** Bitta qurilmani ikki jarayon
ocholmaydi, shuning uchun kuzatuv ishga tushganda FaceID
sahifasidan kelgan eski `CameraWorker` bo'shatiladi va davriy
tekshiruv `pipeline.latest_identity` dan oziqlanadi. Ikkinchi yuz
modelini ochish xotirani ikki barobar yeb, hech qanday yangi
ma'lumot bermasdi.

### Modal dialoglar (`client/ui/dialogs/`)

Qobiq BITTA joyda — `base.py:CardDialog`: ramkasiz oyna, shaffof fon,
yumaloq karta (MD3 "extra large", 28 px), soya va shrift yordamchisi.
To'rtta dialog undan meros oladi (chiqish, siyosat, texnik muammo,
proktor ogohlantirishi) va faqat MAZMUN bilan shug'ullanadi.

**PROKTOR OGOHLANTIRISHI `exec()` BILAN OCHILMAYDI** — faqat
`show()` (`dialogs/warning_dialog.py`). `exec()` hodisa siklini
bloklaydi, ya'ni heartbeat, hodisa buferi va skrinshot taymerlari
ogohlantirish yopilgunga qadar TO'XTAB turardi: aynan talabgor
qoida buzgan paytda nazoratni o'chirish eng noto'g'ri xulq
bo'lardi. Modallik yo'qolmaydi — `ApplicationModal` kiritishni
to'sadi, siklni emas. Ilgari bu chizilgan qoplama edi va u
`QWebEngineView` ustida ko'rinmay qolishi mumkin edi (qoplama —
sahifaning bolasi, brauzer esa o'z oynasini boshqaradi); alohida
OYNA bunday savol qoldirmaydi.

Uchta ko'rinmas qoida shu yerda va ularning hammasi ekranda
ko'rinadigan xatodan kelib chiqqan:

* **SOYA UCHUN JOY** (`SHADOW_MARGIN`). Tashqi layout chetlari nol
  bo'lsa, `QGraphicsDropShadowEffect` chizadigan joy qolmaydi va 56 px
  blur vidjet ramkasiga siqiladi — kartaning atrofida yumshoq soya
  o'rniga QATTIQ CHIZIQ paydo bo'ladi, ekranda u "modalning ramkasi"
  bo'lib ko'rinadi.
* **O'RALADIGAN MATN — `refit()`**. `QLabel` uch qatorga o'ralganda
  ham layout'ga BIR QATORLIK minimal balandlik beradi. Natijada
  dialog o'zini ~30 px past qilib o'lchaydi, Qt esa yetishmagan
  joyni ustundagi maydonlardan "o'g'irlaydi" — xabar satri matn
  maydonining USTIGA chiziladi. `refit()` har bir o'raladigan
  yorliqqa haqiqiy balandlikni (`heightForWidth`) beradi va uni
  MAZMUN O'ZGARGANDA ham chaqirish shart (xabar satri paydo
  bo'lganda).

* **WINDOWS CHIZADIGAN RAMKA** (`strip_native_frame`). Windows 11
  har bir top-level oynaga yupqa ramka va yumaloq burchak chizadi
  — `FramelessWindowHint` ham buni to'xtatmaydi, chunki uni
  kompozitor Qt'dan tashqarida chizadi. Shaffof dialogda natija
  ko'rinadi: karta atrofida, undan soya chetlari qadar (32 px)
  narida yumaloq to'rtburchak paydo bo'ladi va ekranda u
  "modalning ORTIDA ochilgan boshqa oyna" bo'lib ko'rinadi.
  Ilgari ko'zga tashlanmasdi — tashqi chetlar nol bo'lgani uchun
  ramka aynan kartaning chegarasiga tushardi. Yechim `dwmapi`
  atributlari (`DWMWA_BORDER_COLOR = COLOR_NONE`,
  `DWMWA_WINDOW_CORNER_PREFERENCE = DONOTROUND`) va u har
  `showEvent` da qayta qo'yiladi: HWND oyna ko'rsatilganda
  yaratiladi va Qt uni qayta yaratishi mumkin.

Kenglik ham qaror: karta ichidagi eng keng element (uzun tugma
matni, chip qatori) `layout.minimumSize().width()` ni belgilaydi va
u kartadan katta bo'lsa, Qt butun ustunni siqib buzadi. Shuning
uchun dialoglar 520–560 px: tor karta matnni kesardi.

**TIL ALMASHTIRGICH DIALOG ICHIDA YO'Q.** U asosiy oynada suzib
turadi (pastdagi "Klaviatura tili" bo'limi) va modal ochilganda ham
ekranda ko'rinadi; dialogga ikkinchi nusxasini qo'yish bir ekranda
ikkita bir xil tugma degani bo'lardi. BUNING NARXI BOR va uni
bilish kerak: modal `ApplicationModal`, ya'ni pastdagi tugmaga
BOSIB BO'LMAYDI — texnik muammo matnini yozayotganda tilni
almashtirishning yagona yo'li `alt+shift` bo'lib qoladi. U
`lockdown` ro'yxatida bloklangan bo'lsa, bloklashni olib tashlash
kerak (`Setting` → tezkor tugmalar).

`QInputDialog`/`QMessageBox` ISHLATILMAYDI: ular tizim uslubida
chiziladi va kiosk oynasining ustida begona kulrang oyna bo'lib
ko'rinadi. Oxirgi istisno — yakunlash tasdig'i — ham
`dialogs/finish_dialog.py:FinishDialog` ga o'tkazildi: u KIMNING
imtihoni yakunlanayotganini (ism, niqoblangan JSHSHIR, kompyuter,
test davomiyligi) va oqibatni tugmadan OLDIN ko'rsatadi. Xavfsiz amal
(«Testga qaytish») fokusda — Enter imtihonni yakunlamaydi; «Yakunlash»
dasturdagi YAGONA to'ldirilgan qizil tugma (`danger_button_style`).

**IMTIHON SAHIFASIDA XABAR SUZADI** (`indicators.Snackbar`), layoutda
emas. `MessageBar` layoutning qismi va ko'ringanda ostidagi hamma
narsani pastga suradi — imtihon sahifasida esa ostida
`QWebEngineView` turadi: "Muammo qayd etildi" degan xabar butun test
sahifasini pastga surar va xabarni hech kim tozalamagani uchun sahifa
shu holatda qolib ketardi. Snackbar brauzer USTIDA chiziladi, pastki
chap burchakda (o'ng burchak suzuvchi boshqaruv paneliniki) va
jiddiylikka qarab O'ZI yo'qoladi.

### Klaviatura tili — OYNA darajasida

Til almashtirgichi (`ui/widgets/language_bar.py`) sahifalarga
EMAS, `MainWindow` ga qo'yiladi va `QStackedWidget` ustida suzadi.
Sabab oddiy: u oltita sahifada kerak va har biriga alohida
qo'shish oltita nusxa degani bo'lardi — ular albatta ajralib
ketardi (biri boshqa joyda, biri boshqa o'lchamda).

Nima uchun umuman kerak: kiosk rejimida vazifalar paneli
yashiringan va `alt+shift` server bergan ro'yxat bo'yicha
bloklangan bo'lishi mumkin (`services/lockdown.py`) — o'shanda
tilni almashtirishning boshqa yo'li qolmaydi.

**`ActivateKeyboardLayout` YETARLI EMAS**: u faqat chaqiruvchi
thread'ga ta'sir qiladi va Qt oynasining kirish tilini
o'zgartirmaydi. Ishlaydigan yo'l — oynaga
`WM_INPUTLANGCHANGEREQUEST` xabarini yuborish
(`services/keyboard_layout.py`).

**Ekranda FAQAT JORIY til ko'rinadi**, bosilganda keyingisiga
o'tadi. Ro'yxatni to'liq ko'rsatish (segmentli tugma) uch barobar
joy egallardi, holbuki almashtirgich imtihon oynasining ustida
turadi va operator uni kuniga bir-ikki marta bosadi. Aniq tilga
yetish uchun bir necha bosish kerak bo'lishi mumkin, shuning
uchun tooltip KEYINGI tilni ham aytadi.

Vidjet ichki "tanlangan til" holatini SAQLAMAYDI: til tizim
vositalari bilan ham o'zgarishi mumkin, shuning uchun joriy
qiymat sekundiga bir marta OS'dan so'raladi. Ikkita bir xil kodli
til (o'zbek lotin va kirill) yozuv qo'shimchasi bilan ajratiladi.

### Client kamera qatlami (`client/proctoring/camera/`)

`services/` — imtihon oqimining o'zi va u proktorliksiz ham to'liq
ishlaydi; `proctoring/` — qo'shimcha qatlam. Chegara qat'iy: AI
qismi `services/monitoring.py` dagi buferga hodisa qo'yadi va boshqa
hech qayerga yozmaydi.

Ikki daraja: `CameraSource` (sinxron `open`/`read`/`close`, vendorga
xos) va `CameraStream` (thread, FPS o'lchash, uzilish, qayta ulanish —
vendordan mustaqil). Yangi vendor qo'shish = uchta metod yozish.
Qayta ulanish mantig'ini vendor sinfiga ko'chirmang — u albatta
har birida boshqacha bo'lib qoladi.

`rtsp.py` ATAYLAB `hikvision.py` emas: vendor RTSP URL'ga ta'sir
qilmaydi (yo'l, port va transport `Camera` maydonlarida). Vendor
bo'yicha yo'lni taxmin qilish birinchi nostandart proshivkada
buziladi.

**QURILMANI OCHISH — BITTA YO'L** (`camera/factory.py:build_source`).
Uni ikkita chaqiruvchi ishlatadi va ular butunlay boshqa qatlamlarda:
`CameraManager` (tekshiruv sahifasi va kuzatuv oqimi) va
`services/camera_worker.py` (FaceID sahifasi). Ilgari ikkinchisi
kamerani o'zi ochardi (`cv2.VideoCapture(CAMERA_INDEX)`) va oqibati
jimgina edi: operator yuz kamerasini almashtirsa ham FaceID **eski
indeksni** ochar, ya'ni shaxs tekshiruvi stolga qaragan kameradan
ketardi — model esa "yuz topilmadi" deb xabar berardi va sabab
kamera tanlovida ekani hech qayerdan ko'rinmasdi.

Shundan kelib chiqadigan qoida: **sahifa ROLNI so'raydi, indeksni
emas** (`camera_worker.source_for_role(layout, "primary")`). Indeks
operator tanloviga qarab o'zgaradi (`roles.reassign`) va uni
sahifada takrorlash o'sha tanlovni bekor qilardi. Manba `AppState.cameras`
dan quriladi, ya'ni tekshiruv sahifasida ko'rilgan taqsimotning
O'ZI barcha sahifalarda davom etadi — FaceID ham, davriy tekshiruv
ham, AI kuzatuv ham.

`CAMERA_INDEX` va `FRAME_WIDTH`/`FRAME_HEIGHT` — endi ZAXIRA va
UMUMIY qiymatlar: birinchisi taqsimot umuman aniqlanmagan holat
uchun, ikkinchisi esa barcha sahifalarda bir xil bo'lishi uchun
(tekshiruvdan o'tgan rezolyutsiya bilan imtihondagi rezolyutsiya
farq qilsa, `min_width` siyosati aslida hech qachon FaceID kadriga
qo'llanmagan bo'lardi).

**BITTA QURILMA — BITTA EGA.** Windows'da band kamera umuman
ochilmaydi, shuning uchun tartib qat'iy: FaceID ishchisi
kuzatuv oqimi kamerani ochishidan OLDIN bo'shatiladi
(`ProctoringSupervisor.start(before_open=...)`). Teskari tartibda
oqim "kamera band" xatosiga tushib, qayta ulanish kutishida bir
necha soniya yo'qotardi — imtihonning eng boshida. Bo'shatishni
sahifa o'zi hal qila olmaydi: siyosat AI ni o'chirgan bo'lsa kamera
FaceID ishchisida QOLISHI kerak (davriy tekshiruv uni ishlatadi),
va buni faqat supervisor biladi.

**FPS o'lchanadi, e'lon qilinmaydi.** USB kamera 30 FPS deb e'lon
qilib, past yorug'likda 7 FPS beradi — proktorlik uchun butunlay
boshqa sifat va tekshiruv sahifasi aynan shu farqni ko'rsatishi kerak.

**NOM VA INDEKS BITTA MANBADAN** (`camera/dshow.py`). OpenCV
Windows'da `CAP_DSHOW` bilan ishlaydi va indeksni DirectShow'ning
tizim qurilma sanagichidan oladi; client ham o'sha ro'yxatni
o'qiydi (COM, `ctypes` — yangi bog'liqliksiz), ya'ni "0-indeks
qaysi kamera" degan savolga javob TAXMIN emas.

Ilgari nom Windows PnP ro'yxatidan (`Get-PnpDevice -Class Camera`)
olinar va indeksga TARTIB bo'yicha juftlanardi. Ikkala ro'yxat ham
"kameralar" haqida, lekin tartiblari bog'liq emas: ishlab chiqish
mashinasida PnP «GRANDSTREAM GUV3100, Logi C270» beradi,
DirectShow esa «Logi C270, GRANDSTREAM GUV3100» — ya'ni ekranda
ikkala kameraning nomi ALMASHIB chiqardi. Operator esa aynan
nomga qarab "qaysi biri yuzga qaraydi" degan qarorni qabul
qiladi, ya'ni tanlov "nomning ahamiyati yo'q" bo'lib ko'rinardi.
PnP ro'yxati ZAXIRA bo'lib qoladi (COM chaqiruvi ishlamagan
holat uchun) va u yerda eski ehtiyot chorasi ham saqlanadi:
sonlar mos kelmasa nom umuman berilmaydi.

Shu manbadan **`DevicePath`** ham keladi va u qurilmaning
BARQAROR kaliti: `ResolvedCamera.key` avval shunga tayanadi,
indeksga emas. Indeks — SANOQDAGI o'rin: bitta kamera uzilsa
qolganlariniki siljiydi va "Yangilash" dan keyin operator tanlovi
boshqa qurilmaga yopishib qolardi. Qurilmani ochish paytida ham
shu kalit ustun (`factory._resolve_index`) — FaceID sahifasi
taqsimot hisoblangandan bir necha daqiqa keyin ochiladi.

Virtual kamera aniqlash avvalgidek NOMGA tayanadi va u
**xavfsizlik chegarasi emas** — faqat endi virtual qurilma
ro'yxatdan tushib qolmaydi: u PnP qurilmasi emas, DirectShow
filtri.

### Imtihon profili client'ga QACHON yetadi

Uch bosqich va ular ATAYLAB har xil:

| Qachon | Endpoint | Qaysi profil |
|---|---|---|
| Preflight (login'dan oldin) | `client/preflight/` | global — faqat `hotkeys` |
| Login | `client/handshake/` | **global standart** (`get_client_config()`) |
| "Davom etish" bosilganda | `client/exam/config/?exam=` | **imtihonning o'z profili** |

Ikkinchi qatordagi qiymat imtihonnikini BERA OLMAYDI: handshake
imtihon tanlashdan oldin bajariladi va o'sha paytda qaysi imtihon
bo'lishi ma'lum emas.

Uchinchi qadamsiz jimgina nomuvofiqlik qolardi va u eng yomon tarzda
ko'rinardi: server har bir tekshiruvda imtihon profilini ishlatadi
(`verify_periodic_face` → `get_client_config(session.exam)`), client
esa global profilni — ya'ni client 70 ball chegarasini kutib turar,
server esa 85 bilan rad etardi. Farqni faqat log'dan topish mumkin
edi. Tezkor tugmalar ham shu holatda: `MainWindow._on_exam_selected`
imtihon profili kelgach `lockdown.apply` ni QAYTA chaqiradi.

**Mos kelmasa — modal.** `proctoring/policy.py:check_readiness` sof
funksiya: siyosat + kamera taqsimoti → muammolar ro'yxati. Ikki
daraja va ular aralashtirilmaydi:

* **to'siq** — siyosat ochiq talab qilgan narsa yo'q
  (`primary_required`, `secondary_required`, virtual kamera taqiqi).
  Dialog "davom etish" ni umuman **taklif qilmaydi**;
* **ogohlantirish** — holat ideal emas, lekin siyosat talab qilmagan
  (past rezolyutsiya, ikkinchi kamera yo'q, model hali yuklanmagan).
  Qaror operatorniki.

Hamma narsani to'siqqa aylantirish sozlanmagan tizimda butun
imtihonni bloklardi; hammasini ogohlantirishga aylantirish esa
administrator qo'ygan talabni ma'nosiz qilardi.

**Sozlama olinmasa — to'siq EMAS, ogohlantirish.** Muhim qismlarni
server baribir majburlaydi; butun imtihonni o'tkinchi tarmoq xatosi
tufayli to'xtatish bundan battar. Client tomondagi tekshiruv
umuman yagona himoya emas — u operatorga nosozlikni talabgor
kelgunga qadar ko'rsatish uchun.

### Client sozlamalari: `.env` va panel — ikki qatlam

**QOIDA.** `client/.env` da faqat uch toifa qoladi: (1) serverga
ulanishdan OLDIN kerak bo'ladigan, (2) MASHINAGA xos (apparat, disk,
xotira), (3) xavfsizlik chegarasi bo'lgani uchun lokal bo'lishi SHART.
Imtihon/bino bo'yicha o'zgaradigan qolgan hamma narsaning egasi —
admin paneldagi `Setting` profili; u client'ga `_serialize` ->
handshake / `client/exam/config/?exam=` orqali keladi va **SERVER
QIYMATI USTUN**, `.env` faqat ZAXIRA (server javob bermadi yoki kalitni
bilmaydigan eski server).

**BITTA O'QISH NUQTASI** — `client/services/runtime_settings.py`
(`get(config, "face.guide_seconds")`). `SPECS` jadvalida har kalitning
`.env` zaxirasi, birlik o'girishi (soniya -> ms, foiz -> ulush) va
chegarasi turadi. Zaxira o'zgaruvchini (`config.FACE_GUIDE_SECONDS`)
to'g'ridan-to'g'ri O'QIMANG: panelda o'zgartirilgan qiymat o'sha
joyda jimgina e'tiborsiz qoladi — aynan shunday bo'lgan
(`heartbeat_interval`, `is_screen_record` panelda bor edi, client
ularni o'qimasdi). Yangi kalit = `Setting` maydoni + `_serialize` VA
`_default_config` (IKKALASI, testda solishtiriladi) + `SPECS` qatori.

| Sozlama | Qayerda | Nega |
|---|---|---|
| `API_*`, `WS_BASE_URL`, `INVENTORY_CODE` | `.env` | serverdan oldin / mashina |
| `FACE_MODEL_NAME`, `FACE_DET_THRESH` | `.env` | model login bilan PARALLEL, serverdan oldin yuklanadi |
| `MIN_FACE_WIDTH_PX` | `.env` | model (112 px) va kadr o'lchami xususiyati; AI qatlami bilan bir xil bo'lishi shart |
| `FACE_REQUIRE_GPU`, `CUDA_DLL_DIR` | `.env` | apparat |
| `CAMERA_INDEX`, `FRAME_*`, `DETECT_EVERY_NTH_FRAME`, `CAMERA_FRAME_MAX_AGE_S` | `.env` | kamera / CPU |
| `SCREENSHOT_RETRY_QUEUE` | `.env` | RAM (4 GB mashina) |
| `FULLSCREEN`, `KIOSK_MODE`, `*_MONITORS*` | `.env` | Qt'dan oldin, xavfsizlik chegarasi |
| `BLOCKED_HOTKEYS` | `.env` (standart) + `Setting.hotkeys` | pastga qarang |
| `CLOSE_OTHER_APPS*` | `.env` | Qt'dan va serverdan oldin |
| `THREAT_SCAN_ENABLED`/`_ALLOW`, `THREAT_ALLOW_VIRTUAL_HOST` | `.env` | birinchi `sweep()` serverdan oldin; IT agenti va VDI — mashina/infratuzilma |
| `LOCAL_ARCHIVE_*` | `.env` | dev bayrog'i + disk hajmi; tozalash serverdan oldin (serverdagi uzunroq muddat kech kelib, dalil allaqachon o'chgan bo'lardi) |
| `SCREENSHOT_ENABLED` | `.env` | dev VETO (server ustidan) |
| `LOCAL_SERVICE_*` (port 8050, Origin'lar) | `.env` | platforma bilan shartnoma, Qt'dan keyin darhol ochiladi |
| skrinshot serverga ham yuboriladimi | `Setting.is_screenshot_upload` | trafik / server diski — imtihon qarori |
| FaceID oqimi (sanoq, `match_streak`, `fail_streak`, `fail_min_seconds`) | `Setting.faceid_*` | imtihon qoidasi; bir binoda ikki xil qiymat bo'lmasligi kerak |
| davriy FaceID oralig'i | `Setting.faceid_interval` | (avvaldan) |
| ekran yozuvi (yoqish, FPS, kenglik, PiP %) | `Setting.is_screen_record`, `screen_record_*` | disk/sifat kelishuvi — imtihon qarori |
| skrinshot kamera tasmasi (yoqish, %) | `Setting.is_screenshot_camera_overlay`, `screenshot_pip_percent` | trafik kelishuvi |
| tahdid imtihonni to'sadimi | `Setting.is_threat_block_exam` | imtihon siyosati ("Davom etish" da) |
| heartbeat, hodisa batch, oflayn bufer | `Setting` "Tarmoq" | (maydonlar bor edi, endi client o'qiydi) |
| presence oralig'i | server doimiysi `PRESENCE_PING_INTERVAL` | panel maydoni EMAS: TTL >= 2x oraliq, ikkalasi `devices/services.py` da |

`ProctoringPolicy` ga hech narsa ko'chmadi: u "kamera nimani ko'radi
va qachon shubha" savoliga javob beradi, bu yerdagilar esa client
XULQI — `Setting` ning o'z hududi.

**QACHON O'QILADI.** Imtihonga oid qiymatlar IMTIHON PROFILIDAN —
ya'ni "Davom etish" dan keyin: FaceID oqimi `FaceIDPage.start()` da,
tahdid to'sig'i `_finish_check` da, yozuv/tasma/tarmoq test sahifasi
ochilganda (`ScreenRecorder.start(config=)`, `ScreenshotService.start`,
`SessionMonitor.start(config)`). Presence — login'da, handshake'dagi
global profildan (imtihondan tashqarida ishlaydi).

**CHEGARA IKKI JOYDA va bu ataylab**: serverda model validatorlari
(heartbeat <= `HEARTBEAT_TIMEOUT`/2 — `validate_heartbeat_interval`),
clientda `SPECS.minimum/maximum`. Eski server yoki qo'lda tahrirlangan
baza `0` yuborsa, `QTimer.setInterval(0)` clientni band qilmasligi
kerak.

**MAVJUD MAYDONLAR BIRINCHI MARTA KUCHGA KIRDI**
(`controls.0012_client_runtime_settings`): `is_screen_record`
hammasi `True` ga (client ilgari `.env` bo'yicha doim yozardi —
aks holda yangilanish jimgina dalilni o'chirardi), chegaradan
tashqaridagi heartbeat/batch/bufer esa client amalda ishlatgan
qiymatga (30/5/5000) qaytarildi.

**TEZKOR TUGMALAR — ALMASHTIRISH, BO'SH = STANDART.** Dastur
ochilishi bilan (`MainWindow.show_start`, preflight'dan OLDIN)
`.env` `BLOCKED_HOTKEYS` qo'llanadi — ilgari preflight javobi
kelguncha (server javob bermasa — umuman) mashina qulfsiz turardi.
Keyingi har bosqich (preflight, handshake, imtihon profili) TO'LIQ
ro'yxat beradi va `lockdown.resolve_hotkeys` hal qiladi: server
ro'yxati bo'lsa u ALMASHTIRADI, BO'SH bo'lsa standart QOLADI. Bo'sh
ro'yxat "administrator tanlamagan" (profilda tanlanmagan, `Setting`
yo'q yoki eski server) — "hech narsani bloklama" emas: kioskda bu
o'z-o'ziga zid, bunday mashina `.env` da ochiq hal qilinadi
(`KIOSK_MODE=false` yoki bo'sh `BLOCKED_HOTKEYS`). `ctrl+q` hech
qachon bloklanmaydi (`_NEVER_BLOCKED`), `alt+shift` standartda yo'q.

`client/.env.example` shu tartibda: avval lokal qiymatlar, oxirida
«Admin paneldan boshqariladi (bu yerda faqat ZAXIRA)» ro'yxati.

### Client o'rnatuvchisi (`client/installer/`)

**PyInstaller `onedir` + Inno Setup**, ikki nashr: `-Gpu` (~3.2 GB
bundle, setup ~1.5 GB) va `-Cpu` (~0.9 GB / ~0.4 GB). Buyruq va
tafsilotlar — `client/installer/README.md`:

```powershell
cd client
copy installer\env.production.template installer\client.env   # bir marta, manzillarni to'ldiring
powershell -ExecutionPolicy Bypass -File installer\build.ps1 -Gpu   # yoki -Cpu
# natija: dist\installer\ProctoringClientSetup-<versiya>-{gpu,cpu}.exe
ProctoringClientSetup-1.0.0-gpu.exe /VERYSILENT [/INVENTORY_CODE=INV-001]
```

* **SERVER MANZILI O'RNATISHDA SO'RALMAYDI** — u build paytida
  `installer/client.env` dan (git'da yo'q, o'rnatishga xos; `-EnvFile`)
  setup.exe ICHIGA joylanadi. Manzil o'rnatish bo'yicha bitta va
  o'zgarmaydi: uni 500 mashinada qo'lda terish faqat xato manbai edi.
  `build.ps1` uni PyInstaller'dan OLDIN tekshiradi (o'rinbosar, sxema —
  xato; loopback, HTTP, `SSL_VERIFY=0`, o'chiq kiosk — ogohlantirish).
  O'rnatishda faqat INVENTAR KODI so'raladi — ixtiyoriy, server qoidasi
  bilan bir xil tekshiruv (`^[A-Za-z0-9_-]{3,50}$`); fayldagi
  `INVENTORY_CODE` build'da o'rinbosarga almashtiriladi (bitta kod 500
  mashinaga tarqalmasligi uchun).

* **`onefile` EMAS**: u har ishga tushishda 1-3 GB ni `%TEMP%` ga
  ochardi (sekin start, antivirus, qolib ketadigan `_MEI*`). Nuitka
  ham emas: og'ir qism allaqachon native DLL, u faqat build'ni
  murakkablashtirardi.
* **VERSIYA BITTA JOYDA — `client/version.py`**: `config.APP_VERSION`,
  `.exe` versiya resursi va `ISCC /DAppVersion=` uchalasi undan.
* **`.env` O'RNATILGAN DASTURDA `%ProgramData%\ProctoringClient\.env`**
  (`core/bundle_paths.env_file_candidates`: `PROCTORING_ENV_FILE` ->
  ProgramData -> `.exe` yoni; dev'da faqat `client/.env`). Program
  Files'ga yozib bo'lmaydi, ProgramData esa barcha Windows hisoblari
  uchun bitta va oddiy foydalanuvchi uni faqat o'qiydi. Frozen
  rejimda `load_dotenv(override=True)` — aks holda talabgor
  `setx KIOSK_MODE false` bilan administrator faylini soyalardi.
  Qaysi fayl o'qilgani log'da (`main._log_env_file`); topilmasa ERROR.
* **O'rnatuvchi shabloni `.env.example` EMAS** (`installer/env.production.template`):
  unda dev qiymatlari (`FULLSCREEN=false`, `CLOSE_OTHER_APPS=false`,
  `API_SSL_VERIFY=0`) bor va ular imtihon mashinasida himoyani
  o'chirardi. Mavjud `.env` yangilashda USTIGA YOZILMAYDI (`/FORCEENV`
  — `.bak` bilan). `%APPDATA%\ProctoringClient` (`device_id.json`)
  uninstall'da O'CHIRILMAYDI.
* **cuDNN `9.10.2.21` GA QADALGAN** (`installer/requirements-build-gpu.txt`).
  pip'dagi 9.26 bo'laklarini (`cudnn_engines_tensor_ir64_9.dll`) nom
  bo'yicha yuklaydi va bundle'da topolmay birinchi Conv'da yiqiladi —
  ONNX Runtime esa sessiyani JIMGINA CPU'ga o'tkazadi. Dev'da
  ko'rinmaydi (torch'ning cuDNN i yuklanadi). Ikkinchi himoya:
  `cuda_runtime._preload_cudnn_siblings` bo'laklarni to'liq yo'l
  bilan oldindan yuklaydi. Tutun tekshiruvi (`ProctoringClientCheck.exe`,
  `installer/smoke_check.py`) provayderni INFERENSIYADAN KEYIN o'qiydi.
* **Avtostart — Task Scheduler** (`installer/autostart.ps1`), `HKLM\Run`
  emas: yuqori huquq UAC oynasisiz (tahdid skaneri xizmatlarni
  to'xtatadi), 72 soatlik o'ldirish o'chirilgan.
* **Yangilash imtihondan TASHQARIDA**: o'rnatuvchi client'ni
  `taskkill /F` bilan yopadi — o'chirilgan monitorlar qaytmaydi va
  ochiq sessiya `close_stale_sessions` gacha osilib qoladi.
* Build mashinasida `dist\...\ProctoringClient.exe` ni `.env` SIZ
  ochmang: kod standarti to'liq kiosk (dasturlarni yopadi, monitorni
  o'chiradi).

### Backend app'lari (`backend/src/apps/`)

| App | Mas'uliyat |
|---|---|
| `common` | Renderer, exception handler, pagination, permissions, throttling, Redis client, crypto, DB router, `storage.py` (S3) + `screenshot_storage.py` (fayl tizimi) |
| `users` | Xodimlar (`AUTH_USER_MODEL`), `Role`/`Permission` (code-based) |
| `regions` | Viloyat, Zone (bino) |
| `devices` | Computer, Camera (RTSP parollari shifrlangan), DeviceToken |
| `controls` | Client siyosati: ruxsat etilgan IP, COCO/RDP obyektlari, hotkey, model versiyalari, `Setting` profillari, `ProctoringPolicy` (AI), `EventRiskWeight` |
| `exams` | Exam, ExamSchedule (kirish oynasi) |
| `proctoring` | ExamSession, ProctoringEvent (partitsiyalangan), FaceVerificationLog, ScreenshotMeta + ProctoringScreenshot, EvidenceArtifact, LocalRecording (mashinadagi yozuv manzili), TechnicalProblem, AuditLog + consumers/tasks/services |
| `integrations` | Tashqi ntest platformasi (timeout + retry + circuit breaker + kesh) |

Har bir app: `models.py` / `selectors.py` (o'qish query'lari) / `services.py`
(yozish, biznes-mantiq) / `api/v1/{serializers,views,urls}.py`. View'lar
yupqa; biznes-mantiq service'da.

`proctoring/api/v1/` da **ikki xil yuza** bor va ular ataylab ajratilgan:
`views.py`+`urls.py` (admin panel, JWT) va `client_views.py`+`client_urls.py`
(PyQt6 desktop client, `/api/v1/client/...`, boshqa auth va throttling).

### Autentifikatsiya

* Admin panel — SimpleJWT (`Bearer`), refresh rotatsiya + blacklist.
* Desktop client — uch qatlam (`proctoring/authentication.py`):
  xodim JWT'si ("kim"), `X-Device-ID` ("qaysi kompyuter", **kredensial emas**,
  imzo yo'q), opaque sessiya tokeni ("qaysi sessiya", Redis'da, JWT emas —
  chetlashtirish o'sha soniyada kuchga kirishi uchun).
* **WebSocket'da ikki xil qoida.** `MonitorConsumer` (brauzer) tokenni
  query parametrida oladi — brauzer API'si header qo'shishga imkon
  bermaydi. `ClientConsumer` (PyQt6) esa avval `X-Proctoring-Session`
  header'ini o'qiydi va faqat u bo'lmasa query'ga tushadi: URL'dagi
  token nginx access log'ida qoladi, `QWebSocket` esa header qo'ya
  oladi. Query yo'li eski client'lar uchun saqlangan.
* Ruxsatlar — `HasRolePermission` (view'da `required_permission = "sessions.view"`)
  + `RegionScopedPermission` (obyekt darajasida IDOR'ga qarshi ikkinchi qatlam;
  asosiy filtrlash har bir viewset'ning `get_queryset()` ida).
* **VILOYAT CHEGARASI — UCH QATLAM** (`apps/users/tests/test_region_access.py`):
  * **KIM.** `Role.is_global` yoki superuser — butun respublika;
    qolganlari — faqat `User.region`. Viloyat darajasidagi rol +
    viloyat yo'q (`User.lacks_region`) = admin panelda HECH NARSA:
    `HasRegionAssignment` 403 `region_not_assigned` beradi (u
    `PermissionRequiredMixin` ga, dashboard, fayl view'lari va
    `MonitorConsumer` ga ulangan — client yuzasiga EMAS). Ilgari bunday
    xodim hamma narsani ko'rardi. Panel buni `RegionMissingState` bilan
    aytadi (`/auth/me/` → `lacks_region`); `UserWriteSerializer` bunday
    hisob yaratishni rad etadi.
  * **O'QISH.** Har viewset'ning `get_queryset()` i; "so'rovdagi
    viloyat qachon hisobga olinadi" savoli —
    `common.permissions.scope_region_id` (ilgari `is_superuser` ga
    qaralardi va respublika roli o'z viloyatiga qamalardi). Audit —
    `actor__region`, IP ro'yxati — o'z binolari + umumiy (faqat o'qish).
  * **YOZISH.** Yaratish/maydonni almashtirish querysetdan o'tmaydi —
    serializer'da `common.region_scope.ensure_in_region` (kompyuter,
    kamera, bino, seans, IP, chiqish paroli). Umumiy ma'lumot (rol,
    viloyatlar, client sozlamalari, AI siyosati, imtihonlar) —
    `republic_write_only = True` (`RepublicLevelWrite`, 403
    `republic_level_only`); panelda `ResourcePage shared` /
    `AuthContext.canShared` tugmalarni yashiradi. Viloyat admini
    respublika rolini BERA OLMAYDI.
* Client oqimining BIRINCHI qadami — `client/preflight/` (ochiq, JWT'siz):
  dastur ishga tushishi bilan chaqiriladi va client aytgan `public_ip`
  `AllowedPublicIp` da bo'lmasa login formasi umuman ko'rsatilmaydi.
  Qaror AYNAN shu qiymat bo'yicha (server ko'rgan manzil bo'yicha emas —
  server bino ichida turganda u faqat LAN manzilni ko'radi). Bu
  **qulaylik to'sig'i**, himoya emas: haqiqiy tekshiruv o'zgarishsiz
  `ClientBaseView.check_source_ip` da va u faqat server ko'rgan manzilga
  qaraydi.
* **Server clientni QAYSI manzilda ko'radi** — `ALLOW_PRIVATE_SOURCE_IP`
  shuni hal qiladi. `AllowedPublicIp` binolarning **tashqi** (NAT)
  manzillari ro'yxati va u faqat server clientlarni internet orqali
  ko'rganda ishlaydi. Server bino ichida tursa (yoki dev'da client
  bilan bir mashinada), u LAN/loopback manzilni ko'radi va ro'yxat
  unga hech qachon mos kelmaydi — `false` bilan **hamma rad etiladi**.
  Belgisi: preflight o'tadi, keyingi har bir so'rov 403 (`ip_not_allowed`).
  `local.py` da standart `true`, production'da `false`.
  **Yumshatish faqat xususiy manzilga tegishli** — ommaviy manzil
  avvalgidek ro'yxat bo'yicha tekshiriladi.
* **`AllowedPublicIp` da faol yozuv qolmasa** — `REQUIRE_ALLOWED_IP`
  (standart `true`) hal qiladi: hech kim kira olmaydi. Bu qiymat
  `false` bo'lsa ro'yxat bo'shligi "tekshiruv o'chirilgan" degani va
  hamma kiraveradi — ya'ni yagona yozuvni nofaol qilish yoki o'chirish
  butun cheklovni JIMGINA olib tashlaydi. Admin panelga ta'sir qilmaydi.
* **Ishga tushishda boshqa dasturlar yopiladi** (`CLOSE_OTHER_APPS`,
  standart = `KIOSK_MODE`; `client/services/app_closer.py`). Yopiladigan
  narsa — **jarayonlar emas, DASTURLAR**: mezon "ko'rinadigan, sarlavhali,
  yuqori darajali oynasi bor va joriy foydalanuvchi nomidan ishlaydi".
  Bu farq hal qiluvchi — tipik mashinada 321 jarayondan atigi ~10 tasi
  bu ta'rifga tushadi, qolgani tizim xizmatlari va ularni o'ldirish
  mashinani ishga tushmaydigan holga keltiradi. Ustiga to'rt qatlam:
  o'z jarayonlar daraxti (QtWebEngine bolalari ham), himoyalangan
  nomlar, boshqa hisob ostidagilar va avval `WM_CLOSE`, keyin
  majburiy o'ldirish. **Dev mashinasida `CLOSE_OTHER_APPS=false`
  qo'ying** — `KIOSK_MODE=true` bo'lsa u muharrir va terminalni ham
  yopadi. Oynasiz qism (masofaviy boshqaruv xizmati, gipervizor)
  bunga TUSHMAYDI — u ikkinchi tozalovchida
  (`THREAT_SCAN_ENABLED`, yuqoridagi "Toza mashina" bo'limi).
* **Kiosk rejimi** (`KIOSK_MODE`, standart = `FULLSCREEN`): ramkasiz +
  doim ustda oyna, `services/lockdown.py` orqali global tezkor tugma
  bloklash va parolsiz yopilmaslik. Dastur ochilishi bilan `.env`
  dagi `BLOCKED_HOTKEYS` standarti qo'llanadi; server ro'yxati
  (preflight, handshake, imtihon profili) uni ALMASHTIRADI, BO'SH
  server ro'yxati esa standartni qoldiradi (pastdagi "Client
  sozlamalari" bo'limi).
* **KLAVIATURA QULFI — ALOHIDA JARAYON, XOM HOOK, MODIFIKATORGA TEGMAYDI.**
  `keyboard` kutubxonasi OLIB TASHLANDI (requirements'dan ham) va
  QAYTARMANG. Qatlamlar: `services/keyboard_hook.py` (xom
  `WH_KEYBOARD_LL`, ctypes — mexanizm), `lockdown.KeyPolicy` (nima
  yutiladi — sof, testlanadi), `services/keyboard_hook_process.py`
  (qulf jarayoni: client o'z exe'sini `--keyboard-hook` bilan ko'taradi,
  `main.py` bayroqni Qt/log/`.env` dan OLDIN tekshiradi; stdin/stdout
  JSON qatorlar). Hammasi O'LCHANGAN (`tests/test_lockdown_hook.py`):
  * **Nega alohida jarayon:** client ichidagi Python hook'i GIL
    raqobatida har tugmani median ~63–110 ms, eng ko'pi ~310–420 ms
    kechiktirdi — yozish sekinlashadi va `LowLevelHooksTimeout` oshib,
    Windows hook'ni JIMGINA o'chiradi. Qulf jarayonida (bo'sh, GIL
    raqobatisiz) client yuklamada ham median 0.12 ms, max 1.9 ms.
    `sys.setswitchinterval` global va AI'ni sekinlatadi — ishlatilmadi.
  * **Hayot sikli:** client o'lsa (hatto `TerminateProcess`) qulf
    stdin'da EOF oladi va o'zi chiqadi — egasiz qulf qolmaydi. Qulf
    o'lsa client uni qayta ko'taradi (`hook_lost` → `hook_restored`).
    Qulf ishga tushmasa — zaxira `_LocalEngine` (client ichida).
  * **Modifikator ushlanmaydi/qayta yuborilmaydi**: faqat ASOSIY tugma
    yutiladi, modifikator holati `GetAsyncKeyState` dan, ortiqcha
    modifikator bloklashni bekor qilmaydi, yutilgan tugma o'z UP'igacha
    yutiladi. Eski `add_hotkey(suppress=True)` da Alt+Shift OS'ga
    `shift↓ shift↑ alt↓ alt↑` bo'lib yetib TIL ALMASHMASDI,
    `alt+shift+space`/AltGr+Space o'tardi, hook ko'rmagan UP (Ctrl+Alt+Del)
    dan keyin aniq Alt+Space ham o'tib, **kiosk oynasi System Menu
    ochardi**.
  * **VK bo'yicha, skan-kod emas**: `print screen`/`Num *` bir xil
    skan-kodli edi va `*` ham yutilardi; VK — Chromium va Windows
    yorliqni qanday talqin qilsa, shunday. INJEKT qilingan hodisa ham
    tekshiriladi (kutubxona `fake_alt` bilan ularni ko'rmasdi).
  * **Tiriklik — canary** (`KeyboardHook.probe`, 5 s): belgili KEYUP
    (`dwExtraInfo`, tayinlanmagan VK), hook uni YUTADI; javob yo'q —
    qayta o'rnatish (avval yangi, keyin eski — qulfsiz lahza yo'q).
    **Bo'sh mashinada tekshirilmaydi** (`IDLE_SKIP_S`, o'z canary'imiz
    hisobga olinmaydi): injeksiya bo'sh turish taymerini nolga
    qaytarib, ekran saqlagich, monitor uyqusi va auto-lock'ni
    butunlay o'chirardi.
  * **Yopishgan modifikator** (`KeyPolicy.tick`): Alt/Ctrl/Win 20 s,
    Shift 60 s dan ortiq bosilgan VA OS ham shunday desa — mantiqan
    qo'yib yuboriladi, auto-repeat'i jismoniy UP gacha yutiladi
    (apparat nosozligida ham talabgor yoza oladi). OS "qo'yilgan" desa
    (hook ko'rmagan UP) — hech narsa yuborilmaydi.
  * Qulf nosozligi imtihonda `proctoring_degraded` (`module: keyboard`,
    `reason: stuck_key | hook_restored | hook_lost`) — talabgorning aybi
    emas, yangi hodisa turi YO'Q; yopishgan tugmada talabgorga snackbar.
* **KIOSK OYNASIDA SYSTEM MENU YO'Q — hook'ga bog'liq emas.** Ikki
  qatlam: `lockdown.kiosk_window_flags` (`WindowSystemMenuHint`,
  Min/Max/Close bayroqlari olinadi — ular qolsa Qt `adjustFlags` menyuni
  qaytaradi VA `FramelessWindowHint` ni O'CHIRADI, oynaga ramka
  qaytadi) va ilova bo'ylab `install_system_menu_guard` (native filtr:
  Alt+Space `WM_SYSKEYDOWN`, `WM_SYSCHAR ' '`, `SC_KEYMENU`,
  `SC_MOUSEMENU`; dialoglar va WebEngine ham).
* **Chiqish qoidasi ikki bosqichli.** Preflight ekranida (login'gacha)
  parol so'ralmaydi — u yerda hali sessiya ham, talabgor ham yo'q.
  Login sahifasidan boshlab chiqishning YAGONA yo'li — **Ctrl+Q** va
  parol; login sahifasida "Chiqish" tugmasi ataylab yo'q.
  `ctrl+q` ni bloklab bo'lmaydi (`lockdown._NEVER_BLOCKED`) — aks holda
  mashina o'zini qulflab qo'yardi.
* **Chiqish paroli** — `client/exit/verify/` IKKI kalitni qabul qiladi:
  xodimning o'z paroli (JWT bo'lsa, audit'da ismi qoladi) va
  `controls.ClientExitPassword` — HAR BIR VILOYAT uchun alohida parol.
  Ikkinchisi login sahifasidagi yagona yo'l, shuning uchun endpoint
  autentifikatsiya talab qilmaydi (u hech narsa ochmaydi, faqat
  "parol to'g'rimi" deydi; himoya `ExitVerifyThrottle` da). Parol
  **hash** ko'rinishida saqlanadi va API uni hech qachon qaytarmaydi.
  Viloyatda parol yo'q bo'lsa — `exit_password_not_configured` qaytadi
  va client tasdiqlash dialogiga o'tadi: sozlanmagan tizim mashinani
  QULFLAB qo'ymasligi kerak.
* Har bir urinish `client/access-attempt/` orqali **alohida jurnalga**
  tushadi (`backend/logs/client_access.log`, `client_access` logger'i):
  MAC, LAN IP, public IP, manba IP, ruxsat berildimi va login sahifasi
  ochildimi. `AuditLog` ga yozilmaydi — u xodim harakatlari uchun.

> `README.md` da qurilma HMAC imzosi (`X-Device-Signature`) tasvirlangan —
> u **olib tashlangan**, sababi `authentication.py` docstring'ida. Client
> oqimi ham README'dagidan uzunroq: `identity/confirm/` (operator hujjat
> bo'yicha tasdiqlaydi) `exam/access/` dan OLDIN keladi.

### JSHSHIR: panelda TO'LIQ, clientda NIQOBLANGAN

Panel javoblarida (`SessionListSerializer`, `SessionCandidateSerializer`)
raqam TO'LIQ qaytadi va qidiruvga ham kiradi (`search_fields`).
Niqoblangan qiymat (`masked_pinfl`) eski panel nusxalari uchun
saqlanadi.

Sabab ishda: proktor talabgorni platformada yoki hujjatda AYNAN shu
raqam bo'yicha tekshiradi va niqoblangan raqamdan uni ko'chirib ham
bo'lmasdi — qidiruv esa allaqachon to'liq raqam bo'yicha ishlardi,
ya'ni niqob himoya emas, faqat noqulaylik edi. Panelga kirish
avvalgidek ruxsat bilan chegaralangan (`sessions.view` + viloyat
doirasi).

CLIENTDA niqob QOLADI: u yerda ekran oldida talabgorning o'zi
turadi va yonidagi odam ham ko'rib turadi.

### Javob konverti

Barcha javoblar `ApiJSONRenderer` orqali `{success, data, error}` ga
o'raladi; xatolar `apps.common.exceptions.api_exception_handler` dan
`code`/`message`/`details` bilan chiqadi. Frontend axios interceptor'i
konvertni ochib beradi, shuning uchun komponentlarda `response.data.data`
yozilmaydi. Yangi domen xatosi kerak bo'lsa — `DomainError` merosxo'ri
yarating; `code` React tomonda tarjima kaliti sifatida ishlatiladi.

### Frontend (`frontend/src/`)

* Barcha URL'lar `api/endpoints.js` da; komponentda URL yozilmaydi.
* CRUD sahifalari bitta dvigateldan: `components/data/ResourcePage.jsx` +
  `useResource.js` + `ResourceForm.jsx` + `DataTable.jsx`. Yangi model
  sahifasi = faqat `columns` va `fields` deklaratsiyasi
  (`pages/crud/*.jsx` ga qarang). Bu dvigateldan chetga chiqmang —
  URL-state, PATCH-diff, optimistik toggle, eksport, ruxsat tekshiruvi
  va saqlanmagan o'zgarish ogohlantirishi hammasi shu yerda.
* Marshrutlar `App.jsx` da, lazy chunk'lar `layout/navigation.js` dagi
  `ROUTE_LOADERS` orqali (menyu hover'da prefetch qiladi — ikkalasi bir
  xil loader'ni ishlatishi shart).
* `App.jsx` dagi `Guard` faqat UI qulayligi; haqiqiy himoya backendda.
* **Hodisa turkumlari `utils/events.js` da va ular BACKENDDA YO'Q.**
  `integrity` / `identity` / `behaviour` / `system` — sof taqdimot
  qarori. Backend `severity` beradi, u boshqa savolga javob beradi
  ("qanchalik jiddiy", "qaysi turkumdan" emas). Yangi hodisa turi
  qo'shsangiz uni `utils/labels.js:EVENT_LABEL` ga ham,
  `utils/events.js:EVENT_CATEGORY` ga ham qo'shing — aks holda u
  "tizim" turkumiga tushib, jonli kuzatuvda ko'zga tashlanmay
  qoladi. Ikkalasi `ProctoringEvent.Type` bilan to'liq mos
  bo'lishi kerak (hozir 39 ta tur).
* **WebSocket hodisasidagi `detail` — oq ro'yxat.** Backend
  (`ingest._BROADCAST_DETAIL_KEYS`) payload'dan faqat sanab
  o'tilgan kalitlarni, uzunlik chegarasi bilan uzatadi: payload'ni
  client to'ldiradi va u cheklanmagan. Yangi kalit kerak bo'lsa uni
  ikkala tomonda ham qo'shish shart (`utils/events.js:eventDetail`).
* **Sessiya tafsilotidagi skrinshot va yozuvlar alohida komponentda**
  (`components/session/ScreenshotGallery.jsx`, `LocalRecordings.jsx`).
  Galereya blob URL'larni BITTA joyda yuklaydi (`useShotUrls`) —
  karta, ko'rish oynasi va lenta bir xil rasmni ko'rsatadi va har
  biri o'zi so'rasa bitta fayl uch marta berilardi. Ko'rish oynasi
  mavzudan qat'i nazar QORONG'I (media viewer), kartalar `contain`
  (`cover` emas — ikki monitorli skrinshotning bir qismi kesilib,
  dalilda "yashirin" qism qolardi). Yozuvlar bo'limida asosiy
  ma'lumot — client qurilmasidagi TO'LIQ yo'l: fayl panelda ochilmaydi
  (brauzer `file://` ni ochmaydi), proktor uni mashinada topadi.
* Tema: `theme/palettes.js` (5 sxema × 3 rejim × 2 zichlik), sozlamalar
  `localStorage` da, `context/UiContext.jsx` boshqaradi.
* **YUQORI SARLAVHA (AppBar) YO'Q** (`layout/AppLayout.jsx`). Profil,
  viloyat, tungi rejim va chiqish — yon panel PASTIDAGI foydalanuvchi
  kartasida. Panel uch rejimda: `>= lg` to'liq yoki yig'ilgan (rail,
  `UiContext.sidebarCollapsed`), `md..lg` doim rail, `< md` yashirin +
  56 px li mobil satr. Ctrl+K — sahifa qidiruvi (`layout/CommandPalette.jsx`).
* **HAR BIR MENYU BANDIDA `description`** (`layout/navigation.js`) — u
  rail tooltip'ida, Ctrl+K qidiruvida va sarlavhadagi "i" belgisida
  ko'rinadi. Yangi sahifa qo'shsangiz tavsifni ham yozing. Sarlavhadagi
  bo'lim nomi (`Infratuzilma › …`) `findNavEntry` dan olinadi —
  sahifalar uni uzatmaydi.
* **Material 3 rollari `theme.palette.m3` da** (`primaryContainer`,
  `secondaryContainer`, `surfaceContainer{Lowest..Highest}`,
  `outlineVariant`) va ular palitradan HISOBLANADI (`theme/index.js:mix`),
  qo'lda yozilmaydi. `sx` da: `bgcolor: 'm3.surfaceContainerLow'`.
* **(tuzoq) `sx` dagi son `borderRadius` 12 ga KO'PAYTIRILADI**
  (`shape.borderRadius`): `borderRadius: 4` = 48 px, ya'ni kvadrat
  logotip doiraga aylanadi. Aniq qiymat uchun satr yozing (`'12px'`);
  kapsula — `999`.
* Shrift — `@fontsource-variable/inter`, paket ichida (CDN emas: imtihon
  markazi tarmog'ida internet bo'lmasligi mumkin).
* **OMMAVIY AMAL — `ResourcePage bulkActions`** (+ `isRowSelectable`):
  belgilash katakchalari, tanlovda asboblar qatori o'rnida MD3 kontekst
  paneli, "Filtrga mos barcha N tasini tanlash". Backend —
  `common.mixins.BulkSelectionMixin`: `{"ids": [...]}` yoki `{"all": true}`
  + ro'yxatning O'Z query parametrlari (`useResource.scopeParams`), ya'ni
  `get_queryset()` (viloyat chegarasi) va `filter_queryset()` dan o'tadi.
  Filtr/qidiruv o'zgarsa tanlov tozalanadi. Hozir: `computers/bulk-delete/`
  (yumshoq; IMTIHONDAGI mashina o'tkazib yuboriladi) va
  `device-tokens/bulk-approve/` (FAQAT kutayotganlar — blokdan chiqarish
  bittalab). Audit — bitta yozuv, ID'lar `meta` da.
* **`/device-tokens` JADVALI QISQA**: qurilma ID, versiya, GPU, blok sababi,
  xodim, manba/tashqi IP — qator bosilganda ochiladigan yon varaqda
  (`components/devices/DeviceDetailSheet.jsx`, amallar ham shu yerda).
  Ustun qo'shsangiz 1440 px ekranda gorizontal skroll chiqmasligini tekshiring.
* **VILOYAT -> BINO FILTRI** — `pages/crud/shared.jsx:regionZoneFilters`
  (ResourcePage filtri: `options(filters)`, `resets`, `regionScope`).
  Bino filtri viloyatsiz ham ishlaydi (hamma binolar), viloyat
  almashsa tozalanadi; viloyat xodimidan viloyat filtri yashiriladi.
  Faqat «Bino» filtrini qo'ymang — yuzlab bino bitta ro'yxatda bo'lardi.
* **SAHIFALASH.** Jadvallar — `DataTable` (server; «Sahifada» tanlovi
  jadval sayin `localStorage` da eslanadi, `useResource`). DataGrid'siz
  ro'yxatlar ham AYNAN o'sha futerni ishlatadi (`DataTable.TablePager`):
  sessiya tab'lari — `hooks/useCursorPages` (kursor, standart 50;
  skrinshotda ikki manbaning kursor juftligi), bitta so'rovda keladigan
  ro'yxatlar (dashboard binolari, mashinadagi yozuvlar) — brauzerda.
  **`list({ page_size: N })` bilan "hammasini" olmang** — N dan
  keyingilari jimgina tushib qoladi; variantlar uchun `useOptions` /
  `listAll` (barcha sahifalarni yig'adi).
* **TELEFON (< md) QOIDALARI** — 390 px da 28 ta marshrut tekshirilgan:
  * Filtr maydoniga qat'iy `minWidth`/`maxWidth` YOZMANG —
    `components/data/responsive.js:filterFieldSx(min, max, { half })`
    (telefonda to'liq yoki yarim kenglik).
  * `DataTable` telefonda `autoHeight`: sahifa ichida ikkinchi
    vertikal skroll bo'lmaydi, jadval faqat gorizontal suriladi.
    Oddiy `<Table>` ham siqilmaydi — `sx={{ minWidth: … }}` +
    `overflowX: 'auto'` o'rami (`SessionDetail`, `Dashboard`).
  * `ResourceForm` telefonda TO'LIQ EKRAN; forma paper'ning flex bolasi,
    ya'ni «Saqlash» doim pastda ko'rinadi. Temadagi dialog chetlari
    qoidasi `:not(.MuiDialog-paperFullScreen)` bilan yozilgan — usiz
    media so'rov to'liq ekranli dialogni yana oynaga aylantirardi.
  * Tab'lar standart `scrollable` (tema), segmentli guruh
    (`ToggleButtonGroup`) siqilmaydi, suriladi. Uni o'rab turgan flex
    konteynerga `minWidth: 0` kerak — aks holda guruh butun sahifani
    gorizontal suradi.
  * Uzun forma sahifasida (Sozlamalar) saqlash tugmasi telefonda suzadi
    (extended FAB) va sarlavhadagisi yashiriladi.

## Tuzoqlar

* **Yuz balli 0..100 shkalasi IKKI TOMONDA bir xil formuladan
  chiqadi** (`max(0, cos)*100`). Client formulasini "chiroyliroq
  ko'rinsin" deb o'zgartirsangiz, `Setting.faceid_min_score_*`
  chegarasi jimgina boshqa ma'noni anglatadi — shkala o'zgarsa
  chegaralar ham, yozilgan ballar ham migratsiya bilan
  ko'chirilishi SHART.
* **`face_checks` ni serverda oshirmang** — uni client heartbeat
  bilan YOZADI (`hset`). Ikkala tomon ham yozsa, bitta tekshiruv
  ikki marta sanaladi.
* **`multipart/form-data` da `embedding` JSON SATR sifatida keladi**
  va DRF uni BIR ELEMENTLI RO'YXAT ichida beradi
  (`QueryDict.getlist`). `EmbeddingField` ikkala shaklni ham ochadi;
  ochilmasa `FloatField` "String value too large" degan tushunarsiz
  xato beradi.
* **`FaceVerificationLog.session` NULL bo'lishi mumkin** — kirishda
  rad etilgan urinishda sessiya hali yo'q. Bu jadvalga qo'shiladigan
  har qanday `select_related("session")` yoki `session__` filtri
  aynan shu qatorlarni jimgina tashlab ketadi.
* **`filter_backends` ni ViewSet'da qayta e'lon qilmang** — u
  `DEFAULT_FILTER_BACKENDS` ni butunlay almashtiradi va `search_fields` /
  `ordering_fields` jimgina ishlamay qoladi.
* **Kursor va offset sahifalash aralash.** Sessiya/hodisa/audit endpointlari
  `count` qaytarmaydi. Kursorli endpointga `?page=2` yuborish ma'nosiz —
  DRF uni jimgina e'tiborsiz qoldiradi. Frontend ikkala shaklni javob
  bo'yicha avtomatik aniqlaydi.
* **Kursor unikal ustunga qurilishi shart.** Audit `AuditCursorPagination`
  (`-id`) dan foydalanadi, `-created_at` emas: bitta so'rov bir necha yozuv
  yaratadi va ularning `created_at` i bir xil bo'ladi.
* **`204 No Content` javobiga tana qo'shilmaydi** — `ApiJSONRenderer` konvertni
  204 da o'tkazib yuboradi (aks holda `ERR_CONTENT_LENGTH_MISMATCH`).
* **`CHANNEL_LAYERS` da `socket_timeout` (30s) `brpop_timeout` (5s) dan katta
  bo'lishi shart** — redis-py 8 ning `DEFAULT_SOCKET_TIMEOUT=5` qiymati
  WebSocket consumer'ini har bir bo'sh kutishda yiqitadi.
* **Channel layer ulanishi `retry` SIZ ishlatilmaydi**
  (`settings.base._channel_layer_host`). redis-py 8 standarti — NOL
  qayta urinish va `health_check_interval=0`, channels_redis esa
  ulanishni pool'da ushlab turadi. Bo'sh ulanishni yo'ldagi qatlam
  jimgina tashlaydi va keyingi `group_add` to'g'ridan-to'g'ri consumer'ni
  yiqitardi (`Error 22 ... semaphore timeout`, `WinError 121`) — panelning
  jonli kuzatuvi "ulandi, keyin uzildi" sikliga tushardi. Dev mashinasida
  (Windows + WSL2 `mirrored` Redis) bo'sh async ulanish **45–60 s da**
  o'lishi O'LCHANGAN, keepalive bilan ham. Kafolat — qayta urinish
  (o'lik ulanish yopiladi, buyruq yangisida qaytariladi); health check
  va keepalive uni faqat oldinroq ushlaydi. Consumer'lar ham layer
  xatosida yiqilmaydi: `1011` bilan yopiladi va client qayta ulanadi.
  Panel (`useLiveMonitor`) "ulangan" deb faqat `subscribed` dan keyin
  ko'rsatadi — socket ochilgani obuna o'tgani emas.
* **Davriy vazifada `expires` MAJBURIY** (`test_celery_config`). Ishchi
  ishlamagan kunlarda broker navbatida tiklar to'planadi va `expires`
  siz ular tiklangach BIRDANIGA bajariladi. Bir martalik vazifalar
  (`report_session_result`) esa tashqi platformaga haqiqiy natija
  yuboradi — navbatni tozalashda ularni davriy tiklar bilan birga
  o'chirib yubormang.
* **(client) WebSocket manzili HTTP API'nikidan BOSHQA jarayon**
  (`runserver` 8000, uvicorn 8001). `WS_BASE_URL` berilmasa client uni
  API manzilidan chiqaradi va dev tartibini (loopback + 8000) taniydi
  (`realtime.default_ws_url`). Ilgari port ham ko'chirilardi: client
  `ws://...:8000/ws/client/` ga urilib 404 olardi (`runserver` log'ida
  "GET /ws/client/ 404") va proktor ogohlantirishi/chetlashtirish
  buyrug'i clientga YETMASDI.
* **Migratsiyalar versiya nazoratida** (`.gitignore` dan ataylab chiqarilgan).
  `src/config/settings/local.py` esa `.gitignore` da.
* **`celery beat` bir nechta ishga tushirilsa** ingest buferida dublikat
  paydo bo'ladi.
* **Read replica ishlatilganda** "yozdim va darhol o'qidim" stsenariysida
  aniq `.using("default")` yozing (`common/db_router.py`).
* **`EventCursorPagination` ni skrinshot ro'yxatlarida ishlatmang** —
  uning `ordering` i `-occurred_at`, skrinshot jadvallarida esa
  `captured_at`. `ScreenshotCursorPagination` ishlatiladi.
* **Konfiguratsiya modellari `SoftDeleteModel`** — `.delete()` fizik
  o'chirmaydi, `deleted_at` qo'yadi; ro'yxatlarda `.alive()` ishlatiladi.
* **Redis `maxmemory-policy` `noeviction` bo'lishi kerak** — `allkeys-lru`
  da faol sessiya tokenlari imtihon o'rtasida o'chib ketadi.
* **Python `203.0.113.0/24` ni XUSUSIY deb biladi.** RFC 5737 hujjat
  diapazonlari (`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`)
  `ipaddress.is_private` da `True` beradi. Testlarda "ommaviy manzil"
  kerak bo'lsa haqiqiysini oling (`8.8.8.8`) — aks holda
  `ALLOW_PRIVATE_SOURCE_IP` bilan bog'liq testlar chalkash natija
  beradi.
* **(test) client yuzasida `force_authenticate` ISHLATMANG** — DRF uni
  ko'rganda view'ning butun `authentication_classes` ro'yxatini
  `ForcedAuthentication` bilan almashtiradi. `DeviceResolution` va
  `SessionTokenAuthentication` esa yon ta'sirli: ular `None` qaytarib
  faqat `request.device` / `request.exam_session` ni to'ldiradi. Ular
  ishga tushmasa, to'g'ri sessiya tokeni bilan kelgan so'rov ham
  `session_not_found` oladi. Haqiqiy JWT yuboring
  (`tests/test_client_api.py:bearer`).
* **`EventCursorPagination` va `ScreenshotCursorPagination` naqshi
  dalillarga ham tegishli** — `EvidenceArtifact` `captured_at`
  bo'yicha tartiblanadi.
* **`ProctoringEvent.evidence_id` FK EMAS** (partitsiyalangan
  jadvalga FK `bulk_create` ni buzadi). Yaxlitlik tartib bilan
  ta'minlanadi: avval fayl, keyin dalil qatori, keyin hodisa.
* **`ProctoringPolicy` yo'qligi "AI o'chirilgan" degani emas** —
  standart qiymatlar qaytadi (`_default_proctoring`). Bo'sh lug'at
  qaytarish client'ni o'z chegaralarini o'ylab topishga majbur
  qilardi va ular ikki joyda ajralib ketardi.
* **`FrameFeatures.timestamp` uchun `0.0` ni "yo'q" deb hisoblamang** —
  u haqiqiy qiymat (nisbiy soat) bo'lishi mumkin. `x or default`
  naqshi bu yerda davomiylikni MANFIY qilib, hech bir shartni
  tasdiqlanmaydigan holga keltiradi. Bir xil tuzoq
  `EventFusion` cooldown'ida ham bor edi.
* **(client) ByteTrack `min_hits` ni 1 ga tushirmang** — bitta
  kadrdagi aniqlanish shovqin bo'lishi mumkin va u darhol izga
  aylansa, hodisa oqimi soxta obyektlar bilan to'ladi.
* **(client) `pyqtSignal` ni `event` deb nomlamang.** `QObject.event()` —
  Qt'ning markaziy virtual metodi; uni signal bilan bosib qo'yish
  obyektga birinchi bola qo'shilishi bilan (masalan `parent=self` bilan
  yaratilgan `QThread`) butun jarayonni **qulatadi**, va Python hech
  qanday istisno bermaydi — process jimgina o'ladi.
* **(client) Dalil `boxes` maydoni JSON SATR sifatida ketadi** —
  `multipart/form-data` ichma-ich strukturani ko'tarmaydi va
  backend uni satrdan ochadi (`EvidenceUploadSerializer.validate_boxes`,
  chegara 20 ta ramka).
* **(client) To'xtatish tartibi: pipeline → monitor.** Kuzatuv
  yakunda OCHIQ hodisalarni yopadi va ular hodisa buferiga
  tushishi kerak. Monitordan keyin to'xtatilsa, "telefon ko'rindi"
  yozuvi davomiyliksiz qolardi. Supervisor ichida ham xuddi shu
  qoida: avval pipeline, keyin kameralar.
* **(client) `QThread` ning "ishlayapti" bayrog'ini `run()` ichida
  qo'ymang** — `start()` dan keyin darhol `stop()` chaqirilsa, endigina
  boshlangan `run()` bayroqni qaytarib qo'yadi va thread abadiy
  ishlaydi. Bayroq `start()` da, chaqiruvchi thread'da qo'yiladi
  (`device_watch._ProcessScanner`).
* **(frontend) Import qilinmagan komponent BUILD'DAN O'TADI va faqat
  brauzerda yiqiladi.** ESLint konfiguratsiyasi yo'q (`npm run lint`
  ishlamaydi), Vite esa `no-undef` ni tekshirmaydi. `SessionDetail`
  dagi `RecordingRow` shunday edi: `Paper`, `IconButton`,
  `ContentCopyIcon` import qilinmagan va birinchi yozuv chizilishi
  bilan butun sahifa `ReferenceError` bilan yiqilardi — yozuvlar
  bo'sh bo'lgani uchun bu hech qachon ko'rinmagan. Yangi JSX
  yozganda aniqlanmagan identifikatorlarni alohida tekshiring
  (masalan, `@babel/parser` + `@babel/traverse` bilan — ular
  `node_modules` da bor).
* **(client) Ishlab turgan `CameraWorker` referensini `None` QILMANG
  — `retire_camera()` chaqiring.** PyQt egasiz qolgan QThread'ni
  darhol yo'q qilmaydi: u ishlashda davom etadi va KAMERANI BAND
  QILIB TURADI, sikli esa keyinroq (qurilmani boshqa joy ochganda)
  uzilgan zahoti jarayon `0xC0000409` bilan yiqiladi — istisnosiz,
  log'da izsiz. Aynan shunday bo'lgan: `proctoring/start/` rad
  etilganda FaceID sahifasidan uzatilgan kamera tashlab yuborilardi
  (`exam_webview_page._release_pending_camera`). Xavfsizlik to'ri
  sifatida `CameraWorker.start` workerni `_LIVE` registriga yozadi,
  lekin u faqat qulashni to'sadi — kamerani bo'shatmaydi.
* **(client) QAT'IY O'LCHAMLI vidjet siqilgan ustunda USTMA-UST
  TUSHISH beradi.** FaceID sahifasidagi hujjat rasmi 264x352 edi va
  1366x768 ekranda yon ustunga sig'masdi — Qt yetishmagan joyni
  o'raladigan yorliqlardan oladi (ular layout'ga bir qatorlik
  minimum beradi, modal dialoglardagi bilan bir xil tuzoq) va ism
  rasmning USTIGA chiziladi. `faceid_page._fit_photo` rasmni
  KARTAGA TEKKAN balandlikdan kelib chiqib o'lchaydi (nisbat 3:4
  saqlanadi), joy baribir yetmasa ikkilamchi chiplarni yashiradi.
  O'lchov ekran balandligidan EMAS, kartaning o'zidan olinadi:
  qat'iy "chrome" konstantasi shriftga va DPI masshtabiga (125%)
  bog'liq bo'lardi. Shu sababdan yangi element qo'shganda yon
  ustunni past ekranda ham tekshirish kerak.

* **(client) Kamera nomini PnP ro'yxatidan OLMANG.**
  `Get-PnpDevice -Class Camera` tartibi OpenCV indeksiga bog'liq
  emas va ekranda ikkita kameraning nomi almashib qolardi —
  operator esa aynan nomga qarab "qaysi biri yuzga qaraydi" degan
  qarorni qabul qiladi. Nom DirectShow sanagichidan olinadi
  (`camera/dshow.py`), u OpenCV'ning O'ZI ishlatadigan manba.
  Zaxira yo'lda (`_apply_names`) eski qoida qoladi: sonlar mos
  kelmasa nom UMUMAN berilmaydi ("Kamera #0") — xato nom
  nomsizlikdan yomonroq.
* **(client) `onnxruntime-gpu` NASHRI CUDA VERSIYASIGA QADALGAN.**
  `1.22.x` `cublasLt64_12.dll` ni, `1.24+` esa
  `cublasLt64_13.dll` ni so'raydi va ularni almashtirib bo'lmaydi.
  Nomos nashr JIMGINA ishlaydi: paket o'rnatiladi,
  `CUDAExecutionProvider` ro'yxatda turadi, model esa CPU'da
  yuklanadi. `cuda_runtime` buni aniqlaydi va qaysi fayl
  yetishmayotganini aytadi — lekin YECHIM faqat bitta: paketni
  mashinadagi CUDA versiyasiga mos nashri bilan almashtirish.
* **(client) `ctypes` da `restype` YETARLI EMAS, `argtypes` ham
  SHART.** Usiz ctypes Python butun sonini C `int` (32 bit) deb
  uzatadi, Windows deskriptori esa 64-bit tizimda undan katta
  bo'ladi va chaqiruv `OverflowError: int too long to convert`
  bilan yiqiladi. `threat_scanner._stop_service` da bu BARCHA
  xizmatlar uchun yiqilardi, ya'ni tozalashning butun xizmat qismi
  jimgina ishlamasdi. Muqobil yo'l — har bir deskriptorni ochiq
  `ctypes.c_void_p(...)` ga o'rash (`process_identity` shunday
  qiladi).
* **(client) Windows tizim binarlarining PE resursi `.mui`
  faylidan keladi.** `GetFileVersionInfoW` lokalizatsiyalangan
  binar uchun yonidagi yo'ldosh faylga JIMGINA yo'naltiriladi va
  `OriginalFilename` `mstsc.exe.mui` bo'lib chiqadi. Tuzatilmasa
  ikkita jimgina xato beradi: tizim katalogidagi nishon qoidaga
  hech qachon mos kelmasdi va HAR BIR tizim binari "qayta
  nomlangan" deb ko'rinardi (`process_identity._strip_mui`).
  Uchinchi tomon dasturlari MUI ishlatmaydi.
* **(client) Sahifadagi xabar qatori LAYOUTNI suradi.** Imtihon
  sahifasida uning ostida `QWebEngineView` turadi va bitta xabar
  butun test sahifasini pastga surib qo'yadi. U yerda `Snackbar`
  ishlatiladi (suzadi va o'zi yo'qoladi), `MessageBar` esa qolgan
  sahifalarda.

## Muhit o'zgaruvchilari

`backend/.env` (namuna: `.env.example`) va `frontend/.env.example`.
Production'da majburiy: `SECRET_KEY`, `TOKEN_HASH_KEY`,
`FIELD_ENCRYPTION_KEY`, `JWT_SIGNING_KEY`. `TOKEN_HASH_KEY` o'zgarsa barcha
faol sessiya tokenlari bekor bo'ladi; `FIELD_ENCRYPTION_KEY` o'zgarsa
shifrlangan maydonlar o'qilmay qoladi — kamera RTSP parollari
(`Camera.password_encrypted`) va imtihon platformasi sarlavhasi
(`Exam.site_header_encrypted`).

Dev uchun foydali: `BASE_API_MOCK=true` (tashqi ntest'siz ishlash),
`DISABLE_THROTTLING=true`, `REQUIRE_DEVICE_ID=false`, `S3_ENABLED=false`.

**Client dev mashinasida uchta bayroq `false` bo'lishi kerak** —
uchalasi ham `KIOSK_MODE` dan standart qiymat oladi va
`KIOSK_MODE=true` bilan ishlab chiqishda ular ish muhitini buzadi:
`CLOSE_OTHER_APPS` (muharrir va terminalni yopadi),
`THREAT_SCAN_ENABLED` (VirtualBox, WSL2, Docker Desktop),
`DISABLE_EXTRA_MONITORS` (ikkinchi monitorni o'chiradi).
`LOCAL_ARCHIVE_ENABLED=false` ham shu ro'yxatda, lekin u boshqa
sababdan (diskka kadr yozadi).
