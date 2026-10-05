from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

urlpatterns = [
    re_path(r'^static/(?P<path>.*)$', serve, {'document_root': settings.STATIC_ROOT}),
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]

from apps.common.views import HealthView, ReadinessView

admin_url = getattr(settings, "ADMIN_URL", "admin/")

urlpatterns += [
    path(admin_url, admin.site.urls),

    # Infratuzilma probe'lari (load balancer / k8s)
    path("healthz/", HealthView.as_view(), name="health"),
    path("readyz/", ReadinessView.as_view(), name="readiness"),

    # API v1
    path("api/v1/", include("apps.common.urls")),
]

if settings.DEBUG or getattr(settings, "ENABLE_API_DOCS", False):
    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path(
            "api/docs/",
            SpectacularSwaggerView.as_view(url_name="schema"),
            name="swagger-ui",
        ),
        path(
            "api/redoc/",
            SpectacularRedocView.as_view(url_name="schema"),
            name="redoc",
        ),
    ]
