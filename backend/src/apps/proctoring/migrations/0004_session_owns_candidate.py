"""
`Candidate` jadvalini olib tashlaydi — talabgor ma'lumoti `ExamSession` ga
ko'chadi va imtihon paytidagi holatiga MUZLATIB saqlanadi.

Nima uchun:
  * bayonnomadagi F.I.Sh. keyinchalik tashqi platformada o'zgarsa ham
    o'zgarmaydi (huquqiy hujjat uchun to'g'ri xulq);
  * `reference_embedding` har sessiyada yangidan olinadi — bir marta xato
    yozilgan etalon keyingi imtihonlarda aybsiz talabgorni chetlashtirmaydi;
  * yuzning vaqt bilan o'zgarishi (soqol, ko'zoynak) muammo bo'lmaydi.

`0003` allaqachon PII'ni ochiq shaklga o'tkazgan, shuning uchun bu yerda
deshifrlash YO'Q — maydonlar to'g'ridan-to'g'ri ko'chiriladi.
"""

import django.contrib.postgres.fields
from django.db import migrations, models

#: Talabgordan sessiyaga ko'chadigan maydonlar.
_MOVED_FIELDS = [
    "pinfl", "last_name", "first_name", "middle_name",
    "external_candidate_id", "photo_key", "reference_embedding",
    "anonymize_after", "is_anonymized",
]


def move_candidate_to_session(apps, schema_editor):
    ExamSession = apps.get_model("proctoring", "ExamSession")
    Candidate = apps.get_model("proctoring", "Candidate")

    # Talabgor ma'lumotini bir marta o'qib xotirada xaritalaymiz —
    # sessiyalar ko'p, talabgorlar nisbatan kam.
    cache = {
        candidate.pk: {
            "pinfl": candidate.pinfl,
            "last_name": candidate.last_name or "",
            "first_name": candidate.first_name or "",
            "middle_name": candidate.middle_name or "",
            "external_candidate_id": candidate.external_id or "",
            "photo_key": candidate.photo_key or "",
            "reference_embedding": candidate.reference_embedding,
            "anonymize_after": candidate.anonymize_after,
            "is_anonymized": candidate.is_anonymized,
        }
        for candidate in Candidate.objects.all().iterator(chunk_size=1000)
    }

    moved = 0
    orphans = []
    batch = []

    for session in ExamSession.objects.all().iterator(chunk_size=1000):
        data = cache.get(session.candidate_id)
        if data is None:
            # Talabgori yo'q sessiya — CheckConstraint uchun anonim bo'lishi shart.
            orphans.append(session.pk)
            session.is_anonymized = True
        else:
            for field, value in data.items():
                setattr(session, field, value)
            if not session.pinfl:
                session.is_anonymized = True
            moved += 1

        batch.append(session)
        if len(batch) >= 500:
            ExamSession.objects.bulk_update(batch, _MOVED_FIELDS, batch_size=500)
            batch = []

    if batch:
        ExamSession.objects.bulk_update(batch, _MOVED_FIELDS, batch_size=500)

    if moved or orphans:
        print(f"\n  {moved} ta sessiyaga talabgor ma'lumoti ko'chirildi")
    if orphans:
        print(
            f"  DIQQAT: {len(orphans)} ta sessiyaning talabgori topilmadi — "
            f"anonim deb belgilandi. ID'lar: {orphans[:20]}"
        )


def noop_reverse(apps, schema_editor):
    """Orqaga qaytarish ma'lumotni tiklamaydi — faqat sxemani."""


class Migration(migrations.Migration):

    dependencies = [
        ("proctoring", "0003_plain_candidate_pii"),
    ]

    operations = [
        # --- 1. Eski unique cheklov candidate FK ga tayangan — avval olinadi ---
        migrations.RemoveConstraint(
            model_name="examsession",
            name="unique_session_attempt",
        ),

        # --- 2. Talabgor maydonlarini sessiyaga qo'shish ---
        migrations.AddField(
            model_name="examsession",
            name="pinfl",
            field=models.CharField(
                blank=True, db_index=True, max_length=14, null=True,
                verbose_name="JSHSHIR",
            ),
        ),
        migrations.AddField(
            model_name="examsession",
            name="last_name",
            field=models.CharField(
                blank=True, default="", max_length=255, verbose_name="Familiya"
            ),
        ),
        migrations.AddField(
            model_name="examsession",
            name="first_name",
            field=models.CharField(
                blank=True, default="", max_length=255, verbose_name="Ism"
            ),
        ),
        migrations.AddField(
            model_name="examsession",
            name="middle_name",
            field=models.CharField(
                blank=True, default="", max_length=255, verbose_name="Otasining ismi"
            ),
        ),
        migrations.AddField(
            model_name="examsession",
            name="external_candidate_id",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="examsession",
            name="photo_key",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
        migrations.AddField(
            model_name="examsession",
            name="reference_embedding",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.FloatField(), blank=True, null=True, size=None
            ),
        ),
        migrations.AddField(
            model_name="examsession",
            name="anonymize_after",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="examsession",
            name="is_anonymized",
            field=models.BooleanField(db_index=True, default=False),
        ),

        # --- 3. Ma'lumotni ko'chirish ---
        migrations.RunPython(move_candidate_to_session, noop_reverse),

        # --- 4. Endi FK va Candidate jadvalini olib tashlash mumkin ---
        migrations.RemoveField(model_name="examsession", name="candidate"),
        migrations.RemoveIndex(
            model_name="candidate", name="idx_candidate_retention"
        ),
        migrations.DeleteModel(name="Candidate"),

        # --- 5. Yangi cheklov va indekslar ---
        migrations.AddConstraint(
            model_name="examsession",
            constraint=models.UniqueConstraint(
                fields=("pinfl", "exam", "exam_date", "attempt_no"),
                name="unique_session_attempt",
            ),
        ),
        migrations.AddConstraint(
            model_name="examsession",
            constraint=models.CheckConstraint(
                condition=models.Q(("pinfl__isnull", False))
                | models.Q(("is_anonymized", True)),
                name="session_pinfl_required_unless_anonymized",
            ),
        ),
        migrations.AddIndex(
            model_name="examsession",
            index=models.Index(
                fields=["pinfl", "-exam_date"], name="idx_session_pinfl"
            ),
        ),
        migrations.AddIndex(
            model_name="examsession",
            index=models.Index(
                fields=["is_anonymized", "anonymize_after"],
                name="idx_session_retention",
            ),
        ),
    ]
