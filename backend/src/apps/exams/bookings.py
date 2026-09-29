"""
Kompyuter bronlari: test sessiyasida kim qaysi kompyuterda o'tiradi.

Uch iste'molchi va ular BITTA mantiqdan foydalanadi:

    panel (React)       - joylarni yig'ish, biriktirish, ko'chirish;
    tashqi tizim (API)  - talabgorlarni ommaviy biriktirish;
    client (JSHSHIR)    - talabgor AYNAN SHU kompyuterdami?

Qoida ikki joyda yashasa (masalan panel "bo'sh" deb ko'rsatgan joyga
API "band" deb javob bersa) administrator qaysi biriga ishonishni
bilmasdi — shuning uchun hammasi shu modulda.

BRON IXTIYORIY va u sessiya darajasida yoqiladi: test sessiyasida
birorta ham talabgor biriktirilmagan bo'lsa JSHSHIR tekshiruvi bronga
qaramaydi (`bookings_enforced`). Bu `ExamSchedule` dagi "jadval
tuzilmagan = tekshiruv o'chirilgan" qoidasi bilan bir xil: yangi
imkoniyat mavjud o'rnatishlarni to'xtatib qo'ymasligi kerak.
`REQUIRE_COMPUTER_BOOKING=true` bu yumshoqlikni o'chiradi.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.common.exceptions import (
    DomainError,
    MachineMacMismatch,
    SeatInUse,
    SeatNotBooked,
    SeatOutOfService,
    SeatUnavailable,
    WrongComputer,
)
from apps.common.utils.crypto import mask_pinfl, normalize_pinfl
from apps.common.utils.validators import normalize_mac, normalize_machine_uuid, validate_pinfl
from apps.devices.models import Computer
from apps.exams.models import ComputerBooking, ExamSchedule

logger = logging.getLogger(__name__)

#: Bitta ommaviy so'rovdagi eng ko'p talabgor. Bino ~500 o'rinli;
#: chegara bitta so'rov butun serverni daqiqalab band qilmasligi uchun.
BULK_ASSIGN_LIMIT = 1000


# --------------------------------------------------------------------------
# Taqdimot — client ham, panel ham shu shaklni oladi
# --------------------------------------------------------------------------
def computer_payload(computer: Computer | None) -> dict | None:
    """
    Kompyuter haqida odam o'qiydigan ma'lumot.

    MAC YO'Q va bu ataylab: bu javob JSHSHIR tekshiruvida ham qaytadi
    va talabgor ekran oldida turadi. Operatorga "qaysi stol" kerak,
    mashinaning tarmoq identifikatori emas.
    """
    if computer is None:
        return None
    zone = computer.zone
    return {
        "computer_id": computer.pk,
        "number": computer.number,
        "label": computer.label,
        "inventory_code": computer.inventory_code,
        "zone_id": zone.pk if zone else None,
        "zone_name": zone.name if zone else "",
        "region_name": zone.region.name if zone and zone.region_id else "",
    }


def _where(seat: dict) -> str:
    """"№12 · INV-001 («1-bino», Toshkent sh.)" — xabar matni uchun."""
    place = ", ".join(part for part in (seat.get("zone_name"), seat.get("region_name")) if part)
    return "«{}»{}".format(seat["label"], " ({})".format(place) if place else "")


# --------------------------------------------------------------------------
# Doira: sessiyaga qaysi kompyuterlar tegishli
# --------------------------------------------------------------------------
def schedule_computers(schedule: ExamSchedule, *, region_id=None, zone_id=None):
    """
    Test sessiyasida ishlatilishi mumkin bo'lgan kompyuterlar.

    Bino jadvali — faqat o'sha bino; umumiy jadval (`zone=NULL`) —
    BARCHA viloyatlarning barcha binolari. Hisobdan chiqarilgan
    (`Computer.is_active=False`) va o'chirilgan mashinalar kirmaydi:
    ular "buzilgan" emas, ular umuman yo'q.

    `region_id` — viloyat administratorining doirasi. Umumiy jadvalda
    u boshqa viloyatning kompyuterlariga joy yarata olmasligi kerak.
    """
    queryset = Computer.objects.alive().filter(is_active=True).select_related("zone__region")
    if schedule.zone_id:
        queryset = queryset.filter(zone_id=schedule.zone_id)
    if zone_id:
        queryset = queryset.filter(zone_id=zone_id)
    if region_id:
        queryset = queryset.filter(zone__region_id=region_id)
    return queryset


def _check_scope(schedule: ExamSchedule, computer: Computer, *, region_id=None) -> None:
    if computer.deleted_at is not None or not computer.is_active:
        raise SeatUnavailable(
            "«{}» kompyuteri hisobdan chiqarilgan".format(computer.label)
        )
    if schedule.zone_id and computer.zone_id != schedule.zone_id:
        raise SeatUnavailable(
            "«{}» kompyuteri bu test sessiyasining binosida emas".format(computer.label)
        )
    if region_id and computer.zone.region_id != region_id:
        raise SeatUnavailable("Kompyuter sizning viloyatingizda emas")


def generate_seats(schedule: ExamSchedule, *, region_id=None, zone_id=None) -> dict:
    """
    Sessiya doirasidagi har bir kompyuter uchun bo'sh joy yaratadi.

    Takroriy chaqiruv XAVFSIZ (`ignore_conflicts`): mavjud joylarga,
    ularning bron va "buzilgan" belgisiga tegilmaydi — faqat yangi
    qo'shilgan kompyuterlar uchun joy paydo bo'ladi.
    """
    computers = list(
        schedule_computers(schedule, region_id=region_id, zone_id=zone_id).values_list(
            "pk", flat=True
        )
    )
    before = ComputerBooking.objects.filter(schedule=schedule, computer_id__in=computers).count()
    ComputerBooking.objects.bulk_create(
        [ComputerBooking(schedule=schedule, computer_id=pk) for pk in computers],
        ignore_conflicts=True,
        batch_size=500,
    )
    return {"created": len(computers) - before, "total": len(computers)}


# --------------------------------------------------------------------------
# Biriktirish / bo'shatish
# --------------------------------------------------------------------------
def _clean_pinfl(pinfl: str) -> str:
    value = normalize_pinfl(pinfl)
    try:
        validate_pinfl(value)
    except ValidationError as exc:
        raise DomainError(exc.messages[0], code="invalid_pinfl") from exc
    return value


def _next_free_seat(schedule: ExamSchedule, *, region_id=None, zone_id=None):
    """
    Eng kichik raqamli bo'sh ishchi joy.

    `skip_locked`: tashqi tizim talabgorlarni PARALLEL yuborsa, ikki
    so'rov bitta joyni tanlab, biri `IntegrityError` bilan yiqilardi.
    Band qilingan qator o'tkazib yuboriladi va har so'rov o'z joyini
    oladi.
    """
    generate_seats(schedule, region_id=region_id, zone_id=zone_id)
    queryset = ComputerBooking.objects.filter(
        schedule=schedule,
        is_booked=False,
        is_active=True,
        computer__deleted_at__isnull=True,
        computer__is_active=True,
    )
    if zone_id:
        queryset = queryset.filter(computer__zone_id=zone_id)
    if region_id:
        queryset = queryset.filter(computer__zone__region_id=region_id)
    return (
        queryset.select_for_update(skip_locked=True, of=("self",))
        .order_by(
            "computer__zone_id",
            F("computer__number").asc(nulls_last=True),
            "computer__inventory_code",
        )
        .first()
    )


@transaction.atomic
def assign(
    schedule: ExamSchedule,
    pinfl: str,
    *,
    computer: Computer | None = None,
    zone_id=None,
    region_id=None,
    user=None,
) -> tuple[ComputerBooking, int | None]:
    """
    Talabgorni kompyuterga biriktiradi. Qaytaradi `(bron, oldingi_kompyuter_id)`.

    Ikki rejim:

        `computer` berilgan  - AYNAN shu joyga. Talabgorning shu
                               sessiyada boshqa joyi bo'lsa, u
                               BO'SHATILADI (ko'chirish): kompyuter
                               buzilganda administratorning asosiy
                               ishi aynan shu;
        `computer` yo'q      - avtomatik: binodagi eng kichik raqamli
                               bo'sh ishchi joy. Talabgorning joyi
                               allaqachon bo'lsa, o'sha qaytadi —
                               tashqi tizim so'rovni takrorlasa ikkinchi
                               joy band bo'lmasligi kerak.
    """
    pinfl = _clean_pinfl(pinfl)
    if not schedule.is_active or schedule.deleted_at is not None:
        raise SeatUnavailable("Test sessiyasi faol emas")

    existing = (
        ComputerBooking.objects.select_for_update(of=("self",))
        .select_related("computer__zone__region")
        .filter(schedule=schedule, pinfl=pinfl)
        .first()
    )

    if computer is None:
        if existing is not None:
            return existing, existing.computer_id
        target = _next_free_seat(schedule, region_id=region_id, zone_id=zone_id)
        if target is None:
            raise SeatUnavailable("Bu doirada bo'sh ishchi kompyuter qolmadi")
    else:
        _check_scope(schedule, computer, region_id=region_id)
        ComputerBooking.objects.get_or_create(schedule=schedule, computer=computer)
        target = (
            ComputerBooking.objects.select_for_update(of=("self",))
            .get(schedule=schedule, computer=computer)
        )
        if existing is not None and existing.pk == target.pk:
            return existing, existing.computer_id
        if not target.is_active:
            raise SeatUnavailable(
                "«{}» kompyuteri buzilgan deb belgilangan".format(computer.label)
            )
        if target.is_booked:
            raise SeatUnavailable(
                "«{}» kompyuteri band ({})".format(computer.label, mask_pinfl(target.pinfl))
            )

    previous = None
    if existing is not None:
        # Imtihondagi talabgorni KO'CHIRIB bo'lmaydi: u eski stolda
        # o'tiribdi, sessiyasi o'sha kompyuterga yozilgan, eski joy esa
        # bo'shab keyingi talabgorga berilardi — bitta stolda ikki odam.
        _ensure_not_in_exam(existing)
        # AVVAL eskisi bo'shatiladi: `unique_booking_schedule_pinfl`
        # darhol tekshiriladi va tartib teskari bo'lsa yangi joyga
        # yozish cheklovga urilardi.
        previous = existing.computer_id
        _clear(existing)

    target.pinfl = pinfl
    target.is_booked = True
    target.booked_at = timezone.now()
    target.booked_by = user if getattr(user, "pk", None) else None
    target.save(update_fields=["pinfl", "is_booked", "booked_at", "booked_by", "updated_at"])
    return target, previous


def _clear(booking: ComputerBooking) -> None:
    booking.pinfl = ""
    booking.is_booked = False
    booking.booked_at = None
    booking.booked_by = None
    booking.save(update_fields=["pinfl", "is_booked", "booked_at", "booked_by", "updated_at"])


def active_session(booking: ComputerBooking):
    """
    Bron egasining OCHIQ sessiyasi (yakunlanmagan) yoki `None`.

    "Ochiq" — `TERMINAL_STATUSES` dan tashqari hammasi: `ready` (FaceID
    o'tgan, test hali ochilmagan), `in_progress`, `technical_problem`.
    Faqat `in_progress` ga qaralsa, kuzatuv rad etilib FaceID sahifasida
    kutayotgan talabgorning joyi (sessiya tirik — `session_blocked`)
    boshqaga berilib yuborilardi.
    """
    from apps.proctoring.models import ExamSession

    if not booking.is_booked or not booking.pinfl:
        return None
    return (
        ExamSession.objects.filter(schedule_id=booking.schedule_id, pinfl=booking.pinfl)
        .exclude(status__in=ExamSession.TERMINAL_STATUSES)
        .only("pk", "public_id", "status")
        .first()
    )


def _ensure_not_in_exam(booking: ComputerBooking) -> None:
    session = active_session(booking)
    if session is not None:
        raise SeatInUse(extra={"session": str(session.public_id), "status": session.status})


def release(booking: ComputerBooking) -> ComputerBooking:
    """
    Joyni bo'shatadi (panel, Django admin). Kompyuterning "ishchi"
    belgisiga tegilmaydi.

    TALABGOR IMTIHONDA BO'LSA — `SeatInUse`. Qoida SHU YERDA, view'da
    emas: panel, Django admin va tashqi API bitta funksiyani chaqiradi
    va bittasida unutilgan tekshiruv butun qoidani bekor qilardi.
    Imtihondagi talabgorning joyi faqat sessiya orqali bo'shaydi
    (`release_after_session`).
    """
    if booking.is_booked:
        _ensure_not_in_exam(booking)
        _clear(booking)
    return booking


def release_after_session(*, schedule_id, pinfl: str) -> ComputerBooking | None:
    """
    Sessiya yakunlandi — joy keyingi talabgor uchun bo'shaydi.

    IKKI YO'LDAN chaqiriladi va ikkalasi ham ANIQ QAROR:

        «Yakunlash» (client, `completed=true`) -> talabgor testni topshirdi;
        chetlashtirish (panel, administrator)  -> talabgor chiqarildi.

    Qolgan yakunlarda joy ATAYLAB band qoladi:

        expired (client o'ldi, tok)   -> talabgor O'SHA stolga qaytib
                                         qayta kiradi; joy bo'shatilsa
                                         u `seat_not_booked` olardi,
                                         joyi esa boshqaga berilgan
                                         bo'lishi mumkin edi;
        dasturdan chiqish (Ctrl+Q)    -> operator imtihonni yakunlamadi,
                                         talabgor testni topshirmagan;
        shaxs rad etildi (client)     -> operatorning client'dagi amali,
                                         administrator qarori emas.

    `ACTIVE SESSION` TEKSHIRUVI YO'Q: chaqiruvchi sessiyani AYNAN SHU
    tranzaksiyada yakunlagan.

    Joy talabgor bo'yicha topiladi, sessiyaning kompyuteri bo'yicha
    EMAS: administrator imtihon o'rtasida uni ko'chirgan bo'lsa bron
    boshqa kompyuterda turadi va aynan o'sha bo'shashi kerak.

    Bron yo'q (bron yuritilmaydigan sessiya yoki administrator
    allaqachon bo'shatgan) — `None`, xato emas: yakun baribir o'tadi.
    """
    if not schedule_id or not pinfl:
        return None
    booking = (
        ComputerBooking.objects.select_for_update(of=("self",))
        .select_related("computer__zone__region")
        .filter(schedule_id=schedule_id, pinfl=pinfl, is_booked=True)
        .first()
    )
    if booking is None:
        return None
    booking.finished_count = F("finished_count") + 1
    booking.last_finished_at = timezone.now()
    booking.pinfl = ""
    booking.is_booked = False
    booking.booked_at = None
    booking.booked_by = None
    booking.save(
        update_fields=[
            "finished_count", "last_finished_at",
            "pinfl", "is_booked", "booked_at", "booked_by", "updated_at",
        ]
    )
    booking.refresh_from_db(fields=["finished_count"])
    return booking


def bulk_assign(schedule: ExamSchedule, items: list[dict], *, region_id=None, user=None) -> list[dict]:
    """
    Ko'p talabgorni biriktiradi — HAR BIRI ALOHIDA tranzaksiyada.

    Bittasining xatosi (band joy, noto'g'ri JSHSHIR) qolganlarini
    bekor qilmaydi: tashqi tizim 500 talabgordan bittasi uchun butun
    ro'yxatni qaytadan yuborishi kerak bo'lmasligi uchun. Natija har
    bir qator uchun alohida — qaysilari o'tmaganini tizim o'zi ko'radi.
    """
    computers = {
        computer.pk: computer
        for computer in Computer.objects.select_related("zone__region").filter(
            pk__in=[item["computer"] for item in items if item.get("computer")]
        )
    }
    results = []
    for item in items:
        pinfl = normalize_pinfl(item.get("pinfl", ""))
        try:
            computer = None
            if item.get("computer"):
                computer = computers.get(item["computer"])
                if computer is None:
                    raise SeatUnavailable("Kompyuter topilmadi")
            booking, _ = assign(
                schedule, pinfl,
                computer=computer,
                zone_id=item.get("zone"),
                region_id=region_id,
                user=user,
            )
        except DomainError as exc:
            results.append({
                "pinfl": pinfl, "ok": False,
                "code": getattr(exc.detail, "code", None) or exc.default_code,
                "message": str(exc.detail),
            })
            continue
        except IntegrityError:
            # Parallel so'rov shu JSHSHIR'ni yoki shu joyni bir lahza
            # oldin egalladi — bazadagi cheklov ushladi.
            results.append({
                "pinfl": pinfl, "ok": False, "code": "seat_unavailable",
                "message": "Joy yoki JSHSHIR parallel so'rovda band qilindi — qayta yuboring",
            })
            continue
        results.append({"pinfl": pinfl, "ok": True, "seat": computer_payload(booking.computer)})
    return results


# --------------------------------------------------------------------------
# JSHSHIR tekshiruvi (client)
# --------------------------------------------------------------------------
def bookings_enforced(schedule: ExamSchedule | None) -> bool:
    """Shu sessiyada bron qoidasi amal qiladimi (modul izohiga qarang)."""
    if schedule is None:
        return False
    if settings.PROCTORING.get("REQUIRE_COMPUTER_BOOKING"):
        return True
    # `finished_count` HAM hisobga olinadi: yakunlagan talabgorning joyi
    # bo'shaydi (`release_after_session`) va oxirgisi yakunlagach sessiyada
    # birorta band joy qolmaydi. Faqat `is_booked` ga qaralsa, o'sha
    # zahoti tekshiruv o'char va yakunlagan talabgor ham, bronsiz
    # begona ham istalgan stolda qayta kira olardi.
    return ComputerBooking.objects.filter(
        Q(is_booked=True) | Q(finished_count__gt=0), schedule=schedule
    ).exists()


def _physical_computer(zone_id, *, machine_uuid: str = "", mac_address: str = ""):
    """
    Client ishlab turgan JISMONIY mashina - bino ichida.

    Asos - Machine UUID (ona plata). MAC - faqat UUID yubormaydigan eski
    client uchun VA UUID'si hali yozilmagan yozuvlar uchun: UUID berilgan,
    lekin bazada topilmagan bo'lsa MAC'ga tushiladi faqat o'sha yozuvda
    UUID yo'q bo'lsa - aks holda UUID'si BOSHQA mashina MAC'i bo'yicha
    "shu stol" bo'lib qolardi.
    """
    queryset = Computer.objects.alive().select_related("zone__region").filter(zone_id=zone_id)
    uuid_value = normalize_machine_uuid(machine_uuid)
    if uuid_value:
        computer = queryset.filter(machine_uuid=uuid_value).first()
        if computer is not None:
            return computer
    mac = normalize_mac(mac_address)
    if not mac:
        return None
    queryset = queryset.filter(
        Q(mac_address__iexact=mac) | Q(mac_address__iexact=mac.replace(":", "-"))
    )
    if uuid_value:
        queryset = queryset.filter(machine_uuid__isnull=True)
    return queryset.first()


def ensure_machine_mac(*, device=None, zone=None, machine_uuid: str = "", mac_address: str = "") -> None:
    """
    Qat'iy rejimda (`REQUIRE_MACHINE_MAC`) UUID bo'yicha tanilgan
    mashinaning MAC'i yozuvdagiga mos bo'lishi shart.

    Bron qoidasidan MUSTAQIL: savol "talabgor qaysi stolda" emas, "bu
    mashina o'zi aytgan mashinami". Faqat UUID bo'yicha topilgan yozuv
    tekshiriladi - UUID'siz (eski) yozuv MAC bilan TOPILADI, ya'ni u
    yerda MAC ta'rifga ko'ra mos. Qoidaning o'zi `devices.services`
    da (`mac_matches`) - handshake bilan bir xil.
    """
    from apps.devices import services as device_services

    if not device_services.mac_check_required():
        return
    bound = device.computer if device is not None else None
    zone_id = bound.zone_id if bound is not None else getattr(zone, "pk", None)
    if zone_id is None or not normalize_machine_uuid(machine_uuid):
        return
    physical = _physical_computer(zone_id, machine_uuid=machine_uuid)
    if physical is None or device_services.mac_matches(physical, mac_address):
        return
    raise MachineMacMismatch(
        device_services.mac_mismatch_message(physical, mac_address),
        extra={
            "expected_mac": physical.mac_address,
            "reported_mac": normalize_mac(mac_address) or "",
            "computer": computer_payload(physical),
        },
    )


def resolve_candidate_seat(
    *, schedule: ExamSchedule | None, pinfl: str, device=None,
    machine_uuid: str = "", mac_address: str = "",
) -> dict | None:
    """
    Talabgor to'g'ri kompyuterdami. `None` — bron bu sessiyada yuritilmaydi.

    "BU MASHINA" QANDAY ANIQLANADI. Client yuborgan Machine UUID —
    jismoniy mashina (talabgor aynan qaysi stolda o'tiribdi; eski
    client'da MAC); qurilmaning `Computer` biriktiruvi esa sessiya
    QAYSI kompyuterga yoziladi. Odatda ikkalasi bir xil
    (handshake'dagi `verify_machine` shuni tekshiradi). Farq qilsa ikki
    holat bor va ular BOSHQA-BOSHQA:

        UUID boshqa joyniki       -> talabgor noto'g'ri stolda:
                                     `wrong_computer` + qayerga borish;
        UUID to'g'ri, biriktiruv
        boshqa                    -> talabgor to'g'ri stolda, lekin
                                     qurilma obrazi ko'chirilgan:
                                     administrator qayta biriktiradi.

    Ikkinchisini "boshqa kompyuterga boring" deb ko'rsatish operatorni
    talabgorni o'zi turgan stolga yuborishga majbur qilardi.

    Tekshiruv TARTIBI: avval "buzilgan", keyin joylashuv — buzilgan
    joyga talabgorni yuborishdan foyda yo'q.
    """
    if not bookings_enforced(schedule):
        return None

    booking = (
        ComputerBooking.objects.select_related("computer__zone__region")
        .filter(schedule=schedule, pinfl=pinfl, is_booked=True)
        .first()
    )
    if booking is None:
        raise SeatNotBooked()

    seat = computer_payload(booking.computer)
    if not booking.is_active:
        raise SeatOutOfService(extra={"seat": seat})

    bound = device.computer if device is not None else None
    here = bound
    if normalize_machine_uuid(machine_uuid) or normalize_mac(mac_address):
        # FAQAT BINO ICHIDA qidiriladi — `devices.verify_machine` dagi
        # bilan bir xil savol ("shu mashina shu binoda bormi?"). Bino —
        # qurilmaniki; qurilma bo'lmasa (`REQUIRE_DEVICE_ID=false`) —
        # talabgor joyiniki: boshqa binodagi mashina bu joy bo'la
        # olmaydi, uni "bu mashina" deb ko'rsatish esa operatorga begona
        # binoning kompyuterini aytardi.
        zone_id = bound.zone_id if bound is not None else booking.computer.zone_id
        physical = _physical_computer(
            zone_id, machine_uuid=machine_uuid, mac_address=mac_address
        )
        if physical is not None:
            here = physical

    if here is None or here.pk != booking.computer_id:
        current = computer_payload(here)
        message = "Talabgor {} kompyuteriga biriktirilgan".format(_where(seat))
        if current is not None:
            message += ". Bu mashina — «{}»".format(current["label"])
        raise WrongComputer(message, extra={"seat": seat, "current": current})

    if bound is not None and bound.pk != booking.computer_id:
        error = DomainError(
            "Talabgor to'g'ri kompyuterda ({}), lekin dastur «{}» kompyuteriga "
            "biriktirilgan — administrator qurilmani qayta biriktirishi kerak".format(
                seat["label"], bound.label
            ),
            code="device_binding_mismatch",
            extra={"seat": seat, "current": computer_payload(bound)},
        )
        error.status_code = 409
        raise error
    return seat
