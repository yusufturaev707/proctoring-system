# `EventRiskWeight.severity` hech qayerda o'qilmasdi: jiddiylikni client
# beradi va u darhol yozish, proktor ekrani va dalil yig'ish qarorlarini
# boshqaradi. Ishlatilmaydigan ustun panelda "ishlaydi" bo'lib ko'rinardi
# (sabab: `EventRiskWeight` izohi).

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("controls", "0010_screenshot_quality"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="eventriskweight",
            name="severity",
        ),
    ]
