"""Admin / proktor uchun monitoring API."""

from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import ScreenshotNotFound
from apps.common.mixins import AuditLogMixin, PermissionRequiredMixin
from apps.common.pagination import (
    AuditCursorPagination,
    EventCursorPagination,
    ScreenshotCursorPagination,
    SessionCursorPagination,
)
from apps.common.permissions import HasRolePermission, RegionScopedPermission
from apps.proctoring import selectors
from apps.proctoring.api.v1.serializers import (
    AuditLogSerializer,
    FaceVerificationLogSerializer,
    ProctoringEventSerializer,
    ProctoringScreenshotSerializer,
    ScreenshotMetaSerializer,
    SessionDetailSerializer,
    SessionHistorySerializer,
    SessionListSerializer,
    SessionTerminateSerializer,
    SessionWarnSerializer,
    TechnicalProblemResolveSerializer,
    TechnicalProblemSerializer,
)
from apps.proctoring.models import ExamSession, ProctoringEvent, TechnicalProblem
from apps.proctoring.services import screenshots as screenshot_service
from apps.proctoring.services import session as session_service
from apps.proctoring.services.audit import record_audit
from apps.proctoring.services.realtime import send_client_command


class ExamSessionViewSet(PermissionRequiredMixin, viewsets.ReadOnlyModelViewSet):
    """
    Sessiyalar — faqat o'qish uchun.

    Sessiya API orqali yaratilmaydi/o'chirilmaydi: uni faqat client oqimi
    yaratadi va faqat servis qatlami yakunlaydi. Bu holat mashinasini
    tasodifiy buzilishdan himoya qiladi.
    """

    permission_classes = [IsAuthenticated, HasRolePermission, RegionScopedPermission]
    required_permission = "sessions.terminate"
    required_read_permission = "sessions.view"
    pagination_class = SessionCursorPagination

    filterset_fields = [
        "status", "exam", "zone", "zone__region", "exam_date", "computer", "pinfl",
    ]
    search_fields = ["ip_address", "mac_address", "pinfl", "last_name", "first_name"]
    ordering_fields = ["risk_score", "started_at", "created_at", "last_heartbeat_at"]

    def get_serializer_class(self):
        return SessionListSerializer if self.action == "list" else SessionDetailSerializer

    def get_queryset(self):
        queryset = selectors.sessions_base()
        user = self.request.user
        if user.is_region_scoped:
            queryset = queryset.filter(zone__region_id=user.region_id)
        return queryset.order_by("-created_at")

    @extend_schema(responses=SessionListSerializer(many=True))
    @action(detail=False, methods=["get"])
    def live(self, request):
        """
        Jonli monitoring — faqat faol sessiyalar, xavf bo'yicha tartiblangan.

        Proktor jismonan 20-30 tadan ko'pini kuzata olmaydi, shuning uchun
        standart limit kichik. Bu WebSocket fan-out'ini ham kamaytiradi.
        """
        user = request.user

        # Viloyat: foydalanuvchi o'z viloyatiga biriktirilgan bo'lsa,
        # so'rovdagi qiymat E'TIBORGA OLINMAYDI — aks holda filtr
        # maydoni hudud chegarasini chetlab o'tish vositasiga aylanadi.
        # Faqat global ko'ruvchi (superuser) viloyat tanlay oladi.
        if user.is_superuser:
            region_id = request.query_params.get("region") or None
        else:
            region_id = user.region_id

        queryset = selectors.sessions_for_monitoring(
            region_id=region_id,
            zone_id=request.query_params.get("zone"),
            exam_id=request.query_params.get("exam"),
            exam_date=request.query_params.get("date") or None,
        )

        limit = min(int(request.query_params.get("limit", 50)), 200)
        sessions = list(queryset[:limit])

        # Redis'dagi issiq holatni bitta round-trip'da olamiz.
        from apps.proctoring.services import state as session_state

        hot_states = session_state.get_states([item.pk for item in sessions])

        data = SessionListSerializer(sessions, many=True, context={"request": request}).data
        for row in data:
            state = hot_states.get(row["id"], {})
            if state:
                row["risk_score"] = max(row["risk_score"], int(state.get("risk", 0) or 0))
                row["event_count"] = int(state.get("events", row["event_count"]) or 0)
                row["face_fail_count"] = int(state.get("face_fails", row["face_fail_count"]) or 0)
        return Response({"count": len(data), "results": data})

    @extend_schema(responses=SessionHistorySerializer(many=True))
    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        """
        Shu talabgorning barcha imtihonlari.

        Talabgor bir necha sanada topshirishi odatiy hol (1-sanada bir fan,
        10-sanada boshqasi). Alohida `Candidate` jadvali yo'q, shuning uchun
        tarix JSHSHIR bo'yicha yig'iladi — `idx_session_pinfl` indeksida.
        """
        session = self.get_object()
        if not session.pinfl:
            return Response({"count": 0, "results": []})

        queryset = selectors.sessions_for_pinfl(session.pinfl)
        user = request.user
        if user.is_region_scoped:
            queryset = queryset.filter(zone__region_id=user.region_id)

        rows = list(queryset[:100])
        return Response(
            {
                "count": len(rows),
                "results": SessionHistorySerializer(
                    rows, many=True, context={"request": request}
                ).data,
            }
        )

    @extend_schema(responses=ProctoringEventSerializer(many=True))
    @action(detail=True, methods=["get"], pagination_class=EventCursorPagination)
    def events(self, request, pk=None):
        session = self.get_object()
        min_severity = request.query_params.get("min_severity")
        queryset = selectors.session_events(
            session.pk,
            min_severity=int(min_severity) if min_severity else None,
            types=request.query_params.getlist("type"),
        )
        page = self.paginate_queryset(queryset)
        serializer = ProctoringEventSerializer(page, many=True, context={"request": request})
        return self.get_paginated_response(serializer.data)

    @action(detail=True, methods=["get"], url_path="face-logs", pagination_class=EventCursorPagination)
    def face_logs(self, request, pk=None):
        session = self.get_object()
        queryset = selectors.session_face_logs(
            session.pk, only_failed=request.query_params.get("failed") == "true"
        )
        page = self.paginate_queryset(queryset)
        serializer = FaceVerificationLogSerializer(page, many=True, context={"request": request})
        return self.get_paginated_response(serializer.data)

    @action(detail=True, methods=["get"], pagination_class=ScreenshotCursorPagination)
    def screenshots(self, request, pk=None):
        session = self.get_object()
        queryset = selectors.session_screenshots(session.pk, request.query_params.get("kind"))
        page = self.paginate_queryset(queryset)
        serializer = ScreenshotMetaSerializer(page, many=True, context={"request": request})
        return self.get_paginated_response(serializer.data)

    @extend_schema(responses=ProctoringScreenshotSerializer(many=True))
    @action(
        detail=True,
        methods=["get"],
        url_path="stored-screenshots",
        pagination_class=ScreenshotCursorPagination,
    )
    def stored_screenshots(self, request, pk=None):
        """
        Fayl tizimida saqlangan skrinshotlar.

        `screenshots/` dan alohida: u obyekt storage'idagi (`ScreenshotMeta`)
        yozuvlarni beradi. Ikkala ro'yxat bir vaqtda bo'sh bo'lmasligi
        odatiy — o'rnatishda faqat bitta yo'l yoqilgan bo'ladi.
        """
        session = self.get_object()
        queryset = selectors.session_stored_screenshots(session.pk)
        page = self.paginate_queryset(queryset)
        serializer = ProctoringScreenshotSerializer(
            page, many=True, context={"request": request}
        )
        return self.get_paginated_response(serializer.data)

    @extend_schema(request=SessionWarnSerializer, responses={200: None})
    @action(detail=True, methods=["post"])
    def warn(self, request, pk=None):
        """Talabgor ekranida ogohlantirish ko'rsatadi (WebSocket orqali)."""
        if not request.user.has_role_permission("sessions.warn"):
            return Response({"detail": "Ruxsat yo'q"}, status=status.HTTP_403_FORBIDDEN)

        session = self.get_object()
        serializer = SessionWarnSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = serializer.validated_data["message"]

        send_client_command(
            session_id=session.pk,
            command="warning",
            payload={"message": message, "severity": serializer.validated_data["severity"]},
        )
        ProctoringEvent.objects.create(
            session=session,
            type=ProctoringEvent.Type.PROCTOR_WARNING,
            severity=ProctoringEvent.Severity.MEDIUM,
            occurred_at=timezone.now(),
            payload={"message": message, "proctor": request.user.username},
        )
        record_audit(
            actor=request.user, action="session_warn", object_type="ExamSession",
            object_id=session.pk, meta={"message": message}, request=request,
        )
        return Response({"detail": "Ogohlantirish yuborildi"})

    @extend_schema(request=SessionTerminateSerializer, responses=SessionDetailSerializer)
    @action(detail=True, methods=["post"])
    def terminate(self, request, pk=None):
        """
        Sessiyani chetlashtiradi.

        Token Redis'dan darhol o'chadi — talabgorning keyingi so'rovi
        401 oladi va client imtihonni yopadi.
        """
        session = self.get_object()
        serializer = SessionTerminateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data["reason"]

        session = session_service.terminate_session(session, actor=request.user, reason=reason)
        send_client_command(
            session_id=session.pk, command="terminate", payload={"reason": reason}
        )
        record_audit(
            actor=request.user, action="session_terminate", object_type="ExamSession",
            object_id=session.pk, meta={"reason": reason}, request=request,
        )
        return Response(SessionDetailSerializer(session, context={"request": request}).data)


class TechnicalProblemViewSet(PermissionRequiredMixin, AuditLogMixin, viewsets.ModelViewSet):
    serializer_class = TechnicalProblemSerializer
    permission_classes = [IsAuthenticated, HasRolePermission]
    required_permission = "technical.resolve"
    required_read_permission = "technical.view"
    audit_object_type = "TechnicalProblem"
    filterset_fields = [
        "is_resolved", "kind", "session", "session__zone", "session__zone__region",
    ]
    # Operator muammoni talabgor familiyasi bo'yicha qidiradi — u qo'ng'iroq
    # qilib "falonchi Toshmatovda muammo" deydi, sessiya ID'sini emas.
    search_fields = [
        "description", "session__last_name", "session__first_name", "session__pinfl",
    ]
    ordering_fields = ["started_at", "created_at"]

    def get_queryset(self):
        user = self.request.user
        return selectors.technical_problems(
            unresolved_only=self.request.query_params.get("unresolved") == "true",
            region_id=None if user.is_superuser else user.region_id,
        )

    @extend_schema(request=TechnicalProblemResolveSerializer, responses=TechnicalProblemSerializer)
    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        problem = self.get_object()
        serializer = TechnicalProblemResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        problem.is_resolved = True
        problem.resolved_by = request.user
        problem.resolution_note = data.get("note", "")
        problem.finished_at = timezone.now()
        problem.overtime = timezone.timedelta(minutes=data["overtime_minutes"])
        problem.save(
            update_fields=[
                "is_resolved", "resolved_by", "resolution_note",
                "finished_at", "overtime", "updated_at",
            ]
        )

        session = problem.session
        if data["resume_session"] and session.status == ExamSession.Status.TECHNICAL_PROBLEM:
            session.status = ExamSession.Status.IN_PROGRESS
            session.save(update_fields=["status", "updated_at"])
            send_client_command(
                session_id=session.pk,
                command="resume",
                payload={"overtime_minutes": data["overtime_minutes"]},
            )

        record_audit(
            actor=request.user, action="tp_resolve", object_type="TechnicalProblem",
            object_id=problem.pk, meta=data, request=request,
        )
        return Response(TechnicalProblemSerializer(problem, context={"request": request}).data)


class AuditLogViewSet(PermissionRequiredMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated, HasRolePermission]
    required_permission = "audit.view"
    required_read_permission = "audit.view"
    pagination_class = AuditCursorPagination
    filterset_fields = ["actor", "action", "object_type"]
    search_fields = ["actor_username", "object_id", "ip_address"]

    def get_queryset(self):
        queryset = selectors.audit_logs(
            actor_id=self.request.query_params.get("actor"),
            action=self.request.query_params.get("action"),
            object_type=self.request.query_params.get("object_type"),
        )
        # Sana oralig'i — apellyatsiya tekshiruvida "o'sha kuni nima
        # bo'lgan" savoli aynan shu shaklda beriladi.
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")
        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)
        return queryset


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------
class DashboardSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        region_id = None if user.is_superuser else user.region_id
        exam_date = request.query_params.get("date")

        from apps.integrations.exam_platform import platform_health

        return Response(
            {
                "summary": selectors.dashboard_summary(region_id=region_id, exam_date=exam_date),
                "events": selectors.event_type_breakdown(
                    exam_date=exam_date, region_id=region_id
                ),
                "external_platform": platform_health(),
            }
        )


class DashboardZonesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        region_id = None if user.is_superuser else user.region_id
        return Response(
            {
                "zones": selectors.zone_breakdown(
                    region_id=region_id, exam_date=request.query_params.get("date")
                ),
            }
        )


class DashboardDevicesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.devices.selectors import zone_device_summary

        user = request.user
        region_id = None if user.is_superuser else user.region_id
        return Response({"zones": zone_device_summary(region_id=region_id)})


# --------------------------------------------------------------------------
# Skrinshot fayli
# --------------------------------------------------------------------------
class ScreenshotFileView(APIView):
    """
    Fayl tizimidagi skrinshotni beradi.

    Mas'uliyat bo'linishi:

        Django  ->  KIMGA ruxsat bor (autentifikatsiya, rol, hudud)
        nginx   ->  BAYTLARNI uzatish (`X-Accel-Redirect`)

    Django faylni o'zi o'qib bermaydi. Sabab: gunicorn worker'i sinxron
    va u fayl uzatilguncha to'liq band bo'lib turadi. Proktor galereyani
    varaqlaganda bu sekundiga o'nlab so'rov demak — bir necha proktor
    butun API'ni to'xtatib qo'ya oladi. `X-Accel-Redirect` da worker
    javob sarlavhasini berib darhol bo'shaydi.

    Storage root `internal` location ortida yotadi, ya'ni unga to'g'ridan
    to'g'ri URL bilan kirib bo'lmaydi — faqat shu view ruxsat bergandan
    keyin.

    `<img src>` bu endpointga `Authorization` sarlavhasini yubora
    olmaydi, shuning uchun frontend rasmni `fetch`/axios bilan blob
    sifatida oladi (`api/endpoints.js`). Ya'ni token URL'ga chiqmaydi:
    URL brauzer tarixida, `Referer` da va nginx access log'ida qoladi.
    """

    permission_classes = [IsAuthenticated, HasRolePermission]
    required_permission = "sessions.view"

    @extend_schema(responses={200: OpenApiTypes.BINARY})
    def get(self, request, pk: int):
        screenshot = selectors.stored_screenshot_for_user(pk, request.user)
        if screenshot is None:
            # "Ruxsat yo'q" va "mavjud emas" ATAYLAB ajratilmaydi: aks
            # holda 403/404 farqi boshqa hududda qaysi id'lar borligini
            # sanab chiqish imkonini beradi.
            raise ScreenshotNotFound()
        return screenshot_service.screenshot_response(screenshot)
