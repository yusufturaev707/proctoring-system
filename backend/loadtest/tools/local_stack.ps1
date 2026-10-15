# Lokal (Windows dev) yuklama stendi: stub platforma + HTTP + WS + Celery.
# DEV MUHITIDAN AJRATILGAN: `loadtest_settings` (baza proctoring_loadtest,
# Redis 6-10, portlar 8012/8013/8099). Faqat SKRIPTLARNI tekshirish uchun —
# natija production sig'imi haqida hech narsa demaydi (README, "Lokal").
#
#   powershell -ExecutionPolicy Bypass -File loadtest\tools\local_stack.ps1 start
#   powershell -ExecutionPolicy Bypass -File loadtest\tools\local_stack.ps1 stop
#
# `-HttpWorkers N` (N > 0) — HTTP `runserver` o'rniga N ta ALOHIDA uvicorn
# jarayoni, portlar `-HttpBasePort` dan ketma-ket (8021..). 1000+ client uchun
# SHART: runserver bitta jarayon va GIL bilan bir necha yuz so'rov/s da
# to'yinadi. Har jarayonda `-HttpThreads` ta WSGI thread (`server/lt_http_app.py`)
# — har biri o'z DB ulanishi, ya'ni jami N × threads + WS + Celery <= PostgreSQL
# `max_connections`. Locust ularni `--lt-hosts` bilan navbat bilan taqsimlaydi.
#
# NIMA UCHUN `uvicorn --workers N` EMAS: Windows'da ko'p jarayonli uvicorn
# `SelectorEventLoop` (select()) ishlatadi — bitta jarayonda ~512 soket.
# 5000 client sinovida WS jarayoni `too many file descriptors in select()`
# bilan yiqildi. Bitta jarayonli uvicorn `ProactorEventLoop` da — chegara yo'q.
# Production (Linux, epoll) da bu muammo yo'q.
param([ValidateSet("start", "stop")] [string]$Action = "start",
      [int]$PlatformLatencyMs = 150,
      [int]$HttpWorkers = 0,
      [int]$HttpThreads = 4,
      [int]$HttpBasePort = 8021)

$ErrorActionPreference = "Stop"
$Backend = (Resolve-Path "$PSScriptRoot\..\..").Path
$Py = "$Backend\.venv\Scripts\python.exe"
$Logs = "$Backend\loadtest\results\local_stack"
$PidFile = "$Logs\pids.txt"
New-Item -ItemType Directory -Force $Logs | Out-Null

if ($Action -eq "stop") {
    if (Test-Path $PidFile) {
        foreach ($line in Get-Content $PidFile) {
            $p = ($line -split "\s+")[-1]
            # Daraxt bilan (`/T`): venv `python.exe` — yo'naltiruvchi, haqiqiy
            # jarayon (va uvicorn/Celery ishchilari) uning AVLODLARI —
            # `Stop-Process` faqat ildizni o'ldirib, ular portni band qilib qolardi.
            & taskkill.exe /F /T /PID $p 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { "stopped $p" } else { "gone $p" }
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
    # "nom pid" — `tools/monitor.py` CPU'ni shu nom bo'yicha guruhlaydi.
    Add-Content $PidFile "$name $($p.Id)"
    "$name pid=$($p.Id)"
}

Start-Bg "stub"   @("loadtest\server\stub_platform.py", "--port", "8099", "--latency-ms", "$PlatformLatencyMs", "--jitter-ms", "50") $Backend
if ($HttpWorkers -gt 0) {
    # Production'dagi gunicorn gthread (N jarayon × thread) ning Windows
    # taqlidi — WSGI, qat'iy thread pool (sabab `server/lt_http_app.py`).
    $env:LT_HTTP_THREADS = "$HttpThreads"
    for ($i = 0; $i -lt $HttpWorkers; $i++) {
        Start-Bg "http$($i + 1)" @("-m", "uvicorn", "lt_http_app:app", "--port", "$($HttpBasePort + $i)",
            "--no-access-log", "--log-level", "warning", "--backlog", "4096", "--timeout-keep-alive", "75") "$Backend\src"
    }
} else {
    # HTTP: runserver (ko'p thread'li, BITTA jarayon, GIL) — faqat skriptni tekshirish uchun.
    Start-Bg "http" @("manage.py", "runserver", "127.0.0.1:8012", "--noreload") $Backend
}
# WS — BITTA jarayon (production'da 2, lekin Windows'da `--workers` select()
# chegarasiga uriladi — yuqoriga qarang).
$env:ASGI_THREADS = "8"
Start-Bg "ws"     @("-m", "uvicorn", "config.asgi:application", "--port", "8013",
    "--no-access-log", "--log-level", "warning", "--backlog", "4096") "$Backend\src"
Remove-Item Env:ASGI_THREADS
# Celery — production'dagi kabi ikki ishchi (ingest 4, maintenance+default 2).
Start-Bg "worker" @("-m", "celery", "-A", "config", "worker", "-Q", "ingest", "-c", "4", "-n", "lt-ingest@%h", "-l", "warning") $Backend
Start-Bg "maint"  @("-m", "celery", "-A", "config", "worker", "-Q", "maintenance,default", "-c", "2", "-n", "lt-maint@%h", "-l", "warning") $Backend
Start-Bg "beat"   @("-m", "celery", "-A", "config", "beat", "-s", "$Logs\celerybeat-schedule", "-l", "warning") $Backend
