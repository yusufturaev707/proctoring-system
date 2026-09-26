# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — Proctoring Client (`--onedir`).

Ishga tushirish (odatda `installer/build.ps1` orqali):

    pyinstaller installer/proctoring_client.spec --noconfirm --distpath dist --workpath build -- --variant gpu
    pyinstaller installer/proctoring_client.spec --noconfirm --distpath dist --workpath build -- --variant cpu

`--` dan keyingi argumentlar SHU FAYLGA tegishli (PyInstaller 6+).

NIMA UCHUN `--onedir`, `--onefile` EMAS. Bundle 0.9-3.2 GB (QtWebEngine
+ CUDA + modellar). `--onefile` uni HAR ishga tushishda `%TEMP%` ga
ochadi: sovuq startga o'nlab soniya qo'shiladi, antivirus har safar
yangi joyda paydo bo'lgan yuzlab DLL'ni skanerlaydi (va ko'pincha
"packed executable" deb false-positive beradi), dastur qulasa esa
`_MEI*` katalogi diskda qolib ketadi. `onedir` bir marta o'rnatiladi,
start tez, fayllar Program Files'da imzolanishi/ro'yxatga olinishi
mumkin. Tafsilot: `installer/README.md`.

TUZILMA (`dist/ProctoringClient/`):

    ProctoringClient.exe         oynali, konsolsiz
    ProctoringClientCheck.exe    konsolli tutun tekshiruvi (smoke_check.py)
    _internal/
        resources/               logotip (`--add-data "resources;resources"`)
        models/buffalo_l/        InsightFace (det + rec + 2d106)
        models/yolo|pose/        ixtiyoriy — faqat mavjud `.onnx`
        cuda/                    GPU nashrida: CUDA 12 + cuDNN 9 DLL'lari
        onnxruntime/capi/        ORT + provayder DLL'lari
        PyQt6/Qt6/...            Qt + QtWebEngine (PyInstaller hook'lari)

`_internal/cuda` — `proctoring/hardware/cuda_runtime.py` ning 2-qidiruv
joyi (`resource_root() / "cuda"`). Frozen rejimda `sys.path` da
`site-packages` yo'q, ya'ni u `nvidia/*/bin` ni QIDIRMAYDI — DLL'lar
aynan shu katalogda bo'lishi shart. Shu sababli PyInstaller o'zi
boshqa joyga qo'ygan CUDA DLL nusxalari olib tashlanadi (pastda
`_filter_binaries`): ikki nusxa ~1 GB ortiqcha va "qaysi biri
yuklandi?" degan savol.
"""

import argparse
import os
import runpy
import site
import sys
import sysconfig
from pathlib import Path

# --------------------------------------------------------------------------
# Parametrlar
# --------------------------------------------------------------------------
_parser = argparse.ArgumentParser(prog="proctoring_client.spec")
_parser.add_argument(
    "--variant", choices=("gpu", "cpu"),
    default=os.environ.get("PROCTORING_VARIANT", "gpu").lower(),
    help="gpu: CUDA DLL'lari bilan (~1.5 GB ko'p); cpu: faqat CPU",
)
_parser.add_argument(
    "--full-buffalo", action="store_true",
    help="buffalo_l ning ishlatilmaydigan modellarini ham qo'shish (1k3d68, genderage)",
)
_parser.add_argument(
    "--no-nvrtc", action="store_true",
    help="NVRTC ni qo'shmaslik (cuDNN runtime-fusion dvigatellari uchun, ~97 MB)",
)
_parser.add_argument(
    "--no-check-exe", action="store_true",
    help="ProctoringClientCheck.exe ni yig'maslik",
)
_parser.add_argument(
    "--locales", default="en,ru,uz",
    help="Qoldiriladigan Qt/Chromium tillari (vergul bilan)",
)
OPTS = _parser.parse_args(sys.argv[1:])

SPEC_DIR = Path(SPECPATH).resolve()          # noqa: F821 — PyInstaller beradi
CLIENT_DIR = SPEC_DIR.parent
WORK_DIR = Path(workpath).resolve()          # noqa: F821
WORK_DIR.mkdir(parents=True, exist_ok=True)

VERSION = runpy.run_path(str(CLIENT_DIR / "version.py"))
EXE_NAME = VERSION["EXE_NAME"]

print("[spec] variant={} version={} full_buffalo={} nvrtc={} locales={}".format(
    OPTS.variant, VERSION["__version__"], OPTS.full_buffalo, not OPTS.no_nvrtc, OPTS.locales,
))

# --------------------------------------------------------------------------
# Modellar
# --------------------------------------------------------------------------
# buffalo_l dan FAQAT ishlatiladiganlari. `FaceAnalysis` katalogdagi
# HAR `.onnx` ni ochib ko'radi (taskname aniqlash uchun ONNX sessiyasi
# yaratadi) va `allowed_modules` ga kirmaganini keyin tashlaydi — ya'ni
# ortiqcha fayl nafaqat bundle hajmi (1k3d68 = 137 MB), balki HAR ishga
# tushishda bekorga yuklanadigan model. `face_engine` faqat
# `detection` + `recognition` ni oladi; `2d106det` (5 MB) nigoh moduli
# uchun qoldiriladi (`face_identity._detect_with_landmarks`).
_BUFFALO_REQUIRED = ["det_10g.onnx", "w600k_r50.onnx"]
_BUFFALO_OPTIONAL = ["2d106det.onnx"]
_BUFFALO_UNUSED = ["1k3d68.onnx", "genderage.onnx"]


def _model_datas() -> list:
    models = CLIENT_DIR / "models"
    buffalo = models / "buffalo_l"
    missing = [name for name in _BUFFALO_REQUIRED if not (buffalo / name).is_file()]
    if missing:
        # Frozen rejimda `face_engine` modelni internetdan YUKLAMAYDI
        # (imtihon mashinasi oflayn) — modelsiz build yaroqsiz, uni
        # tarqatishdan oldin to'xtatamiz.
        raise SystemExit(
            "[spec] XATO: InsightFace modellari yo'q: {} ({}). "
            "`client/models/README.md` ga qarang.".format(", ".join(missing), buffalo)
        )

    names = _BUFFALO_REQUIRED + _BUFFALO_OPTIONAL
    if OPTS.full_buffalo:
        names += _BUFFALO_UNUSED
    datas = [
        (str(buffalo / name), "models/buffalo_l")
        for name in names if (buffalo / name).is_file()
    ]

    # YOLO / poza — IXTIYORIY: model yo'q bo'lsa modul jimgina o'chadi
    # va `proctoring_degraded` hodisasi chiqadi (`models/README.md`).
    # Faqat `.onnx` va klass nomlari: `.pt` (Ultralytics manbasi)
    # client'da ishlatilmaydi va 25 MB ortiqcha.
    for sub, patterns in (("yolo", ("*.onnx", "*.labels.txt")), ("pose", ("*.onnx",))):
        for pattern in patterns:
            for path in sorted((models / sub).glob(pattern)):
                datas.append((str(path), "models/" + sub))
    if not any(dest == "models/yolo" and src.endswith(".onnx") for src, dest in datas):
        print("[spec] OGOHLANTIRISH: models/yolo/*.onnx yo'q — obyekt aniqlash o'chiq bo'ladi")
    return datas


# --------------------------------------------------------------------------
# CUDA (faqat GPU nashri)
# --------------------------------------------------------------------------
# `cuda_runtime._CUDA_PREFIXES` bilan bir xil — "qaysi DLL CUDA'niki"
# degan savolga ikki joyda ikki xil javob bo'lmasligi kerak.
_CUDA_PREFIXES = (
    "cudart", "cublas", "cudnn", "cufft", "curand", "cusparse",
    "cusolver", "nvrtc", "nvjitlink", "cupti", "nccl",
)


def _site_dirs() -> list:
    dirs = []
    for value in [*site.getsitepackages(), sysconfig.get_paths()["purelib"]]:
        path = Path(value)
        if path.is_dir() and path not in dirs:
            dirs.append(path)
    return dirs


def _cuda_search_dirs() -> list:
    """
    CUDA DLL manbalari — TARTIB bilan.

    `nvidia-*` pip g'ildiraklari birinchi: ular `requirements-build.txt`
    da qadalgan, ya'ni build takrorlanadi. `CUDA_PATH` — mashinada
    Toolkit bor bo'lsa. `torch/lib` OXIRIDA va ogohlantirish bilan:
    u dev mashinasida bor, lekin torch versiyasiga bog'liq boshqa CUDA
    minor versiyasini olib keladi.
    """
    dirs = []

    def add(path, source):
        path = Path(path)
        if path.is_dir() and all(path != known for known, _ in dirs):
            dirs.append((path, source))

    for item in os.environ.get("CUDA_DLL_DIR", "").split(os.pathsep):
        if item.strip():
            add(item.strip(), "CUDA_DLL_DIR")
    for site_dir in _site_dirs():
        nvidia = site_dir / "nvidia"
        if nvidia.is_dir():
            for child in sorted(nvidia.iterdir()):
                add(child / "bin", "pip")
    for name, value in os.environ.items():
        if name.upper().startswith("CUDA_PATH"):
            add(Path(value) / "bin", "CUDA_PATH")
    for site_dir in _site_dirs():
        add(site_dir / "torch" / "lib", "torch")
    return dirs


def _pe_imports(path: Path) -> list:
    import pefile  # PyInstaller'ning o'z bog'liqligi

    pe = pefile.PE(str(path), fast_load=True)
    try:
        pe.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]]
        )
        return [
            entry.dll.decode("ascii", "replace")
            for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])
        ]
    finally:
        pe.close()


def _is_cuda(name: str) -> bool:
    return name.lower().startswith(_CUDA_PREFIXES)


def _cuda_binaries() -> list:
    """
    CUDA DLL'lari — ro'yxat QADALMAYDI, provayder DLL'idan o'qiladi.

    `cuda_runtime` bilan bir xil qoida: kerakli kutubxonalar
    `onnxruntime_providers_cuda.dll` ning PE import jadvalida. ORT
    nashri o'zgarsa (CUDA 12 -> 13) ro'yxat o'zi o'zgaradi; qadalgan
    ro'yxat esa jimgina eskirib, bundle'ga noto'g'ri DLL'larni olardi.

    Keyin YOPIQLIK: topilgan DLL'larning o'z CUDA importlari (cublas ->
    cublasLt). Va ikkita DINAMIK yuklanadigan guruh — ular import
    jadvalida ko'rinmaydi:

      * cuDNN 9 kichik kutubxonalari (`cudnn_*64_9.dll`) — `cudnn64_9`
        ularni ishlash paytida o'z katalogidan yuklaydi. Birortasi
        yetishmasa xato INFERENSIYA paytida chiqadi, yuklashda emas;
      * NVRTC — cuDNN'ning runtime-fusion dvigatellari uchun.
    """
    import onnxruntime

    provider = Path(onnxruntime.__file__).parent / "capi" / "onnxruntime_providers_cuda.dll"
    if not provider.is_file():
        raise SystemExit(
            "[spec] XATO: GPU nashri so'raldi, lekin {} yo'q — venv'da `onnxruntime` ning "
            "CPU paketi o'rnatilgan. `--variant cpu` bilan yig'ing yoki "
            "`onnxruntime-gpu` o'rnating.".format(provider)
        )

    search = _cuda_search_dirs()

    def locate(name: str):
        for directory, source in search:
            candidate = directory / name
            if candidate.is_file():
                return candidate, source
        return None, None

    found: dict = {}
    missing: list = []
    queue = [name for name in _pe_imports(provider) if _is_cuda(name)]
    while queue:
        name = queue.pop(0)
        key = name.lower()
        if key in found or name in missing:
            continue
        path, source = locate(name)
        if path is None:
            missing.append(name)
            continue
        found[key] = (path, source)
        queue.extend(dep for dep in _pe_imports(path) if _is_cuda(dep))

    # cuDNN kichik kutubxonalari — `cudnn64_*.dll` bilan BIR katalogdan
    # (versiyalar aralashmasligi uchun boshqa manbadan olinmaydi).
    for key, (path, source) in list(found.items()):
        if key.startswith("cudnn64_"):
            for extra in sorted(path.parent.glob("cudnn_*.dll")):
                found.setdefault(extra.name.lower(), (extra, source))

    # cuDNN 9.2x `cudnn_engines_tensor_ir64_9.dll` ni NOMI bo'yicha oddiy
    # LoadLibrary bilan yuklaydi va uni `_internal/cuda` dan topolmaydi —
    # GPU nashri birinchi Conv'da jimgina CPU'ga tushadi
    # (`requirements-build-gpu.txt` dagi izoh, o'lchangan).
    if any(key.startswith("cudnn_engines_tensor_ir") for key in found):
        print("[spec] OGOHLANTIRISH: cuDNN 9.2x (tensor_ir) — ORT 1.22 bilan CPU'ga tushadi. "
              "nvidia-cudnn-cu12==9.10.2.21 o'rnating va `build.ps1 -RequireGpuSmoke` bilan tekshiring.")

    if not OPTS.no_nvrtc:
        for directory, source in search:
            main = sorted(p for p in directory.glob("nvrtc64_*.dll") if ".alt." not in p.name)
            if main:
                for path in main + sorted(directory.glob("nvrtc-builtins64_*.dll")):
                    found.setdefault(path.name.lower(), (path, source))
                break

    if missing:
        raise SystemExit(
            "[spec] XATO: CUDA kutubxonalari topilmadi: {}. `pip install -r "
            "installer/requirements-build.txt` (GPU bo'limi) yoki CUDA_DLL_DIR.".format(
                ", ".join(missing)
            )
        )

    total = 0
    for key, (path, source) in sorted(found.items()):
        size = path.stat().st_size
        total += size
        flag = "  <- torch/lib: CUDA minor versiyasi torch'niki" if source == "torch" else ""
        print("[spec] cuda: {:<45} {:>7.1f} MB  [{}]{}".format(path.name, size / 2**20, source, flag))
    print("[spec] cuda: jami {:.0f} MB".format(total / 2**20))
    return [(str(path), "cuda") for path, _ in found.values()]


# --------------------------------------------------------------------------
# Istisnolar
# --------------------------------------------------------------------------
# Faqat ISHLATILMAYDIGANI chiqariladi — bu ro'yxat haqiqiy importlar
# kuzatuvidan tuzilgan (`installer/README.md`, "Import tahlili").
# Venv'da turgan, lekin client import qilmaydigan og'ir paketlar ham
# shu yerda: PyInstaller ularni biror kutubxonaning ixtiyoriy importi
# orqali tortib olishi mumkin (torch 4.3 GB).
#
# SCIPY BUTUNLAY CHIQARILMAYDI: insightface `face_align` ->
# `skimage.transform.SimilarityTransform` -> `scipy.linalg/spatial`.
# U har yuz tekshiruvida ishlaydi. Chiqariladi faqat hech bir ishlash
# yo'lida yuklanmaydigan qism-paketlar.
EXCLUDES = [
    # ML / hisoblash — client'da yo'q
    "torch", "torchvision", "torchaudio", "torchgen", "functorch",
    "tensorflow", "keras", "jax", "sympy", "mpmath", "networkx", "numba",
    "pandas", "sklearn",
    # GUI / grafik — Qt'dan boshqasi kerak emas
    "tkinter", "_tkinter", "turtle", "turtledemo", "idlelib",
    "matplotlib", "PIL", "imageio", "tifffile",
    # Ishlab chiqish vositalari
    "IPython", "jupyter", "notebook", "ipykernel", "pytest", "_pytest",
    "sphinx", "docutils", "setuptools", "pkg_resources", "pip",
    "_distutils_hack", "lib2to3", "pydoc_data", "Cython",
    "fsspec", "jinja2",
    # insightface: GUI, CLI, niqob renderi (main.py uni stub bilan
    # almashtiradi), mxnet ma'lumot yig'uvchi
    "insightface.gui", "insightface.commands",
    "insightface.app.mask_renderer", "insightface.thirdparty.face3d",
    "insightface.data.rec_builder", "albumentations", "mxnet",
    # onnxruntime: kvantlash, transformer vositalari (torch tortadi)
    "onnxruntime.transformers", "onnxruntime.quantization",
    "onnxruntime.tools", "onnxruntime.training",
    # Qt QML/Quick: QtWebEngineCore.dll ularga BOG'LANGAN (Qt6Quick.dll,
    # Qt6Qml.dll bog'liqlik tahlili orqali baribir keladi), lekin PyInstaller
    # shundan Python modulini ham xulosa qiladi va QtQml hook'i butun
    # `qml/` plaginlar daraxtini (Quick3D, Controls2, Multimedia...) va
    # ularning ~50 DLL'ini tortib keladi. Client QML ishlatmaydi —
    # WebEngine Widgets orqali.
    "PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtQuickWidgets", "PyQt6.QtQuick3D",
    # scipy: yuz tekislash yo'lida yuklanmaydiganlar
    "scipy.stats", "scipy.optimize", "scipy.integrate", "scipy.interpolate",
    "scipy.signal", "scipy.io", "scipy.ndimage", "scipy.odr", "scipy.cluster",
    "scipy.datasets", "scipy.misc", "scipy.fftpack", "scipy.differentiate",
]

# Aniq tahlil natijasida kerak bo'lgan yashirin importlar. Hozir BO'SH:
# `skimage.transform` ning lazy `.pyi` fayllarini
# contrib hook yig'adi. Bu ro'yxatga faqat `ProctoringClientCheck.exe`
# (client modullari tekshiruvi) ko'rsatgan modul qo'shiladi.
HIDDENIMPORTS: list = []


# --------------------------------------------------------------------------
# Analiz natijasini tozalash
# --------------------------------------------------------------------------
_KEEP_LOCALES = {code.strip().lower() for code in OPTS.locales.split(",") if code.strip()} | {"en"}


def _locale_of(dest: str):
    """Qt tarjima fayli va Chromium lokali uchun til kodi (yoki None)."""
    path = Path(dest)
    parts = [part.lower() for part in path.parts]
    if "qtwebengine_locales" in parts and path.suffix == ".pak":
        return path.stem.split("-")[0].lower()           # en-US.pak -> en
    if "translations" in parts and path.suffix == ".qm":
        stem = path.stem                                  # qtbase_zh_CN
        tail = stem.split("_", 1)[1] if "_" in stem else ""
        return tail.split("_")[0].lower() or None         # zh
    return None


def _filter_datas(datas):
    """
    Qt / Chromium tarjimalaridan faqat kerakli tillar qoladi.

    ~40 MB `qtwebengine_locales/*.pak` — Chromium'ning kontekst menyu
    va xato sahifalari matni. Imtihon sahifasida ular deyarli
    ko'rinmaydi; tanlangan til yo'q bo'lsa Chromium `en-US` ga
    tushadi, shuning uchun inglizcha HAR DOIM qoladi.
    """
    kept, dropped = [], 0
    for entry in datas:
        # `*.debug.pak`, `v8_context_snapshot.debug.bin` (~78 MB) — faqat
        # Qt'ning DEBUG yig'ilishi (`Qt6WebEngineCored.dll`) o'qiydi.
        if ".debug." in Path(entry[0]).name.lower():
            dropped += 1
            continue
        code = _locale_of(entry[0])
        if code is not None and code not in _KEEP_LOCALES:
            dropped += 1
            continue
        kept.append(entry)
    print("[spec] tarjima/debug: {} ta fayl olib tashlandi (qoldi: {})".format(
        dropped, ", ".join(sorted(_KEEP_LOCALES))))
    return kept


def _filter_binaries(binaries):
    """
    Uch qoida:

      * CUDA DLL faqat `cuda/` da — PyInstaller'ning bog'liqlik tahlili
        ularni (PATH yoki torch orqali) boshqa joyga ham qo'yishi
        mumkin, ikki nusxa esa ~1 GB va noaniq yuklanish tartibi;
      * CPU nashrida CUDA provayderi (320 MB) olib tashlanadi. ORT
        ro'yxatida `CUDAExecutionProvider` qoladi (u `onnxruntime.dll`
        ga kompilyatsiya qilingan), lekin `cuda_runtime` provayder
        faylini topmaydi va to'g'ri CPU ro'yxatini qaytaradi;
      * TensorRT provayderi HAR IKKALA nashrda olib tashlanadi: TensorRT
        kutubxonalari bundle'da yo'q va client uni so'ramaydi.
    """
    kept, dropped = [], []
    for entry in binaries:
        dest = Path(entry[0])
        name = dest.name.lower()
        in_cuda_dir = dest.parent.as_posix().lower() == "cuda"
        if _is_cuda(name) and (OPTS.variant == "cpu" or not in_cuda_dir):
            dropped.append(entry[0])
            continue
        if name == "onnxruntime_providers_tensorrt.dll":
            dropped.append(entry[0])
            continue
        if OPTS.variant == "cpu" and name == "onnxruntime_providers_cuda.dll":
            dropped.append(entry[0])
            continue
        kept.append(entry)
    for item in dropped:
        print("[spec] binar olib tashlandi: {}".format(item))
    return kept


# --------------------------------------------------------------------------
# Ikonka va versiya resursi — BITTA manbadan (logo.png, version.py)
# --------------------------------------------------------------------------
def _make_icon():
    target = WORK_DIR / "app.ico"
    try:
        runpy.run_path(str(SPEC_DIR / "make_icon.py"), run_name="make_icon")["build_icon"](
            CLIENT_DIR / "resources" / "images" / "logo.png", target
        )
        return str(target)
    except Exception as exc:  # Pillow yo'q yoki logotip buzilgan
        print("[spec] OGOHLANTIRISH: ikonka yasalmadi ({}) — standart belgi".format(exc))
        return None


def _version_file(original_filename: str, description: str) -> str:
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable,
        VarFileInfo, VarStruct, VSVersionInfo,
    )

    raw = VERSION["__version__"]
    numbers = []
    for part in raw.split("-")[0].split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        numbers.append(int(digits or 0))
    numbers = (numbers + [0, 0, 0, 0])[:4]

    info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=tuple(numbers), prodvers=tuple(numbers)),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("CompanyName", VERSION["COMPANY_NAME"]),
                StringStruct("FileDescription", description),
                StringStruct("FileVersion", raw),
                StringStruct("InternalName", Path(original_filename).stem),
                StringStruct("LegalCopyright", VERSION["COPYRIGHT"]),
                StringStruct("OriginalFilename", original_filename),
                StringStruct("ProductName", VERSION["APP_NAME"]),
                StringStruct("ProductVersion", raw),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )
    # Matn ko'rinishida yoziladi (`version_info.txt`) — build natijasini
    # ko'z bilan tekshirish uchun; PyInstaller ham aynan shu faylni o'qiydi.
    target = WORK_DIR / "version_info_{}.txt".format(Path(original_filename).stem)
    target.write_text(str(info), encoding="utf-8")
    return str(target)


ICON = _make_icon()
COMMON_ANALYSIS = dict(
    pathex=[str(CLIENT_DIR)],
    hiddenimports=HIDDENIMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    # 0 — docstring va assert'lar saqlanadi: numpy/scipy docstring'larni
    # ishlash paytida o'zgartiradi (`add_newdoc`) va `-OO` ularni buzadi.
    optimize=0,
)

# --------------------------------------------------------------------------
# Asosiy dastur
# --------------------------------------------------------------------------
a = Analysis(  # noqa: F821
    [str(CLIENT_DIR / "main.py")],
    binaries=_cuda_binaries() if OPTS.variant == "gpu" else [],
    datas=[(str(CLIENT_DIR / "resources"), "resources"), *_model_datas()],
    **COMMON_ANALYSIS,
)
a.binaries = _filter_binaries(a.binaries)
a.datas = _filter_datas(a.datas)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=EXE_NAME,
    icon=ICON,
    version=_version_file(EXE_NAME + ".exe", VERSION["FILE_DESCRIPTION"]),
    console=False,
    # asInvoker: kiosk oddiy foydalanuvchi ostida ishlaydi. Administrator
    # huquqi kerak bo'lgan tozalash (xizmatlarni to'xtatish) uchun
    # yuqori huquq Task Scheduler vazifasi orqali beriladi
    # (`proctoring_client.iss`, "autostart") — manifestdagi
    # `requireAdministrator` har ishga tushishda UAC oynasini chiqarardi.
    uac_admin=False,
    # UPX O'CHIQ: Qt/CUDA DLL'larini siqish ularni buzadi (CFG,
    # imzo), yuklanishni sekinlashtiradi va antivirus false-positive'ining
    # eng ko'p uchraydigan sababi. Hajmni o'rnatuvchidagi LZMA2 kamaytiradi.
    upx=False,
    strip=False,
    debug=False,
    bootloader_ignore_signals=False,
)
executables = [exe]
binaries, datas = a.binaries, a.datas

# --------------------------------------------------------------------------
# Tutun tekshiruvi — o'sha `_internal` ustida, konsol bilan
# --------------------------------------------------------------------------
def _client_modules() -> list:
    """
    Client'ning barcha modullari — fayl tizimidan.

    Har `.exe` o'z PYZ arxiviga ega va `smoke_check` client modullarini
    `importlib` bilan (dinamik) yuklaydi — statik tahlil ularni
    ko'rmaydi. Ro'yxat qo'lda yozilmaydi: yangi modul tekshiruvdan
    tushib qolmasligi kerak. `collect_submodules` ishlatilmadi: u
    paketlarni build jarayonida IMPORT qiladi (config `.env` o'qiydi,
    services Qt'ni yuklaydi).
    """
    names = ["config", "main_window", "version"]
    for package in ("core", "services", "proctoring", "ui"):
        for path in sorted((CLIENT_DIR / package).rglob("*.py")):
            parts = list(path.relative_to(CLIENT_DIR).with_suffix("").parts)
            if parts[-1] == "__init__":
                parts = parts[:-1]
            names.append(".".join(parts))
    return names


if not OPTS.no_check_exe:
    check = Analysis(  # noqa: F821
        [str(SPEC_DIR / "smoke_check.py")],
        binaries=[],
        datas=[],
        **{**COMMON_ANALYSIS, "hiddenimports": HIDDENIMPORTS + _client_modules()},
    )
    check.binaries = _filter_binaries(check.binaries)
    check.datas = _filter_datas(check.datas)
    check_exe = EXE(  # noqa: F821
        PYZ(check.pure),  # noqa: F821
        check.scripts,
        [],
        exclude_binaries=True,
        name=EXE_NAME + "Check",
        icon=ICON,
        version=_version_file(EXE_NAME + "Check.exe", "Proctoring Client - diagnostika"),
        console=True,
        uac_admin=False,
        upx=False,
        strip=False,
    )
    executables.append(check_exe)
    binaries = binaries + check.binaries
    datas = datas + check.datas

coll = COLLECT(  # noqa: F821
    *executables,
    binaries,
    datas,
    strip=False,
    upx=False,
    name=EXE_NAME,
)
