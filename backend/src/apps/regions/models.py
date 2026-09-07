from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import SoftDeleteModel, TimeStampedModel


class Region(TimeStampedModel):
    """Viloyat."""

    name = models.CharField(_("Nom"), max_length=255, unique=True)
    dtm_id = models.IntegerField(_("DTM ID"), unique=True)
    vm_number = models.IntegerField(_("VM raqami"), unique=True)
    is_have_part = models.BooleanField(_("Bo'linmalari bor"), default=False)
    is_active = models.BooleanField(_("Faol"), default=True, db_index=True)

    def __str__(self):
        return str(self.name)

    class Meta:
        verbose_name = _("Viloyat")
        verbose_name_plural = _("Viloyatlar")
        db_table = "region"
        ordering = ["dtm_id"]


class Zone(SoftDeleteModel):
    """Imtihon binosi/zonasi. Kompyuterlar va kameralar shunga biriktiriladi."""

    region = models.ForeignKey(
        "regions.Region",
        verbose_name=_("Viloyat"),
        on_delete=models.PROTECT,
        related_name="zones",
    )
    name = models.CharField(_("Nom"), max_length=255)
    number = models.IntegerField(_("Raqam"), default=0)
    address = models.CharField(_("Manzil"), max_length=500, blank=True, default="")
    capacity = models.PositiveIntegerField(_("Sig'im"), default=0)
    is_active = models.BooleanField(_("Faol"), default=True)
    is_part = models.BooleanField(_("Bino anklabmi"), default=False)

    def __str__(self):
        return f"{self.name} ({self.number})"

    class Meta:
        verbose_name = _("Bino")
        verbose_name_plural = _("Binolar")
        db_table = "zone"
        ordering = ["region__dtm_id", "number"]
        constraints = [
            models.UniqueConstraint(
                fields=["region", "number"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_zone_region_number",
            )
        ]
        indexes = [
            # Dashboard "viloyat -> faol binolar" so'rovi uchun.
            models.Index(fields=["region", "is_active"], name="idx_zone_region_active"),
        ]
