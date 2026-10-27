"""
Panel matn muharriri (TipTap) yozgan HTML'ni OQ RO'YXAT bo'yicha tozalash.

NIMA UCHUN SERVERDA. Oferta matni ikki joyda chiziladi: panelda
(`dangerouslySetInnerHTML`) va desktop client'da (`QTextBrowser`). Muharrir
toza HTML beradi, lekin API'ga istalgan so'rov yuborilishi mumkin —
`<script>`, `onerror=` yoki `javascript:` havolasi bazaga tushsa, u oferta
ko'rilgan HAR BIR panel sahifasida ishlardi (saqlangan XSS). Tozalash
yozishda BIR MARTA bo'ladi va bazada faqat toza HTML yotadi: o'quvchilar
(panel, client) qayta tozalamaydi.

YANGI BOG'LIQLIK YO'Q (`bleach` eskirgan, `nh3` — Rust kengaytmasi):
ruxsat etilgan to'plam kichik va stdlib `html.parser` yetadi.

QOIDALAR:

  * ruxsat etilmagan teg tashlanadi, MATNI qoladi (`<div>` -> matn);
  * xavfli teg MAZMUNI BILAN tashlanadi (`<script>`, `<style>`, ...);
  * atributlar tashlanadi; yagona istisno — blokdagi `text-align`, u
    ikki shaklda yoziladi: `style` (brauzer, TipTap qayta o'qiydi) va
    `align` (Qt rich text CSS'dan ko'ra atributni ishonchli o'qiydi);
  * HAVOLA YO'Q (`<a>` -> matn): client kiosk rejimida, havola bosilsa
    tashqi brauzer ochilishi kerak emas, oferta uchun esa matnning o'zi
    yetadi;
  * natija har doim to'g'ri yopilgan (teglar stek bo'yicha yopiladi).
"""

from __future__ import annotations

import re
from html import escape
from html.parser import HTMLParser

#: Ruxsat etilgan teglar. `b`/`i` ham qabul qilinadi (nusxalangan matn).
ALLOWED_TAGS = frozenset({
    "p", "br", "hr",
    "h1", "h2", "h3", "h4",
    "strong", "b", "em", "i", "u", "s",
    "ul", "ol", "li",
    "blockquote",
})

#: Yopilmaydigan teglar.
VOID_TAGS = frozenset({"br", "hr"})

#: Tekislash qo'llanadigan bloklar (TipTap `TextAlign` — paragraf va sarlavha).
ALIGNABLE_TAGS = frozenset({"p", "h1", "h2", "h3", "h4"})

ALIGNMENTS = frozenset({"left", "center", "right", "justify"})

#: Mazmuni bilan birga tashlanadigan teglar — ularning "matni" kod yoki
#: ko'rinmaydigan ma'lumot, ofertaga tushmasligi kerak.
_DROP_WITH_CONTENT = frozenset({
    "script", "style", "iframe", "object", "embed", "template", "noscript",
    "svg", "math", "head", "title", "textarea", "select", "button", "canvas",
})

_TEXT_ALIGN_RE = re.compile(r"(?:^|;)\s*text-align\s*:\s*([a-z]+)\s*(?:;|$)", re.IGNORECASE)


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        # `convert_charrefs` — `&lt;` kabi belgilar matnga ochiladi va
        # chiqishda qayta qochiriladi: ikki marta qochirilgan `&amp;lt;`
        # ham, ochilib qolgan `<` ham bo'lmaydi.
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[str] = []
        #: Mazmuni tashlanayotgan teg ichidagi chuqurlik.
        self.skip_depth = 0

    # --- teglar ------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _DROP_WITH_CONTENT:
            if tag not in VOID_TAGS:
                self.skip_depth += 1
            return
        if self.skip_depth or tag not in ALLOWED_TAGS:
            return
        self.out.append(self._open_tag(tag, attrs))
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        # `<br/>` — o'z-o'zidan yopilgan; bo'sh `<p/>` ochilib qolmasin.
        tag = tag.lower()
        if self.skip_depth or tag not in ALLOWED_TAGS or tag in _DROP_WITH_CONTENT:
            return
        if tag in VOID_TAGS:
            self.out.append(self._open_tag(tag, attrs))

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _DROP_WITH_CONTENT:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth or tag not in ALLOWED_TAGS or tag in VOID_TAGS:
            return
        if tag not in self.stack:
            # Ochilmagan tegning yopilishi — e'tiborsiz.
            return
        while self.stack:
            current = self.stack.pop()
            self.out.append(f"</{current}>")
            if current == tag:
                break

    def handle_data(self, data):
        if not self.skip_depth:
            self.out.append(escape(data, quote=False))

    # Izohlar, `<!DOCTYPE>`, `<?pi?>` — hammasi tashlanadi.
    def handle_comment(self, data):
        return

    def handle_decl(self, decl):
        return

    def handle_pi(self, data):
        return

    def unknown_decl(self, data):
        return

    # --- yordamchilar --------------------------------------------------
    @staticmethod
    def _open_tag(tag: str, attrs) -> str:
        if tag in ALIGNABLE_TAGS:
            align = _alignment(attrs)
            if align and align != "left":
                return f'<{tag} style="text-align: {align}" align="{align}">'
        return f"<{tag}>"

    def result(self) -> str:
        while self.stack:
            self.out.append(f"</{self.stack.pop()}>")
        return "".join(self.out)


def _alignment(attrs) -> str:
    """`style="text-align: center"` yoki `align="center"` -> `center`."""
    for name, value in attrs:
        name = (name or "").lower()
        value = (value or "").strip().lower()
        if name == "align" and value in ALIGNMENTS:
            return value
        if name == "style":
            match = _TEXT_ALIGN_RE.search(value)
            if match and match.group(1).lower() in ALIGNMENTS:
                return match.group(1).lower()
    return ""


def sanitize_html(raw: str) -> str:
    """Toza HTML. Bo'sh paragraflar saqlanadi — muallif qoldirgan bo'sh qator."""
    parser = _Sanitizer()
    parser.feed(raw or "")
    parser.close()
    return parser.result().strip()


def html_text(html: str) -> str:
    """Teglarsiz matn (bo'shliqlar siqilgan) — "matn bormi?" va uzunlik uchun."""

    class _Text(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []

        def handle_data(self, data):
            self.parts.append(data)

    parser = _Text()
    parser.feed(html or "")
    parser.close()
    return " ".join(" ".join(parser.parts).split())
