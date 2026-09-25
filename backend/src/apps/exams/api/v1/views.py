from django.db.models import Count, F, OuterRef, Q, Subquery, Sum
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import SAFE_METHODS, IsAuthenticated
from rest_framework.response import Response

from apps.common.mixins import AuditLogMixin, PermissionRequiredMixin, SoftDeleteRestoreMixin
from apps.common.exceptions import SeatUnavailable
from apps.common.permissions import HasRolePermission
from apps.common.utils.crypto import mask_pinfl
from apps.exams import bookings
from apps.exams.api.v1.serializers import (
    BookingAssignSerializer,
    BookingBulkAssignSerializer,
    BookingGenerateSerializer,
    ComputerBookingSerializer,
    ExamScheduleSerializer,
    ExamSerializer,
    ExamTypeSerializer,
)
from apps.exams.models import ComputerBooking, Exam, ExamSchedule, ExamType
from apps.proctoring.services.audit import record_audit


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
    # Imtihon barcha viloyatlar uchun bitta yozuv (`RepublicLevelWrite`).
    republic_write_only = True
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
    # Imtihon barcha viloyatlar uchun bitta yozuv (`RepublicLevelWrite`).
    republic_write_only = True
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
    filterset_fields = ["exam", "zone", "zone__region", "exam_date", "is_active"]
    ordering_fields = ["exam_date", "starts_at"]

    def get_queryset(self):
        queryset = self.apply_deleted_filter(super().get_queryset())
        user = self.request.user
        if user.is_region_scoped:
            region = Q(zone__region_id=user.region_id)
            # UMUMIY sessiya (`zone=NULL`) viloyat binolariga HAM amal
            # qiladi va viloyat administratori uni KO'RISHI kerak — aks
            # holda u o'z kompyuterlariga bron qila olmasdi (sessiya
            # tanlash ro'yxatida umuman chiqmasdi). O'zgartirish esa
            # faqat respublika darajasida: bitta viloyat hamma uchun
            # vaqtni surib qo'ymasligi kerak.
            if self.request.method in SAFE_METHODS:
                region |= Q(zone__isnull=True)
            queryset = queryset.filter(region)
        return queryset


class ComputerBookingViewSet(PermissionRequiredMixin, AuditLogMixin, viewsets.ModelViewSet):
    """
    Kompyuter bronlari — panel va tashqi tizim uchun BITTA yuza.

    Tashqi tizim (talabgorlarni taqsimlovchi) oddiy xodim kabi JWT bilan
    kiradi va unga faqat `bookings.manage` beriladi: alohida
    integratsiya kaliti ikkinchi autentifikatsiya yuzasini ochardi va
    uning amallari auditda "kim" siz qolardi.

    Mantiq `apps.exams.bookings` da — view faqat doirani (viloyat) va
    auditni qo'shadi.
    """

    serializer_class = ComputerBookingSerializer
    permission_classes = [IsAuthenticated, HasRolePermission]
    required_permission = "bookings.manage"
    required_read_permission = "bookings.view"
    audit_object_type = "ComputerBooking"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filterset_fields = [
        "schedule", "is_active", "is_booked", "pinfl",
        "computer", "computer__zone", "computer__zone__region",
    ]
    search_fields = ["pinfl", "computer__number", "computer__inventory_code"]
    ordering_fields = ["computer__number", "booked_at", "updated_at"]

    def get_queryset(self):
        from apps.proctoring.models import ExamSession

        # Talabgor KELDIMI — eng oxirgi urinishining holati. Subquery:
        # 500 qatorli sahifa uchun 500 ta alohida so'rov bo'lmasligi kerak.
        latest_session = (
            ExamSession.objects.filter(
                schedule_id=OuterRef("schedule_id"), pinfl=OuterRef("pinfl")
            )
            .order_by("-created_at")
            .values("status")[:1]
        )
        queryset = (
            ComputerBooking.objects
            .select_related("schedule__exam", "computer__zone__region", "booked_by")
            .annotate(session_status=Subquery(latest_session))
            .order_by(
                "computer__zone__region__name",
                "computer__zone__name",
                F("computer__number").asc(nulls_last=True),
                "computer__inventory_code",
            )
        )
        user = self.request.user
        if user.is_region_scoped:
            queryset = queryset.filter(computer__zone__region_id=user.region_id)
        return queryset

    # ------------------------------------------------------------------
    def _region_id(self):
        user = self.request.user
        return user.region_id if user.is_region_scoped else None

    def _check_schedule(self, schedule: ExamSchedule) -> None:
        """
        Viloyat administratori faqat O'Z viloyatidagi yoki umumiy
        (`zone=NULL`) sessiyada ishlay oladi. Umumiy sessiyada u baribir
        faqat o'z kompyuterlarini ko'radi (`bookings.schedule_computers`).
        """
        region_id = self._region_id()
        if region_id and schedule.zone_id and schedule.zone.region_id != region_id:
            raise NotFound("Test sessiyasi topilmadi")

    def perform_create(self, serializer):
        self._check_schedule(serializer.validated_data["schedule"])
        return super().perform_create(serializer)

    def perform_update(self, serializer):
        """Yagona yoziladigan maydon — `is_active` (ishchi / buzilgan)."""
        previous = serializer.instance.is_active
        instance = serializer.save()
        if previous != instance.is_active:
            self.log_audit(
                "update", instance,
                {
                    "action": "working" if instance.is_active else "broken",
                    "computer": instance.computer_id,
                    "schedule": instance.schedule_id,
                },
            )
        return instance

    def perform_destroy(self, instance):
        # Band joyni o'chirish talabgorni JIMGINA joysiz qoldirardi va u
        # imtihon kuni `seat_not_booked` bilan qaytarilardi.
        if instance.is_booked:
            raise SeatUnavailable("Band joyni o'chirib bo'lmaydi — avval bo'shating")
        self.log_audit(
            "delete", instance,
            {"computer": instance.computer_id, "schedule": instance.schedule_id},
        )
        instance.delete()

    def _row(self, booking) -> dict:
        """Amaldan keyingi qator — annotatsiyalar bilan (ro'yxatdagi shakl)."""
        return self.get_serializer(self.get_queryset().get(pk=booking.pk)).data

    # ------------------------------------------------------------------
    @extend_schema(request=BookingGenerateSerializer, responses={200: None})
    @action(detail=False, methods=["post"])
    def generate(self, request):
        """
        Sessiya doirasidagi barcha kompyuterlar uchun joy yaratadi.

        Umumiy sessiya — barcha viloyatlarning barcha binolari (viloyat
        administratori uchun — faqat o'z viloyati). Takroriy chaqiruv
        faqat yangi qo'shilgan kompyuterlarni qo'shadi.
        """
        serializer = BookingGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        schedule = serializer.validated_data["schedule"]
        self._check_schedule(schedule)
        result = bookings.generate_seats(
            schedule,
            region_id=self._region_id(),
            zone_id=serializer.validated_data.get("zone"),
        )
        if result["created"]:
            record_audit(
                actor=request.user, action="create", object_type="ExamSchedule",
                object_id=schedule.pk, meta={"action": "generate_seats", **result},
                request=request,
            )
        return Response(result)

    @extend_schema(request=BookingAssignSerializer, responses={200: ComputerBookingSerializer})
    @action(detail=False, methods=["post"])
    def assign(self, request):
        """
        Talabgorni biriktiradi yoki KO'CHIRADI.

        Javob — yangi joy qatori va `moved_from` (oldingi kompyuter ID,
        ko'chirilmagan bo'lsa `null`).
        """
        serializer = BookingAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        schedule = data["schedule"]
        self._check_schedule(schedule)
        booking, previous = bookings.assign(
            schedule,
            data["pinfl"],
            computer=data.get("computer"),
            zone_id=data.get("zone"),
            region_id=self._region_id(),
            user=request.user,
        )
        moved = previous is not None and previous != booking.computer_id
        # Takroriy so'rov (talabgor allaqachon shu joyda) auditga
        # tushmaydi: tashqi tizim qayta yuborganda jurnal to'lmasin.
        if previous != booking.computer_id:
            self.log_audit(
                "update", booking,
                {
                    "action": "move" if moved else "assign",
                    "pinfl": mask_pinfl(booking.pinfl),
                    "computer": booking.computer_id,
                    "computer_from": previous if moved else None,
                    "schedule": schedule.pk,
                },
            )
        return Response({**self._row(booking), "moved_from": previous if moved else None})

    @extend_schema(request=BookingBulkAssignSerializer, responses={200: None})
    @action(detail=False, methods=["post"], url_path="bulk-assign")
    def bulk_assign(self, request):
        """
        Ko'p talabgorni biriktiradi (tashqi tizim uchun).

        Har qator alohida: xato bo'lganlar `ok: false` va sabab bilan
        qaytadi, qolganlari biriktiriladi. Audit bitta yozuv — 500 ta
        alohida yozuv jurnalni o'qib bo'lmas holga keltirardi.
        """
        serializer = BookingBulkAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        schedule = serializer.validated_data["schedule"]
        self._check_schedule(schedule)
        results = bookings.bulk_assign(
            schedule,
            serializer.validated_data["items"],
            region_id=self._region_id(),
            user=request.user,
        )
        assigned = sum(1 for item in results if item["ok"])
        failed = len(results) - assigned
        record_audit(
            actor=request.user, action="update", object_type="ExamSchedule",
            object_id=schedule.pk,
            meta={"action": "bulk_assign", "assigned": assigned, "failed": failed},
            request=request,
        )
        return Response({"assigned": assigned, "failed": failed, "results": results})

    @extend_schema(request=None, responses={200: ComputerBookingSerializer})
    @action(detail=True, methods=["post"])
    def release(self, request, pk=None):
        """Joyni bo'shatadi (talabgor biriktiruvi olib tashlanadi)."""
        booking = self.get_object()
        if booking.is_booked:
            pinfl = booking.pinfl
            bookings.release(booking)
            self.log_audit(
                "update", booking,
                {
                    "action": "release",
                    "pinfl": mask_pinfl(pinfl),
                    "computer": booking.computer_id,
                    "schedule": booking.schedule_id,
                },
            )
        return Response(self._row(booking))

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """
        Sessiya bo'yicha sonlar: jami, band, bo'sh, buzilgan.

        "Bo'sh" — ishchi VA band emas, ya'ni talabgor qo'yish mumkin
        bo'lgan joylar. Buzilgan joy band bo'lsa ham "buzilgan" da
        sanaladi — `broken_booked` aynan ko'chirishni kutayotgan
        talabgorlar va panel ular uchun alohida ogohlantirish beradi.
        """
        queryset = self.filter_queryset(self.get_queryset())
        counts = queryset.aggregate(
            total=Count("id"),
            booked=Count("id", filter=Q(is_booked=True)),
            free=Count("id", filter=Q(is_booked=False, is_active=True)),
            broken=Count("id", filter=Q(is_active=False)),
            broken_booked=Count("id", filter=Q(is_active=False, is_booked=True)),
            # Joy bir sessiyada bir necha talabgorga xizmat qiladi —
            # "nechta talabgor yakunladi" joylar sonidan mustaqil savol.
            finished=Sum("finished_count"),
        )
        counts["finished"] = counts["finished"] or 0
        return Response(counts)

    # ------------------------------------------------------------------
    # Joylar xaritasi (panel: "vagonlar" va "o'rindiqlar")
    # ------------------------------------------------------------------
    def _schedule_param(self, request) -> ExamSchedule:
        """`?schedule=` — majburiy va doira tekshiruvidan o'tgan."""
        raw = request.query_params.get("schedule")
        if not raw or not str(raw).isdigit():
            raise ValidationError({"schedule": "Test sessiyasi tanlanmagan"})
        schedule = (
            ExamSchedule.objects.alive().select_related("zone").filter(pk=int(raw)).first()
        )
        if schedule is None:
            raise NotFound("Test sessiyasi topilmadi")
        self._check_schedule(schedule)
        return schedule

    @action(detail=False, methods=["get"])
    def zones(self, request):
        """
        Sessiyadagi BINOLAR va har birining sonlari (xaritaning "vagonlari").

        Bitta so'rov, GROUP BY: umumiy sessiyada yuzlab bino bo'ladi va
        ularning har biri uchun alohida `stats/` so'rovi panelni
        sekinlashtirardi. Viloyat foydalanuvchisi faqat o'z binolarini
        oladi — `get_queryset()` dagi chegara shu yerda ham amal qiladi.
        """
        schedule = self._schedule_param(request)
        rows = (
            self.get_queryset()
            .filter(schedule=schedule)
            .order_by()
            .values(
                "computer__zone_id", "computer__zone__name", "computer__zone__number",
                "computer__zone__region_id", "computer__zone__region__name",
            )
            .annotate(
                total=Count("id"),
                booked=Count("id", filter=Q(is_booked=True)),
                free=Count("id", filter=Q(is_booked=False, is_active=True)),
                broken=Count("id", filter=Q(is_active=False)),
                broken_booked=Count("id", filter=Q(is_active=False, is_booked=True)),
            )
            .order_by("computer__zone__region__name", "computer__zone__number", "computer__zone__name")
        )
        return Response({
            "results": [
                {
                    "zone": row["computer__zone_id"],
                    "zone_name": row["computer__zone__name"],
                    "zone_number": row["computer__zone__number"],
                    "region": row["computer__zone__region_id"],
                    "region_name": row["computer__zone__region__name"] or "",
                    "total": row["total"],
                    "booked": row["booked"],
                    "free": row["free"],
                    "broken": row["broken"],
                    "broken_booked": row["broken_booked"],
                }
                for row in rows
            ]
        })

    #: Bitta binoda bundan ko'p joy — o'rnatish xatosi (bino emas, butun
    #: viloyat bitta zonaga yozilgan). Xarita baribir chiziladi, lekin
    #: cheksiz javob serverni ham, brauzerni ham to'xtatardi.
    SEATS_LIMIT = 2000

    @action(detail=False, methods=["get"])
    def seats(self, request):
        """
        Bitta binoning BARCHA joylari — xaritaning "o'rindiqlari".

        Sahifalanmaydi: xarita butun zalni bir vaqtda ko'rsatadi va 25
        tadan bo'lingan zal ma'nosiz. Ro'yxat bilan bir xil qator shakli
        (`ComputerBookingSerializer`) — panel ikkala ko'rinishda bitta
        komponentlarni ishlatadi.
        """
        schedule = self._schedule_param(request)
        zone = request.query_params.get("zone")
        if not zone or not str(zone).isdigit():
            raise ValidationError({"zone": "Bino tanlanmagan"})
        queryset = self.get_queryset().filter(schedule=schedule, computer__zone_id=int(zone))
        rows = list(queryset[: self.SEATS_LIMIT + 1])
        return Response({
            "truncated": len(rows) > self.SEATS_LIMIT,
            "results": self.get_serializer(rows[: self.SEATS_LIMIT], many=True).data,
        })
