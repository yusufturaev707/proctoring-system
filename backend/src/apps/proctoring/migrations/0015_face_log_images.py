"""
Yuz tekshiruvi qatoriga RASM va SESSIYASIZ urinish.

Ikkita o'zgarish va ikkalasi ham bitta savoldan kelib chiqadi:
"talabgor kira olmaganda nima qoladi?".

  * `session` endi NULL bo'lishi mumkin. Kirishdagi tekshiruv
    sessiya YARATILISHIDAN oldin bo'ladi — muvaffaqiyatsiz
    urinishni sessiyaga bog'lab bo'lmaydi. Uning o'rniga qator
    `pinfl`, `exam` va `zone` ni o'zida saqlaydi.
  * `image_path` — jonli kadr diskda (storage ildiziga nisbatan),
    `image_purge_after` esa uning muddati. Muddat QATORDA, chunki
    tozalash vazifasi siyosatni qayta o'qimasligi kerak: u sessiya
    tugagach o'zgargan bo'lishi mumkin.

Eski qatorlar tegilmaydi: yangi ustunlar bo'sh qoladi va ular
"rasm saqlanmagan" degani.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('exams', '0005_exam_site_header'),
        ('proctoring', '0014_session_test_link'),
        ('regions', '0002_alter_region_options_alter_zone_options_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='faceverificationlog',
            name='exam',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='face_logs', to='exams.exam'),
        ),
        migrations.AddField(
            model_name='faceverificationlog',
            name='image_path',
            field=models.CharField(blank=True, default='', max_length=500),
        ),
        migrations.AddField(
            model_name='faceverificationlog',
            name='image_purge_after',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='faceverificationlog',
            name='pinfl',
            field=models.CharField(blank=True, db_index=True, default='', max_length=14),
        ),
        migrations.AddField(
            model_name='faceverificationlog',
            name='zone',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='face_logs', to='regions.zone'),
        ),
        migrations.AlterField(
            model_name='faceverificationlog',
            name='session',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='face_logs', to='proctoring.examsession'),
        ),
        migrations.AddIndex(
            model_name='faceverificationlog',
            index=models.Index(fields=['pinfl', '-occurred_at'], name='idx_facelog_pinfl_time'),
        ),
    ]
