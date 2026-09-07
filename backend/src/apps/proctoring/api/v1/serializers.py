from django.urls import reverse
from rest_framework import serializers

from apps.common.storage import presign_get
from apps.proctoring.models import (
    AuditLog,
    ExamSession,
    FaceVerificationLog,
    ProctoringEvent,
    ProctoringScreenshot,
    ScreenshotMeta,
    TechnicalProblem,
)


class SessionHistorySerializer(serializers.ModelSerializer):
    """Talabgor tarixi ro'yxati — bitta JSHSHIR bo'yicha barcha imtihonlar."""

    exam_name = serializers.CharField(source="exam.name", read_only=True)
    zone_name = serializers.CharField(source="zone.name", read_only=True, default="")
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = ExamSession
        fields = (
            "id", "public_id", "exam", "exam_name", "zone_name", "exam_date",
            "attempt_no", "status", "status_display", "risk_score",
            "started_at", "finished_at", "termination_reason",
            "event_count", "face_fail_count",
        )


class CandidateBriefSerializer(serializers.Serializer):
    """
    Sessiyaga muzlatilgan talabgor ma'lumoti.

    Alohida `Candidate` jadvali yo'q — bu maydonlar `ExamSession` ning
    o'zidan o'qiladi. Ochiq JSHSHIR qaytarilmaydi, faqat niqoblangan.
    """

    full_name = serializers.CharField(read_only=True)
    masked_pinfl = serializers.CharField(read_only=True)
    photo_url = serializers.SerializerMethodField()
    identity_verified = serializers.SerializerMethodField()

    def get_photo_url(self, obj) -> str | None:
        return presign_get(obj.photo_key) if obj.photo_key else None

    def get_identity_verified(self, obj) -> bool:
        """Operator hujjat bo'yicha tasdiqlaganmi (FaceID buni bilmaydi)."""
        return obj.identity_verified


class SessionListSerializer(serializers.ModelSerializer):
    """
    Monitoring ro'yxati — ataylab yengil.

    10 000 sessiya ko'rsatilganda har bir qatorga nested obyekt qo'shish
    javob hajmini megabaytlarga chiqaradi. Faqat kerakli maydonlar.
    """

    candidate_name = serializers.CharField(source="full_name", read_only=True)
    masked_pinfl = serializers.CharField(read_only=True)
    exam_name = serializers.CharField(source="exam.name", read_only=True)
    zone_name = serializers.CharField(source="zone.name", read_only=True, default="")
    region_name = serializers.CharField(source="zone.region.name", read_only=True, default="")
    computer_code = serializers.CharField(source="computer.inventory_code", read_only=True, default="")
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    is_online = serializers.SerializerMethodField()
    # Proktor tasdiqlanmagan sessiyani ro'yxatdayoq ajrata olishi kerak.
    identity_verified = serializers.BooleanField(read_only=True)

    class Meta:
        model = ExamSession
        fields = (
            "id", "public_id", "candidate_name", "masked_pinfl", "identity_verified",
            "exam", "exam_name", "zone", "zone_name", "region_name",
            "computer", "computer_code", "attempt_no", "exam_date",
            "status", "status_display", "risk_score",
            "started_at", "finished_at", "last_heartbeat_at", "is_online",
            "event_count", "screenshot_count", "face_fail_count",
            "ip_address", "created_at",
        )

    def get_is_online(self, obj) -> bool:
        from django.conf import settings
        from django.utils import timezone

        if not obj.last_heartbeat_at or obj.status in ExamSession.TERMINAL_STATUSES:
            return False
        timeout = settings.PROCTORING["HEARTBEAT_TIMEOUT"]
        return (timezone.now() - obj.last_heartbeat_at).total_seconds() < timeout


class SessionDetailSerializer(SessionListSerializer):
    # Manba — sessiyaning o'zi: talabgor maydonlari unga muzlatilgan.
    candidate_detail = CandidateBriefSerializer(source="*", read_only=True)
    terminated_by_name = serializers.CharField(
        source="terminated_by.username", read_only=True, default=""
    )
    duration_seconds = serializers.IntegerField(read_only=True)
    live_state = serializers.SerializerMethodField()
    identity = serializers.DictField(read_only=True)

    class Meta(SessionListSerializer.Meta):
        fields = SessionListSerializer.Meta.fields + (
            "candidate_detail", "mac_address", "termination_reason",
            "terminated_by", "terminated_by_name", "face_check_count",
            "duration_seconds", "live_state", "identity", "meta", "updated_at",
        )

    def get_live_state(self, obj) -> dict:
        """Redis'dagi issiq holat — DB'dagidan yangiroq."""
        from apps.proctoring.services import state as session_state

        return session_state.get_state(obj.pk)


class ProctoringEventSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source="get_type_display", read_only=True)
    severity_display = serializers.CharField(source="get_severity_display", read_only=True)
    screenshot_url = serializers.SerializerMethodField()

    class Meta:
        model = ProctoringEvent
        fields = (
            "id", "session", "type", "type_display", "severity", "severity_display",
            "occurred_at", "received_at", "payload", "screenshot_url",
        )

    def get_screenshot_url(self, obj) -> str | None:
        return presign_get(obj.screenshot_key) if obj.screenshot_key else None


class FaceVerificationLogSerializer(serializers.ModelSerializer):
    stage_display = serializers.CharField(source="get_stage_display", read_only=True)
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = FaceVerificationLog
        fields = (
            "id", "session", "stage", "stage_display", "source",
            "score", "threshold", "passed", "faces_detected",
            "image_url", "occurred_at",
        )

    def get_image_url(self, obj) -> str | None:
        return presign_get(obj.image_key) if obj.image_key else None


class ScreenshotMetaSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = ScreenshotMeta
        fields = (
            "id", "session", "kind", "url", "sha256", "size_bytes",
            "width", "height", "captured_at",
        )

    def get_url(self, obj) -> str | None:
        return presign_get(obj.object_key)


class ProctoringScreenshotSerializer(serializers.ModelSerializer):
    """
    Fayl tizimida saqlangan skrinshot.

    `file_path` ATAYLAB berilmaydi — u serverning ichki katalog
    strukturasi. Uning o'rniga `url` beriladi: ruxsat tekshiriladigan
    endpoint, u `X-Accel-Redirect` bilan javob beradi.
    """

    url = serializers.SerializerMethodField()

    class Meta:
        model = ProctoringScreenshot
        fields = (
            "id", "session", "url", "content_hash", "file_size",
            "mime_type", "seq", "captured_at", "received_at",
        )

    def get_url(self, obj) -> str:
        path = reverse("screenshot-file", kwargs={"pk": obj.pk})
        request = self.context.get("request")
        return request.build_absolute_uri(path) if request else path


class TechnicalProblemSerializer(serializers.ModelSerializer):
    session_public_id = serializers.UUIDField(source="session.public_id", read_only=True)
    candidate_name = serializers.SerializerMethodField()
    zone_name = serializers.CharField(source="session.zone.name", read_only=True, default="")
    resolved_by_name = serializers.CharField(
        source="resolved_by.username", read_only=True, default=""
    )
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = TechnicalProblem
        fields = (
            "id", "session", "session_public_id", "candidate_name", "zone_name",
            "kind", "kind_display", "description", "started_at", "finished_at",
            "overtime", "is_resolved", "resolved_by", "resolved_by_name",
            "resolution_note", "created_at",
        )
        read_only_fields = ("id", "created_at", "resolved_by")

    def get_candidate_name(self, obj) -> str:
        return obj.session.full_name


class AuditLogSerializer(serializers.ModelSerializer):
    action_display = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = AuditLog
        fields = (
            "id", "actor", "actor_username", "action", "action_display",
            "object_type", "object_id", "ip_address", "user_agent",
            "request_id", "meta", "created_at",
        )


# --------------------------------------------------------------------------
# Proktor amallari
# --------------------------------------------------------------------------
class SessionWarnSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=500)
    severity = serializers.IntegerField(min_value=0, max_value=4, default=2)


class SessionTerminateSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


class TechnicalProblemResolveSerializer(serializers.Serializer):
    overtime_minutes = serializers.IntegerField(min_value=0, max_value=240, default=0)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True)
    resume_session = serializers.BooleanField(default=True)
