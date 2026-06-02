"""django-tables2 layouts for netbox-ceph list views."""

from __future__ import annotations

import django_tables2 as tables
from netbox.tables import NetBoxTable
from netbox.tables.columns import BooleanColumn

from netbox_ceph.models import (
    CephCluster,
    CephCrushRule,
    CephDaemon,
    CephDriftRecord,
    CephFilesystem,
    CephFilesystemDesiredState,
    CephFlag,
    CephHealthCheck,
    CephMetricSnapshot,
    CephOperation,
    CephOperationRun,
    CephOSD,
    CephPlan,
    CephPool,
    CephPoolDesiredState,
    CephProvider,
    CephRBDImageDesiredState,
    CephRBDSnapshotDesiredState,
    CephValidationResult,
)


class CephClusterTable(NetBoxTable):
    name = tables.Column(linkify=True)
    endpoint = tables.Column(linkify=True)
    proxmox_cluster = tables.Column(linkify=True)

    class Meta(NetBoxTable.Meta):
        model = CephCluster
        fields = (
            "pk",
            "id",
            "name",
            "endpoint",
            "proxmox_cluster",
            "fsid",
            "health",
            "last_seen_at",
            "actions",
        )
        default_columns = ("name", "endpoint", "proxmox_cluster", "fsid", "health", "last_seen_at")


class CephDaemonTable(NetBoxTable):
    name = tables.Column(linkify=True)
    endpoint = tables.Column(linkify=True)
    cluster = tables.Column(linkify=True)
    proxmox_node = tables.Column(linkify=True)

    class Meta(NetBoxTable.Meta):
        model = CephDaemon
        fields = (
            "pk",
            "id",
            "daemon_type",
            "name",
            "daemon_id",
            "endpoint",
            "cluster",
            "proxmox_node",
            "host",
            "state",
            "version",
            "last_seen_at",
            "actions",
        )
        default_columns = (
            "daemon_type",
            "name",
            "endpoint",
            "cluster",
            "host",
            "state",
            "last_seen_at",
        )


class CephOSDTable(NetBoxTable):
    osd_id = tables.Column(linkify=True, verbose_name="OSD")
    endpoint = tables.Column(linkify=True)
    cluster = tables.Column(linkify=True)
    proxmox_node = tables.Column(linkify=True)
    up = BooleanColumn()
    in_cluster = BooleanColumn()

    class Meta(NetBoxTable.Meta):
        model = CephOSD
        fields = (
            "pk",
            "id",
            "osd_id",
            "endpoint",
            "cluster",
            "proxmox_node",
            "host",
            "up",
            "in_cluster",
            "status",
            "device_class",
            "weight",
            "reweight",
            "used_bytes",
            "available_bytes",
            "total_bytes",
            "pgs",
            "last_seen_at",
            "actions",
        )
        default_columns = (
            "osd_id",
            "endpoint",
            "cluster",
            "host",
            "up",
            "in_cluster",
            "device_class",
            "weight",
            "last_seen_at",
        )


class CephPoolTable(NetBoxTable):
    name = tables.Column(linkify=True)
    endpoint = tables.Column(linkify=True)
    cluster = tables.Column(linkify=True)

    class Meta(NetBoxTable.Meta):
        model = CephPool
        fields = (
            "pk",
            "id",
            "name",
            "endpoint",
            "cluster",
            "pool_id",
            "size",
            "min_size",
            "pg_num",
            "pg_autoscale_mode",
            "crush_rule",
            "application",
            "used_bytes",
            "max_available_bytes",
            "percent_used",
            "last_seen_at",
            "actions",
        )
        default_columns = (
            "name",
            "endpoint",
            "cluster",
            "size",
            "min_size",
            "application",
            "percent_used",
            "last_seen_at",
        )


class CephFilesystemTable(NetBoxTable):
    name = tables.Column(linkify=True)
    endpoint = tables.Column(linkify=True)
    cluster = tables.Column(linkify=True)
    metadata_pool = tables.Column(linkify=True)

    class Meta(NetBoxTable.Meta):
        model = CephFilesystem
        fields = (
            "pk",
            "id",
            "name",
            "endpoint",
            "cluster",
            "metadata_pool",
            "standby_count_wanted",
            "last_seen_at",
            "actions",
        )
        default_columns = ("name", "endpoint", "cluster", "metadata_pool", "last_seen_at")


class CephCrushRuleTable(NetBoxTable):
    name = tables.Column(linkify=True)
    endpoint = tables.Column(linkify=True)
    cluster = tables.Column(linkify=True)

    class Meta(NetBoxTable.Meta):
        model = CephCrushRule
        fields = (
            "pk",
            "id",
            "name",
            "endpoint",
            "cluster",
            "rule_id",
            "rule_type",
            "device_class",
            "last_seen_at",
            "actions",
        )
        default_columns = (
            "name",
            "endpoint",
            "cluster",
            "rule_type",
            "device_class",
            "last_seen_at",
        )


class CephFlagTable(NetBoxTable):
    name = tables.Column(linkify=True)
    endpoint = tables.Column(linkify=True)
    cluster = tables.Column(linkify=True)
    enabled = BooleanColumn()

    class Meta(NetBoxTable.Meta):
        model = CephFlag
        fields = (
            "pk",
            "id",
            "name",
            "endpoint",
            "cluster",
            "enabled",
            "value",
            "last_seen_at",
            "actions",
        )
        default_columns = ("name", "endpoint", "cluster", "enabled", "value", "last_seen_at")


class CephHealthCheckTable(NetBoxTable):
    name = tables.Column(linkify=True)
    endpoint = tables.Column(linkify=True)
    cluster = tables.Column(linkify=True)

    class Meta(NetBoxTable.Meta):
        model = CephHealthCheck
        fields = (
            "pk",
            "id",
            "name",
            "endpoint",
            "cluster",
            "severity",
            "summary",
            "source",
            "first_seen_at",
            "last_seen_at",
            "actions",
        )
        default_columns = ("name", "endpoint", "cluster", "severity", "summary", "last_seen_at")


class CephProviderTable(NetBoxTable):
    name = tables.Column(linkify=True)
    cluster = tables.Column(linkify=True)
    enabled = BooleanColumn()
    is_default = BooleanColumn()
    verify_ssl = BooleanColumn(verbose_name="Verify SSL")

    class Meta(NetBoxTable.Meta):
        model = CephProvider
        fields = (
            "pk",
            "id",
            "name",
            "cluster",
            "kind",
            "enabled",
            "is_default",
            "base_url",
            "verify_ssl",
            "credential_ref",
            "status",
            "status_detail",
            "last_checked_at",
            "actions",
        )
        default_columns = (
            "name",
            "cluster",
            "kind",
            "enabled",
            "is_default",
            "status",
            "last_checked_at",
        )


class CephOperationTable(NetBoxTable):
    target_kind = tables.Column(linkify=True)
    cluster = tables.Column(linkify=True)
    provider = tables.Column(linkify=True)
    is_destructive = BooleanColumn()
    confirmation_required = BooleanColumn()
    confirmed = BooleanColumn()

    class Meta(NetBoxTable.Meta):
        model = CephOperation
        fields = (
            "pk",
            "id",
            "cluster",
            "provider",
            "operation_type",
            "target_kind",
            "target_ref",
            "status",
            "is_destructive",
            "confirmation_required",
            "confirmed",
            "requested_by",
            "source_branch_schema_id",
            "created",
            "last_updated",
            "actions",
        )
        default_columns = (
            "operation_type",
            "target_kind",
            "target_ref",
            "cluster",
            "provider",
            "status",
            "is_destructive",
            "confirmed",
            "created",
        )


class CephPlanTable(NetBoxTable):
    operation = tables.Column(linkify=True)
    is_destructive = BooleanColumn()

    class Meta(NetBoxTable.Meta):
        model = CephPlan
        fields = (
            "pk",
            "id",
            "operation",
            "status",
            "summary",
            "provider_target",
            "is_destructive",
            "generated_at",
            "created",
            "last_updated",
            "actions",
        )
        default_columns = (
            "operation",
            "status",
            "provider_target",
            "is_destructive",
            "generated_at",
        )


class CephValidationResultTable(NetBoxTable):
    code = tables.Column(linkify=True)
    plan = tables.Column(linkify=True)
    operation = tables.Column(linkify=True)

    class Meta(NetBoxTable.Meta):
        model = CephValidationResult
        fields = (
            "pk",
            "id",
            "plan",
            "operation",
            "severity",
            "code",
            "message",
            "target",
            "created",
            "last_updated",
            "actions",
        )
        default_columns = ("severity", "code", "message", "target", "operation")


class CephOperationRunTable(NetBoxTable):
    operation = tables.Column(linkify=True)
    plan = tables.Column(linkify=True)
    provider = tables.Column(linkify=True)

    class Meta(NetBoxTable.Meta):
        model = CephOperationRun
        fields = (
            "pk",
            "id",
            "operation",
            "plan",
            "provider",
            "status",
            "actor",
            "source_branch_schema_id",
            "provider_task_ref",
            "started_at",
            "finished_at",
            "created",
            "last_updated",
            "actions",
        )
        default_columns = (
            "operation",
            "provider",
            "status",
            "provider_task_ref",
            "started_at",
            "finished_at",
        )


class CephDriftRecordTable(NetBoxTable):
    object_ref = tables.Column(linkify=True)
    cluster = tables.Column(linkify=True)
    provider = tables.Column(linkify=True)

    class Meta(NetBoxTable.Meta):
        model = CephDriftRecord
        fields = (
            "pk",
            "id",
            "cluster",
            "provider",
            "object_kind",
            "object_ref",
            "drift_status",
            "detected_at",
            "created",
            "last_updated",
            "actions",
        )
        default_columns = (
            "object_kind",
            "object_ref",
            "cluster",
            "provider",
            "drift_status",
            "detected_at",
        )


class CephMetricSnapshotTable(NetBoxTable):
    object_ref = tables.Column(linkify=True)
    cluster = tables.Column(linkify=True)
    provider = tables.Column(linkify=True)

    class Meta(NetBoxTable.Meta):
        model = CephMetricSnapshot
        fields = (
            "pk",
            "id",
            "cluster",
            "provider",
            "scope",
            "object_ref",
            "source",
            "captured_at",
            "created",
            "last_updated",
            "actions",
        )
        default_columns = (
            "scope",
            "object_ref",
            "cluster",
            "provider",
            "source",
            "captured_at",
        )


class CephPoolDesiredStateTable(NetBoxTable):
    name = tables.Column(linkify=True)
    cluster = tables.Column(linkify=True)
    provider = tables.Column(linkify=True)
    enabled = BooleanColumn()

    class Meta(NetBoxTable.Meta):
        model = CephPoolDesiredState
        fields = (
            "pk",
            "id",
            "name",
            "cluster",
            "provider",
            "enabled",
            "size",
            "min_size",
            "pg_autoscale_mode",
            "application",
            "crush_rule_name",
            "compression_mode",
            "erasure_code_profile",
            "actions",
        )
        default_columns = (
            "name",
            "cluster",
            "enabled",
            "size",
            "min_size",
            "application",
            "pg_autoscale_mode",
        )


class CephFilesystemDesiredStateTable(NetBoxTable):
    name = tables.Column(linkify=True)
    cluster = tables.Column(linkify=True)
    provider = tables.Column(linkify=True)
    metadata_pool = tables.Column(linkify=True)
    enabled = BooleanColumn()

    class Meta(NetBoxTable.Meta):
        model = CephFilesystemDesiredState
        fields = (
            "pk",
            "id",
            "name",
            "cluster",
            "provider",
            "enabled",
            "metadata_pool",
            "mds_placement",
            "standby_count",
            "max_mds",
            "actions",
        )
        default_columns = (
            "name",
            "cluster",
            "enabled",
            "metadata_pool",
            "standby_count",
            "max_mds",
        )


class CephRBDImageDesiredStateTable(NetBoxTable):
    name = tables.Column(linkify=True)
    cluster = tables.Column(linkify=True)
    provider = tables.Column(linkify=True)
    clone_parent_image = tables.Column(linkify=True)
    enabled = BooleanColumn()

    class Meta(NetBoxTable.Meta):
        model = CephRBDImageDesiredState
        fields = (
            "pk",
            "id",
            "name",
            "cluster",
            "provider",
            "pool_name",
            "enabled",
            "size_bytes",
            "object_size",
            "stripe_unit",
            "stripe_count",
            "data_pool",
            "clone_parent_image",
            "clone_parent_snapshot",
            "actions",
        )
        default_columns = (
            "name",
            "cluster",
            "pool_name",
            "enabled",
            "size_bytes",
            "data_pool",
        )


class CephRBDSnapshotDesiredStateTable(NetBoxTable):
    name = tables.Column(linkify=True)
    cluster = tables.Column(linkify=True)
    provider = tables.Column(linkify=True)
    image = tables.Column(linkify=True)
    enabled = BooleanColumn()
    protected = BooleanColumn()

    class Meta(NetBoxTable.Meta):
        model = CephRBDSnapshotDesiredState
        fields = (
            "pk",
            "id",
            "name",
            "cluster",
            "provider",
            "image",
            "enabled",
            "protected",
            "actions",
        )
        default_columns = (
            "name",
            "cluster",
            "image",
            "enabled",
            "protected",
        )
