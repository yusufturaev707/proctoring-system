"""
Logotipdan Windows ikonkasini (`.ico`) yasaydi — BUILD vaqtida.

Manba — `resources/images/logo_bba.svg` (muassasa muhri). Shu ikonka
`.exe` ga, ish stoli/«Start» yorlig'iga, o'rnatuvchi va «Programs and
Features» ga tushadi. Dastur ICHIDAGI logotip (sarlavha, splash) —
alohida fayl, `logo.png`.

Nima uchun `.ico` repo'da saqlanmaydi: logotip muassasaga qarab
almashtiriladi. Ikkinchi nusxa `.ico` bo'lib yotsa, logotip
almashtirilganda `.exe` va o'rnatuvchi eski belgida qolib ketardi.
Manba bitta, ikonka har build'da qaytadan yasaladi.

Pillow (va SVG'ning zaxira yo'li uchun PyQt6) faqat build mashinasida
kerak — `.exe` ichiga kirmaydi.
"""

from __future__ import annotations

import argparse
import base64
import io
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

#: Windows Explorer, vazifalar paneli va o'rnatuvchi ishlatadigan
#: o'lchamlar. 256 — "katta belgilar" ko'rinishi uchun (PNG siqilgan
#: holda saqlanadi, ya'ni hajmga deyarli ta'sir qilmaydi).
_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]

#: Shu o'lchamgacha kadr kichraytirilgandan keyin biroz o'tkirlanadi:
#: LANCZOS muhr chizig'i va harflarni 1-2 piksellik xira dog'ga
#: aylantiradi, vazifalar paneli (24-32 px) va «Details» ro'yxatida
#: (16 px) belgi loyqa ko'rinardi. Katta o'lchamda o'tkirlash shovqin beradi.
_SHARPEN_UP_TO = 48

#: Shu o'lchamgacha muhrning faqat ICHKI doirasi («BBA» belgisi va uning
#: halqasi) olinadi. To'liq muhrda 16-32 px da aylana yozuv bilan belgi
#: 1 pikseldan ingichka bo'lib, oq fonda deyarli ko'rinmasdi (vazifalar
#: paneli, «Start», Explorer ro'yxati); 40-48 px da (ish stoli yorlig'i,
#: 100% masshtab) yozuv shovqinga aylanib, belgini ezib qo'yardi.
#: 64 px dan — to'liq muhr (yozuv o'qiladi).
_SMALL_UP_TO = 48

#: Ichki doira tashqi doiraning qancha qismi (`logo_bba.svg` da o'lchangan:
#: 395 px muhrda ichki halqa 136..397 px, 261/395 = 0.661; halqaning
#: silliq cheti kesilmasligi uchun biroz kattaroq). Logotip
#: almashtirilsa — qayta o'lchang yoki `1.0` (to'liq logotip).
_SMALL_MARK = 0.67

#: SVG shu o'lchamda (eng katta kadrdan 4 marta katta) chiziladi — har
#: bir kadr unga nisbatan KICHRAYTIRILADI, kattalashtirilmaydi.
_MASTER_SIDE = _SIZES[-1] * 4

_SVG = "{http://www.w3.org/2000/svg}"
_XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
DEFAULT_SOURCE = Path(__file__).resolve().parent.parent / "resources" / "images" / "logo_bba.svg"


def build_icon(source: Path, target: Path) -> Path:
    from PIL import Image

    image = load_logo(Path(source))
    # Shaffof chetlarni kesamiz: logotip atrofidagi bo'sh joy kichik
    # (16 px) ikonkada belgini nuqtaga aylantirib qo'yardi.
    bbox = image.getchannel("A").getbbox()
    if not bbox:
        raise ValueError("logotip bo'sh: {}".format(source))
    image = image.crop(bbox)

    # Kvadrat bo'lmagan logotip cho'zilmasligi uchun shaffof kvadrat
    # maydonning o'rtasiga nisbati saqlangan holda joylanadi.
    side = max(image.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(image, ((side - image.width) // 2, (side - image.height) // 2))

    small = _center_mark(canvas, _SMALL_MARK)

    # Har o'lcham ASL rasmdan alohida kichraytiriladi (Pillow'ning o'zi
    # 256 dan zanjir qilib kichraytirardi) va kichiklari o'tkirlanadi.
    frames = [_frame(small if size <= _SMALL_UP_TO else canvas, size) for size in _SIZES]
    target.parent.mkdir(parents=True, exist_ok=True)
    frames[-1].save(
        target,
        format="ICO",
        sizes=[(size, size) for size in _SIZES],
        append_images=frames[:-1],
    )
    return target


def _center_mark(canvas, fraction: float):
    """Kvadrat logotipning markazidagi doira (`fraction` — diametr ulushi)."""
    from PIL import Image, ImageChops, ImageDraw

    if fraction >= 1.0:
        return canvas
    side = canvas.width
    inner = max(1, round(side * fraction))
    offset = (side - inner) // 2
    mark = canvas.crop((offset, offset, offset + inner, offset + inner))
    mask = Image.new("L", mark.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, inner - 1, inner - 1), fill=255)
    mark.putalpha(ImageChops.multiply(mark.getchannel("A"), mask))
    return mark


def _frame(canvas, size: int):
    import numpy as np
    from PIL import Image, ImageFilter

    # Ranglar oldindan alfaga ko'paytiriladi (RGBa): aks holda shaffof
    # chetdagi (ko'rinmaydigan) piksel rangi kichraytirish va
    # o'tkirlashda aralashib, doira atrofida qora hoshiya paydo qilardi.
    frame = canvas.convert("RGBa").resize((size, size), Image.Resampling.LANCZOS)
    if size > _SHARPEN_UP_TO:
        return frame.convert("RGBA")
    # Filtr RGBa rejimini qabul qilmaydi — baytlar RGBA deb o'qiladi
    # (alfa ham o'tkirlanadi — doira cheti ham aniqlashadi).
    raw = Image.frombytes("RGBA", frame.size, frame.tobytes())
    raw = raw.filter(ImageFilter.UnsharpMask(radius=0.6, percent=80 if size <= 24 else 50, threshold=1))
    pixels = np.array(raw)
    # O'tkirlash rangni alfadan oshirishi mumkin — ko'paytirilgan rang
    # uchun bu yaroqsiz (aks holda chetda yorqin nuqtalar).
    pixels[..., :3] = np.minimum(pixels[..., :3], pixels[..., 3:4])
    return Image.frombytes("RGBa", frame.size, pixels.tobytes()).convert("RGBA")


# --------------------------------------------------------------------------
# Logotipni o'qish
# --------------------------------------------------------------------------
def load_logo(source: Path):
    """Logotipni RGBA rasm sifatida qaytaradi (PNG/JPG yoki SVG)."""
    from PIL import Image

    if source.suffix.lower() == ".svg":
        return render_svg(source, _MASTER_SIDE)
    return Image.open(source).convert("RGBA")


def render_svg(source: Path, side: int):
    """SVG'ni `side` piksel kenglikda chizadi.

    Ikki yo'l:

    1. Figma eksporti — shakl (doira/yumaloq to'rtburchak) ichiga
       `<pattern>` orqali joylangan rastr rasm. QtSvg (SVG Tiny 1.2)
       `pattern` ni QO'LLAMAYDI va bo'sh rasm qaytaradi, shuning uchun
       bu tuzilma shu yerda o'qiladi: rasm asl o'lchamida olinadi,
       shakl bilan kesiladi.
    2. Qolgan (vektor) SVG — QtSvg bilan.
    """
    root = ET.parse(source).getroot()
    image = _render_pattern_fill(root, side)
    if image is None:
        image = _render_with_qt(source, side)
    if image is None or not image.getchannel("A").getbbox():
        raise ValueError("SVG chizilmadi (qo'llanmaydigan tuzilma): {}".format(source))
    return image


def _render_pattern_fill(root, side: int):
    from PIL import Image, ImageChops, ImageDraw

    view = _view_box(root)
    shape, pattern_id = _pattern_shape(root)
    if shape is None:
        return None
    pattern = _by_id(root, pattern_id)
    if pattern is None or pattern.get("patternContentUnits") != "objectBoundingBox":
        return None
    use = pattern.find(_SVG + "use")
    if use is None:
        return None
    raster = _by_id(root, _href(use).lstrip("#"))
    if raster is None or raster.tag != _SVG + "image":
        return None
    picture = _decode_data_uri(_href(raster))
    if picture is None:
        return None
    # Rasm `<image width/height>` ga cho'ziladi (preserveAspectRatio="none").
    picture = picture.convert("RGBA")
    declared = (round(float(raster.get("width") or picture.width)), round(float(raster.get("height") or picture.height)))
    if picture.size != declared:
        picture = picture.resize(declared, Image.Resampling.LANCZOS)

    a, b, c, d, e, f = _parse_transform(use.get("transform", ""))
    vx, vy, vw, vh = view
    bx, by, bw, bh, rx, ry = _shape_box(shape)
    scale = side / vw
    height = max(1, round(vh * scale))

    # Rasm pikseli (i, j) -> pattern (u, v) -> viewBox -> natija pikseli
    # (X, Y). Pillow'ga TESKARI almashtirish kerak: (X, Y) -> (i, j).
    # u = a*i + c*j + e,  v = b*i + d*j + f
    # X = (bx + bw*u - vx) * scale,  Y = (by + bh*v - vy) * scale
    u_x, u_0 = 1.0 / (bw * scale), (vx - bx) / bw
    v_y, v_0 = 1.0 / (bh * scale), (vy - by) / bh
    det = a * d - b * c
    if not det:
        return None
    # (i, j) = M^-1 * ((u, v) - (e, f))
    ia, ib, ic, id_ = d / det, -c / det, -b / det, a / det
    data = (
        ia * u_x, ib * v_y, ia * (u_0 - e) + ib * (v_0 - f),
        ic * u_x, id_ * v_y, ic * (u_0 - e) + id_ * (v_0 - f),
    )
    filled = picture.transform((side, height), Image.Transform.AFFINE, data, resample=Image.Resampling.BICUBIC)

    mask = Image.new("L", (side, height), 0)
    box = [(bx - vx) * scale, (by - vy) * scale, (bx - vx + bw) * scale - 1, (by - vy + bh) * scale - 1]
    radius = min(max(rx, ry) * scale, min(box[2] - box[0], box[3] - box[1]) / 2)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
    # Rasmning o'z shaffofligi ham saqlanadi (shakl ∩ rasm).
    filled.putalpha(ImageChops.multiply(filled.getchannel("A"), mask))
    return filled


def _pattern_shape(root):
    for node in root.iter():
        if node.tag not in (_SVG + "rect", _SVG + "circle", _SVG + "ellipse"):
            continue
        match = re.fullmatch(r"\s*url\(\s*#([^)\s]+)\s*\)\s*", node.get("fill", ""))
        if match:
            return node, match.group(1)
    return None, None


def _shape_box(shape):
    """(x, y, kenglik, balandlik, rx, ry) — viewBox birligida."""
    num = lambda name, default=0.0: float(shape.get(name) or default)  # noqa: E731
    if shape.tag == _SVG + "rect":
        rx = shape.get("rx")
        ry = shape.get("ry")
        rx_v = float(rx if rx is not None else ry or 0)
        ry_v = float(ry if ry is not None else rx or 0)
        return num("x"), num("y"), num("width"), num("height"), rx_v, ry_v
    if shape.tag == _SVG + "circle":
        r = num("r")
        return num("cx") - r, num("cy") - r, 2 * r, 2 * r, r, r
    rx, ry = num("rx"), num("ry")
    return num("cx") - rx, num("cy") - ry, 2 * rx, 2 * ry, rx, ry


def _view_box(root):
    raw = root.get("viewBox")
    if raw:
        parts = [float(p) for p in re.split(r"[\s,]+", raw.strip())]
        if len(parts) == 4 and parts[2] > 0 and parts[3] > 0:
            return tuple(parts)
    width = float(re.sub(r"[^\d.]", "", root.get("width", "")) or 0)
    height = float(re.sub(r"[^\d.]", "", root.get("height", "")) or 0)
    if width <= 0 or height <= 0:
        raise ValueError("SVG o'lchami yo'q (viewBox/width/height)")
    return 0.0, 0.0, width, height


def _parse_transform(text: str):
    """SVG `transform` -> affin matritsa (a, b, c, d, e, f)."""
    matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", text):
        values = [float(v) for v in re.split(r"[\s,]+", args.strip()) if v]
        if name == "translate":
            step = (1.0, 0.0, 0.0, 1.0, values[0], values[1] if len(values) > 1 else 0.0)
        elif name == "scale":
            step = (values[0], 0.0, 0.0, values[1] if len(values) > 1 else values[0], 0.0, 0.0)
        elif name == "matrix" and len(values) == 6:
            step = tuple(values)
        else:
            raise ValueError("qo'llanmaydigan transform: {}".format(name))
        matrix = _multiply(matrix, step)
    return matrix


def _multiply(m, n):
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (
        a * a2 + c * b2, b * a2 + d * b2,
        a * c2 + c * d2, b * c2 + d * d2,
        a * e2 + c * f2 + e, b * e2 + d * f2 + f,
    )


def _by_id(root, ident: str):
    for node in root.iter():
        if node.get("id") == ident:
            return node
    return None


def _href(node) -> str:
    return node.get(_XLINK_HREF) or node.get("href") or ""


def _decode_data_uri(uri: str):
    from PIL import Image

    match = re.match(r"data:image/[\w.+-]+;base64,(.*)", uri, re.DOTALL)
    if not match:
        return None
    return Image.open(io.BytesIO(base64.b64decode(re.sub(r"\s+", "", match.group(1)))))


def _render_with_qt(source: Path, side: int):
    try:
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QGuiApplication, QImage, QPainter
        from PyQt6.QtSvg import QSvgRenderer
    except ImportError:
        return None
    from PIL import Image

    _app = QGuiApplication.instance() or QGuiApplication(["make_icon"])  # noqa: F841
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        return None
    view = renderer.viewBoxF()
    height = max(1, round(side * view.height() / view.width())) if view.width() else side
    canvas = QImage(side, height, QImage.Format.Format_RGBA8888)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    raw = bytes(canvas.constBits().asstring(canvas.sizeInBytes()))
    return Image.frombuffer("RGBA", (side, height), raw, "raw", "RGBA", canvas.bytesPerLine(), 1).copy()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args(argv)

    if not args.source.is_file():
        print(f"Logotip topilmadi: {args.source}", file=sys.stderr)
        return 1
    print(f"Ikonka yasaldi: {build_icon(args.source, args.target)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
