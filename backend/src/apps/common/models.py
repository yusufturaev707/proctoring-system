import uuid

from django.db import models


class TimeStampedModel(models.Model):
    """created_at / updated_at — barcha modellar uchun asos."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class PublicIDModel(TimeStampedModel):
    """
    Tashqariga chiqadigan identifikator UUID bo'lishi kerak.

    Sequential BigAutoField URL'da ko'rinsa, raqobatchi kunlik sessiyalar
    sonini oson hisoblab oladi (enumeration / info leak). Ichkarida `id`
    (bigint) qoladi — JOIN va indekslar uchun u tezroq.
    """

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def delete(self):
        from django.utils import timezone

        return self.update(deleted_at=timezone.now())

    def hard_delete(self):
        return super().delete()


class SoftDeleteModel(TimeStampedModel):
    """
    Konfiguratsiya ma'lumotlari uchun (Computer, Camera, Exam...).

    Imtihon tarixi bilan bog'liq yozuvni hech qachon fizik o'chirmaslik kerak —
    aks holda `on_delete=PROTECT` butun operatsiyani bloklaydi yoki audit izi
    yo'qoladi.
    """

    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = SoftDeleteQuerySet.as_manager()

    def delete(self, using=None, keep_parents=False):
        from django.utils import timezone

        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at", "updated_at"])

    def restore(self):
        self.deleted_at = None
        self.save(update_fields=["deleted_at", "updated_at"])

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    class Meta:
        abstract = True
