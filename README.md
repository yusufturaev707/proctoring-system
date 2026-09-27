# Onlayn Proctoring Tizimi

Imtihon jarayonini real vaqtda kuzatuvchi mustaqil tizim: Django/DRF backend,
React (MUI) boshqaruv paneli va PyQt6 desktop client uchun API.

```
backend/    Django 6 + DRF + Channels + Celery
frontend/   React 18 + Vite + MUI v6
```

## Tez boshlash

**Talablar:** Python 3.12, Node 20+, PostgreSQL 14+, Redis 6+

```bash
# --- Backend ---
cd backend
python -m venv .venv && .venv/Scripts/activate      # Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                                 # qiymatlarni to'ldiring

python manage.py migrate
python manage.py setup_partitions --apply            # hodisa jadvalini partitsiyalash
python manage.py seed_base_data --demo               # rollar, ruxsatlar, demo ma'lumot
python manage.py createsuperuser

python manage.py runserver 8002                          # HTTP API  :8000
```

```bash
# --- WebSocket (alohida process) ---
cd backend/src
uvicorn config.asgi:application --port 8003
```

```bash
# --- Fon vazifalari ---
cd backend
celery -A config worker -Q ingest -c 4
celery -A config worker -Q maintenance,default -c 2
celery -A config beat                                # FAQAT BITTA
```

```bash
# --- Frontend ---
cd frontend
npm install
npm run dev                                          # http://localhost:5173
```

API hujjati: `http://localhost:8000/api/docs/`

---

## Arxitektura

Tizim to'rt xil process'ga bo'lingan, chunki ularning yuklama profili
tubdan farq qiladi:

| Process | Yuklama | Nima uchun alohida |
|---|---|---|
| HTTP API (WSGI) | ~50–200 rps | CRUD, admin, murakkab query |
| WebSocket (ASGI) | 10 000 uzun ulanish | Uzun umrli ulanishlar WSGI'da umuman ishlamaydi |
| Celery `ingest` | 3 000 hodisa/s | Buffer → DB batch yozish |
| Celery `beat` | — | Rejalashtirish; bir nechta bo'lsa dublikat beradi |

### Yuqori yuklamaga bardoshlilik

Loyihaning markaziy qarori — **ikki bosqichli yozish**:

```
HTTP so'rov  →  Redis Stream (XADD, ~0.2 ms)     [client darhol javob oladi]
Celery (5s)  →  bulk_create (~10 000 qator)      [bitta tranzaksiya]
```

10 000 talaba uchun bu 3 000 tranzaksiya/sekundni ~0.2 ga tushiradi.

| Muammo | Yechim |
|---|---|
| Skrinshot trafigi ~120 MB/s | Presigned S3 URL — binary backenddan **o'tmaydi** |
| Heartbeat 333 UPDATE/s | Redis write-behind; DB'ga 10s da bir marta batch |
| `proctoring_event` mlrd qator | `occurred_at` bo'yicha RANGE partitsiya + cursor pagination |
| FaceID 1 000 inference/s | Embedding clientda; serverga 2 KB vektor keladi, rasm emas |
| Tashqi ntest API bloklanishi | Timeout 2/5s + circuit breaker + 30 daq kesh |
| Ulanish pool'i | PgBouncer (transaction mode) + `CONN_MAX_AGE` |

Batafsil: [`backend/deploy/README.md`](backend/deploy/README.md)

### Xavfsizlik

| Chora | Joyi |
|---|---|
| JSHSHIR HMAC-hash (indeks) + AES-GCM (ko'rsatish) | `common/utils/crypto.py` |
| Qurilma HMAC imzosi + nonce (replay himoyasi) | `proctoring/authentication.py` |
| Opaque sessiya tokeni (JWT emas — darhol bekor qilinadi) | `proctoring/services/state.py` |
| Bir martalik tashqi token, URL'da emas | `proctoring/services/session.py` |
| "Bitta talabgor = bitta sessiya" atomik qulfi | Redis Lua SETNX |
| JSHSHIR brute-force chegarasi | `common/throttling.py` |
| Audit log (o'zgartirilmaydi/o'chirilmaydi) | `proctoring/models.py` |
| Kamera va chiqish parollari shifrlangan | `devices/services.py` |

---

## Asosiy modellar

```
Candidate ──< ExamSession ──< ProctoringEvent      (partitsiyalangan)
                   │       ──< FaceVerificationLog
                   │       ──< ScreenshotMeta       (binary → S3)
                   │       ──< TechnicalProblem
                   │       ─── ExternalAuthToken    (bir martalik)
                   │
              Exam / Zone / Computer / DeviceToken
```

Ma'lumot umr bo'yi uch qatlamga ajratilgan:

* **Hot** (Redis) — sessiya holati, heartbeat, hisoblagichlar
* **Warm** (S3/MinIO) — skrinshot va yuz rasmlari
* **Cold** (PostgreSQL) — sessiya, hodisa, audit (huquqiy dalil)

---

## Client oqimi (PyQt6)

```
1. POST /api/v1/client/handshake/          qurilma + konfiguratsiya
2. POST /api/v1/client/candidate/lookup/   JSHSHIR → talabgor + challenge
3. POST /api/v1/client/face/verify/        FaceID  → sessiya tokeni
4. POST /api/v1/client/exam/access/        bir martalik token + WebView siyosati
   ─── imtihon davomida ───
   POST /client/events/                    batch (5s oyna)
   POST /client/screenshots/presign|commit presigned upload
   POST /client/face/periodic/             embedding (rasm emas)
   POST /client/heartbeat/                 Redis'ga, DB'ga emas
   WS   /ws/client/                        proktor buyruqlari
5. POST /api/v1/client/session/finish/
```

Har bir so'rov HMAC bilan imzolanadi:

```
X-Device-ID, X-Device-Timestamp, X-Device-Nonce
X-Device-Signature = HMAC-SHA256(secret, "device_id.ts.nonce.path")
```

---

## Boshqaruv paneli

| Bo'lim | Imkoniyat |
|---|---|
| Boshqaruv paneli | Interaktiv ko'rsatkichlar, grafiklar, binolar kesimi — hammasi drill-down |
| Jonli kuzatuv | WebSocket oqimi, xavf bo'yicha tartib, ogohlantirish/chetlashtirish |
| Sessiyalar | Arxiv, URL'da saqlanadigan filtrlar, hodisa/FaceID/skrinshot tafsilotlari |
| Texnik muammolar | Qo'shimcha vaqt berish qarorlari |
| Infratuzilma | Viloyat, bino, kompyuter, kamera, qurilma tokenlari |
| Boshqaruv | Foydalanuvchi, rol/ruxsat matritsasi, client sozlamalari, audit |
| Profil | Tema (5 variant), yorug'lik rejimi, zichlik, parol |

### Ko'rinish

Yashil urg'uli, uzoq ishlash uchun mo'ljallangan tema tizimi:

* **5 ta rang sxemasi** — Zumrad (standart), O'rmon, Feruza, Okean, Grafit
* **3 ta rejim** — kunduzgi / tungi / avto (OS sozlamasiga ergashadi)
* **2 ta zichlik** — keng / ixcham
* Sozlamalar `localStorage` da, darhol qo'llanadi

Ko'z charchog'ini kamaytirish qarorlari (`src/theme/palettes.js`):
sof oq/qora ishlatilmaydi, katta yuzalar past to'yinganlikda, to'yingan
rang faqat kichik urg'ularda, barcha matn/fon juftliklari WCAG AA.

### Tezlik

| Chora | Ta'siri |
|---|---|
| Menyu ustiga hover'da marshrutni oldindan yuklash | Bosilganda chunk keshda — kutishsiz o'tish |
| Skelet ekranlar (spinner emas) | Layout sakramaydi, kutish qisqaroq tuyuladi |
| `keepPreviousData` + xiralashish | Sahifa almashganda jadval bo'shamaydi |
| Keyingi sahifani prefetch | «Keyingi» bosilganda ma'lumot tayyor |
| Qidiruvni 350 ms kechiktirish | Har harfda so'rov ketmaydi |
| Kechiktirilgan skelet (180 ms) | Tez javoblarda "chaqnash" bo'lmaydi |
| Kod bo'linishi (route + vendor chunk) | Birinchi yuklash yengil |

### CRUD dvigateli

Barcha modellar bitta dvigateldan foydalanadi
(`components/data/ResourcePage.jsx` + `useResource.js` + `ResourceForm.jsx`).
Sahifa faqat ustunlar va maydonlarni e'lon qiladi, qolgani umumiy:

**Ma'lumot bilan ishlash**

* server tomonda sahifalash, saralash, filtrlash (offset va **kursor** —
  ikkalasi ham, javob shakli bo'yicha avtomatik aniqlanadi);
* qidiruv/filtr/sahifa/saralash **URL'da** saqlanadi — havolani ulashsa
  yoki F5 bossa, ekran aynan o'sha holatda ochiladi;
* joriy sahifani CSV ga eksport (BOM + `;` — Excel to'g'ri ochadi;
  ustun `exportValue` bergan bo'lsa, faylda ekrandagi matn chiqadi,
  xom kod emas);
* ro'yxatdan turib `is_active` ni almashtirish — optimistik, xato bo'lsa
  avvalgi holat qaytariladi;
* klaviatura: `/` — qidiruv, `N` — yangi yozuv (maydon ichida yozayotganda
  ishlamaydi).

**Xato va yo'qotishlardan himoya**

* maydon darajasidagi validatsiya + backend xatolarini aniq maydonga
  bog'lash;
* yangilashda faqat **o'zgargan** maydonlar yuboriladi (PATCH) — parallel
  tahrirlashda begona o'zgarishlar qaytarilmaydi;
* ikki marta yuborish bloklanadi;
* saqlanmagan o'zgarishlar haqida ogohlantirish (massiv maydonlar ham
  qiymat bo'yicha solishtiriladi);
* kritik yozuvlarni o'chirishda nomni qo'lda yozish talab qilinadi;
* ruxsat bo'yicha to'siq (asosiy himoya baribir backendda).

**Maydon turlari:** `text`, `number`, `password`, `date`, `datetime`,
`textarea`, `json`, `boolean`, `select` (12 ta variantdan ko'p bo'lsa
avtomatik qidiruvli `autocomplete` ga o'tadi), `multiselect` (M2M uchun)
va `custom` — o'ziga xos boshqaruvni forma kafolatlarini yo'qotmasdan
joylash uchun (rol ruxsatlari matritsasi shu orqali ishlaydi).

**Zanjirli tanlov.** Maydon `options` ni funksiya sifatida berishi
mumkin (`options: (form) => …`), `dependsOn` bilan yuqori maydon
tanlanmaguncha to'siladi, `resets` bilan quyi maydonlarni tozalaydi,
`transient` bilan esa serverga umuman yuborilmaydi. Kompyuter va kamera
formalari shu asosda ishlaydi:

```
Viloyat (transient) -> Bino (shu viloyatniki) -> Kameralar (shu binodagi)
```

Viloyat kompyuterning maydoni emas — u faqat 400 ta bino ichidan
qidirmaslik uchun turadi va `PATCH` tanasiga tushmaydi.

### Jadval va sahifalash

* har bir jadvalda `№` ustuni — tartib raqami, tooltipda yozuvning
  haqiqiy ID'si (offset rejimida raqam sahifalar bo'ylab uzluksiz,
  kursorli rejimda o'tilgan sahifalar soniga qarab hisoblanadi);
* futer offset va kursor rejimida bir xil ko'rinadi: sahifa hajmi,
  oraliq va navigatsiya. Offset rejimida raqamli sahifalar, kursorli
  rejimda faqat oldinga/orqaga — chunki kursorli sahifalashda "7-sahifa"
  ga sakrash texnik jihatdan mumkin emas;
* eskirgan `?p=7` havolasi (o'sha sahifa endi mavjud emas) 404 xatosi
  bilan qamab qo'ymaydi — ro'yxat avtomatik birinchi sahifadan ochiladi.

---

## Nomuvofiqlik eslatmalari

* **`channels-redis` + `redis-py 8`** — `CHANNEL_LAYERS` da `socket_timeout`
  aniq berilishi shart va u `brpop_timeout` (5s) dan katta bo'lishi kerak.
  redis-py 8 da `DEFAULT_SOCKET_TIMEOUT = 5` paydo bo'ldi; teng qiymatlar
  har bir bo'sh kutishda WebSocket consumer'ini yiqitadi.
* **PgBouncer transaction mode** — `USE_PGBOUNCER=true` qo'ying, aks holda
  `CONN_MAX_AGE > 0` prepared statement konfliktini beradi.
* **Migratsiyalar versiya nazoratida** bo'lishi shart (`.gitignore` dan
  chiqarilgan).
* **`204 No Content` javobiga tana qo'shilmaydi** — `ApiJSONRenderer`
  konvertni 204 da o'tkazib yuboradi, aks holda `Content-Length` mos
  kelmaydi va brauzer `ERR_CONTENT_LENGTH_MISMATCH` beradi.
* **Cursor va offset sahifalash aralash** — sessiya/hodisa/audit
  endpointlari `count` qaytarmaydi (milliardlab qatorda `COUNT(*)`
  qimmat). Frontend ikkala shaklni ham avtomatik aniqlaydi. Kursorli
  endpointga `?page=2` yuborish MA'NOSIZ: DRF uni jimgina e'tiborsiz
  qoldiradi va o'sha qatorlarni qaytaradi.
* **Kursor unikal ustunga qurilishi shart** — `AuditLog` da bitta so'rov
  bir necha yozuv yaratadi va ularning `created_at` i bir xil bo'ladi.
  Shuning uchun audit `AuditCursorPagination` (`-id`) dan foydalanadi;
  `-created_at` bo'lsa sahifa chegarasidagi yozuvlar takrorlanadi yoki
  tushib qoladi.
* **ViewSet'da `filter_backends` ni qayta e'lon qilmang** — u
  `DEFAULT_FILTER_BACKENDS` ni butunlay almashtiradi. Masalan
  `filter_backends = [DjangoFilterBackend]` yozilsa, o'sha view'dagi
  `search_fields` va `ordering_fields` jimgina ishlamay qoladi: panelda
  qidiruv maydoni bor, bosiladi, lekin natija hech qachon filtrlanmaydi.
