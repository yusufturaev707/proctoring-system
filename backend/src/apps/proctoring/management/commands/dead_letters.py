"""
`:dead` oqimidagi yozuvlar: sababini ko'rish, qayta yozish, tozalash.

    python manage.py dead_letters stats
    python manage.py dead_letters show --category other --limit 5
    python manage.py dead_letters replay --dry-run
    python manage.py dead_letters replay
    python manage.py dead_letters purge --category session_missing --yes

`--stream screenshots` — S3 skrinshot metadata oqimi uchun (standart `events`).
"""

from django.core.management.base import BaseCommand, CommandError

from apps.proctoring.services import dead_letters as service


class Command(BaseCommand):
    help = "Ingest :dead oqimi — sabab, qayta yozish (replay), zaxira bilan tozalash (purge)"

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="action", required=True)

        def common(command):
            command.add_argument("--stream", default="events", choices=sorted(service.STREAMS))
            return command

        common(sub.add_parser("stats", help="Sabab bo'yicha guruhlab ko'rsatadi"))

        show = common(sub.add_parser("show", help="Namuna yozuvlar"))
        show.add_argument("--category", choices=sorted(service.CATEGORIES))
        show.add_argument("--limit", type=int, default=5)

        replay = common(sub.add_parser("replay", help="Asosiy oqimga qaytaradi (Celery qayta yozadi)"))
        replay.add_argument("--category", action="append", choices=sorted(service.CATEGORIES))
        replay.add_argument("--limit", type=int)
        replay.add_argument("--dry-run", action="store_true")

        purge = common(sub.add_parser("purge", help="JSONL faylga zaxira qilib o'chiradi"))
        purge.add_argument("--category", action="append", required=True, choices=sorted(service.CATEGORIES))
        purge.add_argument("--yes", action="store_true", help="Tasdiq (usiz faqat nima o'chishini aytadi)")

    def handle(self, *args, **options):
        try:
            getattr(self, f"_{options['action']}")(options)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

    # ------------------------------------------------------------------
    def _stats(self, options):
        name = options["stream"]
        result = service.stats(name)
        if not result["total"]:
            self.stdout.write(self.style.SUCCESS(f"«{name}»: :dead bo'sh"))
            return
        self.stdout.write(self.style.WARNING(f"«{name}»: jami {result['total']} ta yozuv\n"))
        for key, group in sorted(result["groups"].items(), key=lambda item: -item[1]["count"]):
            category = service.CATEGORIES[key]
            first = service.entry_time(group["first"]).strftime("%Y-%m-%d %H:%M")
            last = service.entry_time(group["last"]).strftime("%Y-%m-%d %H:%M")
            codes = ", ".join(f"{code}×{n}" for code, n in group["codes"].most_common()) or "kodsiz (eski yozuv)"
            self.stdout.write(self.style.MIGRATE_HEADING(f"[{key}] {category.title}: {group['count']} ta"))
            self.stdout.write(f"  vaqt:     {first} … {last} (UTC)")
            self.stdout.write(f"  sessiya:  {len(group['sessions'])} ta turli")
            self.stdout.write(f"  SQLSTATE: {codes}")
            self.stdout.write(f"  namuna:   {group['sample'][:300]}")
            self.stdout.write(f"  qayta yozish: {'mumkin' if category.replayable else "YO'Q"}")
            self.stdout.write(f"  nima qilish: {category.action}\n")

    def _show(self, options):
        shown = 0
        for entry_id, entry in service.read(options["stream"]):
            category = service.classify(entry)
            if options["category"] and category != options["category"]:
                continue
            self.stdout.write(self.style.MIGRATE_HEADING(f"{entry_id} [{category}] {service.entry_time(entry_id):%Y-%m-%d %H:%M:%S}"))
            for field in ("error", "code", "constraint", "reason", "payload"):
                if entry.get(field):
                    self.stdout.write(f"  {field}: {entry[field][:600]}")
            shown += 1
            if shown >= options["limit"]:
                break
        if not shown:
            self.stdout.write("Yozuv yo'q")

    def _replay(self, options):
        categories = set(options["category"]) if options["category"] else None
        result = service.replay(
            options["stream"], categories=categories, dry_run=options["dry_run"], limit=options["limit"],
        )
        verb = "qaytariladi (dry-run)" if result["dry_run"] else "asosiy oqimga qaytarildi"
        self.stdout.write(self.style.SUCCESS(f"{result['replayed']} ta yozuv {verb}"))
        for reason, count in sorted(result["skipped"].items()):
            self.stdout.write(f"  o'tkazib yuborildi [{reason}]: {count}")
        if result["replayed"] and not result["dry_run"]:
            self.stdout.write(
                "Celery `flush_event_buffer` ularni ~5 s da yozadi. Yana yiqilganlari SQLSTATE kodi bilan "
                ":dead ga qaytadi — `dead_letters stats` bilan tekshiring."
            )

    def _purge(self, options):
        categories = set(options["category"])
        if not options["yes"]:
            result = service.stats(options["stream"])
            count = sum(group["count"] for key, group in result["groups"].items() if key in categories)
            self.stdout.write(f"{count} ta yozuv o'chiriladi (avval JSONL zaxira). Tasdiqlash: --yes")
            return
        result = service.purge(options["stream"], categories=categories)
        if not result["deleted"]:
            self.stdout.write("O'chiriladigan yozuv yo'q")
            return
        self.stdout.write(self.style.SUCCESS(f"{result['deleted']} ta yozuv o'chirildi; zaxira: {result['file']}"))
