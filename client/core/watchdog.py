"""
Watchdog: UI jarayoni kutilmaganda o'lsa uni qayta ishga tushiradi.

ALOHIDA EXE YO'Q - o'sha `ProctoringClient.exe` `--watchdog` bayrog'i
bilan (`main.py` bayroqni Qt, log va `.env` dan OLDIN tekshiradi, xuddi
`--keyboard-hook` kabi). Paketlashga hech narsa qo'shilmaydi.

JARAYONLAR DARAXTI:

    UI (Task Scheduler / operator)
      -> `--watchdog-launch` (darhol chiqadi)
           -> `--watchdog --pid <UI>`   (ota jarayoni allaqachon o'lik)
                -> qayta ko'tarilgan UI `--watchdog-pid <W> --restart-count N`

Oraliq `--watchdog-launch` ATAYLAB: watchdog UI ning BOLASI bo'lsa,
Task Manager'dagi "End task" (ilova guruhi) va "End process tree" uni
UI bilan BIRGA o'ldirardi va qayta tiklash hech qachon ishlamasdi.
Ota jarayoni o'lik bo'lgan watchdog UI daraxtiga kirmaydi.

O'RNATUVCHI: `taskkill /F /T /IM ProctoringClient.exe` rasm NOMI bo'yicha
o'ldiradi - watchdog ham shu nomda, ya'ni u ham o'ladi. Poyga yo'q:
watchdog qayta ko'tarishdan oldin `RESTART_DELAY_S` kutadi, `taskkill`
esa shu vaqt ichida ro'yxatdagi hamma jarayonni tugatib bo'ladi.

QAYTA KO'TARILMAYDI:
  * chiqish kodi 0 (oddiy yopilish, OS seansi yakuni);
  * `state.json` da shu PID uchun `clean_exit` (Ctrl+Q + parol - hatto
    tozalash paytida nativ qulash bo'lsa ham);
  * Windows o'chmoqda / seans yakunlanmoqda (`SM_SHUTTINGDOWN`);
  * `MAX_RESTARTS` / `WINDOW_S` chegarasi oshdi - log + tizim xabari.

MUTEX OLINMAYDI: watchdog ham, klaviatura qulfi ham `single_instance`
ga tegmaydi - aks holda qayta ko'tarilgan UI "boshqa nusxa ishlayapti"
deb chiqib ketardi.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger("watchdog")

WATCHDOG_FLAG = "--watchdog"
LAUNCH_FLAG = "--watchdog-launch"
PID_FLAG = "--pid"
PARENT_WATCHDOG_FLAG = "--watchdog-pid"
RESTART_COUNT_FLAG = "--restart-count"

MAX_RESTARTS = 3
WINDOW_S = 300.0
#: Qayta ko'tarishdan oldingi pauza: o'rnatuvchining `taskkill` i
#: watchdog'ni ham tugatib ulgursin, o'lgan UI ning bolalari
#: (QtWebEngineProcess, klaviatura qulfi) kamera va portni bo'shatsin.
RESTART_DELAY_S = 3.0

_CREATE_NO_WINDOW = 0x08000000
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000
_SYNCHRONIZE = 0x00100000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_INFINITE = 0xFFFFFFFF
_SM_SHUTTINGDOWN = 0x2000
#: Ctrl+C / seans yakunida o'ldirilgan jarayon kodi.
_STATUS_CONTROL_C_EXIT = 0xC000013A

_STATUS_FILE = "watchdog.json"


# ----------------------------------------------------------------------
# Sof mantiq (testlanadi)
# ----------------------------------------------------------------------
@dataclass
class RestartPolicy:
    """`window_s` ichida ko'pi bilan `max_restarts` marta qayta ko'tarish."""

    max_restarts: int = MAX_RESTARTS
    window_s: float = WINDOW_S
    history: deque = field(default_factory=deque)

    def allow(self, now: float) -> bool:
        while self.history and now - self.history[0] > self.window_s:
            self.history.popleft()
        return len(self.history) < self.max_restarts

    def record(self, now: float) -> None:
        self.history.append(now)


def exit_reason(exit_code: int, *, clean_marker: bool, shutting_down: bool) -> str:
    """
    UI chiqishini tasniflaydi: "" - qayta ko'tarish KERAK, aks holda sabab.
    """
    code = int(exit_code) & 0xFFFFFFFF
    if clean_marker:
        return "toza chiqish belgisi (state.json)"
    if code == 0:
        return "oddiy yopilish (kod 0)"
    if shutting_down:
        return "Windows o'chmoqda / seans yakunlanmoqda"
    if code == _STATUS_CONTROL_C_EXIT:
        return "seans yakuni (STATUS_CONTROL_C_EXIT)"
    return ""


def parse_args(argv: list) -> dict:
    """`--pid 123 --restart-count 2` -> {"pid": 123, "restart_count": 2}."""
    result = {"pid": 0, "restart_count": 0, "watchdog_pid": 0}
    names = {PID_FLAG: "pid", RESTART_COUNT_FLAG: "restart_count",
             PARENT_WATCHDOG_FLAG: "watchdog_pid"}
    for index, item in enumerate(argv):
        key = names.get(item)
        if key and index + 1 < len(argv):
            try:
                result[key] = int(argv[index + 1])
            except ValueError:
                pass
    return result


def base_command() -> list:
    """UI ni ishga tushirish buyrug'i (frozen / dev) - bayroqsiz."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    main_py = Path(__file__).resolve().parents[1] / "main.py"
    return [sys.executable, str(main_py)]


def strip_own_flags(argv: list) -> list:
    """UI argumentlaridan watchdog bayroqlarini olib tashlaydi (qayta ko'tarish uchun)."""
    result, skip = [], False
    with_value = {PID_FLAG, PARENT_WATCHDOG_FLAG, RESTART_COUNT_FLAG}
    for item in argv:
        if skip:
            skip = False
            continue
        if item in with_value:
            skip = True
            continue
        if item in (WATCHDOG_FLAG, LAUNCH_FLAG):
            continue
        result.append(item)
    return result


# ----------------------------------------------------------------------
# Windows yordamchilari
# ----------------------------------------------------------------------
def _kernel32():
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    k32.WaitForSingleObject.restype = wintypes.DWORD
    k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    k32.GetExitCodeProcess.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    k32.CloseHandle.restype = wintypes.BOOL
    k32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
    )
    k32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    return k32


def _open_process(pid: int):
    k32 = _kernel32()
    handle = k32.OpenProcess(_SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    return handle or None


def _image_path(handle) -> str:
    import ctypes
    from ctypes import wintypes

    k32 = _kernel32()
    size = wintypes.DWORD(1024)
    buffer = ctypes.create_unicode_buffer(size.value)
    if not k32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
        return ""
    return buffer.value


def _wait_exit_code(handle) -> int:
    import ctypes
    from ctypes import wintypes

    k32 = _kernel32()
    k32.WaitForSingleObject(handle, _INFINITE)
    code = wintypes.DWORD(0)
    k32.GetExitCodeProcess(handle, ctypes.byref(code))
    k32.CloseHandle(handle)
    return int(code.value)


def _shutting_down() -> bool:
    try:
        import ctypes

        user32 = ctypes.WinDLL("user32")
        user32.GetSystemMetrics.argtypes = (ctypes.c_int,)
        user32.GetSystemMetrics.restype = ctypes.c_int
        return bool(user32.GetSystemMetrics(_SM_SHUTTINGDOWN))
    except Exception:  # noqa: BLE001
        return False


def is_alive(pid: int) -> bool:
    """Jarayon tirikmi (UI watchdog'ni tekshirish uchun)."""
    if not pid or sys.platform != "win32":
        return False
    try:
        handle = _open_process(pid)
        if not handle:
            return False
        k32 = _kernel32()
        alive = k32.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT
        k32.CloseHandle(handle)
        return alive
    except Exception:  # noqa: BLE001
        return False


def _popen(command: list) -> Optional[subprocess.Popen]:
    """
    Bola jarayon: konsolsiz, meros deskriptorlarsiz.

    Avval `CREATE_BREAKAWAY_FROM_JOB` bilan: Task Scheduler vazifani job
    obyektiga qo'yishi mumkin va vazifa tugaganda job ichidagilarni
    to'xtatishi mumkin. Job ajralishga ruxsat bermasa (`ERROR_ACCESS_DENIED`)
    - odatiy bayroqlar bilan qayta urinamiz.
    """
    base_flags = _CREATE_NO_WINDOW
    last: Optional[OSError] = None
    for flags in (base_flags | _CREATE_BREAKAWAY_FROM_JOB, base_flags):
        try:
            return subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
                close_fds=True,
                cwd=str(Path(command[0]).resolve().parent) if getattr(sys, "frozen", False) else None,
            )
        except OSError as exc:
            last = exc
            continue
    log.error("Jarayon ishga tushmadi: %s", last)
    return None


# ----------------------------------------------------------------------
# UI tomoni
# ----------------------------------------------------------------------
def spawn_for(ui_pid: int) -> bool:
    """UI dan chaqiriladi: watchdog'ni UZILGAN holda ishga tushiradi."""
    if sys.platform != "win32":
        return False
    command = base_command() + [LAUNCH_FLAG, PID_FLAG, str(int(ui_pid))]
    proc = _popen(command)
    return proc is not None


def run_launcher(argv: list) -> int:
    """`--watchdog-launch`: haqiqiy watchdog'ni ishga tushiradi va DARHOL chiqadi."""
    args = parse_args(argv)
    if not args["pid"]:
        return 2
    proc = _popen(base_command() + [WATCHDOG_FLAG, PID_FLAG, str(args["pid"])])
    return 0 if proc is not None else 1


# ----------------------------------------------------------------------
# Watchdog jarayoni
# ----------------------------------------------------------------------
def _setup_logging() -> Path:
    from logging.handlers import RotatingFileHandler

    from core.bundle_paths import logs_root
    from core.log_redaction import RedactingFormatter

    path = logs_root() / "watchdog.log"
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    try:
        handler = RotatingFileHandler(path, maxBytes=1024 * 1024, backupCount=2, encoding="utf-8")
        handler.setFormatter(RedactingFormatter("%(asctime)s [%(levelname)s] %(message)s"))
        root.addHandler(handler)
    except OSError:
        root.addHandler(logging.NullHandler())
    logging.raiseExceptions = False
    return path


def _status_path() -> Path:
    from core.bundle_paths import local_state_root

    return local_state_root() / _STATUS_FILE


def _write_status(**fields) -> None:
    from core.state_store import atomic_write_json

    try:
        atomic_write_json(_status_path(), dict(fields, updated_at=time.time()))
    except Exception:  # noqa: BLE001 - holat fayli qulaylik, disk to'la bo'lishi mumkin
        log.warning("watchdog.json yozilmadi", exc_info=True)


def read_status() -> dict:
    from core.state_store import read_json

    return read_json(_status_path())


def _clean_marker_for(pid: int) -> bool:
    from core.state_store import default_path, read_json

    state = read_json(default_path())
    return bool(state.get("clean_exit")) and int(state.get("pid") or 0) == int(pid)


def _show_gave_up(log_path: Path) -> None:
    """Chegara oshdi: tizim xabari (Qt yo'q - nativ MessageBox)."""
    text = (
        "Proctoring Client {} daqiqa ichida {} marta kutilmaganda yopildi.\n\n"
        "Avtomatik qayta ishga tushirish to'xtatildi, chunki muammo "
        "takrorlanmoqda.\n\n"
        "Nima qilish kerak:\n"
        "  1. Dasturni qo'lda qayta ishga tushiring.\n"
        "  2. Yana yopilsa - administratorga murojaat qiling va quyidagi "
        "log fayllarini bering:\n     {}\n     {}"
    ).format(int(WINDOW_S // 60), MAX_RESTARTS, log_path.parent, _main_log_hint())
    try:
        import ctypes

        user32 = ctypes.WinDLL("user32")
        user32.MessageBoxW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint)
        user32.MessageBoxW.restype = ctypes.c_int
        # MB_ICONERROR | MB_SYSTEMMODAL | MB_SETFOREGROUND | MB_TOPMOST
        user32.MessageBoxW(None, text, "Proctoring Client", 0x10 | 0x1000 | 0x10000 | 0x40000)
    except Exception:  # noqa: BLE001
        log.debug("Xabar oynasi ko'rsatilmadi", exc_info=True)


def _main_log_hint() -> str:
    try:
        from core.bundle_paths import writable_root

        return str(writable_root() / "proctoring-client.log")
    except Exception:  # noqa: BLE001
        return "%APPDATA%\\ProctoringClient\\proctoring-client.log"


def run(argv: list) -> int:
    """`--watchdog --pid <UI>` jarayonining kirish nuqtasi."""
    log_path = _setup_logging()
    args = parse_args(argv)
    ui_pid = args["pid"]
    my_pid = os.getpid()
    if sys.platform != "win32" or not ui_pid:
        log.error("Watchdog: UI PID berilmadi")
        return 2

    handle = _open_process(ui_pid)
    if not handle:
        log.warning("Watchdog: UI jarayoni (%s) topilmadi - chiqamiz", ui_pid)
        return 0
    # PID qayta ishlatilgan bo'lishi mumkin: begona jarayonni kuzatmaymiz.
    expected = os.path.normcase(os.path.abspath(sys.executable))
    actual = os.path.normcase(_image_path(handle) or "")
    if actual and actual != expected:
        log.warning("Watchdog: PID %s boshqa dasturga tegishli (%s) - chiqamiz", ui_pid, actual)
        _kernel32().CloseHandle(handle)
        return 0

    policy = RestartPolicy()
    restarts = 0
    log.info("Watchdog ishga tushdi (pid=%s), UI pid=%s", my_pid, ui_pid)
    _write_status(pid=my_pid, ui_pid=ui_pid, restarts=0, gave_up=False)

    while True:
        code = _wait_exit_code(handle)
        reason = exit_reason(
            code,
            clean_marker=_clean_marker_for(ui_pid),
            shutting_down=_shutting_down(),
        )
        if reason:
            log.info("UI (pid=%s) yopildi: %s - watchdog tugaydi", ui_pid, reason)
            _write_status(pid=my_pid, ui_pid=ui_pid, restarts=restarts, gave_up=False,
                          finished=reason)
            return 0

        log.error("UI (pid=%s) KUTILMAGANDA tugadi, chiqish kodi 0x%08X", ui_pid, code & 0xFFFFFFFF)
        now = time.time()
        if not policy.allow(now):
            log.error(
                "Qayta ishga tushirish TO'XTATILDI: %s daqiqada %s martadan ko'p yiqildi",
                int(WINDOW_S // 60), MAX_RESTARTS,
            )
            _write_status(pid=my_pid, ui_pid=ui_pid, restarts=restarts, gave_up=True,
                          gave_up_at=now, last_exit_code=code & 0xFFFFFFFF)
            _show_gave_up(log_path)
            return 3

        time.sleep(RESTART_DELAY_S)
        # Pauza paytida seans yakunlana boshlagan bo'lishi mumkin.
        if _shutting_down():
            log.info("Windows o'chmoqda - qayta ishga tushirilmaydi")
            return 0

        policy.record(time.time())
        restarts += 1
        command = base_command() + [
            PARENT_WATCHDOG_FLAG, str(my_pid), RESTART_COUNT_FLAG, str(restarts)
        ]
        proc = _popen(command)
        if proc is None:
            log.error("UI qayta ishga tushmadi - watchdog tugaydi")
            _write_status(pid=my_pid, ui_pid=ui_pid, restarts=restarts, gave_up=True,
                          gave_up_at=time.time(), last_exit_code=code & 0xFFFFFFFF)
            _show_gave_up(log_path)
            return 4
        ui_pid = proc.pid
        handle = _open_process(ui_pid)
        log.warning("UI qayta ishga tushirildi (pid=%s, %s-marta)", ui_pid, restarts)
        _write_status(pid=my_pid, ui_pid=ui_pid, restarts=restarts, gave_up=False,
                      last_exit_code=code & 0xFFFFFFFF, restarted_at=time.time())
        if not handle:
            # Jarayon shu zahoti tugagan: keyingi aylanishda baholab bo'lmaydi.
            log.error("Yangi UI jarayoniga ulanib bo'lmadi - watchdog tugaydi")
            return 5


def status_summary() -> Optional[str]:
    """UI uchun: watchdog oxirgi marta nima qildi (log/diagnostika)."""
    data = read_status()
    if not data:
        return None
    try:
        return json.dumps(data, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return None
