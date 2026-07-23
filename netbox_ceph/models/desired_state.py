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

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
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
from netbox_ceph.services.redaction import (
    SecretBearingIntentError,
    validate_secret_free_intent,
)

_EXECUTION_NODE_VALIDATOR = RegexValidator(
    regex=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    message=_("Enter an exact Proxmox node name (letters, numbers, '.', '_' and '-')."),
)


class _SecretFreeDesiredStateMixin:
    """Enforce the no-credential invariant on model and ModelForm paths."""

    intent_fields: tuple[str, ...] = ()

    def clean(self) -> None:
        super().clean()
        intent = {field: getattr(self, field) for field in self.intent_fields}
        try:
            validate_secret_free_intent(intent)
        except SecretBearingIntentError as exc:
            raise ValidationError({"__all__": _(str(exc))}) from exc


class CephPoolDesiredState(_SecretFreeDesiredStateMixin, NetBoxModel):
    """NetBox-defined desired configuration for a Ceph pool.

    Distinct from the reflected ``CephPool`` inventory model: this row is the
    intended state an operator manages from NetBox and feeds into a plan/apply
    operation.
    """

    intent_fields = ("parameters",)

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
    execution_node = models.CharField(
        max_length=128,
        default="",
        validators=(_EXECUTION_NODE_VALIDATOR,),
        help_text=_("Exact Proxmox node that will execute this desired mutation."),
    )
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


class CephFilesystemDesiredState(_SecretFreeDesiredStateMixin, NetBoxModel):
    """NetBox-defined desired configuration for a CephFS filesystem."""

    intent_fields = ("data_pools", "parameters")

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
    execution_node = models.CharField(
        max_length=128,
        default="",
        validators=(_EXECUTION_NODE_VALIDATOR,),
        help_text=_("Exact Proxmox node that will execute this desired mutation."),
    )
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
    pg_num = models.PositiveIntegerField(null=True, blank=True)
    add_storage = models.BooleanField(null=True, blank=True)
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


class CephRBDImageDesiredState(_SecretFreeDesiredStateMixin, NetBoxModel):
    """NetBox-defined desired configuration for an RBD image."""

    intent_fields = ("features", "metadata", "parameters")

    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="rbd_image_desired_states",
        verbose_name=_("Ceph cluster"),
    )
    provider = models.ForeignKey(
        to="netbox_ceph.CephProvider",
        on_delete=models.SET_NULL,
        related_name="rbd_image_desired_states",
        null=True,
        blank=True,
    )
    pool_name = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    enabled = models.BooleanField(
        default=True,
        help_text=_("Whether this desired state is active for reconciliation."),
    )
    size_bytes = models.BigIntegerField(null=True, blank=True)
    features = models.JSONField(
        blank=True,
        default=list,
        encoder=CustomFieldJSONEncoder,
        help_text=_(
            "RBD feature flags, e.g. layering, exclusive-lock, object-map, fast-diff, "
            "deep-flatten, journaling."
        ),
    )
    object_size = models.PositiveIntegerField(null=True, blank=True)
    stripe_unit = models.PositiveIntegerField(null=True, blank=True)
    stripe_count = models.PositiveIntegerField(null=True, blank=True)
    data_pool = models.CharField(max_length=255, blank=True)
    clone_parent_image = models.ForeignKey(
        to="self",
        on_delete=models.SET_NULL,
        related_name="clone_children",
        null=True,
        blank=True,
    )
    clone_parent_snapshot = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(
        blank=True,
        default=dict,
        encoder=CustomFieldJSONEncoder,
        help_text=_("Image rbd-meta key/value pairs."),
    )
    parameters = models.JSONField(
        blank=True,
        default=dict,
        encoder=CustomFieldJSONEncoder,
        help_text=_("Additional provider-specific image parameters."),
    )

    class Meta:
        ordering = ("cluster", "pool_name", "name")
        verbose_name = _("Ceph RBD image (desired state)")
        verbose_name_plural = _("Ceph RBD images (desired state)")
        constraints = [
            models.UniqueConstraint(
                fields=("cluster", "pool_name", "name"),
                name="netbox_ceph_rbd_image_desired_identity",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} (desired)"

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephrbdimagedesiredstate", args=[self.pk])


class CephRBDSnapshotDesiredState(_SecretFreeDesiredStateMixin, NetBoxModel):
    """NetBox-defined desired intent for an RBD snapshot."""

    intent_fields = ("parameters",)

    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="rbd_snapshot_desired_states",
        verbose_name=_("Ceph cluster"),
    )
    provider = models.ForeignKey(
        to="netbox_ceph.CephProvider",
        on_delete=models.SET_NULL,
        related_name="rbd_snapshot_desired_states",
        null=True,
        blank=True,
    )
    image = models.ForeignKey(
        to="netbox_ceph.CephRBDImageDesiredState",
        on_delete=models.CASCADE,
        related_name="snapshots",
    )
    name = models.CharField(max_length=255)
    enabled = models.BooleanField(
        default=True,
        help_text=_("Whether this desired state is active for reconciliation."),
    )
    protected = models.BooleanField(
        default=False,
        help_text=_("Whether the snapshot should be protected (required before cloning)."),
    )
    parameters = models.JSONField(
        blank=True,
        default=dict,
        encoder=CustomFieldJSONEncoder,
        help_text=_("Additional provider-specific snapshot parameters."),
    )

    class Meta:
        ordering = ("image", "name")
        verbose_name = _("Ceph RBD snapshot (desired state)")
        verbose_name_plural = _("Ceph RBD snapshots (desired state)")
        constraints = [
            models.UniqueConstraint(
                fields=("image", "name"),
                name="netbox_ceph_rbd_snapshot_desired_identity",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} (desired)"

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephrbdsnapshotdesiredstate", args=[self.pk])


class CephRGWRealmDesiredState(_SecretFreeDesiredStateMixin, NetBoxModel):
    """NetBox-defined desired configuration for an RGW realm."""

    intent_fields = ("parameters",)

    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="rgw_realm_desired_states",
        verbose_name=_("Ceph cluster"),
    )
    provider = models.ForeignKey(
        to="netbox_ceph.CephProvider",
        on_delete=models.SET_NULL,
        related_name="rgw_realm_desired_states",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    enabled = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    parameters = models.JSONField(
        blank=True,
        default=dict,
        encoder=CustomFieldJSONEncoder,
    )

    class Meta:
        ordering = ("cluster", "name")
        verbose_name = _("Ceph RGW realm (desired state)")
        verbose_name_plural = _("Ceph RGW realms (desired state)")
        constraints = [
            models.UniqueConstraint(
                fields=("cluster", "name"),
                name="netbox_ceph_rgw_realm_desired_identity",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} (desired)"

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephrgwrealmdesiredstate", args=[self.pk])


class CephRGWZoneDesiredState(_SecretFreeDesiredStateMixin, NetBoxModel):
    """NetBox-defined desired configuration for an RGW zone."""

    intent_fields = ("endpoints", "placement_targets", "parameters")

    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="rgw_zone_desired_states",
        verbose_name=_("Ceph cluster"),
    )
    provider = models.ForeignKey(
        to="netbox_ceph.CephProvider",
        on_delete=models.SET_NULL,
        related_name="rgw_zone_desired_states",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    enabled = models.BooleanField(default=True)
    realm = models.ForeignKey(
        to="netbox_ceph.CephRGWRealmDesiredState",
        on_delete=models.SET_NULL,
        related_name="zones",
        null=True,
        blank=True,
    )
    zonegroup_name = models.CharField(max_length=255, blank=True)
    is_master = models.BooleanField(default=False)
    endpoints = models.JSONField(
        blank=True,
        default=list,
        encoder=CustomFieldJSONEncoder,
    )
    placement_targets = models.JSONField(
        blank=True,
        default=list,
        encoder=CustomFieldJSONEncoder,
    )
    parameters = models.JSONField(
        blank=True,
        default=dict,
        encoder=CustomFieldJSONEncoder,
    )

    class Meta:
        ordering = ("cluster", "name")
        verbose_name = _("Ceph RGW zone (desired state)")
        verbose_name_plural = _("Ceph RGW zones (desired state)")
        constraints = [
            models.UniqueConstraint(
                fields=("cluster", "name"),
                name="netbox_ceph_rgw_zone_desired_identity",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} (desired)"

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephrgwzonedesiredstate", args=[self.pk])


class CephRGWUserDesiredState(_SecretFreeDesiredStateMixin, NetBoxModel):
    """NetBox-defined desired configuration for an RGW/S3 user."""

    intent_fields = ("credential_ref", "parameters")

    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="rgw_user_desired_states",
        verbose_name=_("Ceph cluster"),
    )
    provider = models.ForeignKey(
        to="netbox_ceph.CephProvider",
        on_delete=models.SET_NULL,
        related_name="rgw_user_desired_states",
        null=True,
        blank=True,
    )
    uid = models.CharField(max_length=255)
    enabled = models.BooleanField(default=True)
    display_name = models.CharField(max_length=255, blank=True)
    email = models.CharField(max_length=255, blank=True)
    tenant_name = models.CharField(max_length=255, blank=True)
    suspended = models.BooleanField(default=False)
    max_buckets = models.IntegerField(null=True, blank=True)
    quota_max_size_bytes = models.BigIntegerField(null=True, blank=True)
    quota_max_objects = models.BigIntegerField(null=True, blank=True)
    credential_ref = models.CharField(
        max_length=255,
        blank=True,
        help_text=_(
            "Opaque pointer to the user's S3 keys in proxbox-api; NetBox never stores the keys."
        ),
    )
    parameters = models.JSONField(
        blank=True,
        default=dict,
        encoder=CustomFieldJSONEncoder,
    )

    class Meta:
        ordering = ("cluster", "uid")
        verbose_name = _("Ceph RGW user (desired state)")
        verbose_name_plural = _("Ceph RGW users (desired state)")
        constraints = [
            models.UniqueConstraint(
                fields=("cluster", "uid"),
                name="netbox_ceph_rgw_user_desired_identity",
            )
        ]

    def __str__(self) -> str:
        return f"{self.uid} (desired)"

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephrgwuserdesiredstate", args=[self.pk])


class CephRGWBucketDesiredState(_SecretFreeDesiredStateMixin, NetBoxModel):
    """NetBox-defined desired configuration for an RGW/S3 bucket."""

    intent_fields = ("lifecycle_policy", "parameters")

    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="rgw_bucket_desired_states",
        verbose_name=_("Ceph cluster"),
    )
    provider = models.ForeignKey(
        to="netbox_ceph.CephProvider",
        on_delete=models.SET_NULL,
        related_name="rgw_bucket_desired_states",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    enabled = models.BooleanField(default=True)
    owner = models.ForeignKey(
        to="netbox_ceph.CephRGWUserDesiredState",
        on_delete=models.SET_NULL,
        related_name="buckets",
        null=True,
        blank=True,
    )
    placement_target = models.CharField(max_length=255, blank=True)
    versioning_enabled = models.BooleanField(default=False)
    quota_max_size_bytes = models.BigIntegerField(null=True, blank=True)
    quota_max_objects = models.BigIntegerField(null=True, blank=True)
    lifecycle_policy = models.JSONField(
        blank=True,
        default=dict,
        encoder=CustomFieldJSONEncoder,
    )
    parameters = models.JSONField(
        blank=True,
        default=dict,
        encoder=CustomFieldJSONEncoder,
    )

    class Meta:
        ordering = ("cluster", "name")
        verbose_name = _("Ceph RGW bucket (desired state)")
        verbose_name_plural = _("Ceph RGW buckets (desired state)")
        constraints = [
            models.UniqueConstraint(
                fields=("cluster", "name"),
                name="netbox_ceph_rgw_bucket_desired_identity",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} (desired)"

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephrgwbucketdesiredstate", args=[self.pk])
