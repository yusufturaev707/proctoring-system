from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.bba.api.v1.views import (
    BbaDeviceViewSet,
    BbaJobTypesView,
    BbaJobViewSet,
    BbaOverviewView,
    BbaRegionViewSet,
    BbaRoomViewSet,
    BbaSyncView,
)

router = DefaultRouter()
router.register("bba/devices", BbaDeviceViewSet, basename="bba-device")
router.register("bba/regions", BbaRegionViewSet, basename="bba-region")
router.register("bba/rooms", BbaRoomViewSet, basename="bba-room")
router.register("bba/jobs", BbaJobViewSet, basename="bba-job")

urlpatterns = router.urls + [
    path("bba/overview/", BbaOverviewView.as_view(), name="bba-overview"),
    path("bba/job-types/", BbaJobTypesView.as_view(), name="bba-job-types"),
    path("bba/sync/", BbaSyncView.as_view(), name="bba-sync"),
]
