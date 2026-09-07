"""
Superadmin roli olib tashlanadi, Administrator esa respublika darajasiga
ko'tariladi.

Sabab: ikkala rol ham amalda bir xil ruxsatlarga ega edi va ular faqat
`is_superuser` bayrog'i bilan farqlanardi. Bu chalkash edi - "kim nima
qila oladi" degan savolga javob rolda emas, foydalanuvchi bayrog'ida
yotardi.

Endi ierarxiya oddiy:
    Administrator (is_global) -> butun respublika
    qolgan rollar            -> o'z viloyati
    is_superuser             -> faqat favqulodda zaxira yo'l

`User.role` FK `PROTECT` bo'lgani uchun tartib MUHIM: avval xodimlar
ko'chiriladi, keyin rol o'chiriladi.
"""

from django.db import migrations

SUPERADMIN = "Superadmin"
ADMINISTRATOR = "Administrator"


def forwards(apps, schema_editor):
    Role = apps.get_model("users", "Role")
    User = apps.get_model("users", "User")

    administrator = Role.objects.filter(name=ADMINISTRATOR).first()
    superadmin = Role.objects.filter(name=SUPERADMIN).first()

    if administrator is not None:
        administrator.is_global = True
        administrator.save(update_fields=["is_global"])

    if superadmin is None:
        return

    if administrator is None:
        # Administrator hali yaratilmagan (bo'sh baza) - Superadmin'ni
        # o'chirish o'rniga uni Administrator'ga aylantiramiz, aks holda
        # unga bog'langan xodimlar rolsiz qolardi.
        superadmin.name = ADMINISTRATOR
        superadmin.is_global = True
        superadmin.save(update_fields=["name", "is_global"])
        return

    moved = User.objects.filter(role_id=superadmin.pk).update(role_id=administrator.pk)
    superadmin.permissions.clear()
    superadmin.delete()
    if moved:
        print("  {} ta xodim Administrator roliga ko'chirildi".format(moved))


def backwards(apps, schema_editor):
    """
    Rolni qaytaramiz, lekin xodimlarni EMAS.

    Kim aynan Superadmin bo'lganini bu migratsiya eslab qolmaydi va
    taxmin qilish xavfli: noto'g'ri odamga to'liq huquq berish -
    ma'lumotni yo'qotishdan battar.
    """
    Role = apps.get_model("users", "Role")
    Permission = apps.get_model("users", "Permission")

    role, created = Role.objects.get_or_create(
        name=SUPERADMIN, defaults={"key": 1, "is_active": True}
    )
    if created:
        role.permissions.set(Permission.objects.all())


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0002_role_is_global"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
