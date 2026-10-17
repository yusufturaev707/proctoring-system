"""
Test platformasining RESURS domenlari (`Exam.resource_domains`).

Savol rasmlari, shriftlar, uslublar ko'pincha platformaning o'zidan
emas, boshqa serverdan (CDN, `files.…`) keladi. WebView allowlist'i
esa faqat `test_link` va `site_url` hostlaridan iborat
(`session._link_domains`), ya'ni bunday rasm bloklanardi: talabgor
savolni to'liq ko'rmasdi, har bloklangan so'rov esa `navigation_blocked`
bo'lib xavf ballini oshirardi.

Bu ro'yxat ASOSIY allowlist'ni ALMASHTIRMAYDI va unga QO'SHILMAYDI:
client uni faqat sub-resurslarga (rasm, shrift, CSS, media) qo'llaydi
(`client/ui/pages/exam_webview_page.py:DomainAllowlistInterceptor`).
Shu domenga sahifa navigatsiyasi, iframe, skript va XHR baribir
bloklanadi - aks holda talabgor CDN domeniga to'g'ridan-to'g'ri o'tib
ketishi yoki begona kod yuklanishi mumkin edi.

Ilgari olib tashlangan `allowed_domains` dan farqi: u ASOSIY domenni
belgilardi va yangilanmasa butun imtihon oq ekranda qolardi. Bu yerda
bo'sh ro'yxat - hozirgi xatti-harakat; unutilgan yozuv faqat rasmni
yashiradi.

Qoida BITTA joyda (panel serializer'i, Django admin `Exam.clean`,
client'ga berish `Exam.get_resource_domains`). Model import qilinmaydi.
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

#: Ro'yxat chegarasi. Platformaga bir-ikki CDN yetadi; uzun ro'yxat
#: "hamma narsani ochib qo'yish" belgisi.
MAX_RESOURCE_DOMAINS = 20

#: DNS yorlig'i: harf/raqam/defis, chetlarida defis yo'q, ≤ 63 belgi.
_LABEL_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


def clean_resource_domain(value) -> str:
    """
    Bitta yozuvni kanonik HOST ga keltiradi; yaroqsizida `ValueError`.

    Qabul qilinadi: `cdn.test.uz`, `https://cdn.test.uz/img/a.png`
    (host olinadi), `*.cdn.test.uz` (`cdn.test.uz` ga tushadi - client
    allowlist'i domenni subdomenlari bilan birga solishtiradi,
    `host.endswith("." + domain)`), IPv4/IPv6 manzil (yopiq tarmoqdagi
    rasm serveri).

    Rad etiladi:

    * bitta yorliqli nom (`uz`, `localhost`) - butun zonani ochardi;
    * loopback/maxsus manzil - rasm so'rovi orqali mashinadagi lokal
      xizmatlarga GET yuborish mumkin bo'lardi (lokal xizmatning o'z
      porti alohida ochiq, `local_port`);
    * ASCII bo'lmagan nom - Qt hostni boshqa shaklda berishi mumkin va
      yozuv jimgina hech narsaga mos kelmasdi; `xn--` shaklida yoziladi.
    """
    raw = str(value or "").strip().lower()
    if not raw:
        raise ValueError("Bo'sh qiymat")

    if "://" in raw:
        try:
            raw = urlsplit(raw).hostname or ""
        except ValueError:
            raw = ""
        if not raw:
            raise ValueError("Manzildan domen ajratib bo'lmadi")
    elif "/" in raw:
        raw = raw.split("/", 1)[0]

    # Port olib tashlanadi (`cdn.uz:8443`, `10.0.0.5:80`, `[fd00::1]:443`)
    # - interceptor faqat hostni solishtiradi. Qavssiz IPv6 (`fd00::1`)
    # da ikki nuqta bir nechta, u tegilmaydi.
    if raw.startswith("["):
        raw = raw[1:].split("]", 1)[0]
    elif raw.count(":") == 1:
        raw = raw.split(":", 1)[0]

    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        address = None
    if address is not None:
        if (address.is_loopback or address.is_unspecified
                or address.is_multicast or address.is_link_local):
            raise ValueError("Bu manzilga ruxsat berib bo'lmaydi")
        return str(address)

    if raw.startswith("*."):
        raw = raw[2:]
    raw = raw.rstrip(".")

    if not raw.isascii():
        raise ValueError("Domenni lotin harflarida (xn-- ko'rinishida) yozing")
    labels = raw.split(".")
    if len(labels) < 2:
        raise ValueError("Juda keng: kamida ikki qismli domen kiriting (masalan cdn.test.uz)")
    if any(not _LABEL_RE.match(label) for label in labels) or len(raw) > 253:
        raise ValueError("Domen noto'g'ri")
    if labels[-1].isdigit():
        # `10.0.0` kabi to'liq bo'lmagan manzil domen emas.
        raise ValueError("Domen noto'g'ri")
    return raw


def clean_resource_domains(values) -> list[str]:
    """
    Ro'yxatni tekshiradi: kanonik, takrorsiz, tartib saqlangan.

    Xato `ValueError` - matnida qaysi yozuv ekanligi bor (panel uni
    maydon ostida ko'rsatadi).
    """
    if values in (None, ""):
        return []
    if not isinstance(values, (list, tuple)):
        raise ValueError("Ro'yxat bo'lishi kerak")
    cleaned: list[str] = []
    for value in values:
        try:
            domain = clean_resource_domain(value)
        except ValueError as exc:
            raise ValueError("«{}»: {}".format(str(value).strip(), exc)) from exc
        if domain not in cleaned:
            cleaned.append(domain)
    if len(cleaned) > MAX_RESOURCE_DOMAINS:
        raise ValueError("Ko'pi bilan {} ta domen".format(MAX_RESOURCE_DOMAINS))
    return cleaned


def safe_resource_domains(values) -> list[str]:
    """
    Client'ga berish uchun: yaroqsiz yozuv TASHLANADI, istisno yo'q.

    Bazadagi qiymat qoidadan oldin (yoki to'g'ridan-to'g'ri SQL bilan)
    yozilgan bo'lishi mumkin; bitta buzilgan yozuv imtihonni ochishni
    to'xtatmasligi, keng yozuv esa client'ga o'tib ketmasligi kerak.
    """
    if not isinstance(values, (list, tuple)):
        return []
    result: list[str] = []
    for value in values:
        try:
            domain = clean_resource_domain(value)
        except ValueError:
            continue
        if domain not in result:
            result.append(domain)
    return result[:MAX_RESOURCE_DOMAINS]
