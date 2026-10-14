<#
.SYNOPSIS
    Authenticode imzosi: SIGN_CERT_THUMBPRINT sertifikati bilan fayllarni
    imzolaydi va `signtool verify /pa` bilan tekshiradi.

.DESCRIPTION
    Imzolashning YAGONA joyi: installer\build.ps1 (.exe va modullar) ham,
    Inno Setup (`SignTool=` - setup.exe va uninstaller) ham shu skriptni
    chaqiradi. Ikki joyda yozilgan signtool buyrug'i vaqt o'tib bir-biridan
    ajralib ketardi (biri vaqt tamg'asisiz qolsa, imzo sertifikat muddati
    bilan o'ladi).

    IZ BO'LMASA TO'XTAYDI (exit 1) va bu ataylab: skript chaqirilgan
    bo'lsa imzo kutilgan, jimgina o'tkazib yuborish esa imzosiz faylni
    tarqatishga olib kelardi. "Imzo ixtiyoriy" qarori build.ps1 da.

    Muhit o'zgaruvchilari (sir emas - kalit sertifikat omborida qoladi,
    parol skriptga ham, logga ham tushmaydi):
      SIGN_CERT_THUMBPRINT  sertifikat izi (MAJBURIY)
      SIGN_MACHINE_STORE=1  sertifikat LocalMachine\My da (standart CurrentUser\My)
      SIGN_TIMESTAMP_URL    RFC 3161 server (standart http://timestamp.digicert.com)
      SIGNTOOL_PATH         signtool.exe (standart: eng yangi Windows Kits\10\bin\<ver>\x64)

    FAYL FAQAT ASCII: Windows PowerShell 5.1 BOM'siz faylni tizim kod
    sahifasida o'qiydi.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\sign.ps1 dist\gpu\ProctoringClient\ProctoringClient.exe
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\sign.ps1 -VerifyOnly dist\installer\ProctoringClientSetup-1.0.3-gpu.exe
#>
[CmdletBinding()]
param(
    # Imzolanadigan fayllar (asosiy .exe, .dll/.pyd, installer).
    [Parameter(Mandatory = $true, Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$Path,

    # Imzodagi tavsif (Windows UAC oynasida "Program name").
    [string]$Description = "Proctoring Client",

    # Imzolamasdan faqat tekshirish (masalan ISCC yasagan setup.exe).
    [switch]$VerifyOnly,

    # `verify /v` o'rniga `/q` - yuzlab modulni imzolaganda log bitta
    # fayl uchun o'nlab qatorga to'lib ketmasligi uchun. Xato baribir chiqadi.
    [switch]$QuietVerify
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

function Fail([string]$Text) {
    Write-Host ("XATO (imzo): " + $Text) -ForegroundColor Red
    exit 1
}

# --------------------------------------------------------------------------
# 1. Sertifikat izi
# --------------------------------------------------------------------------
$thumbprint = ""
if ($env:SIGN_CERT_THUMBPRINT) {
    # certmgr.msc dan nusxalangan izda bo'shliq va ko'rinmas belgi bo'ladi.
    $thumbprint = ($env:SIGN_CERT_THUMBPRINT -replace "[^0-9A-Fa-f]", "").ToUpperInvariant()
}
# Tekshirish (-VerifyOnly) uchun iz kerak emas - u faqat imzolashda.
if (-not $thumbprint -and -not $VerifyOnly) {
    Fail ("SIGN_CERT_THUMBPRINT o'rnatilmagan - fayllar IMZOLANMADI.`n" +
          "  Sertifikat yo'q bo'lsa:  powershell -ExecutionPolicy Bypass -File tools\create_codesign_cert.ps1`n" +
          "  Keyin:                   `$env:SIGN_CERT_THUMBPRINT = '<iz>'`n" +
          "  Batafsil: docs\CODESIGN.md")
}
if (-not $VerifyOnly -and $thumbprint.Length -ne 40) {
    Fail ("SIGN_CERT_THUMBPRINT 40 ta hex belgi bo'lishi kerak (hozir " + $thumbprint.Length + ").")
}

$storeName = "CurrentUser"
if ($env:SIGN_MACHINE_STORE -eq "1") { $storeName = "LocalMachine" }

# --------------------------------------------------------------------------
# 2. Sertifikat omborda bormi va imzolay oladimi
# --------------------------------------------------------------------------
# signtool o'zi ham aytadi, lekin "SignerSign() failed" dan nima
# yetishmayotganini tushunib bo'lmaydi. Bu yerda sabab aniq.
if (-not $VerifyOnly) {
    $cert = Get-Item -Path ("Cert:\" + $storeName + "\My\" + $thumbprint) -ErrorAction SilentlyContinue
    if (-not $cert) {
        Fail ("Sertifikat " + $storeName + "\My omborida topilmadi: " + $thumbprint +
              "`n  Boshqa build mashinasi bo'lsa - .pfx zaxirasini import qiling (docs\CODESIGN.md).")
    }
    if (-not $cert.HasPrivateKey) {
        Fail ("Sertifikatning maxfiy kaliti shu mashinada yo'q (faqat .cer import qilingan): " + $thumbprint)
    }
    $codeSigningOid = "1.3.6.1.5.5.7.3.3"
    $ekus = @($cert.EnhancedKeyUsageList | ForEach-Object { $_.ObjectId })
    if ($ekus -notcontains $codeSigningOid) {
        Fail ("Sertifikat kod imzolash uchun emas (EKU Code Signing yo'q): " + $cert.Subject)
    }
    $now = Get-Date
    if ($cert.NotAfter -lt $now) {
        Fail ("Sertifikat muddati tugagan (" + $cert.NotAfter.ToString("yyyy-MM-dd") + ") - yangilang: docs\CODESIGN.md")
    }
    $daysLeft = [int]($cert.NotAfter - $now).TotalDays
    Write-Host ("Sertifikat: " + $cert.Subject + " | " + $thumbprint + " | " + $cert.NotAfter.ToString("yyyy-MM-dd") + " gacha")
    if ($daysLeft -lt 60) {
        # Yangi .cer mijozlarga build'dan OLDIN yetishi kerak (GPO bir necha
        # kun oladi) - ogohlantirish erta.
        Write-Host ("DIQQAT: sertifikat muddati " + $daysLeft + " kundan keyin tugaydi - yangilash tartibi docs\CODESIGN.md da.") -ForegroundColor Yellow
    }
}

# --------------------------------------------------------------------------
# 3. signtool.exe
# --------------------------------------------------------------------------
function Resolve-SignTool {
    if ($env:SIGNTOOL_PATH) {
        if (Test-Path -LiteralPath $env:SIGNTOOL_PATH) { return $env:SIGNTOOL_PATH }
        Fail ("SIGNTOOL_PATH topilmadi: " + $env:SIGNTOOL_PATH)
    }
    $roots = @()
    if (${env:ProgramFiles(x86)}) { $roots += (Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin") }
    if ($env:ProgramFiles) { $roots += (Join-Path $env:ProgramFiles "Windows Kits\10\bin") }
    $found = @()
    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        $found += @(Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue |
            ForEach-Object {
                $exe = Join-Path $_.FullName "x64\signtool.exe"
                $ver = $null
                # Papka nomi versiya ("10.0.22621.0"); satr sifatida
                # saralash "10.0.9" ni "10.0.22621" dan yuqori qo'yardi.
                if ([version]::TryParse($_.Name, [ref]$ver) -and (Test-Path -LiteralPath $exe)) {
                    New-Object PSObject -Property @{ Version = $ver; Path = $exe }
                }
            })
    }
    if ($found.Count -gt 0) {
        return ($found | Sort-Object Version -Descending | Select-Object -First 1).Path
    }
    $cmd = Get-Command "signtool.exe" -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    Fail "signtool.exe topilmadi: Windows SDK ('Windows SDK Signing Tools for Desktop Apps') o'rnating yoki SIGNTOOL_PATH bering."
}

$signTool = Resolve-SignTool
Write-Host ("signtool: " + $signTool)

# --------------------------------------------------------------------------
# 4. Fayllar
# --------------------------------------------------------------------------
$files = @()
foreach ($item in $Path) {
    if (-not $item) { continue }
    if (-not (Test-Path -LiteralPath $item -PathType Leaf)) { Fail ("Fayl topilmadi: " + $item) }
    $files += (Resolve-Path -LiteralPath $item).ProviderPath
}
if ($files.Count -eq 0) { Fail "Imzolanadigan fayl berilmadi." }

$timestamp = "http://timestamp.digicert.com"
if ($env:SIGN_TIMESTAMP_URL) { $timestamp = $env:SIGN_TIMESTAMP_URL }

$verifyFlag = "/v"
if ($QuietVerify) { $verifyFlag = "/q" }

# Bitta chaqiruvda ko'p fayl - vaqt tamg'asi serveriga kamroq murojaat,
# lekin buyruq satri ~32K bilan cheklangan: 50 tadan bo'lamiz.
for ($i = 0; $i -lt $files.Count; $i += 50) {
    $chunk = @($files[$i..([Math]::Min($i + 49, $files.Count - 1))])

    if (-not $VerifyOnly) {
        # Vaqt tamg'asi MAJBURIY (`/tr`): usiz imzo sertifikat muddati
        # tugashi bilan yaroqsiz bo'ladi. Tamg'a serveri vaqti-vaqti bilan
        # javob bermaydi - 3 marta urinamiz, aks holda butun build yiqiladi.
        $signArgs = @("sign", "/sha1", $thumbprint, "/fd", "SHA256", "/tr", $timestamp, "/td", "SHA256",
                      "/d", $Description)
        if ($storeName -eq "LocalMachine") { $signArgs += "/sm" }
        $ok = $false
        for ($attempt = 1; $attempt -le 3; $attempt++) {
            & $signTool @signArgs @chunk
            if ($LASTEXITCODE -eq 0) { $ok = $true; break }
            if ($attempt -lt 3) {
                Write-Host ("signtool sign yiqildi (urinish " + $attempt + "/3) - 10 s dan keyin qayta...") -ForegroundColor Yellow
                Start-Sleep -Seconds 10
            }
        }
        if (-not $ok) { Fail ("signtool sign yiqildi: " + ($chunk -join ", ")) }
    }

    & $signTool verify /pa $verifyFlag @chunk
    if ($LASTEXITCODE -ne 0) {
        # Self-signed sertifikatda eng ko'p uchraydigan sabab: build
        # mashinasining o'zi sertifikatga ishonmaydi ("terminated in a root
        # certificate which is not trusted").
        Fail ("signtool verify /pa yiqildi: " + ($chunk -join ", ") +
              "`n  Self-signed sertifikat bo'lsa, u shu mashinada ham Trusted Root va Trusted Publishers'da bo'lishi kerak:" +
              "`n  tools\create_codesign_cert.ps1 -TrustOnly -CerPath bba-codesign.cer  (docs\CODESIGN.md)")
    }
}

$verb = "imzolandi va tekshirildi"
if ($VerifyOnly) { $verb = "imzosi tekshirildi" }
Write-Host ("Kod imzosi: " + $files.Count + " fayl " + $verb + ".") -ForegroundColor Green
exit 0
