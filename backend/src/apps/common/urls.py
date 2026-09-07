"""API v1 yig'uvchisi."""

from django.urls import include, path

urlpatterns = [
    path("auth/", include("apps.users.api.v1.auth_urls")),
    path("", include("apps.users.api.v1.urls")),
    path("", include("apps.regions.api.v1.urls")),
    path("", include("apps.devices.api.v1.urls")),
    path("", include("apps.controls.api.v1.urls")),
    path("", include("apps.exams.api.v1.urls")),
    path("", include("apps.proctoring.api.v1.urls")),
    # PyQt6 desktop client uchun alohida yuza
    path("client/", include("apps.proctoring.api.v1.client_urls")),
]
