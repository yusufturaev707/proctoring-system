from rest_framework.routers import DefaultRouter

from apps.controls.api.v1.views import (
    AllowedPublicIpViewSet,
    ClientExitPasswordViewSet,
    CocoObjectGroupViewSet,
    CocoObjectViewSet,
    EventRiskWeightViewSet,
    HotKeyboardKeyViewSet,
    ModelVersionViewSet,
    ProctoringPolicyViewSet,
    RdpObjectViewSet,
    SettingViewSet,
)

router = DefaultRouter()
router.register("settings", SettingViewSet, basename="setting")
router.register("allowed-ips", AllowedPublicIpViewSet, basename="allowed-ip")
router.register("exit-passwords", ClientExitPasswordViewSet, basename="exit-password")
router.register("model-versions", ModelVersionViewSet, basename="model-version")
router.register("coco-groups", CocoObjectGroupViewSet, basename="coco-group")
router.register("coco-objects", CocoObjectViewSet, basename="coco-object")
router.register("rdp-objects", RdpObjectViewSet, basename="rdp-object")
router.register("hotkeys", HotKeyboardKeyViewSet, basename="hotkey")
router.register("proctoring-policies", ProctoringPolicyViewSet, basename="proctoring-policy")
router.register("risk-weights", EventRiskWeightViewSet, basename="risk-weight")

urlpatterns = router.urls
