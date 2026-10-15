from django.urls import path

from .views import SystemHistoryView, SystemRequestsView, SystemStatusView

urlpatterns = [
    path("system/status/", SystemStatusView.as_view(), name="system-status"),
    path("system/history/", SystemHistoryView.as_view(), name="system-history"),
    path("system/requests/", SystemRequestsView.as_view(), name="system-requests"),
]
