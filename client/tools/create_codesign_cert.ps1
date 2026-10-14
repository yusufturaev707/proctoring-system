<#
.SYNOPSIS
    Proctoring Client uchun self-signed kod imzolash sertifikatini yaratadi.

.DESCRIPTION
    Sertifikat (RSA 3072, SHA256, 3 yil) Cert:\CurrentUser\My ga yoziladi,
    izi (thumbprint) ekranga chiqadi, OCHIQ kalit bba-codesign.cer bo'lib
    eksport qilinadi - u mijoz kompyuterlariga tarqatiladi (docs\CODESIGN.md).

    MAXFIY KALIT:
      * standart holatda EKSPORT QILINMAYDIGAN (NonExportable) - u faqat
        shu build mashinasining omborida yashaydi;
      * -ExportPfx berilsa - eksport qilinadigan bo'lib yaratiladi va .pfx
        zaxirasi yoziladi. Parol KLAVIATURADAN so'raladi (ikki marta),
        skriptga, muhitga va logga yozilmaydi. .pfx git ombori ichiga
        yozilmaydi (skript rad etadi) va *.pfx .gitignore da.

    Zaxirasiz kalit yo'qolsa (disk, qayta o'rnatish) yangi sertifikat va
    uni BARCHA mijoz kompyuterlariga qayta tarqatish kerak bo'ladi -
    shuning uchun bitta build mashinasidan ortiq bo'lsa yoki uzoq muddat
    kerak bo'lsa -ExportPfx tavsiya etiladi (oflayn saqlang).

    -TrustOnThisMachine / -TrustOnly: .cer ni SHU mashinaning (joriy
    foydalanuvchi) Trusted Root va Trusted Publishers omboriga qo'yadi.
    Usiz `signtool verify /pa` self-signed imzoni "ishonchsiz ildiz" deb
    rad etadi va build yiqiladi. Windows tasdiqlash oynasini ko'rsatadi.

    FAYL FAQAT ASCII: Windows PowerShell 5.1 BOM'siz faylni tizim kod
    sahifasida o'qiydi.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\create_codesign_cert.ps1 -TrustOnThisMachine
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\create_codesign_cert.ps1 -ExportPfx D:\keys\bba-codesign.pfx -TrustOnThisMachine
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\create_codesign_cert.ps1 -TrustOnly -CerPath bba-codesign.cer
#>
[CmdletBinding()]
param(
    # bba-codesign.cer yoziladigan papka (standart: joriy papka).
    [string]$OutDir = "",

    # Amal qilish muddati (yil).
    [ValidateRange(1, 10)]
    [int]$Years = 3,

    # Maxfiy kalit zaxirasi (.pfx). Berilmasa kalit eksport qilinmaydi.
    [string]$ExportPfx = "",

    # Yaratilgan sertifikatga shu mashinada ishonish (build mashinasi).
    [switch]$TrustOnThisMachine,

    # Yangi sertifikat yaratmasdan, mavjud .cer ga shu mashinada ishonish.
    [switch]$TrustOnly,
    [string]$CerPath = "",

    # Shu nomli amal qilayotgan sertifikat bo'lsa ham yangisini yaratish
    # (yangilash: docs\CODESIGN.md).
    [switch]$Force
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$Subject = "CN=BBA Proctoring Client, O=UZBMB"
$CerName = "bba-codesign.cer"

function Fail([string]$Text) {
    Write-Host ("XATO: " + $Text) -ForegroundColor Red
    exit 1
}

function Trust-Certificate([string]$File) {
    # CurrentUser omborlari: administrator huquqi kerak emas. Root'ga
    # qo'yishda Windows foydalanuvchidan tasdiq so'raydi - bu himoya,
    # uni chetlab o'tmaymiz.
    Import-Certificate -FilePath $File -CertStoreLocation Cert:\CurrentUser\Root | Out-Null
    Import-Certificate -FilePath $File -CertStoreLocation Cert:\CurrentUser\TrustedPublisher | Out-Null
    Write-Host "Shu mashinada ishonchli qilindi: CurrentUser\Root va CurrentUser\TrustedPublisher" -ForegroundColor Green
}

function Test-InsideGitRepo([string]$Dir) {
    $current = $Dir
    while ($current) {
        if (Test-Path -LiteralPath (Join-Path $current ".git")) { return $true }
        $parent = Split-Path -Parent $current
        if ($parent -eq $current) { break }
        $current = $parent
    }
    return $false
}

# --------------------------------------------------------------------------
# Faqat ishonch (build mashinasi, sertifikat boshqa joyda yaratilgan)
# --------------------------------------------------------------------------
if ($TrustOnly) {
    if (-not $CerPath) { Fail "-TrustOnly uchun -CerPath <bba-codesign.cer> bering." }
    if (-not (Test-Path -LiteralPath $CerPath -PathType Leaf)) { Fail ("Fayl topilmadi: " + $CerPath) }
    Trust-Certificate (Resolve-Path -LiteralPath $CerPath).ProviderPath
    exit 0
}

# --------------------------------------------------------------------------
# Takroriy yaratishdan himoya
# --------------------------------------------------------------------------
# Bir xil nomli ikkita sertifikat omborda bo'lsa qaysi iz build'da
# ishlatilayotgani chalkashadi va mijozlarga noto'g'ri .cer ketishi mumkin.
$existing = @(Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
    Where-Object { $_.Subject -eq $Subject -and $_.NotAfter -gt (Get-Date) })
if ($existing.Count -gt 0 -and -not $Force) {
    Write-Host "Shu nomli amal qilayotgan sertifikat allaqachon bor:" -ForegroundColor Yellow
    foreach ($c in $existing) {
        Write-Host ("  " + $c.Thumbprint + "  " + $c.NotAfter.ToString("yyyy-MM-dd") + " gacha")
    }
    Fail "Yangisi yaratilmadi. Yangilash (muddat tugayapti) bo'lsa -Force bilan qayta ishga tushiring."
}

if (-not $OutDir) { $OutDir = (Get-Location).Path }
if (-not (Test-Path -LiteralPath $OutDir)) { New-Item -ItemType Directory -Path $OutDir | Out-Null }
$OutDir = (Resolve-Path -LiteralPath $OutDir).ProviderPath

$pfxPassword = $null
if ($ExportPfx) {
    $pfxFull = [System.IO.Path]::GetFullPath($ExportPfx)
    if (Test-InsideGitRepo (Split-Path -Parent $pfxFull)) {
        # .gitignore ikkinchi himoya; birinchisi - kalit umuman ishchi
        # nusxaga tushmasligi (git add -f, zip arxiv, IDE sinxronizatsiyasi).
        Fail (".pfx git ombori ichiga yozilmaydi: " + $pfxFull + "`n  Repodan tashqaridagi (oflayn) joyni bering.")
    }
    if (Test-Path -LiteralPath $pfxFull) { Fail ("Fayl allaqachon bor: " + $pfxFull) }
    # Parol FAQAT SecureString'da: ekranga, logga va tarixga tushmaydi.
    $first = Read-Host -AsSecureString "PFX paroli"
    $second = Read-Host -AsSecureString "PFX paroli (takror)"
    # Ochiq matn faqat solishtirish uchun va darhol tozalanadi. Qaror
    # `finally` dan KEYIN: `exit` try ichida bo'lsa tozalash kafolatlanmaydi.
    $b1 = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($first)
    $b2 = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($second)
    $tooShort = $false
    $mismatch = $false
    try {
        $p1 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b1)
        $p2 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b2)
        $tooShort = $p1.Length -lt 12
        $mismatch = $p1 -cne $p2
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b1)
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b2)
        $p1 = $null
        $p2 = $null
    }
    if ($tooShort) { Fail "Parol kamida 12 belgi bo'lishi kerak." }
    if ($mismatch) { Fail "Parollar mos kelmadi." }
    $pfxPassword = $first
}

# --------------------------------------------------------------------------
# Sertifikat
# --------------------------------------------------------------------------
$exportPolicy = "NonExportable"
if ($ExportPfx) { $exportPolicy = "Exportable" }

$cert = New-SelfSignedCertificate `
    -Type CodeSigningCert `
    -Subject $Subject `
    -FriendlyName "BBA Proctoring Client - kod imzosi" `
    -KeyAlgorithm RSA `
    -KeyLength 3072 `
    -HashAlgorithm SHA256 `
    -KeySpec Signature `
    -KeyUsage DigitalSignature `
    -KeyExportPolicy $exportPolicy `
    -NotAfter (Get-Date).AddYears($Years) `
    -CertStoreLocation Cert:\CurrentUser\My

$cerFile = Join-Path $OutDir $CerName
if (Test-Path -LiteralPath $cerFile) {
    # Eskisini bosib ketmaymiz: u hali mijozlarda turgan bo'lishi mumkin
    # (yangilash davri) va ikkalasi ham kerak.
    $cerFile = Join-Path $OutDir ("bba-codesign-" + $cert.Thumbprint.Substring(0, 8) + ".cer")
}
Export-Certificate -Cert $cert -FilePath $cerFile -Type CERT | Out-Null

if ($ExportPfx) {
    $pfxArgs = @{ Cert = $cert; FilePath = $pfxFull; Password = $pfxPassword }
    # AES256 shifrlash (Windows 10 1709+); eski tizimda standart (3DES).
    if ((Get-Command Export-PfxCertificate).Parameters.ContainsKey("CryptoAlgorithmOption")) {
        $pfxArgs["CryptoAlgorithmOption"] = "AES256_SHA256"
    }
    Export-PfxCertificate @pfxArgs | Out-Null
    $pfxPassword = $null
}

if ($TrustOnThisMachine) { Trust-Certificate $cerFile }

Write-Host ""
Write-Host "Sertifikat yaratildi:" -ForegroundColor Green
Write-Host ("  Subject    : " + $cert.Subject)
Write-Host ("  Thumbprint : " + $cert.Thumbprint) -ForegroundColor Cyan
Write-Host ("  Muddati    : " + $cert.NotAfter.ToString("yyyy-MM-dd") + " gacha")
Write-Host ("  Ombor      : Cert:\CurrentUser\My (kalit: " + $exportPolicy + ")")
Write-Host ("  Ochiq kalit: " + $cerFile + "  -> mijoz kompyuterlariga")
if ($ExportPfx) {
    Write-Host ("  PFX zaxira : " + $pfxFull + "  -> OFLAYN saqlang, repoga qo'ymang") -ForegroundColor Yellow
}
Write-Host ""
Write-Host "Build uchun (iz sir emas):"
Write-Host ("  `$env:SIGN_CERT_THUMBPRINT = '" + $cert.Thumbprint + "'")
Write-Host ("  setx SIGN_CERT_THUMBPRINT " + $cert.Thumbprint + "     # doimiy, yangi terminalda")
if (-not $TrustOnThisMachine) {
    Write-Host ""
    Write-Host "DIQQAT: shu mashina sertifikatga hali ishonmaydi - 'signtool verify /pa' yiqiladi." -ForegroundColor Yellow
    Write-Host ("  tools\create_codesign_cert.ps1 -TrustOnly -CerPath " + $cerFile)
}
exit 0
