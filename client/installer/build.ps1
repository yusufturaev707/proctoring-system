<#
.SYNOPSIS
    Proctoring Client: PyInstaller (onedir) + Inno Setup o'rnatuvchisi.

.DESCRIPTION
    Qadamlar:
      1. venv va build vositalarini tekshirish (-InstallBuildDeps o'rnatadi);
      2. onnxruntime paketi nashrga mosligini tekshirish (GPU -> provayder DLL);
      3. PyInstaller spec -> dist\<nashr>\ProctoringClient\;
         3a. models_manifest.json (.exe yonida, model yaxlitligi);
         3b. kod imzosi - SIGN_CERT_THUMBPRINT berilganda (tools\sign.ps1;
             -RequireSign bilan izsiz build boshlanmaydi);
      4. ProctoringClientCheck.exe bilan tutun tekshiruvi (-SkipSmoke o'chiradi);
      5. Inno Setup (ISCC.exe) topilsa -> dist\installer\ProctoringClientSetup-<ver>-<nashr>.exe
         (imzo bilan: setup.exe va uninstaller ham ISCC ichida imzolanadi)

    SERVER MANZILI O'RNATUVCHIGA BUILD PAYTIDA JOYLANADI: installer\client.env
    (yoki -EnvFile) tekshiriladi va setup.exe ichiga qo'yiladi - o'rnatishda
    API/WebSocket manzili so'ralmaydi. Birinchi marta:
        copy installer\env.production.template installer\client.env
    va undagi @API_BASE_URL@ / @WS_BASE_URL@ ni to'ldiring.

    FAYL FAQAT ASCII: Windows PowerShell 5.1 BOM'siz faylni tizim kod
    sahifasida o'qiydi va UTF-8 dagi har qanday belgi (tire, qo'shtirnoq)
    buzilib, skript sintaksis xatosi bilan yiqiladi.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File installer\build.ps1 -Gpu
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File installer\build.ps1 -Cpu -InstallBuildDeps
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File installer\build.ps1 -Gpu -SkipInstaller -RequireGpuSmoke
#>
[CmdletBinding()]
param(
    # Nashr. Ikkalasi ham berilmasa -Gpu.
    [switch]$Gpu,
    [switch]$Cpu,

    # Python muhiti (standart: client\venv).
    [string]$Venv = "",

    # requirements-build*.txt ni venv ga o'rnatish.
    [switch]$InstallBuildDeps,

    # PyInstaller keshini tozalab yig'ish (hook yoki paket o'zgarganda).
    [switch]$Clean,

    # Faqat .exe; o'rnatuvchi yig'ilmaydi.
    [switch]$SkipInstaller,

    # Tutun tekshiruvini o'tkazib yuborish.
    [switch]$SkipSmoke,

    # Tutun tekshiruvida CUDA ishlamasa build'ni yiqitish (GPU'li build mashinasida).
    [switch]$RequireGpuSmoke,

    # buffalo_l ning ishlatilmaydigan modellarini ham qo'shish (1k3d68, genderage).
    [switch]$FullBuffalo,

    # ProctoringClientCheck.exe ni yig'maslik.
    [switch]$NoCheckExe,

    # ISCC.exe ga ochiq yo'l.
    [string]$IsccPath = "",

    # O'rnatuvchiga joylanadigan tayyor .env (standart: installer\client.env).
    # Bir nechta o'rnatish (viloyat/markaz) bo'lsa - har biriga alohida fayl.
    [string]$EnvFile = "",

    # Imzolashda _internal dagi IMZOSIZ PE fayllarni (.dll/.pyd/.exe) ham
    # imzolash. Faqat SIGN_CERT_THUMBPRINT berilganda ishlaydi.
    [switch]$SignAllUnsigned,

    # O'rnatuvchi imzolovchi self-signed sertifikatni mashina omborlariga
    # (Root, TrustedPublisher) QO'SHMASIN - ishonch GPO orqali tarqatilsa.
    [switch]$NoCertTrust,

    # Reliz build: SIGN_CERT_THUMBPRINT bo'lmasa build BOSHLANMAYDI.
    # Usiz iz yo'qligi faqat sariq ogohlantirish va imzosiz o'rnatuvchi
    # 20 daqiqalik build oxirida jimgina tarqatishga ketishi mumkin edi.
    [switch]$RequireSign
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

function Write-Step([string]$Text) {
    Write-Host ""
    Write-Host ("==> " + $Text) -ForegroundColor Cyan
}

function Fail([string]$Text) {
    Write-Host ("XATO: " + $Text) -ForegroundColor Red
    exit 1
}

# --------------------------------------------------------------------------
# Kod imzosi (ixtiyoriy) - bajaruvchi tools\sign.ps1
# --------------------------------------------------------------------------
# Sertifikat berilmasa HECH NARSA qilinmaydi (dev va sinov build'lari);
# -RequireSign bunga yo'l qo'ymaydi. Muhit o'zgaruvchilari va signtool'ni
# topish - sign.ps1 da (SIGN_CERT_THUMBPRINT, SIGN_MACHINE_STORE,
# SIGN_TIMESTAMP_URL, SIGNTOOL_PATH). Parol va kalit fayli skriptda/git'da
# yo'q: kalit sertifikat omborida.
#
# Imzolash BITTA joyda: .exe/modullar ham, ISCC (setup.exe + uninstaller)
# ham sign.ps1 ni chaqiradi - signtool argumentlari (vaqt tamg'asi!) ikki
# nusxada yashab, bir-biridan ajralib ketmasligi uchun.
$SignThumbprint = ""
if ($env:SIGN_CERT_THUMBPRINT) { $SignThumbprint = ($env:SIGN_CERT_THUMBPRINT -replace "[^0-9A-Fa-f]", "") }
$SignScript = Join-Path (Split-Path -Parent $PSScriptRoot) "tools\sign.ps1"

if ($RequireSign -and -not $SignThumbprint) {
    Fail ("-RequireSign: SIGN_CERT_THUMBPRINT o'rnatilmagan - build boshlanmadi.`n" +
          "  Sertifikat: tools\create_codesign_cert.ps1, batafsil docs\CODESIGN.md")
}
if ($SignThumbprint -and -not (Test-Path -LiteralPath $SignScript)) {
    Fail ("Imzolash skripti topilmadi: " + $SignScript)
}

function Invoke-CodeSign([string[]]$Paths, [string]$What, [switch]$Quiet) {
    if (-not $SignThumbprint) { return }
    if (-not $Paths -or $Paths.Count -eq 0) { return }
    Write-Host ("Imzolash: " + $What + " (" + $Paths.Count + " fayl)")
    $signArgs = @{ Path = $Paths; Description = "Proctoring Client" }
    if ($Quiet) { $signArgs["QuietVerify"] = $true }
    & $SignScript @signArgs
    if ($LASTEXITCODE -ne 0) { Fail ("Kod imzosi yiqildi (" + $What + ")") }
}

# --------------------------------------------------------------------------
# Nashr va yo'llar
# --------------------------------------------------------------------------
if ($Gpu -and $Cpu) { Fail "-Gpu va -Cpu birga berilmaydi." }
$Variant = "gpu"
if ($Cpu) { $Variant = "cpu" }

$InstallerDir = $PSScriptRoot
$ClientDir = Split-Path -Parent $InstallerDir
if (-not $Venv) { $Venv = Join-Path $ClientDir "venv" }
$Python = Join-Path $Venv "Scripts\python.exe"
$Spec = Join-Path $InstallerDir "proctoring_client.spec"
$Iss = Join-Path $InstallerDir "proctoring_client.iss"
$DistRoot = Join-Path $ClientDir "dist"
$DistDir = Join-Path $DistRoot $Variant
$WorkDir = Join-Path (Join-Path $ClientDir "build") $Variant
$AppDir = Join-Path $DistDir "ProctoringClient"
$InstallerOut = Join-Path $DistRoot "installer"

Write-Host ("Nashr: " + $Variant.ToUpper() + "   client: " + $ClientDir)

# --------------------------------------------------------------------------
# 0. O'rnatuvchiga joylanadigan .env
# --------------------------------------------------------------------------
# PyInstaller'dan OLDIN tekshiriladi: xato manzil 5 daqiqalik build va
# siqishdan keyin emas, darhol aytilishi kerak. Eng yomon holat esa
# umuman boshqa - manzili buzuq setup.exe 500 mashinaga tarqalib, ularning
# hech biri serverga ulanmaydi.
function Get-EnvValue([string[]]$Lines, [string]$Key) {
    foreach ($line in $Lines) {
        if ($line -match ("^\s*" + [regex]::Escape($Key) + "\s*=(.*)$")) { return $Matches[1].Trim() }
    }
    return $null
}

$EnvStaged = $null
if (-not $SkipInstaller) {
    Write-Step "O'rnatuvchi .env"
    if (-not $EnvFile) { $EnvFile = Join-Path $InstallerDir "client.env" }
    if (-not (Test-Path $EnvFile)) {
        Fail ("Tayyor .env topilmadi: " + $EnvFile + "`n  copy installer\env.production.template installer\client.env`n  va undagi API_BASE_URL / WS_BASE_URL ni to'ldiring (yoki -EnvFile <yo'l>).")
    }
    # UTF-8 (BOM'li yoki BOM'siz) - python-dotenv ham shunday o'qiydi.
    $envLines = [System.IO.File]::ReadAllLines((Resolve-Path $EnvFile).Path, [System.Text.Encoding]::UTF8)

    $leftover = @($envLines | Where-Object { $_ -notmatch "^\s*#" -and $_ -match "@[A-Z_]+@" -and $_ -notmatch "@INVENTORY_CODE@" })
    if ($leftover.Count -gt 0) {
        Fail ("To'ldirilmagan o'rinbosar: " + ($leftover -join "; ") + "  (" + $EnvFile + ")")
    }

    $api = Get-EnvValue $envLines "API_BASE_URL"
    $ws = Get-EnvValue $envLines "WS_BASE_URL"
    $ssl = Get-EnvValue $envLines "API_SSL_VERIFY"
    if (-not $api -or $api -notmatch "^https?://[^/\s]+") {
        Fail ("API_BASE_URL yo'q yoki http(s):// bilan boshlanmaydi: '" + $api + "'  (" + $EnvFile + ")")
    }
    if ($ws -and $ws -notmatch "^wss?://[^/\s]+") {
        Fail ("WS_BASE_URL ws:// yoki wss:// bilan boshlanishi kerak (yoki bo'sh): '" + $ws + "'")
    }
    Write-Host ("  API_BASE_URL = " + $api)
    if ($ws) { Write-Host ("  WS_BASE_URL  = " + $ws) } else { Write-Host "  WS_BASE_URL  = (bo'sh - API manzilidan chiqariladi)" }

    # Ogohlantirishlar - to'xtatmaydi (sinov o'rnatuvchisi ham kerak
    # bo'ladi), lekin imtihon mashinasiga ketadigan build'da ular xato.
    $warnings = @()
    if ($api -match "^https?://(127\.|localhost|\[::1\])") { $warnings += "API_BASE_URL loopback - boshqa mashinada ishlamaydi" }
    if ($api -match "^http://") { $warnings += "API_BASE_URL HTTPS emas" }
    if ($ssl -in @("0", "false", "False", "no")) { $warnings += "API_SSL_VERIFY=0 - TLS tekshiruvi o'chiq" }
    foreach ($key in @("FULLSCREEN", "KIOSK_MODE", "CLOSE_OTHER_APPS", "THREAT_SCAN_ENABLED", "DISABLE_EXTRA_MONITORS")) {
        if ((Get-EnvValue $envLines $key) -in @("0", "false", "False", "no")) { $warnings += ($key + "=false - kiosk himoyasi o'chiq") }
    }
    foreach ($w in $warnings) { Write-Host ("  DIQQAT: " + $w) -ForegroundColor Yellow }

    # INVENTORY_CODE - mashinaga xos, o'rnatishda so'raladi. Fayldagi
    # qiymat (agar bo'lsa) o'rinbosar bilan ALMASHTIRILADI: bitta kod 500
    # mashinaga tarqalsa, server ularning hammasini bitta kompyuter deb
    # bilardi.
    $staged = New-Object System.Collections.Generic.List[string]
    $hasInventory = $false
    foreach ($line in $envLines) {
        if ($line -match "^\s*INVENTORY_CODE\s*=") {
            if ($hasInventory) { continue }
            $staged.Add("INVENTORY_CODE=@INVENTORY_CODE@")
            $hasInventory = $true
        } else {
            $staged.Add($line)
        }
    }
    if (-not $hasInventory) {
        $staged.Add("")
        $staged.Add("# Mashinaning inventar kodi (o'rnatishda kiritiladi, ixtiyoriy).")
        $staged.Add("INVENTORY_CODE=@INVENTORY_CODE@")
    }
    $StageDir = Join-Path (Join-Path $ClientDir "build") $Variant
    New-Item -ItemType Directory -Force -Path $StageDir | Out-Null
    $EnvStaged = Join-Path $StageDir "client.env"
    [System.IO.File]::WriteAllLines($EnvStaged, $staged, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host ("  manba: " + $EnvFile)
}

# --------------------------------------------------------------------------
# 1. Python muhiti
# --------------------------------------------------------------------------
Write-Step "Python muhiti"
if (-not (Test-Path $Python)) {
    Fail ("venv topilmadi: " + $Python + "`n  cd client; python -m venv venv; venv\Scripts\python -m pip install -r requirements.txt")
}
& $Python --version
if ($LASTEXITCODE -ne 0) { Fail "python ishga tushmadi" }

if ($InstallBuildDeps) {
    $req = Join-Path $InstallerDir "requirements-build.txt"
    if ($Variant -eq "gpu") { $req = Join-Path $InstallerDir "requirements-build-gpu.txt" }
    Write-Step ("Build bog'liqliklari: " + $req)
    & $Python -m pip install -r $req
    if ($LASTEXITCODE -ne 0) { Fail "pip install yiqildi" }
}

& $Python -c "import PyInstaller, sys; sys.stdout.write('PyInstaller ' + PyInstaller.__version__)"
if ($LASTEXITCODE -ne 0) {
    Fail "PyInstaller o'rnatilmagan. -InstallBuildDeps bilan ishga tushiring yoki: venv\Scripts\python -m pip install -r installer\requirements-build.txt"
}
Write-Host ""

# --------------------------------------------------------------------------
# 2. onnxruntime nashri
# --------------------------------------------------------------------------
# GPU nashri CUDA provayder DLL'isiz yig'ilsa, natija CPU'da ishlaydi va
# buni hech kim sezmaydi (cuda_runtime.py docstring'i) - shuning uchun
# bu yerda to'xtatamiz, spec'ga yetib bormasdan.
$HasCuda = & $Python -c "import onnxruntime, pathlib; p = pathlib.Path(onnxruntime.__file__).parent / 'capi' / 'onnxruntime_providers_cuda.dll'; print(int(p.is_file()))"
if ($LASTEXITCODE -ne 0) { Fail "onnxruntime import qilinmadi" }
if ($Variant -eq "gpu" -and $HasCuda.Trim() -ne "1") {
    Fail "GPU nashri so'raldi, lekin venv'da onnxruntime ning CPU paketi. onnxruntime-gpu==1.22.0 o'rnating yoki -Cpu."
}
# IKKI PAKET BIR PAPKADA. `insightface` metadata'sida `onnxruntime` bor va
# `pip install -r requirements.txt` CPU paketini (eng yangisi) GPU paketi
# USTIGA yozadi: `onnxruntime/` papkasi umumiy, `.pyd` CPU'niki bo'ladi,
# eski `onnxruntime_providers_cuda.dll` esa qoladi — yuqoridagi tekshiruv
# o'tadi, build esa GPU'siz chiqadi (28.10.2026 dev venv'da shunday bo'ldi).
$OrtDists = & $Python -c "from importlib import metadata as m; import onnxruntime as o; d = [n for n in ('onnxruntime', 'onnxruntime-gpu') if any(x.metadata['Name'] == n for x in m.distributions())]; print(','.join(d) + '|' + o.__version__)"
if ($LASTEXITCODE -ne 0) { Fail "onnxruntime paketlari o'qilmadi" }
$OrtNames, $OrtVersion = $OrtDists.Trim().Split("|")
if ($OrtNames -eq "onnxruntime,onnxruntime-gpu") {
    Fail ("venv'da onnxruntime (CPU, $OrtVersion) va onnxruntime-gpu BIRGA - CPU fayllari GPU paketini bosib ketgan. Tuzatish: " +
          "venv\Scripts\python -m pip uninstall -y onnxruntime; " +
          "venv\Scripts\python -m pip install --force-reinstall --no-deps onnxruntime-gpu==1.22.0")
}

# Yo'l muhit o'zgaruvchisi orqali: satr ichiga qo'yilsa, yo'ldagi
# apostrof (Windows foydalanuvchi nomlarida uchraydi) Python satrini buzardi.
$env:PROCTORING_CLIENT_DIR = $ClientDir
$Version = & $Python -c "import os, runpy; print(runpy.run_path(os.path.join(os.environ['PROCTORING_CLIENT_DIR'], 'version.py'))['__version__'])"
if ($LASTEXITCODE -ne 0) { Fail "version.py o'qilmadi" }
$Version = $Version.Trim()
Write-Host ("Versiya: " + $Version)

# --------------------------------------------------------------------------
# 3. PyInstaller
# --------------------------------------------------------------------------
Write-Step "PyInstaller (onedir)"
$pyiArgs = @("-m", "PyInstaller", $Spec, "--noconfirm", "--distpath", $DistDir, "--workpath", $WorkDir)
if ($Clean) { $pyiArgs += "--clean" }
$pyiArgs += @("--", "--variant", $Variant)
if ($FullBuffalo) { $pyiArgs += "--full-buffalo" }
if ($NoCheckExe) { $pyiArgs += "--no-check-exe" }

$started = Get-Date
Push-Location $ClientDir
try {
    & $Python @pyiArgs
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($code -ne 0) { Fail ("PyInstaller yiqildi (kod " + $code + "). Log: " + $WorkDir) }
$elapsed = (Get-Date) - $started
Write-Host ("PyInstaller: {0:N1} daqiqa" -f $elapsed.TotalMinutes)

$MainExe = Join-Path $AppDir "ProctoringClient.exe"
if (-not (Test-Path $MainExe)) { Fail ("Natija topilmadi: " + $MainExe) }

# Hajm - GPU va CPU nashri orasidagi farq aynan shu yerda ko'rinadi.
$files = Get-ChildItem -Path $AppDir -Recurse -File
$total = ($files | Measure-Object -Property Length -Sum).Sum
Write-Host ("Bundle: {0:N0} MB, {1} fayl" -f ($total / 1MB), $files.Count)
foreach ($sub in @("_internal\cuda", "_internal\models", "_internal\PyQt6", "_internal\onnxruntime")) {
    $p = Join-Path $AppDir $sub
    if (Test-Path $p) {
        $s = (Get-ChildItem -Path $p -Recurse -File | Measure-Object -Property Length -Sum).Sum
        Write-Host ("  {0,-24} {1,8:N0} MB" -f $sub, ($s / 1MB))
    }
}
# O'rnatuvchining disk tekshiruvi uchun (ISCC /DBundleMB) - manifest va
# imzodan keyingi o'sish ahamiyatsiz (KB).
$BundleMB = [int][Math]::Ceiling($total / 1MB)

# --------------------------------------------------------------------------
# 3a. Model manifesti (models_manifest.json, .exe yonida)
# --------------------------------------------------------------------------
# Client ishga tushishda modellar yaxlitligini shu fayl bilan tekshiradi.
# Tutun tekshiruvidan OLDIN: u manifestni bundle bilan solishtiradi.
Write-Step "Model manifesti"
& $Python (Join-Path $InstallerDir "make_models_manifest.py") --app-dir $AppDir
if ($LASTEXITCODE -ne 0) { Fail "models_manifest.json yozilmadi" }

# --------------------------------------------------------------------------
# 3b. Kod imzosi (SIGN_CERT_THUMBPRINT bo'lmasa - o'tkazib yuboriladi)
# --------------------------------------------------------------------------
# Tutun tekshiruvidan OLDIN: tekshiruv aynan tarqatiladigan (imzolangan)
# fayllar ustida o'tishi kerak. UPX yo'q (spec) - imzo siqilgan faylni
# buzmaydi.
if ($SignThumbprint) {
    Write-Step "Kod imzosi"
    Invoke-CodeSign @($MainExe, (Join-Path $AppDir "ProctoringClientCheck.exe") | Where-Object { Test-Path $_ }) "client .exe"
    if ($SignAllUnsigned) {
        # Uchinchi tomon DLL'larining ko'pchiligi (Qt, ORT, CUDA, python312)
        # o'z nashriyoti imzosi bilan keladi - ularga TEGILMAYDI. Imzosiz
        # qolganlari (.pyd, ba'zi DLL'lar) bizning imzo bilan yopiladi:
        # antivirus evristikasi "imzosiz modul yuklayotgan imzolangan exe"
        # ni ham shubhali deb biladi.
        $unsigned = @(Get-ChildItem -Path (Join-Path $AppDir "_internal") -Recurse -File -Include *.dll, *.pyd, *.exe |
            Where-Object { (Get-AuthenticodeSignature -FilePath $_.FullName).Status -eq "NotSigned" } |
            ForEach-Object { $_.FullName })
        # Yuzlab fayl: `verify /v` logni har fayl uchun o'nlab qatorga to'ldirardi.
        Invoke-CodeSign $unsigned "_internal dagi imzosiz modullar" -Quiet
    }
} else {
    Write-Host ""
    Write-Host "Kod imzosi: SIGN_CERT_THUMBPRINT yo'q - imzolanmadi (SmartScreen/antivirus ogohlantirishi mumkin)." -ForegroundColor Yellow
}

# --------------------------------------------------------------------------
# 4. Tutun tekshiruvi
# --------------------------------------------------------------------------
$CheckExe = Join-Path $AppDir "ProctoringClientCheck.exe"
if (-not $SkipSmoke -and -not $NoCheckExe) {
    Write-Step "Tutun tekshiruvi (ProctoringClientCheck.exe)"
    $report = Join-Path $WorkDir "smoke-report.txt"
    $checkArgs = @("--report", $report)
    if ($RequireGpuSmoke) { $checkArgs += "--require-gpu" }
    & $CheckExe @checkArgs
    if ($LASTEXITCODE -ne 0) { Fail ("Tutun tekshiruvi yiqildi. Hisobot: " + $report) }
}

# --------------------------------------------------------------------------
# 5. Inno Setup
# --------------------------------------------------------------------------
if ($SkipInstaller) {
    Write-Host ""
    Write-Host ("Tayyor (o'rnatuvchisiz): " + $AppDir) -ForegroundColor Green
    exit 0
}

Write-Step "Inno Setup"
$candidates = @()
if ($IsccPath) { $candidates += $IsccPath }
if (${env:ProgramFiles(x86)}) { $candidates += (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe") }
if ($env:ProgramFiles) { $candidates += (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe") }
foreach ($key in @("HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
                   "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
                   "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1")) {
    $item = Get-ItemProperty -Path $key -ErrorAction SilentlyContinue
    if ($item -and $item.PSObject.Properties["InstallLocation"]) {
        $candidates += (Join-Path $item.InstallLocation "ISCC.exe")
    }
}
$cmd = Get-Command "iscc.exe" -ErrorAction SilentlyContinue
if ($cmd) { $candidates += $cmd.Source }

$Iscc = $null
foreach ($c in $candidates) {
    if ($c -and (Test-Path $c)) { $Iscc = $c; break }
}
if (-not $Iscc) {
    Write-Host "Inno Setup 6 topilmadi - o'rnatuvchi YIG'ILMADI." -ForegroundColor Yellow
    Write-Host "  https://jrsoftware.org/isdl.php dan o'rnating yoki -IsccPath bering."
    Write-Host ("  Bundle tayyor: " + $AppDir)
    exit 2
}
Write-Host ("ISCC: " + $Iscc)

# Windows versiya resursi faqat raqamlarni qabul qiladi: "1.2.0-rc1" -> "1.2.0".
$VersionNumeric = ($Version -split "-")[0]
$isccArgs = @(
    "/Qp",
    ("/DAppVersion=" + $Version),
    ("/DAppVersionNumeric=" + $VersionNumeric),
    ("/DVariant=" + $Variant),
    ("/DSourceDir=" + $AppDir),
    ("/DEnvSource=" + $EnvStaged),
    ("/DOutputDir=" + $InstallerOut),
    ("/DBundleMB=" + $BundleMB)
)
# Nashriyot nomi version.py dan - .exe resursi (spec), setup.exe resursi
# va "Programs and Features" dagi nom BIR XIL bo'lishi kerak: antivirus
# reputatsiyasi va imzo egasi bilan solishtirish shu nomga tayanadi.
$Publisher = & $Python -c "import os, runpy; print(runpy.run_path(os.path.join(os.environ['PROCTORING_CLIENT_DIR'], 'version.py'))['COMPANY_NAME'])"
if ($LASTEXITCODE -eq 0 -and $Publisher) { $isccArgs += ("/DAppPublisher=" + $Publisher.Trim()) }
# PyInstaller spec'ning `workpath` i = <workpath>\<spec nomi>.
$icon = Join-Path $WorkDir "proctoring_client\app.ico"
if (Test-Path $icon) { $isccArgs += ("/DIconFile=" + $icon) }
$redist = Join-Path $InstallerDir "redist\vc_redist.x64.exe"
if (Test-Path $redist) {
    # Bu fayl 500 mashinada ADMINISTRATOR huquqida ishga tushadi -
    # Microsoft imzosisiz (buzilgan yoki almashtirilgan) nusxa
    # o'rnatuvchiga kirmasligi kerak.
    $sig = Get-AuthenticodeSignature -FilePath $redist
    if ($sig.Status -ne "Valid" -or -not $sig.SignerCertificate -or $sig.SignerCertificate.Subject -notmatch "O=Microsoft Corporation") {
        Fail ("redist\vc_redist.x64.exe Microsoft imzosi bilan emas (" + $sig.Status + "): " + $redist)
    }
    $isccArgs += ("/DVcRedist=" + $redist)
    Write-Host "VC++ runtime o'rnatuvchisi qo'shiladi: $redist"
} else {
    # Bundle runtime'ni app-local olib keladi, ya'ni bu to'siq emas. Lekin
    # tizimdagi runtime 14.40 dan ESKI bo'lsa o'rnatuvchi uni yangilay
    # olmaydi - faqat ogohlantiradi (proctoring_client.iss, VcRuntimeOld).
    Write-Host "DIQQAT: installer\redist\vc_redist.x64.exe yo'q - VC++ runtime o'rnatuvchiga qo'shilmadi." -ForegroundColor Yellow
    Write-Host "  https://aka.ms/vs/17/release/vc_redist.x64.exe (README, 'VC++ runtime')" -ForegroundColor Yellow
}
if ($SignThumbprint) {
    # setup.exe VA uninstaller'ni (unins000.exe) ISCC o'zi imzolaydi
    # (`SignTool=`, proctoring_client.iss): uninstaller build paytida emas,
    # ISCC ichida yasaladi, ya'ni uni keyin tashqaridan imzolab bo'lmaydi.
    # Buyruq - o'sha sign.ps1 (iz ISCC jarayoniga muhit orqali o'tadi).
    # `$f` (qo'shtirnoqli fayl nomi) / `$q` - ISCC o'rinbosarlari.
    $signCmd = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File $q' + $SignScript +
               '$q -Description $qProctoring Client$q -Path $f'
    $isccArgs += ("/Sproctoringsign=" + $signCmd)
    $isccArgs += "/DSignToolName=proctoringsign"

    # Imzolovchi sertifikatning OCHIQ qismi o'rnatuvchiga: u har mashinada
    # uni Root/TrustedPublisher ga qo'shadi (proctoring_client.iss,
    # TrustCodeSignCert) - domen/GPO'siz mashinalarda ham imzo "Valid".
    # `-Type CERT` - faqat ochiq kalit; maxfiy kalit ombordan chiqmaydi.
    # Sertifikat yangilansa yangi reliz yangisini o'zi olib boradi.
    if (-not $NoCertTrust) {
        $certStore = "CurrentUser"
        if ($env:SIGN_MACHINE_STORE -eq "1") { $certStore = "LocalMachine" }
        $signCert = Get-Item -Path ("Cert:\" + $certStore + "\My\" + $SignThumbprint) -ErrorAction SilentlyContinue
        if (-not $signCert) {
            Fail ("Imzolovchi sertifikat omborda topilmadi: " + $SignThumbprint)
        }
        if ($signCert.Subject -eq $signCert.Issuer) {
            $cerOut = Join-Path $WorkDir "bba-codesign.cer"
            Export-Certificate -Cert $signCert -FilePath $cerOut -Type CERT | Out-Null
            $isccArgs += ("/DCodeSignCert=" + $cerOut)
            Write-Host ("O'rnatuvchi sertifikatni mashina omboriga qo'shadi: " + $signCert.Subject)
        } else {
            # CA bergan (OV/EV) sertifikat ILDIZ emas - Root'ga qo'yish
            # noto'g'ri; uning ildizi Windows'da allaqachon bor.
            Write-Host "Sertifikat CA tomonidan berilgan - o'rnatuvchi uni ombor(lar)ga qo'shmaydi."
        }
    }
}
$isccArgs += $Iss

# Eski setup.exe band bo'lsa (sinash uchun ishga tushirilgan o'rnatuvchi,
# antivirus skaneri) ISCC 4 daqiqalik siqishdan KEYIN "Error 32" bilan
# yiqiladi. Oldindan tekshiramiz.
$setupTarget = Join-Path $InstallerOut ("ProctoringClientSetup-" + $Version + "-" + $Variant + ".exe")
if (Test-Path $setupTarget) {
    try {
        $stream = [System.IO.File]::Open($setupTarget, "Open", "ReadWrite", "None")
        $stream.Close()
    } catch {
        Fail ("Eski o'rnatuvchi band (ishlab turibdimi?): " + $setupTarget)
    }
}

$started = Get-Date
& $Iscc @isccArgs
if ($LASTEXITCODE -ne 0) { Fail ("ISCC yiqildi (kod " + $LASTEXITCODE + ")") }
$elapsed = (Get-Date) - $started

$setup = Join-Path $InstallerOut ("ProctoringClientSetup-" + $Version + "-" + $Variant + ".exe")
if (Test-Path $setup) {
    if ($SignThumbprint) {
        # Tayyor fayl ustida yakuniy tekshiruv: ISCC imzodan keyin faylni
        # o'zgartirgan bo'lsa (yoki imzolash jimgina o'tkazilgan bo'lsa) shu ushlaydi.
        & $SignScript -VerifyOnly -Path $setup
        if ($LASTEXITCODE -ne 0) { Fail ("setup.exe imzosi tekshiruvdan o'tmadi: " + $setup) }
        Write-Host "setup.exe imzolangan va tekshirildi."
    }
    $size = (Get-Item $setup).Length
    Write-Host ""
    Write-Host ("O'rnatuvchi: {0} ({1:N0} MB, {2:N1} daqiqa)" -f $setup, ($size / 1MB), $elapsed.TotalMinutes) -ForegroundColor Green
} else {
    Write-Host ("ISCC tugadi, lekin kutilgan fayl yo'q: " + $setup) -ForegroundColor Yellow
}
exit 0
