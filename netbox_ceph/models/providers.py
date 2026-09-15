"""Ceph v2 provider models."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from netbox.models import NetBoxModel
from utilities.json import CustomFieldJSONEncoder

from netbox_ceph.choices import CephProviderKindChoices, CephProviderStatusChoices
from netbox_ceph.validators import validate_credential_reference


class CephProvider(NetBoxModel):
    """Ceph backend/provider reference.

    NetBox stores only the opaque ``credential_ref``. Actual provider secrets
    live in proxbox-api or its configured secret store and are never stored in
    netbox-ceph.
    """

    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="providers",
        verbose_name=_("Ceph cluster"),
    )
    kind = models.CharField(
        max_length=32,
        choices=CephProviderKindChoices,
        default=CephProviderKindChoices.KIND_PROXMOX,
    )
    name = models.CharField(max_length=255)
    enabled = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    base_url = models.URLField(max_length=512, blank=True)
    verify_ssl = models.BooleanField(default=True, verbose_name=_("Verify SSL"))
    credential_ref = models.CharField(max_length=255, blank=True)
    capabilities = models.JSONField(
        blank=True,
        default=dict,
        encoder=CustomFieldJSONEncoder,
    )
    status = models.CharField(
        max_length=32,
        choices=CephProviderStatusChoices,
        default=CephProviderStatusChoices.STATUS_UNKNOWN,
    )
    status_detail = models.CharField(max_length=512, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("cluster", "kind", "name")
        verbose_name = _("Ceph provider")
        verbose_name_plural = _("Ceph providers")
        constraints = [
            models.UniqueConstraint(
                fields=("cluster", "kind", "name"),
                name="netbox_ceph_provider_identity",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.kind})"

    def clean(self) -> None:
        """Reject secret material while preserving the migration field state."""

        super().clean()
        try:
            validate_credential_reference(self.credential_ref, stored=self._stored_credential_ref())
        except ValidationError as exc:
            raise ValidationError({"credential_ref": exc}) from exc

    def _stored_credential_ref(self) -> str:
        """Return the persisted reference for this row, or ``""`` for a new row."""

        if self.pk is None:
            return ""
        stored = (
            type(self).objects.filter(pk=self.pk).values_list("credential_ref", flat=True).first()
        )
        return stored or ""

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephprovider", args=[self.pk])
