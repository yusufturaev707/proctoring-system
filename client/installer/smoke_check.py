"""
Yig'ilgan client'ning tutun tekshiruvi (smoke check).

NIMA UCHUN KERAK. PyInstaller xatolari BUILD paytida emas, ISHGA
TUSHISHDA chiqadi va eng yomoni — ko'pchiligi jimgina:

  * yashirin import tushib qolsa `.exe` faqat o'sha sahifa ochilganda
    yiqiladi (FaceID sahifasi — talabgor kamera oldida turganda);
  * CUDA DLL'i bundle'ga tushmasa ONNX Runtime JIMGINA CPU'ga o'tadi
    (`proctoring/hardware/cuda_runtime.py` docstring'i);
  * QtWebEngine resurslari yo'q bo'lsa test sahifasi oq ekran bo'lib
    qoladi;
  * `skimage.transform` `lazy_loader` orqali yuklanadi va u `.pyi`
    fayllarini ISHGA TUSHISHDA o'qiydi — importni statik tahlil
    ko'rmaydi, xato esa birinchi yuz tekshiruvida chiqadi.

Shuning uchun bu skript HAQIQIY yo'llarni bosib o'tadi: modelni
yuklaydi, bitta inferensiya qiladi, yuzni tekislash (skimage + scipy)
ni chaqiradi, WebEngine sahifasini ochadi, mp4 yozadi.

UCH XIL ISHGA TUSHIRISH:

  * dev: `venv/Scripts/python installer/smoke_check.py`
  * build: `dist/ProctoringClient/ProctoringClientCheck.exe` — spec
    uni asosiy `.exe` bilan BITTA `_internal` ustida yig'adi, ya'ni
    aynan o'sha DLL'lar va modellar tekshiriladi;
  * asosiy `.exe` ichidan — `main.py` ga `--smoke` ulansa
    (`run(argv)`), konsol yo'qligi uchun natija `--report` fayliga.

Chiqish kodi: 0 — hammasi joyida (ogohlantirishlar bo'lishi mumkin),
1 — kamida bitta MAJBURIY tekshiruv yiqildi.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import traceback
import types
from pathlib import Path

# Dev rejimda `installer/` dan ishga tushiriladi — client ildizi
# sys.path da bo'lishi kerak (`core`, `services`, `proctoring`).
_CLIENT_DIR = Path(__file__).resolve().parent.parent
if not getattr(sys, "frozen", False) and str(_CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(_CLIENT_DIR))


class _Report:
    def __init__(self) -> None:
        self.items: list[dict] = []
        self.lines: list[str] = []

    def add(self, name: str, status: str, detail: str = "", required: bool = True) -> None:
        self.items.append(
            {"name": name, "status": status, "detail": detail, "required": required}
        )
        line = "[{:4}] {}{}".format(status, name, " - " + detail if detail else "")
        self.lines.append(line)
        # Oynali (`windowed`) `.exe` da `sys.stdout` — None: natija
        # faqat `--report` fayliga tushadi.
        if sys.stdout is not None:
            print(line, flush=True)

    @property
    def failed(self) -> list[dict]:
        return [item for item in self.items if item["status"] == "FAIL" and item["required"]]


def _check(report: _Report, name: str, func, required: bool = True) -> object:
    """Bitta tekshiruv. Istisno — FAIL, `None` bo'lmagan satr — tafsilot."""
    started = time.perf_counter()
    try:
        detail = func()
    except Exception as exc:  # noqa: BLE001 — har qanday xato natija
        report.add(
            name,
            "FAIL" if required else "WARN",
            "{}: {}".format(type(exc).__name__, exc),
            required,
        )
        report.lines.append(traceback.format_exc())
        return None
    took = (time.perf_counter() - started) * 1000
    text = "" if detail is None else str(detail)
    report.add(name, "OK", "{} ({:.0f} ms)".format(text, took).strip(), required)
    return detail


# --------------------------------------------------------------------------
def _prepare_like_main() -> None:
    """
    `main.py` ning import OLDIDAN qiladigan ishi — AYNAN o'shanday.

    Ikkalasi ajralib ketsa tekshiruv yolg'on natija beradi: masalan
    `mask_renderer` stub'isiz insightface bu yerda boshqa yo'l bilan
    import bo'lardi. `main.py` o'zgarsa, bu funksiya ham yangilanadi.
    """
    from core.bundle_paths import resource_root

    os.environ.setdefault("INSIGHTFACE_ROOT", str(resource_root()))
    stub = types.ModuleType("insightface.app.mask_renderer")
    stub.MaskRenderer = type("MaskRenderer", (), {})
    sys.modules.setdefault("insightface.app.mask_renderer", stub)


def _environment() -> str:
    from core import bundle_paths

    try:
        from version import __version__
    except ImportError:
        __version__ = "?"
    return "v{} frozen={} root={} exe={}".format(
        __version__, bundle_paths.is_frozen(), bundle_paths.resource_root(), sys.executable
    )


def _env_file() -> str:
    from core import bundle_paths

    chosen = bundle_paths.env_file_path()
    candidates = ", ".join(str(path) for path in bundle_paths.env_file_candidates())
    if chosen is None:
        raise FileNotFoundError("`.env` topilmadi. Qidirilgan: " + candidates)
    return str(chosen)


def _client_modules() -> str:
    """
    Client'ning BARCHA modullari import qilinadi.

    Ro'yxat qo'lda yozilmaydi — paketlar kezib chiqiladi: yangi modul
    qo'shilganda uning yashirin importi tekshiruvdan tushib qolmasligi
    kerak. Frozen rejimda PyInstaller'ning `FrozenImporter` i
    `pkgutil.walk_packages` ni qo'llaydi.
    """
    import importlib
    import pkgutil

    loaded = 0
    failures: list[str] = []
    for root in ("core", "services", "proctoring", "ui"):
        package = importlib.import_module(root)
        for info in pkgutil.walk_packages(package.__path__, root + "."):
            try:
                importlib.import_module(info.name)
                loaded += 1
            except Exception as exc:  # noqa: BLE001
                failures.append("{} ({}: {})".format(info.name, type(exc).__name__, exc))
    for name in ("config", "main_window"):
        importlib.import_module(name)
        loaded += 1
    if failures:
        raise ImportError("; ".join(failures))
    return "{} ta modul".format(loaded)


def _libraries() -> str:
    import cv2
    import httpx  # noqa: F401
    import numpy
    import onnxruntime
    import psutil  # noqa: F401
    from dotenv import load_dotenv  # noqa: F401

    return "numpy {} cv2 {} onnxruntime {}".format(
        numpy.__version__, cv2.__version__, onnxruntime.__version__
    )


def _models() -> str:
    from core.bundle_paths import resource_root

    root = resource_root() / "models"
    required = [root / "buffalo_l" / "det_10g.onnx", root / "buffalo_l" / "w600k_r50.onnx"]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(", ".join(missing))
    extras = sorted(
        str(path.relative_to(root)) for path in root.rglob("*.onnx") if path not in required
    )
    return "buffalo_l tayyor; qo'shimcha: {}".format(", ".join(extras) or "yo'q")


def _models_manifest() -> str:
    """
    `models_manifest.json` (build.ps1 yozadi) bundle'dagi modellarga mosmi.

    Client ishga tushishda shu manifestga tayanadi; build'da uni
    tekshirmasak, xato manifest 500 mashinaga tarqalib, har birida
    "model buzilgan" degan YOLG'ON signal berardi. Ikki tomon: manifestdagi
    har fayl bor va o'lcham/xesh mos, `models/` dagi har fayl manifestda.
    Kalitlar `resource_root()` ga nisbatan (`make_models_manifest.py`).
    """
    import hashlib

    from core.bundle_paths import resource_root

    manifest_path = Path(sys.executable).resolve().parent / "models_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(str(manifest_path))
    files = json.loads(manifest_path.read_text(encoding="utf-8"))["files"]

    root = resource_root()
    problems: list[str] = []
    for key, expected in files.items():
        path = root / key
        if not path.is_file():
            problems.append("yo'q: " + key)
            continue
        if path.stat().st_size != expected["size"]:
            problems.append("o'lcham: " + key)
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != expected["sha256"]:
            problems.append("sha256: " + key)
    listed = set(files)
    for path in (root / "models").rglob("*"):
        if path.is_file() and path.relative_to(root).as_posix() not in listed:
            problems.append("manifestda yo'q: " + path.relative_to(root).as_posix())
    if problems:
        raise RuntimeError("; ".join(problems))
    return "{} ta fayl mos".format(len(files))


def _cuda_status() -> dict:
    from proctoring.hardware import cuda_runtime

    status = cuda_runtime.prepare()
    return {
        "available": status.available,
        "listed": status.listed,
        "missing": status.missing,
        "loaded_from": status.loaded_from,
        # `loaded_from` NOM bo'yicha yuklanganda faqat nomni beradi.
        # Haqiqiy fayl jarayon xaritasidan: bundle'dagi `_internal/cuda`
        # dan yuklandimi yoki mashinadagi boshqa CUDA'danmi — dala
        # diagnostikasida aynan shu savol beriladi.
        "paths": _loaded_cuda_paths(),
        "reason": status.reason,
    }


def _loaded_cuda_paths() -> list:
    try:
        import psutil
    except ImportError:
        return []
    prefixes = ("cudart", "cublas", "cudnn64", "cufft")
    paths = set()
    try:
        for mapping in psutil.Process().memory_maps(grouped=True):
            name = Path(mapping.path).name.lower()
            if name.endswith(".dll") and name.startswith(prefixes):
                paths.add(mapping.path)
    except Exception:  # noqa: BLE001 — diagnostika, tekshiruv sharti emas
        return []
    return sorted(paths)


def _onnx_session(require_gpu: bool) -> str:
    import numpy as np
    import onnxruntime as ort

    from core.bundle_paths import resource_root
    from proctoring.hardware import cuda_runtime

    model = resource_root() / "models" / "buffalo_l" / "det_10g.onnx"
    session = ort.InferenceSession(str(model), providers=cuda_runtime.providers())
    tensor = np.zeros((1, 3, 640, 640), dtype=np.float32)
    session.run(None, {session.get_inputs()[0].name: tensor})
    # Provayderlar INFERENSIYADAN KEYIN o'qiladi. ORT birinchi `run()` da
    # CUDA xatosini (masalan cuDNN kichik kutubxonasi topilmasa) ushlab,
    # sessiyani JIMGINA CPU'ga o'tkazadi ("Falling back to CPU") —
    # yaratilgandan keyingi ro'yxat esa hali CUDA ni ko'rsatadi. Aynan shu
    # holat cuDNN 9.26 bilan build'da bo'lgan (`requirements-build-gpu.txt`).
    active = session.get_providers()
    if require_gpu and "CUDAExecutionProvider" not in active:
        raise RuntimeError(
            "GPU talab qilingan, sessiya esa {} da. {}".format(
                active, cuda_runtime.prepare().reason
            )
        )
    return "sessiya provayderlari: {}".format(active)


def _face_align() -> str:
    """
    Yuzni tekislash — `skimage.transform` (lazy_loader) + `scipy`.

    Bu yo'l FAQAT yuz topilganda ishlaydi, ya'ni bo'sh kadr bilan
    sinab bo'lmaydi: shuning uchun kalit nuqtalar qo'lda beriladi.
    """
    import numpy as np
    from insightface.utils import face_align

    image = np.zeros((480, 640, 3), dtype=np.uint8)
    kps = np.array(
        [[280, 220], [360, 220], [320, 260], [290, 300], [350, 300]], dtype=np.float32
    )
    aligned = face_align.norm_crop(image, kps)
    return "norm_crop -> {}".format(aligned.shape)


def _face_analysis(require_gpu: bool) -> str:
    """InsightFace to'liq yuklanishi — aynan `FaceEngine` dagidek."""
    import numpy as np
    from insightface.app import FaceAnalysis

    from core.bundle_paths import resource_root
    from proctoring.hardware import cuda_runtime

    providers = cuda_runtime.providers()
    app = FaceAnalysis(
        name="buffalo_l",
        root=str(resource_root()),
        providers=providers,
        allowed_modules=["detection", "recognition"],
    )
    app.prepare(ctx_id=0 if "CUDAExecutionProvider" in providers else -1, det_size=(640, 640))
    faces = app.get(np.zeros((480, 640, 3), dtype=np.uint8))
    # Inferensiyadan keyin — `_onnx_session` dagi sabab bilan.
    detector = app.models["detection"].session.get_providers()
    if require_gpu and "CUDAExecutionProvider" not in detector:
        raise RuntimeError("detektor sessiyasi CPU'ga tushdi: {}".format(detector))
    return "modullar: {}, detektor: {}, bo'sh kadrda yuz: {}".format(
        sorted(app.models), detector[0], len(faces)
    )


def _video_writer() -> str:
    """Ekran yozuvi (`mp4v`) — OpenCV'ning videoio backend'i bundle'dami."""
    import cv2
    import numpy as np

    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "smoke.mp4"
        writer = cv2.VideoWriter(
            str(target), cv2.VideoWriter_fourcc(*"mp4v"), 5.0, (320, 240)
        )
        if not writer.isOpened():
            raise RuntimeError("VideoWriter ochilmadi (mp4v)")
        for _ in range(5):
            writer.write(np.zeros((240, 320, 3), dtype=np.uint8))
        writer.release()
        size = target.stat().st_size
    if size <= 0:
        raise RuntimeError("mp4 fayl bo'sh")
    return "mp4v {} bayt".format(size)


def _webengine(timeout_s: float) -> str:
    """
    QtWebEngine: alohida jarayon (`QtWebEngineProcess.exe`), resurslar
    (`*.pak`, `icudtl.dat`) va JavaScript.

    Sahifa ekranga CHIQARILMAYDI — `QWebEnginePage` ko'rinishsiz ham
    yuklanadi va JS bajaradi. Natija JS'dan qaytgan qiymat bilan
    tasdiqlanadi: `loadFinished(True)` bo'sh sahifada ham kelishi
    mumkin, renderer jarayoni ishlamasa esa JS javob bermaydi.
    """
    from PyQt6.QtCore import QCoreApplication, QEventLoop, Qt, QTimer
    from PyQt6.QtWidgets import QApplication

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication.instance() or QApplication(sys.argv[:1] or ["smoke"])

    from PyQt6.QtWebEngineCore import QWebEnginePage

    page = QWebEnginePage()
    loop = QEventLoop()
    result: dict = {}

    def on_js(value) -> None:
        result["js"] = value
        loop.quit()

    def on_loaded(ok: bool) -> None:
        result["loaded"] = ok
        page.runJavaScript("document.title + ':' + (6 * 7)", on_js)

    page.loadFinished.connect(on_loaded)
    page.setHtml("<html><head><title>smoke</title></head><body>ok</body></html>")
    QTimer.singleShot(int(timeout_s * 1000), loop.quit)
    loop.exec()
    page.deleteLater()
    QCoreApplication.processEvents()
    del app

    if result.get("js") != "smoke:42":
        raise RuntimeError("WebEngine javob bermadi: {}".format(result or "timeout"))
    return "JS natijasi {}".format(result["js"])


# --------------------------------------------------------------------------
def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ProctoringClientCheck", description="Client tutun tekshiruvi")
    parser.add_argument("--report", type=Path, help="Natijani matn faylga ham yozish")
    parser.add_argument("--json", type=Path, help="Natijani JSON faylga yozish")
    parser.add_argument(
        "--require-gpu", action="store_true",
        help="CUDA ishlamasa FAIL (GPU build'ni tekshirish uchun)",
    )
    parser.add_argument(
        "--require-env", action="store_true",
        help="`.env` topilmasa FAIL (o'rnatilgan mashinada)",
    )
    parser.add_argument("--skip-webengine", action="store_true")
    parser.add_argument("--webengine-timeout", type=float, default=30.0)
    args = parser.parse_args(argv)

    report = _Report()
    _prepare_like_main()

    _check(report, "muhit", _environment)
    _check(report, ".env", _env_file, required=args.require_env)
    _check(report, "kutubxonalar", _libraries)
    _check(report, "client modullari", _client_modules)
    _check(report, "modellar", _models)
    # Dev rejimda manifest yo'q (u faqat build natijasida) — ogohlantirish.
    _check(report, "model manifesti", _models_manifest, required=bool(getattr(sys, "frozen", False)))
    cuda = _check(report, "CUDA", _cuda_status, required=args.require_gpu)
    if isinstance(cuda, dict) and not cuda["available"]:
        report.add("CUDA holati", "WARN" if not args.require_gpu else "FAIL",
                   cuda["reason"], required=args.require_gpu)
    _check(report, "ONNX Runtime sessiyasi", lambda: _onnx_session(args.require_gpu))
    _check(report, "yuzni tekislash (skimage/scipy)", _face_align)
    _check(report, "InsightFace FaceAnalysis", lambda: _face_analysis(args.require_gpu))
    _check(report, "ekran yozuvi (cv2 mp4v)", _video_writer)
    if not args.skip_webengine:
        _check(report, "QtWebEngine", lambda: _webengine(args.webengine_timeout))

    verdict = "YIQILDI: {} ta tekshiruv".format(len(report.failed)) if report.failed else "HAMMASI JOYIDA"
    report.lines.append(verdict)
    if sys.stdout is not None:
        print(verdict, flush=True)

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text("\n".join(report.lines) + "\n", encoding="utf-8")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps({"ok": not report.failed, "checks": report.items}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(run())
