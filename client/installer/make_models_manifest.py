"""
Model yaxlitligi manifesti — `<ilova katalogi>/models_manifest.json`.

`build.ps1` PyInstaller'dan KEYIN chaqiradi:

    venv\\Scripts\\python installer\\make_models_manifest.py --app-dir dist\\gpu\\ProctoringClient

NIMA UCHUN. Client ishga tushishda modellarni o'zi tekshiradi (fayl
buzilgan, qisqargan yoki almashtirilgan bo'lsa ONNX Runtime xatoni
faqat yuklashda, ba'zan esa umuman bermaydi - "yuz topilmadi" bo'lib
ko'rinadi). Solishtirish uchun etalon BUILD paytida, aynan tarqatiladigan
fayllardan olinadi - qo'lda yozilgan xesh birinchi model yangilanishida
eskiradi.

SHAKL (client o'quvchisi bilan SHARTNOMA):

    {"files": {"models/buffalo_l/det_10g.onnx": {"size": 16923827, "sha256": "..."}},
     "base": "_internal"}

  * kalit - `core.bundle_paths.resource_root()` ga NISBATAN yo'l, `/`
    bilan. onedir'da `resource_root()` = `sys._MEIPASS` =
    `<exe yoni>/_internal`, ya'ni fayl `<exe yoni>/_internal/models/...`
    da yotadi (client `resource_root() / "models"` dan o'qiydi -
    `config.FACE_MODEL_ROOT`, `proctoring_supervisor`);
  * `base` - faqat MA'LUMOT uchun (odam o'qishi uchun); o'quvchi
    `resource_root()` ga tayanadi;
  * manifestning o'zi `.exe` YONIDA (`_internal` da emas) - u bundle'ga
    PyInstaller'dan keyin qo'shiladi va o'rnatuvchi `{app}` ni butunligicha
    ko'chiradi.

`models/` ostidagi HAR fayl kiradi (`.onnx` va `*.labels.txt`): klass
nomlari fayli almashtirilsa detektor "telefon" o'rniga boshqa narsa
deb yozardi.

FAYL FAQAT stdlib ISHLATADI - build venv'idan boshqa narsa kerak emas.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

MANIFEST_NAME = "models_manifest.json"
RESOURCE_DIR = "_internal"
_CHUNK = 4 * 1024 * 1024


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def build_manifest(app_dir: Path) -> dict:
    resource_root = app_dir / RESOURCE_DIR
    models = resource_root / "models"
    if not models.is_dir():
        raise SystemExit("XATO: modellar katalogi yo'q: {}".format(models))
    files = {}
    for path in sorted(p for p in models.rglob("*") if p.is_file()):
        key = path.relative_to(resource_root).as_posix()
        files[key] = {"size": path.stat().st_size, "sha256": sha256_of(path)}
    if not files:
        raise SystemExit("XATO: {} bo'sh".format(models))
    return {"files": files, "base": RESOURCE_DIR}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make_models_manifest")
    parser.add_argument("--app-dir", type=Path, required=True,
                        help="PyInstaller natijasi (ProctoringClient.exe turgan katalog)")
    args = parser.parse_args(argv)

    app_dir = args.app_dir.resolve()
    manifest = build_manifest(app_dir)
    target = app_dir / MANIFEST_NAME
    # Vaqtinchalik fayl + almashtirish: yarim yozilgan manifest
    # o'rnatuvchiga tushib, har mashinada "model buzilgan" deb
    # yolg'on signal bermasligi uchun.
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(target)

    total = sum(item["size"] for item in manifest["files"].values())
    print("Manifest: {} ({} fayl, {:.1f} MB)".format(target, len(manifest["files"]), total / 2**20))
    for key in manifest["files"]:
        print("  " + key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
