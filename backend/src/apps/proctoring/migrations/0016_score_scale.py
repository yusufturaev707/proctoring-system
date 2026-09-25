"""
Yuz tekshiruvi yozuvlarini yangi ball shkalasiga ko'chirish.

`controls.0008_score_scale` bilan BIR JUFT: u chegaralarni ko'chiradi,
bu esa allaqachon yozilgan natijalarni. Ikkalasi birga bo'lishi shart —
aks holda bitta ustunda ikki xil ma'nodagi son yotardi va "47 ball"
qaysi shkalada ekanini faqat yozuv sanasiga qarab taxmin qilish
mumkin bo'lardi.

    yangi = eski * 2 - 100        (0 dan past bo'lsa 0)

Ball va chegara BIRGA ko'chiriladi, ya'ni "o'tdi/o'tmadi" munosabati
o'zgarmaydi: 47/70 (o'tmadi) -> 0/40 (o'tmadi).

Eski `initial` qatorlarida ball 0 bo'lgan (o'sha paytda server
clientning ballini yozmasdi) — ular 0 bo'lib qolaveradi va bu
to'g'ri: o'sha yozuvlarda ball HECH QACHON o'lchanmagan.
"""

from django.db import migrations


def _to_new(value) -> int:
    return max(0, min(100, int(value or 0) * 2 - 100))


def to_new_scale(apps, schema_editor):
    FaceVerificationLog = apps.get_model("proctoring", "FaceVerificationLog")
    rows = FaceVerificationLog.objects.values_list("pk", "score", "threshold")
    # Partiyalab emas, bittalab: bu jadval kichik (sessiyaga ~10 qator)
    # va migratsiya bir marta ishlaydi. Bittalab `update()` esa
    # xotirani ushlab qolmaydi.
    for pk, score, threshold in rows.iterator(chunk_size=1000):
        FaceVerificationLog.objects.filter(pk=pk).update(
            score=_to_new(score), threshold=_to_new(threshold)
        )


def to_old_scale(apps, schema_editor):
    """Teskari yo'l TAXMINIY (`controls.0008` dagi bilan bir xil sabab)."""
    FaceVerificationLog = apps.get_model("proctoring", "FaceVerificationLog")
    rows = FaceVerificationLog.objects.values_list("pk", "score", "threshold")
    for pk, score, threshold in rows.iterator(chunk_size=1000):
        FaceVerificationLog.objects.filter(pk=pk).update(
            score=min(100, int(score or 0) // 2 + 50),
            threshold=min(100, int(threshold or 0) // 2 + 50),
        )


class Migration(migrations.Migration):

    dependencies = [
        ("proctoring", "0015_face_log_images"),
        ("controls", "0008_score_scale"),
    ]

    operations = [
        migrations.RunPython(to_new_scale, to_old_scale),
    ]
