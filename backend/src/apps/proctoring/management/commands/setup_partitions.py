"""
`proctoring_event` jadvalini sana bo'yicha partitsiyalaydi.

Nima uchun kerak:
    10 000 talaba × 3 soat × ~1 hodisa/5s = ~20 mln qator/kun.
    6 oyda bu ~3.6 mlrd qator. Bunday jadvalda:
      * `DELETE FROM ... WHERE occurred_at < ...` bir necha soat ishlaydi
        va jadval bloat qiladi;
      * `VACUUM` hech qachon yetib olmaydi;
      * indekslar RAM'ga sig'maydi.

    Partitsiyalangan jadvalda eski ma'lumot `DROP TABLE partition` bilan
    BIR SONIYADA o'chadi va har bir partitsiyaning indeksi kichik bo'ladi.

Ishlatish:
    python manage.py setup_partitions            # holatni ko'rsatadi
    python manage.py setup_partitions --apply    # konvertatsiya qiladi
    python manage.py setup_partitions --days 30  # oldindan 30 kunlik

DIQQAT: `--apply` jadvalni qayta quradi. Bo'sh yoki kichik jadvalda
xavfsiz; katta jadvalda texnik tanaffusda va backup'dan keyin bajaring.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

TABLE = "proctoring_event"


class Command(BaseCommand):
    help = "proctoring_event jadvalini occurred_at bo'yicha partitsiyalaydi"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Konvertatsiyani bajaradi")
        parser.add_argument("--days", type=int, default=14, help="Necha kunlik partitsiya yaratish")
        parser.add_argument("--force", action="store_true", help="Bo'sh bo'lmagan jadvalda ham bajaradi")

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_partitioned_table pt "
                "JOIN pg_class c ON c.oid = pt.partrelid WHERE c.relname = %s",
                [TABLE],
            )
            already = cursor.fetchone() is not None

            cursor.execute(f"SELECT count(*) FROM {TABLE}")
            row_count = cursor.fetchone()[0]

        if already:
            self.stdout.write(self.style.SUCCESS(f"{TABLE} allaqachon partitsiyalangan"))
            if options["apply"]:
                self._create_partitions(options["days"])
            return

        self.stdout.write(f"{TABLE}: partitsiyalanmagan, {row_count} qator")

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    "Konvertatsiya qilish uchun --apply bering.\n"
                    "Avval backup oling: pg_dump -t proctoring_event ..."
                )
            )
            return

        if row_count > 1_000_000 and not options["force"]:
            raise CommandError(
                f"Jadvalda {row_count} qator bor. Konvertatsiya uzoq davom etadi "
                f"va jadvalni bloklaydi. Texnik tanaffusda --force bilan bajaring."
            )

        self._convert(row_count)
        self._create_partitions(options["days"])

    @transaction.atomic
    def _convert(self, row_count: int):
        """
        Konvertatsiya: eski jadvalni nomlash -> partitsiyalangan yangi jadval
        -> ma'lumotni ko'chirish -> eskisini o'chirish.

        PostgreSQL mavjud jadvalni joyida partitsiyalay olmaydi, shuning
        uchun swap yagona yo'l.
        """
        self.stdout.write("Konvertatsiya boshlandi...")

        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {TABLE} RENAME TO {TABLE}_old")

            # Jadval nomini o'zgartirish INDEKSLARNI qayta nomlamaydi — eski
            # nomlar band qolib, yangi indekslarni yaratishga to'sqinlik qiladi.
            cursor.execute(
                "SELECT indexname FROM pg_indexes WHERE tablename = %s", [f"{TABLE}_old"]
            )
            for (index_name,) in cursor.fetchall():
                cursor.execute(f'ALTER INDEX "{index_name}" RENAME TO "{index_name}_old"')

            # Yangi partitsiyalangan jadval. PRIMARY KEY partitsiya kalitini
            # o'z ichiga olishi SHART — Postgres talabi.
            cursor.execute(
                f"""
                CREATE TABLE {TABLE} (
                    id                bigserial      NOT NULL,
                    session_id        bigint         NOT NULL,
                    type              varchar(32)    NOT NULL,
                    severity          smallint       NOT NULL,
                    occurred_at       timestamptz    NOT NULL,
                    received_at       timestamptz    NOT NULL,
                    payload           jsonb          NOT NULL,
                    screenshot_key    varchar(500)   NOT NULL,
                    client_event_id   varchar(64)    NOT NULL,
                    PRIMARY KEY (id, occurred_at)
                ) PARTITION BY RANGE (occurred_at)
                """
            )
            cursor.execute(
                f"ALTER TABLE {TABLE} ADD CONSTRAINT {TABLE}_session_fk "
                f"FOREIGN KEY (session_id) REFERENCES exam_session(id) "
                f"ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED"
            )

            # Indekslar ota-jadvalda e'lon qilinadi va har bir partitsiyaga
            # avtomatik meros bo'ladi.
            cursor.execute(f"CREATE INDEX idx_event_session_time ON {TABLE} (session_id, occurred_at DESC)")
            cursor.execute(f"CREATE INDEX idx_event_type_time ON {TABLE} (type, occurred_at DESC)")
            cursor.execute(f"CREATE INDEX idx_event_critical ON {TABLE} (occurred_at DESC) WHERE severity >= 3")
            cursor.execute(
                f"CREATE UNIQUE INDEX unique_session_client_event ON {TABLE} "
                f"(session_id, client_event_id, occurred_at) WHERE client_event_id <> ''"
            )

        self.stdout.write(self.style.SUCCESS("Partitsiyalangan jadval yaratildi"))

        if row_count:
            # Ma'lumotni ko'chirishdan oldin kerakli partitsiyalar bo'lishi shart.
            self._create_partitions_for_existing_data()
            with connection.cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO {TABLE} "
                    f"(id, session_id, type, severity, occurred_at, received_at, "
                    f" payload, screenshot_key, client_event_id) "
                    f"SELECT id, session_id, type, severity, occurred_at, received_at, "
                    f"       payload, screenshot_key, client_event_id FROM {TABLE}_old"
                )
                cursor.execute(
                    f"SELECT setval(pg_get_serial_sequence('{TABLE}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {TABLE}), 1))"
                )
            self.stdout.write(self.style.SUCCESS(f"{row_count} qator ko'chirildi"))

        with connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE {TABLE}_old CASCADE")

    def _create_partitions_for_existing_data(self):
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT DISTINCT occurred_at::date FROM {TABLE}_old ORDER BY 1"
            )
            days = [row[0] for row in cursor.fetchall()]
            for day in days:
                self._create_one(cursor, day)
        self.stdout.write(f"  Mavjud ma'lumot uchun {len(days)} partitsiya yaratildi")

    def _create_partitions(self, days_ahead: int):
        today = timezone.localdate()
        created = 0
        with connection.cursor() as cursor:
            # DEFAULT — oxirgi himoya qatlami. Usiz kutilmagan sanali qator
            # INSERT'ni yiqitadi va u bilan birga butun batchni.
            cursor.execute(
                f"CREATE TABLE IF NOT EXISTS {TABLE}_default PARTITION OF {TABLE} DEFAULT"
            )
            # Kechagi kun ham — vaqt mintaqasi chegarasidagi hodisalar uchun.
            for offset in range(-1, days_ahead + 1):
                self._create_one(cursor, today + timezone.timedelta(days=offset))
                created += 1
        self.stdout.write(
            self.style.SUCCESS(f"{created} kunlik partitsiya + DEFAULT tayyor")
        )

    @staticmethod
    def _create_one(cursor, day):
        name = f"{TABLE}_{day:%Y%m%d}"
        cursor.execute(
            f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF {TABLE} "
            f"FOR VALUES FROM (%s) TO (%s)",
            [day, day + timezone.timedelta(days=1)],
        )
