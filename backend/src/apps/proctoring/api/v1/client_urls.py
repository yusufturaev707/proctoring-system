"""
PyQt6 desktop client marshrutlari (`/api/v1/client/...`).

Ataylab admin API'dan ajratilgan: boshqa autentifikatsiya, boshqa
throttling, boshqa xavf profili.
"""

from django.urls import path

from apps.proctoring.api.v1.client_views import (
    AccessAttemptView,
    CandidateLookupView,
    EventBatchView,
    ExamAccessView,
    ExitVerifyView,
    FaceVerifyView,
    HandshakeView,
    HeartbeatView,
    IdentityConfirmView,
    PeriodicFaceView,
    PreflightView,
    ScreenshotCommitView,
    ScreenshotPresignView,
    ScreenshotUploadView,
    SessionFinishView,
    SessionStateView,
    TechnicalProblemReportView,
)

urlpatterns = [
    # Kirish oqimi
    # Preflight login'dan OLDIN chaqiriladi va JWT talab qilmaydi —
    # shuning uchun u ro'yxatda ham birinchi turadi.
    path("preflight/", PreflightView.as_view(), name="client-preflight"),
    # Urinish natijasi (ruxsat berildi/berilmadi, login ochildi/ochilmadi)
    # shu yerga keladi va `client_access.log` ga tushadi.
    path("access-attempt/", AccessAttemptView.as_view(), name="client-access-attempt"),
    path("handshake/", HandshakeView.as_view(), name="client-handshake"),
    path("candidate/lookup/", CandidateLookupView.as_view(), name="client-candidate-lookup"),
    path("face/verify/", FaceVerifyView.as_view(), name="client-face-verify"),
    # Operator tasdig'i — `exam/access/` dan OLDIN bo'lishi shart.
    path("identity/confirm/", IdentityConfirmView.as_view(), name="client-identity-confirm"),
    path("exam/access/", ExamAccessView.as_view(), name="client-exam-access"),

    # Imtihon davomida
    path("face/periodic/", PeriodicFaceView.as_view(), name="client-face-periodic"),
    path("events/", EventBatchView.as_view(), name="client-events"),
    path("screenshots/presign/", ScreenshotPresignView.as_view(), name="client-screenshot-presign"),
    path("screenshots/commit/", ScreenshotCommitView.as_view(), name="client-screenshot-commit"),
    # Fayl tizimi yo'li: binary shu yerda keladi (presign/commit o'rniga).
    path("screenshots/upload/", ScreenshotUploadView.as_view(), name="client-screenshot-upload"),
    path("heartbeat/", HeartbeatView.as_view(), name="client-heartbeat"),
    path("session/state/", SessionStateView.as_view(), name="client-session-state"),

    # Yakunlash
    path("technical-problem/", TechnicalProblemReportView.as_view(), name="client-technical-problem"),
    path("session/finish/", SessionFinishView.as_view(), name="client-session-finish"),
    path("exit/verify/", ExitVerifyView.as_view(), name="client-exit-verify"),
]
