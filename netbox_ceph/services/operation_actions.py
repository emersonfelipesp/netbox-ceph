"""Fail-closed Ceph plan, independent approval, apply, and recovery actions."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from netbox_ceph.choices import (
    CephApprovalStatusChoices,
    CephOperationStatusChoices,
    CephOperationTypeChoices,
    CephPlanStatusChoices,
    CephProviderKindChoices,
    CephValidationSeverityChoices,
)
from netbox_ceph.models import (
    CephCluster,
    CephOperation,
    CephOperationApproval,
    CephOperationRun,
    CephPlan,
    CephProvider,
    CephValidationResult,
)
from netbox_ceph.services import ceph_v2_responses
from netbox_ceph.services.http_client import CephBackendError
from netbox_ceph.services.orchestrator import (
    CephOrchestratorClient,
    CephOrchestratorHTTPError,
    CephOrchestratorTimeout,
    CephOrchestratorUnavailable,
    CephOrchestratorUnsupported,
)
from netbox_ceph.services.redaction import (
    SecretBearingIntentError,
    redact_secrets,
    redact_text,
    validate_secret_free_intent,
)

_REQUEST_PERMISSION = "netbox_ceph.request_cephoperation"
_APPLY_PERMISSION = "netbox_ceph.apply_cephoperation"
_APPROVE_PERMISSION = "netbox_ceph.approve_cephoperation"
_TERMINAL_RUN_STATUSES = {
    CephOperationStatusChoices.STATUS_SUCCEEDED,
    CephOperationStatusChoices.STATUS_FAILED,
    CephOperationStatusChoices.STATUS_CANCELLED,
    CephOperationStatusChoices.STATUS_UNSUPPORTED,
}
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_NODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PLAN_RESERVATION_TTL = timedelta(minutes=10)
_APPROVAL_ISSUANCE_TTL = timedelta(minutes=10)
_PROXMOX_WRITER_ACTIONS: dict[str, frozenset[str]] = {
    "pool": frozenset({"create", "update", "delete", "noop"}),
    "flag": frozenset({"create", "update", "delete", "noop"}),
    "osd": frozenset({"create", "update", "delete", "noop"}),
    "mon": frozenset({"create", "delete", "noop"}),
    "mgr": frozenset({"create", "delete", "noop"}),
    "mds": frozenset({"create", "delete", "noop"}),
    "filesystem": frozenset({"create", "noop"}),
}
_PROXMOX_WRITER_FIELDS: dict[tuple[str, str], frozenset[str]] = {
    ("pool", "create"): frozenset(
        {
            "add_storages",
            "application",
            "crush_rule",
            "erasure_coding",
            "min_size",
            "pg_autoscale_mode",
            "pg_num",
            "pg_num_min",
            "size",
            "target_size",
            "target_size_ratio",
        }
    ),
    ("pool", "update"): frozenset(
        {
            "application",
            "crush_rule",
            "min_size",
            "pg_autoscale_mode",
            "pg_num",
            "pg_num_min",
            "size",
            "target_size",
            "target_size_ratio",
        }
    ),
    ("pool", "delete"): frozenset({"force", "remove_ecprofile", "remove_storages"}),
    ("osd", "create"): frozenset(
        {
            "dev",
            "crush_device_class",
            "db_dev",
            "db_dev_size",
            "encrypted",
            "osds_per_device",
            "wal_dev",
            "wal_dev_size",
        }
    ),
    ("osd", "update"): frozenset({"in"}),
    ("osd", "delete"): frozenset({"cleanup"}),
    ("mon", "create"): frozenset({"mon_address"}),
    ("mds", "create"): frozenset({"hotstandby"}),
    ("filesystem", "create"): frozenset({"add_storage", "pg_num"}),
}
_PROXMOX_WRITER_REQUIRED_FIELDS: dict[tuple[str, str], frozenset[str]] = {
    ("osd", "create"): frozenset({"dev"}),
    ("osd", "update"): frozenset({"in"}),
}
_PROXMOX_WRITER_BOOL_FIELDS = frozenset(
    {
        "add_storage",
        "add_storages",
        "cleanup",
        "encrypted",
        "force",
        "hotstandby",
        "in",
        "remove_ecprofile",
        "remove_storages",
    }
)
_PROXMOX_WRITER_INT_FIELDS = frozenset(
    {"min_size", "osds_per_device", "pg_num", "pg_num_min", "size"}
)
_PROXMOX_WRITER_FLOAT_FIELDS = frozenset({"db_dev_size", "target_size_ratio", "wal_dev_size"})
_PROXMOX_WRITER_STRING_FIELDS = frozenset(
    {
        "application",
        "crush_device_class",
        "crush_rule",
        "db_dev",
        "dev",
        "erasure_coding",
        "mon_address",
        "pg_autoscale_mode",
        "target_size",
        "wal_dev",
    }
)
_PROXMOX_OPERATION_FIELDS = frozenset(
    {
        "id",
        "provider",
        "kind",
        "target_ref",
        "action",
        "node",
        "is_destructive",
        "supported",
        "blocked_reason",
        "before_summary",
        "after_summary",
        "metadata",
    }
)
_ACTIVE_APPROVAL_STATUSES = {
    CephApprovalStatusChoices.STATUS_ISSUING,
    CephApprovalStatusChoices.STATUS_ISSUED,
    CephApprovalStatusChoices.STATUS_APPLYING,
    CephApprovalStatusChoices.STATUS_OUTCOME_UNKNOWN,
}
_ACTIVE_OPERATION_STATUSES = {
    CephOperationStatusChoices.STATUS_PLANNING,
    CephOperationStatusChoices.STATUS_APPLYING,
    CephOperationStatusChoices.STATUS_OUTCOME_UNKNOWN,
}

# Tests can replace this with a callback that raises at a named checkpoint.
# Every checkpoint is inside ``transaction.atomic()`` and therefore proves
# partial audit-chain writes roll back together.
_TRANSITION_FAULT_INJECTOR: Callable[[str], None] | None = None


class OperationActionError(Exception):
    """Typed action failure safe for an API response or UI flash message."""

    def __init__(
        self,
        message: Any,
        *,
        kind: str = "backend",
        reason: str = "operation_failed",
        recovery: dict[str, str | int] | None = None,
        run: CephOperationRun | None = None,
    ) -> None:
        super().__init__(str(message))
        self.message = str(message)
        self.kind = kind
        self.reason = reason
        self.recovery = recovery or {}
        self.run = run


def _transition_checkpoint(name: str) -> None:
    injector = _TRANSITION_FAULT_INJECTOR
    if injector is not None:
        injector(name)


def _snapshot_value(value: Any) -> Any:
    """Return a deterministic JSON value without exposing it outside a digest."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(key): _snapshot_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_snapshot_value(item) for item in value]
    return str(value)


def _local_config_digest(*, cluster: Any, provider: Any) -> str:
    """Fingerprint the local routing/provider configuration used for a plan."""

    endpoint = getattr(cluster, "endpoint", None)
    endpoint_config = {
        name: _snapshot_value(getattr(endpoint, name, None))
        for name in (
            "pk",
            "backend_key",
            "name",
            "ip_address_id",
            "domain",
            "port",
            "mode",
            "environment",
            "username",
            "password_enc",
            "token_name",
            "token_value_enc",
            "pushed_credential_fingerprint",
            "verify_ssl",
            "allow_writes",
            "access_methods",
            "timeout",
            "max_retries",
            "retry_backoff",
            "enabled",
        )
    }
    provider_config = {
        name: _snapshot_value(getattr(provider, name, None))
        for name in (
            "pk",
            "cluster_id",
            "kind",
            "name",
            "enabled",
            "base_url",
            "verify_ssl",
            "credential_ref",
            "capabilities",
        )
    }
    return request_digest(
        {
            "cluster_id": getattr(cluster, "pk", None),
            "plugin_endpoint": endpoint_config,
            "provider": provider_config,
        }
    )


def _binding_snapshot(
    operation: CephOperation,
    *,
    cluster: Any | None = None,
    provider: CephProvider | None = None,
) -> dict[str, Any]:
    """Capture the exact local routing identity a backend authority may use."""

    cluster = cluster or getattr(operation, "cluster", None)
    provider = provider or getattr(operation, "provider", None)
    endpoint_id = getattr(cluster, "endpoint_id", None)
    provider_id = getattr(provider, "pk", None)
    execution_node = str(getattr(operation, "execution_node", "") or "").strip()
    if (
        isinstance(endpoint_id, bool)
        or not isinstance(endpoint_id, int)
        or endpoint_id <= 0
        or isinstance(provider_id, bool)
        or not isinstance(provider_id, int)
        or provider_id <= 0
    ):
        raise OperationActionError(
            "The operation has no durable endpoint/provider binding.",
            kind="invalid",
            reason="local_binding_missing",
        )
    if _NODE_PATTERN.fullmatch(execution_node) is None:
        raise OperationActionError(
            "An exact valid Proxmox execution node is required.",
            kind="invalid",
            reason="execution_node_required",
        )
    return {
        "plugin_endpoint_id": endpoint_id,
        "provider_id_snapshot": provider_id,
        "provider_kind_snapshot": str(getattr(provider, "kind", "") or ""),
        "execution_node": execution_node,
        "local_config_digest": _local_config_digest(cluster=cluster, provider=provider),
    }


def _binding_matches(authority: Any, binding: dict[str, Any]) -> bool:
    return all(getattr(authority, field, None) == value for field, value in binding.items())


def _require_binding_matches(
    authority: Any,
    binding: dict[str, Any],
    *,
    reason: str = "local_binding_changed",
) -> None:
    if not _binding_matches(authority, binding):
        raise OperationActionError(
            "The endpoint, provider, execution node, or local configuration changed.",
            kind="invalid",
            reason=reason,
        )


def _lock_binding_source(operation_pk: int) -> tuple[CephOperation, dict[str, Any]]:
    """Lock every mutable local row that can retarget a Ceph mutation."""

    operation = CephOperation.objects.select_for_update().get(pk=operation_pk)
    if not isinstance(operation, CephOperation):
        _validate_operation_provider(operation)
        return operation, _binding_snapshot(operation)
    cluster = (
        CephCluster.objects.select_for_update()
        .select_related("endpoint")
        .get(pk=operation.cluster_id)
    )
    if operation.provider_id is None:
        _validate_operation_provider(operation)
    provider = CephProvider.objects.select_for_update().get(pk=operation.provider_id)
    # Avoid using relation objects that were cached before row locks were held.
    operation.cluster = cluster
    operation.provider = provider
    _validate_operation_provider(operation)
    return operation, _binding_snapshot(operation, cluster=cluster, provider=provider)


def _lock_audit_chain(
    *,
    operation: CephOperation,
    plan: CephPlan | None = None,
    approval: CephOperationApproval | None = None,
    run: CephOperationRun | None = None,
) -> tuple[CephOperation, CephPlan | None, CephOperationApproval | None, CephOperationRun | None]:
    """Lock an audit chain in one consistent order; pure-test records pass through."""

    if not isinstance(operation, CephOperation):
        return operation, plan, approval, run
    locked_operation = CephOperation.objects.select_for_update().get(pk=operation.pk)
    locked_plan = plan
    if plan is not None and getattr(plan, "pk", None) is not None:
        locked_plan = CephPlan.objects.select_for_update().get(pk=plan.pk)
    locked_approval = approval
    if approval is not None and getattr(approval, "pk", None) is not None:
        locked_approval = CephOperationApproval.objects.select_for_update().get(pk=approval.pk)
    locked_run = run
    if run is not None and getattr(run, "pk", None) is not None:
        locked_run = CephOperationRun.objects.select_for_update().get(pk=run.pk)
    return locked_operation, locked_plan, locked_approval, locked_run


def _actor_name(actor: Any) -> str:
    if actor is None or not bool(getattr(actor, "is_authenticated", False)):
        raise OperationActionError(
            "An authenticated actor is required.",
            kind="invalid",
            reason="actor_required",
        )
    get_username = getattr(actor, "get_username", None)
    value = get_username() if callable(get_username) else getattr(actor, "username", "")
    name = str(value or "").strip()
    if not name:
        raise OperationActionError(
            "The authenticated actor has no stable username.",
            kind="invalid",
            reason="actor_required",
        )
    return name


def _require_permission(actor: Any, permission: str, obj: Any) -> None:
    """Require ``permission`` on the exact durable authority object.

    A model-level ``has_perm(permission)`` result only proves that the actor may
    access *some* object. Ceph write authority is always scoped to one operation
    (or provider for reconciliation), so callers must never omit ``obj``.
    """

    _actor_name(actor)
    has_perm = getattr(actor, "has_perm", None)
    if not callable(has_perm) or not bool(has_perm(permission, obj)):
        raise OperationActionError(
            "The actor lacks the required Ceph operation permission.",
            kind="forbidden",
            reason="permission_denied",
        )


def _same_actor(left: Any, right: Any) -> bool:
    left_pk = getattr(left, "pk", None)
    right_pk = getattr(right, "pk", None)
    if left_pk is not None and right_pk is not None:
        return left_pk == right_pk
    try:
        return _actor_name(left).casefold() == _actor_name(right).casefold()
    except OperationActionError:
        return False


def _validate_operation_provider(operation: CephOperation) -> CephProvider:
    """Fail closed unless one enabled same-cluster Proxmox provider is selected."""

    try:
        validate_secret_free_intent(getattr(operation, "desired", {}))
    except SecretBearingIntentError as exc:
        raise OperationActionError(
            "The operation intent contains forbidden credential material.",
            kind="invalid",
            reason="secret_bearing_intent",
        ) from exc
    provider = getattr(operation, "provider", None)
    if provider is None:
        raise OperationActionError(
            "The operation has no provider.",
            kind="invalid",
            reason="provider_required",
        )
    if provider.cluster_id != getattr(operation, "cluster_id", None):
        raise OperationActionError(
            "The operation provider belongs to a different Ceph cluster.",
            kind="invalid",
            reason="provider_cluster_mismatch",
        )
    if not provider.enabled:
        raise OperationActionError(
            "The operation provider is disabled.",
            kind="invalid",
            reason="provider_disabled",
        )
    if provider.kind != CephProviderKindChoices.KIND_PROXMOX:
        raise OperationActionError(
            "The provider does not support the durable Proxmox write contract.",
            kind="unsupported",
            reason="provider_write_contract_unsupported",
        )
    target_kind = str(getattr(operation, "target_kind", "") or "").strip().lower()
    if target_kind not in _PROXMOX_WRITER_ACTIONS:
        raise OperationActionError(
            "The requested object kind is not implemented by the Proxmox Ceph writer.",
            kind="unsupported",
            reason="operation_kind_unsupported",
        )
    execution_node = str(getattr(operation, "execution_node", "") or "").strip()
    if _NODE_PATTERN.fullmatch(execution_node) is None:
        raise OperationActionError(
            "An exact valid Proxmox execution node is required.",
            kind="invalid",
            reason="execution_node_required",
        )
    desired = getattr(operation, "desired", {})
    desired_node = desired.get("node") if isinstance(desired, dict) else None
    if desired_node not in (None, "", execution_node):
        raise OperationActionError(
            "The desired payload node conflicts with the persisted execution node.",
            kind="invalid",
            reason="execution_node_mismatch",
        )
    return provider


def _has_active_authority(operation: CephOperation) -> bool:
    return (
        operation.status in _ACTIVE_OPERATION_STATUSES
        or operation.approvals.filter(status__in=_ACTIVE_APPROVAL_STATUSES).exists()
        # Treat every current or future nonterminal backend state as active.
        # An allowlist of known active states would make a newly introduced
        # state such as ``pending`` accidentally release authority.
        or operation.runs.exclude(status__in=_TERMINAL_RUN_STATUSES).exists()
    )


def _has_active_approval_or_run(operation: CephOperation) -> bool:
    return (
        operation.approvals.filter(status__in=_ACTIVE_APPROVAL_STATUSES).exists()
        or operation.runs.exclude(status__in=_TERMINAL_RUN_STATUSES).exists()
    )


def operation_payload(operation: CephOperation, *, endpoint_id: int) -> dict[str, Any]:
    """Serialize one endpoint-bound desired object for proxbox-api's strict writer."""

    if isinstance(endpoint_id, bool) or not isinstance(endpoint_id, int) or endpoint_id <= 0:
        raise OperationActionError(
            "A canonical positive backend endpoint ID is required.",
            kind="invalid",
            reason="endpoint_binding_missing",
        )

    provider = operation.provider
    desired = dict(operation.desired) if isinstance(operation.desired, dict) else {}
    # ``node`` is top-level on the desired object and is later persisted as the
    # strict ProviderOperation.node. It is never left to provider inference.
    desired_object = {
        "kind": operation.target_kind,
        "target_ref": operation.target_ref,
        "action": operation.operation_type,
        "provider": "proxmox",
        "node": operation.execution_node,
        "payload": desired,
    }
    return {
        "id": operation.pk,
        "cluster_id": operation.cluster_id,
        "provider_id": operation.provider_id,
        "provider_kind": provider.kind if provider is not None else None,
        "provider_name": provider.name if provider is not None else None,
        "provider": "proxmox",
        "endpoint_id": endpoint_id,
        "operation_type": operation.operation_type,
        "target_kind": operation.target_kind,
        "target_ref": operation.target_ref,
        "execution_node": operation.execution_node,
        "desired": desired,
        "desired_state": {"objects": [desired_object]},
        "is_destructive": operation.is_destructive,
        "confirmation_required": operation.confirmation_required,
        "source_branch_schema_id": operation.source_branch_schema_id,
    }


def request_digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _choice_or_default(value: Any, choices: list[tuple[str, str, str]], default: str) -> str:
    allowed = {choice[0] for choice in choices}
    if value in allowed:
        return str(value)
    return default


def _plan_payload(response: dict[str, Any]) -> dict[str, Any]:
    nested = response.get("plan")
    return nested if isinstance(nested, dict) else response


def _validation_payloads(
    response: dict[str, Any], plan_payload: dict[str, Any]
) -> list[dict[str, Any]]:
    candidates = response.get("validations", plan_payload.get("validations", []))
    if not isinstance(candidates, list):
        return []
    return [item for item in candidates if isinstance(item, dict)]


def latest_plan(operation: CephOperation) -> CephPlan | None:
    return operation.plans.order_by("-generated_at", "-created", "-pk").first()


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if timezone.is_naive(result):
        result = timezone.make_aware(result, timezone.get_current_timezone())
    return result


def _plan_status_from_response(payload: dict[str, Any]) -> str:
    valid_choices = {choice[0] for choice in CephPlanStatusChoices.CHOICES}
    status_value = ceph_v2_responses.plan_status_value(payload, valid_choices=valid_choices)
    if status_value in valid_choices:
        return str(status_value)
    return CephPlanStatusChoices.STATUS_DRAFT


def _is_stable_identifier(value: object) -> bool:
    return isinstance(value, str) and _IDENTIFIER_PATTERN.fullmatch(value) is not None


def _is_canonical_digest(value: object) -> bool:
    return isinstance(value, str) and _DIGEST_PATTERN.fullmatch(value) is not None


def _is_ambiguous_http_error(exc: CephOrchestratorHTTPError) -> bool:
    return exc.status_code == 408 or exc.status_code >= 500


def refresh_plan(
    operation: CephOperation,
    response_payload: dict[str, Any],
    *,
    requester: Any,
    backend_endpoint_id: int,
    local_request_digest: str,
    local_binding: dict[str, Any],
) -> tuple[CephPlan, list[CephValidationResult]]:
    """Append an immutable plan and preserve all earlier validation history."""

    payload = _plan_payload(response_payload)
    safe_response = redact_secrets(response_payload)
    safe_payload = _plan_payload(safe_response)
    fields = ceph_v2_responses.plan_fields_from_response(safe_payload)
    operation.plans.exclude(
        status__in=(CephPlanStatusChoices.STATUS_APPLIED, CephPlanStatusChoices.STATUS_STALE)
    ).update(status=CephPlanStatusChoices.STATUS_STALE)
    plan = CephPlan.objects.create(
        operation=operation,
        status=_plan_status_from_response(payload),
        summary=fields["summary"],
        intended_changes=fields["intended_changes"],
        provider_target=fields["provider_target"],
        blast_radius=fields["blast_radius"],
        expected_tasks=fields["expected_tasks"],
        rollback_limits=redact_text(payload.get("rollback_limits", "")),
        is_destructive=bool(fields["is_destructive"] or operation.is_destructive),
        generated_at=timezone.now(),
        raw=safe_response,
        backend_plan_id=str(payload.get("id", "")),
        backend_plan_digest=str(payload.get("digest", "")),
        backend_endpoint_id=backend_endpoint_id,
        backend_endpoint_config_revision=str(payload.get("endpoint_config_revision", "")),
        plugin_endpoint_id=local_binding["plugin_endpoint_id"],
        provider_id_snapshot=local_binding["provider_id_snapshot"],
        provider_kind_snapshot=local_binding["provider_kind_snapshot"],
        execution_node=local_binding["execution_node"],
        local_config_digest=local_binding["local_config_digest"],
        requester=requester,
        requester_username=_actor_name(requester),
        expires_at=_parse_datetime(payload.get("expires_at")),
        request_digest=local_request_digest,
    )

    validations: list[CephValidationResult] = []
    for item in _validation_payloads(safe_response, safe_payload):
        validation = CephValidationResult.objects.create(
            plan=plan,
            operation=operation,
            severity=_choice_or_default(
                item.get("severity"),
                CephValidationSeverityChoices.CHOICES,
                CephValidationSeverityChoices.SEVERITY_INFO,
            ),
            code=str(item.get("code", "backend"))[:128],
            message=redact_text(item.get("message", "")),
            target=redact_text(item.get("target", ""))[:255],
        )
        validations.append(validation)
    return plan, validations


def run_status(value: Any, default: str) -> str:
    mapped = ceph_v2_responses.map_run_status(value)
    if mapped is not None:
        return mapped
    return _choice_or_default(value, CephOperationStatusChoices.CHOICES, default)


def provider_task_ref(response: dict[str, Any]) -> str:
    return ceph_v2_responses.provider_task_ref(response)


def _error_from_orchestrator(
    exc: Exception,
    *,
    run: CephOperationRun | None = None,
) -> OperationActionError:
    if isinstance(exc, CephOrchestratorHTTPError):
        kind = "invalid" if exc.status_code in (400, 409, 422) else "backend"
        if exc.status_code in (401, 403):
            kind = "forbidden"
        elif exc.status_code == 408 or exc.status_code >= 500:
            kind = "unavailable"
        return OperationActionError(
            exc.detail,
            kind=kind,
            reason=exc.reason,
            recovery=exc.recovery,
            run=run,
        )
    if isinstance(exc, CephOrchestratorUnsupported):
        return OperationActionError(
            "The configured backend does not support the required Ceph v2 route.",
            kind="unsupported",
            reason="backend_unsupported",
            run=run,
        )
    if isinstance(exc, CephOrchestratorUnavailable):
        return OperationActionError(
            "The Ceph v2 backend is unavailable.",
            kind="unavailable",
            reason="backend_unavailable",
            run=run,
        )
    return OperationActionError(
        "The Ceph v2 backend rejected the operation.",
        kind="backend",
        reason="backend_request_rejected",
        run=run,
    )


def _failed_status_for(exc: Exception) -> str:
    if isinstance(exc, CephOrchestratorUnsupported):
        return CephOperationStatusChoices.STATUS_UNSUPPORTED
    return CephOperationStatusChoices.STATUS_FAILED


def _one_planned_operation(response: dict[str, Any]) -> dict[str, Any]:
    operations = response.get("operations")
    if not isinstance(operations, list) or len(operations) != 1:
        raise OperationActionError(
            "The backend plan did not return exactly one canonical provider operation.",
            kind="backend",
            reason="invalid_plan_operations",
        )
    planned = operations[0]
    if not isinstance(planned, dict):
        raise OperationActionError(
            "The backend plan operation had an invalid shape.",
            kind="backend",
            reason="invalid_plan_operations",
        )
    return planned


def _writer_payload_types_are_valid(
    payload: dict[str, Any],
    *,
    kind: str,
    action: str,
) -> bool:
    """Mirror #258's strict Pydantic scalar constraints at the trust boundary."""

    required = _PROXMOX_WRITER_REQUIRED_FIELDS.get((kind, action), frozenset())
    if not required.issubset(payload):
        return False
    for field, value in payload.items():
        if field in _PROXMOX_WRITER_BOOL_FIELDS:
            valid = isinstance(value, bool)
        elif field in _PROXMOX_WRITER_INT_FIELDS:
            valid = not isinstance(value, bool) and isinstance(value, int) and value >= 1
        elif field in _PROXMOX_WRITER_FLOAT_FIELDS:
            valid = not isinstance(value, bool) and isinstance(value, (int, float)) and value > 0
        elif field in _PROXMOX_WRITER_STRING_FIELDS:
            valid = isinstance(value, str) and (field != "dev" or bool(value))
        else:
            # Field-name validation runs before this helper. Reaching this
            # branch means the two local mirrors drifted, so fail closed.
            valid = False
        if not valid:
            return False
    return True


def _validate_writer_payload(payload: Any, *, kind: str, action: str) -> None:
    """Reject any response payload that #258's writer would not accept."""

    if not isinstance(payload, dict):
        raise OperationActionError(
            "The backend plan operation payload had an invalid shape.",
            kind="backend",
            reason="invalid_plan_operations",
        )
    allowed_fields = _PROXMOX_WRITER_FIELDS.get((kind, action), frozenset())
    if action == "noop":
        allowed_fields = frozenset().union(
            *(
                fields
                for (field_kind, field_action), fields in _PROXMOX_WRITER_FIELDS.items()
                if field_kind == kind and field_action != "delete"
            )
        )
    if set(payload).difference(allowed_fields) or not _writer_payload_types_are_valid(
        payload,
        kind=kind,
        action=action,
    ):
        raise OperationActionError(
            "The backend plan payload does not match the typed Proxmox writer contract.",
            kind="backend",
            reason="plan_payload_contract_mismatch",
        )


def _validate_planned_operation(
    response: dict[str, Any],
    *,
    operation: CephOperation,
    local_binding: dict[str, Any] | None,
) -> None:
    planned = _one_planned_operation(response)
    if set(planned).difference(_PROXMOX_OPERATION_FIELDS):
        raise OperationActionError(
            "The backend plan operation contains fields outside ProviderOperation.",
            kind="backend",
            reason="invalid_plan_operations",
        )
    expected_node = (
        str(local_binding["execution_node"])
        if local_binding is not None
        else str(getattr(operation, "execution_node", "") or "")
    )
    kind = str(planned.get("kind") or "")
    action = str(planned.get("action") or "")
    binding_matches = (
        planned.get("provider") == "proxmox"
        and kind == str(operation.target_kind)
        and str(planned.get("target_ref") or "") == str(operation.target_ref)
        and str(planned.get("node") or "") == expected_node
    )
    if not binding_matches:
        raise OperationActionError(
            "The backend plan operation did not preserve the requested target and node.",
            kind="backend",
            reason="plan_operation_binding_mismatch",
        )
    if (
        planned.get("supported") is not True
        or planned.get("blocked_reason") not in (None, "")
        or action not in _PROXMOX_WRITER_ACTIONS.get(kind, frozenset())
    ):
        raise OperationActionError(
            "The backend plan contains an operation the Proxmox writer cannot execute.",
            kind="unsupported",
            reason="plan_operation_unsupported",
        )
    allowed_result_actions = {
        CephOperationTypeChoices.TYPE_CREATE: {"create", "noop"},
        CephOperationTypeChoices.TYPE_UPDATE: {"update", "noop"},
        CephOperationTypeChoices.TYPE_DELETE: {"delete"},
        CephOperationTypeChoices.TYPE_RECONCILE: frozenset(
            action_name
            for action_name in _PROXMOX_WRITER_ACTIONS.get(kind, frozenset())
            if action_name != "delete"
        ),
    }.get(str(operation.operation_type))
    destructive_mismatch = (action == "delete" and planned.get("is_destructive") is not True) or (
        operation.operation_type == CephOperationTypeChoices.TYPE_RECONCILE
        and planned.get("is_destructive") is True
    )
    if (
        allowed_result_actions is None
        or action not in allowed_result_actions
        or destructive_mismatch
    ):
        raise OperationActionError(
            "The planned provider action does not match the requested operation type.",
            kind="invalid",
            reason="plan_action_mismatch",
        )
    validations = response.get("validations", [])
    blocked_actions = response.get("blocked_actions", [])
    if (
        not isinstance(validations, list)
        or any(not isinstance(item, dict) for item in validations)
        or not isinstance(blocked_actions, list)
    ):
        raise OperationActionError(
            "The backend plan returned malformed validation or blocker data.",
            kind="backend",
            reason="invalid_plan_contract",
        )
    has_error = any(item.get("severity") == "error" for item in validations)
    if blocked_actions or has_error:
        raise OperationActionError(
            "The backend plan is blocked by a capability or validation gate.",
            kind="invalid",
            reason="plan_blocked",
        )
    _validate_writer_payload(planned.get("after_summary", {}), kind=kind, action=action)


def _validate_plan_response(
    response: dict[str, Any],
    *,
    endpoint_id: int,
    requester_name: str,
    operation: CephOperation | None = None,
    local_binding: dict[str, Any] | None = None,
) -> None:
    if response.get("provider") != "proxmox":
        raise OperationActionError(
            "The backend plan did not confirm the Proxmox provider contract.",
            kind="backend",
            reason="plan_provider_mismatch",
        )
    if not _is_stable_identifier(response.get("id")) or not _is_canonical_digest(
        response.get("digest")
    ):
        raise OperationActionError(
            "The backend returned a plan without a valid durable ID and digest.",
            kind="backend",
            reason="invalid_plan_contract",
        )
    if not _is_canonical_digest(response.get("endpoint_config_revision")):
        raise OperationActionError(
            "The backend plan did not include a valid endpoint configuration revision.",
            kind="backend",
            reason="invalid_endpoint_config_revision",
        )
    response_endpoint_id = response.get("endpoint_id")
    if (
        isinstance(response_endpoint_id, bool)
        or not isinstance(response_endpoint_id, int)
        or response_endpoint_id != endpoint_id
    ):
        raise OperationActionError(
            "The backend plan endpoint binding did not match the selected endpoint.",
            kind="backend",
            reason="plan_endpoint_mismatch",
        )
    backend_requester = str(response.get("requester") or "")
    if backend_requester.casefold() != requester_name.casefold():
        raise OperationActionError(
            "The backend plan requester binding did not match the authenticated actor.",
            kind="backend",
            reason="plan_requester_mismatch",
        )
    expires_at = _parse_datetime(response.get("expires_at"))
    if expires_at is None or expires_at <= timezone.now():
        raise OperationActionError(
            "The backend plan has no valid future expiry.",
            kind="backend",
            reason="invalid_plan_expiry",
        )
    if operation is None:
        return
    _validate_planned_operation(
        response,
        operation=operation,
        local_binding=local_binding,
    )


def _current_plan_payload(operation: CephOperation, endpoint_id: int) -> dict[str, Any]:
    return operation_payload(operation, endpoint_id=endpoint_id)


def _mark_plan_stale(operation: CephOperation, plan: CephPlan, reason: str) -> None:
    with transaction.atomic():
        operation, plan, _approval, _run = _lock_audit_chain(
            operation=operation,
            plan=plan,
        )
        assert plan is not None
        plan.status = CephPlanStatusChoices.STATUS_STALE
        plan.save(update_fields=("status", "last_updated"))
        _transition_checkpoint("mark_plan_stale.after_plan")
        operation.status = CephOperationStatusChoices.STATUS_PENDING
        operation.save(update_fields=("status", "last_updated"))


def _validate_plan_is_current(
    operation: CephOperation,
    plan: CephPlan,
    *,
    endpoint_id: int,
    local_binding: dict[str, Any] | None = None,
    mark_stale: bool = True,
) -> None:
    def stale(reason: str) -> None:
        if mark_stale:
            _mark_plan_stale(operation, plan, reason)
        raise OperationActionError(
            "The operation or endpoint changed after planning; create a fresh plan.",
            kind="invalid",
            reason=reason,
        )

    if plan.status == CephPlanStatusChoices.STATUS_STALE:
        raise OperationActionError(
            "The latest plan is stale; create a fresh plan.",
            kind="invalid",
            reason="plan_stale",
        )
    if plan.expires_at is None or plan.expires_at <= timezone.now():
        stale("plan_expired")
    if plan.backend_endpoint_id != endpoint_id:
        stale("endpoint_binding_changed")
    if local_binding is not None and not _binding_matches(plan, local_binding):
        stale("local_binding_changed")
    current_digest = request_digest(_current_plan_payload(operation, endpoint_id))
    if not plan.request_digest or current_digest != plan.request_digest:
        stale("operation_changed_after_plan")
    if not plan.backend_plan_id or not plan.backend_plan_digest:
        stale("legacy_plan_has_no_authority")
    if not _is_canonical_digest(plan.backend_endpoint_config_revision):
        stale("legacy_plan_has_no_endpoint_revision")


def _approval_actor_names(approval: CephOperationApproval) -> tuple[str, str]:
    requester_name = approval.requester_username.strip()
    approver_name = approval.approver_username.strip()
    if not requester_name or not approver_name:
        raise OperationActionError(
            "The approval audit record has no immutable actor identity.",
            kind="backend",
            reason="approval_actor_binding_missing",
        )
    return requester_name, approver_name


def _validate_approval_status_binding(
    payload: dict[str, Any],
    *,
    approval: CephOperationApproval,
    plan: CephPlan,
) -> None:
    requester_name, approver_name = _approval_actor_names(approval)
    response_expiry = _parse_datetime(payload.get("expires_at"))
    binding_matches = (
        all(
            getattr(approval, field, None) == getattr(plan, field, None)
            for field in (
                "plugin_endpoint_id",
                "provider_id_snapshot",
                "provider_kind_snapshot",
                "execution_node",
                "local_config_digest",
            )
        )
        and _is_canonical_digest(approval.backend_endpoint_config_revision)
        and approval.backend_endpoint_config_revision == plan.backend_endpoint_config_revision
        and str(payload.get("id") or "") == approval.backend_approval_id
        and str(payload.get("plan_id") or "") == plan.backend_plan_id
        and str(payload.get("plan_digest") or "") == plan.backend_plan_digest
        and not isinstance(payload.get("endpoint_id"), bool)
        and isinstance(payload.get("endpoint_id"), int)
        and payload.get("endpoint_id") == approval.backend_endpoint_id
        and str(payload.get("endpoint_config_revision") or "")
        == approval.backend_endpoint_config_revision
        and str(payload.get("requester") or "").casefold() == requester_name.casefold()
        and str(payload.get("approver") or "").casefold() == approver_name.casefold()
        and response_expiry is not None
        and plan.expires_at is not None
        and response_expiry <= plan.expires_at
        and (approval.expires_at is None or response_expiry == approval.expires_at)
    )
    if not binding_matches:
        raise OperationActionError(
            "The backend approval status did not match the canonical local authority.",
            kind="backend",
            reason="approval_status_binding_mismatch",
        )


def _validate_run_binding(
    payload: dict[str, Any],
    *,
    approval: CephOperationApproval,
    plan: CephPlan,
    run: CephOperationRun | None = None,
) -> None:
    requester_name, approver_name = _approval_actor_names(approval)
    binding_matches = (
        all(
            getattr(approval, field, None) == getattr(plan, field, None)
            for field in (
                "plugin_endpoint_id",
                "provider_id_snapshot",
                "provider_kind_snapshot",
                "execution_node",
                "local_config_digest",
            )
        )
        and (
            run is None
            or all(
                getattr(run, field, None) == getattr(approval, field, None)
                for field in (
                    "plugin_endpoint_id",
                    "provider_id_snapshot",
                    "provider_kind_snapshot",
                    "execution_node",
                    "local_config_digest",
                )
            )
        )
        and _is_canonical_digest(approval.backend_endpoint_config_revision)
        and approval.backend_endpoint_config_revision == plan.backend_endpoint_config_revision
        and (not approval.backend_run_id or str(payload.get("id") or "") == approval.backend_run_id)
        and str(payload.get("plan_id") or "") == plan.backend_plan_id
        and str(payload.get("plan_digest") or "") == plan.backend_plan_digest
        and not isinstance(payload.get("endpoint_id"), bool)
        and isinstance(payload.get("endpoint_id"), int)
        and payload.get("endpoint_id") == approval.backend_endpoint_id
        and str(payload.get("endpoint_config_revision") or "")
        == approval.backend_endpoint_config_revision
        and str(payload.get("approval_id") or "") == approval.backend_approval_id
        and str(payload.get("requester") or "").casefold() == requester_name.casefold()
        and str(payload.get("approver") or "").casefold() == approver_name.casefold()
        and str(payload.get("actor") or "").casefold() == requester_name.casefold()
        and payload.get("provider") == "proxmox"
    )
    if not binding_matches:
        raise OperationActionError(
            "The backend run did not match the canonical plan and approval authority.",
            kind="backend",
            reason="run_binding_mismatch",
        )


def _record_run_response(
    run: CephOperationRun,
    operation: CephOperation,
    approval: CephOperationApproval,
    response_payload: dict[str, Any],
    *,
    plan: CephPlan,
) -> CephOperationRun:
    status_value = run_status(
        response_payload.get("status"),
        CephOperationStatusChoices.STATUS_OUTCOME_UNKNOWN,
    )
    backend_run_id = str(response_payload.get("id") or "")
    try:
        with transaction.atomic():
            operation, plan, approval, run = _lock_audit_chain(
                operation=operation,
                plan=plan,
                approval=approval,
                run=run,
            )
            assert plan is not None and approval is not None and run is not None
            _validate_run_binding(response_payload, approval=approval, plan=plan, run=run)
            if not _is_stable_identifier(backend_run_id):
                raise OperationActionError(
                    "The backend returned a run without a durable ID.",
                    kind="backend",
                    reason="invalid_run_contract",
                    run=run,
                )
            run.status = status_value
            run.backend_run_id = backend_run_id
            run.provider_task_ref = redact_text(provider_task_ref(response_payload))[:255]
            run.outcome_unknown = status_value == CephOperationStatusChoices.STATUS_OUTCOME_UNKNOWN
            run.finished_at = timezone.now() if status_value in _TERMINAL_RUN_STATUSES else None
            run.result = redact_secrets(response_payload)
            warnings = redact_secrets(response_payload.get("warnings", []))
            run.warnings = warnings if isinstance(warnings, list) else []
            errors = response_payload.get("errors", [])
            run.error = (
                f"Backend reported {len(errors)} operation error(s)."
                if isinstance(errors, list) and errors
                else ""
            )
            run.save(
                update_fields=(
                    "status",
                    "backend_run_id",
                    "provider_task_ref",
                    "outcome_unknown",
                    "finished_at",
                    "result",
                    "warnings",
                    "error",
                    "last_updated",
                )
            )
            _transition_checkpoint("record_run.after_run")
            operation.status = status_value
            operation.save(update_fields=("status", "last_updated"))
            _transition_checkpoint("record_run.after_operation")
            approval.backend_run_id = backend_run_id
            approval.status = (
                CephApprovalStatusChoices.STATUS_OUTCOME_UNKNOWN
                if run.outcome_unknown
                else CephApprovalStatusChoices.STATUS_CONSUMED
            )
            approval.save(update_fields=("backend_run_id", "status", "last_updated"))
            _transition_checkpoint("record_run.after_approval")
            if status_value == CephOperationStatusChoices.STATUS_SUCCEEDED:
                plan.status = CephPlanStatusChoices.STATUS_APPLIED
                plan.save(update_fields=("status", "last_updated"))
            return run
    except OperationActionError as exc:
        _mark_outcome_unknown(run, operation, approval)
        if exc.run is None:
            exc.run = run
        raise


def _mark_outcome_unknown(
    run: CephOperationRun,
    operation: CephOperation,
    approval: CephOperationApproval,
) -> None:
    with transaction.atomic():
        operation, _plan, approval, run = _lock_audit_chain(
            operation=operation,
            approval=approval,
            run=run,
        )
        assert approval is not None and run is not None
        run.status = CephOperationStatusChoices.STATUS_OUTCOME_UNKNOWN
        run.outcome_unknown = True
        run.error = "Apply transport outcome is unknown; recover by approval/run ID before acting."
        run.save(update_fields=("status", "outcome_unknown", "error", "last_updated"))
        _transition_checkpoint("outcome_unknown.after_run")
        operation.status = CephOperationStatusChoices.STATUS_OUTCOME_UNKNOWN
        operation.save(update_fields=("status", "last_updated"))
        _transition_checkpoint("outcome_unknown.after_operation")
        approval.status = CephApprovalStatusChoices.STATUS_OUTCOME_UNKNOWN
        approval.failure_code = "apply_transport_outcome_unknown"
        approval.failure_detail = "Use backend approval/run status; do not issue another write."
        approval.save(update_fields=("status", "failure_code", "failure_detail", "last_updated"))


def _recover_backend_run(
    orchestrator: CephOrchestratorClient,
    *,
    backend_run_id: str,
    run: CephOperationRun,
    operation: CephOperation,
    approval: CephOperationApproval,
    plan: CephPlan,
) -> CephOperationRun:
    try:
        payload = orchestrator.operation(backend_run_id)
    except CephBackendError as exc:
        _mark_outcome_unknown(run, operation, approval)
        raise _error_from_orchestrator(exc, run=run) from exc
    return _record_run_response(run, operation, approval, payload, plan=plan)


def _approval_status_run_id(
    orchestrator: CephOrchestratorClient,
    *,
    approval: CephOperationApproval,
    plan: CephPlan,
    run: CephOperationRun,
    operation: CephOperation,
) -> str:
    try:
        status_payload = orchestrator.approval_status(approval.backend_approval_id)
        _validate_approval_status_binding(status_payload, approval=approval, plan=plan)
    except CephBackendError as exc:
        _mark_outcome_unknown(run, operation, approval)
        raise _error_from_orchestrator(exc, run=run) from exc
    except OperationActionError:
        _mark_outcome_unknown(run, operation, approval)
        raise
    response_expiry = _parse_datetime(status_payload.get("expires_at"))
    if approval.expires_at is None and response_expiry is not None:
        approval.expires_at = response_expiry
        approval.save(update_fields=("expires_at", "last_updated"))
    backend_run_id = str(status_payload.get("operation_run_id") or "")
    if backend_run_id and not _is_stable_identifier(backend_run_id):
        _mark_outcome_unknown(run, operation, approval)
        raise OperationActionError(
            "The backend approval status returned an invalid run ID.",
            kind="backend",
            reason="invalid_run_contract",
            run=run,
        )
    return backend_run_id


def _expire_unrecovered_approval(
    approval: CephOperationApproval,
    run: CephOperationRun,
    operation: CephOperation,
) -> None:
    with transaction.atomic():
        operation, _plan, approval, run = _lock_audit_chain(
            operation=operation,
            approval=approval,
            run=run,
        )
        assert approval is not None and run is not None
        approval.status = CephApprovalStatusChoices.STATUS_EXPIRED
        approval.failure_code = "approval_expired_without_dispatch"
        approval.failure_detail = "The unconsumed approval expired without a recoverable run."
        approval.save(update_fields=("status", "failure_code", "failure_detail", "last_updated"))
        _transition_checkpoint("expire_approval.after_approval")
        run.status = CephOperationStatusChoices.STATUS_FAILED
        run.outcome_unknown = False
        run.finished_at = timezone.now()
        run.error = "The backend approval expired before a run could be recovered."
        run.save(
            update_fields=(
                "status",
                "outcome_unknown",
                "finished_at",
                "error",
                "last_updated",
            )
        )
        _transition_checkpoint("expire_approval.after_run")
        operation.status = CephOperationStatusChoices.STATUS_FAILED
        operation.save(update_fields=("status", "last_updated"))


def _recover_existing_approval(
    orchestrator: CephOrchestratorClient,
    *,
    approval: CephOperationApproval,
    operation: CephOperation,
    plan: CephPlan,
    approver: Any,
) -> CephOperationRun:
    with transaction.atomic():
        if isinstance(operation, CephOperation):
            operation, local_binding = _lock_binding_source(operation.pk)
            plan = CephPlan.objects.select_for_update().get(pk=plan.pk)
            approval = CephOperationApproval.objects.select_for_update().get(pk=approval.pk)
            _require_binding_matches(plan, local_binding)
            _require_binding_matches(approval, local_binding)
            run = CephOperationRun.objects.select_for_update().filter(approval=approval).first()
        else:
            run = getattr(approval, "run", None)
        if (
            approval.backend_plan_id != plan.backend_plan_id
            or approval.backend_plan_digest != plan.backend_plan_digest
            or approval.backend_endpoint_id != plan.backend_endpoint_id
            or approval.backend_endpoint_config_revision != plan.backend_endpoint_config_revision
            or not _is_canonical_digest(approval.backend_endpoint_config_revision)
        ):
            raise OperationActionError(
                "The local approval record does not match its canonical plan.",
                kind="backend",
                reason="local_approval_binding_mismatch",
            )
        if run is None:
            run = CephOperationRun.objects.create(
                operation=operation,
                plan=plan,
                provider=operation.provider,
                approval=approval,
                status=CephOperationStatusChoices.STATUS_OUTCOME_UNKNOWN,
                backend_endpoint_config_revision=approval.backend_endpoint_config_revision,
                plugin_endpoint_id=getattr(approval, "plugin_endpoint_id", None),
                provider_id_snapshot=getattr(approval, "provider_id_snapshot", None),
                provider_kind_snapshot=getattr(approval, "provider_kind_snapshot", ""),
                execution_node=getattr(approval, "execution_node", ""),
                local_config_digest=getattr(approval, "local_config_digest", ""),
                actor=approver,
                actor_username=_actor_name(approver),
                source_branch_schema_id=operation.source_branch_schema_id,
                started_at=timezone.now(),
                outcome_unknown=True,
            )
    backend_run_id = approval.backend_run_id
    if not backend_run_id and approval.backend_approval_id:
        backend_run_id = _approval_status_run_id(
            orchestrator,
            approval=approval,
            plan=plan,
            run=run,
            operation=operation,
        )
        if backend_run_id:
            approval.backend_run_id = backend_run_id
            approval.save(update_fields=("backend_run_id", "last_updated"))
    if backend_run_id:
        return _recover_backend_run(
            orchestrator,
            backend_run_id=backend_run_id,
            run=run,
            operation=operation,
            approval=approval,
            plan=plan,
        )
    if approval.expires_at is not None and approval.expires_at <= timezone.now():
        _expire_unrecovered_approval(approval, run, operation)
        raise OperationActionError(
            "The backend approval expired without dispatch; create a fresh plan.",
            kind="invalid",
            reason="approval_expired_without_dispatch",
            run=run,
        )
    _mark_outcome_unknown(run, operation, approval)
    raise OperationActionError(
        "An approval exists without a recoverable run; wait for expiry or recover by audit ID.",
        kind="invalid",
        reason="approval_token_unrecoverable",
        run=run,
    )


def _reserve_plan_operation(operation: CephOperation, *, requested_by: Any) -> CephOperation:
    with transaction.atomic():
        locked, local_binding = _lock_binding_source(operation.pk)
        _require_permission(requested_by, _REQUEST_PERMISSION, locked)
        _require_permission(requested_by, _APPLY_PERMISSION, locked)
        if locked.requested_by_id is not None and not _same_actor(
            locked.requested_by, requested_by
        ):
            raise OperationActionError(
                "Only the recorded requester may refresh this operation plan.",
                kind="forbidden",
                reason="requester_mismatch",
            )
        now = timezone.now()
        planning_takeover = False
        if locked.status == CephOperationStatusChoices.STATUS_PLANNING:
            planning_expiry = locked.planning_reservation_expires_at
            if planning_expiry is None and locked.last_updated is not None:
                planning_expiry = locked.last_updated + _PLAN_RESERVATION_TTL
            planning_takeover = planning_expiry is not None and planning_expiry <= now
            if not planning_takeover or _has_active_approval_or_run(locked):
                raise OperationActionError(
                    "This operation already has planning, approval, or apply authority in flight.",
                    kind="invalid",
                    reason="operation_authority_in_flight",
                )
        elif _has_active_authority(locked):
            raise OperationActionError(
                "This operation already has planning, approval, or apply authority in flight.",
                kind="invalid",
                reason="operation_authority_in_flight",
            )
        if not planning_takeover and locked.status not in {
            CephOperationStatusChoices.STATUS_PENDING,
            CephOperationStatusChoices.STATUS_PLANNED,
            CephOperationStatusChoices.STATUS_FAILED,
            CephOperationStatusChoices.STATUS_UNSUPPORTED,
        }:
            raise OperationActionError(
                "This operation cannot be planned again; create a fresh request.",
                kind="invalid",
                reason="operation_not_replannable",
            )
        locked.status = CephOperationStatusChoices.STATUS_PLANNING
        locked.planning_reservation_id = uuid.uuid4()
        locked.planning_reservation_expires_at = now + _PLAN_RESERVATION_TTL
        locked.requested_by = requested_by
        locked.requested_by_username = _actor_name(requested_by)
        locked.confirmed = False
        locked.save(
            update_fields=(
                "status",
                "planning_reservation_id",
                "planning_reservation_expires_at",
                "requested_by",
                "requested_by_username",
                "confirmed",
                "last_updated",
            )
        )
        locked._ceph_local_binding = local_binding
        return locked


def _finish_planning_failure(operation_pk: int, reservation_id: uuid.UUID, status: str) -> None:
    with transaction.atomic():
        locked = CephOperation.objects.select_for_update().get(pk=operation_pk)
        if (
            locked.status == CephOperationStatusChoices.STATUS_PLANNING
            and locked.planning_reservation_id == reservation_id
        ):
            locked.status = status
            locked.planning_reservation_id = None
            locked.planning_reservation_expires_at = None
            locked.save(
                update_fields=(
                    "status",
                    "planning_reservation_id",
                    "planning_reservation_expires_at",
                    "last_updated",
                )
            )


def plan_operation(
    operation: CephOperation,
    *,
    requested_by: Any,
) -> tuple[CephPlan, list[CephValidationResult]]:
    """Reserve one authority, then append a canonical plan outside the DB lock."""

    _require_permission(requested_by, _REQUEST_PERMISSION, operation)
    _require_permission(requested_by, _APPLY_PERMISSION, operation)
    requester_name = _actor_name(requested_by)
    operation = _reserve_plan_operation(operation, requested_by=requested_by)
    local_binding = getattr(operation, "_ceph_local_binding", None)
    if not isinstance(local_binding, dict):  # pragma: no cover - defensive invariant
        raise OperationActionError(
            "The local planning binding was not captured.",
            kind="backend",
            reason="local_binding_missing",
        )
    reservation_id = operation.planning_reservation_id
    if reservation_id is None:  # pragma: no cover - defensive database invariant
        raise OperationActionError(
            "The planning reservation was not persisted.",
            kind="backend",
            reason="planning_reservation_missing",
        )

    orchestrator = CephOrchestratorClient()
    try:
        backend_endpoint_id = orchestrator.resolve_backend_endpoint_id(operation.cluster.endpoint)
        payload = _current_plan_payload(operation, backend_endpoint_id)
        local_digest = request_digest(payload)
        response_payload = orchestrator.plan(payload, actor=requester_name)
        _validate_plan_response(
            response_payload,
            endpoint_id=backend_endpoint_id,
            requester_name=requester_name,
            operation=operation,
            local_binding=local_binding,
        )
    except OperationActionError:
        _finish_planning_failure(
            operation.pk,
            reservation_id,
            CephOperationStatusChoices.STATUS_FAILED,
        )
        raise
    except CephBackendError as exc:
        _finish_planning_failure(operation.pk, reservation_id, _failed_status_for(exc))
        raise _error_from_orchestrator(exc) from exc

    try:
        with transaction.atomic():
            locked, current_binding = _lock_binding_source(operation.pk)
            if (
                locked.status != CephOperationStatusChoices.STATUS_PLANNING
                or locked.planning_reservation_id != reservation_id
                or locked.approvals.filter(status__in=_ACTIVE_APPROVAL_STATUSES).exists()
                or locked.runs.exclude(status__in=_TERMINAL_RUN_STATUSES).exists()
            ):
                raise OperationActionError(
                    "The operation authority changed while its plan was being generated.",
                    kind="invalid",
                    reason="planning_reservation_lost",
                )
            if current_binding != local_binding:
                raise OperationActionError(
                    "The local endpoint/provider/node binding changed during planning.",
                    kind="invalid",
                    reason="planning_binding_changed",
                )
            if not _same_actor(locked.requested_by, requested_by):
                raise OperationActionError(
                    "The operation requester changed while its plan was being generated.",
                    kind="forbidden",
                    reason="requester_mismatch",
                )
            plan, validations = refresh_plan(
                locked,
                response_payload,
                requester=requested_by,
                backend_endpoint_id=backend_endpoint_id,
                local_request_digest=local_digest,
                local_binding=local_binding,
            )
            _transition_checkpoint("plan_finalize.after_plan")
            locked.status = CephOperationStatusChoices.STATUS_PLANNED
            locked.planning_reservation_id = None
            locked.planning_reservation_expires_at = None
            locked.save(
                update_fields=(
                    "status",
                    "planning_reservation_id",
                    "planning_reservation_expires_at",
                    "last_updated",
                )
            )
            return plan, validations
    except OperationActionError:
        _finish_planning_failure(
            operation.pk,
            reservation_id,
            CephOperationStatusChoices.STATUS_FAILED,
        )
        raise


def _approval_actors(operation: CephOperation, approver: Any) -> tuple[Any, str, str]:
    _require_permission(approver, _APPROVE_PERMISSION, operation)
    approver_name = _actor_name(approver)
    requester = operation.requested_by
    if requester is None:
        raise OperationActionError(
            "The operation has no authenticated requester.",
            kind="invalid",
            reason="requester_missing",
        )
    _require_permission(requester, _REQUEST_PERMISSION, operation)
    _require_permission(requester, _APPLY_PERMISSION, operation)
    requester_name = _actor_name(requester)
    if requester_name.casefold() == approver_name.casefold():
        raise OperationActionError(
            "The requester and approver must be different actors.",
            kind="invalid",
            reason="two_person_approval_required",
        )
    return requester, requester_name, approver_name


def _approvable_plan(operation: CephOperation) -> CephPlan:
    if operation.status not in (
        CephOperationStatusChoices.STATUS_PLANNED,
        CephOperationStatusChoices.STATUS_OUTCOME_UNKNOWN,
    ):
        raise OperationActionError(
            "Operation must be planned before independent approval.",
            kind="invalid",
            reason="operation_not_planned",
        )
    plan = latest_plan(operation)
    if plan is None:
        raise OperationActionError(
            "Operation has no generated plan to approve.",
            kind="invalid",
            reason="plan_missing",
        )
    if plan.status != CephPlanStatusChoices.STATUS_VALID:
        raise OperationActionError(
            "Only a valid, unblocked plan can be approved.",
            kind="invalid",
            reason="plan_not_valid",
        )
    return plan


def _reserve_approval_intent(
    operation: CephOperation,
    *,
    endpoint_id: int,
    requester: Any,
    requester_name: str,
    approver: Any,
    approver_name: str,
) -> tuple[CephOperation, CephPlan, CephOperationApproval, uuid.UUID | None]:
    """CAS-reserve one lease-owned approval issuance before any backend POST."""

    with transaction.atomic():
        locked, local_binding = _lock_binding_source(operation.pk)
        _require_permission(approver, _APPROVE_PERMISSION, locked)
        _require_permission(requester, _REQUEST_PERMISSION, locked)
        _require_permission(requester, _APPLY_PERMISSION, locked)
        if not _same_actor(locked.requested_by, requester) or (
            locked.requested_by_username
            and locked.requested_by_username.casefold() != requester_name.casefold()
        ):
            raise OperationActionError(
                "The operation requester changed before approval reservation.",
                kind="forbidden",
                reason="requester_mismatch",
            )
        if requester_name.casefold() == approver_name.casefold():
            raise OperationActionError(
                "The requester and approver must be different actors.",
                kind="invalid",
                reason="two_person_approval_required",
            )
        plan = (
            CephPlan.objects.select_for_update()
            .filter(operation=locked)
            .order_by("-generated_at", "-created", "-pk")
            .first()
        )
        if plan is None:
            raise OperationActionError(
                "Operation has no generated plan to approve.",
                kind="invalid",
                reason="plan_missing",
            )
        existing = CephOperationApproval.objects.select_for_update().filter(plan=plan).first()
        if existing is not None:
            if existing.approver_username.casefold() != approver_name.casefold():
                raise OperationActionError(
                    "Only the recorded approver may resume this approval authority.",
                    kind="forbidden",
                    reason="approver_mismatch",
                )
            if (
                existing.status == CephApprovalStatusChoices.STATUS_ISSUING
                and not existing.backend_approval_id
            ):
                _validate_plan_is_current(
                    locked,
                    plan,
                    endpoint_id=endpoint_id,
                    local_binding=local_binding,
                )
                _require_binding_matches(
                    existing,
                    local_binding,
                    reason="approval_local_binding_mismatch",
                )
                now = timezone.now()
                lease_active = (
                    existing.issuance_reservation_id is not None
                    and existing.issuance_reservation_expires_at is not None
                    and existing.issuance_reservation_expires_at > now
                )
                if lease_active:
                    return locked, plan, existing, None
                reservation_id = uuid.uuid4()
                existing.issuance_reservation_id = reservation_id
                existing.issuance_reservation_expires_at = now + _APPROVAL_ISSUANCE_TTL
                existing.save(
                    update_fields=(
                        "issuance_reservation_id",
                        "issuance_reservation_expires_at",
                        "last_updated",
                    )
                )
                return locked, plan, existing, reservation_id
            return locked, plan, existing, None
        if (
            locked.approvals.filter(status__in=_ACTIVE_APPROVAL_STATUSES).exists()
            or locked.runs.exclude(status__in=_TERMINAL_RUN_STATUSES).exists()
        ):
            raise OperationActionError(
                "Another plan authority for this operation is still active or unresolved.",
                kind="invalid",
                reason="operation_authority_in_flight",
            )
        plan = _approvable_plan(locked)
        _validate_plan_is_current(
            locked,
            plan,
            endpoint_id=endpoint_id,
            local_binding=local_binding,
        )
        reservation_id = uuid.uuid4()
        approval = CephOperationApproval.objects.create(
            operation=locked,
            plan=plan,
            backend_plan_id=plan.backend_plan_id,
            backend_plan_digest=plan.backend_plan_digest,
            backend_endpoint_id=endpoint_id,
            backend_endpoint_config_revision=plan.backend_endpoint_config_revision,
            plugin_endpoint_id=local_binding["plugin_endpoint_id"],
            provider_id_snapshot=local_binding["provider_id_snapshot"],
            provider_kind_snapshot=local_binding["provider_kind_snapshot"],
            execution_node=local_binding["execution_node"],
            local_config_digest=local_binding["local_config_digest"],
            requester=requester,
            requester_username=requester_name,
            approver=approver,
            approver_username=approver_name,
            status=CephApprovalStatusChoices.STATUS_ISSUING,
            issuance_reservation_id=reservation_id,
            issuance_reservation_expires_at=timezone.now() + _APPROVAL_ISSUANCE_TTL,
        )
        locked.status = CephOperationStatusChoices.STATUS_APPLYING
        locked.save(update_fields=("status", "last_updated"))
        return locked, plan, approval, reservation_id


def _ensure_issuance_owner(
    approval: CephOperationApproval,
    issuance_reservation_id: uuid.UUID | None,
    *,
    require_unexpired: bool = True,
) -> None:
    persisted_owner = getattr(approval, "issuance_reservation_id", None)
    persisted_expiry = getattr(approval, "issuance_reservation_expires_at", None)
    # Pure contract tests use token-free records without Django model fields.
    if (
        persisted_owner is None
        and issuance_reservation_id is None
        and not hasattr(approval, "issuance_reservation_id")
    ):
        return
    if (
        issuance_reservation_id is None
        or persisted_owner != issuance_reservation_id
        or persisted_expiry is None
        or (require_unexpired and persisted_expiry <= timezone.now())
    ):
        raise OperationActionError(
            "The approval issuance lease is no longer owned by this worker.",
            kind="invalid",
            reason="approval_reservation_lost",
        )


def _transition_approval_issuance(
    *,
    approval: CephOperationApproval,
    operation: CephOperation,
    issuance_reservation_id: uuid.UUID | None,
    approval_status: str,
    operation_status: str,
    failure_code: str,
    failure_detail: str,
    backend_approval_id: str = "",
) -> None:
    """CAS-update both issuance records or roll back both."""

    with transaction.atomic():
        operation, _plan, approval, _run = _lock_audit_chain(
            operation=operation,
            approval=approval,
        )
        assert approval is not None
        if approval.status != CephApprovalStatusChoices.STATUS_ISSUING:
            raise OperationActionError(
                "The approval reservation changed before issuance was recorded.",
                kind="invalid",
                reason="approval_reservation_lost",
            )
        # This worker has already attempted the backend POST. Its owner UUID
        # may CAS-record the outcome after wall-clock expiry only while no
        # takeover has rotated that UUID.
        _ensure_issuance_owner(
            approval,
            issuance_reservation_id,
            require_unexpired=False,
        )
        approval.backend_approval_id = (
            backend_approval_id if _is_stable_identifier(backend_approval_id) else ""
        )
        approval.status = approval_status
        approval.failure_code = failure_code
        approval.failure_detail = failure_detail
        if hasattr(approval, "issuance_reservation_id"):
            approval.issuance_reservation_id = None
            approval.issuance_reservation_expires_at = None
        approval_fields = [
            "backend_approval_id",
            "status",
            "failure_code",
            "failure_detail",
        ]
        if hasattr(approval, "issuance_reservation_id"):
            approval_fields.extend(("issuance_reservation_id", "issuance_reservation_expires_at"))
        approval_fields.append("last_updated")
        approval.save(update_fields=tuple(approval_fields))
        _transition_checkpoint("approval_issuance.after_approval")
        operation.status = operation_status
        operation.save(update_fields=("status", "last_updated"))


def _post_backend_approval_with_locked_binding(
    orchestrator: CephOrchestratorClient,
    *,
    approval: CephOperationApproval,
    operation: CephOperation,
    plan: CephPlan,
    backend_endpoint_id: int,
    approver_name: str,
    issuance_reservation_id: uuid.UUID | None,
) -> dict[str, Any]:
    """Hold routing locks across issuance so config cannot retarget the POST."""

    if getattr(operation, "pk", None) is None:
        _ensure_issuance_owner(approval, issuance_reservation_id)
        return orchestrator.approve(
            plan.backend_plan_id,
            endpoint_id=backend_endpoint_id,
            actor=approver_name,
        )
    with transaction.atomic():
        locked_operation, local_binding = _lock_binding_source(operation.pk)
        locked_plan = CephPlan.objects.select_for_update().get(pk=plan.pk)
        locked_approval = CephOperationApproval.objects.select_for_update().get(pk=approval.pk)
        _ensure_issuance_owner(locked_approval, issuance_reservation_id)
        _require_binding_matches(locked_plan, local_binding)
        _require_binding_matches(locked_approval, local_binding)
        _validate_plan_is_current(
            locked_operation,
            locked_plan,
            endpoint_id=backend_endpoint_id,
            local_binding=local_binding,
            mark_stale=False,
        )
        return orchestrator.approve(
            locked_plan.backend_plan_id,
            endpoint_id=backend_endpoint_id,
            actor=approver_name,
        )


def _issue_backend_approval(
    orchestrator: CephOrchestratorClient,
    *,
    approval: CephOperationApproval,
    operation: CephOperation,
    plan: CephPlan,
    backend_endpoint_id: int,
    requester: Any,
    requester_name: str,
    approver: Any,
    approver_name: str,
    issuance_reservation_id: uuid.UUID | None = None,
) -> tuple[dict[str, Any], str, str]:
    del requester, approver

    def record_unknown_approval(
        *, failure_code: str, failure_detail: str, backend_approval_id: str = ""
    ) -> None:
        _transition_approval_issuance(
            approval=approval,
            operation=operation,
            issuance_reservation_id=issuance_reservation_id,
            approval_status=CephApprovalStatusChoices.STATUS_OUTCOME_UNKNOWN,
            operation_status=CephOperationStatusChoices.STATUS_OUTCOME_UNKNOWN,
            failure_code=failure_code,
            failure_detail=failure_detail,
            backend_approval_id=backend_approval_id,
        )

    def record_known_failure(*, failure_code: str, failure_detail: str) -> None:
        _transition_approval_issuance(
            approval=approval,
            operation=operation,
            issuance_reservation_id=issuance_reservation_id,
            approval_status=CephApprovalStatusChoices.STATUS_FAILED,
            operation_status=CephOperationStatusChoices.STATUS_FAILED,
            failure_code=failure_code,
            failure_detail=failure_detail,
        )

    try:
        payload = _post_backend_approval_with_locked_binding(
            orchestrator,
            approval=approval,
            operation=operation,
            plan=plan,
            backend_endpoint_id=backend_endpoint_id,
            approver_name=approver_name,
            issuance_reservation_id=issuance_reservation_id,
        )
    except CephOrchestratorHTTPError as exc:
        recovery_approval_id = str(exc.recovery.get("approval_id") or "")
        if _is_ambiguous_http_error(exc) or exc.reason == "approval_already_issued":
            record_unknown_approval(
                backend_approval_id=recovery_approval_id,
                failure_code="approval_transport_outcome_unknown",
                failure_detail=(
                    "The approval outcome requires status recovery before any new plan."
                ),
            )
        else:
            record_known_failure(
                failure_code=exc.reason,
                failure_detail="The backend definitively rejected approval issuance.",
            )
        raise _error_from_orchestrator(exc) from exc
    except (CephOrchestratorTimeout, CephOrchestratorUnavailable) as exc:
        record_unknown_approval(
            failure_code="approval_transport_outcome_unknown",
            failure_detail="The one-time token response was not received; create a fresh plan.",
        )
        raise _error_from_orchestrator(exc) from exc
    except CephOrchestratorUnsupported as exc:
        record_known_failure(
            failure_code="backend_unsupported",
            failure_detail="The backend definitively lacks the canonical approval route.",
        )
        raise _error_from_orchestrator(exc) from exc
    except CephBackendError as exc:
        # A success response that cannot be decoded may follow a committed
        # remote issuance. Never classify that post-POST outcome as a known
        # rejection or allow the plan to issue another approval.
        record_unknown_approval(
            failure_code="approval_transport_outcome_unknown",
            failure_detail="The approval response was unusable after a possible issuance.",
        )
        raise _error_from_orchestrator(exc) from exc

    token = str(payload.get("token") or "")
    approval_id = str(payload.get("id") or "")
    expires_at = _parse_datetime(payload.get("expires_at"))
    expiry_valid = (
        expires_at is not None
        and expires_at > timezone.now()
        and plan.expires_at is not None
        and expires_at <= plan.expires_at
    )
    if not token or len(token) > 4096 or not _is_stable_identifier(approval_id) or not expiry_valid:
        record_unknown_approval(
            backend_approval_id=approval_id if _is_stable_identifier(approval_id) else "",
            failure_code="invalid_approval_contract",
            failure_detail="The backend response was incomplete; the credential was discarded.",
        )
        raise OperationActionError(
            "The backend approval response omitted a valid credential, audit ID, or expiry.",
            kind="backend",
            reason="invalid_approval_contract",
        )
    binding_matches = (
        str(payload.get("plan_id") or "") == plan.backend_plan_id
        and str(payload.get("plan_digest") or "") == plan.backend_plan_digest
        and not isinstance(payload.get("endpoint_id"), bool)
        and isinstance(payload.get("endpoint_id"), int)
        and payload.get("endpoint_id") == backend_endpoint_id
        and str(payload.get("endpoint_config_revision") or "")
        == plan.backend_endpoint_config_revision
        and str(payload.get("requester") or "").casefold() == requester_name.casefold()
        and str(payload.get("approver") or "").casefold() == approver_name.casefold()
    )
    if not binding_matches:
        record_unknown_approval(
            backend_approval_id=approval_id,
            failure_code="approval_binding_mismatch",
            failure_detail="The backend approval did not match the canonical local plan.",
        )
        raise OperationActionError(
            "The backend approval binding did not match the local canonical plan.",
            kind="backend",
            reason="approval_binding_mismatch",
        )
    return payload, token, approval_id


def _persist_approval_and_run(
    *,
    operation: CephOperation,
    plan: CephPlan,
    backend_endpoint_id: int,
    requester: Any,
    approver: Any,
    approval: CephOperationApproval,
    approval_payload: dict[str, Any],
    approval_id: str,
    issuance_reservation_id: uuid.UUID | None = None,
) -> tuple[CephOperationApproval, CephOperationRun]:
    del requester
    with transaction.atomic():
        if isinstance(operation, CephOperation):
            locked_operation, local_binding = _lock_binding_source(operation.pk)
            plan = CephPlan.objects.select_for_update().get(pk=plan.pk)
            approval = CephOperationApproval.objects.select_for_update().get(pk=approval.pk)
            _require_binding_matches(plan, local_binding)
            _require_binding_matches(approval, local_binding)
            _validate_plan_is_current(
                locked_operation,
                plan,
                endpoint_id=backend_endpoint_id,
                local_binding=local_binding,
                mark_stale=False,
            )
        else:
            locked_operation, plan, approval, _run = _lock_audit_chain(
                operation=operation,
                plan=plan,
                approval=approval,
            )
            assert plan is not None and approval is not None
        if approval.status != CephApprovalStatusChoices.STATUS_ISSUING:
            raise OperationActionError(
                "The local approval reservation changed before dispatch.",
                kind="invalid",
                reason="approval_reservation_lost",
            )
        # Approval was already issued remotely. Finalize after expiry only if
        # no takeover has changed the persisted owner UUID.
        _ensure_issuance_owner(
            approval,
            issuance_reservation_id,
            require_unexpired=False,
        )
        approval.backend_approval_id = approval_id
        approval.expires_at = _parse_datetime(approval_payload.get("expires_at"))
        approval.status = CephApprovalStatusChoices.STATUS_APPLYING
        approval.failure_code = ""
        approval.failure_detail = ""
        if hasattr(approval, "issuance_reservation_id"):
            approval.issuance_reservation_id = None
            approval.issuance_reservation_expires_at = None
        approval_fields = [
            "backend_approval_id",
            "expires_at",
            "status",
            "failure_code",
            "failure_detail",
        ]
        if hasattr(approval, "issuance_reservation_id"):
            approval_fields.extend(("issuance_reservation_id", "issuance_reservation_expires_at"))
        approval_fields.append("last_updated")
        approval.save(update_fields=tuple(approval_fields))
        _transition_checkpoint("persist_approval.after_approval")
        run = CephOperationRun.objects.create(
            operation=locked_operation,
            plan=plan,
            provider=locked_operation.provider,
            approval=approval,
            status=CephOperationStatusChoices.STATUS_APPLYING,
            backend_endpoint_config_revision=approval.backend_endpoint_config_revision,
            plugin_endpoint_id=getattr(approval, "plugin_endpoint_id", None),
            provider_id_snapshot=getattr(approval, "provider_id_snapshot", None),
            provider_kind_snapshot=getattr(approval, "provider_kind_snapshot", ""),
            execution_node=getattr(approval, "execution_node", ""),
            local_config_digest=getattr(approval, "local_config_digest", ""),
            actor=approver,
            actor_username=_actor_name(approver),
            source_branch_schema_id=locked_operation.source_branch_schema_id,
            started_at=timezone.now(),
        )
        _transition_checkpoint("persist_approval.after_run")
        locked_operation.status = CephOperationStatusChoices.STATUS_APPLYING
        locked_operation.save(update_fields=("status", "last_updated"))
    return approval, run


def _fail_known_apply(
    exc: CephOrchestratorHTTPError,
    *,
    approval: CephOperationApproval,
    run: CephOperationRun,
    operation: CephOperation,
) -> None:
    with transaction.atomic():
        operation, _plan, approval, run = _lock_audit_chain(
            operation=operation,
            approval=approval,
            run=run,
        )
        assert approval is not None and run is not None
        approval.status = CephApprovalStatusChoices.STATUS_FAILED
        approval.failure_code = exc.reason
        approval.failure_detail = exc.detail
        approval.save(update_fields=("status", "failure_code", "failure_detail", "last_updated"))
        _transition_checkpoint("fail_apply.after_approval")
        run.status = CephOperationStatusChoices.STATUS_FAILED
        run.finished_at = timezone.now()
        run.error = exc.detail
        run.save(update_fields=("status", "finished_at", "error", "last_updated"))
        _transition_checkpoint("fail_apply.after_run")
        operation.status = CephOperationStatusChoices.STATUS_FAILED
        operation.save(update_fields=("status", "last_updated"))


def _handle_apply_http_error(
    exc: CephOrchestratorHTTPError,
    *,
    orchestrator: CephOrchestratorClient,
    approval: CephOperationApproval,
    run: CephOperationRun,
    operation: CephOperation,
    plan: CephPlan,
) -> tuple[str, CephOperationRun | None]:
    """Classify one HTTP failure as recovered, retryable, or definitively failed."""

    recovered_id = str(exc.recovery.get("operation_run_id") or "")
    if _is_stable_identifier(recovered_id):
        approval.backend_run_id = recovered_id
        approval.save(update_fields=("backend_run_id", "last_updated"))
        recovered = _recover_backend_run(
            orchestrator,
            backend_run_id=recovered_id,
            run=run,
            operation=operation,
            approval=approval,
            plan=plan,
        )
        return "recovered", recovered
    if exc.reason in {"approval_replayed", "approval_consumed"}:
        return "recover", None
    if _is_ambiguous_http_error(exc):
        return "retry", None
    _fail_known_apply(exc, approval=approval, run=run, operation=operation)
    raise _error_from_orchestrator(exc, run=run) from exc


def _recover_dispatch_outcome(
    orchestrator: CephOrchestratorClient,
    *,
    approval: CephOperationApproval,
    run: CephOperationRun,
    operation: CephOperation,
    plan: CephPlan,
) -> CephOperationRun | None:
    _mark_outcome_unknown(run, operation, approval)
    try:
        recovered_id = _approval_status_run_id(
            orchestrator,
            approval=approval,
            plan=plan,
            run=run,
            operation=operation,
        )
    except (CephBackendError, OperationActionError):
        return None
    if not recovered_id:
        return None
    approval.backend_run_id = recovered_id
    approval.save(update_fields=("backend_run_id", "last_updated"))
    return _recover_backend_run(
        orchestrator,
        backend_run_id=recovered_id,
        run=run,
        operation=operation,
        approval=approval,
        plan=plan,
    )


def _post_backend_apply_with_locked_binding(
    orchestrator: CephOrchestratorClient,
    *,
    operation: CephOperation,
    plan: CephPlan,
    approval: CephOperationApproval,
    run: CephOperationRun,
    backend_endpoint_id: int,
    token: str,
    requester_name: str,
) -> dict[str, Any]:
    """Hold all routing rows locked across the irreversible backend POST."""

    if not isinstance(operation, CephOperation):
        return orchestrator.apply(
            plan.backend_plan_id,
            endpoint_id=backend_endpoint_id,
            approval_token=token,
            actor=requester_name,
        )
    with transaction.atomic():
        locked_operation, local_binding = _lock_binding_source(operation.pk)
        locked_plan = CephPlan.objects.select_for_update().get(pk=plan.pk)
        locked_approval = CephOperationApproval.objects.select_for_update().get(pk=approval.pk)
        locked_run = CephOperationRun.objects.select_for_update().get(pk=run.pk)
        _require_binding_matches(locked_plan, local_binding)
        _require_binding_matches(locked_approval, local_binding)
        _require_binding_matches(locked_run, local_binding)
        _validate_plan_is_current(
            locked_operation,
            locked_plan,
            endpoint_id=backend_endpoint_id,
            local_binding=local_binding,
            mark_stale=False,
        )
        if (
            locked_approval.status != CephApprovalStatusChoices.STATUS_APPLYING
            or locked_run.approval_id != locked_approval.pk
            or locked_run.operation_id != locked_operation.pk
            or locked_run.plan_id != locked_plan.pk
        ):
            raise OperationActionError(
                "The approval/run audit binding changed before dispatch.",
                kind="invalid",
                reason="run_authority_binding_changed",
                run=locked_run,
            )
        return orchestrator.apply(
            locked_plan.backend_plan_id,
            endpoint_id=backend_endpoint_id,
            approval_token=token,
            actor=requester_name,
        )


def _mark_apply_unsupported(
    *,
    approval: CephOperationApproval,
    run: CephOperationRun,
    operation: CephOperation,
) -> None:
    with transaction.atomic():
        operation, _plan, approval, run = _lock_audit_chain(
            operation=operation,
            approval=approval,
            run=run,
        )
        assert approval is not None and run is not None
        approval.status = CephApprovalStatusChoices.STATUS_FAILED
        approval.failure_code = "backend_unsupported"
        approval.failure_detail = "The canonical apply route is unsupported."
        approval.save(update_fields=("status", "failure_code", "failure_detail", "last_updated"))
        _transition_checkpoint("unsupported_apply.after_approval")
        run.status = CephOperationStatusChoices.STATUS_UNSUPPORTED
        run.finished_at = timezone.now()
        run.error = "The canonical apply route is unsupported."
        run.save(update_fields=("status", "finished_at", "error", "last_updated"))
        _transition_checkpoint("unsupported_apply.after_run")
        operation.status = CephOperationStatusChoices.STATUS_UNSUPPORTED
        operation.save(update_fields=("status", "last_updated"))


def _dispatch_approved_plan(
    orchestrator: CephOrchestratorClient,
    *,
    operation: CephOperation,
    plan: CephPlan,
    approval: CephOperationApproval,
    run: CephOperationRun,
    backend_endpoint_id: int,
    token: str,
    requester_name: str,
) -> CephOperationRun:
    last_transport_error: CephBackendError | None = None
    for _attempt in range(2):
        try:
            response_payload = _post_backend_apply_with_locked_binding(
                orchestrator,
                operation=operation,
                plan=plan,
                approval=approval,
                run=run,
                backend_endpoint_id=backend_endpoint_id,
                token=token,
                requester_name=requester_name,
            )
            return _record_run_response(run, operation, approval, response_payload, plan=plan)
        except CephOrchestratorHTTPError as exc:
            action, recovered = _handle_apply_http_error(
                exc,
                orchestrator=orchestrator,
                approval=approval,
                run=run,
                operation=operation,
                plan=plan,
            )
            if recovered is not None:
                return recovered
            last_transport_error = exc
            if action == "recover":
                break
        except (CephOrchestratorTimeout, CephOrchestratorUnavailable) as exc:
            last_transport_error = exc
        except CephOrchestratorUnsupported as exc:
            _mark_apply_unsupported(approval=approval, run=run, operation=operation)
            raise _error_from_orchestrator(exc, run=run) from exc
        except CephBackendError as exc:
            last_transport_error = exc
        except OperationActionError:
            _mark_outcome_unknown(run, operation, approval)
            raise

    recovered = _recover_dispatch_outcome(
        orchestrator,
        approval=approval,
        run=run,
        operation=operation,
        plan=plan,
    )
    if recovered is not None:
        return recovered
    assert last_transport_error is not None
    raise _error_from_orchestrator(last_transport_error, run=run) from last_transport_error


def approve_and_apply_operation(
    operation: CephOperation,
    *,
    approver: Any,
) -> CephOperationRun:
    """Reserve durable intent, issue approval, and apply with a transient token."""

    requester, requester_name, approver_name = _approval_actors(operation, approver)
    if getattr(operation, "status", None) not in {
        CephOperationStatusChoices.STATUS_PLANNED,
        CephOperationStatusChoices.STATUS_APPLYING,
        CephOperationStatusChoices.STATUS_OUTCOME_UNKNOWN,
    }:
        raise OperationActionError(
            "Operation must be planned before independent approval.",
            kind="invalid",
            reason="operation_not_planned",
        )
    _validate_operation_provider(operation)

    orchestrator = CephOrchestratorClient()
    try:
        backend_endpoint_id = orchestrator.resolve_backend_endpoint_id(operation.cluster.endpoint)
    except CephBackendError as exc:
        raise _error_from_orchestrator(exc) from exc
    operation, plan, approval, issuance_reservation_id = _reserve_approval_intent(
        operation,
        endpoint_id=backend_endpoint_id,
        requester=requester,
        requester_name=requester_name,
        approver=approver,
        approver_name=approver_name,
    )
    if issuance_reservation_id is None:
        if (
            approval.status == CephApprovalStatusChoices.STATUS_ISSUING
            and not approval.backend_approval_id
        ):
            raise OperationActionError(
                "Another worker owns the live approval issuance lease.",
                kind="invalid",
                reason="approval_issuance_in_flight",
            )
        if approval.status in {
            CephApprovalStatusChoices.STATUS_FAILED,
            CephApprovalStatusChoices.STATUS_EXPIRED,
        }:
            raise OperationActionError(
                "The prior approval is terminal; create a fresh canonical plan.",
                kind="invalid",
                reason="approval_terminal",
            )
        return _recover_existing_approval(
            orchestrator,
            approval=approval,
            operation=operation,
            plan=plan,
            approver=approver,
        )

    approval_payload, token, approval_id = _issue_backend_approval(
        orchestrator,
        approval=approval,
        operation=operation,
        plan=plan,
        backend_endpoint_id=backend_endpoint_id,
        requester=requester,
        requester_name=requester_name,
        approver=approver,
        approver_name=approver_name,
        issuance_reservation_id=issuance_reservation_id,
    )
    try:
        approval, run = _persist_approval_and_run(
            operation=operation,
            plan=plan,
            backend_endpoint_id=backend_endpoint_id,
            requester=requester,
            approver=approver,
            approval=approval,
            approval_payload=approval_payload,
            approval_id=approval_id,
            issuance_reservation_id=issuance_reservation_id,
        )
    except Exception as exc:  # noqa: BLE001 - post-issuance failures all require quarantine
        failure_code = (
            exc.reason if isinstance(exc, OperationActionError) else "approval_persistence_failed"
        )
        try:
            _transition_approval_issuance(
                approval=approval,
                operation=operation,
                issuance_reservation_id=issuance_reservation_id,
                approval_status=CephApprovalStatusChoices.STATUS_OUTCOME_UNKNOWN,
                operation_status=CephOperationStatusChoices.STATUS_OUTCOME_UNKNOWN,
                failure_code=failure_code,
                failure_detail=(
                    "The approval was issued but local authority could not be persisted safely."
                ),
                backend_approval_id=approval_id,
            )
        except OperationActionError:
            # A rotated issuance owner is authoritative; the late worker must
            # not overwrite it while propagating its original failure.
            pass
        raise
    return _dispatch_approved_plan(
        orchestrator,
        operation=operation,
        plan=plan,
        approval=approval,
        run=run,
        backend_endpoint_id=backend_endpoint_id,
        token=token,
        requester_name=requester_name,
    )


def apply_operation(
    operation: CephOperation,
    *,
    actor: Any = None,
    confirmed: bool = False,
) -> CephOperationRun:
    """Compatibility entry point; legacy confirmation is deliberately ignored."""

    del confirmed
    return approve_and_apply_operation(operation, approver=actor)


def reconcile_provider(
    provider: CephProvider,
    *,
    actor: Any = None,
    scope: dict[str, Any] | None = None,
) -> CephOperationRun:
    """Record a read-only provider reconciliation through proxbox-api."""

    _require_permission(actor, "netbox_ceph.change_cephprovider", provider)
    try:
        validate_secret_free_intent(scope or {}, path="scope")
    except SecretBearingIntentError as exc:
        raise OperationActionError(
            "The reconciliation scope contains forbidden credential material.",
            kind="invalid",
            reason="secret_bearing_intent",
        ) from exc
    actor_name = _actor_name(actor)
    operation = CephOperation.objects.create(
        cluster=provider.cluster,
        provider=provider,
        operation_type=CephOperationTypeChoices.TYPE_RECONCILE,
        target_kind="provider",
        target_ref=provider.name,
        desired={"scope": scope or {}},
        is_destructive=False,
        confirmation_required=False,
        requested_by=actor,
        requested_by_username=actor_name,
        status=CephOperationStatusChoices.STATUS_APPLYING,
    )
    run = CephOperationRun.objects.create(
        operation=operation,
        provider=provider,
        status=CephOperationStatusChoices.STATUS_APPLYING,
        actor=actor,
        actor_username=actor_name,
        started_at=timezone.now(),
    )
    orchestrator = CephOrchestratorClient()
    try:
        backend_endpoint_id = orchestrator.resolve_backend_endpoint_id(provider.cluster.endpoint)
        response_payload = orchestrator.reconcile(
            {
                "provider": provider.kind,
                "endpoint_id": backend_endpoint_id,
                "scope": scope or {},
            },
            actor=actor_name,
        )
    except CephBackendError as exc:
        run.status = _failed_status_for(exc)
        run.finished_at = timezone.now()
        run.error = "Read-only reconciliation failed."
        run.save(update_fields=("status", "finished_at", "error", "last_updated"))
        operation.status = run.status
        operation.save(update_fields=("status", "last_updated"))
        raise _error_from_orchestrator(exc, run=run) from exc

    run.status = run_status(
        response_payload.get("status"),
        CephOperationStatusChoices.STATUS_OUTCOME_UNKNOWN,
    )
    run.backend_run_id = (
        str(response_payload.get("id")) if _is_stable_identifier(response_payload.get("id")) else ""
    )
    run.provider_task_ref = redact_text(provider_task_ref(response_payload))[:255]
    run.outcome_unknown = run.status == CephOperationStatusChoices.STATUS_OUTCOME_UNKNOWN
    run.finished_at = timezone.now() if run.status in _TERMINAL_RUN_STATUSES else None
    run.result = redact_secrets(response_payload)
    run.save(
        update_fields=(
            "status",
            "backend_run_id",
            "provider_task_ref",
            "outcome_unknown",
            "finished_at",
            "result",
            "last_updated",
        )
    )
    operation.status = run.status
    operation.save(update_fields=("status", "last_updated"))
    return run
