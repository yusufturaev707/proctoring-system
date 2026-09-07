from django.contrib import admin

from apps.exams.models import Exam, ExamSchedule, ExamType


@admin.register(ExamType)
class ExamTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "is_active")
    list_filter = ("is_active",)
    # `ExamAdmin.autocomplete_fields` shu ro'yxatga tayanadi — usiz
    # Django admin tekshiruvda (`admin.E040`) xato beradi.
    search_fields = ("name", "key")


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ("name", "exam_type", "key", "external_code", "duration_minutes", "is_active")
    list_filter = ("is_active", "exam_type")
    search_fields = ("name", "key", "external_code")
    # Turi ustunga chiqarilgani uchun: usiz har bir qator uchun alohida
    # so'rov ketardi (N+1).
    list_select_related = ("exam_type",)
    autocomplete_fields = ("exam_type",)


@admin.register(ExamSchedule)
class ExamScheduleAdmin(admin.ModelAdmin):
    list_display = ("exam", "zone", "exam_date", "starts_at", "ends_at", "is_active")
    list_filter = ("exam_date", "is_active", "exam")
    date_hierarchy = "exam_date"
    list_select_related = ("exam", "zone")
