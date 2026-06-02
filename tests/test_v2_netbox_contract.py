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
    CephMetricSnapshot,
    CephOperation,
    CephOperationRun,
    CephPlan,
    CephProvider,
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
