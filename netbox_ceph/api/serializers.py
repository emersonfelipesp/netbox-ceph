"""DRF serializers for read-only Ceph inventory models."""

from __future__ import annotations

from netbox.api.serializers import NetBoxModelSerializer
from rest_framework import serializers

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
    CephPluginSettings,
    CephPool,
    CephPoolDesiredState,
    CephProvider,
    CephRBDImageDesiredState,
    CephRBDSnapshotDesiredState,
    CephRGWBucketDesiredState,
    CephRGWRealmDesiredState,
    CephRGWUserDesiredState,
    CephRGWZoneDesiredState,
    CephValidationResult,
)


class CephPluginSettingsSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_ceph-api:cephpluginsettings-detail"
    )

    class Meta:
        model = CephPluginSettings
        fields = (
            "id",
            "url",
            "display",
            "branching_enabled",
            "branch_name_prefix",
            "branch_on_conflict",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display")


class CephClusterSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_ceph-api:cephcluster-detail"
    )

    class Meta:
        model = CephCluster
        fields = (
            "id",
            "url",
            "display",
            "endpoint",
            "proxmox_cluster",
            "name",
            "fsid",
            "health",
            "quorum_names",
            "status",
            "last_seen_at",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "name", "health")


class CephDaemonSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_ceph-api:cephdaemon-detail"
    )

    class Meta:
        model = CephDaemon
        fields = (
            "id",
            "url",
            "display",
            "endpoint",
            "cluster",
            "proxmox_node",
            "daemon_type",
            "name",
            "daemon_id",
            "host",
            "state",
            "status",
            "version",
            "metadata",
            "last_seen_at",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "daemon_type", "name", "state")


class CephOSDSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_ceph-api:cephosd-detail"
    )

    class Meta:
        model = CephOSD
        fields = (
            "id",
            "url",
            "display",
            "endpoint",
            "cluster",
            "proxmox_node",
            "osd_id",
            "name",
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
            "metadata",
            "last_seen_at",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "osd_id", "up", "in_cluster")


class CephPoolSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_ceph-api:cephpool-detail"
    )

    class Meta:
        model = CephPool
        fields = (
            "id",
            "url",
            "display",
            "endpoint",
            "cluster",
            "name",
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
            "status",
            "last_seen_at",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "name")


class CephFilesystemSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_ceph-api:cephfilesystem-detail"
    )

    class Meta:
        model = CephFilesystem
        fields = (
            "id",
            "url",
            "display",
            "endpoint",
            "cluster",
            "name",
            "metadata_pool",
            "data_pools",
            "standby_count_wanted",
            "status",
            "last_seen_at",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "name")


class CephCrushRuleSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_ceph-api:cephcrushrule-detail"
    )

    class Meta:
        model = CephCrushRule
        fields = (
            "id",
            "url",
            "display",
            "endpoint",
            "cluster",
            "name",
            "rule_id",
            "rule_type",
            "device_class",
            "steps",
            "raw",
            "last_seen_at",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "name", "rule_type")


class CephFlagSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_ceph-api:cephflag-detail"
    )

    class Meta:
        model = CephFlag
        fields = (
            "id",
            "url",
            "display",
            "endpoint",
            "cluster",
            "name",
            "enabled",
            "value",
            "raw",
            "last_seen_at",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "name", "enabled")


class CephHealthCheckSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_ceph-api:cephhealthcheck-detail"
    )

    class Meta:
        model = CephHealthCheck
        fields = (
            "id",
            "url",
            "display",
            "endpoint",
            "cluster",
            "name",
            "severity",
            "summary",
            "detail",
            "source",
            "first_seen_at",
            "last_seen_at",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "name", "severity")


class CephProviderSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_ceph-api:cephprovider-detail"
    )

    class Meta:
        model = CephProvider
        fields = (
            "id",
            "url",
            "display",
            "cluster",
            "kind",
            "name",
            "enabled",
            "is_default",
            "base_url",
            "verify_ssl",
            "credential_ref",
            "capabilities",
            "status",
            "status_detail",
            "last_checked_at",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "name", "kind", "status")


class CephOperationSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_ceph-api:cephoperation-detail"
    )

    class Meta:
        model = CephOperation
        fields = (
            "id",
            "url",
            "display",
            "cluster",
            "provider",
            "operation_type",
            "target_kind",
            "target_ref",
            "desired",
            "status",
            "is_destructive",
            "confirmation_required",
            "confirmed",
            "confirmed_by",
            "confirmed_at",
            "requested_by",
            "source_branch_schema_id",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "operation_type", "target_kind", "status")


class CephPlanSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_ceph-api:cephplan-detail"
    )

    class Meta:
        model = CephPlan
        fields = (
            "id",
            "url",
            "display",
            "operation",
            "status",
            "summary",
            "intended_changes",
            "provider_target",
            "blast_radius",
            "expected_tasks",
            "rollback_limits",
            "is_destructive",
            "generated_at",
            "raw",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "operation", "status")


class CephValidationResultSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_ceph-api:cephvalidationresult-detail"
    )

    class Meta:
        model = CephValidationResult
        fields = (
            "id",
            "url",
            "display",
            "plan",
            "operation",
            "severity",
            "code",
            "message",
            "target",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "severity", "code")


class CephOperationRunSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_ceph-api:cephoperationrun-detail"
    )

    class Meta:
        model = CephOperationRun
        fields = (
            "id",
            "url",
            "display",
            "operation",
            "plan",
            "provider",
            "status",
            "actor",
            "source_branch_schema_id",
            "provider_task_ref",
            "started_at",
            "finished_at",
            "result",
            "warnings",
            "error",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "operation", "status")


class CephDriftRecordSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_ceph-api:cephdriftrecord-detail"
    )

    class Meta:
        model = CephDriftRecord
        fields = (
            "id",
            "url",
            "display",
            "cluster",
            "provider",
            "object_kind",
            "object_ref",
            "drift_status",
            "desired_summary",
            "actual_summary",
            "detected_at",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "object_kind", "object_ref", "drift_status")


class CephMetricSnapshotSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_ceph-api:cephmetricsnapshot-detail"
    )

    class Meta:
        model = CephMetricSnapshot
        fields = (
            "id",
            "url",
            "display",
            "cluster",
            "provider",
            "scope",
            "object_ref",
            "metrics",
            "source",
            "captured_at",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "scope", "object_ref", "captured_at")


class CephPoolDesiredStateSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_ceph-api:cephpooldesiredstate-detail"
    )

    class Meta:
        model = CephPoolDesiredState
        fields = (
            "id",
            "url",
            "display",
            "cluster",
            "provider",
            "name",
            "enabled",
            "size",
            "min_size",
            "pg_autoscale_mode",
            "crush_rule_name",
            "application",
            "target_size_ratio",
            "quota_max_bytes",
            "quota_max_objects",
            "compression_mode",
            "erasure_code_profile",
            "parameters",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "name", "application", "enabled")


class CephFilesystemDesiredStateSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_ceph-api:cephfilesystemdesiredstate-detail"
    )

    class Meta:
        model = CephFilesystemDesiredState
        fields = (
            "id",
            "url",
            "display",
            "cluster",
            "provider",
            "name",
            "enabled",
            "metadata_pool",
            "data_pools",
            "mds_placement",
            "standby_count",
            "max_mds",
            "quota_max_bytes",
            "parameters",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "name", "enabled")


class CephRBDImageDesiredStateSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_ceph-api:cephrbdimagedesiredstate-detail"
    )

    class Meta:
        model = CephRBDImageDesiredState
        fields = (
            "id",
            "url",
            "display",
            "cluster",
            "provider",
            "pool_name",
            "name",
            "enabled",
            "size_bytes",
            "features",
            "object_size",
            "stripe_unit",
            "stripe_count",
            "data_pool",
            "clone_parent_image",
            "clone_parent_snapshot",
            "metadata",
            "parameters",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "name", "pool_name", "enabled")


class CephRBDSnapshotDesiredStateSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_ceph-api:cephrbdsnapshotdesiredstate-detail"
    )

    class Meta:
        model = CephRBDSnapshotDesiredState
        fields = (
            "id",
            "url",
            "display",
            "cluster",
            "provider",
            "image",
            "name",
            "enabled",
            "protected",
            "parameters",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "name", "image", "enabled")


class CephRGWRealmDesiredStateSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_ceph-api:cephrgwrealmdesiredstate-detail"
    )

    class Meta:
        model = CephRGWRealmDesiredState
        fields = (
            "id",
            "url",
            "display",
            "cluster",
            "provider",
            "name",
            "enabled",
            "is_default",
            "parameters",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "name", "enabled", "is_default")


class CephRGWZoneDesiredStateSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_ceph-api:cephrgwzonedesiredstate-detail"
    )

    class Meta:
        model = CephRGWZoneDesiredState
        fields = (
            "id",
            "url",
            "display",
            "cluster",
            "provider",
            "name",
            "enabled",
            "realm",
            "zonegroup_name",
            "is_master",
            "endpoints",
            "placement_targets",
            "parameters",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "name", "realm", "enabled")


class CephRGWUserDesiredStateSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_ceph-api:cephrgwuserdesiredstate-detail"
    )

    class Meta:
        model = CephRGWUserDesiredState
        fields = (
            "id",
            "url",
            "display",
            "cluster",
            "provider",
            "uid",
            "enabled",
            "display_name",
            "email",
            "tenant_name",
            "suspended",
            "max_buckets",
            "quota_max_size_bytes",
            "quota_max_objects",
            "credential_ref",
            "parameters",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "uid", "enabled", "suspended")


class CephRGWBucketDesiredStateSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_ceph-api:cephrgwbucketdesiredstate-detail"
    )

    class Meta:
        model = CephRGWBucketDesiredState
        fields = (
            "id",
            "url",
            "display",
            "cluster",
            "provider",
            "name",
            "enabled",
            "owner",
            "placement_target",
            "versioning_enabled",
            "quota_max_size_bytes",
            "quota_max_objects",
            "lifecycle_policy",
            "parameters",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "name", "owner", "enabled")
