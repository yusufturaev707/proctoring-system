from django.contrib import admin

from apps.proctoring.models import (
    AuditLog,
    ExamSession,
    FaceVerificationLog,
    ProctoringEvent,
    ProctoringScreenshot,
    ScreenshotMeta,
    TechnicalProblem,
)


@admin.register(ExamSession)
class ExamSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id", "public_id", "pinfl", "full_name", "exam", "zone",
        "status", "risk_score", "started_at", "finished_at",
    )
    list_filter = ("status", "exam_date", "exam", "zone__region", "is_anonymized")
    search_fields = ("public_id", "pinfl", "last_name", "first_name", "ip_address")
    list_select_related = ("exam", "zone", "computer")
    date_hierarchy = "exam_date"
    # Talabgor ma'lumoti imtihon paytiga muzlatilgan — tahrirlanmaydi.
    readonly_fields = (
        "public_id", "token_hash", "pinfl", "last_name", "first_name",
        "middle_name", "external_candidate_id", "created_at", "updated_at",
    )
    exclude = ("reference_embedding",)
    raw_id_fields = ("computer", "device", "terminated_by")


@admin.register(ProctoringEvent)
class ProctoringEventAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "type", "severity", "occurred_at")
    list_filter = ("type", "severity")
    date_hierarchy = "occurred_at"
    raw_id_fields = ("session",)
    # Milliardlab qatorli jadval — sanashni o'chirib qo'yamiz,
    # aks holda admin sahifasi ochilmaydi.
    show_full_result_count = False

    def has_add_permission(self, request):
        return False


@admin.register(FaceVerificationLog)
class FaceVerificationLogAdmin(admin.ModelAdmin):
    # `session` BO'SH bo'lishi mumkin (kirishda rad etilgan urinish),
    # shuning uchun ro'yxatda `pinfl` va `exam` ham turadi - aks holda
    # aynan shu qatorlarni bir-biridan ajratib bo'lmasdi.
    list_display = (
        "id", "session", "pinfl", "exam", "stage", "source",
        "score", "threshold", "passed", "occurred_at",
    )
    list_filter = ("stage", "source", "passed", "exam")
    search_fields = ("pinfl",)
    raw_id_fields = ("session", "exam", "zone")
    show_full_result_count = False


@admin.register(ScreenshotMeta)
class ScreenshotMetaAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "kind", "size_bytes", "captured_at", "is_committed")
    list_filter = ("kind", "is_committed")
    raw_id_fields = ("session",)
    show_full_result_count = False


@admin.register(ProctoringScreenshot)
class ProctoringScreenshotAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "file_path", "file_size", "mime_type", "captured_at")
    list_filter = ("mime_type",)
    search_fields = ("content_hash", "file_path")
    raw_id_fields = ("session",)
    date_hierarchy = "captured_at"
    show_full_result_count = False

    # Qatorni admin orqali yaratish/tahrirlash MA'NOSIZ: u diskdagi
    # aniq faylga ishora qiladi va faylsiz qator faqat 404 beradi.
    readonly_fields = (
        "session", "file_path", "content_hash", "file_size",
        "mime_type", "seq", "captured_at", "received_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def delete_model(self, request, obj):
        # Fayl va qator BIRGA ketadi — aks holda diskda yetim qoladi.
        from apps.proctoring.services.screenshots import screenshot_delete

        screenshot_delete(obj)

    def delete_queryset(self, request, queryset):
        from apps.proctoring.services.screenshots import screenshot_delete

        for screenshot in queryset:
            screenshot_delete(screenshot)


@admin.register(TechnicalProblem)
class TechnicalProblemAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "kind", "is_resolved", "started_at", "overtime")
    list_filter = ("kind", "is_resolved")
    raw_id_fields = ("session", "resolved_by")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("id", "actor_username", "action", "object_type", "object_id", "created_at")
    list_filter = ("action", "object_type")
    search_fields = ("actor_username", "object_id", "ip_address")
    show_full_result_count = False

    # Audit yozuvi o'zgartirilmasligi va o'chirilmasligi kerak —
    # aks holda uning huquqiy qiymati yo'qoladi.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
