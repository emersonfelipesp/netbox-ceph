"""Smoke tests that do not require a NetBox environment."""

from __future__ import annotations

import importlib

import pytest


def test_package_importable() -> None:
    pytest.importorskip("netbox")
    module = importlib.import_module("netbox_ceph")
    assert module is not None


def test_package_metadata_version() -> None:
    from importlib import metadata

    try:
        version = metadata.version("netbox-ceph")
    except metadata.PackageNotFoundError:
        pytest.skip("netbox-ceph is not installed in the current environment")
    assert version.count(".") >= 2
