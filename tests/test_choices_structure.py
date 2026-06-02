"""Choice-set structure tests for Ceph v2 values."""

from __future__ import annotations

import pytest

pytest.importorskip("utilities.choices")

from netbox_ceph.choices import (  # noqa: E402
    CephDriftStatusChoices,
    CephMetricScopeChoices,
    CephOperationStatusChoices,
    CephOperationTypeChoices,
    CephPlanStatusChoices,
    CephProviderKindChoices,
    CephProviderStatusChoices,
    CephValidationSeverityChoices,
)


def _values(choice_set) -> set[str]:
    return {value for value, _label, _color in choice_set.CHOICES}


def _assert_colored_triples(choice_set) -> None:
    assert choice_set.key
    for choice in choice_set.CHOICES:
        assert len(choice) == 3
        value, label, color = choice
        assert value
        assert label
        assert color


def test_v2_choice_sets_have_expected_values_and_colors() -> None:
    expected = {
        CephProviderKindChoices: {"proxmox", "dashboard", "rgw_admin", "prometheus", "external"},
        CephProviderStatusChoices: {
            "unknown",
            "ok",
            "degraded",
            "unreachable",
            "unauthorized",
        },
        CephOperationTypeChoices: {"create", "update", "delete", "apply", "reconcile", "custom"},
        CephOperationStatusChoices: {
            "pending",
            "planning",
            "planned",
            "awaiting_confirmation",
            "applying",
            "succeeded",
            "failed",
            "cancelled",
            "unsupported",
        },
        CephPlanStatusChoices: {"draft", "valid", "invalid", "applied", "stale"},
        CephDriftStatusChoices: {
            "in_sync",
            "drifted",
            "missing_in_provider",
            "missing_in_netbox",
            "unknown",
        },
        CephValidationSeverityChoices: {"info", "warning", "error", "blocker"},
        CephMetricScopeChoices: {"cluster", "daemon", "pool", "osd", "cephfs", "rgw", "rbd"},
    }

    for choice_set, values in expected.items():
        _assert_colored_triples(choice_set)
        assert _values(choice_set) == values
