"""
Kirish oynalari kesishgan seanslar (bitta imtihon, bitta ko'lam).

Nima uchun kerak:
    Qoida (`exams/schedules.py`) faqat SAQLASHDA ishlaydi — u qo'shilishidan
    oldin tuzilgan seanslar bazada kesishib turgan bo'lishi mumkin. Bunday
    juftlikda `candidate/lookup/` birinchi seansni tanlaydi va 2-smena
    talabgori boshqa smenaga tushadi. Buni imtihon KUNI emas, oldindan bilish
    kerak.

Bino seansi umumiy seans bilan kesishishi xato EMAS (ataylab ustun).

Ishlatish:
    python manage.py audit_schedule_overlaps              # bugundan boshlab
    python manage.py audit_schedule_overlaps --all        # o'tganlari ham
    python manage.py audit_schedule_overlaps --exam 5

HECH NARSA YOZMAYDI.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.exams import schedules
from apps.exams.models import ExamSchedule


class Command(BaseCommand):
    help = "Bitta imtihonda kirish oynalari kesishgan seanslarni ko'rsatadi (faqat o'qiydi)"

    def add_arguments(self, parser):
        parser.add_argument("--exam", type=int, help="Faqat shu imtihon (Exam ID)")
        parser.add_argument("--all", action="store_true", help="Tugagan seanslar ham")

    def handle(self, *args, **options):
        rows = (
            ExamSchedule.objects.filter(is_active=True, deleted_at__isnull=True)
            .select_related("exam", "zone")
            .order_by("exam_id", "starts_at")
        )
        if options.get("exam"):
            rows = rows.filter(exam_id=options["exam"])
        if not options.get("all"):
            rows = rows.filter(ends_at__gte=timezone.now())

        seen = set()
        found = 0
        for schedule in rows:
            other = schedules.overlap_of(schedule)
            if other is None:
                continue
            pair = frozenset((schedule.pk, other.pk))
            if pair in seen:
                continue
            seen.add(pair)
            found += 1
            self.stdout.write(
                "{} · {}: #{} ({}) va #{} ({})".format(
                    schedule.exam.name,
                    schedule.zone.name if schedule.zone_id else "barcha binolar",
                    other.pk, schedules.window_label(other.opens_at, other.ends_at),
                    schedule.pk, schedules.window_label(schedule.opens_at, schedule.ends_at),
                )
            )
        if found:
            self.stdout.write(self.style.WARNING("Kesishgan juftliklar: {} ta".format(found)))
        else:
            self.stdout.write(self.style.SUCCESS("Kesishgan seans yo'q"))
