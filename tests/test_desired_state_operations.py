"""Pure tests for the desired-state -> CephOperation request builders.

These exercise ``netbox_ceph.services.desired_state_operations`` without a
NetBox runtime: the payload/target shaping is Django-free, so it runs in the
plain-pytest CI job. The generated ``{target_kind, target_ref, desired}`` shape
mirrors the proxbox-api ``/ceph/v2`` contract verified in proxbox-api's
``tests/ceph/test_v2_netbox_payload.py``.
"""

from __future__ import annotations

from netbox_ceph.services import desired_state_operations as dso


def test_supported_models_covers_eight_desired_state_kinds() -> None:
    assert len(dso.supported_models()) == 8
    assert "CephPoolDesiredState" in dso.supported_models()
    assert "CephRGWBucketDesiredState" in dso.supported_models()


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


def test_pool_request_shape() -> None:
    request = dso.build_request(
        "CephPoolDesiredState",
        {
            "name": "rbd",
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
    assert request["desired"] == {
        "name": "rbd",
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
            "metadata_pool_name": "cephfs_meta",
            "data_pools": ["cephfs_data"],
            "max_mds": 2,
        },
    )
    assert request["target_kind"] == "filesystem"
    assert request["target_ref"] == "cephfs"
    assert request["desired"]["metadata_pool"] == "cephfs_meta"
    assert request["desired"]["data_pools"] == ["cephfs_data"]
    assert request["desired"]["max_mds"] == 2


def test_rbd_image_ref_uses_pool_and_name() -> None:
    request = dso.build_request(
        "CephRBDImageDesiredState",
        {"pool_name": "rbd", "name": "disk0", "size_bytes": 10737418240},
    )
    assert request["target_kind"] == "rbd_image"
    assert request["target_ref"] == "rbd/disk0"
    assert request["desired"]["pool"] == "rbd"
    assert request["desired"]["size_bytes"] == 10737418240


def test_rbd_snapshot_ref_uses_pool_image_and_snapshot() -> None:
    request = dso.build_request(
        "CephRBDSnapshotDesiredState",
        {"pool_name": "rbd", "image_name": "disk0", "name": "snap1", "protected": True},
    )
    assert request["target_kind"] == "rbd_snapshot"
    assert request["target_ref"] == "rbd/disk0@snap1"
    assert request["desired"]["protected"] is True


def test_rgw_realm_request_shape() -> None:
    request = dso.build_request(
        "CephRGWRealmDesiredState",
        {"name": "default-realm", "is_default": True},
    )
    assert request["target_kind"] == "rgw_realm"
    assert request["target_ref"] == "default-realm"
    assert request["desired"] == {"name": "default-realm", "is_default": True}


def test_rgw_zone_request_shape() -> None:
    request = dso.build_request(
        "CephRGWZoneDesiredState",
        {
            "name": "z1",
            "realm_name": "r1",
            "zonegroup_name": "zg1",
            "is_master": True,
            "endpoints": ["http://rgw:7480"],
        },
    )
    assert request["target_kind"] == "rgw_zone"
    assert request["target_ref"] == "z1"
    assert request["desired"]["realm"] == "r1"
    assert request["desired"]["zonegroup"] == "zg1"
    assert request["desired"]["endpoints"] == ["http://rgw:7480"]


def test_rgw_user_request_carries_only_credential_ref() -> None:
    request = dso.build_request(
        "CephRGWUserDesiredState",
        {
            "uid": "alice",
            "display_name": "Alice",
            "credential_ref": "vault:rgw/alice",
            "suspended": False,
        },
    )
    assert request["target_kind"] == "rgw_user"
    assert request["target_ref"] == "alice"
    assert request["desired"]["credential_ref"] == "vault:rgw/alice"
    # No raw secret keys are ever emitted.
    assert "secret_key" not in request["desired"]
    assert "access_key" not in request["desired"]


def test_rgw_bucket_request_shape() -> None:
    request = dso.build_request(
        "CephRGWBucketDesiredState",
        {"name": "backups", "owner_uid": "alice", "versioning_enabled": True},
    )
    assert request["target_kind"] == "rgw_bucket"
    assert request["target_ref"] == "backups"
    assert request["desired"]["owner"] == "alice"
    assert request["desired"]["versioning_enabled"] is True
