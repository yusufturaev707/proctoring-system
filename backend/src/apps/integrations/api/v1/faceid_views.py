"""
FaceID tizimi uchun kompyuter broni — `X-API-Key` bilan.

FaceID bu yerda ikki ish qiladi:

    1. biriktirishdan OLDIN: ochiq test sessiyalari (`schedules/`) va
       tanlangan sessiyaning ishchi kompyuterlari (`computers/`) — FaceID
       ular ustida nomzodlarga o'rin (`sp_n`) taqsimlaydi;
    2. nomzod Face ID'dan o'tganda: `book/` — shu kompyuterni unga bron
       qiladi. Proctoring client JSHSHIR tekshiruvida AYNAN shu bronni
       talab qiladi (`bookings.resolve_candidate_seat`).

BINO TASHQI RAQAMLAR BILAN ATALADI — `region_dtm_id` + `zone_number`
(FaceID'dagi `regions.number` + `zone.number`), ichki `id` lar emas: ikki
tizimning ID'lari hech qachon mos kelmaydi, bu juftlik esa ikkalasida
bir xil va barqaror. Kompyuter — bino ichidagi TARTIB RAQAMI (stolga
yozilgan, `Computer.number`).

Biznes qoidalari QAYTA YOZILMAGAN: `book/` panel ishlatadigan
`bookings.assign` ni chaqiradi — band, buzilgan, sessiya doirasidan
tashqari joy va imtihondagi talabgorni ko'chirish shu yerda ham rad
etiladi.
"""

from __future__ import annotations

from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import SeatUnavailable
from apps.common.permissions import HasRolePermission
from apps.common.utils.crypto import mask_pinfl
from apps.devices.models import Computer
from apps.exams import bookings
from apps.exams.models import ComputerBooking, ExamSchedule
from apps.integrations.authentication import FaceIdApiKeyAuthentication
from apps.proctoring.services.audit import record_audit


class RepublicLevelIntegration(BasePermission):
    """
    Servis xodimi RESPUBLIKA darajasida bo'lishi shart.

    FaceID butun respublika bo'yicha ishlaydi. Viloyat roli berilgan
    servis xodimi boshqa viloyatlarning kompyuterlarini "yo'q" deb
    ko'rardi va nomzodlar jimgina o'rinsiz qolardi — ochiq xato yaxshiroq.
    """

    message = "Integratsiya xodimi respublika darajasidagi rolga ega bo'lishi kerak"

    def has_permission(self, request, view):
        return not request.user.is_region_scoped


class FaceIdBaseView(APIView):
    authentication_classes = [FaceIdApiKeyAuthentication]
    permission_classes = [HasRolePermission, RepublicLevelIntegration]
    required_permission = "bookings.manage"
    required_read_permission = "bookings.view"


def _zone_ref(zone) -> dict | None:
    if zone is None:
        return None
    return {
        "region_dtm_id": zone.region.dtm_id,
        "zone_number": zone.number,
        "zone_name": zone.name,
        "region_name": zone.region.name,
    }


def _open_schedule(schedule_id) -> ExamSchedule:
    schedule = (
        ExamSchedule.objects.alive()
        .select_related("exam", "zone__region")
        .filter(pk=schedule_id, is_active=True, ends_at__gte=timezone.now())
        .first()
    )
    if schedule is None:
        raise NotFound("Test sessiyasi topilmadi yoki yakunlangan")
    return schedule


class FaceIdSchedulesView(FaceIdBaseView):
    """
    Ochiq test sessiyalari — hali TUGAMAGANLAR (hozir ketayotgan va
    kelgusilari). Biriktirish imtihondan oldin qilinadi, shuning uchun
    "kirish oynasi hozir ochiq" (`is_open`) sharti bu yerda noto'g'ri bo'lardi.
    """

    def get(self, request):
        schedules = (
            ExamSchedule.objects.alive()
            .select_related("exam", "zone__region")
            .filter(is_active=True, ends_at__gte=timezone.now())
            .order_by("starts_at", "pk")
        )
        return Response([
            {
                "id": schedule.pk,
                "exam_id": schedule.exam_id,
                "exam_name": schedule.exam.name,
                "exam_date": schedule.exam_date,
                "starts_at": schedule.starts_at,
                "ends_at": schedule.ends_at,
                # `null` — umumiy sessiya: barcha binolarning kompyuterlari.
                "zone": _zone_ref(schedule.zone),
            }
            for schedule in schedules
        ])


class FaceIdComputersView(FaceIdBaseView):
    """
    Sessiyaning ISHCHI kompyuterlari — FaceID ular ustida o'rin taqsimlaydi.

    "Ishchi" = hisobdan chiqarilmagan (`Computer.is_active`) VA shu
    sessiyada buzilgan deb belgilanmagan (`ComputerBooking.is_active`).
    Raqamsiz kompyuter kirmaydi: FaceID nomzodga RAQAM beradi (`sp_n`) va
    raqamsiz mashina bu yerda hech kimga berib bo'lmaydigan o'rin.

    Allaqachon band joylar ham qaytadi (`pinfl` bilan): FaceID o'z
    nomzodining joyini saqlab qoladi, begona bronni esa chetlab o'tadi.

    O'QISH — hech narsa yozilmaydi: bron qatori hali yo'q kompyuter
    "ishchi" hisoblanadi (`generate_seats` qatorni keyin, bronda yaratadi).
    """

    def get(self, request, schedule_id: int):
        schedule = _open_schedule(schedule_id)
        computers = (
            bookings.schedule_computers(schedule)
            .filter(number__isnull=False, zone__deleted_at__isnull=True)
            .order_by("zone__region__dtm_id", "zone__number", "number")
        )
        seats = {
            booking.computer_id: booking
            for booking in ComputerBooking.objects.filter(schedule=schedule).only(
                "computer_id", "is_active", "is_booked", "pinfl"
            )
        }
        results = []
        for computer in computers:
            seat = seats.get(computer.pk)
            if seat is not None and not seat.is_active:
                continue
            results.append({
                "computer_id": computer.pk,
                "number": computer.number,
                "label": computer.label,
                **_zone_ref(computer.zone),
                "is_booked": bool(seat and seat.is_booked),
                "pinfl": seat.pinfl if seat is not None else "",
            })
        return Response({"schedule": schedule.pk, "count": len(results), "results": results})


class FaceIdBookSerializer(serializers.Serializer):
    schedule = serializers.IntegerField()
    pinfl = serializers.CharField(max_length=20)
    region_dtm_id = serializers.IntegerField()
    zone_number = serializers.IntegerField()
    computer_number = serializers.IntegerField(min_value=1)


class FaceIdBookView(FaceIdBaseView):
    """
    Nomzodni kompyuterga bron qiladi (Face ID'dan o'tgach).

    IDEMPOTENT: xuddi shu nomzod xuddi shu joyga qayta yuborilsa (FaceID
    Celery'da qayta uradi) javob o'sha bron. Boshqa joyda bo'lsa —
    KO'CHIRISH, lekin talabgor imtihonda bo'lsa `seat_in_use` (409).
    """

    def post(self, request):
        serializer = FaceIdBookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        schedule = _open_schedule(data["schedule"])

        computer = (
            Computer.objects.alive()
            .select_related("zone__region")
            .filter(
                zone__deleted_at__isnull=True,
                zone__region__dtm_id=data["region_dtm_id"],
                zone__number=data["zone_number"],
                number=data["computer_number"],
            )
            .first()
        )
        if computer is None:
            raise SeatUnavailable(
                "Kompyuter topilmadi: viloyat {}, bino {}, №{}".format(
                    data["region_dtm_id"], data["zone_number"], data["computer_number"]
                )
            )

        booking, previous = bookings.assign(
            schedule, data["pinfl"], computer=computer, user=request.user
        )
        moved = previous is not None and previous != booking.computer_id
        if previous != booking.computer_id:
            # Takroriy (idempotent) chaqiruv auditni to'ldirmaydi.
            record_audit(
                actor=request.user,
                action="update",
                object_type="ComputerBooking",
                object_id=booking.pk,
                meta={
                    "action": "move" if moved else "assign",
                    "by": "faceid",
                    "pinfl": mask_pinfl(booking.pinfl),
                    "computer": booking.computer_id,
                    "computer_from": previous if moved else None,
                    "schedule": schedule.pk,
                },
                request=request,
            )
        return Response({
            "booking_id": booking.pk,
            "schedule": schedule.pk,
            "pinfl": booking.pinfl,
            "moved_from": previous if moved else None,
            "seat": bookings.computer_payload(booking.computer),
        })

