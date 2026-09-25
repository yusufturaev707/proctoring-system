"""
`external_session_token_enc` -> `external_test_link_enc`.

BU RENAME EMAS, ikkita alohida amal — va farq muhim. Eski ustunda
tashqi platformaning sessiya TOKENI yotardi, yangisida esa to'liq
test HAVOLASI (`data.test_link`). Ularning formati ham, ma'nosi ham
boshqa: tokenni havola sifatida ochib bo'lmaydi.

Rename qilinsa, eski sessiyalarning tokeni yangi maydonga tushib
qolardi va `exam/access/` uni havola deb WebView'ga berardi —
natijada talabgor "sahifa topilmadi" ekranini ko'rardi. Ustun
o'chirilgani ma'qul: tugallanmagan eski sessiyalar baribir
`close_stale_sessions` bilan yopiladi.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("proctoring", "0013_alter_auditlog_action"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="examsession",
            name="external_session_token_enc",
        ),
        migrations.AddField(
            model_name="examsession",
            name="external_test_link_enc",
            field=models.TextField(blank=True, default=""),
        ),
    ]
