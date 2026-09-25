"""
Bron ruxsatlarini MAVJUD bazaga qo'shadi.

Ruxsatlar odatda `seed_base_data` bilan yaratiladi, lekin uni qayta
ishga tushirish rollarning ruxsatlarini matritsaga QAYTARADI — ya'ni
administrator panelda qo'lda o'zgartirgan rollar jimgina eski holiga
tushardi. Shuning uchun yangi kalitlar migratsiya bilan qo'shiladi va
mavjud huquqqa qarab beriladi:

    bookings.manage  <- `exams.manage` bor rollar;
    bookings.view    <- `exams.view`/`exams.manage` bor rollar va
                        seed matritsasidagi Proktor, Monitoring, Operator.
"""

from django.db import migrations

_PERMISSIONS = (
    ("bookings.view", "Kompyuter bronlarini ko'rish"),
    ("bookings.manage", "Kompyuter bronlarini boshqarish"),
)
_VIEW_ROLES = ("Proktor", "Monitoring", "Operator")


def forwards(apps, schema_editor):
    Permission = apps.get_model("users", "Permission")
    Role = apps.get_model("users", "Role")

    created = {}
    for code, name in _PERMISSIONS:
        created[code], _ = Permission.objects.get_or_create(
            code=code, defaults={"name": name, "group": "exams"}
        )

    for role in Role.objects.filter(permissions__code="exams.manage").distinct():
        role.permissions.add(created["bookings.manage"], created["bookings.view"])
    view_roles = Role.objects.filter(permissions__code__in=["exams.view"]) | Role.objects.filter(
        name__in=_VIEW_ROLES
    )
    for role in view_roles.distinct():
        role.permissions.add(created["bookings.view"])


def backwards(apps, schema_editor):
    apps.get_model("users", "Permission").objects.filter(
        code__in=[code for code, _ in _PERMISSIONS]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("exams", "0006_computer_booking"),
        ("users", "0003_drop_superadmin_role"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
