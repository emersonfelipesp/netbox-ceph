"""Ceph v2 metric snapshot models."""

from __future__ import annotations

from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from netbox.models import NetBoxModel
from utilities.json import CustomFieldJSONEncoder

from netbox_ceph.choices import CephMetricScopeChoices


class CephMetricSnapshot(NetBoxModel):
    """Latest metric payload captured for a Ceph object scope."""

    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="metric_snapshots",
    )
    provider = models.ForeignKey(
        to="netbox_ceph.CephProvider",
        on_delete=models.SET_NULL,
        related_name="metric_snapshots",
        null=True,
        blank=True,
    )
    scope = models.CharField(
        max_length=32,
        choices=CephMetricScopeChoices,
        default=CephMetricScopeChoices.SCOPE_CLUSTER,
    )
    object_ref = models.CharField(max_length=255, blank=True)
    metrics = models.JSONField(blank=True, default=dict, encoder=CustomFieldJSONEncoder)
    source = models.CharField(max_length=255, blank=True)
    captured_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("cluster", "scope", "object_ref")
        verbose_name = _("Ceph metric snapshot")
        verbose_name_plural = _("Ceph metric snapshots")
        constraints = [
            models.UniqueConstraint(
                fields=("cluster", "scope", "object_ref"),
                name="netbox_ceph_metric_snapshot_identity",
            )
        ]

    def __str__(self) -> str:
        return f"{self.scope}:{self.object_ref or self.cluster}"

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephmetricsnapshot", args=[self.pk])
