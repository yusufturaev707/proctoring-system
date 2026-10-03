<#
.SYNOPSIS
    Proctoring Client avtostarti - Task Scheduler "at logon" vazifasi.

.DESCRIPTION
    O'rnatuvchi (proctoring_client.iss) chaqiradi. Qo'lda ham ishlatsa bo'ladi:
        powershell -ExecutionPolicy Bypass -File autostart.ps1 -Action Register -ExePath "C:\Program Files\ProctoringClient\ProctoringClient.exe"
        powershell -ExecutionPolicy Bypass -File autostart.ps1 -Action Unregister

    NIMA UCHUN TASK SCHEDULER, HKLM\...\Run EMAS:
      * Run kaliti dasturni foydalanuvchi TOKENI bilan, ya'ni har doim
        cheklangan huquqda ochadi. Imtihon mashinasi ko'pincha lokal
        administrator hisobida ishlaydi va client'ning tozalash qismi
        (masofaviy boshqaruv XIZMATINI to'xtatish, boshqa hisob jarayonini
        o'ldirish - services/threat_scanner.py) aynan administrator
        huquqini talab qiladi. "RunLevel Highest" administrator hisobida
        UAC oynasiz yuqori huquq beradi, oddiy hisobda esa oddiy huquq -
        manifestga requireAdministrator yozish har ishga tushishda UAC
        oynasini chiqarardi va kioskni to'xtatib qo'yardi.
      * Vazifa standart sozlamasi 72 soatdan keyin jarayonni O'LDIRADI
        va ustuvorligi 7 (past). Bu yerda ikkalasi ochiq o'zgartirilgan:
        muddatsiz, ustuvorlik 4 (normal) - aks holda ekran yozuvi va AI
        kuzatuv fon jarayonlaridan orqada qolardi.

    Trigger - ISTALGAN foydalanuvchi kirganda (BUILTIN\Users guruhi):
    operator va talabgor boshqa-boshqa Windows hisobida bo'lishi mumkin.
    Guruh nomi SID'dan olinadi: ruscha Windows'da u boshqacha yoziladi.

    FAYL FAQAT ASCII (PowerShell 5.1 BOM'siz faylni ANSI deb o'qiydi).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Register", "Unregister")]
    [string]$Action,

    [string]$ExePath = "",

    [string]$TaskName = "ProctoringClient"
)

$ErrorActionPreference = "Stop"

if ($Action -eq "Unregister") {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host ("Vazifa o'chirildi: " + $TaskName)
    }
    exit 0
}

if (-not $ExePath -or -not (Test-Path $ExePath)) {
    Write-Error ("ExePath topilmadi: " + $ExePath)
    exit 1
}

$usersSid = New-Object System.Security.Principal.SecurityIdentifier("S-1-5-32-545")
$usersGroup = $usersSid.Translate([System.Security.Principal.NTAccount]).Value

$taskAction = New-ScheduledTaskAction -Execute $ExePath -WorkingDirectory (Split-Path -Parent $ExePath)

$trigger = New-ScheduledTaskTrigger -AtLogOn
# Ish stoli va tarmoq ko'tarilishiga vaqt: darhol ishga tushgan client
# preflight so'rovini tarmoq hali yo'q paytda yuborib, "server javob
# bermadi" ekranida qolardi.
$trigger.Delay = "PT10S"

$principal = New-ScheduledTaskPrincipal -GroupId $usersGroup -RunLevel Highest

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -Priority 4

$task = New-ScheduledTask -Action $taskAction -Trigger $trigger -Principal $principal -Settings $settings `
    -Description "Proctoring Client: foydalanuvchi kirganda imtihon kuzatuv dasturini ishga tushiradi."

Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null

# QO'LDA ISHGA TUSHIRISH RUXSATI. Administrator yaratgan vazifani oddiy
# huquqli jarayon O'QIY OLADI, lekin `schtasks /Run` "Access is denied"
# (kod 1) oladi. Client esa yorliqdan oddiy huquqda ochilib, o'zini
# aynan shu vazifa orqali administrator huquqi bilan qayta ochadi
# (core/elevation.py). Authenticated Users ga GRGX (o'qish + ishga
# tushirish) beriladi. Bu UAC'ni chetlab o'tish EMAS: vazifa faqat shu
# o'rnatilgan .exe ni ochadi (Program Files - yozish faqat admin) va
# yuqori huquqni faqat administratorlar guruhidagi hisob oladi
# (RunLevel Highest); oddiy hisob oddiy huquq oladi.
try {
    $service = New-Object -ComObject "Schedule.Service"
    $service.Connect()
    $registered = $service.GetFolder("\").GetTask($TaskName)
    $sddl = $registered.GetSecurityDescriptor(0xF)
    if ($sddl -notmatch "\(A;;GRGX;;;AU\)") {
        $registered.SetSecurityDescriptor($sddl + "(A;;GRGX;;;AU)", 0)
    }
    Write-Host "Vazifani foydalanuvchi ishga tushira oladi (GRGX;AU)"
} catch {
    # Avtostart baribir ishlaydi - faqat yorliqdan ochilganda yuqori
    # huquq bo'lmaydi (client log'ida "Vazifa ishga tushmadi").
    Write-Warning ("Vazifa ruxsati o'rnatilmadi: " + $_.Exception.Message)
}

Write-Host ("Vazifa ro'yxatga olindi: " + $TaskName + " -> " + $ExePath)
exit 0
