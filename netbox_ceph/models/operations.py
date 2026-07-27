"""Ceph v2 desired operation, plan, run, and drift models."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from netbox.models import NetBoxModel
from utilities.json import CustomFieldJSONEncoder

from netbox_ceph.choices import (
    CephApprovalStatusChoices,
    CephDriftStatusChoices,
    CephOperationStatusChoices,
    CephOperationTypeChoices,
    CephPlanStatusChoices,
    CephProviderKindChoices,
    CephValidationSeverityChoices,
)
from netbox_ceph.services.redaction import (
    SecretBearingIntentError,
    validate_secret_free_intent,
)

_EXECUTION_NODE_VALIDATOR = RegexValidator(
    regex=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    message=_("Enter an exact Proxmox node name (letters, numbers, '.', '_' and '-')."),
)


class CephOperation(NetBoxModel):
    """A requested NetBox-to-Ceph operation and its desired payload."""

    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="operations",
    )
    provider = models.ForeignKey(
        to="netbox_ceph.CephProvider",
        on_delete=models.SET_NULL,
        related_name="operations",
        null=True,
        blank=True,
    )
    operation_type = models.CharField(
        max_length=32,
        choices=CephOperationTypeChoices,
        default=CephOperationTypeChoices.TYPE_CUSTOM,
    )
    target_kind = models.CharField(max_length=128)
    target_ref = models.CharField(max_length=255, blank=True)
    execution_node = models.CharField(
        max_length=128,
        default="",
        validators=(_EXECUTION_NODE_VALIDATOR,),
        help_text=_("Exact Proxmox node that will execute the planned mutation."),
    )
    desired = models.JSONField(blank=True, default=dict, encoder=CustomFieldJSONEncoder)
    status = models.CharField(
        max_length=32,
        choices=CephOperationStatusChoices,
        default=CephOperationStatusChoices.STATUS_PENDING,
    )
    is_destructive = models.BooleanField(default=False)
    confirmation_required = models.BooleanField(default=False)
    confirmed = models.BooleanField(default=False)
    confirmed_by = models.ForeignKey(
        to="users.User",
        on_delete=models.SET_NULL,
        related_name="confirmed_ceph_operations",
        null=True,
        blank=True,
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    requested_by = models.ForeignKey(
        to="users.User",
        on_delete=models.SET_NULL,
        related_name="requested_ceph_operations",
        null=True,
        blank=True,
    )
    requested_by_username = models.CharField(max_length=150, blank=True)
    planning_reservation_id = models.UUIDField(null=True, blank=True, editable=False)
    planning_reservation_expires_at = models.DateTimeField(null=True, blank=True, editable=False)
    source_branch_schema_id = models.CharField(max_length=128, blank=True)

    class Meta:
        ordering = ("-created", "-pk")
        verbose_name = _("Ceph operation")
        verbose_name_plural = _("Ceph operations")
        permissions = (
            ("request_cephoperation", _("Can request and plan Ceph operations")),
            ("apply_cephoperation", _("Can submit approved Ceph operations")),
            ("approve_cephoperation", _("Can independently approve Ceph operations")),
        )

    def __str__(self) -> str:
        target = f"{self.target_kind}:{self.target_ref}" if self.target_ref else self.target_kind
        return f"{self.operation_type} {target}"

    def clean(self) -> None:
        """Reject provider identities that cannot use the Proxmox write contract."""

        super().clean()
        try:
            validate_secret_free_intent(self.desired)
        except SecretBearingIntentError as exc:
            raise ValidationError({"desired": _(str(exc))}) from exc
        if self.provider_id is None:
            raise ValidationError({"provider": _("A provider is required for Ceph operations.")})
        if self.cluster_id is not None and self.provider.cluster_id != self.cluster_id:
            raise ValidationError(
                {"provider": _("The provider must belong to the selected Ceph cluster.")}
            )
        if not self.provider.enabled:
            raise ValidationError({"provider": _("The selected provider is disabled.")})
        if self.provider.kind != CephProviderKindChoices.KIND_PROXMOX:
            raise ValidationError(
                {"provider": _("Only Proxmox providers support the durable write contract.")}
            )

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephoperation", args=[self.pk])


class CephPlan(NetBoxModel):
    """Provider-generated preview for a Ceph operation."""

    operation = models.ForeignKey(
        to="netbox_ceph.CephOperation",
        on_delete=models.PROTECT,
        related_name="plans",
    )
    status = models.CharField(
        max_length=32,
        choices=CephPlanStatusChoices,
        default=CephPlanStatusChoices.STATUS_DRAFT,
    )
    summary = models.TextField(blank=True)
    intended_changes = models.JSONField(blank=True, default=list, encoder=CustomFieldJSONEncoder)
    provider_target = models.CharField(max_length=255, blank=True)
    blast_radius = models.JSONField(blank=True, default=dict, encoder=CustomFieldJSONEncoder)
    expected_tasks = models.JSONField(blank=True, default=list, encoder=CustomFieldJSONEncoder)
    rollback_limits = models.TextField(blank=True)
    is_destructive = models.BooleanField(default=False)
    generated_at = models.DateTimeField(null=True, blank=True)
    raw = models.JSONField(blank=True, default=dict, encoder=CustomFieldJSONEncoder)
    backend_plan_id = models.CharField(max_length=64, blank=True, db_index=True)
    backend_plan_digest = models.CharField(max_length=64, blank=True)
    backend_endpoint_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    backend_endpoint_config_revision = models.CharField(max_length=64, blank=True)
    plugin_endpoint_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    provider_id_snapshot = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    provider_kind_snapshot = models.CharField(max_length=32, blank=True)
    execution_node = models.CharField(max_length=128, blank=True)
    local_config_digest = models.CharField(max_length=64, blank=True)
    requester = models.ForeignKey(
        to="users.User",
        on_delete=models.SET_NULL,
        related_name="requested_ceph_plans",
        null=True,
        blank=True,
    )
    requester_username = models.CharField(max_length=150, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    request_digest = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ("-generated_at", "-created", "-pk")
        verbose_name = _("Ceph plan")
        verbose_name_plural = _("Ceph plans")

    def __str__(self) -> str:
        return f"Plan for {self.operation}"

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephplan", args=[self.pk])


class CephOperationApproval(NetBoxModel):
    """Token-free audit record for a backend-issued two-person approval."""

    operation = models.ForeignKey(
        to="netbox_ceph.CephOperation",
        on_delete=models.PROTECT,
        related_name="approvals",
    )
    plan = models.OneToOneField(
        to="netbox_ceph.CephPlan",
        on_delete=models.PROTECT,
        related_name="approval",
    )
    backend_plan_id = models.CharField(max_length=64, db_index=True)
    backend_plan_digest = models.CharField(max_length=64)
    backend_endpoint_id = models.PositiveBigIntegerField(db_index=True)
    backend_endpoint_config_revision = models.CharField(max_length=64)
    plugin_endpoint_id = models.PositiveBigIntegerField(db_index=True)
    provider_id_snapshot = models.PositiveBigIntegerField(db_index=True)
    provider_kind_snapshot = models.CharField(max_length=32)
    execution_node = models.CharField(max_length=128)
    local_config_digest = models.CharField(max_length=64)
    requester = models.ForeignKey(
        to="users.User",
        on_delete=models.SET_NULL,
        related_name="requested_ceph_approvals",
        null=True,
        blank=True,
    )
    requester_username = models.CharField(max_length=150, blank=True)
    approver = models.ForeignKey(
        to="users.User",
        on_delete=models.SET_NULL,
        related_name="approved_ceph_operations",
        null=True,
        blank=True,
    )
    approver_username = models.CharField(max_length=150, blank=True)
    backend_approval_id = models.CharField(max_length=64, blank=True, db_index=True)
    issuance_reservation_id = models.UUIDField(
        null=True,
        blank=True,
        editable=False,
        unique=True,
    )
    issuance_reservation_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=32,
        choices=CephApprovalStatusChoices,
        default=CephApprovalStatusChoices.STATUS_ISSUED,
    )
    backend_run_id = models.CharField(max_length=64, blank=True, db_index=True)
    failure_code = models.CharField(max_length=128, blank=True)
    failure_detail = models.TextField(blank=True)

    class Meta:
        ordering = ("-created", "-pk")
        verbose_name = _("Ceph operation approval")
        verbose_name_plural = _("Ceph operation approvals")

    def __str__(self) -> str:
        return f"Approval for {self.plan}"

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephoperationapproval", args=[self.pk])


class CephValidationResult(NetBoxModel):
    """Validation finding attached to an operation and/or generated plan."""

    plan = models.ForeignKey(
        to="netbox_ceph.CephPlan",
        on_delete=models.SET_NULL,
        related_name="validations",
        null=True,
        blank=True,
    )
    operation = models.ForeignKey(
        to="netbox_ceph.CephOperation",
        on_delete=models.SET_NULL,
        related_name="validations",
        null=True,
        blank=True,
    )
    severity = models.CharField(
        max_length=32,
        choices=CephValidationSeverityChoices,
        default=CephValidationSeverityChoices.SEVERITY_INFO,
    )
    code = models.CharField(max_length=128)
    message = models.TextField()
    target = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ("severity", "code", "pk")
        verbose_name = _("Ceph validation result")
        verbose_name_plural = _("Ceph validation results")

    def __str__(self) -> str:
        return f"{self.severity}: {self.code}"

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephvalidationresult", args=[self.pk])


class CephOperationRun(NetBoxModel):
    """An attempt to apply a planned Ceph operation through a provider."""

    operation = models.ForeignKey(
        to="netbox_ceph.CephOperation",
        on_delete=models.PROTECT,
        related_name="runs",
    )
    plan = models.ForeignKey(
        to="netbox_ceph.CephPlan",
        on_delete=models.PROTECT,
        related_name="runs",
        null=True,
        blank=True,
    )
    provider = models.ForeignKey(
        to="netbox_ceph.CephProvider",
        on_delete=models.SET_NULL,
        related_name="runs",
        null=True,
        blank=True,
    )
    approval = models.OneToOneField(
        to="netbox_ceph.CephOperationApproval",
        on_delete=models.PROTECT,
        related_name="run",
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=32,
        choices=CephOperationStatusChoices,
        default=CephOperationStatusChoices.STATUS_PENDING,
    )
    actor = models.ForeignKey(
        to="users.User",
        on_delete=models.SET_NULL,
        related_name="ceph_operation_runs",
        null=True,
        blank=True,
    )
    actor_username = models.CharField(max_length=150, blank=True)
    source_branch_schema_id = models.CharField(max_length=128, blank=True)
    provider_task_ref = models.CharField(max_length=255, blank=True)
    backend_run_id = models.CharField(max_length=64, blank=True, db_index=True)
    backend_endpoint_config_revision = models.CharField(max_length=64, blank=True)
    plugin_endpoint_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    provider_id_snapshot = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    provider_kind_snapshot = models.CharField(max_length=32, blank=True)
    execution_node = models.CharField(max_length=128, blank=True)
    local_config_digest = models.CharField(max_length=64, blank=True)
    outcome_unknown = models.BooleanField(default=False)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(blank=True, default=dict, encoder=CustomFieldJSONEncoder)
    warnings = models.JSONField(blank=True, default=list, encoder=CustomFieldJSONEncoder)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ("-started_at", "-created", "-pk")
        verbose_name = _("Ceph operation run")
        verbose_name_plural = _("Ceph operation runs")

    def __str__(self) -> str:
        suffix = self.provider_task_ref or self.pk or "pending"
        return f"Run {suffix} for {self.operation}"

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephoperationrun", args=[self.pk])


class CephDriftRecord(NetBoxModel):
    """Latest known drift state for one desired/actual Ceph object identity."""

    cluster = models.ForeignKey(
        to="netbox_ceph.CephCluster",
        on_delete=models.CASCADE,
        related_name="drift_records",
    )
    provider = models.ForeignKey(
        to="netbox_ceph.CephProvider",
        on_delete=models.SET_NULL,
        related_name="drift_records",
        null=True,
        blank=True,
    )
    object_kind = models.CharField(max_length=128)
    object_ref = models.CharField(max_length=255)
    drift_status = models.CharField(
        max_length=32,
        choices=CephDriftStatusChoices,
        default=CephDriftStatusChoices.STATUS_UNKNOWN,
    )
    desired_summary = models.JSONField(blank=True, default=dict, encoder=CustomFieldJSONEncoder)
    actual_summary = models.JSONField(blank=True, default=dict, encoder=CustomFieldJSONEncoder)
    detected_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("cluster", "object_kind", "object_ref")
        verbose_name = _("Ceph drift record")
        verbose_name_plural = _("Ceph drift records")
        constraints = [
            models.UniqueConstraint(
                fields=("cluster", "object_kind", "object_ref"),
                name="netbox_ceph_drift_record_identity",
            )
        ]

    def __str__(self) -> str:
        return f"{self.object_kind}:{self.object_ref} {self.drift_status}"

    def get_absolute_url(self) -> str:
        return reverse("plugins:netbox_ceph:cephdriftrecord", args=[self.pk])
