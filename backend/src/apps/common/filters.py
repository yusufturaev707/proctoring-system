"""
Panel qidiruvi (`?search=`) — DRF `SearchFilter` + MAC manzil ajratgichi.

MAC bazada kanonik shaklda (`EC:D6:8A:E0:B8:93`, `normalize_mac`), lekin
Windows (`getmac`, `ipconfig /all`) va yorliqlar uni `EC-D6-8A-E0-B8-93`
deb beradi; eski yozuvlarda esa `2c-f0-...` shakli ham qolgan. Oddiy
`icontains` da ko'chirib qo'yilgan manzil hech narsa topmasdi. Shuning uchun
MAC maydonlari uchun so'z IKKALA ajratgich bilan solishtiriladi; qolgan
maydonlar so'zni o'zgarishsiz oladi ("INV-001" "INV:001" ga aylanmaydi).

MAC maydoni nomidan taniladi (`_is_mac_field`) — har viewset'da alohida
ro'yxat yuritilmaydi: `mac_address`, `reported_mac`, `computer__mac_address`.
"""

import operator
import re
from functools import reduce

from django.db import models
from django.db.models.constants import LOOKUP_SEP
from rest_framework.filters import SearchFilter as BaseSearchFilter

#: Faqat o'n oltilik raqamlar va MAC ajratgichlari ("EC-D6-8A", "e0:b8:9").
_MAC_FRAGMENT_RE = re.compile(r"^[0-9A-Fa-f]*[:-][0-9A-Fa-f:-]*$")
#: Ajratgichsiz to'liq manzil ("ECD68AE0B893").
_MAC_BARE_RE = re.compile(r"^[0-9A-Fa-f]{12}$")


def _is_mac_field(search_field: str) -> bool:
    name = search_field.lstrip("^=@$").split(LOOKUP_SEP)[-1]
    return name == "mac_address" or name.endswith("_mac")


def mac_term_variants(term: str) -> list[str]:
    """
    MAC maydoni uchun so'zning shakllari (`icontains` bilan solishtiriladi).

    Ajratgichsiz qism ("ECD68A") faqat TO'LIQ manzil bo'lsa ochiladi: qisqa
    qismda juftlar chegarasi noma'lum ("CD68" — `C:D6:8` mi, `CD:68` mi).
    """
    if _MAC_BARE_RE.match(term):
        pairs = [term[i:i + 2] for i in range(0, 12, 2)]
        return [term, ":".join(pairs), "-".join(pairs)]
    if _MAC_FRAGMENT_RE.match(term):
        return list(dict.fromkeys([term, term.replace("-", ":"), term.replace(":", "-")]))
    return [term]


class SearchFilter(BaseSearchFilter):
    def filter_queryset(self, request, queryset, view):
        search_fields = self.get_search_fields(view, request)
        search_terms = self.get_search_terms(request)

        if not search_fields or not search_terms:
            return queryset

        lookups = [
            (self.construct_search(str(field), queryset), _is_mac_field(str(field)))
            for field in search_fields
        ]

        def term_condition(term):
            mac_variants = mac_term_variants(term)
            return reduce(operator.or_, (
                models.Q(**{lookup: variant})
                for lookup, is_mac in lookups
                for variant in (mac_variants if is_mac else [term])
            ))

        # Qolgani DRF bilan aynan bir xil: so'zlar VA, maydonlar YOKI.
        base = queryset
        queryset = queryset.filter(reduce(operator.and_, map(term_condition, search_terms)))
        if self.must_call_distinct(queryset, search_fields):
            queryset = queryset.filter(pk=models.OuterRef("pk"))
            queryset = base.filter(models.Exists(queryset))
        return queryset
