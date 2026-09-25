# Proctoring Client (PyQt6)

Imtihon markazidagi operator ish o'rni uchun desktop dastur. Backend
(`../backend`) ning `/api/v1/client/...` yuzasi bilan ishlaydi.

## Ishga tushirish

```bash
cd client
python -m venv venv
venv/Scripts/activate            # Windows
pip install -r requirements.txt

# ONNX Runtime — FAQAT bittasi:
pip install onnxruntime==1.22.0          # CPU
# pip install onnxruntime-gpu==1.22.0    # CUDA 12.x (requirements.txt izohiga qarang)

cp .env.example .env              # API_BASE_URL ni to'g'rilang
python main.py
```

Logotip `client/resources/images/logo.png` da — PyInstaller buyrug'iga
`--add-data "resources;resources"` qo'shilishi SHART (fayl topilmasa
dastur ishlaydi, lekin logotip ko'rinmaydi).

InsightFace modellari `client/models/buffalo_l/` ga qo'yiladi (5 ta
`.onnx` fayl). Dev rejimda ular bo'lmasa InsightFace internetdan yuklab
oladi; frozen (`.exe`) rejimda esa bu **xato** — imtihon mashinasi
oflayn bo'lishi mumkin va yuklab olish 30+ soniya timeout bilan
tushunarsiz xato beradi.

## Sozlamalar: `.env` va admin panel

Ikki qatlam (batafsil: `../CLAUDE.md` -> "Client sozlamalari"):

* **`.env`** — serverdan OLDIN kerak bo'ladigan va mashinaga xos
  qiymatlar: server manzili, TLS, kiosk, monitorlar, ishga tushishda
  dasturlarni yopish (`CLOSE_OTHER_APPS*`), bloklanadigan tezkor
  tugmalarning STANDARTI (`BLOCKED_HOTKEYS`), kamera/GPU, arxiv diski.
* **Admin panel (`Setting` profili)** — imtihon/bino bo'yicha
  o'zgaradiganlar: FaceID oqimi, ekran yozuvi, skrinshot tasmasi,
  tahdid to'sig'i, heartbeat/batch, tezkor tugmalar ro'yxati. Server
  qiymati USTUN, `.env` dagi mos qiymat faqat zaxira
  (`services/runtime_settings.py`).

## O'rnatuvchi (Windows)

`.exe` va `setup.exe` — [`installer/`](installer/README.md): PyInstaller
`onedir` + Inno Setup, GPU/CPU nashri, silent o'rnatish
(`/VERYSILENT`; server manzili build paytida `installer/client.env` dan joylanadi), `.env` ning joyi
(`%ProgramData%\ProctoringClient\.env`) va yangilash tartibi.
Logotip (`--add-data "resources;resources"`) va modellarni spec o'zi
qo'shadi.

```powershell
powershell -ExecutionPolicy Bypass -File installer\build.ps1 -Gpu   # yoki -Cpu
```

## Oqim

| Sahifa | Nima qiladi | Backend |
|---|---|---|
| 1. Login | Xodim JWT'si, fon rejimida model yuklanadi | `/auth/login/` + `/client/handshake/` |
| 2. Imtihon | Test turi -> test (zanjirli select) | tarmoqsiz (handshake ma'lumoti) |
| 3. Talabgor | JSHSHIR -> tashqi platforma javobi + hujjat rasmi | `/client/candidate/lookup/` |
| 4. FaceID | Kamera + InsightFace, pasport rasmi bilan solishtirish | `/client/face/verify/`, `/client/identity/confirm/` |
| 5. WebView | Qulflangan QWebEngineView, heartbeat + hodisalar + davriy FaceID | `/client/exam/access/`, `/client/heartbeat/`, `/client/events/`, `/client/face/periodic/` |

Qurilma birinchi ishga tushishda `/devices/register/` orqali o'zini
ro'yxatga qo'yadi va `PENDING` holatida qoladi — administrator admin
panelda tasdiqlamaguncha handshake ishlamaydi. Olingan `device_id`
`%APPDATA%/ProctoringClient/device_id.json` da saqlanadi.

Server kompyuterni uchta belgi bo'yicha, shu ISHONCHLILIK tartibida
topadi:

1. **MAC manzil** — asosiy belgi (global unikal, apparatga bog'langan).
2. **Inventar kodi** — ixtiyoriy `.env` qiymati (`INVENTORY_CODE`).
3. **LAN IP + bino** — bino so'rovning tashqi IP'si orqali aniqlanganda
   (`controls.AllowedPublicIp`). Bino noma'lum bo'lsa IP bo'yicha
   qidiruv umuman qilinmaydi: `192.168.1.10` turli binolarda takrorlanadi
   va client jimgina boshqa binoga biriktirilib qolardi.

`device_id` yo'qolsa (masalan `%APPDATA%` tozalansa) client o'zini
tiklaydi: apparat izi mos kelsa, server mavjud identifikatorni
qaytaradi.

## Struktura

```
client/
├── main.py               # kirish nuqtasi (log, env, QApplication)
├── main_window.py        # QStackedWidget navigatsiyasi
├── config.py             # .env dan o'qiladigan barcha sozlamalar
├── core/                 # bundle yo'llari, log, xato modeli, singleton
├── services/             # API, repository, auth, FaceID, kamera, monitoring
│   ├── api_client.py     # HTTP transport (konvert, JWT refresh, headerlar)
│   ├── repositories.py   # ENDPOINTLAR faqat shu yerda
│   ├── app_state.py      # sahifalar orasidagi holat
│   ├── face_engine.py    # InsightFace (singleton + fon yuklovchi)
│   ├── camera_worker.py  # kamera oqimi (QThread)
│   ├── monitoring.py     # heartbeat + hodisalar buferi
│   └── workers.py        # universal ApiWorker (QThread)
├── ui/
│   ├── styles.py         # yashil urg'uli dizayn tizimi
│   ├── widgets/          # StatusPill, BusyOverlay, CameraView, PageHeader
│   └── pages/            # 5 ta sahifa
└── models/buffalo_l/     # InsightFace modellari (VCS'ga kirmaydi)
```

## Arxitektura qoidalari

* **UI thread'da tarmoq YO'Q.** Har bir chaqiruv `ApiWorker` (QThread)
  ichida; natija signal orqali qaytadi. `WorkerHolder` referens ushlaydi
  — aks holda QThread yig'ilib ketadi va dastur qulaydi.
* **URL faqat `repositories.py` da.** Sahifalarda endpoint yozilmaydi.
* **Xato `code` bo'yicha hal qilinadi**, matn bo'yicha emas
  (`core/errors.py`). Server matni faqat zaxira.
* **Kamera egaligi uzatiladi.** 4-sahifadagi `CameraWorker` yopilmaydi,
  WebView sahifasiga beriladi: kamerani qayta ochish Windows'da 2–4
  soniya oladi va shu vaqtda talabgor kuzatuvsiz qoladi.
* **Sessiya tokeni `ApiClient` da**, sahifalarda emas. Sessiya
  tugaganda `set_session_token(None)` — eski token keyingi so'rovga
  qo'shilib qolmaydi.

## Muhim tuzoqlar

* **`QImage` numpy buferiga referens ushlaydi.** `camera_view.py` da
  `.copy()` majburiy, aks holda kadr buzilib chiziladi yoki dastur
  qulaydi.
* **WebView profili obyekt sifatida saqlanishi kerak.** Python tomonda
  referens yo'qolsa, sahifa "Render process terminated" bilan yiqiladi.
* **Har sessiya uchun yangi off-the-record profil** — oldingi
  talabgorning cookie'si keyingisiga o'tmasligi uchun.
* **`FACE_MATCH_STREAK`** ketma-ket kadr talab qiladi: bitta kadr
  tasodifiy mos kelishi mumkin, ketma-ketlik esa yo'q.
* **Etalon rasm bo'lmasa** oqim to'xtamaydi — enrollment rejimi ishlaydi
  va qaror operatorning hujjat tekshiruviga qoladi (backend mantig'i
  bilan bir xil).
