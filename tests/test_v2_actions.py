"""NetBox-gated tests for the Ceph v2 action service and UI wiring.

These need the NetBox app registry (for models/choices and URL registration) but
not a database. They are skipped in the plain-pytest CI job and run in a NetBox
environment (local / plugin smoke). DB-backed behavior is covered by the
proxbox-api contract suite and the pure builder tests.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("netbox")

from django.conf import settings  # noqa: E402

if not settings.configured:
    pytest.skip("Django settings are not configured", allow_module_level=True)

try:
    import django  # noqa: E402

    django.setup()
except Exception as exc:  # noqa: BLE001
    pytest.skip(f"NetBox app registry is not available: {exc}", allow_module_level=True)

from django.urls import reverse  # noqa: E402

from netbox_ceph import views  # noqa: E402
from netbox_ceph.choices import CephOperationStatusChoices, CephOperationTypeChoices  # noqa: E402
from netbox_ceph.services import desired_state_operations, operation_actions  # noqa: E402


def test_operation_payload_shape() -> None:
    provider = SimpleNamespace(kind="proxmox", name="pve-cluster")
    operation = SimpleNamespace(
        pk=1,
        cluster_id=7,
        provider_id=3,
        provider=provider,
        operation_type="reconcile",
        target_kind="pool",
        target_ref="rbd",
        desired={"size": 3},
        is_destructive=False,
        confirmation_required=False,
        confirmed=False,
        source_branch_schema_id="branch-abc",
    )
    payload = operation_actions.operation_payload(operation)
    assert payload["provider_kind"] == "proxmox"
    assert payload["target_kind"] == "pool"
    assert payload["target_ref"] == "rbd"
    assert payload["desired"] == {"size": 3}
    assert payload["source_branch_schema_id"] == "branch-abc"


def test_apply_operation_rejects_unplanned() -> None:
    operation = SimpleNamespace(status=CephOperationStatusChoices.STATUS_PENDING)
    with pytest.raises(operation_actions.OperationActionError) as excinfo:
        operation_actions.apply_operation(operation, actor=None, confirmed=False)
    assert excinfo.value.kind == "invalid"
    assert "planned" in excinfo.value.message


def test_instance_values_for_pool_resolves_without_db() -> None:
    pool = type(
        "CephPoolDesiredState",
        (),
        {},
    )()
    pool.name = "rbd"
    pool.size = 3
    pool.min_size = 2
    pool.pg_autoscale_mode = "on"
    pool.crush_rule_name = ""
    pool.application = "rbd"
    pool.target_size_ratio = None
    pool.quota_max_bytes = None
    pool.quota_max_objects = None
    pool.compression_mode = "none"
    pool.erasure_code_profile = ""
    pool.parameters = {}

    values = desired_state_operations._instance_values(pool)
    request = desired_state_operations.build_request("CephPoolDesiredState", values)
    assert request["target_kind"] == "pool"
    assert request["target_ref"] == "rbd"
    assert request["desired"]["size"] == 3
    assert "crush_rule" not in request["desired"]  # blank crush rule dropped


def test_reconcile_uses_reconcile_operation_type() -> None:
    # The generated reconcile operation type is non-destructive by contract.
    assert CephOperationTypeChoices.TYPE_RECONCILE == "reconcile"


def test_action_views_are_registered() -> None:
    assert hasattr(views, "CephOperationPlanView")
    assert hasattr(views, "CephOperationApplyView")
    assert hasattr(views, "CephProviderReconcileView")


@pytest.mark.parametrize(
    "route_name",
    [
        "plugins:netbox_ceph:cephoperation_plan",
        "plugins:netbox_ceph:cephoperation_apply",
        "plugins:netbox_ceph:cephprovider_reconcile",
        "plugins:netbox_ceph:cephpooldesiredstate_generate_operation",
        "plugins:netbox_ceph:cephrgwbucketdesiredstate_generate_operation",
    ],
)
def test_action_routes_reverse(route_name: str) -> None:
    assert reverse(route_name, kwargs={"pk": 1})
