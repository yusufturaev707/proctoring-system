"""
Yuz balli shkalasi: `(cos+1)/2*100` -> `max(0, cos)*100`.

NIMA UCHUN O'ZGARDI. Eski shkalada butunlay boshqa odam ~50 ball
olardi va panelda bu "yarmi o'xshash" bo'lib ko'rinardi. Chegarani
tanlash ham chalkash edi: 70 ball aslida 0.40 cosine degani edi va
buni faqat formulani ochib bilish mumkin edi. Yangi shkalada ball
to'g'ridan-to'g'ri o'xshashlikni bildiradi — 70 ball 0.70 cosine.

MAVJUD QIYMATLAR KO'CHIRILADI, aks holda o'zgarish JIMGINA
qattiqlashtirish bo'lardi: administrator qo'ygan 70 yangi shkalada
0.70 cosine bo'lib qolar va hujjat rasmi bilan solishtirishda
deyarli hech kim o'tolmasdi (odatiy oraliq 0.40-0.70).

    yangi = eski * 2 - 100        (0 dan past bo'lsa 0)

Ya'ni 70 -> 40, 60 -> 20, 85 -> 70. Har bir profil AVVALGIDEK
ishlashda davom etadi.
"""

from django.db import migrations, models


def _to_new(value) -> int:
    return max(0, min(100, int(value or 0) * 2 - 100))


def to_new_scale(apps, schema_editor):
    Setting = apps.get_model("controls", "Setting")
    for pk, student, exam in Setting.objects.values_list(
        "pk", "faceid_min_score_student", "faceid_min_score_exam"
    ):
        Setting.objects.filter(pk=pk).update(
            faceid_min_score_student=_to_new(student),
            faceid_min_score_exam=_to_new(exam),
        )


def to_old_scale(apps, schema_editor):
    """
    Teskari yo'l TAXMINIY va buni bilish kerak.

    `max(0, cos)` manfiy qiymatlarni yo'qotgan, ya'ni 0 ball eski
    shkalada 50 yoki undan past istalgan qiymat bo'lishi mumkin edi.
    Chegara sifatida 50 dan past qiymat ishlatilmaydi, shuning uchun
    teskari ko'chirishda aynan 50 olinadi.
    """
    Setting = apps.get_model("controls", "Setting")
    for pk, student, exam in Setting.objects.values_list(
        "pk", "faceid_min_score_student", "faceid_min_score_exam"
    ):
        Setting.objects.filter(pk=pk).update(
            faceid_min_score_student=min(100, int(student or 0) // 2 + 50),
            faceid_min_score_exam=min(100, int(exam or 0) // 2 + 50),
        )


class Migration(migrations.Migration):

    dependencies = [
        ('controls', '0007_proctoring_policy'),
    ]

    operations = [
        migrations.AlterField(
            model_name='setting',
            name='faceid_min_score_exam',
            field=models.PositiveSmallIntegerField(default=40, verbose_name='Min ball (test)'),
        ),
        migrations.AlterField(
            model_name='setting',
            name='faceid_min_score_student',
            field=models.PositiveSmallIntegerField(default=40, verbose_name='Min ball (talabgor)'),
        ),
        migrations.RunPython(to_new_scale, to_old_scale),
    ]
