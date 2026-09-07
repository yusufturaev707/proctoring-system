import logging

from django.db import connections
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.redis_client import get_redis

logger = logging.getLogger(__name__)


class HealthView(APIView):
    """
    Liveness probe — process tirikmi.

    Ataylab hech qanday tashqi bog'liqlikni tekshirmaydi: DB tushganda
    orkestrator sog'lom process'larni qayta ishga tushirib, holatni
    yomonlashtirmasligi kerak.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []

    def get(self, request):
        return Response({"status": "ok"})


class ReadinessView(APIView):
    """
    Readiness probe — so'rovlarni qabul qila oladimi.

    DB va Redis tekshiriladi; biri ishlamasa 503 qaytadi va load balancer
    bu instansiyani rotatsiyadan chiqaradi.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []

    def get(self, request):
        checks = {"database": self._check_database(), "redis": self._check_redis()}
        healthy = all(checks.values())
        return Response(
            {"status": "ready" if healthy else "degraded", "checks": checks},
            status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @staticmethod
    def _check_database() -> bool:
        try:
            with connections["default"].cursor() as cursor:
                cursor.execute("SELECT 1")
            return True
        except Exception as exc:
            logger.warning("Readiness: DB tekshiruvi muvaffaqiyatsiz: %s", exc)
            return False

    @staticmethod
    def _check_redis() -> bool:
        try:
            return bool(get_redis().ping())
        except Exception as exc:
            logger.warning("Readiness: Redis tekshiruvi muvaffaqiyatsiz: %s", exc)
            return False
