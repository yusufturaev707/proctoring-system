"""
Client sozlamalarining ikkinchi qatlami: `.env` dan panelga.

FaceID oqimi, ekran yozuvi, skrinshot kamera tasmasi va tahdid
to'sig'i endi `Setting` da (ilgari har mashinaning `.env` ida edi).
Qoida va jadval - `CLAUDE.md`: "Client sozlamalari: .env va panel".

MA'LUMOT KO'CHIRISH - "AMALDAGI XULQNI SAQLASH" qoidasi bilan. Uchta
mavjud maydon ilgari panelda bor edi, lekin client ularni O'QIMASDI
va o'z `.env` qiymati bilan ishlardi. Endi o'qiydi, ya'ni bazadagi
qiymat birinchi marta KUCHGA KIRADI:

  * `is_screen_record` - standart `False` edi, client esa ekranni
    `SCREEN_RECORD_ENABLED=true` bo'yicha HAR DOIM yozardi. Hammasi
    `True` ga ko'chiriladi: aks holda yangilanish jimgina dalilni
    (ekran yozuvini) o'chirib qo'yardi;
  * `heartbeat_interval` / `event_batch_interval` /
    `offline_buffer_size` - yangi chegaradan tashqaridagi qiymat
    client amalda ishlatgan qiymatga (30 / 5 / 5000) qaytariladi.
    Masalan 120 s heartbeat endi har sessiyani panelda "aloqa yo'q"
    qilib qo'yardi.

Orqaga qaytarishda qiymatlarga TEGILMAYDI: ular maydon standartidan
boshqa hech narsani buzmaydi, asl qiymatni esa tiklab bo'lmaydi.
"""

import django.core.validators
from django.conf import settings
from django.db import migrations, models

import apps.controls.models


def forwards(apps, schema_editor):
    Setting = apps.get_model("controls", "Setting")
    Setting.objects.filter(is_screen_record=False).update(is_screen_record=True)

    heartbeat_max = int(settings.PROCTORING["HEARTBEAT_TIMEOUT"]) // 2
    Setting.objects.exclude(heartbeat_interval__range=(5, heartbeat_max)).update(
        heartbeat_interval=30
    )
    Setting.objects.exclude(event_batch_interval__range=(1, 60)).update(
        event_batch_interval=5
    )
    Setting.objects.exclude(offline_buffer_size__range=(100, 50000)).update(
        offline_buffer_size=5000
    )


class Migration(migrations.Migration):

    dependencies = [
        ('controls', '0011_drop_risk_weight_severity'),
    ]

    operations = [
        migrations.AddField(
            model_name='setting',
            name='faceid_fail_min_seconds',
            field=models.PositiveSmallIntegerField(default=8, help_text='Urinish shu vaqtdan oldin muvaffaqiyatsiz deb yopilmaydi', validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(120)], verbose_name='Rad uchun minimal vaqt (s)'),
        ),
        migrations.AddField(
            model_name='setting',
            name='faceid_fail_streak',
            field=models.PositiveSmallIntegerField(default=15, help_text="Shuncha ketma-ket kadr mos kelmasa (va vaqt o'tsa) - urinish yopiladi", validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(300)], verbose_name='Rad uchun ketma-ket kadr'),
        ),
        migrations.AddField(
            model_name='setting',
            name='faceid_guide_seconds',
            field=models.PositiveSmallIntegerField(default=5, help_text='Kamera ochilgach yuzni ovalga joylash vaqti; 0 - sanoqsiz', validators=[django.core.validators.MaxValueValidator(30)], verbose_name="Joylashish sanog'i (s)"),
        ),
        migrations.AddField(
            model_name='setting',
            name='faceid_match_streak',
            field=models.PositiveSmallIntegerField(default=3, help_text='Shuncha ketma-ket kadr mos kelsa - shaxs tasdiqlanadi', validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(30)], verbose_name='Tasdiq uchun ketma-ket kadr'),
        ),
        migrations.AddField(
            model_name='setting',
            name='is_screenshot_camera_overlay',
            field=models.BooleanField(default=True, verbose_name='Skrinshotga kamera kadri'),
        ),
        migrations.AddField(
            model_name='setting',
            name='is_threat_block_exam',
            field=models.BooleanField(default=True, verbose_name="Yo'q qilinmagan tahdid imtihonni to'sadi"),
        ),
        migrations.AddField(
            model_name='setting',
            name='screen_record_fps',
            field=models.PositiveSmallIntegerField(default=5, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(15)], verbose_name='Ekran yozuvi FPS'),
        ),
        migrations.AddField(
            model_name='setting',
            name='screen_record_pip_percent',
            field=models.PositiveSmallIntegerField(default=12, help_text='Kamera tasviri kengligi - yozuv kengligiga nisbatan', validators=[django.core.validators.MinValueValidator(5), django.core.validators.MaxValueValidator(30)], verbose_name='Yozuvdagi kamera oynasi (%)'),
        ),
        migrations.AddField(
            model_name='setting',
            name='screen_record_width',
            field=models.PositiveSmallIntegerField(default=1600, validators=[django.core.validators.MinValueValidator(640), django.core.validators.MaxValueValidator(3840)], verbose_name='Ekran yozuvi kengligi (px)'),
        ),
        migrations.AddField(
            model_name='setting',
            name='screenshot_pip_percent',
            field=models.PositiveSmallIntegerField(default=16, help_text='Ramka kengligi - skrinshot kengligiga nisbatan', validators=[django.core.validators.MinValueValidator(5), django.core.validators.MaxValueValidator(40)], verbose_name='Skrinshotdagi kamera ramkasi (%)'),
        ),
        migrations.AlterField(
            model_name='setting',
            name='event_batch_interval',
            field=models.PositiveSmallIntegerField(default=5, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(60)], verbose_name='Event batch intervali (s)'),
        ),
        migrations.AlterField(
            model_name='setting',
            name='heartbeat_interval',
            field=models.PositiveSmallIntegerField(default=30, validators=[django.core.validators.MinValueValidator(5), apps.controls.models.validate_heartbeat_interval], verbose_name='Heartbeat intervali (s)'),
        ),
        migrations.AlterField(
            model_name='setting',
            name='is_screen_record',
            field=models.BooleanField(default=True, verbose_name='Ekranni yozish'),
        ),
        migrations.AlterField(
            model_name='setting',
            name='offline_buffer_size',
            field=models.PositiveIntegerField(default=5000, validators=[django.core.validators.MinValueValidator(100), django.core.validators.MaxValueValidator(50000)], verbose_name='Offline buffer hajmi'),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
