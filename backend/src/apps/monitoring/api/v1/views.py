from django.core.cache import cache
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import HasPanelAccess, HasRolePermission, RepublicLevelOnly
from apps.monitoring import request_metrics, services


class _SystemView(APIView):
    """
    Server holati — faqat respublika darajasi (`RepublicLevelOnly`) va
    `system.view`. Javoblar faqat o'qish; hech biri serverni o'zgartirmaydi.
    """

    permission_classes = [IsAuthenticated, HasPanelAccess, HasRolePermission, RepublicLevelOnly]
    required_permission = "system.view"


class SystemStatusView(_SystemView):
    """Jonli holat (panel har 5 s da so'raydi, natija 3 s keshlanadi)."""

    def get(self, request):
        return Response(services.system_status())


class SystemHistoryView(_SystemView):
    """Grafiklar: `?range=1h|6h|24h`."""

    def get(self, request):
        range_name = request.query_params.get("range") or "1h"
        if range_name not in services.RANGES:
            range_name = "1h"
        key = f"sysmon:history:{range_name}"
        data = cache.get(key)
        if data is None:
            data = services.history(range_name)
            # Tarix 30 s da bir nuqta oladi — tez-tez qayta o'qish behuda.
            cache.set(key, data, 15)
        return Response(data)


class SystemRequestsView(_SystemView):
    """Marshrutlar jadvali: `?minutes=5|15|60`."""

    def get(self, request):
        try:
            minutes = int(request.query_params.get("minutes") or 15)
        except ValueError:
            minutes = 15
        minutes = max(1, min(minutes, 120))
        key = f"sysmon:routes:{minutes}"
        data = cache.get(key)
        if data is None:
            data = request_metrics.routes(minutes)
            cache.set(key, data, 10)
        return Response(data)
