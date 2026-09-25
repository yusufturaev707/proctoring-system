"""
Tashqi tizimlar uchun `X-API-Key` autentifikatsiyasi.

HOZIRCHA BITTA KALIT — FaceID (`settings.FACEID_INTEGRATION`). Kalit
bazada emas, `.env` da: yangi jadval va uni boshqaradigan panel sahifasi
bitta tizim uchun ortiqcha. Ikkinchi tashqi tizim paydo bo'lsa kalitlar
jadvalga ko'chiriladi.

Kalit xodim JWT'si O'RNINI BOSADI, ruxsatlar tizimini emas: so'rov
`USER` nomidagi servis xodimi nomidan bajariladi va u oddiy xodim kabi
`HasRolePermission` dan o'tadi. Shu tufayli kalitning qo'lidan nima
kelishini paneldagi rol belgilaydi, kod emas.
"""

from __future__ import annotations

import hmac

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed


class FaceIdApiKeyAuthentication(BaseAuthentication):
    """`X-API-Key` → FaceID servis xodimi."""

    def authenticate(self, request):
        supplied = request.META.get("HTTP_X_API_KEY")
        if not supplied:
            # Sarlavha yo'q — 401 (`authenticate_header` tufayli), 403 emas.
            return None

        conf = settings.FACEID_INTEGRATION
        expected = conf.get("API_KEY") or ""
        # `compare_digest` — vaqt bo'yicha sizib chiqmaydigan solishtirish.
        # Kalit sozlanmagan bo'lsa HAR QANDAY qiymat rad etiladi: bo'sh
        # kalit "tekshiruv o'chiq" degani bo'lib qolmasligi kerak.
        if not expected or not hmac.compare_digest(supplied.encode(), expected.encode()):
            raise AuthenticationFailed("API kalit noto'g'ri", code="invalid_api_key")

        user = (
            get_user_model()
            .objects.select_related("role")
            .filter(username=conf.get("USER") or "", is_active=True)
            .first()
        )
        if user is None:
            raise AuthenticationFailed(
                "Integratsiya xodimi topilmadi yoki faol emas", code="integration_user_missing"
            )
        return user, "faceid"

    def authenticate_header(self, request):
        return "X-API-Key"
