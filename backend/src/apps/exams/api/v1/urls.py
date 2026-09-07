from rest_framework.routers import DefaultRouter

from apps.exams.api.v1.views import ExamScheduleViewSet, ExamTypeViewSet, ExamViewSet

router = DefaultRouter()
router.register("exam-types", ExamTypeViewSet, basename="exam-type")
router.register("exams", ExamViewSet, basename="exam")
router.register("exam-schedules", ExamScheduleViewSet, basename="exam-schedule")

urlpatterns = router.urls
