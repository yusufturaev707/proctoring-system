"""
Ishga tushishdagi o'z-o'zini tekshirish: "muammo va yechim".

Imtihon kuni operator "dastur ishlamayapti" deganda sababi odatda
oldindan aniqlanadigan narsa: antivirus model yoki DLL'ni karantinga
olgan, disk to'la, `.env` yo'q, kamera ulanmagan, server manzili
noto'g'ri. Bu modul ularni BIRINCHI ekranda, har biri uchun "nima qilish
kerak" matni bilan aytadi.

QOIDALAR:
  * HECH NARSA TO'SILMAYDI. Tekshiruv faqat ma'lumot beradi: tarmoq
    (preflight), yuz modeli (FaceID sahifasi), kamera (kamera
    tekshiruvi) o'z joyida o'z qarorini qabul qiladi. Bu yerdagi
    to'siq operatorni Ctrl+Q ga ham yetkazmay qo'yardi.
  * Hamma narsa FON thread'ida (`run_all`) - UI hech qachon kutmaydi.
    Kamera sanash (COM) va TCP ulanish sekin bo'lishi mumkin.
  * ARZON har ishga tushishda: model fayllari HAJMI har safar, SHA-256
    esa faqat birinchi ishga tushishda yoki fayl o'zgarganda (hajm/mtime)
    - natija keshda (`selfcheck_cache.json`). ~300 MB ni har safar
    xeshlash model yuklanishi bilan disk uchun raqobatlashardi.

MANIFEST (`<dastur katalogi>/models_manifest.json`, o'rnatuvchi build
paytida yaratadi): `{"files": {"models/<nisbiy yo'l>": {"size", "sha256"}}}`.
Yo'q bo'lsa (dev) - majburiy fayllar borligi tekshiriladi.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import socket
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.parse import urlparse

log = logging.getLogger(__name__)

MANIFEST_NAME = "models_manifest.json"
CACHE_NAME = "selfcheck_cache.json"

#: Yuz modeli usiz ishlamaydi (`installer/proctoring_client.spec:_BUFFALO_REQUIRED`).
REQUIRED_MODELS = ("models/buffalo_l/det_10g.onnx", "models/buffalo_l/w600k_r50.onnx")

#: Frozen build'dagi hayotiy fayllar - antivirus ko'pincha aynan
#: shularni karantinga oladi (noma'lum imzoli DLL/EXE).
BUNDLE_FILES = (
    "onnxruntime/capi/onnxruntime.dll",
    "PyQt6/Qt6/bin/QtWebEngineProcess.exe",
    "PyQt6/Qt6/bin/Qt6WebEngineCore.dll",
    "cv2/cv2.pyd",
)

DISK_WARN_MB = 1024
DISK_ERROR_MB = 200
TCP_TIMEOUT_S = 3.0

ERROR = "error"
WARNING = "warning"


@dataclass
class Problem:
    code: str
    severity: str
    title: str
    solution: str

    def as_line(self) -> str:
        return "[{}] {}: {} -> {}".format(self.severity, self.code, self.title, self.solution)


@dataclass
class CheckReport:
    problems: list = field(default_factory=list)
    first_run: bool = False
    duration_ms: int = 0
    hashed_files: int = 0

    @property
    def ok(self) -> bool:
        return not self.problems

    @property
    def has_errors(self) -> bool:
        return any(problem.severity == ERROR for problem in self.problems)


# ----------------------------------------------------------------------
# Kataloglar va disk
# ----------------------------------------------------------------------
def check_writable(path: Path, label: str) -> list:
    """Katalogga haqiqatan yozib ko'riladi (ruxsat, disk to'la, antivirus)."""
    probe = Path(path) / ".selfcheck.tmp"
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("ok")
            handle.flush()
            os.fsync(handle.fileno())
        probe.unlink()
        return []
    except OSError as exc:
        return [Problem(
            "folder_not_writable", ERROR,
            "{} katalogiga yozib bo'lmadi: {} ({})".format(label, path, exc.strerror or exc),
            "Diskda joy borligini va Windows hisobida bu katalogga yozish huquqi "
            "borligini tekshiring. Antivirus katalogni to'sgan bo'lishi mumkin - "
            "administratorga murojaat qiling.",
        )]


def check_disk(path: Path, *, warn_mb: int = DISK_WARN_MB, error_mb: int = DISK_ERROR_MB) -> list:
    try:
        free_mb = shutil.disk_usage(str(path)).free // (1024 * 1024)
    except OSError:
        return []
    if free_mb < error_mb:
        return [Problem(
            "disk_full", ERROR,
            "Diskda joy deyarli qolmadi ({} MB bo'sh).".format(free_mb),
            "Keraksiz fayllarni o'chiring yoki administratorga murojaat qiling. "
            "Joy bo'lmasa log, skrinshot va ekran yozuvi saqlanmaydi.",
        )]
    if free_mb < warn_mb:
        return [Problem(
            "disk_low", WARNING,
            "Diskda joy kam ({} MB bo'sh).".format(free_mb),
            "Imtihon davomida ekran yozuvi ~0.7 GB joy oladi. Diskni tozalang.",
        )]
    return []


# ----------------------------------------------------------------------
# Sozlama
# ----------------------------------------------------------------------
def check_config(*, frozen: bool, env_file: Optional[Path], api_base_url: str) -> list:
    problems = []
    if frozen and env_file is None:
        problems.append(Problem(
            "env_missing", ERROR,
            "Sozlama fayli (.env) topilmadi - server manzili standart qiymatda.",
            "Dasturni qayta o'rnating yoki administrator "
            "%ProgramData%\\ProctoringClient\\.env faylini tiklasin.",
        ))
    host = urlparse(api_base_url or "").hostname or ""
    if frozen and host in ("127.0.0.1", "localhost", "::1", ""):
        problems.append(Problem(
            "api_url_local", WARNING,
            "Server manzili shu kompyuterning o'zi ({}).".format(host or "bo'sh"),
            "Bu odatda o'rnatish xatosi: .env dagi API_BASE_URL ni tekshiring.",
        ))
    return problems


# ----------------------------------------------------------------------
# Model fayllari
# ----------------------------------------------------------------------
def manifest_candidates(resource_root: Path, exe_dir: Optional[Path]) -> list:
    candidates = []
    if exe_dir is not None:
        candidates.append(Path(exe_dir) / MANIFEST_NAME)
    candidates.append(Path(resource_root) / MANIFEST_NAME)
    return candidates


def load_manifest(candidates: Iterable[Path]) -> Optional[dict]:
    """Birinchi o'qiladigan manifest yoki `None`. Buzilgan fayl - `{}` (muammo)."""
    for path in candidates:
        if not Path(path).is_file():
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            files = data.get("files") if isinstance(data, dict) else None
            return files if isinstance(files, dict) else {}
        except (OSError, ValueError):
            return {}
    return None


def _model_problem(rel: str, what: str) -> Problem:
    return Problem(
        "model_" + what, ERROR,
        "Model fayli {}: {}".format(
            {"missing": "topilmadi", "size": "buzilgan (hajmi mos emas)",
             "hash": "buzilgan (SHA-256 mos emas)", "unreadable": "o'qib bo'lmadi"}[what],
            rel,
        ),
        "Antivirus faylni karantinga olgan yoki o'zgartirgan bo'lishi mumkin: "
        "Windows Defender -> Himoya tarixini tekshiring, dastur katalogini "
        "istisnoga qo'shing va dasturni qayta o'rnating.",
    )


def check_model_sizes(manifest: dict, root: Path) -> tuple:
    """
    Manifest bo'yicha borlik va HAJM (sinxron, arzon).

    Qaytaradi: (muammolar, xeshlanadigan yozuvlar ro'yxati
    `(rel, path, size, sha256)`).
    """
    problems, to_hash = [], []
    for rel, meta in sorted((manifest or {}).items()):
        path = Path(root) / rel
        try:
            size = path.stat().st_size
        except OSError:
            problems.append(_model_problem(rel, "missing"))
            continue
        expected = int((meta or {}).get("size") or -1)
        if expected >= 0 and size != expected:
            problems.append(_model_problem(rel, "size"))
            continue
        sha = str((meta or {}).get("sha256") or "").lower()
        if sha:
            to_hash.append((rel, path, size, sha))
    return problems, to_hash


def check_required_models(root: Path, required: Iterable[str] = REQUIRED_MODELS) -> list:
    """Manifest yo'q (dev) - faqat majburiy fayllar borligi."""
    problems = []
    for rel in required:
        path = Path(root) / rel
        try:
            if path.stat().st_size <= 0:
                problems.append(_model_problem(rel, "size"))
        except OSError:
            problems.append(_model_problem(rel, "missing"))
    return problems


def sha256_of(path: Path, chunk: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def verify_hashes(entries: list, cache: dict, *, hasher: Callable = sha256_of) -> tuple:
    """
    Xeshlarni tekshiradi; keshdagi (hajm, mtime) o'zgarmagan fayl QAYTA
    xeshlanmaydi. Qaytaradi: (muammolar, yangi kesh, xeshlangan fayllar soni).
    """
    problems, new_cache, hashed = [], {}, 0
    for rel, path, size, expected in entries:
        try:
            mtime = Path(path).stat().st_mtime_ns
        except OSError:
            problems.append(_model_problem(rel, "missing"))
            continue
        cached = cache.get(rel) or {}
        if (cached.get("size") == size and cached.get("mtime_ns") == mtime
                and cached.get("sha256") == expected and cached.get("ok")):
            new_cache[rel] = cached
            continue
        try:
            actual = hasher(path)
            hashed += 1
        except OSError:
            problems.append(_model_problem(rel, "unreadable"))
            continue
        ok = actual.lower() == expected
        if not ok:
            problems.append(_model_problem(rel, "hash"))
        new_cache[rel] = {"size": size, "mtime_ns": mtime, "sha256": expected, "ok": ok}
    return problems, new_cache, hashed


def check_bundle_files(root: Path, files: Iterable[str] = BUNDLE_FILES) -> list:
    """Frozen build: hayotiy DLL/EXE bormi va O'QILADIMI (antivirus qulfi)."""
    missing = []
    for rel in files:
        path = Path(root) / rel
        try:
            with open(path, "rb") as handle:
                handle.read(2)
        except OSError:
            missing.append(rel)
    if not missing:
        return []
    return [Problem(
        "bundle_files", ERROR,
        "Dastur fayllari yetishmayapti yoki to'silgan: {}".format(", ".join(missing)),
        "Antivirus (Windows Defender) ularni karantinga olgan bo'lishi mumkin. "
        "Himoya tarixidan tiklang, dastur katalogini istisnoga qo'shing va "
        "dasturni qayta o'rnating.",
    )]


# ----------------------------------------------------------------------
# Kamera va tarmoq
# ----------------------------------------------------------------------
def check_cameras(enumerate_devices: Optional[Callable] = None) -> list:
    """
    Lokal kamera bormi (DirectShow). FAQAT O'QISH - qurilma ochilmaydi.

    Yo'qligi OGOHLANTIRISH: bino IP kameralar bilan ishlashi mumkin -
    haqiqiy qaror kamera tekshiruvida (`camera/check/`).
    """
    if enumerate_devices is None:
        if sys.platform != "win32":
            return []
        from proctoring.camera.dshow import enumerate_devices
    try:
        devices = enumerate_devices()
    except Exception:  # noqa: BLE001
        log.debug("Kamera sanalmadi", exc_info=True)
        return []
    if devices:
        return []
    return [Problem(
        "camera_none", WARNING,
        "Kompyuterga ulangan veb-kamera topilmadi.",
        "Kamera kabelini tekshiring (boshqa USB portga ulang), Windows "
        "Sozlamalar -> Maxfiylik -> Kamera da ilovalarga ruxsat berilganini "
        "tekshiring. Bino IP kamera bilan ishlasa - bu xabarni e'tiborsiz qoldiring.",
    )]


def tcp_reachable(host: str, port: int, timeout: float = TCP_TIMEOUT_S) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_network(api_base_url: str, *, probe: Callable = tcp_reachable) -> list:
    """
    Server va internet - FAQAT TCP ulanish (ma'lumot yuborilmaydi).

    Haqiqiy ruxsat tekshiruvi preflight'da; bu yerda faqat "qayerda
    uzilgan" degan savolga aniq javob.
    """
    problems = []
    parsed = urlparse(api_base_url or "")
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    server_ok = bool(host) and probe(host, port)
    if not server_ok:
        problems.append(Problem(
            "server_unreachable", WARNING,
            "Serverga ulanib bo'lmadi ({}:{}).".format(host or "?", port),
            "Tarmoq kabelini tekshiring. Boshqa kompyuterlar ham ulanolmasa - "
            "server yoki tarmoq administratoriga murojaat qiling.",
        ))
    if not probe("api.ipify.org", 443):
        problems.append(Problem(
            "internet_unreachable", WARNING,
            "Internetga chiqib bo'lmadi.",
            "Imtihon tashqi platformada o'tadi - internet ulanishini "
            "tekshiring (tarmoq kabeli, proxy, firewall).",
        ))
    return problems


def check_elevation(threat_scan_enabled: bool) -> list:
    """Administrator huquqi yo'q - tozalash yarim qoladi (ma'lumot uchun)."""
    if not threat_scan_enabled or sys.platform != "win32":
        return []
    try:
        import ctypes

        shell32 = ctypes.WinDLL("shell32")
        shell32.IsUserAnAdmin.argtypes = ()
        shell32.IsUserAnAdmin.restype = ctypes.c_int
        if shell32.IsUserAnAdmin():
            return []
    except Exception:  # noqa: BLE001
        return []
    return [Problem(
        "not_elevated", WARNING,
        "Dastur administrator huquqisiz ishlayapti.",
        "Masofaviy boshqaruv xizmatlarini to'xtatib bo'lmasligi mumkin. "
        "Avtostart vazifasi (Task Scheduler) orqali ishga tushiring yoki "
        "administratorga murojaat qiling.",
    )]


# ----------------------------------------------------------------------
# Kesh
# ----------------------------------------------------------------------
def _cache_path() -> Path:
    from core.bundle_paths import local_state_root

    return local_state_root() / CACHE_NAME


def _load_cache(app_version: str) -> tuple:
    from core.state_store import read_json

    path = _cache_path()
    first_run = not path.exists()
    data = read_json(path)
    if data.get("app_version") != app_version:
        # Yangi versiya - yangi modellar bo'lishi mumkin: kesh eskirgan.
        return {}, first_run
    hashes = data.get("hashes")
    return (hashes if isinstance(hashes, dict) else {}), first_run


def _save_cache(app_version: str, hashes: dict) -> None:
    from core.state_store import atomic_write_json

    try:
        atomic_write_json(_cache_path(), {
            "app_version": app_version, "hashes": hashes, "checked_at": time.time(),
        })
    except Exception:  # noqa: BLE001 - kesh qulaylik
        log.debug("Self-check keshi yozilmadi", exc_info=True)


# ----------------------------------------------------------------------
def run_all() -> CheckReport:
    """
    Barcha tekshiruvlar. FON THREAD'IDA chaqiriladi. Xato KO'TARMAYDI:
    bitta tekshiruvning yiqilishi qolganlarini to'xtatmaydi.
    """
    started = time.monotonic()
    report = CheckReport()
    try:
        import config
        from core.bundle_paths import (
            is_frozen, local_state_root, logs_root, resource_root, writable_root,
        )
    except Exception:  # noqa: BLE001
        log.exception("Self-check boshlanmadi")
        return report

    frozen = is_frozen()
    app_version = getattr(config, "APP_VERSION", "")
    try:
        report.first_run = not _cache_path().exists()
    except OSError:
        report.first_run = True

    def guarded(name: str, func: Callable) -> None:
        try:
            report.problems.extend(func() or [])
        except Exception:  # noqa: BLE001
            log.warning("Self-check bosqichi yiqildi: %s", name, exc_info=True)

    guarded("folders", lambda: (
        check_writable(writable_root(), "Ma'lumotlar")
        + check_writable(local_state_root(), "Holat")
        + check_writable(logs_root(), "Log")
    ))
    guarded("disk", lambda: check_disk(writable_root()))
    guarded("config", lambda: check_config(
        frozen=frozen, env_file=getattr(config, "ENV_FILE", None),
        api_base_url=getattr(config, "API_BASE_URL", ""),
    ))
    if frozen:
        guarded("bundle", lambda: check_bundle_files(resource_root()))

    def models() -> list:
        root = resource_root()
        exe_dir = Path(sys.executable).resolve().parent if frozen else None
        manifest = load_manifest(manifest_candidates(root, exe_dir))
        if manifest is None:
            # Dev / manifestsiz build: kesh faqat "birinchi ishga tushish
            # o'tdi" belgisi sifatida yoziladi.
            _save_cache(app_version, {})
            return check_required_models(root)
        if not manifest:
            return [Problem(
                "manifest_broken", WARNING,
                "Model manifesti o'qilmadi ({}).".format(MANIFEST_NAME),
                "Dasturni qayta o'rnating. Fayllar faqat borligi bo'yicha tekshirildi.",
            )] + check_required_models(root)
        problems, entries = check_model_sizes(manifest, root)
        cache, _first = _load_cache(app_version)
        hash_problems, new_cache, report.hashed_files = verify_hashes(entries, cache)
        _save_cache(app_version, new_cache)
        return problems + hash_problems

    guarded("models", models)
    guarded("cameras", check_cameras)
    guarded("network", lambda: check_network(getattr(config, "API_BASE_URL", "")))
    guarded("elevation", lambda: check_elevation(bool(getattr(config, "THREAT_SCAN_ENABLED", False))))

    report.duration_ms = int((time.monotonic() - started) * 1000)
    if report.problems:
        log.warning(
            "Self-check: %s ta muammo (%s ms)\n  %s",
            len(report.problems), report.duration_ms,
            "\n  ".join(problem.as_line() for problem in report.problems),
        )
    else:
        log.info("Self-check: muammo yo'q (%s ms, xeshlangan: %s)",
                 report.duration_ms, report.hashed_files)
    return report
