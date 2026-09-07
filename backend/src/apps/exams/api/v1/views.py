from django.db.models import Count, Q
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.common.mixins import AuditLogMixin, PermissionRequiredMixin, SoftDeleteRestoreMixin
from apps.common.permissions import HasRolePermission
from apps.exams.api.v1.serializers import (
    ExamScheduleSerializer,
    ExamSerializer,
    ExamTypeSerializer,
)
from apps.exams.models import Exam, ExamSchedule, ExamType


class ExamTypeViewSet(
    PermissionRequiredMixin, AuditLogMixin, SoftDeleteRestoreMixin, viewsets.ModelViewSet
):
    """
    Imtihon turlari ma'lumotnomasi.

    Alohida ruxsat kiritilmadi — tur imtihon domenining bir qismi, ya'ni
    `exams.view` / `exams.manage` bilan boshqariladi. Aks holda rol
    matritsasiga hech qanday yangi qaror bermaydigan yana ikkita kalit
    qo'shilardi.
    """

    queryset = (
        ExamType.objects
        # Turga bog'langan imtihonlar soni — o'chirishdan oldin
        # "bu tur ishlatilyaptimi" degan savolga javob beradi. Yumshoq
        # o'chirilgan imtihonlar hisobga olinmaydi.
        .annotate(
            exams_count=Count(
                "exams", filter=Q(exams__deleted_at__isnull=True), distinct=True
            )
        )
        .order_by("name")  # annotate() Meta.ordering ni bekor qiladi
    )
    serializer_class = ExamTypeSerializer
    permission_classes = [IsAuthenticated, HasRolePermission]
    required_permission = "exams.manage"
    required_read_permission = "exams.view"
    audit_object_type = "ExamType"
    filterset_fields = ["is_active"]
    search_fields = ["name", "key"]
    ordering_fields = ["name", "created_at"]

    def get_queryset(self):
        return self.apply_deleted_filter(super().get_queryset())


class ExamViewSet(
    PermissionRequiredMixin, AuditLogMixin, SoftDeleteRestoreMixin, viewsets.ModelViewSet
):
    queryset = (
        Exam.objects
        .select_related("setting", "exam_type")
        .annotate(sessions_count=Count("sessions", distinct=True))
        .order_by("name")  # annotate() Meta.ordering ni bekor qiladi
    )
    serializer_class = ExamSerializer
    permission_classes = [IsAuthenticated, HasRolePermission]
    required_permission = "exams.manage"
    required_read_permission = "exams.view"
    audit_object_type = "Exam"
    filterset_fields = ["is_active", "setting", "exam_type"]
    # Tur nomi bo'yicha ham qidiriladi: ro'yxatda ustun sifatida
    # ko'rinib turgan qiymat qidiruvga tushmasligi kutilmagan xulq.
    search_fields = ["name", "key", "external_code", "exam_type__name"]
    ordering_fields = ["name", "created_at"]

    def get_queryset(self):
        return self.apply_deleted_filter(super().get_queryset())


class ExamScheduleViewSet(
    PermissionRequiredMixin, AuditLogMixin, SoftDeleteRestoreMixin, viewsets.ModelViewSet
):
    queryset = (
        ExamSchedule.objects
        .select_related("exam", "zone", "zone__region")
    )
    serializer_class = ExamScheduleSerializer
    permission_classes = [IsAuthenticated, HasRolePermission]
    required_permission = "exams.manage"
    required_read_permission = "exams.view"
    audit_object_type = "ExamSchedule"
    filterset_fields = ["exam", "zone", "exam_date", "is_active"]
    ordering_fields = ["exam_date", "starts_at"]

    def get_queryset(self):
        queryset = self.apply_deleted_filter(super().get_queryset())
        user = self.request.user
        if user.is_region_scoped:
            queryset = queryset.filter(zone__region_id=user.region_id)
        return queryset
