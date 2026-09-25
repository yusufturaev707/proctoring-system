"""FaceID integratsiyasi (`/api/v1/integrations/faceid/...`, `X-API-Key`)."""

from django.urls import path

from apps.integrations.api.v1.faceid_views import (
    FaceIdBookView,
    FaceIdComputersView,
    FaceIdSchedulesView,
)

urlpatterns = [
    path("faceid/schedules/", FaceIdSchedulesView.as_view(), name="faceid-schedules"),
    path(
        "faceid/schedules/<int:schedule_id>/computers/",
        FaceIdComputersView.as_view(),
        name="faceid-computers",
    ),
    path("faceid/book/", FaceIdBookView.as_view(), name="faceid-book"),
]
