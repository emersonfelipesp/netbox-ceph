"""Pure-python tests for proxbox-api -> NetBox Ceph v2 response mapping (issue #9).

Asserts that the real proxbox-api #95 ``PlanResponse``/``OperationRun`` shapes
are translated into NetBox plan/run fields, and that legacy ``plan``-wrapped /
``summary``-shaped responses still parse.
"""

from __future__ import annotations

from netbox_ceph.services import ceph_v2_responses as responses

# The netbox CephOperationStatusChoices / CephPlanStatusChoices values the
# mapper is allowed to produce (kept in sync with netbox_ceph/choices.py; the
# Django contract test asserts these are real choices).
_RUN_STATUS_VALUES = {
    "succeeded",
    "applying",
    "outcome_unknown",
    "failed",
    "cancelled",
    "pending",
}
_PLAN_STATUS_VALUES = {"draft", "valid", "invalid", "applied", "stale"}

_PLAN_RESPONSE = {
    "id": "plan-123",
    "provider": "proxmox",
    "operations": [
        {"kind": "pool", "action": "create", "target_ref": "rbd", "is_destructive": False},
        {"kind": "pool", "action": "delete", "target_ref": "old", "is_destructive": True},
    ],
    "blocked_actions": [
        {
            "kind": "filesystem",
            "action": "delete",
            "target_ref": "fs1",
            "blocked_reason": "unsupported",
        }
    ],
    "validations": [{"severity": "info", "code": "ok", "message": "fine"}],
    "warnings": ["recovery in progress"],
    "live_state_summary": {"pools": 3},
    "created_at": "2026-06-04T00:00:00Z",
}

_OPERATION_RUN = {
    "id": "run-1",
    "status": "completed",
    "provider": "proxmox",
    "provider_task_refs": ["UPID:node1:pool_create", "UPID:node1:pool_delete"],
    "warnings": [],
    "errors": [],
    "result_summary": {"applied": 2, "total": 2},
}


def test_run_status_map_targets_are_valid_choice_values() -> None:
    assert set(responses.RUN_STATUS_MAP.values()) <= _RUN_STATUS_VALUES
    assert {responses.PLAN_STATUS_VALID, responses.PLAN_STATUS_INVALID} <= _PLAN_STATUS_VALUES


def test_map_run_status_covers_proxbox_statuses() -> None:
    assert responses.map_run_status("completed") == "succeeded"
    assert responses.map_run_status("running") == "applying"
    assert responses.map_run_status("dispatching") == "applying"
    assert responses.map_run_status("blocked") == "failed"
    assert responses.map_run_status("failed") == "failed"
    assert responses.map_run_status("cancelled") == "cancelled"
    assert responses.map_run_status("ok") == "succeeded"  # legacy
    assert responses.map_run_status("weird-unknown") is None
    assert responses.map_run_status(None) is None


def test_blocked_actions_make_plan_invalid() -> None:
    assert (
        responses.plan_status_value(
            {"blocked_actions": [{"kind": "pool", "action": "delete"}]},
            valid_choices={"valid", "invalid"},
        )
        == "invalid"
    )


def test_provider_task_ref_joins_list() -> None:
    assert (
        responses.provider_task_ref(_OPERATION_RUN)
        == "UPID:node1:pool_create, UPID:node1:pool_delete"
    )


def test_provider_task_ref_singular_back_compat() -> None:
    assert responses.provider_task_ref({"provider_task_ref": "UPID:x"}) == "UPID:x"
    assert responses.provider_task_ref({"task_ref": "UPID:y"}) == "UPID:y"
    assert responses.provider_task_ref({"provider_task_refs": []}) == ""
    assert responses.provider_task_ref({}) == ""


def test_plan_fields_derived_from_operations() -> None:
    fields = responses.plan_fields_from_response(_PLAN_RESPONSE)
    assert fields["intended_changes"] == [
        {
            "kind": "pool",
            "action": "create",
            "target_ref": "rbd",
            "is_destructive": False,
            "blocked_reason": None,
        },
        {
            "kind": "pool",
            "action": "delete",
            "target_ref": "old",
            "is_destructive": True,
            "blocked_reason": None,
        },
    ]
    assert fields["expected_tasks"] == ["create pool rbd", "delete pool old"]
    assert fields["is_destructive"] is True  # a delete op + a blocked action
    assert "2 operation(s)" in fields["summary"]
    assert "1 blocked" in fields["summary"]
    assert "1 warning(s)" in fields["summary"]
    assert fields["blast_radius"] == {"pools": 3}
    assert fields["provider_target"] == "proxmox"


def test_plan_fields_prefers_explicit_legacy_fields() -> None:
    legacy = {
        "summary": "ok",
        "intended_changes": [{"x": 1}],
        "expected_tasks": ["t1"],
        "provider_target": "cluster-a",
        "blast_radius": {"a": 1},
    }
    fields = responses.plan_fields_from_response(legacy)
    assert fields["summary"] == "ok"
    assert fields["intended_changes"] == [{"x": 1}]
    assert fields["expected_tasks"] == ["t1"]
    assert fields["provider_target"] == "cluster-a"
    assert fields["blast_radius"] == {"a": 1}


def test_plan_status_value_invalid_on_error_validation() -> None:
    valid = {"valid", "invalid", "draft", "applied", "stale"}
    unblocked = dict(_PLAN_RESPONSE, blocked_actions=[])
    assert responses.plan_status_value(unblocked, valid_choices=valid) == "valid"
    assert responses.plan_status_value(_PLAN_RESPONSE, valid_choices=valid) == "invalid"
    with_error = dict(_PLAN_RESPONSE, validations=[{"severity": "error", "message": "bad"}])
    assert responses.plan_status_value(with_error, valid_choices=valid) == "invalid"
    explicit = {"status": "applied", "validations": []}
    assert responses.plan_status_value(explicit, valid_choices=valid) == "applied"


def test_empty_plan_response_is_safe() -> None:
    fields = responses.plan_fields_from_response({})
    assert fields["intended_changes"] == []
    assert fields["expected_tasks"] == []
    assert fields["is_destructive"] is False
    assert fields["summary"] == "0 operation(s)"
    assert fields["blast_radius"] == {}
    assert fields["provider_target"] == ""
