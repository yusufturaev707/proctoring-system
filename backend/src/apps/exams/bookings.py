"""
Kompyuter bronlari: test sessiyasida kim qaysi kompyuterda o'tiradi.

Uch iste'molchi va ular BITTA mantiqdan foydalanadi:

    panel (React)       - joylarni yig'ish, biriktirish, ko'chirish;
    tashqi tizim (API)  - talabgorlarni ommaviy biriktirish;
    client (JSHSHIR)    - talabgor AYNAN SHU kompyuterdami?

Qoida ikki joyda yashasa (masalan panel "bo'sh" deb ko'rsatgan joyga
API "band" deb javob bersa) administrator qaysi biriga ishonishni
bilmasdi — shuning uchun hammasi shu modulda.

IKKI REJIM — imtihon profilida (`Setting.is_booking`):

    bron (True)             - talabgor OLDINDAN biriktirilgan kompyuterda.
                              Bron sessiya darajasida yoqiladi: birorta
                              ham talabgor biriktirilmagan bo'lsa JSHSHIR
                              tekshiruvi bronga qaramaydi
                              (`bookings_enforced`) - `ExamSchedule` dagi
                              "jadval tuzilmagan = tekshiruv o'chiq"
                              qoidasi bilan bir xil.
                              `REQUIRE_COMPUTER_BOOKING=true` bu
                              yumshoqlikni o'chiradi;
    erkin joylashuv (False) - talabgor sessiyaga KIRITILGAN (joyi
                              yig'ilgan) istalgan bo'sh ishchi kompyuterda.
                              Joy `proctoring/start/` da o'sha kompyuterga
                              avtomatik yoziladi (`claim_for_session`) va
                              shundan keyin hammasi bron rejimidagidek:
                              o'sha stolga bog'langan, bo'shatish
                              (`release_after_session`) bir xil.

Erkin rejim bron rejimining USTIGA qurilgan, uning o'rnini bosmaydi:
administrator oldindan biriktirgan talabgor u yerda ham o'z joyiga
boradi, biriktirilgan joyni esa boshqa talabgor egallay olmaydi.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.common.exceptions import (
    CandidateAlreadyFinished,
    ComputerBusy,
    ComputerNotInSchedule,
    ComputerOutOfService,
    DomainError,
    ExamScheduleMissing,
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


#: Bitta so'rovda qo'shiladigan/olinadigan eng ko'p kompyuter (har biri
#: alohida). Bino ~500 o'rinli; `SEATS_LIMIT` (2000) bilan bir xil chegara.
SESSION_COMPUTERS_LIMIT = 2000

#: Joyni sessiyadan olib bo'lmaslik sabablari — panel ularni matn bilan
#: ko'rsatadi va kompyuterni "qulflangan" deb chizadi.
LOCK_BOOKED = "booked"
LOCK_USED = "used"
LOCK_IN_EXAM = "in_exam"


def _open_sessions_by_computer(schedule: ExamSchedule, computer_ids) -> set:
    """Shu sessiyada OCHIQ imtihon ketayotgan kompyuterlar (ID to'plami)."""
    from apps.proctoring.models import ExamSession

    return set(
        ExamSession.objects.filter(schedule=schedule, computer_id__in=list(computer_ids))
        .exclude(status__in=ExamSession.TERMINAL_STATUSES)
        .values_list("computer_id", flat=True)
    )


def _seat_lock(booking: ComputerBooking, open_computers: set) -> str:
    """
    Joyni sessiyadan OLIB BO'LMASLIK sababi yoki "".

    `used` (talabgor shu joyda yakunlagan) ham to'siq: qator kim qayerda
    o'tirganini bayonnomada isbotlaydi va `finished_count`
    `bookings_enforced` ga kiradi — qator o'chsa oxirgi talabgorlardan
    keyin bron tekshiruvi jimgina o'chishi mumkin edi. Ishlamaydigan
    mashina uchun to'g'ri yo'l — «buzilgan» belgisi.

    `in_exam` — erkin rejimda joy start'gacha band EMAS, lekin stolda
    allaqachon FaceID'dan o'tgan talabgor o'tirishi mumkin: qator
    o'chsa uning `proctoring/start/` i `computer_not_in_schedule` olardi.
    """
    if booking.is_booked:
        return LOCK_BOOKED
    if booking.computer_id in open_computers:
        return LOCK_IN_EXAM
    if booking.finished_count > 0:
        return LOCK_USED
    return ""


def zone_computers(schedule: ExamSchedule, zone_id, *, region_id=None) -> dict:
    """
    Bino kompyuterlari va har birining SHU sessiyadagi holati.

    Panelning «Kompyuterlarni biriktirish» oynasi uchun: chapda —
    sessiyaga hali kiritilmagan ishchi (`Computer.is_active`)
    kompyuterlar, o'ngda — kiritilganlar. Doira `schedule_computers`
    bilan BITTA qoida: boshqa binodagi, hisobdan chiqarilgan yoki boshqa
    viloyatdagi mashina ro'yxatga umuman tushmaydi.

    Sessiyada turgan, lekin endi doiradan tashqaridagi joylar (mashina
    hisobdan chiqarilgan) ham qaytariladi (`decommissioned`) — aks holda
    ular hech qayerda ko'rinmay, xaritada "arvoh" bo'lib qolardi.
    """
    found = list(
        schedule_computers(schedule, region_id=region_id, zone_id=zone_id)
        .order_by(F("number").asc(nulls_last=True), "inventory_code")[: SESSION_COMPUTERS_LIMIT + 1]
    )
    computers = {computer.pk: computer for computer in found[:SESSION_COMPUTERS_LIMIT]}
    seats_qs = ComputerBooking.objects.filter(
        schedule=schedule, computer__zone_id=zone_id
    ).select_related("computer__zone__region")
    if region_id:
        seats_qs = seats_qs.filter(computer__zone__region_id=region_id)
    seats = {seat.computer_id: seat for seat in seats_qs}
    open_computers = _open_sessions_by_computer(
        schedule, [pk for pk, seat in seats.items() if not seat.is_booked]
    )

    rows = []
    for pk in [*computers, *(pk for pk in seats if pk not in computers)]:
        seat = seats.get(pk)
        computer = computers.get(pk) or seat.computer
        rows.append({
            "computer": pk,
            "number": computer.number,
            "label": computer.label,
            "inventory_code": computer.inventory_code,
            "decommissioned": pk not in computers,
            "seat": seat.pk if seat else None,
            "seat_active": seat.is_active if seat else None,
            "lock": _seat_lock(seat, open_computers) if seat else "",
        })
    return {"results": rows, "truncated": len(found) > SESSION_COMPUTERS_LIMIT}


@transaction.atomic
def update_session_computers(
    schedule: ExamSchedule, zone_id, *, add=(), remove=(), region_id=None
) -> dict:
    """
    Bino kompyuterlarini sessiyaga QO'LDA kiritadi va chiqaradi.

    `generate_seats` dan farqi: u binoning HAMMA kompyuterini qo'shadi,
    bu esa administrator tanlaganlarini. Zalda zaxira yoki boshqa
    imtihonga ajratilgan mashinalar bo'ladi va erkin joylashuvda
    sessiyaga kiritilgan har stol talabgor qabul qiladi.

    Har kompyuter ALOHIDA baholanadi: doiradan tashqarisi va qulflangan
    joy (`_seat_lock`) `skipped` ga tushadi, qolganlari bajariladi —
    bitta band joy 40 ta to'g'ri tanlovni bekor qilmasligi kerak.
    """
    if not schedule.is_active or schedule.deleted_at is not None:
        raise SeatUnavailable("Test sessiyasi faol emas")

    add_ids = {int(pk) for pk in add}
    remove_ids = {int(pk) for pk in remove} - add_ids
    skipped = []

    allowed = set(
        schedule_computers(schedule, region_id=region_id, zone_id=zone_id)
        .filter(pk__in=add_ids)
        .values_list("pk", flat=True)
    )
    for pk in sorted(add_ids - allowed):
        skipped.append({"computer": pk, "reason": "out_of_scope",
                        "message": "Kompyuter bu binoda yoki sessiya doirasida emas"})
    before = ComputerBooking.objects.filter(schedule=schedule, computer_id__in=allowed).count()
    ComputerBooking.objects.bulk_create(
        [ComputerBooking(schedule=schedule, computer_id=pk) for pk in sorted(allowed)],
        ignore_conflicts=True,
        batch_size=500,
    )
    added = len(allowed) - before

    removed = 0
    if remove_ids:
        # Qulf: parallel `assign` yoki `claim_for_session` shu lahzada
        # joyni band qilsa, o'chirish band qatorni olib ketmasligi kerak.
        queryset = ComputerBooking.objects.filter(
            schedule=schedule, computer_id__in=remove_ids, computer__zone_id=zone_id
        )
        if region_id:
            queryset = queryset.filter(computer__zone__region_id=region_id)
        rows = list(queryset.select_for_update(of=("self",)).select_related("computer"))
        open_computers = _open_sessions_by_computer(schedule, [row.computer_id for row in rows])
        deletable = []
        for row in rows:
            lock = _seat_lock(row, open_computers)
            if lock:
                skipped.append({"computer": row.computer_id, "reason": lock,
                                "message": "«{}»: {}".format(row.computer.label, LOCK_MESSAGES[lock])})
            else:
                deletable.append(row.pk)
        removed = ComputerBooking.objects.filter(pk__in=deletable).delete()[0]

    return {"added": added, "removed": removed, "skipped": skipped}


LOCK_MESSAGES = {
    LOCK_BOOKED: "talabgor biriktirilgan — avval bo'shating yoki ko'chiring",
    LOCK_USED: "bu joyda talabgor imtihon topshirgan — joy tarixi saqlanadi, "
               "ishlatmaslik uchun «buzilgan» deb belgilang",
    LOCK_IN_EXAM: "kompyuterda imtihon ketmoqda",
}


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
    # Joylar faqat doirada BIRORTA HAM joy bo'lmasa yig'iladi (sessiyani
    # hech kim tuzmagan — tashqi tizim to'g'ridan-to'g'ri biriktiryapti).
    # Ilgari har chaqiruvda yig'ilardi va administrator QO'LDA tuzgan
    # sessiyaga (`update_session_computers`) ataylab qoldirilgan zaxira
    # mashinalarni ham qaytarib qo'shardi.
    scope = ComputerBooking.objects.filter(schedule=schedule)
    if zone_id:
        scope = scope.filter(computer__zone_id=zone_id)
    if region_id:
        scope = scope.filter(computer__zone__region_id=region_id)
    if not scope.exists():
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

    UUID bor client - (UUID, MAC) juftligi, qoida `devices.services.
    find_computer_by_identity` da (handshake bilan BITTA). UUID mos, MAC
    boshqa mashina "shu stol" EMAS: UUID bir partiyadagi platalarda
    takrorlanadi va u qo'shni stolning mashinasi bo'lishi mumkin.

    UUID yubormaydigan ESKI client - avvalgidek MAC bo'yicha.
    """
    from apps.devices import services as device_services

    if normalize_machine_uuid(machine_uuid):
        return device_services.find_computer_by_identity(zone_id, machine_uuid, mac_address)
    mac = normalize_mac(mac_address)
    if not mac:
        return None
    return (
        Computer.objects.alive()
        .select_related("zone__region")
        .filter(zone_id=zone_id)
        .filter(Q(mac_address__iexact=mac) | Q(mac_address__iexact=mac.replace(":", "-")))
        .first()
    )


def _machine_here(bound, zone_id, *, machine_uuid: str = "", mac_address: str = ""):
    """
    Client ishlab turgan kompyuter yozuvi yoki `None` (tanilmadi).

    Client juftlik (yoki eski client MAC) yuborgan bo'lsa — jismoniy
    mashina, FAQAT BINO ICHIDA (`devices.verify_machine` dagi bilan bir
    xil savol: "shu mashina shu binoda bormi?"). Topilmasa qurilma
    biriktiruviga tushiladi, lekin UUID yuborilgan bo'lsa EMAS: juftlik
    bo'yicha tanilmagan mashina (masalan UUID mos, MAC boshqa)
    biriktiruv orqali ham "shu stol" bo'lib qolmaydi — aks holda qo'shni
    stolning bir xil UUID'li mashinasi o'tib ketardi.
    """
    if not (normalize_machine_uuid(machine_uuid) or normalize_mac(mac_address)):
        return bound
    physical = (
        _physical_computer(zone_id, machine_uuid=machine_uuid, mac_address=mac_address)
        if zone_id
        else None
    )
    if physical is not None:
        return physical
    return None if normalize_machine_uuid(machine_uuid) else bound


def _binding_mismatch(seat: dict, bound) -> DomainError:
    """Talabgor to'g'ri stolda, lekin dastur boshqa kompyuterga biriktirilgan."""
    error = DomainError(
        "Talabgor to'g'ri kompyuterda ({}), lekin dastur «{}» kompyuteriga "
        "biriktirilgan — administrator qurilmani qayta biriktirishi kerak".format(
            seat["label"], bound.label
        ),
        code="device_binding_mismatch",
        extra={"seat": seat, "current": computer_payload(bound)},
    )
    error.status_code = 409
    return error


def resolve_candidate_seat(
    *, schedule: ExamSchedule | None, pinfl: str, device=None,
    machine_uuid: str = "", mac_address: str = "", booking_required: bool = True,
) -> dict | None:
    """
    Talabgor to'g'ri kompyuterdami. `None` — joy bu sessiyada yuritilmaydi.

    `booking_required` — imtihon profilidagi `Setting.is_booking`.
    Talabgorning broni bo'lsa ikkala rejimda BIR XIL qoida (pastda);
    bronsiz talabgor bron rejimida rad etiladi, erkin rejimda esa
    o'tirgan stoli tekshiriladi (`_free_seat`).

    "BU MASHINA" QANDAY ANIQLANADI. Client yuborgan (Machine UUID, MAC)
    juftligi — jismoniy mashina (talabgor aynan qaysi stolda o'tiribdi;
    eski client'da MAC); qurilmaning `Computer` biriktiruvi esa sessiya
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
    if schedule is None:
        # Jadval tuzilmagan (`REQUIRE_EXAM_SCHEDULE=false`) — bron ham, joy
        # ham test sessiyasiga bog'langan, ya'ni solishtiradigan narsa yo'q.
        # Ilgari bu HAR DOIM "tekshiruv o'chiq" edi va `REQUIRE_COMPUTER_BOOKING
        # =true` ham jimgina chetlab o'tilardi: jadvalsiz imtihonga talabgor
        # istalgan stoldan kirardi. Endi faqat ikkala qoida yumshoq bo'lsa
        # (bron rejimi, `REQUIRE_COMPUTER_BOOKING=false`) o'tkaziladi;
        # erkin joylashuv esa sessiyaning joylarisiz umuman ishlay olmaydi.
        if booking_required and not settings.PROCTORING.get("REQUIRE_COMPUTER_BOOKING"):
            return None
        raise ExamScheduleMissing()
    if booking_required and not bookings_enforced(schedule):
        return None

    booking = (
        ComputerBooking.objects.select_related("computer__zone__region")
        .filter(schedule=schedule, pinfl=pinfl, is_booked=True)
        .first()
    )
    if booking is None:
        if booking_required:
            raise SeatNotBooked()
        return _free_seat(
            schedule=schedule, pinfl=pinfl, device=device,
            machine_uuid=machine_uuid, mac_address=mac_address,
        )

    seat = computer_payload(booking.computer)
    if not booking.is_active:
        raise SeatOutOfService(extra={"seat": seat})

    bound = device.computer if device is not None else None
    # Bino — qurilmaniki; qurilma bo'lmasa (`REQUIRE_DEVICE_ID=false`) —
    # talabgor joyiniki: boshqa binodagi mashina bu joy bo'la olmaydi,
    # uni "bu mashina" deb ko'rsatish esa operatorga begona binoning
    # kompyuterini aytardi.
    here = _machine_here(
        bound,
        bound.zone_id if bound is not None else booking.computer.zone_id,
        machine_uuid=machine_uuid, mac_address=mac_address,
    )

    if here is None or here.pk != booking.computer_id:
        current = computer_payload(here)
        message = "Talabgor {} kompyuteriga biriktirilgan".format(_where(seat))
        if current is not None:
            message += ". Bu mashina — «{}»".format(current["label"])
        else:
            message += ". Bu mashina (Machine UUID va MAC) binoda ro'yxatda yo'q"
        raise WrongComputer(message, extra={"seat": seat, "current": current})

    if bound is not None and bound.pk != booking.computer_id:
        raise _binding_mismatch(seat, bound)
    return seat


def candidate_finished_here(schedule: ExamSchedule, pinfl: str) -> bool:
    """
    Talabgorning shu sessiyadagi joyi YAKUN bilan bo'shatilganmi.

    Iz sessiyada (`meta.seat_release`) — bron qatorida emas: bo'shagan
    joy darhol keyingi talabgorga o'tadi va qatorda oldingi egasining
    JSHSHIR'i qolmaydi.
    """
    from apps.proctoring.models import ExamSession

    return ExamSession.objects.filter(
        schedule_id=schedule.pk, pinfl=pinfl, meta__has_key="seat_release"
    ).exists()


def _free_seat(
    *, schedule: ExamSchedule, pinfl: str, device=None,
    machine_uuid: str = "", mac_address: str = "",
) -> dict:
    """
    Erkin joylashuv: bronsiz talabgor O'TIRGAN stol yaroqlimi.

    Qaytgan joy `auto_assign: True` belgisi bilan — u hali BAND
    QILINMAGAN. Band qilish `proctoring/start/` da (`claim_for_session`):
    FaceID'dan o'tolmagan yoki kamera darvozasida qolgan talabgor stolni
    egallab qolmasligi kerak — aks holda shu stoldagi keyingi talabgor
    "band" javobini olardi. Belgi sessiyaga muzlatiladi (`meta.seat`) va
    start AYNAN shunga qaraydi: profil oraliqda o'zgarsa ham qaror bir
    xil qoladi.

    Tekshiruv TARTIBI operatorning keyingi qadami bo'yicha: avval
    talabgorning o'zi (yakunlagan bo'lsa hech qaysi stol yordam
    bermaydi), keyin stol (boshqa stolga o'tkazish), oxirida qurilma
    biriktiruvi (administrator).
    """
    if candidate_finished_here(schedule, pinfl):
        raise CandidateAlreadyFinished()

    bound = device.computer if device is not None else None
    zone_id = bound.zone_id if bound is not None else schedule.zone_id
    here = _machine_here(bound, zone_id, machine_uuid=machine_uuid, mac_address=mac_address)
    if here is None:
        raise ComputerNotInSchedule(
            "Bu mashina (Machine UUID va MAC) binoda ro'yxatda yo'q",
            extra={"current": None},
        )

    seat = computer_payload(here)
    row = (
        ComputerBooking.objects.filter(schedule=schedule, computer=here)
        .only("pk", "is_active", "is_booked", "pinfl")
        .first()
    )
    # "BAZADA BOR" yetmaydi — stol SESSIYAGA KIRITILGAN bo'lishi shart
    # (joyi yig'ilgan, `generate_seats`): administrator qaysi stollarda
    # imtihon o'tishini o'zi belgilaydi. Hisobdan chiqarilgan mashina
    # ham shu yerda to'xtaydi (avval yig'ilgan joyi qolgan bo'lsa ham).
    if row is None or here.deleted_at is not None or not here.is_active:
        raise ComputerNotInSchedule(
            "«{}» kompyuteri bu test sessiyasiga kiritilmagan".format(seat["label"]),
            extra={"current": seat},
        )
    if not row.is_active:
        raise ComputerOutOfService(
            "«{}» kompyuteri bu sessiyada buzilgan deb belgilangan".format(seat["label"]),
            extra={"current": seat},
        )
    if row.is_booked:
        # Bronda turgan joy egasiniki: oldindan biriktirilgan talabgor
        # hali kelmagan, egasi imtihonda yoki uzilib qaytadi.
        raise ComputerBusy(
            "«{}» kompyuteri boshqa talabgorga biriktirilgan ({})".format(
                seat["label"], mask_pinfl(row.pinfl)
            ),
            extra={"current": seat},
        )
    if bound is not None and bound.pk != here.pk:
        raise _binding_mismatch(seat, bound)
    return {**seat, "auto_assign": True}


@transaction.atomic
def claim_for_session(session) -> ComputerBooking | None:
    """
    Erkin joylashuv: talabgor o'tirgan kompyuterni UNGA yozadi.

    `proctoring/start/` dan — kamera darvozasidan o'tgach, BITTA
    tranzaksiyada kuzatuv bilan (joy olinmasa kuzatuv ham boshlanmaydi
    va aksincha). Shundan keyin talabgor bron rejimidagidek shu stolga
    bog'langan: bo'shatish — «Yakunlash» yoki chetlashtirish
    (`release_after_session`), qolganlarida band qoladi.

    `None` — sessiya erkin joylashuvdan emas (bron rejimi yoki jadvalsiz).

    TAKRORIY CHAQIRUV XAVFSIZ: kamera qayta tekshirilib start yana
    kelsa, joy allaqachon shu talabgorniki — o'sha qaytadi.

    JSHSHIR tekshiruvidan beri vaziyat o'zgargan bo'lishi mumkin
    (administrator stolni buzilgan deb belgiladi, joyni boshqaga berdi
    yoki talabgorni boshqa joyga biriktirdi) — o'shanda rad etiladi va
    sessiya tirik qoladi (kamera rad javobidagi kabi).
    """
    seat = (session.meta or {}).get("seat") or {}
    if not seat.get("auto_assign") or not session.schedule_id or not session.pinfl:
        return None
    computer_id = seat.get("computer_id")
    here = {key: value for key, value in seat.items() if key != "auto_assign"}

    existing = (
        ComputerBooking.objects.select_for_update(of=("self",))
        .select_related("computer__zone__region")
        .filter(schedule_id=session.schedule_id, pinfl=session.pinfl)
        .first()
    )
    if existing is not None:
        if existing.computer_id == computer_id:
            return existing
        target = computer_payload(existing.computer)
        raise WrongComputer(
            "Talabgor {} kompyuteriga biriktirilgan".format(_where(target)),
            extra={"seat": target, "current": here},
        )

    target = (
        ComputerBooking.objects.select_for_update(of=("self",))
        .select_related("computer__zone__region")
        .filter(schedule_id=session.schedule_id, computer_id=computer_id)
        .first()
    )
    label = seat.get("label") or "Kompyuter"
    if target is None:
        raise ComputerNotInSchedule(
            "«{}» kompyuteri test sessiyasidan chiqarilgan".format(label),
            extra={"current": here},
        )
    if not target.is_active:
        raise ComputerOutOfService(
            "«{}» kompyuteri bu sessiyada buzilgan deb belgilangan".format(label),
            extra={"current": here},
        )
    if target.is_booked:
        raise ComputerBusy(
            "«{}» kompyuteri boshqa talabgorga biriktirilgan ({})".format(
                label, mask_pinfl(target.pinfl)
            ),
            extra={"current": here},
        )

    target.pinfl = session.pinfl
    target.is_booked = True
    target.booked_at = timezone.now()
    # Biriktirgan xodim yo'q — tizimning o'zi (auditda `by: session_start`).
    target.booked_by = None
    try:
        # Ichki savepoint: parallel so'rov shu JSHSHIR'ni bir lahza oldin
        # boshqa joyga yozgan bo'lsa (`unique_booking_schedule_pinfl`)
        # tashqi tranzaksiya buzilmasdan aniq javob qaytadi.
        with transaction.atomic():
            target.save(
                update_fields=["pinfl", "is_booked", "booked_at", "booked_by", "updated_at"]
            )
    except IntegrityError as exc:
        raise ComputerBusy(
            "Joy parallel so'rovda band qilindi — JSHSHIR'ni qaytadan kiriting",
            extra={"current": here},
        ) from exc
    return target
