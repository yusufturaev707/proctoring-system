"""
PyQt6 desktop client marshrutlari (`/api/v1/client/...`).

Ataylab admin API'dan ajratilgan: boshqa autentifikatsiya, boshqa
throttling, boshqa xavf profili.
"""

from django.urls import path

from apps.proctoring.api.v1.client_views import (
    AccessAttemptView,
    CameraCheckView,
    CameraConfigView,
    CameraStreamView,
    CandidateLookupView,
    EventBatchView,
    EvidenceUploadView,
    LocalRecordingView,
    ExamAccessView,
    ExamConfigView,
    ExitVerifyView,
    FaceAttemptView,
    FaceVerifyView,
    HandshakeView,
    HeartbeatView,
    IdentityConfirmView,
    PeriodicFaceView,
    PreflightView,
    PresenceView,
    ProctoringStartView,
    ProctoringStopView,
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
    # "Client ishlab turibdi" signali - SESSIYASIZ ham yuboriladi
    # (operator kirgan, talabgor kutilmoqda).
    path("presence/", PresenceView.as_view(), name="client-presence"),
    # Kamera tekshiruvi - login'dan KEYIN, imtihon tanlashdan OLDIN.
    path("camera/config/", CameraConfigView.as_view(), name="client-camera-config"),
    path("camera/stream/", CameraStreamView.as_view(), name="client-camera-stream"),
    path("camera/check/", CameraCheckView.as_view(), name="client-camera-check"),
    # Imtihon tanlangach - o'sha imtihonning to'liq profili.
    path("exam/config/", ExamConfigView.as_view(), name="client-exam-config"),
    path("candidate/lookup/", CandidateLookupView.as_view(), name="client-candidate-lookup"),
    path("face/verify/", FaceVerifyView.as_view(), name="client-face-verify"),
    # Mos kelmagan urinish: sessiya yaratmaydi, challenge'ni sarflamaydi.
    path("face/attempt/", FaceAttemptView.as_view(), name="client-face-attempt"),
    # Operator tasdig'i — `exam/access/` dan OLDIN bo'lishi shart.
    path("identity/confirm/", IdentityConfirmView.as_view(), name="client-identity-confirm"),
    path("exam/access/", ExamAccessView.as_view(), name="client-exam-access"),

    # Imtihon davomida
    # Kuzatuvni ishga tushirish - "START EXAM" nuqtasi, WebView
    # ochilishidan OLDIN.
    path("proctoring/start/", ProctoringStartView.as_view(), name="client-proctoring-start"),
    path("proctoring/stop/", ProctoringStopView.as_view(), name="client-proctoring-stop"),
    path("face/periodic/", PeriodicFaceView.as_view(), name="client-face-periodic"),
    path("events/", EventBatchView.as_view(), name="client-events"),
    # Dalil: skrinshotdan ALOHIDA endpoint (hodisa konteksti bilan).
    path("evidence/upload/", EvidenceUploadView.as_view(), name="client-evidence-upload"),
    # Mashinada QOLGAN yozuv (ekran videosi, kamera klipi) - fayl
    # emas, manzil. Sabab `LocalRecordingView` docstring'ida.
    path("recordings/", LocalRecordingView.as_view(), name="client-recordings"),
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
