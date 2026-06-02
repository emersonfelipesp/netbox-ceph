"""NetBox forms for netbox-ceph.

v1 reflects Proxmox-managed Ceph state read-only, so the only editable form
is ``CephPluginSettingsForm`` for branch-aware sync behavior. All other forms
are filter-only.
"""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _
from netbox.forms import NetBoxModelFilterSetForm, NetBoxModelForm
from utilities.forms.fields import DynamicModelChoiceField

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
    CephValidationResult,
)


class CephPluginSettingsForm(NetBoxModelForm):
    class Meta:
        model = CephPluginSettings
        fields = (
            "branching_enabled",
            "branch_name_prefix",
            "branch_on_conflict",
            "tags",
        )


class _EndpointFilterMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from netbox_proxbox.models import ProxmoxEndpoint  # noqa: PLC0415

        self.fields["endpoint"] = DynamicModelChoiceField(
            queryset=ProxmoxEndpoint.objects.all(),
            required=False,
            label=_("Proxmox endpoint"),
        )


class CephClusterFilterForm(_EndpointFilterMixin, NetBoxModelFilterSetForm):
    model = CephCluster
    name = forms.CharField(required=False)
    fsid = forms.CharField(required=False)
    health = forms.CharField(required=False)


class CephDaemonFilterForm(_EndpointFilterMixin, NetBoxModelFilterSetForm):
    model = CephDaemon
    daemon_type = forms.CharField(required=False)
    name = forms.CharField(required=False)
    state = forms.CharField(required=False)


class CephOSDFilterForm(_EndpointFilterMixin, NetBoxModelFilterSetForm):
    model = CephOSD
    osd_id = forms.IntegerField(required=False)
    up = forms.NullBooleanField(required=False)
    in_cluster = forms.NullBooleanField(required=False)
    device_class = forms.CharField(required=False)


class CephPoolFilterForm(_EndpointFilterMixin, NetBoxModelFilterSetForm):
    model = CephPool
    name = forms.CharField(required=False)
    application = forms.CharField(required=False)


class CephFilesystemFilterForm(_EndpointFilterMixin, NetBoxModelFilterSetForm):
    model = CephFilesystem
    name = forms.CharField(required=False)


class CephCrushRuleFilterForm(_EndpointFilterMixin, NetBoxModelFilterSetForm):
    model = CephCrushRule
    name = forms.CharField(required=False)
    rule_type = forms.CharField(required=False)
    device_class = forms.CharField(required=False)


class CephFlagFilterForm(_EndpointFilterMixin, NetBoxModelFilterSetForm):
    model = CephFlag
    name = forms.CharField(required=False)
    enabled = forms.NullBooleanField(required=False)


class CephHealthCheckFilterForm(_EndpointFilterMixin, NetBoxModelFilterSetForm):
    model = CephHealthCheck
    name = forms.CharField(required=False)
    severity = forms.CharField(required=False)
    source = forms.CharField(required=False)


class CephProviderForm(NetBoxModelForm):
    class Meta:
        model = CephProvider
        fields = (
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
        )


class CephOperationForm(NetBoxModelForm):
    class Meta:
        model = CephOperation
        fields = (
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
        )


class CephPlanForm(NetBoxModelForm):
    class Meta:
        model = CephPlan
        fields = (
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
        )


class CephValidationResultForm(NetBoxModelForm):
    class Meta:
        model = CephValidationResult
        fields = (
            "plan",
            "operation",
            "severity",
            "code",
            "message",
            "target",
            "tags",
        )


class CephOperationRunForm(NetBoxModelForm):
    class Meta:
        model = CephOperationRun
        fields = (
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
        )


class CephProviderFilterForm(NetBoxModelFilterSetForm):
    model = CephProvider
    cluster = DynamicModelChoiceField(queryset=CephCluster.objects.all(), required=False)
    kind = forms.CharField(required=False)
    name = forms.CharField(required=False)
    enabled = forms.NullBooleanField(required=False)
    is_default = forms.NullBooleanField(required=False)
    status = forms.CharField(required=False)


class CephOperationFilterForm(NetBoxModelFilterSetForm):
    model = CephOperation
    cluster = DynamicModelChoiceField(queryset=CephCluster.objects.all(), required=False)
    provider = DynamicModelChoiceField(queryset=CephProvider.objects.all(), required=False)
    operation_type = forms.CharField(required=False)
    target_kind = forms.CharField(required=False)
    target_ref = forms.CharField(required=False)
    status = forms.CharField(required=False)
    is_destructive = forms.NullBooleanField(required=False)
    confirmation_required = forms.NullBooleanField(required=False)
    confirmed = forms.NullBooleanField(required=False)
    source_branch_schema_id = forms.CharField(required=False)


class CephPlanFilterForm(NetBoxModelFilterSetForm):
    model = CephPlan
    operation = DynamicModelChoiceField(queryset=CephOperation.objects.all(), required=False)
    status = forms.CharField(required=False)
    provider_target = forms.CharField(required=False)
    is_destructive = forms.NullBooleanField(required=False)


class CephValidationResultFilterForm(NetBoxModelFilterSetForm):
    model = CephValidationResult
    plan = DynamicModelChoiceField(queryset=CephPlan.objects.all(), required=False)
    operation = DynamicModelChoiceField(queryset=CephOperation.objects.all(), required=False)
    severity = forms.CharField(required=False)
    code = forms.CharField(required=False)
    target = forms.CharField(required=False)


class CephOperationRunFilterForm(NetBoxModelFilterSetForm):
    model = CephOperationRun
    operation = DynamicModelChoiceField(queryset=CephOperation.objects.all(), required=False)
    plan = DynamicModelChoiceField(queryset=CephPlan.objects.all(), required=False)
    provider = DynamicModelChoiceField(queryset=CephProvider.objects.all(), required=False)
    status = forms.CharField(required=False)
    source_branch_schema_id = forms.CharField(required=False)
    provider_task_ref = forms.CharField(required=False)


class CephDriftRecordFilterForm(NetBoxModelFilterSetForm):
    model = CephDriftRecord
    cluster = DynamicModelChoiceField(queryset=CephCluster.objects.all(), required=False)
    provider = DynamicModelChoiceField(queryset=CephProvider.objects.all(), required=False)
    object_kind = forms.CharField(required=False)
    object_ref = forms.CharField(required=False)
    drift_status = forms.CharField(required=False)


class CephMetricSnapshotFilterForm(NetBoxModelFilterSetForm):
    model = CephMetricSnapshot
    cluster = DynamicModelChoiceField(queryset=CephCluster.objects.all(), required=False)
    provider = DynamicModelChoiceField(queryset=CephProvider.objects.all(), required=False)
    scope = forms.CharField(required=False)
    object_ref = forms.CharField(required=False)
    source = forms.CharField(required=False)


# ---------------------------------------------------------------------------
# Desired-state config forms (writable)
# ---------------------------------------------------------------------------


class CephPoolDesiredStateForm(NetBoxModelForm):
    class Meta:
        model = CephPoolDesiredState
        fields = (
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
        )


class CephFilesystemDesiredStateForm(NetBoxModelForm):
    class Meta:
        model = CephFilesystemDesiredState
        fields = (
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
        )


class CephRBDImageDesiredStateForm(NetBoxModelForm):
    class Meta:
        model = CephRBDImageDesiredState
        fields = (
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
        )


class CephRBDSnapshotDesiredStateForm(NetBoxModelForm):
    class Meta:
        model = CephRBDSnapshotDesiredState
        fields = (
            "cluster",
            "provider",
            "image",
            "name",
            "enabled",
            "protected",
            "parameters",
            "tags",
        )


class CephPoolDesiredStateFilterForm(NetBoxModelFilterSetForm):
    model = CephPoolDesiredState
    cluster = DynamicModelChoiceField(queryset=CephCluster.objects.all(), required=False)
    provider = DynamicModelChoiceField(queryset=CephProvider.objects.all(), required=False)
    name = forms.CharField(required=False)
    application = forms.CharField(required=False)
    pg_autoscale_mode = forms.CharField(required=False)
    enabled = forms.NullBooleanField(required=False)


class CephFilesystemDesiredStateFilterForm(NetBoxModelFilterSetForm):
    model = CephFilesystemDesiredState
    cluster = DynamicModelChoiceField(queryset=CephCluster.objects.all(), required=False)
    provider = DynamicModelChoiceField(queryset=CephProvider.objects.all(), required=False)
    name = forms.CharField(required=False)
    enabled = forms.NullBooleanField(required=False)


class CephRBDImageDesiredStateFilterForm(NetBoxModelFilterSetForm):
    model = CephRBDImageDesiredState
    cluster = DynamicModelChoiceField(queryset=CephCluster.objects.all(), required=False)
    provider = DynamicModelChoiceField(queryset=CephProvider.objects.all(), required=False)
    pool_name = forms.CharField(required=False)
    name = forms.CharField(required=False)
    enabled = forms.NullBooleanField(required=False)


class CephRBDSnapshotDesiredStateFilterForm(NetBoxModelFilterSetForm):
    model = CephRBDSnapshotDesiredState
    cluster = DynamicModelChoiceField(queryset=CephCluster.objects.all(), required=False)
    provider = DynamicModelChoiceField(queryset=CephProvider.objects.all(), required=False)
    image = DynamicModelChoiceField(
        queryset=CephRBDImageDesiredState.objects.all(), required=False
    )
    name = forms.CharField(required=False)
    enabled = forms.NullBooleanField(required=False)
    protected = forms.NullBooleanField(required=False)
