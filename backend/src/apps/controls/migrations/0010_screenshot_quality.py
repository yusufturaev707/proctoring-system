"""
Skrinshot standarti 960/65 -> 1920/80.

Faqat AYNAN ESKI STANDART juftligida turgan profillar ko'chiriladi:
ular hech qachon tahrirlanmagan va yangi standartni kutadi. Qiymati
ataylab o'zgartirilgan profilga tegilmaydi — administrator qarori
migratsiyadan ustun.
"""

from django.db import migrations, models

_OLD = {"screenshot_quality": 65, "screenshot_max_width": 960}
_NEW = {"screenshot_quality": 80, "screenshot_max_width": 1920}


def forwards(apps, schema_editor):
    Setting = apps.get_model("controls", "Setting")
    Setting.objects.filter(**_OLD).update(**_NEW)


def backwards(apps, schema_editor):
    Setting = apps.get_model("controls", "Setting")
    Setting.objects.filter(**_NEW).update(**_OLD)


class Migration(migrations.Migration):
    dependencies = [("controls", "0009_threat_signals")]

    operations = [
        migrations.AlterField(
            model_name="setting",
            name="screenshot_quality",
            field=models.PositiveSmallIntegerField(default=80, verbose_name="Skrinshot sifati"),
        ),
        migrations.AlterField(
            model_name="setting",
            name="screenshot_max_width",
            field=models.PositiveSmallIntegerField(default=1920, verbose_name="Maks. kenglik"),
        ),
        migrations.RunPython(forwards, backwards),
    ]
