"""
`allowed_domains` olib tashlanadi, `site_header_encrypted` qo'shiladi.

MA'LUMOT KO'CHIRILMAYDI va bu ongli. `allowed_domains` ro'yxati
`site_url` domenidan boshqa qiymat saqlagan bo'lsa ham, yangi
mantiq domenni har doim `site_url` dan oladi — ya'ni ko'chiriladigan
joy yo'q. Agar biror imtihonda ro'yxat boshqa domenlarni ham
o'z ichiga olgan bo'lsa, `site_url` ni to'g'rilash kerak; buni
migratsiya taxmin qilib bajarolmaydi.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('exams', '0004_exam_type'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='exam',
            name='allowed_domains',
        ),
        migrations.AddField(
            model_name='exam',
            name='site_header_encrypted',
            field=models.TextField(blank=True, default='', verbose_name='Platforma sarlavhasi'),
        ),
    ]
