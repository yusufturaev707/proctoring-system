from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.devices.api.v1.views import (
    CameraViewSet,
    ComputerViewSet,
    DeviceRegisterView,
    DeviceTokenViewSet,
)

router = DefaultRouter()
router.register("computers", ComputerViewSet, basename="computer")
router.register("cameras", CameraViewSet, basename="camera")
router.register("device-tokens", DeviceTokenViewSet, basename="device-token")

urlpatterns = router.urls + [
    path("devices/register/", DeviceRegisterView.as_view(), name="device-register"),
]
