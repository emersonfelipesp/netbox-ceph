"""Pure tests for the desired-state -> CephOperation request builders.

These exercise ``netbox_ceph.services.desired_state_operations`` without a
NetBox runtime: the payload/target shaping is Django-free, so it runs in the
plain-pytest CI job. The generated ``{target_kind, target_ref, desired}`` shape
mirrors the proxbox-api ``/ceph/v2`` contract verified in proxbox-api's
``tests/ceph/test_v2_netbox_payload.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from netbox_ceph.services import desired_state_operations as dso
from netbox_ceph.services.redaction import SecretBearingIntentError

FIXTURE_PATH = Path(__file__).parent / "fixtures/ceph_v2_writer_contract.v1.json"


def test_supported_models_match_implemented_proxmox_writer_kinds() -> None:
    assert dso.supported_models() == (
        "CephPoolDesiredState",
        "CephFilesystemDesiredState",
    )


def test_clean_drops_empty_values_keeps_false_and_zero() -> None:
    cleaned = dso._clean(
        {
            "name": "x",
            "blank": "",
            "none": None,
            "empty_list": [],
            "empty_map": {},
            "flag_false": False,
            "zero": 0,
        }
    )
    assert cleaned == {"name": "x", "flag_false": False, "zero": 0}


def test_clean_folds_parameters_without_overriding_explicit_keys() -> None:
    cleaned = dso._clean(
        {
            "name": "explicit",
            "parameters": {"name": "ignored", "extra": "kept"},
        }
    )
    assert cleaned == {"name": "explicit", "extra": "kept"}


def test_clean_rejects_nested_secret_parameters_before_folding() -> None:
    with pytest.raises(SecretBearingIntentError):
        dso._clean(
            {
                "name": "unsafe",
                "parameters": {"nested": {"apiToken": "must-not-persist"}},
            }
        )


def test_pool_request_shape() -> None:
    request = dso.build_request(
        "CephPoolDesiredState",
        {
            "name": "rbd",
            "execution_node": "pve-a",
            "size": 3,
            "min_size": 2,
            "pg_autoscale_mode": "on",
            "crush_rule_name": "replicated_rule",
            "application": "rbd",
            "parameters": {},
        },
    )
    assert request["target_kind"] == "pool"
    assert request["target_ref"] == "rbd"
    assert request["execution_node"] == "pve-a"
    assert request["desired"] == {
        "size": 3,
        "min_size": 2,
        "pg_autoscale_mode": "on",
        "crush_rule": "replicated_rule",
        "application": "rbd",
    }


def test_filesystem_request_shape() -> None:
    request = dso.build_request(
        "CephFilesystemDesiredState",
        {
            "name": "cephfs",
            "execution_node": "pve-a",
            "pg_num": 128,
            "add_storage": True,
        },
    )
    assert request["target_kind"] == "filesystem"
    assert request["target_ref"] == "cephfs"
    assert request["execution_node"] == "pve-a"
    assert request["desired"] == {"pg_num": 128, "add_storage": True}


@pytest.mark.parametrize(
    "model_name",
    (
        "CephRBDImageDesiredState",
        "CephRBDSnapshotDesiredState",
        "CephRGWRealmDesiredState",
        "CephRGWZoneDesiredState",
        "CephRGWUserDesiredState",
        "CephRGWBucketDesiredState",
    ),
)
def test_unsupported_desired_kinds_fail_before_backend_planning(model_name) -> None:
    with pytest.raises(dso.DesiredStateContractError, match="not supported"):
        dso.build_request(model_name, {"name": "blocked"})


@pytest.mark.parametrize(
    "values, field",
    (
        ({"name": "pool", "quota_max_bytes": 1}, "quota_max_bytes"),
        ({"name": "pool", "compression_mode": "aggressive"}, "compression_mode"),
        ({"name": "pool", "parameters": {"unknown": True}}, "unknown"),
    ),
)
def test_pool_builder_rejects_fields_outside_strict_writer(values, field) -> None:
    with pytest.raises(dso.DesiredStateContractError, match=field):
        dso.build_request("CephPoolDesiredState", values)


def test_pool_builder_uses_proxbox_erasure_coding_alias() -> None:
    request = dso.build_request(
        "CephPoolDesiredState",
        {
            "name": "ec",
            "execution_node": "pve-a",
            "erasure_code_profile": "ec-profile",
        },
    )
    assert request["desired"] == {"erasure_coding": "ec-profile"}


def test_versioned_writer_fixture_matches_real_builders() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert fixture["contract_version"] == dso.CEPH_WRITE_CONTRACT_VERSION
    for case in fixture["cases"]:
        request = dso.build_request(case["model"], case["values"])
        assert request == case["request"]
        assert case["plan_request"] == {
            "provider": "proxmox",
            "endpoint_id": 41,
            "desired_state": {
                "objects": [
                    {
                        "kind": request["target_kind"],
                        "target_ref": request["target_ref"],
                        "action": "reconcile",
                        "provider": "proxmox",
                        "node": request["execution_node"],
                        "payload": request["desired"],
                    }
                ]
            },
        }
        assert case["provider_operation"] == {
            "provider": "proxmox",
            "kind": request["target_kind"],
            "target_ref": request["target_ref"],
            "action": "create",
            "node": request["execution_node"],
            "supported": True,
            "after_summary": request["desired"],
        }
