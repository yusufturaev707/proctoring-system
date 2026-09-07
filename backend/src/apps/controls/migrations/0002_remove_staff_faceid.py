"""
Xodim FaceID sozlamalarini olib tashlaydi.

`is_faceid_staff` va `faceid_min_score_staff` sozlamalar ekranida
ko'rinardi, lekin ularni o'qiydigan yagona kod — `users.services.
verify_staff_face` — hech qayerdan chaqirilmasdi. Ya'ni bu tugmalar
hech nimani boshqarmasdi.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("controls", "0001_initial"),
    ]

    operations = [
        migrations.RemoveField(model_name="setting", name="is_faceid_staff"),
        migrations.RemoveField(model_name="setting", name="faceid_min_score_staff"),
    ]
