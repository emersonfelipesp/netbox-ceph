"""Static safeguards for the security-critical CI verification contract."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_SHA = "82feea3b8ea875121dee7731c96be76fe2931611"


def _workflow(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_both_ci_surfaces_use_the_reviewed_authority_contract() -> None:
    for path in (".github/workflows/ci.yml", ".gitea/workflows/ci.yml"):
        workflow = _workflow(path)

        assert AUTHORITY_SHA in workflow
        assert 'checkout --detach "$NETBOX_PROXBOX_SHA"' in workflow
        assert 'rev-parse HEAD)" = "$NETBOX_PROXBOX_SHA"' in workflow
        assert "pip install -e ./netbox-proxbox" in workflow
        assert "pip install -e . --no-deps" in workflow


def test_public_ci_fetches_public_dependencies() -> None:
    github_workflow = _workflow(".github/workflows/ci.yml")
    gitea_workflow = _workflow(".gitea/workflows/ci.yml")

    assert "https://github.com/emersonfelipesp/netbox-proxbox.git" in github_workflow
    assert "git.nmulti.cloud" not in github_workflow
    assert "https://git.nmulti.cloud/emersonfelipesp/netbox-proxbox.git" in gitea_workflow


def test_core_ci_actions_are_pinned_by_commit() -> None:
    for path in (".github/workflows/ci.yml", ".gitea/workflows/ci.yml"):
        workflow = _workflow(path)
        action_references = re.findall(r"^\s*uses:\s*(\S+)", workflow, re.MULTILINE)

        assert action_references
        assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref) for ref in action_references)

    assert _workflow(".github/workflows/ci.yml").count("persist-credentials: false") >= 3


def test_both_ci_surfaces_enforce_full_tree_formatting() -> None:
    for path in (".github/workflows/ci.yml", ".gitea/workflows/ci.yml"):
        assert "ruff format --check ." in _workflow(path)


def test_github_ci_exercises_real_postgresql_authority_state_machine() -> None:
    workflow = _workflow(".github/workflows/ci.yml")

    assert 'netbox-version: "v4.5.8"' in workflow
    assert "netbox-ref: 75e1b86613792458b4d4c8d0cbbfc94df16cfaaf" in workflow
    assert 'netbox-version: "v4.6.4"' in workflow
    assert "netbox-ref: 3d73b2a1669ad03c9f0ccb1332fe201d60cbce9e" in workflow
    assert "ref: ${{ matrix.netbox-ref }}" in workflow
    assert "postgres-state-machine:" in workflow
    assert "tests/test_operation_state_machine_django.py" in workflow
    assert "tests/test_v2_actions.py" in workflow
    assert "tests/test_v2_netbox_contract.py" in workflow
    assert "makemigrations netbox_ceph --check --dry-run" in workflow


def test_github_ci_database_images_are_digest_pinned() -> None:
    workflow = _workflow(".github/workflows/ci.yml")

    assert (
        "postgres:16-alpine@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777"
    ) in workflow
    assert (
        "redis:7-alpine@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99"
    ) in workflow
    assert "runs-on: ubuntu-latest" not in workflow


def test_gitea_quality_toolchain_is_version_pinned() -> None:
    workflow = _workflow(".gitea/workflows/ci.yml")

    for requirement in (
        "requests==2.33.0",
        "pytest==9.0.3",
        "pytest-cov==7.1.0",
        "mkdocs==1.6.1",
        "mkdocs-material==9.7.6",
        "mkdocstrings[python]==1.0.3",
        "ghp-import==2.1.0",
        "ruff==0.15.8",
        "build==1.5.0",
        "twine==6.2.0",
    ):
        assert requirement in workflow


def test_real_netbox_configuration_keeps_companion_plugins_opt_in() -> None:
    configuration = (ROOT / "tests" / "netbox_test_configuration.py").read_text(encoding="utf-8")

    assert "NETBOX_TEST_ENABLE_BRANCHING" in configuration
    assert "NETBOX_TEST_ENABLE_PDM" in configuration
    assert 'PLUGINS.append("netbox_proxbox")' in configuration
    assert 'PLUGINS.append("netbox_ceph")' in configuration
