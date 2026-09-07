"""
Ishga tushishda boshqa dasturlarni yopish.

Imtihon mashinasi TOZA holatda boshlanishi kerak: ochiq brauzer,
messenjer, masofaviy boshqaruv oynasi yoki hujjat - bularning har biri
nazoratdan tashqarida qoladigan kanal. Kiosk dasturlari (Safe Exam
Browser, LockDown Browser) aynan shuni qiladi.

ENG MUHIM QAROR: "barcha jarayonlarni" emas, "barcha DASTURLARNI"
yopamiz.

Bu farq mashinaning ishlashini hal qiladi. Windows'da bu mashinada
321 ta jarayon bor va ularning katta qismi - tizim xizmatlari
(`csrss.exe`, `lsass.exe`, `winlogon.exe`, `svchost.exe`). Ularni
o'ldirish BSOD yoki darhol qayta yuklanish bilan tugaydi, ya'ni
"barchasini yop" ni to'g'ridan-to'g'ri bajarish imtihon mashinasini
ishga tushmaydigan holga keltiradi.

Foydalanuvchi "dastur" deganda KO'RINADIGAN OYNANI tushunadi. Shuning
uchun mezon aynan shu: ko'rinadigan, sarlavhali, yuqori darajali oyna.
Fon xizmatlari va tizim jarayonlari bu ta'rifga tushmaydi va tegilmaydi.

BESH QATLAMLI HIMOYA (har biri mustaqil):

  1. Faqat JORIY FOYDALANUVCHI jarayonlari. `SYSTEM`, `LOCAL SERVICE`
     va boshqa hisoblar ostidagi hech narsaga tegilmaydi.
  2. Faqat ko'rinadigan, sarlavhali, egasi yo'q (top-level) oynasi
     bor jarayonlar.
  3. O'Z jarayonlar daraxti - hech qachon. Bunga QtWebEngine bola
     jarayonlari ham kiradi; ular alohida process va oynasi bo'lishi
     mumkin.
  4. Himoyalangan nomlar ro'yxati (`_PROTECTED`) - qobiq, ish stoli,
     xavfsizlik dasturlari.
  5. Avval MULOYIM yopish (`WM_CLOSE`), keyin qolganini majburan.
     Muloyim yopish dasturga saqlash imkonini beradi; majburiy o'ldirish
     esa "saqlaysizmi?" dialogida osilib qolganlarni oladi.

`WM_CLOSE` ATAYLAB `terminate()` dan oldin: Windows'da
`psutil.terminate()` bu `TerminateProcess`, ya'ni u ham majburiy
o'ldirish. Muloyim yopishning yagona yo'li - oynaga xabar yuborish.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Iterable

log = logging.getLogger(__name__)

#: HECH QACHON o'ldirilmaydigan jarayonlar (kichik harfda).
#:
#: Ro'yxat qisqa va ataylab shunday: asosiy filtr - ko'rinadigan oyna
#: va joriy foydalanuvchi. Bu yerga faqat SHU FILTRDAN O'TIB KETADIGAN,
#: lekin yopilmasligi kerak bo'lganlar kiradi.
_PROTECTED = frozenset(
    {
        # --- Qobiq va ish stoli ---
        # `explorer.exe` ni yopish vazifalar panelini va ish stolini
        # yo'q qiladi. Kiosk uchun bu foydali ko'rinadi, lekin fayl
        # dialoglarini buzadi va Windows uni baribir qayta ishga
        # tushiradi - ya'ni foyda yo'q, zarar bor.
        "explorer.exe",
        "dwm.exe",
        "sihost.exe",
        "ctfmon.exe",
        "textinputhost.exe",
        "shellexperiencehost.exe",
        "startmenuexperiencehost.exe",
        "searchhost.exe",
        "searchapp.exe",
        # UWP oynalarini SHU jarayon ushlab turadi. Uni o'ldirish
        # barcha UWP dasturlarni birdan yopadi - qo'pol va kutilmagan.
        # `WM_CLOSE` esa uning oynalariga yetadi va dasturlar odatdagidek
        # yopiladi, o'zi esa himoyalangani uchun tirik qoladi.
        "applicationframehost.exe",
        # --- Tizim ---
        "system",
        "registry",
        "memory compression",
        "smss.exe",
        "csrss.exe",
        "wininit.exe",
        "winlogon.exe",
        "services.exe",
        "lsass.exe",
        "lsaiso.exe",
        "svchost.exe",
        "fontdrvhost.exe",
        "dllhost.exe",
        "conhost.exe",
        "runtimebroker.exe",
        "taskhostw.exe",
        "sppsvc.exe",
        "wudfhost.exe",
        "audiodg.exe",
        "spoolsv.exe",
        "logonui.exe",
        # --- Xavfsizlik ---
        # Ularni o'ldirish odatda BARIBIR ishlamaydi (himoyalangan
        # jarayon), lekin urinishning o'zi antivirus jurnalida
        # "zararli xulq" sifatida qoladi.
        "msmpeng.exe",
        "nissrv.exe",
        "mpdefendercoreservice.exe",
        "securityhealthservice.exe",
        "securityhealthsystray.exe",
    }
)

#: `WM_CLOSE` dan keyin qancha kutiladi (soniya).
_GRACE_SECONDS = 3.0

#: Majburiy o'ldirishdan keyin tugashini kutish (soniya).
_KILL_TIMEOUT = 2.0

_WM_CLOSE = 0x0010
_GW_OWNER = 4
_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080


# --------------------------------------------------------------------------
# Windows API (faqat ctypes - qo'shimcha bog'liqliksiz)
# --------------------------------------------------------------------------
def _user32():
    """
    `user32.dll` yoki `None` (Windows bo'lmagan tizimda).

    `pywin32` ATAYLAB ishlatilmaydi: u PyInstaller bundle'iga sezilarli
    hajm qo'shadi va bizga bor-yo'g'i beshta funksiya kerak.
    """
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.EnumWindows.argtypes = [
        ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM),
        wintypes.LPARAM,
    ]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = wintypes.LONG
    user32.PostMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.PostMessageW.restype = wintypes.BOOL
    return user32


def visible_windows() -> dict:
    """
    `{pid: [hwnd, ...]}` — ko'rinadigan dastur oynalari.

    Uchta shart birga: oyna ko'rinadi, sarlavhasi bor va u yuqori
    darajali (egasi yo'q). Ular birgalikda "foydalanuvchi ko'radigan
    dastur" ta'rifini beradi va fon xizmatlarini, yashirin xabar
    oynalarini hamda dialoglarni chetlab o'tadi.
    """
    user32 = _user32()
    if user32 is None:
        return {}

    import ctypes
    from ctypes import wintypes

    result: dict = {}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            if user32.GetWindowTextLengthW(hwnd) == 0:
                return True
            if user32.GetWindow(hwnd, _GW_OWNER):
                return True
            # Asboblar oynasi vazifalar panelida ko'rinmaydi va u
            # odatda dasturning yordamchi qismi.
            if user32.GetWindowLongW(hwnd, _GWL_EXSTYLE) & _WS_EX_TOOLWINDOW:
                return True

            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value:
                result.setdefault(pid.value, []).append(hwnd)
        except Exception:
            # Bitta oyna tufayli butun sanashni to'xtatmaymiz.
            log.debug("Oynani o'qishda xato", exc_info=True)
        return True

    user32.EnumWindows(callback, 0)
    return result


def _own_pids() -> set:
    """
    O'z jarayonimiz, uning barcha bolalari va ota-onalari.

    Bolalar SHART: QtWebEngine alohida jarayonlarda ishlaydi va ular
    o'z oynasiga ega bo'lishi mumkin. Ota-onalar ham: dastur
    launcher yoki konsoldan ishga tushirilgan bo'lishi mumkin va uni
    o'ldirish o'zimizni ham o'ldiradi.
    """
    pids = {os.getpid()}
    try:
        import psutil

        current = psutil.Process()
        pids.update(child.pid for child in current.children(recursive=True))
        parent = current.parent()
        while parent is not None:
            pids.add(parent.pid)
            parent = parent.parent()
    except Exception:
        log.debug("O'z jarayonlar daraxtini aniqlab bo'lmadi", exc_info=True)
    return pids


# --------------------------------------------------------------------------
def close_other_apps(
    *,
    keep: Iterable[str] = (),
    grace_seconds: float = _GRACE_SECONDS,
    dry_run: bool = False,
) -> dict:
    """
    Boshqa barcha dasturlarni yopadi va hisobot qaytaradi.

    `keep` — qo'shimcha himoyalangan nomlar (muassasaning o'z
    dasturlari, IT agentlari, antivirus). `.env` dan keladi.

    `dry_run` — hech nima yopilmaydi, faqat ro'yxat qaytariladi.
    Yangi mashinada sozlashni tekshirish uchun.

    Qaytaradi:
        {"closed": [...], "killed": [...], "protected": [...],
         "failed": [...], "dry_run": bool}
    """
    report = {"closed": [], "killed": [], "protected": [], "failed": [], "dry_run": dry_run}

    if sys.platform != "win32":
        log.info("Dasturlarni yopish faqat Windows'da qo'llab-quvvatlanadi")
        return report

    try:
        import psutil
    except ImportError:
        log.error("psutil yo'q — boshqa dasturlar yopilmaydi")
        return report

    protected = _PROTECTED | {str(name).strip().lower() for name in keep if str(name).strip()}
    own = _own_pids()
    windows = visible_windows()

    try:
        me = psutil.Process().username()
    except Exception:
        me = None

    targets = []
    for pid, handles in windows.items():
        if pid in own:
            continue
        try:
            process = psutil.Process(pid)
            name = (process.name() or "").lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

        if name in protected:
            report["protected"].append(name)
            continue

        # Boshqa hisob ostidagi jarayon — tegilmaydi. Bu tizim
        # xizmatlariga qarshi ikkinchi, mustaqil qatlam.
        try:
            if me is not None and process.username() != me:
                report["protected"].append(name)
                continue
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

        targets.append((process, name, handles))

    if not targets:
        log.info("Yopiladigan dastur topilmadi")
        return report

    names = sorted({name for _, name, _ in targets})
    if dry_run:
        report["closed"] = names
        log.info("[DRY-RUN] Yopilardi: %s", ", ".join(names))
        return report

    log.info("Yopilmoqda: %s", ", ".join(names))

    # 1-bosqich: muloyim yopish.
    user32 = _user32()
    for _process, _name, handles in targets:
        for hwnd in handles:
            try:
                user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0)
            except Exception:
                log.debug("WM_CLOSE yuborilmadi", exc_info=True)

    gone, alive = psutil.wait_procs(
        [process for process, _, _ in targets], timeout=grace_seconds
    )
    report["closed"] = sorted({_safe_name(process) for process in gone})

    # 2-bosqich: qolganlarini majburan. Bu yerga "saqlaysizmi?"
    # dialogida osilib qolganlar va yopilishni rad etganlar tushadi.
    for process in alive:
        name = _safe_name(process)
        try:
            process.kill()
            report["killed"].append(name)
        except psutil.NoSuchProcess:
            report["closed"].append(name)
        except Exception as exc:
            # Huquq yetmadi (himoyalangan jarayon) — bu KUTILGAN holat
            # va u oqimni to'xtatmaydi.
            log.warning("Yopib bo'lmadi: %s (%s)", name, exc)
            report["failed"].append(name)

    psutil.wait_procs(alive, timeout=_KILL_TIMEOUT)

    log.info(
        "Yopildi: %s ta muloyim, %s ta majburan, %s ta yopilmadi",
        len(report["closed"]), len(report["killed"]), len(report["failed"]),
    )
    return report


def _safe_name(process) -> str:
    try:
        return (process.name() or "").lower()
    except Exception:
        return f"pid:{getattr(process, 'pid', '?')}"
