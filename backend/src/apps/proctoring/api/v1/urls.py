from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.proctoring.api.v1.views import (
    AuditLogViewSet,
    DashboardDevicesView,
    DashboardSummaryView,
    DashboardZonesView,
    ExamSessionViewSet,
    ScreenshotFileView,
    TechnicalProblemViewSet,
)

router = DefaultRouter()
router.register("sessions", ExamSessionViewSet, basename="session")
router.register("technical-problems", TechnicalProblemViewSet, basename="technical-problem")
router.register("audit-logs", AuditLogViewSet, basename="audit-log")

urlpatterns = router.urls + [
    path("dashboard/summary/", DashboardSummaryView.as_view(), name="dashboard-summary"),
    path("dashboard/zones/", DashboardZonesView.as_view(), name="dashboard-zones"),
    path("dashboard/devices/", DashboardDevicesView.as_view(), name="dashboard-devices"),

    # Skrinshot fayli: ruxsatni Django tekshiradi, baytlarni nginx beradi.
    path(
        "screenshots/<int:pk>/file/",
        ScreenshotFileView.as_view(),
        name="screenshot-file",
    ),
]
