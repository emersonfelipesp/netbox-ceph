"""Shared service for triggering Ceph v2 operation actions.

Owns the proxbox-api orchestrator call plus persistence and status transitions
for ``plan``, ``apply`` and provider ``reconcile``, so the DRF API viewset and
the NetBox web action views share one implementation. Callers translate
:class:`OperationActionError` into their own surface — HTTP status codes for the
REST API, flash messages for the UI.

The orchestration helpers (``operation_payload``, ``refresh_plan``,
``run_status``, ``provider_task_ref`` …) live here so both layers consume the
same proxbox-api response mapping (see ``ceph_v2_responses``).
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from netbox_ceph.choices import (
    CephOperationStatusChoices,
    CephOperationTypeChoices,
    CephPlanStatusChoices,
    CephValidationSeverityChoices,
)
from netbox_ceph.models import (
    CephOperation,
    CephOperationRun,
    CephPlan,
    CephProvider,
    CephValidationResult,
)
from netbox_ceph.services import ceph_v2_responses
from netbox_ceph.services.http_client import CephBackendError
from netbox_ceph.services.orchestrator import (
    CephOrchestratorClient,
    CephOrchestratorUnavailable,
    CephOrchestratorUnsupported,
)

_SUCCESS_RUN_UPDATE_FIELDS = (
    "status",
    "provider_task_ref",
    "finished_at",
    "result",
    "warnings",
    "error",
    "last_updated",
)


class OperationActionError(Exception):
    """A plan/apply/reconcile action that could not complete.

    ``kind`` drives the caller's response mapping:

    - ``invalid``    -> client error (HTTP 400)
    - ``unsupported``-> backend lacks the route (HTTP 409)
    - ``unavailable``-> backend unreachable (HTTP 503)
    - ``backend``    -> backend returned an error (HTTP 502)

    ``run`` carries the persisted :class:`CephOperationRun` when one was created
    before the failure, so the API can serialize it in the error response.
    """

    def __init__(self, message: Any, *, kind: str = "backend", run: CephOperationRun | None = None):
        super().__init__(str(message))
        self.message = str(message)
        self.kind = kind
        self.run = run


# --------------------------------------------------------------------------- #
# Orchestration helpers (shared response mapping)
# --------------------------------------------------------------------------- #


def operation_payload(operation: CephOperation) -> dict[str, Any]:
    """Serialize a ``CephOperation`` into the proxbox-api ``/ceph/v2`` payload."""

    provider = operation.provider
    return {
        "id": operation.pk,
        "cluster_id": operation.cluster_id,
        "provider_id": operation.provider_id,
        "provider_kind": provider.kind if provider is not None else None,
        "provider_name": provider.name if provider is not None else None,
        "operation_type": operation.operation_type,
        "target_kind": operation.target_kind,
        "target_ref": operation.target_ref,
        "desired": operation.desired,
        "is_destructive": operation.is_destructive,
        "confirmation_required": operation.confirmation_required,
        "confirmed": operation.confirmed,
        "source_branch_schema_id": operation.source_branch_schema_id,
    }


def _choice_or_default(value: Any, choices: list[tuple[str, str, str]], default: str) -> str:
    allowed = {choice[0] for choice in choices}
    if value in allowed:
        return str(value)
    return default


def _plan_payload(response: dict[str, Any]) -> dict[str, Any]:
    plan = response.get("plan")
    if isinstance(plan, dict):
        return plan
    return response


def _validation_payloads(
    response: dict[str, Any], plan_payload: dict[str, Any]
) -> list[dict[str, Any]]:
    candidates = response.get("validations", plan_payload.get("validations", []))
    if not isinstance(candidates, list):
        return []
    return [item for item in candidates if isinstance(item, dict)]


def latest_plan(operation: CephOperation) -> CephPlan | None:
    return operation.plans.order_by("-generated_at", "-created", "-pk").first()


def _plan_status_from_response(payload: dict[str, Any]) -> str:
    valid_choices = {choice[0] for choice in CephPlanStatusChoices.CHOICES}
    status_value = ceph_v2_responses.plan_status_value(payload, valid_choices=valid_choices)
    if status_value in valid_choices:
        return str(status_value)
    return CephPlanStatusChoices.STATUS_DRAFT


def refresh_plan(
    operation: CephOperation,
    response_payload: dict[str, Any],
) -> tuple[CephPlan, list[CephValidationResult]]:
    payload = _plan_payload(response_payload)
    fields = ceph_v2_responses.plan_fields_from_response(payload)
    plan = latest_plan(operation) or CephPlan(operation=operation)
    plan.status = _plan_status_from_response(payload)
    plan.summary = fields["summary"]
    plan.intended_changes = fields["intended_changes"]
    plan.provider_target = fields["provider_target"]
    plan.blast_radius = fields["blast_radius"]
    plan.expected_tasks = fields["expected_tasks"]
    plan.rollback_limits = str(payload.get("rollback_limits", ""))
    plan.is_destructive = bool(fields["is_destructive"] or operation.is_destructive)
    plan.generated_at = timezone.now()
    plan.raw = response_payload
    plan.save()

    plan.validations.all().delete()
    validations: list[CephValidationResult] = []
    for item in _validation_payloads(response_payload, payload):
        validation = CephValidationResult.objects.create(
            plan=plan,
            operation=operation,
            severity=_choice_or_default(
                item.get("severity"),
                CephValidationSeverityChoices.CHOICES,
                CephValidationSeverityChoices.SEVERITY_INFO,
            ),
            code=str(item.get("code", "backend")),
            message=str(item.get("message", "")),
            target=str(item.get("target", "")),
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


# --------------------------------------------------------------------------- #
# Run lifecycle helpers
# --------------------------------------------------------------------------- #


def _fail_run(
    run: CephOperationRun,
    operation: CephOperation,
    exc: Exception,
    status_value: str,
) -> None:
    run.status = status_value
    run.finished_at = timezone.now()
    run.error = str(exc)
    run.save(update_fields=("status", "finished_at", "error", "last_updated"))
    operation.status = status_value
    operation.save(update_fields=("status", "last_updated"))


def _record_success(
    run: CephOperationRun,
    operation: CephOperation,
    response_payload: dict[str, Any],
    *,
    plan: CephPlan | None = None,
) -> CephOperationRun:
    run.status = run_status(
        response_payload.get("status"),
        CephOperationStatusChoices.STATUS_SUCCEEDED,
    )
    run.provider_task_ref = provider_task_ref(response_payload)
    run.finished_at = timezone.now()
    run.result = response_payload
    warnings = response_payload.get("warnings", [])
    run.warnings = warnings if isinstance(warnings, list) else [str(warnings)]
    errors = response_payload.get("errors", [])
    if isinstance(errors, list) and errors:
        run.error = "; ".join(str(item) for item in errors if item)
    run.save(update_fields=_SUCCESS_RUN_UPDATE_FIELDS)
    operation.status = run.status
    operation.save(update_fields=("status", "last_updated"))
    if plan is not None and run.status == CephOperationStatusChoices.STATUS_SUCCEEDED:
        plan.status = CephPlanStatusChoices.STATUS_APPLIED
        plan.save(update_fields=("status", "last_updated"))
    return run


def _raise_for_orchestrator(exc: Exception, *, run: CephOperationRun | None = None) -> None:
    """Map an orchestrator exception to an :class:`OperationActionError`."""

    if isinstance(exc, CephOrchestratorUnsupported):
        raise OperationActionError(exc, kind="unsupported", run=run) from exc
    if isinstance(exc, CephOrchestratorUnavailable):
        raise OperationActionError(exc, kind="unavailable", run=run) from exc
    raise OperationActionError(exc, kind="backend", run=run) from exc


def _failed_status_for(exc: Exception) -> str:
    if isinstance(exc, CephOrchestratorUnsupported):
        return CephOperationStatusChoices.STATUS_UNSUPPORTED
    return CephOperationStatusChoices.STATUS_FAILED


# --------------------------------------------------------------------------- #
# Public actions
# --------------------------------------------------------------------------- #


def plan_operation(
    operation: CephOperation,
    *,
    requested_by: Any = None,
) -> tuple[CephPlan, list[CephValidationResult]]:
    """Build a provider plan for ``operation`` and persist it."""

    operation.status = CephOperationStatusChoices.STATUS_PLANNING
    if operation.requested_by_id is None:
        operation.requested_by = requested_by
    operation.save(update_fields=("status", "requested_by", "last_updated"))

    orchestrator = CephOrchestratorClient()
    try:
        response_payload = orchestrator.plan(operation_payload(operation))
    except CephBackendError as exc:
        operation.status = _failed_status_for(exc)
        operation.save(update_fields=("status", "last_updated"))
        _raise_for_orchestrator(exc)

    plan, validations = refresh_plan(operation, response_payload)
    operation.status = CephOperationStatusChoices.STATUS_PLANNED
    operation.save(update_fields=("status", "last_updated"))
    return plan, validations


def apply_operation(
    operation: CephOperation,
    *,
    actor: Any = None,
    confirmed: bool = False,
) -> CephOperationRun:
    """Execute the latest plan for ``operation``, gated on confirmation."""

    if operation.status != CephOperationStatusChoices.STATUS_PLANNED:
        raise OperationActionError(
            "Operation must be in planned status before apply.", kind="invalid"
        )

    plan = latest_plan(operation)
    if plan is None:
        raise OperationActionError("Operation has no generated plan to apply.", kind="invalid")

    if confirmed is True and not operation.confirmed:
        operation.confirmed = True
        operation.confirmed_by = actor
        operation.confirmed_at = timezone.now()
        operation.save(
            update_fields=("confirmed", "confirmed_by", "confirmed_at", "last_updated")
        )

    if (operation.is_destructive or operation.confirmation_required) and not operation.confirmed:
        raise OperationActionError(
            "Destructive or confirmation-required operations need confirmed=True.",
            kind="invalid",
        )

    run = CephOperationRun.objects.create(
        operation=operation,
        plan=plan,
        provider=operation.provider,
        status=CephOperationStatusChoices.STATUS_APPLYING,
        actor=actor,
        source_branch_schema_id=operation.source_branch_schema_id,
        started_at=timezone.now(),
    )
    operation.status = CephOperationStatusChoices.STATUS_APPLYING
    operation.save(update_fields=("status", "last_updated"))

    payload = {**operation_payload(operation), "plan_id": plan.pk, "plan": plan.raw}
    orchestrator = CephOrchestratorClient()
    try:
        response_payload = orchestrator.apply(payload)
    except CephBackendError as exc:
        _fail_run(run, operation, exc, _failed_status_for(exc))
        _raise_for_orchestrator(exc, run=run)

    return _record_success(run, operation, response_payload, plan=plan)


def reconcile_provider(
    provider: CephProvider,
    *,
    actor: Any = None,
    scope: dict[str, Any] | None = None,
) -> CephOperationRun:
    """Reconcile live provider state into NetBox via ``/ceph/v2/reconcile``.

    Records an auditable provider-scoped operation and run.
    """

    operation = CephOperation(
        cluster=provider.cluster,
        provider=provider,
        operation_type=CephOperationTypeChoices.TYPE_RECONCILE,
        target_kind="provider",
        target_ref=provider.name,
        desired={"scope": scope or {}},
        is_destructive=False,
        confirmation_required=False,
        requested_by=actor,
        status=CephOperationStatusChoices.STATUS_APPLYING,
    )
    operation.save()
    run = CephOperationRun.objects.create(
        operation=operation,
        provider=provider,
        status=CephOperationStatusChoices.STATUS_APPLYING,
        actor=actor,
        started_at=timezone.now(),
    )

    orchestrator = CephOrchestratorClient()
    try:
        response_payload = orchestrator.reconcile({"provider": provider.kind, "scope": scope or {}})
    except CephBackendError as exc:
        _fail_run(run, operation, exc, _failed_status_for(exc))
        _raise_for_orchestrator(exc, run=run)

    return _record_success(run, operation, response_payload)
