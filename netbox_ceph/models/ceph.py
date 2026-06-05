"""Read-only Ceph inventory models.

All operational objects are reflected from Proxmox-managed Ceph state in v1.
They intentionally do not carry ``allow_writes`` fields or desired-state
configuration. v2 tracks NetBox-to-Ceph writes separately.
"""

from __future__ import annotations

from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from netbox.models import NetBoxModel
from utilities.json import CustomFieldJSONEncoder

from netbox_ceph.choices import (
    CephDaemonStateChoices,
    CephDaemonTypeChoices,
    CephHealthChoices,
)

BRANCH_ON_CONFLICT_CHOICES = (
    ("fail", _("Fail (leave branch open for review)")),
    ("acknowledge", _("Acknowledge and merge anyway")),
)


class CephPluginSettings(NetBoxModel):
    """Singleton-style settings row for netbox-ceph sync behavior."""

    singleton_key = models.CharField(
        max_length=32,
        unique=True,
        default="default",
        editable=False,
    )
    branching_enabled = models.BooleanField(
        default=False,
        verbose_name=_("Branching-enabled sync (Ceph -> NetBox)"),
        help_text=_(
            "When enabled, every Ceph sync job creates a fresh netbox-branching "
            "branch, runs the sync on that branch, and merges it back into main "
            "on success."
        ),
    )
    branch_name_prefix = models.CharField(
        max_length=64,
        default="ceph-sync",
        verbose_name=_("Branch name prefix"),
    )
    branch_on_conflict = models.CharField(
        max_length=16,
        choices=BRANCH_ON_CONFLICT_CHOICES,
        default="fail",
        verbose_name=_("Branch merge conflict policy"),
    )

    class Meta:
        verbose_name = _("Ceph plugin settings")
        verbose_name_plural = _("Ceph plugin settings")

    def __str__(self) -> str:
        return "Ceph plugin settings"

    def save(self, *args: object, **kwargs: object) -> None:
        self.singleton_key = "default"
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls) -> "CephPluginSettings":
        obj, _created = cls.objects.get_or_create(singleton_key="default")
        return obj


class CephCluster(NetBoxModel):
    """Ceph cluster state discovered from a Proxmox endpoint."""

    endpoint = models.ForeignKey(
        to="netbox_proxbox.ProxmoxEndpoint",
        on_delete=models.CASCADE,
        related_name="ceph_clusters",
        verbose_name=_("Proxmox endpoint"),
    )
    proxmox_cluster = models.ForeignKey(
        to="netbox_proxbox.ProxmoxCluster",
        on_delete=models.SET_NULL,
        related_name="ceph_clusters",
        null=True,
        blank=True,
        verbose_name=_("Proxmox cluster"),
    )
    name = models.CharField(max_length=255, verbose_name=_("Cluster name"))
    fsid = models.CharField(max_length=64, blank=True, verbose_name=_("FSID"))
    health = models.CharField(
        max_length=32,
        choices=CephHealthChoices,
        default=CephHealthChoices.HEALTH_UNKNOWN,
    )
    quorum_names = models.JSONField(
        blank=True,
        default=list,
        encoder=CustomFieldJSONEncoder,
        verbose_name=_("Quorum members"),
    )
    status = models.JSONField(blank=True, default=dict, encoder=CustomFieldJSONEncoder)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("endpoint", "name")
        verbose_name = _("Ceph cluster")
        verbose_name_plural = _("Ceph clusters")
        constraints = [
            models.UniqueConstraint(
                fields=("endpoint", "name"),
                name="netbox_ceph_cluster_identity",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.endpoint})"

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephcluster", args=[self.pk])


class CephDaemon(NetBoxModel):
    """MON/MGR/MDS daemon record reflected from Ceph."""

    endpoint = models.ForeignKey(
        to="netbox_proxbox.ProxmoxEndpoint",
        on_delete=models.CASCADE,
        related_name="ceph_daemons",
    )
    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="daemons",
        null=True,
        blank=True,
    )
    proxmox_node = models.ForeignKey(
        to="netbox_proxbox.ProxmoxNode",
        on_delete=models.SET_NULL,
        related_name="ceph_daemons",
        null=True,
        blank=True,
    )
    daemon_type = models.CharField(
        max_length=16,
        choices=CephDaemonTypeChoices,
        default=CephDaemonTypeChoices.TYPE_UNKNOWN,
    )
    name = models.CharField(max_length=255)
    daemon_id = models.CharField(max_length=255, blank=True)
    host = models.CharField(max_length=255, blank=True)
    state = models.CharField(
        max_length=32,
        choices=CephDaemonStateChoices,
        default=CephDaemonStateChoices.STATE_UNKNOWN,
    )
    status = models.CharField(max_length=255, blank=True)
    version = models.CharField(max_length=128, blank=True)
    metadata = models.JSONField(blank=True, default=dict, encoder=CustomFieldJSONEncoder)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("endpoint", "daemon_type", "name")
        verbose_name = _("Ceph daemon")
        verbose_name_plural = _("Ceph daemons")
        constraints = [
            models.UniqueConstraint(
                fields=("endpoint", "daemon_type", "name"),
                name="netbox_ceph_daemon_identity",
            )
        ]

    def __str__(self) -> str:
        return f"{self.daemon_type}.{self.name}"

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephdaemon", args=[self.pk])


class CephOSD(NetBoxModel):
    """Ceph OSD capacity and status."""

    endpoint = models.ForeignKey(
        to="netbox_proxbox.ProxmoxEndpoint",
        on_delete=models.CASCADE,
        related_name="ceph_osds",
    )
    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="osds",
        null=True,
        blank=True,
    )
    proxmox_node = models.ForeignKey(
        to="netbox_proxbox.ProxmoxNode",
        on_delete=models.SET_NULL,
        related_name="ceph_osds",
        null=True,
        blank=True,
    )
    osd_id = models.PositiveIntegerField(verbose_name=_("OSD ID"))
    name = models.CharField(max_length=255, blank=True)
    host = models.CharField(max_length=255, blank=True)
    up = models.BooleanField(default=False)
    in_cluster = models.BooleanField(default=False, verbose_name=_("In cluster"))
    status = models.CharField(max_length=255, blank=True)
    device_class = models.CharField(max_length=64, blank=True)
    weight = models.FloatField(null=True, blank=True)
    reweight = models.FloatField(null=True, blank=True)
    used_bytes = models.BigIntegerField(null=True, blank=True)
    available_bytes = models.BigIntegerField(null=True, blank=True)
    total_bytes = models.BigIntegerField(null=True, blank=True)
    pgs = models.PositiveIntegerField(null=True, blank=True)
    metadata = models.JSONField(blank=True, default=dict, encoder=CustomFieldJSONEncoder)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("endpoint", "osd_id")
        verbose_name = _("Ceph OSD")
        verbose_name_plural = _("Ceph OSDs")
        constraints = [
            models.UniqueConstraint(
                fields=("endpoint", "osd_id"),
                name="netbox_ceph_osd_identity",
            )
        ]

    def __str__(self) -> str:
        return f"osd.{self.osd_id}"

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephosd", args=[self.pk])


class CephPool(NetBoxModel):
    """Ceph pool state."""

    endpoint = models.ForeignKey(
        to="netbox_proxbox.ProxmoxEndpoint",
        on_delete=models.CASCADE,
        related_name="ceph_pools",
    )
    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="pools",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    pool_id = models.PositiveIntegerField(null=True, blank=True)
    size = models.PositiveSmallIntegerField(null=True, blank=True)
    min_size = models.PositiveSmallIntegerField(null=True, blank=True)
    pg_num = models.PositiveIntegerField(null=True, blank=True)
    pg_autoscale_mode = models.CharField(max_length=32, blank=True)
    crush_rule = models.CharField(max_length=255, blank=True)
    application = models.CharField(max_length=64, blank=True)
    used_bytes = models.BigIntegerField(null=True, blank=True)
    max_available_bytes = models.BigIntegerField(null=True, blank=True)
    percent_used = models.FloatField(null=True, blank=True)
    status = models.JSONField(blank=True, default=dict, encoder=CustomFieldJSONEncoder)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("endpoint", "name")
        verbose_name = _("Ceph pool")
        verbose_name_plural = _("Ceph pools")
        constraints = [
            models.UniqueConstraint(
                fields=("endpoint", "name"),
                name="netbox_ceph_pool_identity",
            )
        ]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephpool", args=[self.pk])


class CephFilesystem(NetBoxModel):
    """CephFS state."""

    endpoint = models.ForeignKey(
        to="netbox_proxbox.ProxmoxEndpoint",
        on_delete=models.CASCADE,
        related_name="ceph_filesystems",
    )
    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="filesystems",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    metadata_pool = models.ForeignKey(
        to="netbox_ceph.CephPool",
        on_delete=models.SET_NULL,
        related_name="metadata_filesystems",
        null=True,
        blank=True,
    )
    data_pools = models.JSONField(blank=True, default=list, encoder=CustomFieldJSONEncoder)
    standby_count_wanted = models.PositiveIntegerField(null=True, blank=True)
    status = models.JSONField(blank=True, default=dict, encoder=CustomFieldJSONEncoder)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("endpoint", "name")
        verbose_name = _("Ceph filesystem")
        verbose_name_plural = _("Ceph filesystems")
        constraints = [
            models.UniqueConstraint(
                fields=("endpoint", "name"),
                name="netbox_ceph_filesystem_identity",
            )
        ]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephfilesystem", args=[self.pk])


class CephCrushRule(NetBoxModel):
    """CRUSH rule reflected from Ceph."""

    endpoint = models.ForeignKey(
        to="netbox_proxbox.ProxmoxEndpoint",
        on_delete=models.CASCADE,
        related_name="ceph_crush_rules",
    )
    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="crush_rules",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    rule_id = models.IntegerField(null=True, blank=True)
    rule_type = models.CharField(max_length=64, blank=True)
    device_class = models.CharField(max_length=64, blank=True)
    steps = models.JSONField(blank=True, default=list, encoder=CustomFieldJSONEncoder)
    raw = models.JSONField(blank=True, default=dict, encoder=CustomFieldJSONEncoder)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("endpoint", "name")
        verbose_name = _("Ceph CRUSH rule")
        verbose_name_plural = _("Ceph CRUSH rules")
        constraints = [
            models.UniqueConstraint(
                fields=("endpoint", "name"),
                name="netbox_ceph_crush_rule_identity",
            )
        ]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephcrushrule", args=[self.pk])


class CephFlag(NetBoxModel):
    """Cluster-level Ceph flag state."""

    endpoint = models.ForeignKey(
        to="netbox_proxbox.ProxmoxEndpoint",
        on_delete=models.CASCADE,
        related_name="ceph_flags",
    )
    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="flags",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=64)
    enabled = models.BooleanField(null=True, blank=True)
    value = models.CharField(max_length=255, blank=True)
    raw = models.JSONField(blank=True, default=dict, encoder=CustomFieldJSONEncoder)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("endpoint", "name")
        verbose_name = _("Ceph flag")
        verbose_name_plural = _("Ceph flags")
        constraints = [
            models.UniqueConstraint(
                fields=("endpoint", "name"),
                name="netbox_ceph_flag_identity",
            )
        ]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephflag", args=[self.pk])


class CephHealthCheck(NetBoxModel):
    """Health check entry parsed from Ceph status payloads."""

    endpoint = models.ForeignKey(
        to="netbox_proxbox.ProxmoxEndpoint",
        on_delete=models.CASCADE,
        related_name="ceph_health_checks",
    )
    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="health_checks",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    severity = models.CharField(
        max_length=32,
        choices=CephHealthChoices,
        default=CephHealthChoices.HEALTH_UNKNOWN,
    )
    summary = models.CharField(max_length=512, blank=True)
    detail = models.JSONField(blank=True, default=list, encoder=CustomFieldJSONEncoder)
    source = models.CharField(max_length=64, blank=True)
    first_seen_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("endpoint", "severity", "name")
        verbose_name = _("Ceph health check")
        verbose_name_plural = _("Ceph health checks")
        constraints = [
            models.UniqueConstraint(
                fields=("endpoint", "name"),
                name="netbox_ceph_health_check_identity",
            )
        ]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephhealthcheck", args=[self.pk])


class CephRGWRealm(NetBoxModel):
    """RGW realm reflected from live Ceph state."""

    endpoint = models.ForeignKey(
        to="netbox_proxbox.ProxmoxEndpoint",
        on_delete=models.CASCADE,
        related_name="ceph_rgw_realms",
    )
    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="rgw_realms",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    is_default = models.BooleanField(default=False)
    status = models.JSONField(blank=True, default=dict, encoder=CustomFieldJSONEncoder)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("endpoint", "name")
        verbose_name = _("Ceph RGW realm")
        verbose_name_plural = _("Ceph RGW realms")
        constraints = [
            models.UniqueConstraint(
                fields=("endpoint", "name"),
                name="netbox_ceph_rgw_realm_identity",
            )
        ]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephrgwrealm", args=[self.pk])


class CephRGWZoneGroup(NetBoxModel):
    """RGW zonegroup reflected from live Ceph state."""

    endpoint = models.ForeignKey(
        to="netbox_proxbox.ProxmoxEndpoint",
        on_delete=models.CASCADE,
        related_name="ceph_rgw_zonegroups",
    )
    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="rgw_zonegroups",
        null=True,
        blank=True,
    )
    realm = models.ForeignKey(
        to="netbox_ceph.CephRGWRealm",
        on_delete=models.SET_NULL,
        related_name="zonegroups",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    is_master = models.BooleanField(default=False)
    endpoints = models.JSONField(blank=True, default=list, encoder=CustomFieldJSONEncoder)
    status = models.JSONField(blank=True, default=dict, encoder=CustomFieldJSONEncoder)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("endpoint", "name")
        verbose_name = _("Ceph RGW zone group")
        verbose_name_plural = _("Ceph RGW zone groups")
        constraints = [
            models.UniqueConstraint(
                fields=("endpoint", "name"),
                name="netbox_ceph_rgw_zone_group_identity",
            )
        ]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephrgwzonegroup", args=[self.pk])


class CephRGWZone(NetBoxModel):
    """RGW zone reflected from live Ceph state."""

    endpoint = models.ForeignKey(
        to="netbox_proxbox.ProxmoxEndpoint",
        on_delete=models.CASCADE,
        related_name="ceph_rgw_zones",
    )
    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="rgw_zones",
        null=True,
        blank=True,
    )
    zonegroup = models.ForeignKey(
        to="netbox_ceph.CephRGWZoneGroup",
        on_delete=models.SET_NULL,
        related_name="zones",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    endpoints = models.JSONField(blank=True, default=list, encoder=CustomFieldJSONEncoder)
    status = models.JSONField(blank=True, default=dict, encoder=CustomFieldJSONEncoder)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("endpoint", "name")
        verbose_name = _("Ceph RGW zone")
        verbose_name_plural = _("Ceph RGW zones")
        constraints = [
            models.UniqueConstraint(
                fields=("endpoint", "name"),
                name="netbox_ceph_rgw_zone_identity",
            )
        ]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephrgwzone", args=[self.pk])


class CephRGWPlacementTarget(NetBoxModel):
    """RGW placement target reflected from live Ceph state."""

    endpoint = models.ForeignKey(
        to="netbox_proxbox.ProxmoxEndpoint",
        on_delete=models.CASCADE,
        related_name="ceph_rgw_placement_targets",
    )
    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="rgw_placement_targets",
        null=True,
        blank=True,
    )
    zonegroup = models.ForeignKey(
        to="netbox_ceph.CephRGWZoneGroup",
        on_delete=models.SET_NULL,
        related_name="placement_targets",
        null=True,
        blank=True,
    )
    zone = models.ForeignKey(
        to="netbox_ceph.CephRGWZone",
        on_delete=models.SET_NULL,
        related_name="placement_targets",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    storage_classes = models.JSONField(
        blank=True,
        default=list,
        encoder=CustomFieldJSONEncoder,
    )
    status = models.JSONField(blank=True, default=dict, encoder=CustomFieldJSONEncoder)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("endpoint", "name")
        verbose_name = _("Ceph RGW placement target")
        verbose_name_plural = _("Ceph RGW placement targets")
        constraints = [
            models.UniqueConstraint(
                fields=("endpoint", "name"),
                name="netbox_ceph_rgw_placement_target_identity",
            )
        ]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephrgwplacementtarget", args=[self.pk])


class CephRGWUserReflected(NetBoxModel):
    """RGW/S3 user metadata reflected from live Ceph state.

    This model deliberately stores only non-secret user metadata. S3 access
    keys, secret keys, passwords, tokens, and credential refs do not belong in
    reflected NetBox inventory.
    """

    endpoint = models.ForeignKey(
        to="netbox_proxbox.ProxmoxEndpoint",
        on_delete=models.CASCADE,
        related_name="ceph_rgw_users_reflected",
    )
    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="rgw_users_reflected",
        null=True,
        blank=True,
    )
    uid = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255, blank=True)
    email = models.CharField(max_length=255, blank=True)
    tenant = models.CharField(max_length=255, blank=True)
    suspended = models.BooleanField(default=False)
    max_buckets = models.IntegerField(null=True, blank=True)
    status = models.JSONField(blank=True, default=dict, encoder=CustomFieldJSONEncoder)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("endpoint", "tenant", "uid")
        verbose_name = _("Ceph RGW user (reflected)")
        verbose_name_plural = _("Ceph RGW users (reflected)")
        constraints = [
            models.UniqueConstraint(
                fields=("endpoint", "tenant", "uid"),
                name="netbox_ceph_rgw_user_reflected_identity",
            )
        ]

    def __str__(self) -> str:
        if self.tenant:
            return f"{self.tenant}/{self.uid}"
        return self.uid

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephrgwuserreflected", args=[self.pk])


class CephRGWBucketReflected(NetBoxModel):
    """RGW/S3 bucket metadata reflected from live Ceph state."""

    endpoint = models.ForeignKey(
        to="netbox_proxbox.ProxmoxEndpoint",
        on_delete=models.CASCADE,
        related_name="ceph_rgw_buckets_reflected",
    )
    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="rgw_buckets_reflected",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    owner_uid = models.CharField(max_length=255, blank=True)
    tenant = models.CharField(max_length=255, blank=True)
    num_objects = models.BigIntegerField(null=True, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    placement_rule = models.CharField(max_length=255, blank=True)
    versioning = models.CharField(max_length=32, blank=True)
    status = models.JSONField(blank=True, default=dict, encoder=CustomFieldJSONEncoder)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("endpoint", "tenant", "name")
        verbose_name = _("Ceph RGW bucket (reflected)")
        verbose_name_plural = _("Ceph RGW buckets (reflected)")
        constraints = [
            models.UniqueConstraint(
                fields=("endpoint", "tenant", "name"),
                name="netbox_ceph_rgw_bucket_reflected_identity",
            )
        ]

    def __str__(self) -> str:
        if self.tenant:
            return f"{self.tenant}/{self.name}"
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephrgwbucketreflected", args=[self.pk])


class CephRBDImage(NetBoxModel):
    """RBD image reflected from live Ceph state."""

    endpoint = models.ForeignKey(
        to="netbox_proxbox.ProxmoxEndpoint",
        on_delete=models.CASCADE,
        related_name="ceph_rbd_images",
    )
    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="rbd_images",
        null=True,
        blank=True,
    )
    pool_name = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    namespace = models.CharField(max_length=255, blank=True)
    image_id = models.CharField(max_length=255, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    object_size = models.PositiveIntegerField(null=True, blank=True)
    features = models.JSONField(blank=True, default=list, encoder=CustomFieldJSONEncoder)
    num_objects = models.BigIntegerField(null=True, blank=True)
    parent = models.JSONField(blank=True, default=dict, encoder=CustomFieldJSONEncoder)
    data_pool = models.CharField(max_length=255, blank=True)
    status = models.JSONField(blank=True, default=dict, encoder=CustomFieldJSONEncoder)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("endpoint", "pool_name", "namespace", "name")
        verbose_name = _("Ceph RBD image")
        verbose_name_plural = _("Ceph RBD images")
        constraints = [
            models.UniqueConstraint(
                fields=("endpoint", "pool_name", "namespace", "name"),
                name="netbox_ceph_rbd_image_identity",
            )
        ]

    def __str__(self) -> str:
        if self.namespace:
            return f"{self.pool_name}/{self.namespace}/{self.name}"
        return f"{self.pool_name}/{self.name}"

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephrbdimage", args=[self.pk])


class CephRBDSnapshot(NetBoxModel):
    """RBD snapshot reflected from live Ceph state."""

    endpoint = models.ForeignKey(
        to="netbox_proxbox.ProxmoxEndpoint",
        on_delete=models.CASCADE,
        related_name="ceph_rbd_snapshots",
    )
    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="rbd_snapshots",
        null=True,
        blank=True,
    )
    image = models.ForeignKey(
        to="netbox_ceph.CephRBDImage",
        on_delete=models.CASCADE,
        related_name="snapshots",
    )
    name = models.CharField(max_length=255)
    snap_id = models.PositiveIntegerField(null=True, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    protected = models.BooleanField(default=False)
    status = models.JSONField(blank=True, default=dict, encoder=CustomFieldJSONEncoder)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("image", "name")
        verbose_name = _("Ceph RBD snapshot")
        verbose_name_plural = _("Ceph RBD snapshots")
        constraints = [
            models.UniqueConstraint(
                fields=("image", "name"),
                name="netbox_ceph_rbd_snapshot_identity",
            )
        ]

    def __str__(self) -> str:
        return f"{self.image}@{self.name}"

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephrbdsnapshot", args=[self.pk])


class CephRBDClone(NetBoxModel):
    """RBD clone relationship reflected from live Ceph state."""

    endpoint = models.ForeignKey(
        to="netbox_proxbox.ProxmoxEndpoint",
        on_delete=models.CASCADE,
        related_name="ceph_rbd_clones",
    )
    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="rbd_clones",
        null=True,
        blank=True,
    )
    parent_image = models.ForeignKey(
        to="netbox_ceph.CephRBDImage",
        on_delete=models.CASCADE,
        related_name="clone_children",
    )
    parent_snapshot = models.ForeignKey(
        to="netbox_ceph.CephRBDSnapshot",
        on_delete=models.CASCADE,
        related_name="clone_children",
    )
    child_pool_name = models.CharField(max_length=255)
    child_name = models.CharField(max_length=255)
    status = models.JSONField(blank=True, default=dict, encoder=CustomFieldJSONEncoder)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("endpoint", "child_pool_name", "child_name")
        verbose_name = _("Ceph RBD clone")
        verbose_name_plural = _("Ceph RBD clones")
        constraints = [
            models.UniqueConstraint(
                fields=("parent_image", "parent_snapshot", "child_pool_name", "child_name"),
                name="netbox_ceph_rbd_clone_identity",
            )
        ]

    def __str__(self) -> str:
        return (
            f"{self.parent_image}@{self.parent_snapshot.name} -> "
            f"{self.child_pool_name}/{self.child_name}"
        )

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephrbdclone", args=[self.pk])
