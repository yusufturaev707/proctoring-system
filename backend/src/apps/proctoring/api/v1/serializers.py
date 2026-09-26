from django.urls import reverse
from rest_framework import serializers

from apps.common.storage import presign_get
from apps.proctoring.models import (
    EvidenceArtifact,
    AuditLog,
    ExamSession,
    FaceVerificationLog,
    LocalRecording,
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
    o'zidan o'qiladi.

    JSHSHIR TO'LIQ QAYTADI. Ilgari faqat niqoblangani berilardi
    ("3000******0001") va bu panelda ishni to'sardi: proktor
    talabgorni platformada yoki hujjatda aynan shu raqam bo'yicha
    tekshiradi, niqoblangan raqamdan esa uni ko'chirib ham
    bo'lmaydi. Niqob himoya ham emas edi — qidiruv allaqachon to'liq
    raqam bo'yicha ishlaydi va panelga faqat ruxsati bor xodim
    kiradi (`sessions.view` + viloyat doirasi). Niqoblangan qiymat
    CLIENTDA qoladi: u yerda ekran oldida talabgor turadi.
    """

    full_name = serializers.CharField(read_only=True)
    pinfl = serializers.CharField(read_only=True)
    #: Eski panel nusxalari uchun saqlanadi (ular shu kalitni
    #: o'qiydi). Yangi ekranlar `pinfl` ni ishlatadi.
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
    # To'liq JSHSHIR — ro'yxatda ham (`SessionCandidateSerializer`
    # izohiga qarang: qidiruv va solishtirish aynan shu raqam
    # bo'yicha ketadi).
    pinfl = serializers.CharField(read_only=True)
    masked_pinfl = serializers.CharField(read_only=True)
    exam_name = serializers.CharField(source="exam.name", read_only=True)
    zone_name = serializers.CharField(source="zone.name", read_only=True, default="")
    region_name = serializers.CharField(source="zone.region.name", read_only=True, default="")
    computer_code = serializers.CharField(source="computer.inventory_code", read_only=True, default="")
    # KOMPYUTER RAQAMI. Proktor "12-kompyuterda nima bo'lyapti?"
    # degan savol bilan keladi va inventar kodini u bilmaydi -
    # stolda raqam yozilgan, kod esa stikerning orqasida.
    computer_number = serializers.IntegerField(
        source="computer.number", read_only=True, default=None
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    is_online = serializers.SerializerMethodField()
    # Proktor tasdiqlanmagan sessiyani ro'yxatdayoq ajrata olishi kerak.
    identity_verified = serializers.BooleanField(read_only=True)
    # Kuzatuv holati ro'yxatda ham kerak: `status` "imtihon ketyapti"
    # deb turgan, kuzatuv esa `degraded` bo'lgan sessiya aynan
    # ro'yxatdan ajralib turishi kerak. Qiymat qisqa satr - javob
    # hajmiga sezilarli ta'sir qilmaydi.
    proctoring_state_display = serializers.CharField(
        source="get_proctoring_state_display", read_only=True
    )

    class Meta:
        model = ExamSession
        fields = (
            "id", "public_id", "candidate_name", "pinfl", "masked_pinfl",
            "identity_verified",
            "exam", "exam_name", "zone", "zone_name", "region_name",
            "computer", "computer_code", "computer_number", "attempt_no", "exam_date",
            "status", "status_display", "risk_score",
            "proctoring_state", "proctoring_state_display",
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


class LocalRecordingSerializer(serializers.ModelSerializer):
    """
    Mashinada qolgan yozuv — panel uchun.

    `file_url` FAQAT NUSXALASH UCHUN: brauzer `file://` ni ocha
    olmaydi (xavfsizlik cheklovi) va bu kutilgan. Manzil odam
    uchun — proktor mashinani topib, papkani o'sha yerdan ochadi.
    """

    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    file_url = serializers.CharField(read_only=True)
    size_mb = serializers.SerializerMethodField()

    class Meta:
        model = LocalRecording
        fields = (
            "id", "kind", "kind_display", "local_path", "file_url",
            "size_bytes", "size_mb", "duration_ms", "width", "height",
            "frames", "frames_dropped", "device_id", "machine_mac",
            "event_type", "camera_role", "confidence", "captured_at",
        )

    def get_size_mb(self, obj) -> float:
        return round(obj.size_bytes / (1024 * 1024), 1)


class SessionDetailSerializer(SessionListSerializer):
    # Manba — sessiyaning o'zi: talabgor maydonlari unga muzlatilgan.
    candidate_detail = CandidateBriefSerializer(source="*", read_only=True)
    terminated_by_name = serializers.CharField(
        source="terminated_by.username", read_only=True, default=""
    )
    duration_seconds = serializers.IntegerField(read_only=True)
    live_state = serializers.SerializerMethodField()
    identity = serializers.DictField(read_only=True)
    # MASHINADAGI YOZUVLAR. Ro'yxatda ko'rsatilmaydi (u yerda
    # sessiyalar yuzlab) va alohida endpoint ham berilmaydi: bitta
    # sessiyada ular bir nechta bo'ladi, ya'ni sahifalashning
    # ma'nosi yo'q va ikkinchi so'rov faqat kechikish qo'shardi.
    local_recordings = LocalRecordingSerializer(many=True, read_only=True)

    class Meta(SessionListSerializer.Meta):
        fields = SessionListSerializer.Meta.fields + (
            "candidate_detail", "mac_address", "machine_uuid", "termination_reason",
            "terminated_by", "terminated_by_name", "face_check_count",
            # Platforma identifikatorlari panelda KO'RSATILADI: nosozlikda
            # operator administratorga aynan shu raqamlarni aytadi.
            "external_candidate_id", "external_status",
            "duration_seconds", "live_state", "identity", "meta", "updated_at",
            # Ball TARKIBI faqat tafsilotda: u apellyatsiya hujjati va
            # ro'yxatda hech qachon ko'rsatilmaydi.
            "risk_breakdown", "camera_check", "ai_profile",
            "local_recordings",
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
    """
    Bitta yuz tekshiruvi.

    `image_path` ATAYLAB berilmaydi — u serverning ichki katalog
    strukturasi (`ProctoringScreenshotSerializer` bilan bir xil
    qoida). Uning o'rniga `image_url`: ruxsat tekshiriladigan
    endpoint, u `X-Accel-Redirect` bilan javob beradi.
    """

    stage_display = serializers.CharField(source="get_stage_display", read_only=True)
    image_url = serializers.SerializerMethodField()
    reference_image_url = serializers.SerializerMethodField()

    class Meta:
        model = FaceVerificationLog
        fields = (
            "id", "session", "exam", "pinfl", "stage", "stage_display", "source",
            "score", "threshold", "passed", "faces_detected",
            "image_url", "reference_image_url", "occurred_at",
        )

    def get_image_url(self, obj) -> str | None:
        """
        IKKI SAQLASH YO'LI, ikki xil havola.

        Fayl tizimi yo'li USTUN: client kadrni multipart bilan
        yuboradi va u diskka tushadi. `image_key` (S3) qoldirilgan,
        chunki presigned yo'l qo'shilganda shartnoma o'zgarmasligi
        kerak.
        """
        if obj.image_path:
            path = reverse("face-log-file", kwargs={"pk": obj.pk})
            request = self.context.get("request")
            return request.build_absolute_uri(path) if request else path
        return presign_get(obj.image_key) if obj.image_key else None

    def get_reference_image_url(self, obj) -> str | None:
        """
        Hujjat (pasport) rasmi — FAQAT kirishdagi tekshiruvda.

        Test davomidagi qatorlarda u yo'q va bu ataylab: u yerda
        etalon pasport rasmi emas, kirishda tasdiqlangan kadr
        (`CLAUDE.md`, "FaceID: solishtirish CLIENTDA" bo'limi).
        """
        if not obj.reference_image_path:
            return None
        path = reverse("face-log-file", kwargs={"pk": obj.pk})
        url = "{}?kind=reference".format(path)
        request = self.context.get("request")
        return request.build_absolute_uri(url) if request else url


class ScreenshotMetaSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = ScreenshotMeta
        fields = (
            "id", "session", "kind", "url", "sha256", "size_bytes",
            "width", "height", "captured_at", "question_id", "question_number",
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
            "mime_type", "seq", "captured_at", "received_at", "question_id", "question_number",
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


class EvidenceArtifactSerializer(serializers.ModelSerializer):
    """
    Dalil metadata'si — FAYLNING O'ZI EMAS.

    Fayl alohida endpointdan olinadi (`evidence/{id}/file/`), chunki
    u nginx orqali beriladi va ruxsati alohida (`evidence.view`).
    Ro'yxatga baytlarni qo'shish 20 ta dalilli sahifani o'nlab
    megabaytga aylantirardi.
    """

    file_url = serializers.SerializerMethodField()
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = EvidenceArtifact
        fields = (
            "id", "kind", "kind_display", "event_type", "camera_role",
            "confidence", "duration_ms", "width", "height", "size_bytes",
            "mime_type", "boxes", "captured_at", "received_at", "file_url",
        )

    def get_file_url(self, obj) -> str:
        request = self.context.get("request")
        from django.urls import reverse

        url = reverse("evidence-file", kwargs={"pk": obj.pk})
        return request.build_absolute_uri(url) if request else url
