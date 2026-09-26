"""
Klaviatura qulfi ALOHIDA JARAYONDA: `ProctoringClient.exe --keyboard-hook`.

NIMA UCHUN. `WH_KEYBOARD_LL` callback'i Python'da va u GIL'ni oladi.
Client jarayonida GIL'ni AI kuzatuv, ekran yozuvi, skrinshot, tarmoq
thread'lari band qiladi. O'lchangan (4 ta Python thread yuklamasi):
har tugma median ~110 ms, p95 ~320 ms, eng ko'pi ~420 ms kechikdi.
Oqibatlari ikkita va ikkalasi ham jiddiy:

  * talabgor YOZISHDA kechikishni sezadi (har harf 0.1 s);
  * `LowLevelHooksTimeout` (standart ~300 ms) oshadi va Windows hook'ni
    OGOHLANTIRISHSIZ olib tashlaydi - Alt+Tab imtihon oxirigacha ochiq.

`sys.setswitchinterval` ni kamaytirish ham yordam berdi (0.2 ms da
~1.3 ms), lekin u BUTUN client uchun global va AI thread'larini
sekinlashtiradi. Alohida jarayonda esa GIL uchun raqobat yo'q: unda
faqat hook, nazoratchi va ikki bloklanadigan I/O thread'i bor.

SHARTNOMA (stdin/stdout, JSON qatorlar, UTF-8):

    client -> qulf:  {"op": "codes", "codes": ["alt+tab", ...]}
    qulf -> client:  {"ev": "ready", "blocked": [...]}
                     {"ev": "blocked", "code": "alt+tab"}
                     {"ev": "issue", "reason": "stuck_key", "key": "alt"}
                     {"ev": "log", "level": 30, "msg": "..."}

HAYOT SIKLI. Client o'lsa (hatto `TerminateProcess`) OS uning pipe
uchlarini yopadi, qulf stdin'da EOF oladi va chiqadi - hook u bilan
birga yo'qoladi, "egasiz qulflangan mashina" qolmaydi. Qulf o'lsa -
client uni qayta ko'taradi (`HookProcess._supervise`) va proktorga
`hook_lost` / `hook_restored` boradi.

Qulf jarayoni Qt'ni, log faylini va `.env` ni YUKLAMAYDI (`main.py`
bayroqni hamma narsadan oldin tekshiradi) - ishga tushishi ~0.1 s.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)

HOOK_FLAG = "--keyboard-hook"

_CREATE_NO_WINDOW = 0x08000000
#: Hook thread'i jarayon ichida HIGHEST - bu klass bilan u CPU'ni AI
#: to'liq band qilganda ham navbatni birinchi oladi.
_ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000


def child_command() -> list:
    """Qulf jarayonini ishga tushirish buyrug'i (frozen / dev)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, HOOK_FLAG]
    main_py = Path(__file__).resolve().parents[1] / "main.py"
    return [sys.executable, str(main_py), HOOK_FLAG]


# ----------------------------------------------------------------------
# Qulf jarayoni (bola)
# ----------------------------------------------------------------------
class _PipeLogHandler(logging.Handler):
    def __init__(self, emit: Callable[[dict], None]) -> None:
        super().__init__(logging.INFO)
        self._emit = emit

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._emit({"ev": "log", "level": record.levelno, "msg": self.format(record)})
        except Exception:
            pass


def run() -> int:
    """Qulf jarayonining kirish nuqtasi. Chiqish kodi: 0 - EOF, 2/3 - xato."""
    from services.keyboard_hook import KeyboardHook
    from services.lockdown import KeyPolicy

    try:
        reader = os.fdopen(0, "rb", buffering=0)
    except OSError:
        return 2
    outbox: "queue.Queue[Optional[dict]]" = queue.Queue()

    def writer() -> None:
        # Hook callback'i HECH QACHON pipe'ga o'zi yozmaydi: client
        # o'qimay qolsa yozish bloklanadi va hook timeout'ga tushadi.
        while True:
            item = outbox.get()
            if item is None:
                return
            try:
                os.write(1, (json.dumps(item, ensure_ascii=False) + "\n").encode("utf-8"))
            except OSError:
                os._exit(0)  # client yo'q - qulf ham kerak emas

    threading.Thread(target=writer, name="hook-writer", daemon=True).start()
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(_PipeLogHandler(outbox.put))

    policy = KeyPolicy(
        on_blocked=lambda code: outbox.put({"ev": "blocked", "code": code}),
        on_issue=lambda reason, key: outbox.put({"ev": "issue", "reason": reason, "key": key}),
    )
    hook = KeyboardHook(
        policy.on_key, on_tick=policy.tick,
        on_health=lambda state: policy.report("hook_" + state),
    )
    policy.release_key = hook.release_key
    code = 0
    try:
        for raw in reader:
            try:
                message = json.loads(raw.decode("utf-8"))
            except ValueError:
                continue
            if message.get("op") != "codes":
                continue
            blocked = policy.set_codes(message.get("codes") or [])
            if not hook.running:
                if not hook.start():
                    outbox.put({"ev": "fatal"})
                    code = 3
                    break
                outbox.put({"ev": "ready", "blocked": blocked})
    finally:
        hook.stop()
        outbox.put(None)
        time.sleep(0.05)
    return code


# ----------------------------------------------------------------------
# Client tomoni (ota)
# ----------------------------------------------------------------------
class HookProcess:
    """
    Qulf jarayonini boshqaradi: ishga tushirish, siyosat, qayta ko'tarish.

    `on_blocked(code)`, `on_issue(reason, key)` - o'quvchi thread'idan.
    """

    START_TIMEOUT_S = 5.0
    RESTART_BACKOFF_S = (0.5, 1.0, 2.0, 5.0, 10.0)

    def __init__(self, *, on_blocked=None, on_issue=None, command: Optional[list] = None) -> None:
        self._on_blocked = on_blocked
        self._on_issue = on_issue
        self._command = command or child_command()
        self._codes: list = []
        self._proc: Optional[subprocess.Popen] = None
        self._write_lock = threading.Lock()
        self._ready = threading.Event()
        self._stopping = threading.Event()
        self._supervisor: Optional[threading.Thread] = None
        #: Qulf jarayoni necha marta qayta ko'tarildi - diagnostika.
        self.restarts = 0

    @property
    def running(self) -> bool:
        return (not self._stopping.is_set() and self._supervisor is not None
                and self._supervisor.is_alive())

    @property
    def pid(self) -> Optional[int]:
        proc = self._proc
        return proc.pid if proc is not None else None

    def start(self, codes: list) -> bool:
        self._codes = list(codes)
        self._stopping.clear()
        if not self._spawn():
            return False
        if not self._ready.wait(self.START_TIMEOUT_S):
            log.error("Klaviatura qulfi jarayoni %.0f s da tayyor bo'lmadi", self.START_TIMEOUT_S)
            self._kill()
            return False
        self._supervisor = threading.Thread(target=self._supervise, name="hook-supervisor", daemon=True)
        self._supervisor.start()
        log.info("Klaviatura qulfi alohida jarayonda (pid %s)", self.pid)
        return True

    def update(self, codes: list) -> None:
        self._codes = list(codes)
        self._send({"op": "codes", "codes": self._codes})

    def stop(self) -> None:
        self._stopping.set()
        proc = self._proc
        if proc is not None:
            try:
                proc.stdin.close()  # EOF - qulf o'zi chiqadi va hook'ni oladi
            except Exception:
                pass
            try:
                proc.wait(timeout=2.0)
            except Exception:
                self._kill()
            self._close_pipes(proc)
        supervisor = self._supervisor
        if supervisor is not None and supervisor is not threading.current_thread():
            supervisor.join(timeout=2.0)
        self._supervisor = None

    # ------------------------------------------------------------------
    def _spawn(self) -> bool:
        self._ready.clear()
        try:
            proc = subprocess.Popen(
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                creationflags=_CREATE_NO_WINDOW | _ABOVE_NORMAL_PRIORITY_CLASS,
                close_fds=True,
            )
        except OSError as exc:
            log.error("Klaviatura qulfi jarayoni ishga tushmadi: %s", exc)
            return False
        self._proc = proc
        threading.Thread(target=self._read, args=(proc,), name="hook-reader", daemon=True).start()
        self._send({"op": "codes", "codes": self._codes})
        return True

    def _send(self, message: dict) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            return
        data = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        with self._write_lock:
            try:
                proc.stdin.write(data)
                proc.stdin.flush()
            except (OSError, ValueError):
                pass  # jarayon o'lgan - supervisor qayta ko'taradi va kodlarni yuboradi

    def _read(self, proc: subprocess.Popen) -> None:
        for raw in proc.stdout:
            try:
                message = json.loads(raw.decode("utf-8"))
            except ValueError:
                continue
            event = message.get("ev")
            if event == "ready":
                self._ready.set()
            elif event == "blocked":
                self._call(self._on_blocked, message.get("code", ""))
            elif event == "issue":
                self._call(self._on_issue, message.get("reason", ""), message.get("key", ""))
            elif event == "log":
                log.log(int(message.get("level") or logging.INFO), "[qulf] %s", message.get("msg", ""))

    @staticmethod
    def _call(callback, *args) -> None:
        if callback is None:
            return
        try:
            callback(*args)
        except Exception:
            log.debug("Qulf observer'i xatosi", exc_info=True)

    def _supervise(self) -> None:
        attempt = 0
        while not self._stopping.is_set():
            proc = self._proc
            if proc is not None:
                code = proc.wait()
                self._close_pipes(proc)
                if self._stopping.is_set():
                    return
                log.error("Klaviatura qulfi jarayoni kutilmaganda tugadi (kod %s) - qayta ko'tariladi", code)
                self._call(self._on_issue, "hook_lost", "")
            delay = self.RESTART_BACKOFF_S[min(attempt, len(self.RESTART_BACKOFF_S) - 1)]
            if self._stopping.wait(delay):
                return
            attempt += 1
            if self._spawn() and self._ready.wait(self.START_TIMEOUT_S):
                self.restarts += 1
                attempt = 0
                log.warning("Klaviatura qulfi jarayoni qayta ko'tarildi (pid %s)", self.pid)
                self._call(self._on_issue, "hook_restored", "")
            else:
                self._kill()
                self._proc = None

    def _kill(self) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            proc.kill()
            proc.wait(timeout=2.0)
        except Exception:
            pass
        self._close_pipes(proc)

    @staticmethod
    def _close_pipes(proc: subprocess.Popen) -> None:
        for stream in (proc.stdin, proc.stdout):
            try:
                if stream is not None:
                    stream.close()
            except Exception:
                pass
