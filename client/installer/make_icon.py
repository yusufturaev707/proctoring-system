"""
`logo.png` dan Windows ikonkasini (`.ico`) yasaydi — BUILD vaqtida.

Nima uchun `.ico` repo'da saqlanmaydi: logotip muassasaga qarab
almashtiriladi (`resources/images/logo.png`, CLAUDE.md dagi "LOGOTIP -
FAYL" qoidasi). Ikkinchi nusxa `.ico` bo'lib yotsa, logotip
almashtirilganda `.exe` va o'rnatuvchi eski belgida qolib ketardi.
Endi manba bitta, ikonka har build'da qaytadan yasaladi.

Logotip kvadrat EMAS (150x88). To'g'ridan-to'g'ri kichraytirish uni
cho'zib yuborardi, shuning uchun u shaffof kvadrat maydonning
o'rtasiga nisbati saqlangan holda joylanadi.

Pillow faqat build mashinasida kerak — `.exe` ichiga kirmaydi.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

#: Windows Explorer, vazifalar paneli va o'rnatuvchi ishlatadigan
#: o'lchamlar. 256 — "katta belgilar" ko'rinishi uchun (PNG siqilgan
#: holda saqlanadi, ya'ni hajmga deyarli ta'sir qilmaydi).
_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def build_icon(source: Path, target: Path) -> Path:
    from PIL import Image

    image = Image.open(source).convert("RGBA")
    # Shaffof chetlarni kesamiz: logotip atrofidagi bo'sh joy kichik
    # (16 px) ikonkada belgini nuqtaga aylantirib qo'yardi.
    bbox = image.getbbox()
    if bbox:
        image = image.crop(bbox)

    side = max(image.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(image, ((side - image.width) // 2, (side - image.height) // 2))

    # Eng katta o'lchamgacha bir marta sifatli kattalashtiramiz — Pillow
    # qolgan o'lchamlarni shu rasmdan kichraytiradi.
    canvas = canvas.resize((_SIZES[-1], _SIZES[-1]), Image.Resampling.LANCZOS)

    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target, format="ICO", sizes=[(size, size) for size in _SIZES])
    return target


def main(argv: list[str] | None = None) -> int:
    client_dir = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument(
        "--source", type=Path, default=client_dir / "resources" / "images" / "logo.png"
    )
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args(argv)

    if not args.source.is_file():
        print(f"Logotip topilmadi: {args.source}", file=sys.stderr)
        return 1
    print(f"Ikonka yasaldi: {build_icon(args.source, args.target)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
