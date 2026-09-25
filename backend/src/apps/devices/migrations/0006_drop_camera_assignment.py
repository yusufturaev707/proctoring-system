"""
`CameraAssignment` olib tashlanadi.

Model kompyuter -> kamera rolini saqlardi va u amalda HECH QACHON
to'ldirilmasdi: 500 mashinani qo'lda biriktirib chiqish kunlab vaqt
oladi, natijada client baribir zaxira qoidaga tushardi. Rolni endi
operator client tomonda tanlaydi - u ikkala kadrni ekranda ko'rib
turibdi, administrator esa jadvalda faqat nomni ko'rardi.

MA'LUMOT YO'QOLADI va bu ataylab: jadvaldagi yagona qiymatli
ma'lumot (qaysi IP kamera qaysi mashinaga tegishli) endi BINO
doirasi bilan almashtirildi (`devices.services.cameras_for_computer`),
ya'ni uni ko'chirishning ma'nosi yo'q.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('devices', '0005_camera_roles'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='cameraassignment',
            name='idx_cam_assign_computer',
        ),
        migrations.RemoveConstraint(
            model_name='cameraassignment',
            name='unique_camera_assignment_role',
        ),
        migrations.RemoveConstraint(
            model_name='cameraassignment',
            name='camera_assignment_source_matches',
        ),
        migrations.DeleteModel(
            name='CameraAssignment',
        ),
    ]
