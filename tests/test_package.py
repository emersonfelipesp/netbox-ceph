"""Smoke tests that do not require a NetBox environment."""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_NETBOX_IMAGES = (
    "netboxcommunity/netbox:v4.5.8",
    "netboxcommunity/netbox:v4.5.9",
    "netboxcommunity/netbox:v4.6.0",
    "netboxcommunity/netbox:v4.6.1",
    "netboxcommunity/netbox:v4.6.2",
    "netboxcommunity/netbox:v4.6.3",
)


def test_package_importable() -> None:
    pytest.importorskip("netbox")
    module = importlib.import_module("netbox_ceph")
    assert module is not None
    assert module.__version__ == "0.0.1.post1"


def test_plugin_config_exposes_certification_metadata() -> None:
    pytest.importorskip("netbox")
    from netbox_ceph import config

    assert config.version == "0.0.1.post1"
    assert config.min_version == "4.5.8"
    assert config.max_version == "4.6.99"
    assert config.required_plugins == ["netbox_proxbox"]
    assert config.author_email == "emersonfelipe.2003@gmail.com"


def test_pyproject_certification_metadata() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]

    assert project["version"] == "0.0.1.post1"
    assert project["license"] == "Apache-2.0"
    assert project["license-files"] == ["LICENSE"]
    assert "License :: OSI Approved :: Apache Software License" not in project["classifiers"]
    assert "netbox-proxbox>=0.0.18,<0.1.0" in project["dependencies"]
    assert project["urls"]["Documentation"] == "https://emersonfelipesp.github.io/netbox-ceph/"
    assert (ROOT / "LICENSE").is_file()


def test_package_metadata_version() -> None:
    from importlib import metadata

    try:
        version = metadata.version("netbox-ceph")
    except metadata.PackageNotFoundError:
        pytest.skip("netbox-ceph is not installed in the current environment")
    assert version.count(".") >= 2


def test_e2e_workflow_covers_supported_netbox_versions() -> None:
    workflow = (ROOT / ".github" / "workflows" / "e2e.yml").read_text(encoding="utf-8")

    for image in SUPPORTED_NETBOX_IMAGES:
        assert image in workflow


def test_docs_name_supported_netbox_versions() -> None:
    docs = "\n".join(
        [
            (ROOT / "CERTIFICATION.md").read_text(encoding="utf-8"),
            (ROOT / "README.md").read_text(encoding="utf-8"),
            (ROOT / "docs" / "certification.md").read_text(encoding="utf-8"),
            (ROOT / "docs" / "index.md").read_text(encoding="utf-8"),
            (ROOT / "docs" / "release-notes" / "version-0.0.1.post1.md").read_text(
                encoding="utf-8"
            ),
        ]
    )

    for image in SUPPORTED_NETBOX_IMAGES:
        assert image.rsplit(":", 1)[1] in docs
