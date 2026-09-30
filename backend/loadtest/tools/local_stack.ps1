# Lokal (Windows dev) yuklama stendi: stub platforma + HTTP + WS + Celery.
# DEV MUHITIDAN AJRATILGAN: `loadtest_settings` (baza proctoring_loadtest,
# Redis 6-10, portlar 8012/8013/8099). Faqat SKRIPTLARNI tekshirish uchun —
# natija production sig'imi haqida hech narsa demaydi (README, "Lokal").
#
#   powershell -ExecutionPolicy Bypass -File loadtest\tools\local_stack.ps1 start
#   powershell -ExecutionPolicy Bypass -File loadtest\tools\local_stack.ps1 stop
param([ValidateSet("start", "stop")] [string]$Action = "start",
      [int]$PlatformLatencyMs = 150)

$ErrorActionPreference = "Stop"
$Backend = (Resolve-Path "$PSScriptRoot\..\..").Path
$Py = "$Backend\.venv\Scripts\python.exe"
$Logs = "$Backend\loadtest\results\local_stack"
$PidFile = "$Logs\pids.txt"
New-Item -ItemType Directory -Force $Logs | Out-Null

if ($Action -eq "stop") {
    if (Test-Path $PidFile) {
        foreach ($p in Get-Content $PidFile) {
            try { Stop-Process -Id ([int]$p) -Force -ErrorAction Stop; "stopped $p" } catch { "gone $p" }
        }
        Remove-Item $PidFile
    }
    return
}

$env:PYTHONPATH = "$Backend\loadtest\server;$Backend\src"
$env:DJANGO_SETTINGS_MODULE = "loadtest_settings"
$env:PYTHONUNBUFFERED = "1"
# Celery muhit o'zgaruvchisini sozlamadan USTUN qo'yadi, `.env` esa dev
# brokerini (`/0`) beradi — jarayon muhitida qayta yozamiz (override=False).
$env:CELERY_BROKER_URL = "redis://127.0.0.1:6379/8"
$env:CELERY_RESULT_BACKEND = "redis://127.0.0.1:6379/9"

function Start-Bg($name, $argv, $cwd) {
    $p = Start-Process -FilePath $Py -ArgumentList $argv -WorkingDirectory $cwd -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput "$Logs\$name.out.log" -RedirectStandardError "$Logs\$name.err.log"
    Add-Content $PidFile $p.Id
    "$name pid=$($p.Id)"
}

Start-Bg "stub"   @("loadtest\server\stub_platform.py", "--port", "8099", "--latency-ms", "$PlatformLatencyMs", "--jitter-ms", "50") $Backend
# HTTP: runserver (ko'p thread'li, BITTA jarayon, GIL) — gunicorn Windows'da ishlamaydi.
Start-Bg "http"   @("manage.py", "runserver", "127.0.0.1:8012", "--noreload") $Backend
Start-Bg "ws"     @("-m", "uvicorn", "config.asgi:application", "--port", "8013", "--no-access-log", "--log-level", "warning") "$Backend\src"
Start-Bg "worker" @("-m", "celery", "-A", "config", "worker", "-Q", "ingest,maintenance,default", "-c", "4", "-n", "lt@%h", "-l", "warning") $Backend
Start-Bg "beat"   @("-m", "celery", "-A", "config", "beat", "-s", "$Logs\celerybeat-schedule", "-l", "warning") $Backend
