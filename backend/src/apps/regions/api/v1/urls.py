from rest_framework.routers import DefaultRouter

from apps.regions.api.v1.views import RegionViewSet, ZoneViewSet

router = DefaultRouter()
router.register("regions", RegionViewSet, basename="region")
router.register("zones", ZoneViewSet, basename="zone")

urlpatterns = router.urls
