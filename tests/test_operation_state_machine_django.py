"""PostgreSQL-backed authority, permission, and audit-chain integration tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event

import pytest

pytest.importorskip("netbox")

from django.conf import settings  # noqa: E402

if not settings.configured:
    pytest.skip("Django settings are not configured", allow_module_level=True)

import django  # noqa: E402

django.setup()

from django.contrib.contenttypes.models import ContentType  # noqa: E402
from django.db import IntegrityError, close_old_connections, transaction  # noqa: E402
from django.db.models.deletion import ProtectedError  # noqa: E402
from django.utils import timezone  # noqa: E402
from netbox_proxbox.models import ProxmoxEndpoint  # noqa: E402
from users.models import ObjectPermission, User  # noqa: E402

from netbox_ceph.api.serializers import CephOperationSerializer  # noqa: E402
from netbox_ceph.api.views import CephOperationActionPermissions  # noqa: E402
from netbox_ceph.choices import (  # noqa: E402
    CephApprovalStatusChoices,
    CephOperationStatusChoices,
    CephPlanStatusChoices,
    CephProviderKindChoices,
)
from netbox_ceph.models import (  # noqa: E402
    CephCluster,
    CephOperation,
    CephOperationApproval,
    CephOperationRun,
    CephPlan,
    CephProvider,
)
from netbox_ceph.services import operation_actions  # noqa: E402

pytestmark = pytest.mark.django_db(transaction=True)
ENDPOINT_CONFIG_REVISION = "e" * 64


def _actors() -> tuple[User, User]:
    requester = User.objects.create_user(username="ceph-requester")
    approver = User.objects.create_user(username="ceph-approver")
    operation_type = ContentType.objects.get_for_model(CephOperation)
    requester_permission = ObjectPermission.objects.create(
        name="Ceph requester test permission",
        actions=["request", "apply"],
        constraints=None,
    )
    requester_permission.object_types.add(operation_type)
    requester.object_permissions.add(requester_permission)
    approver_permission = ObjectPermission.objects.create(
        name="Ceph approver test permission",
        actions=["approve"],
        constraints=None,
    )
    approver_permission.object_types.add(operation_type)
    approver.object_permissions.add(approver_permission)
    return requester, approver


def _operation(requester: User, *, status: str = "pending") -> CephOperation:
    endpoint = ProxmoxEndpoint.objects.create(
        name="ceph-authority-test",
        domain="ceph-authority.invalid",
        port=8006,
        verify_ssl=False,
    )
    cluster = CephCluster.objects.create(endpoint=endpoint, name="ceph-test")
    provider = CephProvider.objects.create(
        cluster=cluster,
        kind=CephProviderKindChoices.KIND_PROXMOX,
        name="proxmox",
        enabled=True,
    )
    return CephOperation.objects.create(
        cluster=cluster,
        provider=provider,
        operation_type="delete",
        target_kind="pool",
        target_ref="old-pool",
        execution_node="pve-a",
        desired={},
        status=status,
        is_destructive=True,
        confirmation_required=True,
        requested_by=requester,
        requested_by_username=requester.get_username(),
    )


def _plan(operation: CephOperation, *, endpoint_id: int = 41) -> CephPlan:
    binding = operation_actions._binding_snapshot(operation)
    return CephPlan.objects.create(
        operation=operation,
        status=CephPlanStatusChoices.STATUS_VALID,
        backend_plan_id="plan-1",
        backend_plan_digest="1" * 64,
        backend_endpoint_id=endpoint_id,
        backend_endpoint_config_revision=ENDPOINT_CONFIG_REVISION,
        **binding,
        requester=operation.requested_by,
        requester_username=operation.requested_by_username,
        generated_at=timezone.now(),
        expires_at=timezone.now() + timedelta(minutes=30),
        request_digest=operation_actions.request_digest(
            operation_actions._current_plan_payload(operation, endpoint_id)
        ),
    )


def test_custom_api_roles_match_requester_and_approver_authority() -> None:
    requester, approver = _actors()
    operation = _operation(requester)
    permission = CephOperationActionPermissions()

    requester_request = type(
        "Request",
        (),
        {"user": requester, "auth": None, "method": "POST"},
    )()
    approver_request = type(
        "Request",
        (),
        {"user": approver, "auth": None, "method": "POST"},
    )()

    create_view = type("View", (), {"action": "create"})()
    approve_view = type("View", (), {"action": "approve_and_apply"})()
    assert permission.has_permission(requester_request, create_view) is True
    assert permission.has_permission(approver_request, create_view) is False
    assert permission.has_permission(approver_request, approve_view) is True
    assert permission.has_permission(requester_request, approve_view) is False
    assert permission.has_object_permission(approver_request, approve_view, operation) is True


def test_planning_lease_supports_takeover_and_rejects_late_owner() -> None:
    requester, _ = _actors()
    operation = _operation(requester)

    first = operation_actions._reserve_plan_operation(operation, requested_by=requester)
    first_id = first.planning_reservation_id
    assert first_id is not None
    CephOperation.objects.filter(pk=operation.pk).update(
        planning_reservation_expires_at=timezone.now() - timedelta(seconds=1)
    )

    second = operation_actions._reserve_plan_operation(operation, requested_by=requester)
    second_id = second.planning_reservation_id
    assert second_id is not None and second_id != first_id

    operation_actions._finish_planning_failure(
        operation.pk,
        first_id,
        CephOperationStatusChoices.STATUS_FAILED,
    )
    operation.refresh_from_db()
    assert operation.status == CephOperationStatusChoices.STATUS_PLANNING
    assert operation.planning_reservation_id == second_id


def test_concurrent_approval_reservation_creates_exactly_one_authority() -> None:
    requester, approver = _actors()
    operation = _operation(requester, status=CephOperationStatusChoices.STATUS_PLANNED)
    _plan(operation)
    barrier = Barrier(2)

    def reserve() -> bool:
        close_old_connections()
        try:
            local_operation = CephOperation.objects.get(pk=operation.pk)
            local_requester = User.objects.get(pk=requester.pk)
            local_approver = User.objects.get(pk=approver.pk)
            barrier.wait(timeout=10)
            _operation_row, _plan_row, _approval, issuance_owner = (
                operation_actions._reserve_approval_intent(
                    local_operation,
                    endpoint_id=41,
                    requester=local_requester,
                    requester_name=local_requester.get_username(),
                    approver=local_approver,
                    approver_name=local_approver.get_username(),
                )
            )
            return issuance_owner is not None
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: reserve(), range(2)))

    assert sorted(results) == [False, True]
    approval = CephOperationApproval.objects.get(operation=operation)
    assert approval.status == CephApprovalStatusChoices.STATUS_ISSUING
    assert approval.backend_approval_id == ""
    assert approval.issuance_reservation_id is not None
    assert approval.requester_username == requester.get_username()
    assert approval.approver_username == approver.get_username()


def test_audit_chain_is_protected_and_actor_snapshots_survive_user_deletion() -> None:
    requester, approver = _actors()
    operation = _operation(requester, status=CephOperationStatusChoices.STATUS_APPLYING)
    plan = _plan(operation)
    approval = CephOperationApproval.objects.create(
        operation=operation,
        plan=plan,
        backend_plan_id=plan.backend_plan_id,
        backend_plan_digest=plan.backend_plan_digest,
        backend_endpoint_id=41,
        backend_endpoint_config_revision=ENDPOINT_CONFIG_REVISION,
        plugin_endpoint_id=plan.plugin_endpoint_id,
        provider_id_snapshot=plan.provider_id_snapshot,
        provider_kind_snapshot=plan.provider_kind_snapshot,
        execution_node=plan.execution_node,
        local_config_digest=plan.local_config_digest,
        requester=requester,
        requester_username=requester.get_username(),
        approver=approver,
        approver_username=approver.get_username(),
        backend_approval_id="approval-1",
        status=CephApprovalStatusChoices.STATUS_APPLYING,
    )
    run = CephOperationRun.objects.create(
        operation=operation,
        plan=plan,
        provider=operation.provider,
        approval=approval,
        status=CephOperationStatusChoices.STATUS_APPLYING,
        backend_endpoint_config_revision=ENDPOINT_CONFIG_REVISION,
        plugin_endpoint_id=approval.plugin_endpoint_id,
        provider_id_snapshot=approval.provider_id_snapshot,
        provider_kind_snapshot=approval.provider_kind_snapshot,
        execution_node=approval.execution_node,
        local_config_digest=approval.local_config_digest,
        actor=approver,
        actor_username=approver.get_username(),
        started_at=timezone.now(),
    )

    with pytest.raises(ProtectedError):
        CephOperation.objects.filter(pk=operation.pk).delete()
    with pytest.raises(ProtectedError):
        CephPlan.objects.filter(pk=plan.pk).delete()

    User.objects.filter(pk__in=(requester.pk, approver.pk)).delete()
    operation.refresh_from_db()
    plan.refresh_from_db()
    approval.refresh_from_db()
    run.refresh_from_db()
    assert operation.requested_by is None
    assert operation.requested_by_username == "ceph-requester"
    assert plan.requester is None
    assert plan.requester_username == "ceph-requester"
    assert approval.requester is None
    assert approval.requester_username == "ceph-requester"
    assert approval.approver is None
    assert approval.approver_username == "ceph-approver"
    assert run.actor is None
    assert run.actor_username == "ceph-approver"


def test_live_issuance_lease_allows_exactly_one_backend_approval_post(monkeypatch) -> None:
    requester, approver = _actors()
    operation = _operation(requester, status=CephOperationStatusChoices.STATUS_PLANNED)
    plan = _plan(operation)
    approve_entered = Event()
    release_approve = Event()
    second_started = Event()
    second_finished = Event()
    calls = {"approve": 0, "apply": 0}

    class Orchestrator:
        def resolve_backend_endpoint_id(self, endpoint):
            assert endpoint.pk == operation.cluster.endpoint_id
            return 41

        def approve(self, plan_id, **kwargs):
            calls["approve"] += 1
            approve_entered.set()
            assert release_approve.wait(timeout=30)
            return {
                "id": "approval-1",
                "token": "transient-only",
                "plan_id": plan_id,
                "plan_digest": plan.backend_plan_digest,
                "endpoint_id": 41,
                "endpoint_config_revision": ENDPOINT_CONFIG_REVISION,
                "requester": requester.get_username(),
                "approver": approver.get_username(),
                "expires_at": (timezone.now() + timedelta(minutes=5)).isoformat(),
            }

        def apply(self, plan_id, **kwargs):
            calls["apply"] += 1
            assert kwargs["approval_token"] == "transient-only"
            return {
                "id": "run-1",
                "status": "completed",
                "plan_id": plan_id,
                "plan_digest": plan.backend_plan_digest,
                "endpoint_id": 41,
                "endpoint_config_revision": ENDPOINT_CONFIG_REVISION,
                "approval_id": "approval-1",
                "requester": requester.get_username(),
                "approver": approver.get_username(),
                "actor": requester.get_username(),
                "provider": "proxmox",
                "provider_task_refs": ["UPID:pve-a:task"],
                "warnings": [],
                "errors": [],
            }

        def operation(self, operation_id):
            assert operation_id == "run-1"
            return self.apply_response

        @property
        def apply_response(self):
            return {
                "id": "run-1",
                "status": "completed",
                "plan_id": plan.backend_plan_id,
                "plan_digest": plan.backend_plan_digest,
                "endpoint_id": 41,
                "endpoint_config_revision": ENDPOINT_CONFIG_REVISION,
                "approval_id": "approval-1",
                "requester": requester.get_username(),
                "approver": approver.get_username(),
                "actor": requester.get_username(),
                "provider": "proxmox",
                "provider_task_refs": ["UPID:pve-a:task"],
                "warnings": [],
                "errors": [],
            }

    monkeypatch.setattr(operation_actions, "CephOrchestratorClient", Orchestrator)

    def apply_once():
        close_old_connections()
        try:
            return operation_actions.approve_and_apply_operation(
                CephOperation.objects.get(pk=operation.pk),
                approver=User.objects.get(pk=approver.pk),
            )
        finally:
            close_old_connections()

    def apply_second():
        second_started.set()
        try:
            return apply_once()
        finally:
            second_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(apply_once)
        assert approve_entered.wait(timeout=30)
        second = executor.submit(apply_second)
        assert second_started.wait(timeout=30)
        # Dispatch holds the binding rows locked, so the contender cannot
        # observe or reissue authority while the backend POST is in flight.
        assert second_finished.wait(timeout=0.2) is False
        release_approve.set()
        first_result = first.result(timeout=30)
        with pytest.raises(operation_actions.OperationActionError) as excinfo:
            second.result(timeout=30)

    assert first_result.status == CephOperationStatusChoices.STATUS_SUCCEEDED
    assert excinfo.value.reason == "approval_issuance_in_flight"
    assert calls == {"approve": 1, "apply": 1}
    assert CephOperationApproval.objects.filter(operation=operation).count() == 1
    assert CephOperationRun.objects.filter(operation=operation).count() == 1


def test_expired_issuance_lease_takeover_rejects_late_owner() -> None:
    requester, approver = _actors()
    operation = _operation(requester, status=CephOperationStatusChoices.STATUS_PLANNED)
    _plan(operation)
    _operation_row, _plan_row, approval, first_owner = operation_actions._reserve_approval_intent(
        operation,
        endpoint_id=41,
        requester=requester,
        requester_name=requester.get_username(),
        approver=approver,
        approver_name=approver.get_username(),
    )
    assert first_owner is not None
    CephOperationApproval.objects.filter(pk=approval.pk).update(
        issuance_reservation_expires_at=timezone.now() - timedelta(seconds=1)
    )
    operation.refresh_from_db()
    _operation_row, _plan_row, approval, second_owner = operation_actions._reserve_approval_intent(
        operation,
        endpoint_id=41,
        requester=requester,
        requester_name=requester.get_username(),
        approver=approver,
        approver_name=approver.get_username(),
    )
    assert second_owner is not None and second_owner != first_owner

    with pytest.raises(operation_actions.OperationActionError) as excinfo:
        operation_actions._transition_approval_issuance(
            approval=approval,
            operation=operation,
            issuance_reservation_id=first_owner,
            approval_status=CephApprovalStatusChoices.STATUS_FAILED,
            operation_status=CephOperationStatusChoices.STATUS_FAILED,
            failure_code="late",
            failure_detail="late owner",
        )
    assert excinfo.value.reason == "approval_reservation_lost"
    approval.refresh_from_db()
    assert approval.status == CephApprovalStatusChoices.STATUS_ISSUING
    assert approval.issuance_reservation_id == second_owner


def test_pending_run_is_active_authority_for_plan_and_approval() -> None:
    requester, approver = _actors()
    operation = _operation(requester, status=CephOperationStatusChoices.STATUS_PLANNED)
    _plan(operation)
    CephOperationRun.objects.create(
        operation=operation,
        provider=operation.provider,
        status=CephOperationStatusChoices.STATUS_PENDING,
        actor=requester,
        actor_username=requester.get_username(),
    )

    with pytest.raises(operation_actions.OperationActionError) as plan_error:
        operation_actions._reserve_plan_operation(operation, requested_by=requester)
    assert plan_error.value.reason == "operation_authority_in_flight"

    with pytest.raises(operation_actions.OperationActionError) as approval_error:
        operation_actions._reserve_approval_intent(
            operation,
            endpoint_id=41,
            requester=requester,
            requester_name=requester.get_username(),
            approver=approver,
            approver_name=approver.get_username(),
        )
    assert approval_error.value.reason == "operation_authority_in_flight"


def test_issued_approval_remains_active_authority() -> None:
    requester, approver = _actors()
    operation = _operation(requester, status=CephOperationStatusChoices.STATUS_PLANNED)
    _plan(operation)
    _operation_row, _plan_row, approval, _owner = operation_actions._reserve_approval_intent(
        operation,
        endpoint_id=41,
        requester=requester,
        requester_name=requester.get_username(),
        approver=approver,
        approver_name=approver.get_username(),
    )
    CephOperationApproval.objects.filter(pk=approval.pk).update(
        status=CephApprovalStatusChoices.STATUS_ISSUED,
        issuance_reservation_id=None,
        issuance_reservation_expires_at=None,
    )
    CephOperation.objects.filter(pk=operation.pk).update(
        status=CephOperationStatusChoices.STATUS_PENDING
    )
    operation.refresh_from_db()

    with pytest.raises(operation_actions.OperationActionError) as excinfo:
        operation_actions._reserve_plan_operation(operation, requested_by=requester)
    assert excinfo.value.reason == "operation_authority_in_flight"


def test_stale_execution_node_binding_blocks_approval_reservation() -> None:
    requester, approver = _actors()
    operation = _operation(requester, status=CephOperationStatusChoices.STATUS_PLANNED)
    _plan(operation)
    CephOperation.objects.filter(pk=operation.pk).update(execution_node="pve-b")
    operation.refresh_from_db()

    with pytest.raises(operation_actions.OperationActionError) as excinfo:
        operation_actions._reserve_approval_intent(
            operation,
            endpoint_id=41,
            requester=requester,
            requester_name=requester.get_username(),
            approver=approver,
            approver_name=approver.get_username(),
        )
    assert excinfo.value.reason == "local_binding_changed"
    assert not CephOperationApproval.objects.filter(operation=operation).exists()


def test_nested_secret_intent_is_rejected_before_operation_persistence() -> None:
    requester, _approver = _actors()
    seed = _operation(requester)
    payload = {
        "cluster": seed.cluster_id,
        "provider": seed.provider_id,
        "operation_type": "create",
        "target_kind": "pool",
        "target_ref": "secret-test",
        "execution_node": "pve-a",
        "desired": {"nested": {"apiToken": "never-store"}},
    }
    serializer = CephOperationSerializer(data=payload)

    assert serializer.is_valid() is False
    assert "desired" in serializer.errors
    assert not CephOperation.objects.filter(target_ref="secret-test").exists()

    missing_node = {**payload, "target_ref": "missing-node", "desired": {"size": 3}}
    missing_node.pop("execution_node")
    serializer = CephOperationSerializer(data=missing_node)
    assert serializer.is_valid() is False
    assert "execution_node" in serializer.errors
    assert not CephOperation.objects.filter(target_ref="missing-node").exists()


def test_fault_injection_rolls_back_run_operation_approval_and_plan(monkeypatch) -> None:
    requester, approver = _actors()
    operation = _operation(requester, status=CephOperationStatusChoices.STATUS_APPLYING)
    plan = _plan(operation)
    approval = CephOperationApproval.objects.create(
        operation=operation,
        plan=plan,
        backend_plan_id=plan.backend_plan_id,
        backend_plan_digest=plan.backend_plan_digest,
        backend_endpoint_id=41,
        backend_endpoint_config_revision=ENDPOINT_CONFIG_REVISION,
        plugin_endpoint_id=plan.plugin_endpoint_id,
        provider_id_snapshot=plan.provider_id_snapshot,
        provider_kind_snapshot=plan.provider_kind_snapshot,
        execution_node=plan.execution_node,
        local_config_digest=plan.local_config_digest,
        requester=requester,
        requester_username=requester.get_username(),
        approver=approver,
        approver_username=approver.get_username(),
        backend_approval_id="approval-1",
        status=CephApprovalStatusChoices.STATUS_APPLYING,
    )
    run = CephOperationRun.objects.create(
        operation=operation,
        plan=plan,
        provider=operation.provider,
        approval=approval,
        status=CephOperationStatusChoices.STATUS_APPLYING,
        backend_endpoint_config_revision=ENDPOINT_CONFIG_REVISION,
        plugin_endpoint_id=approval.plugin_endpoint_id,
        provider_id_snapshot=approval.provider_id_snapshot,
        provider_kind_snapshot=approval.provider_kind_snapshot,
        execution_node=approval.execution_node,
        local_config_digest=approval.local_config_digest,
        actor=approver,
        actor_username=approver.get_username(),
        started_at=timezone.now(),
    )
    response = {
        "id": "run-1",
        "status": "completed",
        "plan_id": plan.backend_plan_id,
        "plan_digest": plan.backend_plan_digest,
        "endpoint_id": 41,
        "endpoint_config_revision": ENDPOINT_CONFIG_REVISION,
        "approval_id": approval.backend_approval_id,
        "requester": requester.get_username(),
        "approver": approver.get_username(),
        "actor": requester.get_username(),
        "provider": "proxmox",
        "warnings": [],
        "errors": [],
    }

    def fail(point: str) -> None:
        if point == "record_run.after_run":
            raise RuntimeError("fault injection")

    monkeypatch.setattr(operation_actions, "_TRANSITION_FAULT_INJECTOR", fail)
    with pytest.raises(RuntimeError, match="fault injection"):
        operation_actions._record_run_response(
            run,
            operation,
            approval,
            response,
            plan=plan,
        )

    operation.refresh_from_db()
    plan.refresh_from_db()
    approval.refresh_from_db()
    run.refresh_from_db()
    assert operation.status == CephOperationStatusChoices.STATUS_APPLYING
    assert plan.status == CephPlanStatusChoices.STATUS_VALID
    assert approval.status == CephApprovalStatusChoices.STATUS_APPLYING
    assert approval.backend_run_id == ""
    assert run.status == CephOperationStatusChoices.STATUS_APPLYING
    assert run.backend_run_id == ""


def test_database_enforces_one_run_per_approval() -> None:
    requester, approver = _actors()
    operation = _operation(requester, status=CephOperationStatusChoices.STATUS_APPLYING)
    plan = _plan(operation)
    binding = {
        "plugin_endpoint_id": plan.plugin_endpoint_id,
        "provider_id_snapshot": plan.provider_id_snapshot,
        "provider_kind_snapshot": plan.provider_kind_snapshot,
        "execution_node": plan.execution_node,
        "local_config_digest": plan.local_config_digest,
    }
    approval = CephOperationApproval.objects.create(
        operation=operation,
        plan=plan,
        backend_plan_id=plan.backend_plan_id,
        backend_plan_digest=plan.backend_plan_digest,
        backend_endpoint_id=41,
        backend_endpoint_config_revision=ENDPOINT_CONFIG_REVISION,
        requester=requester,
        requester_username=requester.get_username(),
        approver=approver,
        approver_username=approver.get_username(),
        status=CephApprovalStatusChoices.STATUS_APPLYING,
        **binding,
    )
    run_fields = {
        "operation": operation,
        "plan": plan,
        "provider": operation.provider,
        "approval": approval,
        "status": CephOperationStatusChoices.STATUS_APPLYING,
        "backend_endpoint_config_revision": ENDPOINT_CONFIG_REVISION,
        "actor": approver,
        "actor_username": approver.get_username(),
        **binding,
    }
    CephOperationRun.objects.create(**run_fields)
    with pytest.raises(IntegrityError), transaction.atomic():
        CephOperationRun.objects.create(**run_fields)
