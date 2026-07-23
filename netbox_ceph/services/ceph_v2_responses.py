"""Pure mappers from proxbox-api ``/ceph/v2`` response shapes to NetBox fields.

proxbox-api (#95) returns ``PlanResponse``/``OperationRun`` with these field
names:

- ``PlanResponse``: ``operations``, ``blocked_actions``, ``validations``,
  ``warnings``, ``live_state_summary`` (no ``plan`` wrapper, no ``summary``).
- ``OperationRun``: ``status`` (``completed``/``running``/``failed``/
  ``blocked``/``cancelled``/``pending``), ``provider_task_refs`` (list of UPIDs),
  ``warnings``, ``errors``, ``result_summary``.

netbox-ceph's models use different field names, so these helpers translate. They
are intentionally Django-free and string-literal based so they can be unit
tested without a NetBox runtime; ``netbox_ceph.api.views`` wraps them with the
``ChoiceSet`` validation. The literal status values mirror
``CephOperationStatusChoices``/``CephPlanStatusChoices`` and are asserted against
those choices by the contract tests.
"""

from __future__ import annotations

from typing import Any

# proxbox-api OperationRun.status -> CephOperationStatusChoices value.
RUN_STATUS_MAP: dict[str, str] = {
    "completed": "succeeded",
    "ok": "succeeded",
    "succeeded": "succeeded",
    "running": "applying",
    "dispatching": "applying",
    "applying": "applying",
    "submitted": "applying",
    "outcome_unknown": "outcome_unknown",
    "failed": "failed",
    "blocked": "failed",
    "cancelled": "cancelled",
    "pending": "pending",
}

# CephPlanStatusChoices values used by plan-status derivation.
PLAN_STATUS_VALID = "valid"
PLAN_STATUS_INVALID = "invalid"


def map_run_status(value: Any) -> str | None:
    """Return the NetBox run-status value for a proxbox-api status, or ``None``."""
    if isinstance(value, str):
        return RUN_STATUS_MAP.get(value)
    return None


def provider_task_ref(response: dict[str, Any]) -> str:
    """Join ``provider_task_refs`` (list of UPIDs); fall back to singular keys."""
    refs = response.get("provider_task_refs")
    if isinstance(refs, list):
        joined = ", ".join(str(ref) for ref in refs if ref)
        if joined:
            return joined
    return str(response.get("provider_task_ref") or response.get("task_ref") or "")


def operation_summary(op: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": op.get("kind"),
        "action": op.get("action"),
        "target_ref": op.get("target_ref"),
        "is_destructive": bool(op.get("is_destructive")),
        "blocked_reason": op.get("blocked_reason"),
    }


def plan_fields_from_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Derive CephPlan display fields from a ``PlanResponse`` (or legacy) payload.

    Prefers explicit legacy fields (``summary``/``intended_changes``/
    ``expected_tasks``) when present, otherwise derives them from ``operations``
    so the NetBox plan UI is populated against the real #95 schema.
    """
    ops = [op for op in payload.get("operations", []) if isinstance(op, dict)]
    blocked = [op for op in payload.get("blocked_actions", []) if isinstance(op, dict)]
    warnings = [w for w in payload.get("warnings", []) if isinstance(w, str)]

    intended = payload.get("intended_changes")
    if not isinstance(intended, list) or not intended:
        intended = [operation_summary(op) for op in ops]

    expected = payload.get("expected_tasks")
    if not isinstance(expected, list) or not expected:
        expected = [
            " ".join(
                str(part)
                for part in (op.get("action"), op.get("kind"), op.get("target_ref"))
                if part
            )
            for op in ops
        ]

    is_destructive = (
        bool(payload.get("is_destructive"))
        or any(op.get("is_destructive") for op in ops)
        or bool(blocked)
    )

    summary = payload.get("summary")
    if not summary:
        parts = [f"{len(ops)} operation(s)"]
        if blocked:
            parts.append(f"{len(blocked)} blocked")
        if warnings:
            parts.append(f"{len(warnings)} warning(s)")
        summary = "; ".join(parts)

    blast_radius = payload.get("blast_radius")
    if not isinstance(blast_radius, dict) or not blast_radius:
        live = payload.get("live_state_summary")
        blast_radius = live if isinstance(live, dict) else {}

    provider_target = payload.get("provider_target") or payload.get("provider") or ""

    return {
        "intended_changes": intended,
        "expected_tasks": expected,
        "is_destructive": is_destructive,
        "summary": str(summary),
        "blast_radius": blast_radius,
        "provider_target": str(provider_target),
    }


def plan_status_value(payload: dict[str, Any], *, valid_choices: set[str]) -> str | None:
    """Derive a plan-status value: explicit (if valid), else invalid on errors.

    Returns ``None`` to mean "no error-derived override" so the caller can keep a
    default when there are no error validations.
    """
    explicit = payload.get("status")
    if isinstance(explicit, str) and explicit in valid_choices:
        return explicit
    validations = payload.get("validations", [])
    blocked_actions = payload.get("blocked_actions", [])
    if isinstance(blocked_actions, list) and blocked_actions:
        return PLAN_STATUS_INVALID
    if isinstance(validations, list) and any(
        isinstance(item, dict) and item.get("severity") == "error" for item in validations
    ):
        return PLAN_STATUS_INVALID
    return PLAN_STATUS_VALID
