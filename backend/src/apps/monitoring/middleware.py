import time

from django.conf import settings
from django.core.exceptions import MiddlewareNotUsed

from apps.monitoring.request_metrics import aggregator, route_label


class RequestMetricsMiddleware:
    """
    Har HTTP so'rovning vaqti va statusi (`request_metrics.py`).

    Javob tanasi oqim bo'lsa (kamera MJPEG) — vaqt view qaytgunicha,
    ya'ni birinchi baytgacha: oqim davomiyligi "sekin so'rov" emas.
    Istisno bo'lsa ham yoziladi (500): aynan shu holat ko'rinishi kerak.
    """

    def __init__(self, get_response):
        if not settings.SYSTEM_MONITOR.get("ENABLED", True):
            raise MiddlewareNotUsed
        self.get_response = get_response

    def __call__(self, request):
        started = time.perf_counter()
        status = 500
        try:
            response = self.get_response(request)
            status = response.status_code
            return response
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            try:
                aggregator.record(route_label(request, status), status, duration_ms)
            except Exception:  # noqa: BLE001 — statistika so'rovni yiqitmaydi
                pass
