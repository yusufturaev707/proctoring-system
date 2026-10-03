"""
Kirish nuqtasi.

Ishga tushish tartibi referens loyihadagidek: avval log va muhit
(og'ir importlardan OLDIN), keyin Qt, oxirida oyna.

`INSIGHTFACE_ROOT` ni import zanjiridan oldin qo'yish shart -
`insightface.utils.download` va `model_zoo` shu env var'ga qaraydi va
uni kech qo'ysak, model `~/.insightface` ga yuklab olinadi.
"""

from __future__ import annotations

import logging
import os
import sys
import types

# KLAVIATURA QULFI JARAYONI (`services/keyboard_hook_process.py`) - HAMMA
# NARSADAN OLDIN: u Qt'ni, log faylini va `.env` ni yuklamasligi kerak
# (aks holda har ishga tushishda log'da ikkinchi "dastur ishga tushdi"
# yozuvi va ~1 s kechikish). Client uni o'z exe'si bilan ko'taradi.
if __name__ == "__main__" and "--keyboard-hook" in sys.argv:
    from services.keyboard_hook_process import run as _run_keyboard_hook

    sys.exit(_run_keyboard_hook())

# WATCHDOG JARAYONI (`core/watchdog.py`) - xuddi shu sabab bilan Qt, asosiy
# log va `.env` dan OLDIN. Alohida exe yo'q: o'sha exe bayroq bilan.
# `--watchdog-launch` - oraliq jarayon (watchdog UI daraxtidan uzilishi
# uchun), darhol chiqadi. Ikkalasi ham mutex OLMAYDI.
if __name__ == "__main__" and ("--watchdog" in sys.argv or "--watchdog-launch" in sys.argv):
    from core import watchdog as _watchdog

    if "--watchdog-launch" in sys.argv:
        sys.exit(_watchdog.run_launcher(sys.argv))
    sys.exit(_watchdog.run(sys.argv))

from core import crash_guard
from core.bundle_paths import resource_root
from core.env_guard import sanitize_process_env
from core.logging_setup import setup_logging

# MUHITNI TOZALASH - log, `config` va Qt'dan OLDIN (`core/env_guard.py`):
# talabgor `setx` bilan yozgan `QTWEBENGINE_*`, `SSL_CERT_FILE`,
# `ProgramData` va hokazo o'rnatilgan dasturga ta'sir qilmasligi kerak.
# Dev rejimda hech narsa qilmaydi.
_env_ignored = sanitize_process_env()

os.environ.setdefault("INSIGHTFACE_ROOT", str(resource_root()))

# `insightface/app/__init__.py` ichida `from .mask_renderer import *` bor.
# mask_renderer modul darajasida albumentations va face3d ni import qiladi
# (~50 MB + Cython). `FaceAnalysis` uchun ular KERAK EMAS, lekin import
# baribir bajariladi. Stub bilan zanjirni kesamiz: bundle kichrayadi va
# frozen rejimdagi ModuleNotFound xatolari yo'qoladi.
_stub = types.ModuleType("insightface.app.mask_renderer")
_stub.MaskRenderer = type("MaskRenderer", (), {})
sys.modules.setdefault("insightface.app.mask_renderer", _stub)

log = setup_logging()
if _env_ignored:
    # Faqat NOMLAR: qiymatda yo'l yoki manzil bo'lishi mumkin. Odatda
    # bo'sh; bo'lmasa - kimdir mashinada muhitni o'zgartirgan.
    log.warning("Muhit o'zgaruvchilari e'tiborsiz qoldirildi/tiklandi: %s",
                ", ".join(_env_ignored))
# Nativ qulash (access violation, abort) izi - ochiq deskriptorga.
_native_log = crash_guard.enable_native_crash_log()
if _native_log:
    log.info("Native crash log: %s", _native_log)


def _disable_extra_monitors() -> None:
    """
    Imtihon BITTA ekranda o'tadi — qolganlari ish stolidan uziladi.

    QT'DAN OLDIN va boshqa dasturlarni yopishdan ham OLDIN. Sabab
    tartibda: monitor uzilganda undagi oynalar asosiy ekranga
    ko'chadi, ya'ni `app_closer` ularni "ko'rinadigan oyna" sifatida
    ko'radi va yopadi. Teskari tartibda ikkinchi ekrandagi oyna
    yopilgandan keyin monitor uzilar va u yerdagi yangi oyna
    (masalan dialog) nazoratdan tashqarida qolishi mumkin edi.

    Xato butun dasturni TO'XTATMAYDI: bu tozalash bosqichi. O'chmagan
    monitor `DeviceWatcher` orqali baribir `multi_monitor` hodisasi
    sifatida qayd etiladi va proktor uni ko'radi.
    """
    from config import DISABLE_EXTRA_MONITORS

    if not DISABLE_EXTRA_MONITORS:
        log.info("Ortiqcha monitorlarni o'chirish o'chirilgan "
                 "(DISABLE_EXTRA_MONITORS=0)")
        return

    from services import display_control

    try:
        report = display_control.disable_secondary()
    except Exception:
        log.exception("Monitorlarni o'chirishda kutilmagan xato")
        return

    for display in report.disabled:
        log.info("Ortiqcha monitor o'chirildi: %s", display.describe())
    for display in report.failed:
        # Jimgina o'tib ketmasligi kerak: ekran hali ham yonib turibdi
        # va talabgor undan foydalana oladi.
        log.error("Monitor o'chmadi: %s", display.describe())


def _restore_monitors() -> None:
    """Dastur yopilgandan keyin monitorlarni qaytaradi."""
    from config import RESTORE_MONITORS_ON_EXIT

    if not RESTORE_MONITORS_ON_EXIT:
        return
    from services import display_control

    try:
        display_control.restore()
    except Exception:
        log.exception("Monitorlarni qaytarishda xato")


def _close_other_apps() -> None:
    """
    Imtihon mashinasini tozalab, keyin ishga tushamiz.

    Qt'dan OLDIN chaqiriladi va bu ataylab: o'z oynamiz paydo
    bo'lgandan keyin yopish talabgorga bir necha soniya davomida
    boshqa dasturlarni ko'rsatib qo'yardi, ustiga o'z oynamiz
    yopilayotgan dasturlarning dialoglari ostida qolardi.

    Xato butun dasturni TO'XTATMAYDI: bu tozalash bosqichi, imtihonning
    sharti emas. Yopilmagan dastur `DeviceWatcher` orqali baribir
    hodisa sifatida qayd etiladi.
    """
    from config import (
        CLOSE_OTHER_APPS,
        CLOSE_OTHER_APPS_GRACE_S,
        CLOSE_OTHER_APPS_KEEP,
    )

    if not CLOSE_OTHER_APPS:
        log.info("Boshqa dasturlarni yopish o'chirilgan (CLOSE_OTHER_APPS=0)")
        return

    from services.app_closer import close_other_apps

    try:
        report = close_other_apps(
            keep=CLOSE_OTHER_APPS_KEEP, grace_seconds=CLOSE_OTHER_APPS_GRACE_S
        )
    except Exception:
        log.exception("Dasturlarni yopishda kutilmagan xato")
        return

    if report["failed"]:
        # Jimgina o'tib ketmasligi kerak: yopilmagan dastur ekranda
        # qolgan bo'lishi mumkin va operator buni bilishi kerak.
        log.error(
            "Quyidagi dasturlar yopilmadi: %s. Ular administrator "
            "huquqini talab qilishi mumkin.",
            ", ".join(report["failed"]),
        )


def _sweep_threats() -> None:
    """
    Masofaviy boshqaruv, virtualizatsiya va yordamchi vositalarni tozalash.

    `_close_other_apps()` dan KEYIN va bu ataylab. Birinchisi ko'rinadigan
    oynalarni yopadi, ya'ni AnyDesk oynasi allaqachon ketgan bo'ladi va
    bu yerda faqat uning OYNASIZ qismi - xizmat va fon jarayoni qoladi.
    Teskari tartibda ikkala bosqich ham bir xil jarayonlarga tegib,
    ikkinchisi birinchisining natijasini "qayta paydo bo'ldi" deb
    o'qishi mumkin edi.

    Qt'dan OLDIN: tozalash bir necha soniya olishi mumkin va bu paytda
    oyna ko'rinmasligi kerak.

    NATIJA SAQLANADI, lekin bu yerda HECH NARSA TO'SILMAYDI. Qaror
    imtihon tanlangandan keyin qabul qilinadi (`proctoring/policy.py`
    -> `check_readiness`): u yerda operator sababni ham, nima qilish
    kerakligini ham ekranda ko'radi. Bu yerda to'sish - dastur
    oynasi ochilmasdan turib "chiqib ketdi" degani bo'lardi va
    operator nima bo'lganini umuman bilmasdi.
    """
    from config import (
        THREAT_ALLOW_VIRTUAL_HOST,
        THREAT_SCAN_ALLOW,
        THREAT_SCAN_ENABLED,
    )

    if not THREAT_SCAN_ENABLED:
        log.info("Tahdid skaneri o'chirilgan (THREAT_SCAN_ENABLED=0)")
        return

    from services import threat_scanner

    try:
        report = threat_scanner.sweep(
            allow=THREAT_SCAN_ALLOW,
            allow_virtual_host=THREAT_ALLOW_VIRTUAL_HOST,
        )
    except Exception:
        # Tozalash imtihonning SHARTI emas: skaner yiqilsa dastur
        # baribir ishga tushadi va kuzatuv qatlami (`DeviceWatcher`)
        # o'z tekshiruvini bajaradi.
        log.exception("Tahdid skanerida kutilmagan xato")
        return

    threat_scanner.remember(report)
    log.info(
        "Tahdid skaneri: %s (%s ta jarayon, %s ta xizmat, %s ms, admin=%s)",
        report.summary(), report.scanned_processes, report.scanned_services,
        report.duration_ms, report.elevated,
    )
    for finding in report.findings:
        if finding.neutralized:
            log.warning("Yo'q qilindi: %s", finding.describe())
        else:
            log.error("YO'Q QILINMADI: %s | sabab: %s", finding.describe(), finding.reason)


def _purge_archive() -> None:
    """
    Muddati o'tgan yozuvlarni o'chiradi.

    ISHGA TUSHISHDA, imtihon boshlanishidan oldin: tozalash diskni
    kezadi va imtihon davomida u skrinshot oqimi hamda ekran
    yozuvi bilan bitta diskda raqobatlashardi.

    Xato dasturni TO'XTATMAYDI: tozalash qulaylik, kuzatuvning
    sharti emas. To'lgan disk esa alohida muammo va u `pick_root`
    da ko'rinadi (2 GB dan kam joyi bor disk tanlanmaydi).
    """
    from config import LOCAL_ARCHIVE_ENABLED, LOCAL_ARCHIVE_RETENTION_DAYS

    if not LOCAL_ARCHIVE_ENABLED or LOCAL_ARCHIVE_RETENTION_DAYS <= 0:
        return
    from services import local_archive

    try:
        local_archive.purge_old(LOCAL_ARCHIVE_RETENTION_DAYS)
    except Exception:
        log.exception("Arxivni tozalashda kutilmagan xato")


def _log_env_file() -> None:
    """
    Qaysi `.env` o'qilganini yozadi.

    "Nega bu mashina boshqa serverga ulanyapti?" degan savolning birinchi
    javobi shu: `.env` uch joydan qidiriladi (`core/bundle_paths`) va
    eski `.exe` yonidagi fayl ProgramData'dagini soyalab qo'yishi mumkin.
    O'rnatilgan dasturda fayl umuman topilmasa - bu o'rnatish nosozligi
    (server manzili standart `127.0.0.1` bo'lib qoladi), shuning uchun ERROR.
    """
    from config import ENV_FILE
    from core.bundle_paths import env_file_candidates, is_frozen

    if ENV_FILE is not None:
        log.info("Sozlama fayli: %s", ENV_FILE)
        return
    level = logging.ERROR if is_frozen() else logging.WARNING
    log.log(
        level,
        "Sozlama fayli (.env) topilmadi, standart qiymatlar ishlatilmoqda. "
        "Qidirilgan joylar: %s",
        ", ".join(str(path) for path in env_file_candidates()),
    )


def _begin_state(restart_count: int):
    """
    `state.json`: yangi jarayon yoziladi, oldingisi baholanadi.

    Xato dasturni TO'XTATMAYDI - holat fayli qulaylik (`core/state_store.py`).
    """
    from config import APP_VERSION
    from core.state_store import StateStore

    try:
        store = StateStore()
        crash = store.begin(
            pid=os.getpid(), app_version=APP_VERSION, restart_count=restart_count
        )
    except Exception:
        log.exception("Holat fayli ishga tushmadi")
        return None, {}
    if restart_count:
        log.warning("Dastur watchdog tomonidan qayta ishga tushirildi (%s-marta)", restart_count)
    if crash:
        log.error(
            "OLDINGI ishga tushish kutilmaganda tugagan: pid=%s bosqich=%s sessiya=%s",
            crash.get("pid"), crash.get("stage") or "-",
            "bor" if crash.get("session_public_id") else "yo'q",
        )
    return store, crash


def _show_early_splash():
    """
    Nativ splash (`core/early_splash.py`) - mutex olingan zahoti.

    Mutex'dan OLDIN emas: ikkinchi nusxa splash ko'rsatmasligi kerak
    (unga `notify_running` javob beradi). `None` - ko'rsatilmadi, `main`
    Qt splash'ga qaytadi.
    """
    try:
        from core.bundle_paths import resource_path
        from core.early_splash import EarlySplash
        from version import APP_NAME as _APP_NAME

        splash = EarlySplash(_APP_NAME, logo_path=str(resource_path("resources/images/logo.png")))
        return splash if splash.show() else None
    except Exception:  # noqa: BLE001 - bezak, ishga tushishni to'smaydi
        log.debug("Nativ splash ko'rsatilmadi", exc_info=True)
        return None


def _prewarm_api_client() -> None:
    """
    `ApiClient` ni FON thread'ida yaratadi - tozalash bosqichlari bilan parallel.

    Uning konstruktori (httpx + TLS sertifikatlar to'plamini o'qish)
    ~0.3 s oladi va ilgari asosiy oyna qurilayotganda UI thread'ida
    bajarilardi (`PreflightPage` -> `AuthService`). Singleton qulf bilan
    himoyalangan (`core/singleton.py`): oyna undan oldin so'rasa, shu
    nusxa tayyor bo'lishini kutadi, ikkinchisi yaratilmaydi.
    """
    import threading

    def work() -> None:
        try:
            from services.api_client import ApiClient

            ApiClient()
        except Exception:  # noqa: BLE001 - oyna o'zi qayta urinadi
            log.debug("ApiClient oldindan yaratilmadi", exc_info=True)

    threading.Thread(target=work, name="prewarm-api", daemon=True).start()


def main() -> int:
    # BITTA NUSXA - tozalash bosqichlaridan OLDIN: ikkinchi nusxaning
    # `app_closer` i birinchisining oynasini "begona dastur" deb yopardi.
    from core import single_instance
    from core import watchdog

    if not single_instance.acquire():
        # JIMGINA yopilmaydi: xodim belgini qayta-qayta bosmasligi uchun
        # birinchi nusxaning oynasi oldinga chiqariladi yoki (u hali
        # yuklanayotgan bo'lsa) "kuting" xabari ko'rsatiladi.
        from version import APP_NAME as _APP_NAME

        outcome = single_instance.notify_running(_APP_NAME)
        log.warning(
            "Dasturning boshqa nusxasi allaqachon ishlayapti - bu nusxa yopiladi (%s)", outcome
        )
        return 0

    # ADMINISTRATOR HUQUQI - mutex'dan KEYIN (boshqa nusxa ishlayotgan
    # bo'lsa yuqorida chiqib ketilgan), tozalashdan OLDIN: SYSTEM
    # xizmatlarini to'xtatish faqat administrator nusxasida ishlaydi.
    # Yorliq yoki `.exe` dan oddiy huquqda ochilgan nusxa o'zini avtostart
    # vazifasi orqali qayta ochadi va chiqadi (`core/elevation.py`).
    #
    # SPLASH ENG BIRINCHI: qayta ochish ham, tozalash ham soniyalar oladi
    # va shu paytda ekran bo'sh qolmasligi kerak. Qayta ochilganda yangi
    # nusxa o'z splash'ini mutex'ni olgan zahoti ko'rsatadi, bu nusxa esa
    # aynan shundan KEYIN yopiladi - ekranda uzilish bo'lmaydi.
    early = _show_early_splash()
    from core import elevation

    if elevation.relaunch_via_task(
        release_mutex=single_instance.release,
        mutex_held=single_instance.is_held,
        reacquire_mutex=single_instance.acquire,
    ):
        if early is not None:
            early.close()
        return 0

    _prewarm_api_client()

    wd_args = watchdog.parse_args(sys.argv)
    store, previous_crash = _begin_state(wd_args["restart_count"])

    if early is not None:
        early.set_text("Kompyuter imtihonga tayyorlanmoqda…")
    _disable_extra_monitors()
    _purge_archive()
    _close_other_apps()
    _sweep_threats()
    if early is not None:
        early.set_text("Dastur modullari yuklanmoqda…")

    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QApplication

    from config import APP_NAME, APP_VERSION
    from ui.styles import GLOBAL_STYLESHEET

    # QtWebEngine QApplication'dan OLDIN e'lon qilinishi shart. Aks holda
    # `QtWebEngineWidgets` importi "must be imported ... before a
    # QCoreApplication instance is created" bilan yiqiladi. Modulni shu
    # yerda import qilish ham yechim, lekin u butun engine'ni (~150 MB)
    # darhol yuklaydi; bayroq esa buni WebView sahifasi ochilgunga qadar
    # kechiktiradi.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

    # `sys.argv` MAJBURIY, bo'sh ro'yxat EMAS. Chromium `argv[0]` dan
    # dastur nomini oladi; usiz WebEngine "base::CommandLine cannot be
    # properly initialized" deb butun jarayonni qulatadi (0xC0000409).
    # Watchdog bayroqlari (`--watchdog-pid`, `--restart-count`) Qt va
    # Chromium'ga uzatilmaydi - ular faqat bizniki.
    app = QApplication(watchdog.strip_own_flags(sys.argv))
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(GLOBAL_STYLESHEET)

    # QT SPLASH - faqat ZAXIRA: nativ splash (`early`) ko'rsatilmagan
    # bo'lsa. Ikkalasi birga bo'lsa ikki xil oyna almashinib miltillardi.
    # QApplication paydo bo'lgan zahoti, og'ir modullardan (`main_window`:
    # kamera, AI, WebEngine sahifalari) OLDIN.
    splash = None
    if early is None:
        try:
            from ui.widgets.startup_splash import StartupSplash

            splash = StartupSplash(APP_NAME, APP_VERSION, steps=3)
            splash.show()
            splash.set_text("Dastur modullari yuklanmoqda…")
        except Exception:  # noqa: BLE001 - splash bezak, ishga tushishni to'smaydi
            log.warning("Ishga tushish oynasi ko'rsatilmadi", exc_info=True)
            splash = None

    from main_window import MainWindow

    # Qt xabarlari log'ga; xato xabarchisi va tizim hodisalari (uyqu,
    # monitor/DPI) QApplication paydo bo'lgan zahoti.
    crash_guard.install_qt_message_handler()
    crash_guard.reporter()
    try:
        from core.system_events import system_events

        system_events().attach()
    except Exception:
        log.exception("Tizim hodisalari ulanmadi")

    # Oyna qatlamidagi himoya: kiosk'da Windows System Menu ochilmaydi
    # (Alt+Space, SC_KEYMENU) - global hook ishlamay qolgan holatda ham.
    from config import KIOSK_MODE
    if KIOSK_MODE:
        from services.lockdown import install_system_menu_guard
        install_system_menu_guard(app)

    if splash is not None:
        splash.set_text("Oyna tayyorlanmoqda…")
    if early is not None:
        early.set_text("Oyna tayyorlanmoqda…")
    window = MainWindow(
        state_store=store,
        previous_crash=previous_crash,
        watchdog_pid=wd_args["watchdog_pid"],
    )
    window.show_start()
    if splash is not None:
        splash.close()
        splash.deleteLater()
    if early is not None:
        # Hodisa sikli boshlangach - asosiy oyna birinchi marta chizilgandan
        # keyin. Darhol yopilsa oralig'ida bir lahza ish stoli ko'rinardi.
        from PyQt6.QtCore import QTimer

        QTimer.singleShot(0, early.close)
    log.info("%s v%s ishga tushdi", APP_NAME, APP_VERSION)
    _log_env_file()
    try:
        return app.exec()
    finally:
        # `finally` ATAYLAB: monitorning uzilishi registrga yoziladi
        # va u dastur bilan birga yo'qolmaydi. Oddiy chiqishda ham,
        # istisno bilan tugashda ham ekran operatorga qaytishi kerak.
        _restore_monitors()
        crash_guard.uninstall_qt_message_handler()


if __name__ == "__main__":
    sys.exit(main())
