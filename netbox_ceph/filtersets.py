"""NetBox filtersets for netbox-ceph list views and (future) API queries.

Filtersets are intentionally narrow: in v1 the netbox-ceph plugin only
reflects Proxmox-managed Ceph state, so all queries are read-only.
"""

from __future__ import annotations

from django.db.models import Q
from netbox.filtersets import NetBoxModelFilterSet

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
    CephOperationApproval,
    CephOperationRun,
    CephOSD,
    CephPlan,
    CephPool,
    CephPoolDesiredState,
    CephProvider,
    CephRBDClone,
    CephRBDImage,
    CephRBDImageDesiredState,
    CephRBDSnapshot,
    CephRBDSnapshotDesiredState,
    CephRGWBucketDesiredState,
    CephRGWBucketReflected,
    CephRGWPlacementTarget,
    CephRGWRealm,
    CephRGWRealmDesiredState,
    CephRGWUserDesiredState,
    CephRGWUserReflected,
    CephRGWZone,
    CephRGWZoneDesiredState,
    CephRGWZoneGroup,
    CephValidationResult,
)


class _EndpointSearchMixin:
    """Shared free-text search across name/endpoint name."""

    search_fields: tuple[str, ...] = ("name",)

    def search(self, queryset, name, value):
        if not value:
            return queryset
        query = Q(endpoint__name__icontains=value)
        for field in self.search_fields:
            query |= Q(**{f"{field}__icontains": value})
        return queryset.filter(query)


class _ClusterSearchMixin:
    """Shared free-text search across v2 object refs and cluster name."""

    search_fields: tuple[str, ...] = ("name",)

    def search(self, queryset, name, value):
        if not value:
            return queryset
        query = Q(cluster__name__icontains=value)
        for field in self.search_fields:
            query |= Q(**{f"{field}__icontains": value})
        return queryset.filter(query)


class CephClusterFilterSet(_EndpointSearchMixin, NetBoxModelFilterSet):
    class Meta:
        model = CephCluster
        fields = ("id", "endpoint", "proxmox_cluster", "name", "fsid", "health")


class CephDaemonFilterSet(_EndpointSearchMixin, NetBoxModelFilterSet):
    class Meta:
        model = CephDaemon
        fields = (
            "id",
            "endpoint",
            "cluster",
            "proxmox_node",
            "daemon_type",
            "name",
            "daemon_id",
            "state",
        )


class CephOSDFilterSet(_EndpointSearchMixin, NetBoxModelFilterSet):
    class Meta:
        model = CephOSD
        fields = (
            "id",
            "endpoint",
            "cluster",
            "proxmox_node",
            "osd_id",
            "up",
            "in_cluster",
            "device_class",
        )

    def search(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(name__icontains=value) | Q(host__icontains=value) | Q(endpoint__name__icontains=value)
        )


class CephPoolFilterSet(_EndpointSearchMixin, NetBoxModelFilterSet):
    class Meta:
        model = CephPool
        fields = ("id", "endpoint", "cluster", "name", "pool_id", "application")


class CephFilesystemFilterSet(_EndpointSearchMixin, NetBoxModelFilterSet):
    class Meta:
        model = CephFilesystem
        fields = ("id", "endpoint", "cluster", "name")


class CephCrushRuleFilterSet(_EndpointSearchMixin, NetBoxModelFilterSet):
    class Meta:
        model = CephCrushRule
        fields = ("id", "endpoint", "cluster", "name", "rule_id", "rule_type", "device_class")


class CephFlagFilterSet(_EndpointSearchMixin, NetBoxModelFilterSet):
    class Meta:
        model = CephFlag
        fields = ("id", "endpoint", "cluster", "name", "enabled")


class CephHealthCheckFilterSet(_EndpointSearchMixin, NetBoxModelFilterSet):
    class Meta:
        model = CephHealthCheck
        fields = ("id", "endpoint", "cluster", "name", "severity", "source")


class CephRGWRealmFilterSet(_EndpointSearchMixin, NetBoxModelFilterSet):
    class Meta:
        model = CephRGWRealm
        fields = ("id", "endpoint", "cluster", "name", "is_default")


class CephRGWZoneGroupFilterSet(_EndpointSearchMixin, NetBoxModelFilterSet):
    search_fields = ("name", "realm__name")

    class Meta:
        model = CephRGWZoneGroup
        fields = ("id", "endpoint", "cluster", "realm", "name", "is_master")


class CephRGWZoneFilterSet(_EndpointSearchMixin, NetBoxModelFilterSet):
    search_fields = ("name", "zonegroup__name")

    class Meta:
        model = CephRGWZone
        fields = ("id", "endpoint", "cluster", "zonegroup", "name")


class CephRGWPlacementTargetFilterSet(_EndpointSearchMixin, NetBoxModelFilterSet):
    search_fields = ("name", "zonegroup__name", "zone__name")

    class Meta:
        model = CephRGWPlacementTarget
        fields = ("id", "endpoint", "cluster", "zonegroup", "zone", "name")


class CephRGWUserReflectedFilterSet(_EndpointSearchMixin, NetBoxModelFilterSet):
    search_fields = ("uid", "display_name", "email", "tenant")

    class Meta:
        model = CephRGWUserReflected
        fields = (
            "id",
            "endpoint",
            "cluster",
            "uid",
            "tenant",
            "email",
            "suspended",
            "max_buckets",
        )


class CephRGWBucketReflectedFilterSet(_EndpointSearchMixin, NetBoxModelFilterSet):
    search_fields = ("name", "owner_uid", "tenant", "placement_rule")

    class Meta:
        model = CephRGWBucketReflected
        fields = (
            "id",
            "endpoint",
            "cluster",
            "name",
            "owner_uid",
            "tenant",
            "placement_rule",
            "versioning",
        )


class CephRBDImageFilterSet(_EndpointSearchMixin, NetBoxModelFilterSet):
    search_fields = ("name", "pool_name", "namespace", "image_id", "data_pool")

    class Meta:
        model = CephRBDImage
        fields = (
            "id",
            "endpoint",
            "cluster",
            "pool_name",
            "name",
            "namespace",
            "image_id",
            "data_pool",
        )


class CephRBDSnapshotFilterSet(_EndpointSearchMixin, NetBoxModelFilterSet):
    search_fields = ("name", "image__name", "image__pool_name")

    class Meta:
        model = CephRBDSnapshot
        fields = ("id", "endpoint", "cluster", "image", "name", "snap_id", "protected")


class CephRBDCloneFilterSet(_EndpointSearchMixin, NetBoxModelFilterSet):
    search_fields = (
        "child_pool_name",
        "child_name",
        "parent_image__name",
        "parent_snapshot__name",
    )

    class Meta:
        model = CephRBDClone
        fields = (
            "id",
            "endpoint",
            "cluster",
            "parent_image",
            "parent_snapshot",
            "child_pool_name",
            "child_name",
        )


class CephProviderFilterSet(_ClusterSearchMixin, NetBoxModelFilterSet):
    class Meta:
        model = CephProvider
        fields = ("id", "cluster", "kind", "name", "enabled", "is_default", "status")


class CephOperationFilterSet(_ClusterSearchMixin, NetBoxModelFilterSet):
    search_fields = ("target_kind", "target_ref", "source_branch_schema_id")

    class Meta:
        model = CephOperation
        fields = (
            "id",
            "cluster",
            "provider",
            "operation_type",
            "target_kind",
            "target_ref",
            "execution_node",
            "status",
            "is_destructive",
            "confirmation_required",
            "confirmed",
            "requested_by",
            "confirmed_by",
            "source_branch_schema_id",
        )


class CephPlanFilterSet(NetBoxModelFilterSet):
    class Meta:
        model = CephPlan
        fields = (
            "id",
            "operation",
            "status",
            "provider_target",
            "is_destructive",
            "backend_endpoint_id",
            "backend_endpoint_config_revision",
            "plugin_endpoint_id",
            "provider_id_snapshot",
            "provider_kind_snapshot",
            "execution_node",
        )

    def search(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(Q(summary__icontains=value) | Q(provider_target__icontains=value))


class CephOperationApprovalFilterSet(NetBoxModelFilterSet):
    class Meta:
        model = CephOperationApproval
        fields = (
            "id",
            "operation",
            "plan",
            "backend_endpoint_id",
            "backend_endpoint_config_revision",
            "plugin_endpoint_id",
            "provider_id_snapshot",
            "provider_kind_snapshot",
            "execution_node",
            "requester",
            "approver",
            "status",
            "backend_approval_id",
            "backend_run_id",
        )

    def search(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(backend_plan_id__icontains=value)
            | Q(backend_approval_id__icontains=value)
            | Q(backend_run_id__icontains=value)
            | Q(failure_code__icontains=value)
        )


class CephValidationResultFilterSet(NetBoxModelFilterSet):
    class Meta:
        model = CephValidationResult
        fields = ("id", "plan", "operation", "severity", "code", "target")

    def search(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(code__icontains=value) | Q(message__icontains=value) | Q(target__icontains=value)
        )


class CephOperationRunFilterSet(NetBoxModelFilterSet):
    class Meta:
        model = CephOperationRun
        fields = (
            "id",
            "operation",
            "plan",
            "provider",
            "status",
            "actor",
            "source_branch_schema_id",
            "provider_task_ref",
            "backend_endpoint_config_revision",
            "plugin_endpoint_id",
            "provider_id_snapshot",
            "provider_kind_snapshot",
            "execution_node",
        )

    def search(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(provider_task_ref__icontains=value) | Q(source_branch_schema_id__icontains=value)
        )


class CephDriftRecordFilterSet(_ClusterSearchMixin, NetBoxModelFilterSet):
    search_fields = ("object_kind", "object_ref")

    class Meta:
        model = CephDriftRecord
        fields = ("id", "cluster", "provider", "object_kind", "object_ref", "drift_status")


class CephMetricSnapshotFilterSet(_ClusterSearchMixin, NetBoxModelFilterSet):
    search_fields = ("object_ref", "source")

    class Meta:
        model = CephMetricSnapshot
        fields = ("id", "cluster", "provider", "scope", "object_ref", "source")


class CephPoolDesiredStateFilterSet(_ClusterSearchMixin, NetBoxModelFilterSet):
    search_fields = ("name", "crush_rule_name")

    class Meta:
        model = CephPoolDesiredState
        fields = (
            "id",
            "cluster",
            "provider",
            "name",
            "enabled",
            "application",
            "pg_autoscale_mode",
            "compression_mode",
        )


class CephFilesystemDesiredStateFilterSet(_ClusterSearchMixin, NetBoxModelFilterSet):
    search_fields = ("name", "mds_placement")

    class Meta:
        model = CephFilesystemDesiredState
        fields = ("id", "cluster", "provider", "name", "enabled", "metadata_pool")


class CephRBDImageDesiredStateFilterSet(_ClusterSearchMixin, NetBoxModelFilterSet):
    search_fields = ("name", "pool_name", "data_pool")

    class Meta:
        model = CephRBDImageDesiredState
        fields = (
            "id",
            "cluster",
            "provider",
            "pool_name",
            "name",
            "enabled",
            "clone_parent_image",
        )


class CephRBDSnapshotDesiredStateFilterSet(_ClusterSearchMixin, NetBoxModelFilterSet):
    search_fields = ("name", "image__name")

    class Meta:
        model = CephRBDSnapshotDesiredState
        fields = ("id", "cluster", "provider", "image", "name", "enabled", "protected")


class CephRGWRealmDesiredStateFilterSet(_ClusterSearchMixin, NetBoxModelFilterSet):
    class Meta:
        model = CephRGWRealmDesiredState
        fields = ("id", "cluster", "provider", "name", "enabled", "is_default")


class CephRGWZoneDesiredStateFilterSet(_ClusterSearchMixin, NetBoxModelFilterSet):
    search_fields = ("name", "realm__name", "zonegroup_name")

    class Meta:
        model = CephRGWZoneDesiredState
        fields = (
            "id",
            "cluster",
            "provider",
            "realm",
            "name",
            "enabled",
            "zonegroup_name",
            "is_master",
        )


class CephRGWUserDesiredStateFilterSet(_ClusterSearchMixin, NetBoxModelFilterSet):
    search_fields = ("uid", "display_name", "email", "tenant_name")

    class Meta:
        model = CephRGWUserDesiredState
        fields = (
            "id",
            "cluster",
            "provider",
            "uid",
            "enabled",
            "display_name",
            "email",
            "tenant_name",
            "suspended",
            "max_buckets",
        )


class CephRGWBucketDesiredStateFilterSet(_ClusterSearchMixin, NetBoxModelFilterSet):
    search_fields = ("name", "owner__uid", "placement_target")

    class Meta:
        model = CephRGWBucketDesiredState
        fields = (
            "id",
            "cluster",
            "provider",
            "owner",
            "name",
            "enabled",
            "placement_target",
            "versioning_enabled",
        )
