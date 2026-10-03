# Client o'rnatuvchisi (Windows)

Natija — bitta `ProctoringClientSetup-<versiya>-<gpu|cpu>.exe`. U
dasturni `Program Files\ProctoringClient` ga o'rnatadi, server
manzilini `%ProgramData%\ProctoringClient\.env` ga yozadi va
(standart bo'yicha) Windows'ga kirilganda client'ni avtomatik ishga
tushiradi.

| Fayl | Vazifasi |
|---|---|
| `build.ps1` | hammasi bitta buyruqda: tekshiruv → PyInstaller → tutun tekshiruvi → Inno Setup |
| `proctoring_client.spec` | PyInstaller (`onedir`), GPU/CPU nashri |
| `proctoring_client.iss` | Inno Setup 6 skripti |
| `smoke_check.py` | yig'ilgan `.exe` ning tutun tekshiruvi (`ProctoringClientCheck.exe`) |
| `make_models_manifest.py` | `models_manifest.json` — model yaxlitligi etaloni (build yozadi, client `core/self_check.py` o'qiydi) |
| `make_icon.py` | `resources/images/logo.png` → `.ico` (build vaqtida) |
| `autostart.ps1` | Task Scheduler "at logon" vazifasi (o'rnatuvchi chaqiradi) |
| `env.production.template` | `client.env` namunasi (server manzili o'rinbosarlari bilan) |
| `client.env` | **git'da yo'q** — o'rnatuvchiga joylanadigan tayyor `.env` (pastga qarang) |
| `requirements-build*.txt` | build vositalari va CUDA g'ildiraklari (qadalgan) |

Versiya bitta joyda — `client/version.py`. Spec undan `.exe` ning
Windows versiya resursini, `build.ps1` esa `AppVersion` ni oladi.

## Nima uchun aynan shu vositalar

**PyInstaller `--onedir`.** Bundle 0.9–3.2 GB (QtWebEngine + CUDA +
modellar). `--onefile` uni HAR ishga tushishda `%TEMP%` ga ochadi:
sovuq start o'nlab soniya, antivirus har safar yangi joydagi yuzlab
DLL'ni skanerlaydi (va "packed executable" deb false-positive
beradi), qulashda `_MEI*` diskda qoladi. `onedir` bir marta
o'rnatiladi — o'lchangan start: oyna ~1 s, InsightFace GPU'da ~2 s.

**Nuitka emas.** Bu stekda deyarli hamma og'ir qism — Qt, QtWebEngine,
onnxruntime, CUDA, OpenCV — allaqachon native DLL; Nuitka faqat
Python qismini (bundle'ning <2%) kompilyatsiya qiladi. Buning narxi
esa katta: C kompilyatori, soatlab build, onnxruntime/insightface
plaginlari va `lazy_loader` (skimage) uchun qo'lda sozlash.
**cx_Freeze** — PyInstaller bilan bir xil model, lekin QtWebEngine va
onnxruntime uchun hook'lar kamroq sinalgan.

**Inno Setup, MSI (WiX) emas.** Bitta `setup.exe`, LZMA2 siqish
(3.2 GB bundle → 1.5 GB), `/VERYSILENT` + buyruq satri parametrlari
(`/INVENTORY_CODE=`), build paytida joylangan `.env` ni yozish va GPO/SCCM/PDQ
orqali tarqatish. WiX (MSI) Active Directory "Software Installation"
siyosati uchun ideal, lekin 30 000+ faylli `onedir` uchun `heat`
bilan komponent yig'ish, maxsus harakatlar uchun C#/DLL va
parametrlarni `PROPERTY=` orqali uzatish kerak — foydasi bu yerda
yo'q, chunki SCCM/PDQ `.exe` ni ham silent o'rnatadi. **NSIS** —
imkoniyatlari o'xshash, lekin skript tili qiyinroq va Unicode/64-bit
qo'llab-quvvatlash qo'shimcha plaginlarga tayanadi.

## Build

Talablar: `client/venv` (runtime `requirements.txt` o'rnatilgan),
Inno Setup 6 (`C:\Program Files (x86)\Inno Setup 6\ISCC.exe`).

```powershell
cd client
# bir marta: build vositalari (+ GPU uchun CUDA g'ildiraklari)
powershell -ExecutionPolicy Bypass -File installer\build.ps1 -Gpu -InstallBuildDeps

# keyingi safar
powershell -ExecutionPolicy Bypass -File installer\build.ps1 -Gpu
powershell -ExecutionPolicy Bypass -File installer\build.ps1 -Cpu
```

Tayyor `.bat` buyruqlar (istalgan katalogdan ishlaydi, qo'shimcha
parametrlar `build.ps1` ga uzatiladi — masalan `build-gpu-install.bat -Clean`):

| Fayl | Nima yig'adi |
|---|---|
| `installer\build-cpu.bat` | CPU `.exe` → `dist\cpu\ProctoringClient\` |
| `installer\build-cpu-install.bat` | CPU `.exe` + `dist\installer\ProctoringClientSetup-<ver>-cpu.exe` |
| `installer\build-gpu.bat` | GPU `.exe` → `dist\gpu\ProctoringClient\` |
| `installer\build-gpu-install.bat` | GPU `.exe` + `dist\installer\ProctoringClientSetup-<ver>-gpu.exe` |

`*-install.bat` uchun `installer\client.env` kerak (pastda, «Server
manzili — BUILD paytida»); faqat `.exe` yig'ishga u kerak emas.

| Parametr | Ma'nosi |
|---|---|
| `-Gpu` / `-Cpu` | nashr (standart `-Gpu`) |
| `-InstallBuildDeps` | `requirements-build*.txt` ni venv ga o'rnatish |
| `-Clean` | PyInstaller keshini tozalash (paket/hook o'zgarganda) |
| `-SkipInstaller` | faqat `dist\<nashr>\ProctoringClient\` |
| `-SkipSmoke` | tutun tekshiruvisiz |
| `-RequireGpuSmoke` | tutun tekshiruvida CUDA ishlamasa build yiqiladi (GPU'li build mashinasida) |
| `-FullBuffalo` | buffalo_l ning ishlatilmaydigan modellarini ham qo'shish |
| `-NoCheckExe` | `ProctoringClientCheck.exe` siz |
| `-EnvFile <yo'l>` | o'rnatuvchiga joylanadigan `.env` (standart `installer\client.env`) |
| `-SignAllUnsigned` | imzolashda `_internal` dagi imzosiz `.dll/.pyd/.exe` ni ham imzolash (faqat `SIGN_CERT_THUMBPRINT` bilan) |

### Server manzili — BUILD paytida

O'rnatuvchi API va WebSocket manzilini **so'ramaydi**: ular build
paytida tayyor `.env` dan setup.exe ICHIGA joylanadi. Manzil bitta
o'rnatish (viloyat/markaz) uchun bitta va o'zgarmaydi — uni har
mashinada qo'lda terish faqat xato qilish imkoniyati edi (bitta harf
xatosi = mashina hech qayerga ulanmaydi va buni o'sha mashinaga borib
topish kerak).

```powershell
copy installer\env.production.template installer\client.env
# client.env da @API_BASE_URL@ va @WS_BASE_URL@ ni to'ldiring
powershell -ExecutionPolicy Bypass -File installer\build.ps1 -Gpu
# bir nechta o'rnatish:  -EnvFile installer\toshkent.env
```

`build.ps1` faylni PyInstaller'dan OLDIN tekshiradi: to'ldirilmagan
`@...@` va `http(s)://` / `ws(s)://` sxemasi — xato (build to'xtaydi);
loopback manzil, HTTP, `API_SSL_VERIFY=0` va o'chirilgan kiosk
bayroqlari — sariq ogohlantirish (sinov o'rnatuvchisi uchun ruxsat).
Fayldagi `INVENTORY_CODE` o'rinbosar bilan almashtiriladi — u
mashinaga xos va o'rnatishda kiritiladi. Joylangan fayl `{app}` ga
yozilmaydi: faqat o'rnatish paytida `{tmp}` dan ProgramData'ga
ko'chadi.
| `-IsccPath` | ISCC.exe ga ochiq yo'l |

Chiqish:

```
client/dist/gpu/ProctoringClient/        PyInstaller natijasi (sinash uchun)
client/dist/cpu/ProctoringClient/
client/dist/installer/ProctoringClientSetup-1.0.0-gpu.exe
client/build/<nashr>/proctoring_client/  kesh, warn-*.txt, xref-*.html, smoke-report.txt
```

Ikonka `logo.png` dan HAR build'da yasaladi (Pillow faqat build
mashinasida) — logotip almashtirilsa `.exe` ham, o'rnatuvchi ham yangi
belgini oladi.

### GPU va CPU nashri

| | GPU | CPU |
|---|---|---|
| `_internal/cuda/` | CUDA 12 + cuDNN 9.10 (2.06 GB) | yo'q |
| ORT CUDA provayderi | bor (320 MB) | olib tashlangan |
| Bundle / setup.exe (o'lchangan, v1.0.0) | 3 244 MB / 1 517 MB | 882 MB / 412 MB |
| Build vaqti (PyInstaller + ISCC) | ~1.5 + 4 daqiqa | ~1.5 + 1.5 daqiqa |
| GPU'siz mashinada | ishlaydi (CPU'ga tushadi, log'da `ERROR`) | ishlaydi |

Ikkalasi BIR XIL venv'dan yig'iladi (`onnxruntime-gpu`): CPU nashrida
provayder DLL'i olib tashlanadi va `cuda_runtime` uni topmay, to'g'ri
CPU ro'yxatini qaytaradi. Ikkala nashr bir xil `AppId` ga ega —
biri ikkinchisini almashtiradi (`_internal` o'rnatishdan oldin
tozalanadi, ya'ni GPU → CPU o'tishida 2 GB `cuda/` qolib ketmaydi).

**CUDA DLL'lari qayerdan.** Spec `onnxruntime_providers_cuda.dll` ning
PE import jadvalini o'qiydi (`cuda_runtime.py` bilan bir xil qoida —
ro'yxat qadalmagan), DLL'larni `site-packages/nvidia/*/bin` (pip,
`requirements-build-gpu.txt`) → `CUDA_PATH` → `torch/lib` tartibida
qidiradi va `_internal/cuda/` ga qo'yadi. Bu `cuda_runtime` ning
`resource_root() / "cuda"` qidiruv joyi: frozen rejimda `sys.path` da
`site-packages` yo'q, ya'ni `nvidia/*/bin` u yerda umuman
qidirilmaydi. Dinamik yuklanadigan cuDNN kichik kutubxonalari
(`cudnn_*64_9.dll`) va NVRTC ham qo'shiladi — ular import jadvalida
ko'rinmaydi, yetishmasa esa xato INFERENSIYA paytida chiqadi.

**cuDNN 9.10 ga qadalgan, 9.26 EMAS** (o'lchangan). cuDNN 9.2x yangi
`cudnn_engines_tensor_ir64_9.dll` ni oddiy `LoadLibrary` bilan NOMI
bo'yicha yuklaydi va uni `_internal/cuda` dan topolmaydi (ORT 1.22 ning
`preload_dlls` ro'yxatida u yo'q). Natija — birinchi Conv'da
`CUDNN_BACKEND_API_FAILED` va ORT sessiyani JIMGINA CPU'ga o'tkazadi,
log esa "GPU (CUDA)" deb turaveradi (provayderlar inferensiyadan OLDIN
o'qilgani uchun). Tutun tekshiruvi provayderlarni inferensiyadan KEYIN
o'qiydi va `--require-gpu` bilan buni ushlaydi; spec ham ogohlantiradi.
cuDNN'ni yangilashdan oldin: `build.ps1 -Gpu -RequireGpuSmoke`.

**Qt trimlash.** `PyQt6.QtQml/QtQuick` Python modullari chiqarilgan:
`Qt6WebEngineCore.dll` ularga bog'langan (DLL'lar baribir keladi),
lekin PyInstaller shundan butun `qml/` plaginlar daraxtini (Quick3D,
Controls2, Multimedia, ~50 DLL) tortardi. `*.debug.pak` (~78 MB) —
faqat Qt debug yig'ilishi uchun. Birga ~135 MB.

### Import tahlili (excludes)

Spec'dagi `EXCLUDES` haqiqiy ishlash yo'lidan tuzilgan: client
modullari import qilinib, InsightFace'ga haqiqiy yuz rasmi berilib,
`sys.modules` yig'ilgan. Muhim topilma:

* **scipy KERAK** — `insightface.utils.face_align` →
  `skimage.transform.SimilarityTransform` → `scipy.linalg`,
  `scipy.spatial`. Har yuz tekshiruvida ishlaydi. Faqat ishlash
  yo'lida yuklanmaydigan qism-paketlar chiqarilgan (`scipy.stats`,
  `optimize`, `ndimage`, `signal`, ...).
* `onnx`, `requests`, `tqdm` — insightface modul darajasida import
  qiladi, qoladi.
* `torch` (venv'da 4.3 GB), `sympy`, `networkx`, `PIL`, `imageio`,
  `matplotlib`, `tkinter` — client ishlatmaydi, chiqarilgan.
* Uchinchi tomon uchun yashirin import KERAK EMAS: `insightface.model_zoo`
  kichik modullarini statik import qiladi; `onnxruntime.capi`, `cv2`
  (ffmpeg DLL), `skimage` (lazy `.pyi`), `scipy`, `certifi` — contrib
  hook'lari; PyQt6 (WebEngine, WebSockets, `tls/` plaginlari) —
  PyInstaller hook'lari. `warn-*.txt` dagi qolgan "missing" lar
  (`numpy.core.*`, `pwd`, IronPython) — soxta.
* **Client modullari (`core`, `services`, `proctoring`, `ui`, `config`,
  `main_window`, `version`) IKKALA `.exe` ga yashirin import**
  (`CLIENT_MODULES`): tutun tekshiruvi ularni `importlib` bilan yuklaydi
  va o'z PYZ'ini sinaydi — paritetsiz asosiy `.exe` da `main.py` dan
  statik yetib bo'lmaydigan modul yo'qligini u ko'rmasdi.
* `--keyboard-hook` / `--watchdog` — xuddi shu oynali `.exe`
  (`console=False`): konsol oynasi chaqnamaydi, qulf jarayonining
  stdin/stdout'i pipe orqali meros qilinadi. `multiprocessing`
  ishlatilmaydi — `freeze_support()` shart emas.

Yangi paket qo'shilganda tutun tekshiruvi (u client'ning BARCHA
modullarini import qiladi) birinchi bo'lib xabar beradi.

### Model manifesti

`build.ps1` PyInstaller'dan keyin `dist\<nashr>\ProctoringClient\models_manifest.json`
ni yozadi (`.exe` YONIDA):

```json
{"files": {"models/buffalo_l/det_10g.onnx": {"size": 16923827, "sha256": "..."}}, "base": "_internal"}
```

Kalitlar `core.bundle_paths.resource_root()` ga nisbatan (onedir'da
`<exe yoni>\_internal`) — client (`core/self_check.py`) aynan shu ildiz
bilan o'qiydi. `models/` ostidagi HAR fayl kiradi (`.onnx`,
`*.labels.txt`). Tutun tekshiruvi manifestni bundle bilan ikki tomonlama
solishtiradi. Modelni qo'lda almashtirsangiz — manifestni ham qayta yozing
(`make_models_manifest.py --app-dir ...`), aks holda client "model
buzilgan" deydi.

### Tutun tekshiruvi

```powershell
dist\gpu\ProctoringClient\ProctoringClientCheck.exe [--require-gpu] [--require-env] [--report out.txt] [--json out.json]
```

Haqiqiy yo'llarni bosib o'tadi: client modullari, modellar, CUDA
(qaysi fayldan yuklangani bilan), ONNX sessiyasi + inferensiya,
yuzni tekislash (skimage/scipy), `FaceAnalysis`, `mp4v` yozuvi,
QtWebEngine (alohida jarayon + JS). O'rnatilgan mashinada ham
ishlaydi: Start menyuda «Proctoring Client - diagnostika».

## O'rnatish

### Qo'lda

`ProctoringClientSetup-1.0.0-gpu.exe` → «Kompyuter» sahifasi —
inventar kodi, IXTIYORIY (faqat `.env` hali yo'q bo'lsa; bo'sh
qoldirilsa server kompyuterni MAC bo'yicha topadi) → tayyor. Server
manzili so'ralmaydi. Administrator huquqi kerak.

### Silent (500 mashinaga)

```bat
ProctoringClientSetup-1.0.0-gpu.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART ^
    [/INVENTORY_CODE=INV-001] ^
    /LOG="C:\Windows\Temp\proctoring-setup.log"
```

| Parametr | Ma'nosi |
|---|---|
| `/INVENTORY_CODE=` | mashinaning inventar kodi (ixtiyoriy; server qoidasi — 3-50 belgi, `A-Z a-z 0-9 - _`; xato kod bilan o'rnatish boshlanmaydi, kod 1) |
| `/ENVFILE=` | joylangan `.env` o'rniga boshqa tayyor fayl (masalan `\\server\share\bino12.env`) |
| `/FORCEENV` | mavjud `.env` ni almashtirish (eski nusxa `.env.bak-<sana>`) |
| `/TASKS="autostart"` | vazifalar: `autostart` (standart yoqilgan), `desktopicon` |
| `/TASKS=""` | avtostartsiz (sinov mashinasi) |
| `/DIR="D:\ProctoringClient"` | boshqa katalog |

Server manzili parametri YO'Q — u setup.exe ichida. Boshqa manzil
kerak bo'lsa: yangi `client.env` bilan qayta build yoki `/ENVFILE=`.

O'chirish: `"C:\Program Files\ProctoringClient\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART`.

**`/NORESTART` ni tushirib qoldirmang**: `/SUPPRESSMSGBOXES` "qayta
yuklash kerak" savoliga standart bo'yicha HA deydi — VC++ runtime 3010
qaytargan mashina o'rnatish oxirida o'zi qayta yuklanardi.

Chiqish kodlari (SCCM/PDQ uchun): `0` — tayyor; `1` — ishga tushmadi
(eski Windows, 32-bit, xato `/INVENTORY_CODE`, `/ENVFILE` yo'q); `2` —
bekor qilindi; `5` — o'rnatish yarmida to'xtadi (eski versiya QAYTARILDI);
`7` — oldindan tekshiruv to'xtatdi (disk joyi, jarayon to'xtamadi,
zaxiraga olib bo'lmadi) — hech narsa o'zgarmagan.

### Oldindan tekshiruvlar (fayllarga tegishdan OLDIN)

| Tekshiruv | Qayerda | Natija |
|---|---|---|
| Windows 10 1809+ (`MinVersion=10.0.17763`), 64-bit | Inno o'zi | to'xtaydi, kod 1 |
| Administrator | `PrivilegesRequired=admin` — UAC so'raladi (SYSTEM'da so'ralmaydi) | rad etilsa o'rnatilmaydi |
| Disk joyi: bundle + 512 MB | `CheckDiskSpace` (silent'da ham) | kod 7 |
| Client jarayonlari (asosiy, watchdog, klaviatura qulfi, tekshiruv, `{app}` dan ishga tushgan har jarayon) | `StopClient`: `schtasks /End` -> `taskkill /F /T` takrori ~10 s gacha -> yo'l bo'yicha | to'xtamasa kod 7 |
| VC++ runtime 14.40+ | `EnsureVcRuntime` | `redist\vc_redist.x64.exe` bo'lsa jim o'rnatiladi; yo'q bo'lsa va runtime ESKI — ogohlantirish (to'siq emas: app-local nusxa bor) |

### Rollback

Inno faqat o'zi yozgan fayllarni qaytaradi, `[InstallDelete]` o'chirgan
eski `_internal` ni emas. Shuning uchun eski versiya o'chirilmaydi —
`{app}\_rollback` ga KO'CHIRILADI (bir disk — bir zumda). O'rnatish
yarmida yiqilsa (kod 5) `DeinitializeSetup` uni joyiga qaytaradi;
muvaffaqiyatda `ssPostInstall` da o'chiriladi. Elektr o'chib qolgan
holatdagi qoldiqni keyingi o'rnatish yoki uninstall tozalaydi.

### Yangilash

Xuddi o'sha buyruq, yangi `setup.exe` bilan. Mavjud `.env` saqlanadi
(inventar kodi ham) — setup.exe ichidagi manzil faqat `.env` hali yo'q
bo'lsa yoki `/FORCEENV` bilan yoziladi. O'rnatuvchi:

1. ishlab turgan client'ni (watchdog va klaviatura qulfi bilan birga)
   majburan yopadi (kiosk oddiy yopilishni rad etadi);
2. eski `{app}\_internal` ni `{app}\_rollback` ga ko'chiradi (eski DLL
   yangisi bilan aralashmasligi va yiqilishda qaytarish uchun);
3. yangi fayllarni yozadi, zaxirani o'chiradi, avtostart vazifasini
   yangilaydi.

**Yangilashni imtihon vaqtidan tashqarida o'tkazing**: majburan
yopilgan client o'chirilgan qo'shimcha monitorlarni QAYTARMAYDI va
ochiq imtihon sessiyasi serverda `close_stale_sessions` yig'guncha
ochiq qoladi.

### Fayllar qayerda

| Nima | Qayerda | Uninstall'da |
|---|---|---|
| Dastur | `C:\Program Files\ProctoringClient\` | o'chiriladi |
| Sozlama (`.env`) | `C:\ProgramData\ProctoringClient\.env` | **qoladi** |
| `autostart.ps1` | `{app}\tools\` | o'chiriladi |
| `device_id.json`, log | `%APPDATA%\ProctoringClient\` (har Windows hisobi) | **qoladi** |
| Mahalliy arxiv | eng bo'sh qat'iy disk, `ProctoringArchive\` | **qoladi** |

`.env` qidirish tartibi (`core/bundle_paths.env_file_candidates`):
`PROCTORING_ENV_FILE` → `%ProgramData%\ProctoringClient\.env` →
`.exe` yonidagi `.env` (o'rnatuvchisiz nusxa) → dev'da `client/.env`.

**O'rnatilgan dastur sozlamani FAQAT `.env` faylidan oladi** — muhit
o'zgaruvchilari (`set`/`setx KIOSK_MODE=...`) e'tiborsiz qoladi, aks
holda talabgor administrator huquqisiz kioskni o'chira olardi
(`core/env_guard.py`). `PROCTORING_ENV_FILE` faqat MASHINA darajasida
qabul qilinadi (`setx /M PROCTORING_ENV_FILE "D:\cfg\.env"`, administrator).
`QTWEBENGINE_*`, `SSL_CERT_FILE` va shu kabi kutubxona o'zgaruvchilari
ham o'chiriladi; korporativ CA kerak bo'lsa uni `.env` ga yozing
(`API_SSL_VERIFY=<CA fayl yo'li>` yoki `SSL_CERT_FILE=`). Proxy
(`HTTPS_PROXY`, `NO_PROXY`) muhitdan ham o'qiladi — ataylab: soxta CA'siz
proxy TLS trafigini o'qiy olmaydi, korporativ tarmoqda esa u kerak.

`device_id` saqlanishi SHART: u serverdagi qurilma yozuvining kaliti,
yo'qolsa qayta o'rnatilgan mashina administrator tasdig'ini
qaytadan kutadi.

### Avtostart

Task Scheduler vazifasi `ProctoringClient` — istalgan foydalanuvchi
kirganda, 10 s kechikish bilan, **eng yuqori mavjud huquqda**,
muddatsiz, normal ustuvorlikda. Nima uchun `HKLM\...\Run` emas:
Run kaliti dasturni har doim cheklangan tokenda ochadi, tahdid
skaneri esa xizmatlarni to'xtatish uchun administrator huquqini talab
qiladi; vazifaning standart sozlamalari esa jarayonni 72 soatda
o'ldiradi va ustuvorlikni pasaytiradi. Tafsilot — `autostart.ps1`.

### VC++ runtime

Bundle VC++ runtime DLL'larini o'zi bilan olib keladi (app-local,
14.44). Tizimdagi runtime juda eski bo'lsa (onnxruntime 1.2x eski
`msvcp140` bilan `std::mutex` da qulaydi), `installer\redist\vc_redist.x64.exe`
ni qo'ying (https://aka.ms/vs/17/release/vc_redist.x64.exe; git'da yo'q) —
build uni Microsoft imzosini tekshirib qo'shadi va o'rnatuvchi tizim
runtime'i 14.40 dan eski (yoki yo'q) bo'lgandagina, fayllardan OLDIN,
`/install /quiet /norestart` bilan ishga tushiradi (3010 — oxirida qayta
yuklash taklifi; boshqa xato — ogohlantirish, to'siq emas). Fayl
bo'lmasa build sariq ogohlantiradi, o'rnatuvchi esa faqat ESKI runtime
haqida ogohlantiradi.

## Kod imzosi va antivirus

Imzo ixtiyoriy va muhit o'zgaruvchisi bilan yoqiladi (sertifikat/parol
skriptda va git'da yo'q):

```powershell
$env:SIGN_CERT_THUMBPRINT = "<sertifikat izi>"          # CurrentUser\My (EV token ham)
# $env:SIGN_MACHINE_STORE = "1"                          # LocalMachine\My
# $env:SIGN_TIMESTAMP_URL = "http://timestamp.digicert.com"
# $env:SIGNTOOL_PATH = "C:\...\signtool.exe"           # standart: Windows Kits\10\bin\*\x64
powershell -ExecutionPolicy Bypass -File installer\build.ps1 -Gpu [-SignAllUnsigned]
```

Imzolanadi: `ProctoringClient.exe`, `ProctoringClientCheck.exe`
(tutun tekshiruvidan OLDIN), `-SignAllUnsigned` bilan `_internal` dagi
imzosiz modullar, `setup.exe` va uninstaller (ISCC `SignTool=`,
`SignedUninstaller=yes`). Har fayl `signtool verify /pa` dan o'tadi.
Iz berilmasa — hech narsa qilinmaydi (sariq ogohlantirish).

Tavsiyalar (false-positive'ni kamaytiradi):

* **OV/EV sertifikat** (EV SmartScreen reputatsiyasini darhol beradi) +
  **vaqt tamg'asi** (usiz imzo sertifikat muddati bilan o'ladi).
* **UPX yo'q** (spec'da `upx=False`), `onefile` yo'q — "packed/dropper"
  evristikasining asosiy sabablari. Boshqa packer/obfuskator qo'shmang.
* **VERSIONINFO** har `.exe` da (`version.py`), nashriyot nomi hamma
  joyda bir xil — `COMPANY_NAME` imzo egasi (Subject O=) bilan mos bo'lsin.
* Har yangi versiyani tarqatishdan oldin **Microsoft Security
  Intelligence** portaliga yuboring (https://www.microsoft.com/wdsi/filesubmission,
  "Software developer": setup.exe + ProctoringClient.exe) va VirusTotal'da
  tekshiring.
* Imtihon mashinalarida (GPO) `C:\Program Files\ProctoringClient` ni
  Defender istisnosiga qo'shish — oxirgi chora, imzo o'rniga emas.

## Ma'lum cheklovlar

* Sertifikatsiz build IMZOLANMAGAN — SmartScreen ogohlantiradi va
  ba'zi antiviruslar PyInstaller bootloader'ini shubhali deb belgilaydi
  (yuqoridagi bo'lim).
* Inno Setup'da siqilgan hajm ~2.1 GB dan oshsa `DiskSpanning=yes`
  kerak bo'ladi (bir nechta `.bin`). Hozirgi GPU nashri chegaradan
  past.



## GPU uchun bitta parametrni qo'shishni maslahat beraman:

installer\build-gpu-install.bat -Clean -RequireGpuSmoke
installer\build-cpu-install.bat -Clean

- -RequireGpuSmoke — .bat buni o'zi qo'shmaydi. Usiz GPU build'da CUDA ishlamay qolsa, build baribir "tayyor" deydi va installer jimgina CPU'da ishlaydi. Bu parametr bilan bunday holatda build yiqiladi. Uni GPU'li mashinada ishlating — hozirgi kompyuteringiz (GTX 1660 SUPER) mos keladi, men aynan shu yerda tekshirganman.
- -Clean — reliz uchun PyInstaller keshini tozalaydi, eski fayllar build'ga aralashmaydi.
