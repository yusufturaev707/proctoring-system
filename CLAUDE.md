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
python manage.py runserver                            # HTTP API :8000

# WebSocket — ALOHIDA process, `src/` dan
cd backend/src && uvicorn config.asgi:application --port 8001

# Celery — `backend/` dan
celery -A config worker -Q ingest -c 4
celery -A config worker -Q maintenance,default -c 2
celery -A config beat                                 # AYNAN BITTA instansiya

# Frontend
cd frontend && npm install && npm run dev             # :5173, /api va /ws proxy qilinadi
npm run build
```

`DJANGO_SETTINGS_MODULE` standart qiymati `config.settings.local`.
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

Client tomoni (`client/services/screen_capture.py`) qaysi yo'l yoqilganini
**oldindan bilmaydi** — handshake buni aytmaydi. Rejim sessiya boshida bir
marta aniqlanadi: `presign/` 503 qaytarsa, fayl tizimi yo'liga o'tiladi.
Yangi sozlama qo'shganda shu shartnomani buzmang.

**`Setting.screenshot_dedup_threshold` — dHash'dagi FARQLI BITLAR soni
(0–64)**, foiz emas. Bu ikki komponent orasidagi kontrakt va u faqat
client kodida yashaydi: model maydonida birlik yozilmagan. `0` — dedup
o'chirilgan. Ketma-ket 6 marta o'tkazib yuborilgach kadr chegaradan
qat'i nazar yuboriladi (`_FORCE_SEND_AFTER_SKIPS`) — dedup dalilda
"ko'r oyna" yarata olmasligi kerak.

### Backend app'lari (`backend/src/apps/`)

| App | Mas'uliyat |
|---|---|
| `common` | Renderer, exception handler, pagination, permissions, throttling, Redis client, crypto, DB router, `storage.py` (S3) + `screenshot_storage.py` (fayl tizimi) |
| `users` | Xodimlar (`AUTH_USER_MODEL`), `Role`/`Permission` (code-based) |
| `regions` | Viloyat, Zone (bino) |
| `devices` | Computer, Camera (RTSP parollari shifrlangan), DeviceToken |
| `controls` | Client siyosati: ruxsat etilgan IP, COCO/RDP obyektlari, hotkey, model versiyalari, `Setting` profillari |
| `exams` | Exam, ExamSchedule (kirish oynasi) |
| `proctoring` | ExamSession, ProctoringEvent (partitsiyalangan), FaceVerificationLog, ScreenshotMeta + ProctoringScreenshot, TechnicalProblem, AuditLog + consumers/tasks/services |
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
* **Kiosk rejimi** (`KIOSK_MODE`, standart = `FULLSCREEN`): ramkasiz +
  doim ustda oyna, `services/lockdown.py` orqali global tezkor tugma
  bloklash va parolsiz yopilmaslik. Tugmalar ro'yxati serverdan
  keladi — preflight'da (login'dan oldin) va handshake'da (bino
  sozlamasi bilan).
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
  qo'shsangiz uni `EVENT_LABEL` ga ham, `EVENT_CATEGORY` ga ham
  qo'shing — aks holda u "tizim" turkumiga tushib, jonli kuzatuvda
  ko'zga tashlanmay qoladi.
* **WebSocket hodisasidagi `detail` — oq ro'yxat.** Backend
  (`ingest._BROADCAST_DETAIL_KEYS`) payload'dan faqat sanab
  o'tilgan kalitlarni, uzunlik chegarasi bilan uzatadi: payload'ni
  client to'ldiradi va u cheklanmagan. Yangi kalit kerak bo'lsa uni
  ikkala tomonda ham qo'shish shart (`utils/events.js:eventDetail`).
* Tema: `theme/palettes.js` (5 sxema × 3 rejim × 2 zichlik), sozlamalar
  `localStorage` da, `context/UiContext.jsx` boshqaradi.

## Tuzoqlar

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
* **(client) `pyqtSignal` ni `event` deb nomlamang.** `QObject.event()` —
  Qt'ning markaziy virtual metodi; uni signal bilan bosib qo'yish
  obyektga birinchi bola qo'shilishi bilan (masalan `parent=self` bilan
  yaratilgan `QThread`) butun jarayonni **qulatadi**, va Python hech
  qanday istisno bermaydi — process jimgina o'ladi.
* **(client) `QThread` ning "ishlayapti" bayrog'ini `run()` ichida
  qo'ymang** — `start()` dan keyin darhol `stop()` chaqirilsa, endigina
  boshlangan `run()` bayroqni qaytarib qo'yadi va thread abadiy
  ishlaydi. Bayroq `start()` da, chaqiruvchi thread'da qo'yiladi
  (`device_watch._ProcessScanner`).

## Muhit o'zgaruvchilari

`backend/.env` (namuna: `.env.example`) va `frontend/.env.example`.
Production'da majburiy: `SECRET_KEY`, `TOKEN_HASH_KEY`,
`FIELD_ENCRYPTION_KEY`, `JWT_SIGNING_KEY`. `TOKEN_HASH_KEY` o'zgarsa barcha
faol sessiya tokenlari bekor bo'ladi; `FIELD_ENCRYPTION_KEY` o'zgarsa
saqlangan kamera parollari o'qilmay qoladi.

Dev uchun foydali: `BASE_API_MOCK=true` (tashqi ntest'siz ishlash),
`DISABLE_THROTTLING=true`, `REQUIRE_DEVICE_ID=false`, `S3_ENABLED=false`.
