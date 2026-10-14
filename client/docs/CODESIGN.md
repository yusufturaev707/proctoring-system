# Kod imzosi (self-signed)

Proctoring Client fayllari agentlikning o'z sertifikati bilan imzolanadi.
Imzolangan dastur faqat sertifikat o'rnatilgan (ichki) kompyuterlarda
"ishonchli nashriyot" bo'lib ko'rinadi — tashqi dunyoda bu imzo hech narsa
bermaydi (SmartScreen reputatsiyasi uchun OV/EV sertifikat kerak).

Nima imzolanadi (`installer\build.ps1`, bajaruvchi `tools\sign.ps1`):

| Fayl | Qachon |
|---|---|
| `ProctoringClient.exe`, `ProctoringClientCheck.exe` | PyInstaller'dan keyin, tutun tekshiruvidan oldin |
| `_internal` dagi imzosiz `.dll/.pyd/.exe` | `-SignAllUnsigned` bilan (o'z nashriyoti imzolagan Qt/ORT/CUDA DLL'lariga tegilmaydi) |
| `ProctoringClientSetup-*.exe` va uninstaller | Inno Setup ichida (`SignTool=`, `SignedUninstaller=yes`) |

Har imzo SHA256, vaqt tamg'asi bilan (`/tr http://timestamp.digicert.com`)
va `signtool verify /pa` bilan tekshiriladi. Vaqt tamg'asi tufayli
sertifikat muddati tugagandan keyin ham ESKI build'lar imzosi yaroqli
qoladi.

## 1. Sertifikat yaratish (build mashinasida, bir marta)

Kerak: Windows SDK ("Signing Tools for Desktop Apps" — `signtool.exe`).

```powershell
cd client
powershell -ExecutionPolicy Bypass -File tools\create_codesign_cert.ps1 -TrustOnThisMachine
# zaxira bilan (tavsiya, .pfx repodan TASHQARIDA, parol klaviaturadan so'raladi):
powershell -ExecutionPolicy Bypass -File tools\create_codesign_cert.ps1 -TrustOnThisMachine -ExportPfx D:\keys\bba-codesign.pfx
```

* Sertifikat: `CN=BBA Proctoring Client, O=UZBMB`, RSA 3072, SHA256, 3 yil,
  `Cert:\CurrentUser\My`.
* `bba-codesign.cer` — OCHIQ kalit, mijozlarga tarqatiladi.
* Maxfiy kalit omborda qoladi; `-ExportPfx` siz u eksport qilinmaydi.
  `.pfx` ni oflayn saqlang — kalit kimning qo'lida bo'lsa, u agentlikning
  barcha kompyuterlari "ishonchli" deb qabul qiladigan istalgan dasturni
  imzolay oladi. `*.pfx` va `*.cer` `.gitignore` da.
* `-TrustOnThisMachine` — build mashinasining o'zi ham sertifikatga ishonishi
  shart, aks holda `signtool verify /pa` yiqiladi ("root certificate which is
  not trusted"). Windows tasdiq oynasini ko'rsatadi. Sertifikat boshqa joyda
  yaratilgan bo'lsa: `tools\create_codesign_cert.ps1 -TrustOnly -CerPath bba-codesign.cer`.

**Thumbprint (iz) qayerdan olinadi** — u sir emas:

* skript oxirida ekranga chiqaradi;
* `Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert | Format-List Subject, Thumbprint, NotAfter`;
* `certmgr.msc` → Personal → Certificates → sertifikat → Details → Thumbprint.

Boshqa build mashinasiga ko'chirish: `.pfx` ni `certmgr.msc` → Personal →
Import bilan qo'ying (yoki `Import-PfxCertificate -CertStoreLocation
Cert:\CurrentUser\My`), keyin `-TrustOnly`.

## 2. Build

```powershell
$env:SIGN_CERT_THUMBPRINT = "<iz>"     # yoki doimiy: setx SIGN_CERT_THUMBPRINT <iz>
powershell -ExecutionPolicy Bypass -File installer\build.ps1 -Gpu -RequireSign [-SignAllUnsigned]
# yoki: installer\build-gpu-install.bat -RequireSign
```

* `-RequireSign` — reliz build: iz bo'lmasa build BOSHLANMAYDI. Usiz iz
  yo'qligi faqat sariq ogohlantirish ("SIGN_CERT_THUMBPRINT yo'q -
  imzolanmadi") va imzosiz o'rnatuvchi chiqadi (dev build'lar uchun).
* Ixtiyoriy: `SIGN_MACHINE_STORE=1` (sertifikat `LocalMachine\My` da),
  `SIGN_TIMESTAMP_URL`, `SIGNTOOL_PATH`.
* Alohida faylni qo'lda imzolash/tekshirish:
  `tools\sign.ps1 <fayl>...`, `tools\sign.ps1 -VerifyOnly <fayl>`.

## 3. Mijoz kompyuterlariga o'rnatish

`.cer` IKKI omborga kerak: **Trusted Root Certification Authorities**
(zanjir ishonchli) va **Trusted Publishers** (nashriyot ishonchli — UAC va
dastur siyosatlari ogohlantirmaydi). Imtihon mashinasida bir nechta hisob
bo'lgani uchun **kompyuter** omboriga qo'ying (joriy foydalanuvchiniki emas).
Usiz imzo bor, lekin `Get-AuthenticodeSignature` `UnknownError` deydi.

### Avtomatik — o'rnatuvchi o'zi qo'shadi (standart)

Imzolangan build'da `build.ps1` imzolovchi sertifikatning OCHIQ qismini
(maxfiy kalitsiz) o'rnatuvchiga joylaydi, o'rnatuvchi esa har mashinada uni
`certutil -addstore` bilan kompyuterning Root va TrustedPublisher omboriga
qo'shadi (`proctoring_client.iss`, `TrustCodeSignCert`). Alohida tarqatish
kerak emas — client o'rnatilgan mashinada imzo darhol `Valid`.

* Faqat self-signed sertifikat qo'shiladi (CA bergan OV/EV — yo'q, uning
  ildizi Windows'da bor).
* Xato o'rnatishni to'xtatmaydi — ogohlantirish va o'rnatish log'ida
  `certutil -addstore ... kodi`.
* Uninstall sertifikatni olib TASHLAMAYDI (qo'lda: `certutil -delstore Root <iz>`
  va `certutil -delstore TrustedPublisher <iz>`).
* O'chirish: `build.ps1 ... -NoCertTrust` (ishonch GPO orqali tarqatilsa).
* Birinchi o'rnatishda UAC oynasi setup.exe'ni hali "noma'lum nashriyot"
  deydi — sertifikat aynan shu o'rnatish paytida qo'shiladi.

Quyidagi yo'llar — o'rnatuvchisiz tarqatish yoki `-NoCertTrust` uchun.

### Qo'lda (bitta kompyuter)

1. `certlm.msc` (Local Computer; `certmgr.msc` — faqat joriy foydalanuvchi).
2. Trusted Root Certification Authorities → Certificates → o'ng tugma →
   All Tasks → Import → `bba-codesign.cer`.
3. Xuddi shunday: Trusted Publishers → Certificates → Import.

Yoki administrator PowerShell/cmd'da (skript bilan ko'p mashinaga):

```bat
certutil -addstore -f Root bba-codesign.cer
certutil -addstore -f TrustedPublisher bba-codesign.cer
```

### Domen bo'lsa — GPO

1. `gpmc.msc` → imtihon kompyuterlari OU'siga bog'langan GPO → Edit.
2. Computer Configuration → Policies → Windows Settings → Security Settings →
   Public Key Policies:
   * **Trusted Root Certification Authorities** → Import → `bba-codesign.cer`;
   * **Trusted Publishers** → Import → `bba-codesign.cer`.
3. Mijozda `gpupdate /force` (yoki qayta yuklash).

### Tekshirish (mijozda)

```powershell
Get-ChildItem Cert:\LocalMachine\Root, Cert:\LocalMachine\TrustedPublisher |
    Where-Object Subject -like "*BBA Proctoring Client*"
Get-AuthenticodeSignature "C:\Program Files\ProctoringClient\ProctoringClient.exe"   # Status: Valid
```

## 4. Muddat tugashidan oldin yangilash

`tools\sign.ps1` 60 kun qolganda har build'da ogohlantiradi.

**O'rnatuvchi sertifikatni o'zi qo'shsa (standart)** — yangi reliz yangi
sertifikatni o'zi olib boradi:

1. Muddat tugashidan oldin yangi sertifikat:
   `tools\create_codesign_cert.ps1 -Force -TrustOnThisMachine [-ExportPfx ...]`
   (eski `.cer` bosilmaydi — yangisi `bba-codesign-<iz>.cer` bo'ladi).
2. `setx SIGN_CERT_THUMBPRINT <yangi iz>`, yangi terminal, odatdagidek build.
3. Yangi relizni mashinalarga o'rnating — har biri yangi sertifikatni
   oladi, eskisi ham omborda qoladi (eski build'lar vaqt tamg'asi tufayli
   yaroqli).
4. Build mashinasidan eski sertifikatni o'chiring (`certmgr.msc` → Personal).

**GPO bilan tarqatilsa** (`-NoCertTrust`) — eskisini olib tashlashdan OLDIN
yangisi hamma joyda bo'lishi kerak: yangi `.cer` ni GPO'ga ESKISI YONIGA
qo'shing, mijozlarga yetganini tekshiring, keyingina yangi iz bilan reliz
yig'ing; eski sertifikatni GPO'dan faqat barcha mashinalar yangi relizga
o'tgach oling.

**Kalit yo'qolsa yoki o'g'irlansa** — kutmasdan: eski sertifikatni
mijozlardan olib tashlang (GPO: Public Key Policies → **Untrusted
Certificates** ga qo'shing; GPO'siz — har mashinada `certutil -delstore Root
<eski iz>` va `certutil -delstore TrustedPublisher <eski iz>`), yangi
sertifikat yarating, yangi relizni imzolab tarqating.
