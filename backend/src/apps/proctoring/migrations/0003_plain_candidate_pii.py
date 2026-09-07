"""
Candidate PII'sini ochiq shaklga o'tkazadi va ishlatilmagan maydonlarni oladi.

DIQQAT: bu migratsiya allaqachon qo'llanilgan bo'lishi mumkin. Uni
o'zgartirmang va o'chirmang — keyingi qadam `0004` da.

Ma'lumot ko'chirish: eski `pinfl_enc` / `*_name_enc` maydonlari AES-GCM bilan
shifrlangan. Ular yangi ochiq ustunlarga deshifrlab ko'chiriladi — bu qadam
`FIELD_ENCRYPTION_KEY` hali eski qiymatda bo'lishini talab qiladi.

Deshifrlab bo'lmagan yozuv (kalit almashgan yoki buzilgan) `pinfl` siz
qoladi, unique NOT NULL cheklovi esa buni o'tkazmaydi — shuning uchun
bunday qatorlarga surrogat qiymat beriladi va ular log'ga chiqariladi.
"""

import django.contrib.postgres.fields
from django.db import migrations, models


def decrypt_pii(apps, schema_editor):
    from apps.common.utils.crypto import decrypt

    Candidate = apps.get_model("proctoring", "Candidate")
    broken = []

    for candidate in Candidate.objects.all().iterator(chunk_size=1000):
        pinfl = (decrypt(candidate.pinfl_enc) or "").strip()
        if not pinfl:
            # Deshifrlab bo'lmadi — NOT NULL unique uchun surrogat.
            pinfl = f"anon-{candidate.pk}"
            broken.append(candidate.pk)

        candidate.pinfl = pinfl[:14]
        candidate.last_name = (decrypt(candidate.last_name_enc) or "")[:255]
        candidate.first_name = (decrypt(candidate.first_name_enc) or "")[:255]
        candidate.middle_name = (decrypt(candidate.middle_name_enc) or "")[:255]
        candidate.save(
            update_fields=["pinfl", "last_name", "first_name", "middle_name"]
        )

    if broken:
        print(
            f"\n  DIQQAT: {len(broken)} ta talabgor JSHSHIR'i deshifrlanmadi, "
            f"surrogat qiymat berildi. ID'lar: {broken[:20]}"
        )


def noop_reverse(apps, schema_editor):
    """Orqaga qaytarish ma'lumotni tiklamaydi — faqat sxemani."""


class Migration(migrations.Migration):

    dependencies = [
        ("proctoring", "0002_initial"),
    ]

    operations = [
        # --- 1. Yangi ochiq ustunlar (avval nullable, ko'chirish uchun) ---
        migrations.AddField(
            model_name="candidate",
            name="pinfl",
            field=models.CharField(max_length=14, null=True, verbose_name="JSHSHIR"),
        ),
        migrations.AddField(
            model_name="candidate",
            name="last_name",
            field=models.CharField(
                blank=True, default="", max_length=255, verbose_name="Familiya"
            ),
        ),
        migrations.AddField(
            model_name="candidate",
            name="first_name",
            field=models.CharField(
                blank=True, default="", max_length=255, verbose_name="Ism"
            ),
        ),
        migrations.AddField(
            model_name="candidate",
            name="middle_name",
            field=models.CharField(
                blank=True, default="", max_length=255, verbose_name="Otasining ismi"
            ),
        ),

        # --- 2. Ma'lumotni deshifrlab ko'chirish ---
        migrations.RunPython(decrypt_pii, noop_reverse),

        # --- 3. Endi cheklovlarni qo'yish mumkin ---
        migrations.AlterField(
            model_name="candidate",
            name="pinfl",
            field=models.CharField(
                db_index=True, max_length=14, unique=True, verbose_name="JSHSHIR"
            ),
        ),

        # --- 4. Eski shifrlangan va ishlatilmagan maydonlarni olib tashlash ---
        migrations.RemoveField(model_name="candidate", name="pinfl_hash"),
        migrations.RemoveField(model_name="candidate", name="pinfl_enc"),
        migrations.RemoveField(model_name="candidate", name="last_name_enc"),
        migrations.RemoveField(model_name="candidate", name="first_name_enc"),
        migrations.RemoveField(model_name="candidate", name="middle_name_enc"),
        migrations.RemoveField(model_name="candidate", name="birth_date"),
        migrations.RemoveField(model_name="candidate", name="gender"),
        migrations.RemoveField(model_name="candidate", name="region"),

        # --- 5. Hech qachon yozilmagan maydon ---
        migrations.RemoveField(model_name="examsession", name="external_session_id"),

        # --- 6. `reference_embedding` ni model bilan sinxronlash ---
        migrations.AlterField(
            model_name="candidate",
            name="reference_embedding",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.FloatField(), blank=True, null=True, size=None
            ),
        ),
    ]
