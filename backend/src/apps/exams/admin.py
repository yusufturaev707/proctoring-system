from django.contrib import admin, messages

from apps.common.exceptions import DomainError
from apps.exams import services as exam_services
from apps.exams import bookings
from apps.exams.models import ComputerBooking, Exam, ExamSchedule, ExamType


@admin.register(ExamType)
class ExamTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "is_active")
    list_filter = ("is_active",)
    # `ExamAdmin.autocomplete_fields` shu ro'yxatga tayanadi — usiz
    # Django admin tekshiruvda (`admin.E040`) xato beradi.
    search_fields = ("name", "key")


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = (
        "name", "exam_type", "key", "external_code", "duration_minutes",
        "site_header_masked", "is_active",
    )
    list_filter = ("is_active", "exam_type")
    search_fields = ("name", "key", "external_code")
    # Shifrlangan ustun formada KO'RSATILMAYDI (`CameraAdmin` dagi bilan
    # bir xil sabab): unga ochiq matn yozib qo'yilsa, deshifrlash
    # `None` qaytaradi va sarlavha jimgina yo'qoladi. Qiymat admin
    # panel API'si orqali (`site_header` maydoni) qo'yiladi.
    exclude = ("site_header_encrypted",)

    @admin.display(description="Platforma sarlavhasi")
    def site_header_masked(self, obj) -> str:
        return exam_services.mask_site_header(obj) or "—"
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
    # `ComputerBookingAdmin.autocomplete_fields` shu qidiruvga tayanadi.
    search_fields = ("exam__name",)
    actions = ("generate_seats",)

    @admin.action(description="Kompyuter joylarini yaratish (bron uchun)")
    def generate_seats(self, request, queryset):
        """Panel `generate/` amali bilan BIR XIL servis — takroriy bosish xavfsiz."""
        created = total = 0
        for schedule in queryset:
            result = bookings.generate_seats(schedule)
            created += result["created"]
            total += result["total"]
        self.message_user(
            request,
            "{} ta yangi joy yaratildi (doiradagi kompyuterlar: {})".format(created, total),
            messages.SUCCESS,
        )


@admin.register(ComputerBooking)
class ComputerBookingAdmin(admin.ModelAdmin):
    """
    Zaxira boshqaruv — asosiy ish paneldagi «Kompyuter bronlari» sahifasida.

    Biriktirish ham servis orqali (`bookings.assign`): formada JSHSHIR
    yozilsa band joy, buzilgan kompyuter va sessiya doirasi xuddi API
    dagi kabi tekshiriladi. To'g'ridan-to'g'ri `save()` bu
    tekshiruvlarni chetlab o'tardi.
    """

    list_display = (
        "computer", "zone_name", "schedule", "is_active", "is_booked",
        "masked_pinfl", "booked_at",
    )
    list_filter = ("is_active", "is_booked", "schedule__exam_date", "computer__zone__region")
    search_fields = ("pinfl", "computer__inventory_code", "computer__number")
    list_select_related = ("schedule__exam", "computer__zone__region")
    autocomplete_fields = ("schedule", "computer")
    readonly_fields = ("is_booked", "booked_at", "booked_by", "created_at", "updated_at")
    fields = (
        "schedule", "computer", "is_active", "pinfl",
        "is_booked", "booked_at", "booked_by", "created_at", "updated_at",
    )
    actions = ("release_seats", "mark_broken", "mark_working")

    @admin.display(description="Bino", ordering="computer__zone__name")
    def zone_name(self, obj):
        return obj.computer.zone.name

    def save_model(self, request, obj, form, change):
        pinfl = (form.cleaned_data.get("pinfl") or "").strip()
        # Avval joyning o'zi (JSHSHIRsiz) saqlanadi, keyin biriktirish
        # servis orqali — ikkalasi bitta formada kelgani uchun.
        previous = ComputerBooking.objects.filter(pk=obj.pk).values_list("pinfl", flat=True).first()
        obj.pinfl = previous or ""
        obj.is_booked = bool(obj.pinfl)
        super().save_model(request, obj, form, change)
        if pinfl and pinfl != (previous or ""):
            try:
                bookings.assign(obj.schedule, pinfl, computer=obj.computer, user=request.user)
            except DomainError as exc:
                # Joy saqlandi, biriktirish esa rad etildi (band, buzilgan,
                # noto'g'ri JSHSHIR) — sabab ekranda, 500 sahifasi emas.
                self.message_user(
                    request, "Talabgor biriktirilmadi: {}".format(exc.detail), messages.ERROR
                )
        elif not pinfl and previous:
            try:
                bookings.release(obj)
            except DomainError as exc:
                # Talabgor imtihonda (`SeatInUse`) — joy band qoladi.
                self.message_user(
                    request, "Joy bo'shatilmadi: {}".format(exc.detail), messages.ERROR
                )

    @admin.action(description="Tanlanganlarni bo'shatish")
    def release_seats(self, request, queryset):
        released = skipped = 0
        for booking in queryset.filter(is_booked=True):
            try:
                bookings.release(booking)
            except DomainError:
                # Imtihondagi talabgorning joyi — faqat sessiya orqali.
                skipped += 1
                continue
            released += 1
        self.message_user(
            request, "{} ta joy bo'shatildi".format(released), messages.SUCCESS
        )
        if skipped:
            self.message_user(
                request,
                "{} ta joyda talabgor imtihonda — ular bo'shatilmadi "
                "(avval sessiyani chetlashtiring)".format(skipped),
                messages.WARNING,
            )

    @admin.action(description="Buzilgan deb belgilash")
    def mark_broken(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, "{} ta joy buzilgan deb belgilandi".format(count), messages.WARNING)

    @admin.action(description="Ishchi holatga qaytarish")
    def mark_working(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, "{} ta joy ishchi holatga qaytdi".format(count), messages.SUCCESS)
