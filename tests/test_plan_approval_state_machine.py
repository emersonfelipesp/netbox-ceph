"""Pure contract tests for token-transient apply and ambiguity recovery."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import os
import sys
import types
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ENDPOINT_CONFIG_REVISION = "e" * 64


class _Manager:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.records: list[SimpleNamespace] = []

    def create(self, **kwargs):
        self.created.append(kwargs)
        value = _record(pk=len(self.records) + 1, **kwargs)
        self.records.append(value)
        return value

    def add(self, value):
        if not hasattr(value, "pk"):
            value.pk = len(self.records) + 1
        self.records.append(value)
        return value

    def select_for_update(self, *args, **kwargs):
        return self

    def select_related(self, *args):
        return self

    def get(self, **kwargs):
        matches = [
            value
            for value in self.records
            if all(getattr(value, key) == expected for key, expected in kwargs.items())
        ]
        if len(matches) != 1:
            raise AssertionError(f"expected one record for {kwargs}, found {len(matches)}")
        return matches[0]


class _Relation:
    def __init__(self, exists: bool = False) -> None:
        self._exists = exists

    def filter(self, **kwargs):
        return self

    def exclude(self, **kwargs):
        return self

    def exists(self) -> bool:
        return self._exists


def _record(**kwargs):
    value = SimpleNamespace(**kwargs)
    value.saved = []
    value.save = lambda **save_kwargs: value.saved.append(save_kwargs)
    return value


def _choice_class(**values):
    values["CHOICES"] = [(value, value, "gray") for value in values.values()]
    return type("Choice", (), values)


@pytest.fixture
def actions(monkeypatch: pytest.MonkeyPatch):
    django = types.ModuleType("django")
    django_db = types.ModuleType("django.db")

    @contextmanager
    def atomic():
        yield

    django_db.transaction = SimpleNamespace(atomic=atomic)
    django_utils = types.ModuleType("django.utils")
    fixed_now = datetime(2026, 7, 22, tzinfo=UTC)
    django_timezone = types.ModuleType("django.utils.timezone")
    django_timezone.now = lambda: fixed_now
    django_timezone.is_naive = lambda value: value.tzinfo is None
    django_timezone.make_aware = lambda value, tz: value.replace(tzinfo=tz)
    django_timezone.get_current_timezone = lambda: UTC
    django_utils.timezone = django_timezone
    monkeypatch.setitem(sys.modules, "django", django)
    monkeypatch.setitem(sys.modules, "django.db", django_db)
    monkeypatch.setitem(sys.modules, "django.utils", django_utils)
    monkeypatch.setitem(sys.modules, "django.utils.timezone", django_timezone)

    choices = types.ModuleType("netbox_ceph.choices")
    choices.CephApprovalStatusChoices = _choice_class(
        STATUS_ISSUING="issuing",
        STATUS_ISSUED="issued",
        STATUS_APPLYING="applying",
        STATUS_CONSUMED="consumed",
        STATUS_OUTCOME_UNKNOWN="outcome_unknown",
        STATUS_FAILED="failed",
        STATUS_EXPIRED="expired",
    )
    choices.CephOperationStatusChoices = _choice_class(
        STATUS_PENDING="pending",
        STATUS_PLANNING="planning",
        STATUS_PLANNED="planned",
        STATUS_APPLYING="applying",
        STATUS_OUTCOME_UNKNOWN="outcome_unknown",
        STATUS_SUCCEEDED="succeeded",
        STATUS_FAILED="failed",
        STATUS_CANCELLED="cancelled",
        STATUS_UNSUPPORTED="unsupported",
    )
    choices.CephOperationTypeChoices = _choice_class(
        TYPE_CREATE="create",
        TYPE_UPDATE="update",
        TYPE_DELETE="delete",
        TYPE_RECONCILE="reconcile",
    )
    choices.CephProviderKindChoices = _choice_class(KIND_PROXMOX="proxmox")
    choices.CephPlanStatusChoices = _choice_class(
        STATUS_DRAFT="draft",
        STATUS_VALID="valid",
        STATUS_INVALID="invalid",
        STATUS_APPLIED="applied",
        STATUS_STALE="stale",
    )
    choices.CephValidationSeverityChoices = _choice_class(SEVERITY_INFO="info")
    monkeypatch.setitem(sys.modules, "netbox_ceph.choices", choices)

    models = types.ModuleType("netbox_ceph.models")
    for name in (
        "CephCluster",
        "CephOperation",
        "CephOperationApproval",
        "CephOperationRun",
        "CephPlan",
        "CephProvider",
        "CephValidationResult",
    ):
        model = type(name, (), {})
        model.objects = _Manager()
        setattr(models, name, model)
    monkeypatch.setitem(sys.modules, "netbox_ceph.models", models)

    http_client = types.ModuleType("netbox_ceph.services.http_client")

    class CephBackendError(RuntimeError):
        pass

    http_client.CephBackendError = CephBackendError
    monkeypatch.setitem(sys.modules, "netbox_ceph.services.http_client", http_client)

    orchestrator = types.ModuleType("netbox_ceph.services.orchestrator")

    class CephOrchestratorUnavailable(CephBackendError):
        pass

    class CephOrchestratorTimeout(CephOrchestratorUnavailable):
        pass

    class CephOrchestratorUnsupported(CephBackendError):
        pass

    class CephOrchestratorHTTPError(CephBackendError):
        def __init__(self, status_code, reason, detail, recovery=None):
            super().__init__(detail)
            self.status_code = status_code
            self.reason = reason
            self.detail = detail
            self.recovery = recovery or {}

    orchestrator.CephOrchestratorClient = object
    orchestrator.CephOrchestratorUnavailable = CephOrchestratorUnavailable
    orchestrator.CephOrchestratorTimeout = CephOrchestratorTimeout
    orchestrator.CephOrchestratorUnsupported = CephOrchestratorUnsupported
    orchestrator.CephOrchestratorHTTPError = CephOrchestratorHTTPError
    monkeypatch.setitem(sys.modules, "netbox_ceph.services.orchestrator", orchestrator)

    module_name = "tests._netbox_ceph_operation_actions_under_test"
    path = Path(__file__).parents[1] / "netbox_ceph/services/operation_actions.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    module._test_fixed_now = fixed_now
    return module


def _apply_records(actions):
    operation = _record(status="applying")
    plan = _record(
        status="valid",
        backend_plan_id="plan-1",
        backend_plan_digest="1" * 64,
        backend_endpoint_config_revision=ENDPOINT_CONFIG_REVISION,
        expires_at=actions._test_fixed_now + timedelta(minutes=10),
    )
    approval = _record(
        status="applying",
        backend_approval_id="approval-1",
        backend_run_id="",
        backend_endpoint_id=41,
        backend_endpoint_config_revision=ENDPOINT_CONFIG_REVISION,
        requester_username="requester",
        approver_username="approver",
        expires_at=actions._test_fixed_now + timedelta(minutes=5),
    )
    run = _record(
        status="applying",
        backend_run_id="",
        provider_task_ref="",
        outcome_unknown=False,
        finished_at=None,
        result={},
        warnings=[],
        error="",
    )
    return operation, plan, approval, run


def _run_payload(actions, **overrides):
    payload = {
        "id": "run-1",
        "status": "completed",
        "plan_id": "plan-1",
        "plan_digest": "1" * 64,
        "endpoint_id": 41,
        "endpoint_config_revision": ENDPOINT_CONFIG_REVISION,
        "approval_id": "approval-1",
        "requester": "requester",
        "approver": "approver",
        "actor": "requester",
        "provider": "proxmox",
        "provider_task_refs": ["UPID:node:task"],
        "warnings": [],
        "errors": [],
    }
    payload.update(overrides)
    return payload


def _approval_payload(actions, **overrides):
    payload = {
        "id": "approval-1",
        "token": "one-time-canary",
        "plan_id": "plan-1",
        "plan_digest": "1" * 64,
        "endpoint_id": 41,
        "endpoint_config_revision": ENDPOINT_CONFIG_REVISION,
        "requester": "requester",
        "approver": "approver",
        "expires_at": (actions._test_fixed_now + timedelta(minutes=5)).isoformat(),
    }
    payload.update(overrides)
    return payload


def test_operation_payload_never_carries_legacy_confirmation_authority(actions) -> None:
    operation = SimpleNamespace(
        pk=1,
        cluster_id=7,
        provider_id=3,
        provider=SimpleNamespace(kind="proxmox", name="pve"),
        operation_type="delete",
        target_kind="pool",
        target_ref="old",
        execution_node="pve-1",
        desired={},
        is_destructive=True,
        confirmation_required=True,
        confirmed=True,
        source_branch_schema_id="branch-1",
    )

    payload = actions.operation_payload(operation, endpoint_id=41)

    assert "confirmed" not in payload
    assert "confirmed_by" not in payload
    assert payload["is_destructive"] is True
    assert payload["endpoint_id"] == 41


def test_operation_payload_satisfies_real_proxbox_plan_route_contract(
    actions,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the provider-owned #258 schema and route guard when available."""

    source_value = os.environ.get("PROXBOX_API_258_SOURCE")
    if not source_value:
        pytest.skip("set PROXBOX_API_258_SOURCE to the proxbox-api #258 worktree")
    source = Path(source_value).resolve()
    if not (source / "proxbox_api/ceph/v2_routes.py").is_file():
        pytest.fail("PROXBOX_API_258_SOURCE does not contain proxbox-api Ceph v2 routes")
    monkeypatch.syspath_prepend(str(source))
    for name in tuple(sys.modules):
        if name == "proxbox_api" or name.startswith("proxbox_api."):
            monkeypatch.delitem(sys.modules, name, raising=False)

    schemas = importlib.import_module("proxbox_api.ceph.v2_schemas")
    routes = importlib.import_module("proxbox_api.ceph.v2_routes")
    operation = SimpleNamespace(
        pk=1,
        cluster_id=7,
        provider_id=3,
        provider=SimpleNamespace(kind="proxmox", name="pve"),
        operation_type="create",
        target_kind="pool",
        target_ref="rbd",
        execution_node="pve-1",
        desired={"size": 3, "pg_num": 128},
        is_destructive=False,
        confirmation_required=False,
        source_branch_schema_id="branch-1",
    )
    payload = actions._current_plan_payload(operation, 41)
    request = schemas.PlanRequest.model_validate(payload)
    assert request.endpoint_id == 41
    assert request.desired_state.objects[0].node == "pve-1"

    missing_endpoint = schemas.PlanRequest.model_validate({**payload, "endpoint_id": None})
    with pytest.raises(routes.HTTPException) as excinfo:
        asyncio.run(routes._build_and_persist(missing_endpoint, object()))
    assert excinfo.value.status_code == 422
    assert excinfo.value.detail["reason"] == "endpoint_id_required"

    calls: list[object] = []

    class Bound:
        endpoint_config_revision = ENDPOINT_CONFIG_REVISION

        async def aclose(self) -> None:
            calls.append("closed")

    async def exact_adapter(session, endpoint_id):
        calls.append((session, endpoint_id))
        return object(), Bound()

    async def build_plan(request_value, adapter, *, endpoint_config_revision):
        calls.append((request_value.endpoint_id, adapter, endpoint_config_revision))
        return "provider-owned-plan"

    async def persist_plan(session, plan):
        calls.append((session, plan))
        return plan

    monkeypatch.setattr(routes, "_exact_proxmox_adapter", exact_adapter)
    monkeypatch.setattr(routes, "build_plan", build_plan)
    monkeypatch.setattr(routes, "persist_plan", persist_plan)
    session = object()
    assert asyncio.run(routes._build_and_persist(request, session)) == "provider-owned-plan"
    assert calls[0] == (session, 41)
    assert calls[-1] == "closed"


def test_request_digest_is_canonical_and_changes_with_endpoint(actions) -> None:
    left = actions.request_digest({"b": 2, "a": 1, "endpoint_id": 41})
    reordered = actions.request_digest({"endpoint_id": 41, "a": 1, "b": 2})
    changed = actions.request_digest({"endpoint_id": 42, "a": 1, "b": 2})

    assert left == reordered
    assert left != changed


def test_timeout_retry_reuses_token_then_replay_recovers_existing_run(actions) -> None:
    operation, plan, approval, run = _apply_records(actions)
    calls = []

    class Orchestrator:
        def apply(self, plan_id, **kwargs):
            calls.append((plan_id, kwargs))
            if len(calls) == 1:
                raise actions.CephOrchestratorTimeout("timeout")
            raise actions.CephOrchestratorHTTPError(
                409,
                "approval_replayed",
                "replayed",
                {"operation_run_id": "run-1"},
            )

        def operation(self, operation_id):
            assert operation_id == "run-1"
            return _run_payload(actions)

    result = actions._dispatch_approved_plan(
        Orchestrator(),
        operation=operation,
        plan=plan,
        approval=approval,
        run=run,
        backend_endpoint_id=41,
        token="one-time-canary",
        requester_name="requester",
    )

    assert result.status == "succeeded"
    assert len(calls) == 2
    assert calls[0][1]["approval_token"] == calls[1][1]["approval_token"]
    assert approval.backend_run_id == "run-1"
    assert approval.status == "consumed"
    assert "one-time-canary" not in repr(operation.__dict__)
    assert "one-time-canary" not in repr(approval.__dict__)
    assert "one-time-canary" not in repr(run.__dict__)


def test_persisted_approval_and_run_never_receive_the_raw_token(actions) -> None:
    operation = _record(
        pk=1,
        provider=SimpleNamespace(pk=3),
        source_branch_schema_id="branch-1",
        status="planned",
    )
    actions.CephOperation.objects.add(operation)
    plan = _record(
        backend_plan_id="plan-1",
        backend_plan_digest="1" * 64,
        backend_endpoint_config_revision=ENDPOINT_CONFIG_REVISION,
    )
    requester = SimpleNamespace(pk=1, is_authenticated=True, username="requester")
    approver = SimpleNamespace(pk=2, is_authenticated=True, username="approver")
    approval = actions.CephOperationApproval.objects.create(
        status="issuing",
        backend_approval_id="",
        backend_endpoint_config_revision=ENDPOINT_CONFIG_REVISION,
    )
    payload = _approval_payload(actions)

    approval, run = actions._persist_approval_and_run(
        operation=operation,
        plan=plan,
        backend_endpoint_id=41,
        requester=requester,
        approver=approver,
        approval=approval,
        approval_payload=payload,
        approval_id="approval-1",
    )

    run_kwargs = actions.CephOperationRun.objects.created[-1]
    assert "token" not in run_kwargs
    assert run_kwargs["backend_endpoint_config_revision"] == ENDPOINT_CONFIG_REVISION
    assert "one-time-canary" not in repr(approval.__dict__)
    assert "one-time-canary" not in repr(run.__dict__)


def test_two_transport_failures_become_outcome_unknown_without_third_dispatch(actions) -> None:
    operation, plan, approval, run = _apply_records(actions)
    calls = []

    class Orchestrator:
        def apply(self, plan_id, **kwargs):
            calls.append((plan_id, kwargs))
            raise actions.CephOrchestratorTimeout("timeout")

        def approval_status(self, approval_id):
            raise actions.CephOrchestratorUnavailable("offline")

    with pytest.raises(actions.OperationActionError) as excinfo:
        actions._dispatch_approved_plan(
            Orchestrator(),
            operation=operation,
            plan=plan,
            approval=approval,
            run=run,
            backend_endpoint_id=41,
            token="one-time-canary",
            requester_name="requester",
        )

    assert excinfo.value.kind == "unavailable"
    assert len(calls) == 2
    assert run.status == "outcome_unknown"
    assert run.outcome_unknown is True
    assert operation.status == "outcome_unknown"
    assert approval.status == "outcome_unknown"


def test_apply_response_without_run_id_is_persisted_as_outcome_unknown(actions) -> None:
    operation, plan, approval, run = _apply_records(actions)

    with pytest.raises(actions.OperationActionError) as excinfo:
        actions._record_run_response(
            run,
            operation,
            approval,
            _run_payload(actions, id="", status="running"),
            plan=plan,
        )

    assert excinfo.value.reason == "invalid_run_contract"
    assert run.status == "outcome_unknown"
    assert operation.status == "outcome_unknown"
    assert approval.status == "outcome_unknown"


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ({"token": ""}, "invalid_approval_contract"),
        ({"plan_id": "wrong-plan"}, "approval_binding_mismatch"),
    ],
)
def test_invalid_approval_response_blocks_reissue_without_persisting_token(
    actions, mutation, reason
) -> None:
    operation = _record(status="planned")
    plan = _record(
        backend_plan_id="plan-1",
        backend_plan_digest="1" * 64,
        backend_endpoint_config_revision=ENDPOINT_CONFIG_REVISION,
        expires_at=actions._test_fixed_now + timedelta(minutes=10),
    )
    approval = _record(status="issuing", backend_approval_id="")
    requester = SimpleNamespace(pk=1)
    approver = SimpleNamespace(pk=2)
    response = _approval_payload(actions, **mutation)

    class Orchestrator:
        def approve(self, *args, **kwargs):
            return response

    with pytest.raises(actions.OperationActionError) as excinfo:
        actions._issue_backend_approval(
            Orchestrator(),
            approval=approval,
            operation=operation,
            plan=plan,
            backend_endpoint_id=41,
            requester=requester,
            requester_name="requester",
            approver=approver,
            approver_name="approver",
        )

    assert excinfo.value.reason == reason
    assert approval.status == "outcome_unknown"
    assert approval.failure_code == reason
    assert "one-time-canary" not in repr(approval.__dict__)
    assert operation.status == "outcome_unknown"


def test_unusable_post_approval_response_is_ambiguous_not_a_known_failure(actions) -> None:
    operation = _record(status="applying")
    plan = _record(
        backend_plan_id="plan-1",
        backend_plan_digest="1" * 64,
        backend_endpoint_config_revision=ENDPOINT_CONFIG_REVISION,
        expires_at=actions._test_fixed_now + timedelta(minutes=10),
    )
    approval = _record(status="issuing", backend_approval_id="")

    class Orchestrator:
        def approve(self, *args, **kwargs):
            raise actions.CephBackendError("malformed success response")

    with pytest.raises(actions.OperationActionError):
        actions._issue_backend_approval(
            Orchestrator(),
            approval=approval,
            operation=operation,
            plan=plan,
            backend_endpoint_id=41,
            requester=SimpleNamespace(pk=1),
            requester_name="requester",
            approver=SimpleNamespace(pk=2),
            approver_name="approver",
        )

    assert approval.status == "outcome_unknown"
    assert approval.failure_code == "approval_transport_outcome_unknown"
    assert operation.status == "outcome_unknown"


def test_approval_connection_failure_is_persisted_as_outcome_unknown(actions) -> None:
    operation = _record(status="planned")
    plan = _record(
        backend_plan_id="plan-1",
        backend_plan_digest="1" * 64,
        backend_endpoint_config_revision=ENDPOINT_CONFIG_REVISION,
        expires_at=actions._test_fixed_now + timedelta(minutes=10),
    )
    approval = _record(status="issuing", backend_approval_id="")

    class Orchestrator:
        def approve(self, *args, **kwargs):
            raise actions.CephOrchestratorUnavailable("password=APPROVAL-CANARY")

    with pytest.raises(actions.OperationActionError) as excinfo:
        actions._issue_backend_approval(
            Orchestrator(),
            approval=approval,
            operation=operation,
            plan=plan,
            backend_endpoint_id=41,
            requester=SimpleNamespace(pk=1),
            requester_name="requester",
            approver=SimpleNamespace(pk=2),
            approver_name="approver",
        )

    assert excinfo.value.reason == "backend_unavailable"
    assert "APPROVAL-CANARY" not in str(excinfo.value)
    assert approval.status == "outcome_unknown"
    assert operation.status == "outcome_unknown"


def test_ambiguous_http_apply_retries_once_then_recovers_by_approval(actions) -> None:
    operation, plan, approval, run = _apply_records(actions)
    calls = []

    class Orchestrator:
        def apply(self, *args, **kwargs):
            calls.append(kwargs)
            raise actions.CephOrchestratorHTTPError(503, "upstream_unavailable", "safe")

        def approval_status(self, approval_id):
            assert approval_id == "approval-1"
            return {
                **_approval_payload(actions),
                "operation_run_id": "run-1",
            }

        def operation(self, operation_id):
            assert operation_id == "run-1"
            return _run_payload(actions)

    recovered = actions._dispatch_approved_plan(
        Orchestrator(),
        operation=operation,
        plan=plan,
        approval=approval,
        run=run,
        backend_endpoint_id=41,
        token="one-time-canary",
        requester_name="requester",
    )

    assert len(calls) == 2
    assert recovered.backend_run_id == "run-1"
    assert recovered.status == "succeeded"


def test_invalid_or_blocked_plan_cannot_be_approved(actions) -> None:
    invalid_plan = _record(status="invalid")

    class Plans:
        def order_by(self, *args):
            return self

        def first(self):
            return invalid_plan

    operation = _record(status="planned", plans=Plans())

    with pytest.raises(actions.OperationActionError) as excinfo:
        actions._approvable_plan(operation)

    assert excinfo.value.reason == "plan_not_valid"


def test_plan_expiry_stales_authority_before_approval(actions) -> None:
    operation = _record(status="planned")
    operation_payload = {
        "id": 1,
        "cluster_id": 7,
        "provider_id": 3,
        "provider_kind": "proxmox",
        "provider_name": "pve",
        "operation_type": "delete",
        "target_kind": "pool",
        "target_ref": "old",
        "execution_node": "pve-1",
        "desired": {},
        "desired_state": {
            "objects": [
                {
                    "kind": "pool",
                    "target_ref": "old",
                    "action": "delete",
                    "provider": "proxmox",
                    "node": "pve-1",
                    "payload": {},
                }
            ]
        },
        "is_destructive": True,
        "confirmation_required": True,
        "source_branch_schema_id": "",
        "provider": "proxmox",
        "endpoint_id": 41,
    }
    for key, value in {
        "pk": 1,
        "cluster_id": 7,
        "provider_id": 3,
        "provider": SimpleNamespace(kind="proxmox", name="pve"),
        "operation_type": "delete",
        "target_kind": "pool",
        "target_ref": "old",
        "execution_node": "pve-1",
        "desired": {},
        "is_destructive": True,
        "confirmation_required": True,
        "source_branch_schema_id": "",
    }.items():
        setattr(operation, key, value)
    plan = _record(
        status="valid",
        expires_at=actions._test_fixed_now - timedelta(seconds=1),
        backend_endpoint_id=41,
        request_digest=actions.request_digest(operation_payload),
        backend_plan_id="plan-1",
        backend_plan_digest="digest-1",
        backend_endpoint_config_revision=ENDPOINT_CONFIG_REVISION,
    )

    with pytest.raises(actions.OperationActionError) as excinfo:
        actions._validate_plan_is_current(operation, plan, endpoint_id=41)

    assert excinfo.value.reason == "plan_expired"
    assert plan.status == "stale"
    assert operation.status == "pending"


@pytest.mark.parametrize(
    ("provider", "reason"),
    [
        (None, "provider_required"),
        (
            SimpleNamespace(cluster_id=8, enabled=True, kind="proxmox"),
            "provider_cluster_mismatch",
        ),
        (
            SimpleNamespace(cluster_id=7, enabled=False, kind="proxmox"),
            "provider_disabled",
        ),
        (
            SimpleNamespace(cluster_id=7, enabled=True, kind="ceph_dashboard"),
            "provider_write_contract_unsupported",
        ),
    ],
)
def test_write_provider_contract_fails_closed(actions, provider, reason) -> None:
    operation = SimpleNamespace(provider=provider, cluster_id=7)

    with pytest.raises(actions.OperationActionError) as excinfo:
        actions._validate_operation_provider(operation)

    assert excinfo.value.reason == reason


def test_local_configuration_digest_covers_routing_credentials_and_capabilities(actions) -> None:
    endpoint = SimpleNamespace(
        pk=41,
        backend_key="endpoint-41",
        name="pve",
        ip_address_id=9,
        domain="pve.example.test",
        port=8006,
        mode="cluster",
        environment="staging",
        username="root@pam",
        password_enc="cipher-a",
        token_name="ceph",
        token_value_enc="token-a",
        pushed_credential_fingerprint="a" * 64,
        verify_ssl=True,
        allow_writes=False,
        access_methods="api",
        timeout=30,
        max_retries=2,
        retry_backoff="0.50",
        enabled=True,
    )
    cluster = SimpleNamespace(pk=7, endpoint=endpoint)
    provider = SimpleNamespace(
        pk=3,
        cluster_id=7,
        kind="proxmox",
        name="pve",
        enabled=True,
        base_url="",
        verify_ssl=True,
        credential_ref="vault://ceph",
        capabilities={"plan": True, "apply": True},
    )

    baseline = actions._local_config_digest(cluster=cluster, provider=provider)
    provider.capabilities = {"apply": True, "plan": True}
    assert actions._local_config_digest(cluster=cluster, provider=provider) == baseline

    endpoint.allow_writes = True
    assert actions._local_config_digest(cluster=cluster, provider=provider) != baseline
    endpoint.allow_writes = False
    endpoint.password_enc = "cipher-b"
    assert actions._local_config_digest(cluster=cluster, provider=provider) != baseline
    endpoint.password_enc = "cipher-a"
    provider.capabilities = {"plan": True, "apply": False}
    assert actions._local_config_digest(cluster=cluster, provider=provider) != baseline


def test_plan_response_requires_canonical_endpoint_configuration_revision(actions) -> None:
    valid = {
        "id": "plan-1",
        "provider": "proxmox",
        "endpoint_id": 41,
        "endpoint_config_revision": ENDPOINT_CONFIG_REVISION,
        "requester": "requester",
        "digest": "1" * 64,
        "expires_at": (actions._test_fixed_now + timedelta(minutes=10)).isoformat(),
    }

    actions._validate_plan_response(valid, endpoint_id=41, requester_name="requester")

    for bad_revision in (None, "", "e" * 63, "G" * 64):
        with pytest.raises(actions.OperationActionError) as excinfo:
            actions._validate_plan_response(
                {**valid, "endpoint_config_revision": bad_revision},
                endpoint_id=41,
                requester_name="requester",
            )
        assert excinfo.value.reason == "invalid_endpoint_config_revision"


def test_plan_response_enforces_exact_proxbox_writer_operation_contract(actions) -> None:
    operation = _record(
        operation_type="create",
        target_kind="pool",
        target_ref="rbd",
        execution_node="pve-a",
    )

    def response(**operation_overrides: object) -> dict[str, object]:
        planned = {
            "provider": "proxmox",
            "kind": "pool",
            "target_ref": "rbd",
            "action": "create",
            "node": "pve-a",
            "supported": True,
            "after_summary": {"size": 3, "pg_num": 128},
        }
        planned.update(operation_overrides)
        return {
            "id": "plan-1",
            "provider": "proxmox",
            "endpoint_id": 41,
            "endpoint_config_revision": ENDPOINT_CONFIG_REVISION,
            "requester": "requester",
            "digest": "1" * 64,
            "expires_at": (actions._test_fixed_now + timedelta(minutes=10)).isoformat(),
            "operations": [planned],
            "blocked_actions": [],
            "validations": [],
        }

    actions._validate_plan_response(
        response(),
        endpoint_id=41,
        requester_name="requester",
        operation=operation,
        local_binding={"execution_node": "pve-a"},
    )

    rejected = (
        ({"node": "pve-b"}, "plan_operation_binding_mismatch"),
        ({"supported": False}, "plan_operation_unsupported"),
        ({"blocked_reason": "writer disabled"}, "plan_operation_unsupported"),
        ({"action": "update"}, "plan_action_mismatch"),
        ({"after_summary": {"compression": "zstd"}}, "plan_payload_contract_mismatch"),
        ({"after_summary": {"size": True}}, "plan_payload_contract_mismatch"),
        ({"after_summary": {"pg_num": 0}}, "plan_payload_contract_mismatch"),
        ({"after_summary": {"target_size_ratio": "0.25"}}, "plan_payload_contract_mismatch"),
        ({"unexpected": True}, "invalid_plan_operations"),
    )
    for overrides, reason in rejected:
        with pytest.raises(actions.OperationActionError) as excinfo:
            actions._validate_plan_response(
                response(**overrides),
                endpoint_id=41,
                requester_name="requester",
                operation=operation,
                local_binding={"execution_node": "pve-a"},
            )
        assert excinfo.value.reason == reason

    blocked = response()
    blocked["blocked_actions"] = [blocked["operations"][0]]
    with pytest.raises(actions.OperationActionError) as excinfo:
        actions._validate_plan_response(
            blocked,
            endpoint_id=41,
            requester_name="requester",
            operation=operation,
            local_binding={"execution_node": "pve-a"},
        )
    assert excinfo.value.reason == "plan_blocked"

    malformed = response()
    malformed["validations"] = {"severity": "error"}
    with pytest.raises(actions.OperationActionError) as excinfo:
        actions._validate_plan_response(
            malformed,
            endpoint_id=41,
            requester_name="requester",
            operation=operation,
            local_binding={"execution_node": "pve-a"},
        )
    assert excinfo.value.reason == "invalid_plan_contract"

    operation.operation_type = "reconcile"
    with pytest.raises(actions.OperationActionError) as excinfo:
        actions._validate_plan_response(
            response(action="delete", is_destructive=True, after_summary={}),
            endpoint_id=41,
            requester_name="requester",
            operation=operation,
            local_binding={"execution_node": "pve-a"},
        )
    assert excinfo.value.reason == "plan_action_mismatch"


def test_local_plan_without_endpoint_revision_is_retired(actions, monkeypatch) -> None:
    operation = _record(status="planned")
    plan = _record(
        status="valid",
        expires_at=actions._test_fixed_now + timedelta(minutes=10),
        backend_endpoint_id=41,
        request_digest=actions.request_digest({"canonical": True}),
        backend_plan_id="plan-1",
        backend_plan_digest="1" * 64,
        backend_endpoint_config_revision="",
    )
    monkeypatch.setattr(
        actions,
        "_current_plan_payload",
        lambda operation, endpoint_id: {"canonical": True},
    )

    with pytest.raises(actions.OperationActionError) as excinfo:
        actions._validate_plan_is_current(operation, plan, endpoint_id=41)

    assert excinfo.value.reason == "legacy_plan_has_no_endpoint_revision"
    assert plan.status == "stale"
    assert operation.status == "pending"


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("id", "other-approval"),
        ("plan_id", "other-plan"),
        ("plan_digest", "2" * 64),
        ("endpoint_id", True),
        ("endpoint_id", 42),
        ("endpoint_config_revision", "f" * 64),
        ("requester", "other-requester"),
        ("approver", "other-approver"),
        ("expires_at", "2026-07-22T00:11:00+00:00"),
    ],
)
def test_approval_status_recovery_rejects_every_binding_tamper(actions, field, bad_value) -> None:
    _, plan, approval, _ = _apply_records(actions)
    payload = _approval_payload(actions, **{field: bad_value})

    with pytest.raises(actions.OperationActionError) as excinfo:
        actions._validate_approval_status_binding(payload, approval=approval, plan=plan)

    assert excinfo.value.reason == "approval_status_binding_mismatch"


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("id", "other-run"),
        ("plan_id", "other-plan"),
        ("plan_digest", "2" * 64),
        ("endpoint_id", True),
        ("endpoint_id", 42),
        ("endpoint_config_revision", "f" * 64),
        ("approval_id", "other-approval"),
        ("requester", "other-requester"),
        ("approver", "other-approver"),
        ("actor", "other-actor"),
        ("provider", "ceph_dashboard"),
    ],
)
def test_run_recovery_rejects_every_binding_tamper(actions, field, bad_value) -> None:
    _, plan, approval, _ = _apply_records(actions)
    approval.backend_run_id = "run-1"
    payload = _run_payload(actions, **{field: bad_value})

    with pytest.raises(actions.OperationActionError) as excinfo:
        actions._validate_run_binding(payload, approval=approval, plan=plan)

    assert excinfo.value.reason == "run_binding_mismatch"


@pytest.mark.parametrize(
    "mutation",
    [
        {"id": "../approval"},
        {"token": "x" * 4097},
        {"expires_at": "not-a-date"},
        {"expires_at": "2026-07-21T23:59:59+00:00"},
        {"expires_at": "2026-07-22T00:11:00+00:00"},
    ],
)
def test_approval_issuance_rejects_unsafe_id_token_or_expiry(actions, mutation) -> None:
    operation = _record(status="applying")
    plan = _record(
        backend_plan_id="plan-1",
        backend_plan_digest="1" * 64,
        backend_endpoint_config_revision=ENDPOINT_CONFIG_REVISION,
        expires_at=actions._test_fixed_now + timedelta(minutes=10),
    )
    approval = _record(status="issuing", backend_approval_id="")
    response = _approval_payload(actions, **mutation)

    class Orchestrator:
        def approve(self, *args, **kwargs):
            return response

    with pytest.raises(actions.OperationActionError) as excinfo:
        actions._issue_backend_approval(
            Orchestrator(),
            approval=approval,
            operation=operation,
            plan=plan,
            backend_endpoint_id=41,
            requester=SimpleNamespace(pk=1),
            requester_name="requester",
            approver=SimpleNamespace(pk=2),
            approver_name="approver",
        )

    assert excinfo.value.reason == "invalid_approval_contract"
    assert approval.status == "outcome_unknown"
    assert operation.status == "outcome_unknown"
    assert "one-time-canary" not in repr(approval.__dict__)


def test_expired_issuance_owner_can_record_outcome_until_takeover(actions) -> None:
    owner = uuid.uuid4()
    approval = _record(
        status="issuing",
        backend_approval_id="",
        failure_code="",
        failure_detail="",
        issuance_reservation_id=owner,
        issuance_reservation_expires_at=actions._test_fixed_now - timedelta(seconds=1),
    )
    operation = _record(status="applying")

    actions._transition_approval_issuance(
        approval=approval,
        operation=operation,
        issuance_reservation_id=owner,
        approval_status="outcome_unknown",
        operation_status="outcome_unknown",
        failure_code="approval_transport_outcome_unknown",
        failure_detail="quarantined",
        backend_approval_id="approval-1",
    )

    assert approval.status == "outcome_unknown"
    assert approval.backend_approval_id == "approval-1"
    assert approval.issuance_reservation_id is None
    assert operation.status == "outcome_unknown"


def test_approve_flow_reserves_durable_intent_before_backend_post(
    actions, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []
    operation = SimpleNamespace(status="planned")
    plan = SimpleNamespace()
    approval = SimpleNamespace(
        status="issuing",
        backend_approval_id="",
        backend_endpoint_id=41,
        approver_username="approver",
    )
    run = SimpleNamespace()
    requester = SimpleNamespace()
    approver = SimpleNamespace()

    class Orchestrator:
        def resolve_backend_endpoint_id(self, endpoint):
            calls.append("resolve")
            return 41

    operation.cluster = SimpleNamespace(endpoint=object())
    monkeypatch.setattr(actions, "CephOrchestratorClient", Orchestrator)
    monkeypatch.setattr(
        actions,
        "_approval_actors",
        lambda *args, **kwargs: (requester, "requester", "approver"),
    )
    monkeypatch.setattr(actions, "_validate_operation_provider", lambda value: None)

    def reserve(*args, **kwargs):
        calls.append("reserve")
        return operation, plan, approval, True

    def issue(*args, **kwargs):
        calls.append("approve-post")
        return _approval_payload(actions), "one-time-canary", "approval-1"

    monkeypatch.setattr(actions, "_reserve_approval_intent", reserve)
    monkeypatch.setattr(actions, "_issue_backend_approval", issue)
    monkeypatch.setattr(
        actions,
        "_persist_approval_and_run",
        lambda **kwargs: (approval, run),
    )
    monkeypatch.setattr(actions, "_dispatch_approved_plan", lambda *args, **kwargs: run)

    assert actions.approve_and_apply_operation(operation, approver=approver) is run
    assert calls == ["resolve", "reserve", "approve-post"]


def test_post_issuance_persistence_fault_quarantines_authority(
    actions, monkeypatch: pytest.MonkeyPatch
) -> None:
    operation = SimpleNamespace(
        status="planned",
        cluster=SimpleNamespace(endpoint=object()),
    )
    plan = SimpleNamespace()
    approval = SimpleNamespace(
        status="issuing",
        backend_approval_id="",
        backend_endpoint_id=41,
        approver_username="approver",
    )
    requester = SimpleNamespace()
    approver = SimpleNamespace()
    transitions = []

    class Orchestrator:
        def resolve_backend_endpoint_id(self, endpoint):
            return 41

    monkeypatch.setattr(actions, "CephOrchestratorClient", Orchestrator)
    monkeypatch.setattr(
        actions,
        "_approval_actors",
        lambda *args, **kwargs: (requester, "requester", "approver"),
    )
    monkeypatch.setattr(actions, "_validate_operation_provider", lambda value: None)
    monkeypatch.setattr(
        actions,
        "_reserve_approval_intent",
        lambda *args, **kwargs: (operation, plan, approval, True),
    )
    monkeypatch.setattr(
        actions,
        "_issue_backend_approval",
        lambda *args, **kwargs: (
            _approval_payload(actions),
            "one-time-canary",
            "approval-1",
        ),
    )
    monkeypatch.setattr(
        actions,
        "_persist_approval_and_run",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("database fault")),
    )
    monkeypatch.setattr(
        actions,
        "_transition_approval_issuance",
        lambda **kwargs: transitions.append(kwargs),
    )

    with pytest.raises(RuntimeError, match="database fault"):
        actions.approve_and_apply_operation(operation, approver=approver)

    assert len(transitions) == 1
    assert transitions[0]["approval_status"] == "outcome_unknown"
    assert transitions[0]["operation_status"] == "outcome_unknown"
    assert transitions[0]["failure_code"] == "approval_persistence_failed"
    assert transitions[0]["backend_approval_id"] == "approval-1"


def test_existing_applying_authority_recovers_without_new_approval_post(
    actions, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []
    operation = SimpleNamespace(
        status="applying",
        cluster=SimpleNamespace(endpoint=object()),
    )
    plan = SimpleNamespace()
    approval = SimpleNamespace(
        status="applying",
        backend_approval_id="approval-1",
        backend_endpoint_id=41,
        approver_username="approver",
    )
    recovered_run = SimpleNamespace()
    requester = SimpleNamespace()
    approver = SimpleNamespace()

    class Orchestrator:
        def resolve_backend_endpoint_id(self, endpoint):
            return 41

    monkeypatch.setattr(actions, "CephOrchestratorClient", Orchestrator)
    monkeypatch.setattr(
        actions,
        "_approval_actors",
        lambda *args, **kwargs: (requester, "requester", "approver"),
    )
    monkeypatch.setattr(actions, "_validate_operation_provider", lambda value: None)
    monkeypatch.setattr(
        actions,
        "_reserve_approval_intent",
        lambda *args, **kwargs: (operation, plan, approval, None),
    )
    monkeypatch.setattr(
        actions,
        "_issue_backend_approval",
        lambda *args, **kwargs: calls.append("approve-post"),
    )

    def recover(*args, **kwargs):
        calls.append("recover")
        return recovered_run

    monkeypatch.setattr(actions, "_recover_existing_approval", recover)

    assert actions.approve_and_apply_operation(operation, approver=approver) is recovered_run
    assert calls == ["recover"]


def _planning_operation(actions, *, expires_at):
    requester = SimpleNamespace(
        pk=1,
        is_authenticated=True,
        username="requester",
        has_perm=lambda permission, obj: True,
    )
    endpoint = SimpleNamespace(
        pk=11,
        name="pve",
        domain="pve.invalid",
        port=8006,
        verify_ssl=True,
        enabled=True,
    )
    cluster = SimpleNamespace(pk=7, endpoint_id=11, endpoint=endpoint)
    provider = SimpleNamespace(
        pk=3,
        cluster_id=7,
        enabled=True,
        kind="proxmox",
        name="pve",
        base_url="",
        verify_ssl=True,
        credential_ref="vault:pve",
    )
    operation = _record(
        pk=1,
        status="planning",
        provider=provider,
        provider_id=3,
        cluster=cluster,
        cluster_id=7,
        target_kind="pool",
        target_ref="pool-1",
        execution_node="pve-1",
        desired={},
        requested_by=requester,
        requested_by_id=requester.pk,
        requested_by_username="requester",
        approvals=_Relation(),
        runs=_Relation(),
        planning_reservation_id=uuid.UUID("cf75a2b5-e394-46c6-af55-b97cae765178"),
        planning_reservation_expires_at=expires_at,
        last_updated=actions._test_fixed_now - timedelta(minutes=11),
        confirmed=True,
    )
    actions.CephOperation.objects.add(operation)
    return operation, requester


def test_live_planning_lease_blocks_parallel_backend_plan(actions) -> None:
    operation, requester = _planning_operation(
        actions,
        expires_at=actions._test_fixed_now + timedelta(seconds=1),
    )

    with pytest.raises(actions.OperationActionError) as excinfo:
        actions._reserve_plan_operation(operation, requested_by=requester)

    assert excinfo.value.reason == "operation_authority_in_flight"


def test_expired_planning_lease_gets_new_nonce(actions) -> None:
    operation, requester = _planning_operation(
        actions,
        expires_at=actions._test_fixed_now - timedelta(seconds=1),
    )
    old_reservation_id = operation.planning_reservation_id

    reserved = actions._reserve_plan_operation(operation, requested_by=requester)

    assert reserved.status == "planning"
    assert reserved.planning_reservation_id != old_reservation_id
    assert reserved.planning_reservation_expires_at == actions._test_fixed_now + timedelta(
        minutes=10
    )


def test_late_planning_failure_cannot_overwrite_newer_reservation(actions) -> None:
    operation, _ = _planning_operation(
        actions,
        expires_at=actions._test_fixed_now + timedelta(minutes=10),
    )
    stale_reservation_id = uuid.UUID("8d214f39-a51c-466b-8b6f-ab95f253b8e7")

    actions._finish_planning_failure(operation.pk, stale_reservation_id, "failed")

    assert operation.status == "planning"
    assert operation.planning_reservation_id != stale_reservation_id
