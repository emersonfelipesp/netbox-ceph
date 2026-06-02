"""Ceph v2 desired-state configuration models.

These models are the NetBox source of truth for *intended* Ceph configuration.
They are deliberately separate from the v1 reflected inventory models in
``netbox_ceph.models.ceph`` (``CephPool``, ``CephFilesystem``, ...), which mirror
live Proxmox-managed state read-only. A desired-state row expresses what an
operator wants; the existing ``CephOperation`` -> ``CephPlan`` -> ``CephOperationRun``
engine reconciles it against a provider via proxbox-api ``/ceph/v2/*``.

Desired-state rows never hold secrets. Any credential lives behind the provider's
opaque ``credential_ref``; orchestrator payloads are redacted at the boundary.
"""

from __future__ import annotations

from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from netbox.models import NetBoxModel
from utilities.json import CustomFieldJSONEncoder

from netbox_ceph.choices import (
    CephPoolApplicationChoices,
    CephPoolAutoscaleChoices,
    CephPoolCompressionChoices,
)


class CephPoolDesiredState(NetBoxModel):
    """NetBox-defined desired configuration for a Ceph pool.

    Distinct from the reflected ``CephPool`` inventory model: this row is the
    intended state an operator manages from NetBox and feeds into a plan/apply
    operation.
    """

    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="pool_desired_states",
        verbose_name=_("Ceph cluster"),
    )
    provider = models.ForeignKey(
        to="netbox_ceph.CephProvider",
        on_delete=models.SET_NULL,
        related_name="pool_desired_states",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    enabled = models.BooleanField(
        default=True,
        help_text=_("Whether this desired state is active for reconciliation."),
    )
    size = models.PositiveSmallIntegerField(default=3)
    min_size = models.PositiveSmallIntegerField(default=2)
    pg_autoscale_mode = models.CharField(
        max_length=16,
        choices=CephPoolAutoscaleChoices,
        default=CephPoolAutoscaleChoices.MODE_ON,
    )
    crush_rule_name = models.CharField(max_length=255, blank=True)
    application = models.CharField(
        max_length=16,
        choices=CephPoolApplicationChoices,
        default=CephPoolApplicationChoices.APP_RBD,
    )
    target_size_ratio = models.FloatField(null=True, blank=True)
    quota_max_bytes = models.BigIntegerField(null=True, blank=True)
    quota_max_objects = models.BigIntegerField(null=True, blank=True)
    compression_mode = models.CharField(
        max_length=16,
        choices=CephPoolCompressionChoices,
        default=CephPoolCompressionChoices.MODE_NONE,
    )
    erasure_code_profile = models.CharField(max_length=255, blank=True)
    parameters = models.JSONField(
        blank=True,
        default=dict,
        encoder=CustomFieldJSONEncoder,
        help_text=_("Additional provider-specific pool parameters."),
    )

    class Meta:
        ordering = ("cluster", "name")
        verbose_name = _("Ceph pool (desired state)")
        verbose_name_plural = _("Ceph pools (desired state)")
        constraints = [
            models.UniqueConstraint(
                fields=("cluster", "name"),
                name="netbox_ceph_pool_desired_identity",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} (desired)"

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephpooldesiredstate", args=[self.pk])


class CephFilesystemDesiredState(NetBoxModel):
    """NetBox-defined desired configuration for a CephFS filesystem."""

    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="filesystem_desired_states",
        verbose_name=_("Ceph cluster"),
    )
    provider = models.ForeignKey(
        to="netbox_ceph.CephProvider",
        on_delete=models.SET_NULL,
        related_name="filesystem_desired_states",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    enabled = models.BooleanField(
        default=True,
        help_text=_("Whether this desired state is active for reconciliation."),
    )
    metadata_pool = models.ForeignKey(
        to="netbox_ceph.CephPoolDesiredState",
        on_delete=models.SET_NULL,
        related_name="metadata_filesystems",
        null=True,
        blank=True,
        help_text=_("Desired-state pool used as the CephFS metadata pool."),
    )
    data_pools = models.JSONField(
        blank=True,
        default=list,
        encoder=CustomFieldJSONEncoder,
        help_text=_("Ordered list of data pool names for this filesystem."),
    )
    mds_placement = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("Placement spec / host label for MDS daemons."),
    )
    standby_count = models.PositiveSmallIntegerField(default=1)
    max_mds = models.PositiveSmallIntegerField(default=1)
    quota_max_bytes = models.BigIntegerField(null=True, blank=True)
    parameters = models.JSONField(
        blank=True,
        default=dict,
        encoder=CustomFieldJSONEncoder,
        help_text=_("Additional provider-specific CephFS parameters."),
    )

    class Meta:
        ordering = ("cluster", "name")
        verbose_name = _("CephFS filesystem (desired state)")
        verbose_name_plural = _("CephFS filesystems (desired state)")
        constraints = [
            models.UniqueConstraint(
                fields=("cluster", "name"),
                name="netbox_ceph_filesystem_desired_identity",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} (desired)"

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephfilesystemdesiredstate", args=[self.pk])
