"""NetBox-gated contract tests for Ceph v2 foundation objects."""

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

from netbox_ceph.api import serializers, views  # noqa: E402
from netbox_ceph.choices import CephOperationStatusChoices  # noqa: E402
from netbox_ceph.models import (  # noqa: E402
    CephDriftRecord,
    CephFilesystemDesiredState,
    CephMetricSnapshot,
    CephOperation,
    CephOperationRun,
    CephPlan,
    CephPoolDesiredState,
    CephProvider,
    CephRBDImageDesiredState,
    CephRBDSnapshotDesiredState,
    CephValidationResult,
)


def test_v2_model_identity_constraints_are_named() -> None:
    constraints = {
        CephProvider: "netbox_ceph_provider_identity",
        CephDriftRecord: "netbox_ceph_drift_record_identity",
        CephMetricSnapshot: "netbox_ceph_metric_snapshot_identity",
    }

    for model, constraint_name in constraints.items():
        assert constraint_name in {constraint.name for constraint in model._meta.constraints}


@pytest.mark.parametrize(
    ("model", "route_name"),
    [
        (CephProvider, "cephprovider"),
        (CephOperation, "cephoperation"),
        (CephPlan, "cephplan"),
        (CephValidationResult, "cephvalidationresult"),
        (CephOperationRun, "cephoperationrun"),
        (CephDriftRecord, "cephdriftrecord"),
        (CephMetricSnapshot, "cephmetricsnapshot"),
    ],
)
def test_v2_models_reverse_absolute_urls(model, route_name: str) -> None:
    obj = model(pk=123)
    assert obj.get_absolute_url() == reverse(f"plugins:netbox_ceph:{route_name}", args=[123])


def test_v2_serializer_fields_are_present() -> None:
    expected = {
        serializers.CephProviderSerializer: {"cluster", "kind", "credential_ref", "status"},
        serializers.CephOperationSerializer: {
            "cluster",
            "provider",
            "operation_type",
            "target_kind",
            "desired",
            "status",
        },
        serializers.CephPlanSerializer: {"operation", "status", "intended_changes", "raw"},
        serializers.CephValidationResultSerializer: {"plan", "operation", "severity", "code"},
        serializers.CephOperationRunSerializer: {"operation", "plan", "provider", "status"},
        serializers.CephDriftRecordSerializer: {
            "cluster",
            "object_kind",
            "object_ref",
            "drift_status",
        },
        serializers.CephMetricSnapshotSerializer: {"cluster", "scope", "object_ref", "metrics"},
    }

    for serializer_cls, fields in expected.items():
        assert fields.issubset(set(serializer_cls.Meta.fields))


def test_apply_action_rejects_unplanned_operation_before_backend_call() -> None:
    viewset = views.CephOperationViewSet()
    viewset.get_object = lambda: SimpleNamespace(status=CephOperationStatusChoices.STATUS_PENDING)
    request = SimpleNamespace(data={})

    response = viewset.apply(request)

    assert response.status_code == 400
    assert "planned" in response.data["detail"]


def test_desired_state_identity_constraints_are_named() -> None:
    constraints = {
        CephPoolDesiredState: "netbox_ceph_pool_desired_identity",
        CephFilesystemDesiredState: "netbox_ceph_filesystem_desired_identity",
        CephRBDImageDesiredState: "netbox_ceph_rbd_image_desired_identity",
        CephRBDSnapshotDesiredState: "netbox_ceph_rbd_snapshot_desired_identity",
    }
    for model, constraint_name in constraints.items():
        assert constraint_name in {c.name for c in model._meta.constraints}


@pytest.mark.parametrize(
    ("model", "route_name"),
    [
        (CephPoolDesiredState, "cephpooldesiredstate"),
        (CephFilesystemDesiredState, "cephfilesystemdesiredstate"),
        (CephRBDImageDesiredState, "cephrbdimagedesiredstate"),
        (CephRBDSnapshotDesiredState, "cephrbdsnapshotdesiredstate"),
    ],
)
def test_desired_state_models_reverse_absolute_urls(model, route_name: str) -> None:
    obj = model(pk=77)
    assert obj.get_absolute_url() == reverse(f"plugins:netbox_ceph:{route_name}", args=[77])


@pytest.mark.parametrize(
    "route_name",
    [
        "cephpooldesiredstate",
        "cephfilesystemdesiredstate",
        "cephrbdimagedesiredstate",
        "cephrbdsnapshotdesiredstate",
    ],
)
def test_desired_state_writable_crud_urls_registered(route_name: str) -> None:
    # Writable models must expose add/edit/delete/list, or the nav/list UI 500s
    # (a missing ``add`` route was the Part 1 regression this guards against).
    assert reverse(f"plugins:netbox_ceph:{route_name}_add")
    assert reverse(f"plugins:netbox_ceph:{route_name}_list")
    assert reverse(f"plugins:netbox_ceph:{route_name}_edit", args=[1])
    assert reverse(f"plugins:netbox_ceph:{route_name}_delete", args=[1])


def test_desired_state_serializer_fields_are_present() -> None:
    expected = {
        serializers.CephPoolDesiredStateSerializer: {
            "cluster",
            "name",
            "size",
            "min_size",
            "pg_autoscale_mode",
            "application",
            "compression_mode",
        },
        serializers.CephFilesystemDesiredStateSerializer: {
            "cluster",
            "name",
            "metadata_pool",
            "data_pools",
            "standby_count",
            "max_mds",
        },
        serializers.CephRBDImageDesiredStateSerializer: {
            "cluster",
            "pool_name",
            "name",
            "size_bytes",
            "features",
            "clone_parent_image",
            "metadata",
        },
        serializers.CephRBDSnapshotDesiredStateSerializer: {
            "cluster",
            "image",
            "name",
            "protected",
            "parameters",
        },
    }
    for serializer_cls, fields in expected.items():
        assert fields.issubset(set(serializer_cls.Meta.fields))


def test_desired_state_viewsets_allow_writes() -> None:
    for viewset_cls in (
        views.CephPoolDesiredStateViewSet,
        views.CephFilesystemDesiredStateViewSet,
        views.CephRBDImageDesiredStateViewSet,
        views.CephRBDSnapshotDesiredStateViewSet,
    ):
        # No read-only restriction: POST/PATCH/DELETE must be permitted.
        methods = getattr(viewset_cls, "http_method_names", None)
        assert methods is None or "post" in methods


def test_navigation_links_and_buttons_all_reverse() -> None:
    """Every nav link/button must reverse.

    The sidebar is rendered on every templated page, and NetBox reverses each
    ``MenuItem.link`` / ``MenuItemButton.link`` via ``reverse_lazy`` at render
    time without catching ``NoReverseMatch``. A single unregistered URL name
    (e.g. a writable model missing its ``add`` view) therefore 500s the entire
    UI. This test fails fast on that class of regression.
    """
    from netbox_ceph.navigation import menu  # noqa: PLC0415

    link_names: set[str] = set()
    for group in menu.groups:
        for item in group.items:
            if item.link:
                link_names.add(item.link)
            for button in item.buttons:
                if button.link:
                    link_names.add(button.link)

    assert link_names, "navigation menu exposed no links"
    for link_name in sorted(link_names):
        # Raises NoReverseMatch if the URL name is not registered.
        reverse(link_name)


def test_reflected_inventory_viewsets_remain_read_only() -> None:
    reflected_viewsets = (
        views.CephClusterViewSet,
        views.CephDaemonViewSet,
        views.CephOSDViewSet,
        views.CephPoolViewSet,
        views.CephFilesystemViewSet,
        views.CephCrushRuleViewSet,
        views.CephFlagViewSet,
        views.CephHealthCheckViewSet,
    )

    for viewset_cls in reflected_viewsets:
        assert viewset_cls.http_method_names == ("get", "head", "options")
