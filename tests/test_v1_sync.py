"""Tests for the v1 Ceph reflection sync job and dispatch surface."""

from __future__ import annotations

import importlib.util
import logging
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _summary_payload(
    resource: str,
    *,
    errors: list[str] | None = None,
    name: str = "pve-a",
) -> dict[str, object]:
    return {
        "name": name,
        "host": "pve-a.example",
        "resource": resource,
        "fetched": 3,
        "written": 2,
        "errors": list(errors or []),
        "nodes": ["pve-a"],
        "netbox_branch_schema_id": None,
    }


def _sync_payload(
    resource: str,
    *,
    errors: list[str] | None = None,
) -> dict[str, object]:
    return {"items": [_summary_payload(resource, errors=errors)], "raw": None}


def _load_module(module_name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(module_name)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous
    return module


@pytest.fixture
def jobs_module(monkeypatch: pytest.MonkeyPatch):
    netbox_constants = types.ModuleType("netbox.constants")
    netbox_constants.RQ_QUEUE_DEFAULT = "default"
    monkeypatch.setitem(sys.modules, "netbox.constants", netbox_constants)

    netbox_jobs = types.ModuleType("netbox.jobs")

    class JobRunner:
        @classmethod
        def enqueue(cls, **kwargs):  # pragma: no cover - tests patch this per case
            raise AssertionError("JobRunner.enqueue was not patched")

    netbox_jobs.JobRunner = JobRunner
    netbox_jobs.Job = object
    monkeypatch.setitem(sys.modules, "netbox.jobs", netbox_jobs)

    branch_lifecycle = types.ModuleType("netbox_ceph.services.branch_lifecycle")

    class BranchingUnavailableError(RuntimeError):
        pass

    setattr(branch_lifecycle, "BranchingUnavailableError", BranchingUnavailableError)
    branch_lifecycle.branching_enabled_settings = lambda: None
    branch_lifecycle.create_and_provision_branch = None
    branch_lifecycle.merge_branch = None
    monkeypatch.setitem(
        sys.modules,
        "netbox_ceph.services.branch_lifecycle",
        branch_lifecycle,
    )

    http_client = types.ModuleType("netbox_ceph.services.http_client")
    http_client.CEPH_SYNC_RESOURCES = (
        "status",
        "daemons",
        "osds",
        "pools",
        "filesystems",
        "crush",
        "flags",
        "rgw",
        "rbd",
        "full",
    )

    class CephBackendError(RuntimeError):
        pass

    class CephSyncPayloadError(CephBackendError):
        reason = "malformed_summary"

    class CephSyncResponse:
        def __init__(self, payload):
            self._payload = payload
            self.errors = [error for item in payload["items"] for error in item.get("errors", [])]

        def as_payload(self):
            return self._payload

    @dataclass(frozen=True)
    class CephBackendContext:
        base_url: str
        headers: dict[str, str]
        verify_ssl: bool = True

    @dataclass(frozen=True)
    class CephSyncScope:
        backend_endpoint_id: int
        endpoint_name: str
        endpoint_host: str

    http_client.CephBackendError = CephBackendError
    http_client.CephSyncPayloadError = CephSyncPayloadError
    http_client.CephSyncResponse = CephSyncResponse
    http_client.CephBackendContext = CephBackendContext
    http_client.CephSyncScope = CephSyncScope
    http_client.resolve_ceph_backend_context = lambda: CephBackendContext(
        base_url="https://backend.example", headers={}
    )
    http_client.fetch_ceph_sync = lambda resource, **kwargs: CephSyncResponse(
        _sync_payload(resource)
    )
    monkeypatch.setitem(sys.modules, "netbox_ceph.services.http_client", http_client)

    module = _load_module("tests._netbox_ceph_jobs_under_test", "netbox_ceph/jobs.py")
    # Scope resolution needs Django models and a live backend; job tests bind the
    # run to a fixed endpoint unless they exercise the resolver explicitly.
    module._real_resolve_sync_target = module._resolve_sync_target
    module._resolve_sync_target = lambda cluster_pk: _resolved_target(module)
    return module


def _resolved_target(jobs_module):
    return jobs_module._ResolvedSyncTarget(
        scope=jobs_module.CephSyncScope(7, "Lab (nb:3)", "backend.example"),
        backend_context=jobs_module.CephBackendContext(
            base_url="https://backend.example", headers={}
        ),
        proxmox_cluster_pk=5,
        endpoint_pk=3,
    )


def test_normalize_resources_defaults_deduplicates_and_rejects_invalid(jobs_module) -> None:
    assert jobs_module._normalize_resources(None) == ["full"]
    assert jobs_module._normalize_resources([]) == ["full"]
    assert jobs_module._normalize_resources("pools, osds, pools") == ["pools", "osds"]
    assert jobs_module._normalize_resources([" pools ", "osds,flags"]) == [
        "pools",
        "osds",
        "flags",
    ]

    with pytest.raises(ValueError, match="Unknown Ceph sync resource"):
        jobs_module._normalize_resources(["pools", "not-a-resource"])


def test_ceph_sync_job_enqueue_uses_keyword_args_and_persists_params(
    monkeypatch: pytest.MonkeyPatch,
    jobs_module,
) -> None:
    captured: dict[str, object] = {}
    saves: list[list[str]] = []

    class FakeJob:
        pk = 42
        data = None

        def save(self, update_fields=None):
            saves.append(list(update_fields or []))

    @classmethod
    def fake_enqueue(cls, **kwargs):
        captured.update(kwargs)
        return FakeJob()

    monkeypatch.setattr(
        sys.modules["netbox.jobs"].JobRunner,
        "enqueue",
        fake_enqueue,
        raising=False,
    )

    enqueue_kwargs = {
        "name": "Ceph Sync: ceph-a",
        "user": None,
        "queue_name": "default",
        "instance": None,
        "cluster_pk": 7,
        "resources": "pools,osds,pools",
    }
    job = jobs_module.CephSyncJob.enqueue(**enqueue_kwargs)

    assert captured["resources"] == ["pools", "osds"]
    assert captured["cluster_pk"] == 7
    assert captured["job_timeout"] == jobs_module.CEPH_SYNC_JOB_TIMEOUT
    assert "instance" not in captured
    assert job.data == {"ceph_sync": {"params": {"resources": ["pools", "osds"], "cluster_pk": 7}}}
    assert saves == [["data"]]

    with pytest.raises(TypeError):
        jobs_module.CephSyncJob.enqueue(None, resources=["pools"])

    with pytest.raises(ValueError, match="use cluster_pk instead"):
        jobs_module.CephSyncJob.enqueue(**{"instance": object(), "resources": ["pools"]})


def _job_runner(jobs_module):
    runner = jobs_module.CephSyncJob()
    runner.logger = logging.getLogger("test_ceph_sync_job")
    job = SimpleNamespace(
        pk=101,
        user=SimpleNamespace(username="operator"),
        data=None,
        saved_data=[],
    )
    job.save = lambda update_fields=None: job.saved_data.append(job.data)
    runner.job = job
    return runner


def _wire_http_client_to_job(
    monkeypatch: pytest.MonkeyPatch,
    jobs_module,
    http_client_module,
) -> None:
    monkeypatch.setattr(jobs_module, "CephBackendError", http_client_module.CephBackendError)
    monkeypatch.setattr(
        jobs_module,
        "CephSyncPayloadError",
        http_client_module.CephSyncPayloadError,
    )
    monkeypatch.setattr(jobs_module, "fetch_ceph_sync", http_client_module.fetch_ceph_sync)


def _configure_isolated_job(monkeypatch: pytest.MonkeyPatch, jobs_module):
    branch = SimpleNamespace(name="ceph-sync-101", schema_id="schema-101")
    merge_calls: list[object] = []
    monkeypatch.setattr(
        jobs_module,
        "branching_enabled_settings",
        lambda: {"prefix": "ceph-sync", "on_conflict": "fail"},
    )
    monkeypatch.setattr(
        jobs_module,
        "create_and_provision_branch",
        lambda *, name, user: branch,
    )
    monkeypatch.setattr(
        jobs_module,
        "merge_branch",
        lambda **kwargs: merge_calls.append(kwargs),
    )
    return branch, merge_calls


def test_ceph_sync_job_run_records_successful_stages(
    monkeypatch: pytest.MonkeyPatch,
    jobs_module,
) -> None:
    calls: list[tuple[str, str | None]] = []

    def fake_fetch(resource, *, scope, netbox_branch_schema_id=None, backend_context=None):
        calls.append((resource, netbox_branch_schema_id))
        return jobs_module.CephSyncResponse(_sync_payload(resource))

    monkeypatch.setattr(jobs_module, "branching_enabled_settings", lambda: None)
    monkeypatch.setattr(jobs_module, "fetch_ceph_sync", fake_fetch)

    runner = _job_runner(jobs_module)
    runner.run(resources=["pools", "osds"], cluster_pk=7)

    assert calls == [("pools", None), ("osds", None)]
    ceph_sync = runner.job.data["ceph_sync"]
    assert ceph_sync["params"]["cluster_pk"] == 7
    assert ceph_sync["params"]["resources"] == ["pools", "osds"]
    assert [stage["status"] for stage in ceph_sync["response"]["stages"]] == [
        "ok",
        "ok",
    ]
    assert ceph_sync["response"]["stages"][0]["response"] == _sync_payload("pools")


def test_unavailable_branching_stops_before_any_model_write(
    monkeypatch: pytest.MonkeyPatch,
    jobs_module,
) -> None:
    error_message = (
        "Ceph sync refused: branch isolation is configured, but the runtime is unavailable."
    )
    branch_lifecycle = sys.modules["netbox_ceph.services.branch_lifecycle"]
    model_manager = SimpleNamespace(update_or_create=Mock())
    reflected_model = SimpleNamespace(save=Mock())

    def unavailable_settings() -> None:
        raise branch_lifecycle.BranchingUnavailableError(error_message)

    def fake_fetch(resource: str, *, netbox_branch_schema_id: str | None):
        model_manager.update_or_create(resource=resource)
        reflected_model.save()
        return jobs_module.CephSyncResponse(_sync_payload(resource))

    monkeypatch.setattr(jobs_module, "branching_enabled_settings", unavailable_settings)
    monkeypatch.setattr(jobs_module, "fetch_ceph_sync", fake_fetch)

    runner = _job_runner(jobs_module)
    with pytest.raises(
        branch_lifecycle.BranchingUnavailableError,
        match="runtime is unavailable",
    ) as exc_info:
        runner.run(resources=["pools"], cluster_pk=7)

    assert str(exc_info.value) == error_message
    model_manager.update_or_create.assert_not_called()
    reflected_model.save.assert_not_called()
    assert runner.job.saved_data == []


def test_ceph_sync_job_run_continues_after_stage_error_then_fails(
    monkeypatch: pytest.MonkeyPatch,
    jobs_module,
) -> None:
    calls: list[str] = []

    def fake_fetch(resource, *, scope, netbox_branch_schema_id=None, backend_context=None):
        calls.append(resource)
        if resource == "pools":
            raise jobs_module.CephBackendError("backend unavailable")
        return jobs_module.CephSyncResponse(_sync_payload(resource))

    monkeypatch.setattr(jobs_module, "branching_enabled_settings", lambda: None)
    monkeypatch.setattr(jobs_module, "fetch_ceph_sync", fake_fetch)

    runner = _job_runner(jobs_module)
    with pytest.raises(RuntimeError, match="One or more Ceph sync stages failed"):
        runner.run(resources=["pools", "osds"], cluster_pk=7)

    assert calls == ["pools", "osds"]
    stages = runner.job.data["ceph_sync"]["response"]["stages"]
    assert stages[0]["status"] == "failed"
    assert stages[0]["reason"] == "backend_error"
    assert stages[0]["error"] == "backend unavailable"
    assert stages[1]["status"] == "ok"


def test_ceph_sync_job_run_fails_for_mixed_upstream_summary_errors(
    monkeypatch: pytest.MonkeyPatch,
    jobs_module,
) -> None:
    calls: list[str] = []

    def fake_fetch(resource, *, scope, netbox_branch_schema_id=None, backend_context=None):
        calls.append(resource)
        errors = ["RuntimeError: pool query failed"] if resource == "pools" else []
        return jobs_module.CephSyncResponse(_sync_payload(resource, errors=errors))

    monkeypatch.setattr(jobs_module, "branching_enabled_settings", lambda: None)
    monkeypatch.setattr(jobs_module, "fetch_ceph_sync", fake_fetch)

    runner = _job_runner(jobs_module)
    with pytest.raises(RuntimeError, match="One or more Ceph sync stages failed"):
        runner.run(resources=["pools", "osds"], cluster_pk=7)

    assert calls == ["pools", "osds"]
    stages = runner.job.data["ceph_sync"]["response"]["stages"]
    assert [stage["status"] for stage in stages] == ["failed", "ok"]
    assert stages[0]["reason"] == "upstream_errors"
    assert stages[0]["errors"] == ["RuntimeError: pool query failed"]


def test_ceph_sync_job_summary_errors_skip_merge_and_name_open_branch(
    monkeypatch: pytest.MonkeyPatch,
    jobs_module,
) -> None:
    branch = SimpleNamespace(name="ceph-sync-101", schema_id="schema-101")
    merge_calls: list[object] = []

    monkeypatch.setattr(
        jobs_module,
        "branching_enabled_settings",
        lambda: {"prefix": "ceph-sync", "on_conflict": "fail"},
    )
    monkeypatch.setattr(
        jobs_module,
        "create_and_provision_branch",
        lambda *, name, user: branch,
    )
    monkeypatch.setattr(
        jobs_module,
        "fetch_ceph_sync",
        lambda resource, **kwargs: jobs_module.CephSyncResponse(
            _sync_payload(resource, errors=["OSError: upstream read failed"])
        ),
    )
    monkeypatch.setattr(
        jobs_module,
        "merge_branch",
        lambda **kwargs: merge_calls.append(kwargs),
    )

    runner = _job_runner(jobs_module)
    with pytest.raises(RuntimeError, match="One or more Ceph sync stages failed"):
        runner.run(resources=["pools"], cluster_pk=7)

    response = runner.job.data["ceph_sync"]["response"]
    assert response["stages"][0]["status"] == "failed"
    assert response["stages"][0]["errors"] == ["OSError: upstream read failed"]
    assert response["branch_disposition"] == {
        "status": "left_open",
        "branch_name": "ceph-sync-101",
        "reason": "ceph_sync_stage_failed",
    }
    assert merge_calls == []


def test_ceph_sync_job_malformed_summary_records_named_failure(
    monkeypatch: pytest.MonkeyPatch,
    jobs_module,
) -> None:
    def malformed(*args, **kwargs):
        raise jobs_module.CephSyncPayloadError(
            "Ceph backend returned malformed sync summary: items must be a list."
        )

    monkeypatch.setattr(jobs_module, "branching_enabled_settings", lambda: None)
    monkeypatch.setattr(jobs_module, "fetch_ceph_sync", malformed)

    runner = _job_runner(jobs_module)
    with pytest.raises(RuntimeError, match="One or more Ceph sync stages failed"):
        runner.run(resources=["pools"], cluster_pk=7)

    stage = runner.job.data["ceph_sync"]["response"]["stages"][0]
    assert stage["status"] == "failed"
    assert stage["reason"] == "malformed_summary"
    assert stage["error"] == ("Ceph backend returned malformed sync summary: items must be a list.")


def test_ceph_sync_job_scopes_every_stage_to_the_resolved_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    jobs_module,
) -> None:
    calls: list[tuple[str, int, str]] = []

    def fake_fetch(resource, *, scope, netbox_branch_schema_id=None, backend_context=None):
        calls.append((resource, scope.backend_endpoint_id, backend_context.base_url))
        return jobs_module.CephSyncResponse(_sync_payload(resource))

    monkeypatch.setattr(jobs_module, "branching_enabled_settings", lambda: None)
    monkeypatch.setattr(jobs_module, "fetch_ceph_sync", fake_fetch)

    runner = _job_runner(jobs_module)
    runner.run(resources=["pools", "osds"], cluster_pk=7)

    assert calls == [
        ("pools", 7, "https://backend.example"),
        ("osds", 7, "https://backend.example"),
    ]
    params = runner.job.data["ceph_sync"]["params"]
    assert params["proxmox_cluster_pk"] == 5
    assert params["proxmox_endpoint_pk"] == 3
    assert params["backend_endpoint_id"] == 7


def test_ceph_sync_job_unresolved_scope_fails_before_branch_or_request(
    monkeypatch: pytest.MonkeyPatch,
    jobs_module,
) -> None:
    events: list[str] = []

    def refuse(cluster_pk):
        raise jobs_module.CephSyncScopeError(
            f"Ceph sync refused: no CephCluster exists for cluster_pk={cluster_pk!r}."
        )

    monkeypatch.setattr(jobs_module, "_resolve_sync_target", refuse)
    monkeypatch.setattr(
        jobs_module, "branching_enabled_settings", lambda: events.append("branching")
    )
    monkeypatch.setattr(
        jobs_module,
        "create_and_provision_branch",
        lambda **kwargs: events.append("branch"),
    )
    monkeypatch.setattr(jobs_module, "fetch_ceph_sync", lambda *a, **k: events.append("fetch"))

    runner = _job_runner(jobs_module)
    with pytest.raises(jobs_module.CephSyncScopeError, match="cluster_pk=404"):
        runner.run(resources=["pools"], cluster_pk=404)

    assert events == []
    ceph_sync = runner.job.data["ceph_sync"]
    assert ceph_sync["params"] == {"resources": ["pools"], "cluster_pk": 404}
    assert ceph_sync["response"]["status"] == "failed"
    assert ceph_sync["response"]["reason"] == "unresolved_cluster_scope"
    assert "cluster_pk=404" in ceph_sync["response"]["error"]


def _install_cluster_model(monkeypatch: pytest.MonkeyPatch, cluster: object | None):
    models = types.ModuleType("netbox_ceph.models")

    class DoesNotExist(Exception):
        pass

    class _Query:
        def select_related(self, *fields):
            return self

        def get(self, *, pk):
            if cluster is None or getattr(cluster, "pk", None) != pk:
                raise DoesNotExist()
            return cluster

    class CephCluster:
        objects = _Query()

    CephCluster.DoesNotExist = DoesNotExist
    models.CephCluster = CephCluster
    monkeypatch.setitem(sys.modules, "netbox_ceph.models", models)


def _endpoint(pk: int = 3, *, name: str = "Lab", domain: str = "pve-a.example"):
    return SimpleNamespace(pk=pk, name=name, domain=domain, ip_address=None)


def _install_backend_sync(
    monkeypatch: pytest.MonkeyPatch,
    *,
    resolver=None,
    name_builder=None,
    module: bool = True,
):
    if not module:
        monkeypatch.setitem(sys.modules, "netbox_proxbox.views.backend_sync", None)
        return
    backend_sync = types.ModuleType("netbox_proxbox.views.backend_sync")
    if resolver is not None:
        backend_sync.resolve_backend_endpoint_id = resolver
    if name_builder is not None:
        backend_sync.proxmox_backend_name = name_builder
    netbox_proxbox = types.ModuleType("netbox_proxbox")
    netbox_proxbox.__path__ = []
    views = types.ModuleType("netbox_proxbox.views")
    views.__path__ = []
    views.backend_sync = backend_sync
    monkeypatch.setitem(sys.modules, "netbox_proxbox", netbox_proxbox)
    monkeypatch.setitem(sys.modules, "netbox_proxbox.views", views)
    monkeypatch.setitem(sys.modules, "netbox_proxbox.views.backend_sync", backend_sync)


def test_resolve_sync_target_binds_cluster_to_one_backend_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    jobs_module,
) -> None:
    endpoint = _endpoint()
    cluster = SimpleNamespace(
        pk=11, endpoint=endpoint, proxmox_cluster=SimpleNamespace(pk=5, endpoint=endpoint)
    )
    _install_cluster_model(monkeypatch, cluster)
    resolver_calls: list[dict[str, object]] = []

    def resolver(candidate, *, base_url, auth_headers, backend_verify_ssl):
        resolver_calls.append(
            {
                "endpoint": candidate,
                "base_url": base_url,
                "auth_headers": auth_headers,
                "backend_verify_ssl": backend_verify_ssl,
            }
        )
        return 42, None

    _install_backend_sync(
        monkeypatch,
        resolver=resolver,
        name_builder=lambda candidate: f"{candidate.name} (nb:{candidate.pk})",
    )
    monkeypatch.setattr(
        jobs_module,
        "resolve_ceph_backend_context",
        lambda: jobs_module.CephBackendContext(
            base_url="https://backend.example/", headers={"Authorization": "x"}, verify_ssl=False
        ),
    )

    target = jobs_module._real_resolve_sync_target(11)

    assert target.scope == jobs_module.CephSyncScope(42, "Lab (nb:3)", "pve-a.example")
    assert target.proxmox_cluster_pk == 5
    assert target.endpoint_pk == 3
    assert resolver_calls == [
        {
            "endpoint": endpoint,
            "base_url": "https://backend.example",
            "auth_headers": {"Authorization": "x"},
            "backend_verify_ssl": False,
        }
    ]


def _mismatched_cluster():
    return SimpleNamespace(
        pk=11,
        endpoint=_endpoint(pk=3),
        proxmox_cluster=SimpleNamespace(pk=5, endpoint=_endpoint(pk=4)),
    )


def _unlinked_cluster():
    return SimpleNamespace(pk=11, endpoint=_endpoint(), proxmox_cluster=None)


@pytest.mark.parametrize(
    ("cluster_pk", "cluster", "expected"),
    [
        (None, None, "cluster_pk is required"),
        (11, None, "no CephCluster exists for cluster_pk=11"),
        (11, _unlinked_cluster(), "no linked ProxmoxCluster endpoint"),
        (11, _mismatched_cluster(), "name different Proxmox endpoints"),
    ],
    ids=["missing-pk", "unknown-cluster", "unlinked", "endpoint-mismatch"],
)
def test_resolve_sync_target_refuses_before_any_backend_call(
    monkeypatch: pytest.MonkeyPatch,
    jobs_module,
    cluster_pk: object,
    cluster: object,
    expected: str,
) -> None:
    _install_cluster_model(monkeypatch, cluster)
    context_calls: list[str] = []
    monkeypatch.setattr(
        jobs_module, "resolve_ceph_backend_context", lambda: context_calls.append("context")
    )
    _install_backend_sync(monkeypatch, resolver=lambda *a, **k: context_calls.append("resolve"))

    with pytest.raises(jobs_module.CephSyncScopeError, match=expected) as excinfo:
        jobs_module._real_resolve_sync_target(cluster_pk)

    assert excinfo.value.reason == "unresolved_cluster_scope"
    assert context_calls == []


@pytest.mark.parametrize(
    ("resolver", "name_builder", "module", "expected"),
    [
        (None, None, False, "does not expose backend endpoint scope helpers"),
        (None, lambda e: "Lab", True, "typed backend endpoint scope contract"),
        (lambda *a, **k: (None, "ambiguous"), lambda e: "Lab", True, "not uniquely registered"),
        (lambda *a, **k: (None, None), lambda e: "Lab", True, "not uniquely registered"),
        (lambda *a, **k: (True, None), lambda e: "Lab", True, "not uniquely registered"),
        (lambda *a, **k: (0, None), lambda e: "Lab", True, "invalid backend endpoint id"),
        (
            lambda *a, **k: (_ for _ in ()).throw(OSError("down")),
            lambda e: "Lab",
            True,
            "could not be resolved",
        ),
    ],
    ids=["no-module", "no-resolver", "error", "none-id", "bool-id", "zero-id", "raises"],
)
def test_resolve_sync_target_refuses_unresolved_backend_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    jobs_module,
    resolver,
    name_builder,
    module: bool,
    expected: str,
) -> None:
    endpoint = _endpoint()
    cluster = SimpleNamespace(
        pk=11, endpoint=endpoint, proxmox_cluster=SimpleNamespace(pk=5, endpoint=endpoint)
    )
    _install_cluster_model(monkeypatch, cluster)
    _install_backend_sync(monkeypatch, resolver=resolver, name_builder=name_builder, module=module)
    monkeypatch.setattr(
        jobs_module,
        "resolve_ceph_backend_context",
        lambda: jobs_module.CephBackendContext(base_url="https://backend.example", headers={}),
    )

    with pytest.raises(jobs_module.CephSyncScopeError, match=expected):
        jobs_module._real_resolve_sync_target(11)


def test_resolve_sync_target_uses_ip_address_when_endpoint_has_no_domain(
    monkeypatch: pytest.MonkeyPatch,
    jobs_module,
) -> None:
    endpoint = SimpleNamespace(
        pk=3, name="Lab", domain="", ip_address=SimpleNamespace(address="192.0.2.10/24")
    )
    cluster = SimpleNamespace(
        pk=11, endpoint=endpoint, proxmox_cluster=SimpleNamespace(pk=5, endpoint=endpoint)
    )
    _install_cluster_model(monkeypatch, cluster)
    _install_backend_sync(
        monkeypatch, resolver=lambda *a, **k: (9, None), name_builder=lambda e: "Lab (nb:3)"
    )
    monkeypatch.setattr(
        jobs_module,
        "resolve_ceph_backend_context",
        lambda: jobs_module.CephBackendContext(base_url="https://backend.example", headers={}),
    )

    target = jobs_module._real_resolve_sync_target(11)

    assert target.scope.endpoint_host == "192.0.2.10"


def test_ceph_sync_job_run_creates_branch_and_reports_merge_conflict(
    monkeypatch: pytest.MonkeyPatch,
    jobs_module,
) -> None:
    branch = SimpleNamespace(name="ceph-sync-101", schema_id="schema-101")
    fetch_calls: list[tuple[str, str | None]] = []
    merge_calls: list[tuple[object, object, str]] = []

    monkeypatch.setattr(
        jobs_module,
        "branching_enabled_settings",
        lambda: {"prefix": "ceph-sync", "on_conflict": "fail"},
    )
    monkeypatch.setattr(
        jobs_module,
        "create_and_provision_branch",
        lambda *, name, user: branch,
    )

    def fake_fetch(resource, *, scope, netbox_branch_schema_id=None, backend_context=None):
        fetch_calls.append((resource, netbox_branch_schema_id))
        return jobs_module.CephSyncResponse(_sync_payload(resource))

    def fake_merge_branch(*, branch, user, on_conflict):
        merge_calls.append((branch, user, on_conflict))
        return False, "merge conflict detected"

    monkeypatch.setattr(jobs_module, "fetch_ceph_sync", fake_fetch)
    monkeypatch.setattr(jobs_module, "merge_branch", fake_merge_branch)

    runner = _job_runner(jobs_module)
    with pytest.raises(RuntimeError, match="merge conflict detected"):
        runner.run(resources=["pools"], cluster_pk=7)

    assert fetch_calls == [("pools", "schema-101")]
    assert merge_calls == [(branch, runner.job.user, "fail")]


def _scope(http_client_module, **overrides):
    # endpoint_name carries the NetBox display name exactly as netbox-proxbox's
    # proxmox_backend_name() builds it; proxbox-api never echoes it back.
    values = {
        "backend_endpoint_id": 7,
        "endpoint_name": "Lab (nb:3)",
        "endpoint_host": "pve-a.example",
    }
    values.update(overrides)
    return http_client_module.CephSyncScope(**values)


@pytest.fixture
def http_client_module(monkeypatch: pytest.MonkeyPatch):
    netbox_proxbox = types.ModuleType("netbox_proxbox")
    netbox_proxbox.__path__ = []
    services = types.ModuleType("netbox_proxbox.services")
    backend_context = types.ModuleType("netbox_proxbox.services.backend_context")
    backend_context.get_fastapi_request_context = lambda: SimpleNamespace(
        http_url="https://proxbox-api.example",
        headers={"Authorization": "Bearer hidden"},
        verify_ssl=False,
    )
    monkeypatch.setitem(sys.modules, "netbox_proxbox", netbox_proxbox)
    monkeypatch.setitem(sys.modules, "netbox_proxbox.services", services)
    monkeypatch.setitem(
        sys.modules,
        "netbox_proxbox.services.backend_context",
        backend_context,
    )
    return _load_module(
        "tests._netbox_ceph_http_client_under_test",
        "netbox_ceph/services/http_client.py",
    )


class _Response:
    def __init__(self, status_code: int, payload=None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


@pytest.mark.parametrize("status_code", [302, 500])
def test_get_json_rejects_non_2xx_without_raw_error_body(
    monkeypatch: pytest.MonkeyPatch,
    http_client_module,
    status_code: int,
) -> None:
    monkeypatch.setattr(
        http_client_module.requests,
        "get",
        lambda *args, **kwargs: _Response(
            status_code,
            payload=_sync_payload("full"),
            text="traceback with admin_key = super-secret",
        ),
    )

    with pytest.raises(http_client_module.CephBackendError) as excinfo:
        http_client_module._get_json("ceph/sync/full")

    message = str(excinfo.value)
    assert type(excinfo.value) is http_client_module.CephBackendError
    assert message == f"Ceph backend returned HTTP {status_code} for ceph/sync/full."
    assert "super-secret" not in message
    assert "traceback" not in message


def test_get_json_maps_request_failure_non_json_and_bad_shape(
    monkeypatch: pytest.MonkeyPatch,
    http_client_module,
) -> None:
    def timeout(*args, **kwargs):
        raise http_client_module.requests.Timeout("timed out")

    monkeypatch.setattr(http_client_module.requests, "get", timeout)
    with pytest.raises(http_client_module.CephBackendError, match="request failed"):
        http_client_module._get_json("ceph/sync/full")

    monkeypatch.setattr(
        http_client_module.requests,
        "get",
        lambda *args, **kwargs: _Response(200, payload=ValueError("not json")),
    )
    with pytest.raises(
        http_client_module.CephSyncPayloadError,
        match="non-JSON body",
    ) as excinfo:
        http_client_module._get_json("ceph/sync/full")
    assert excinfo.value.reason == "malformed_summary"

    with pytest.raises(http_client_module.CephBackendError, match="non-JSON body") as excinfo:
        http_client_module._get_json("ceph/status")
    assert type(excinfo.value) is http_client_module.CephBackendError

    monkeypatch.setattr(
        http_client_module.requests,
        "get",
        lambda *args, **kwargs: _Response(200, payload=["not", "an", "object"]),
    )
    with pytest.raises(
        http_client_module.CephSyncPayloadError,
        match="unexpected payload shape",
    ) as excinfo:
        http_client_module._get_json("ceph/sync/full")
    assert excinfo.value.reason == "malformed_summary"


def test_fetch_ceph_sync_validates_resource_and_passes_branch_param(
    monkeypatch: pytest.MonkeyPatch,
    http_client_module,
) -> None:
    captured: dict[str, object] = {}

    def fake_get_json(path, *, params=None, backend_context=None):
        captured["path"] = path
        captured["params"] = params
        captured["backend_context"] = backend_context
        return _sync_payload("pools")

    monkeypatch.setattr(http_client_module, "_get_json", fake_get_json)
    context = http_client_module.CephBackendContext(base_url="https://backend.example", headers={})

    response = http_client_module.fetch_ceph_sync(
        "pools",
        scope=_scope(http_client_module),
        netbox_branch_schema_id="branch-1",
        backend_context=context,
    )
    assert response.as_payload() == _sync_payload("pools")
    assert captured == {
        "path": "ceph/sync/pools",
        "params": {"proxmox_endpoint_ids": "7", "netbox_branch_schema_id": "branch-1"},
        "backend_context": context,
    }

    with pytest.raises(ValueError, match="Unknown Ceph sync resource"):
        http_client_module.fetch_ceph_sync("bad-resource", scope=_scope(http_client_module))


@pytest.mark.parametrize("backend_endpoint_id", [0, -1, True, "7"])
def test_fetch_ceph_sync_refuses_unscoped_request(
    monkeypatch: pytest.MonkeyPatch,
    http_client_module,
    backend_endpoint_id: object,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(http_client_module, "_get_json", lambda path, **kwargs: calls.append(path))

    with pytest.raises(ValueError, match="positive backend Proxmox endpoint id"):
        http_client_module.fetch_ceph_sync(
            "pools",
            scope=_scope(http_client_module, backend_endpoint_id=backend_endpoint_id),
        )

    assert calls == []


def test_fetch_ceph_sync_returns_typed_summaries_and_collects_errors(
    monkeypatch: pytest.MonkeyPatch,
    http_client_module,
) -> None:
    payload = {
        "items": [
            _summary_payload(
                "pools",
                errors=["OSError: pve-a failed", "TimeoutError: pve-a mon down"],
                name="pve-a",
            ),
        ],
        "raw": {"resource": "pools"},
    }
    monkeypatch.setattr(http_client_module, "_get_json", lambda *args, **kwargs: payload)

    response = http_client_module.fetch_ceph_sync("pools", scope=_scope(http_client_module))

    assert all(
        isinstance(summary, http_client_module.CephSyncSummary) for summary in response.items
    )
    assert response.errors == ["OSError: pve-a failed", "TimeoutError: pve-a mon down"]
    assert response.as_payload() == payload


@pytest.mark.parametrize(
    ("items", "expected"),
    [
        (
            [_summary_payload("pools", name="pve-a"), _summary_payload("pools", name="pve-b")],
            "items must contain exactly one summary for endpoint 'Lab (nb:3)'; got 2",
        ),
        (
            [{**_summary_payload("pools", name="pve-b"), "host": "pve-b.example"}],
            "items[0].host must match requested endpoint host 'pve-a.example'; got 'pve-b.example' "
            "(session 'pve-b', endpoint 'Lab (nb:3)')",
        ),
        ([], "items must contain exactly one summary for endpoint 'Lab (nb:3)'; got 0"),
    ],
    ids=["fan-out", "other-endpoint", "empty"],
)
def test_fetch_ceph_sync_rejects_summary_outside_requested_scope(
    monkeypatch: pytest.MonkeyPatch,
    http_client_module,
    items: list[object],
    expected: str,
) -> None:
    payload = {"items": items, "raw": None}
    monkeypatch.setattr(http_client_module, "_get_json", lambda *args, **kwargs: payload)

    with pytest.raises(http_client_module.CephSyncPayloadError) as excinfo:
        http_client_module.fetch_ceph_sync("pools", scope=_scope(http_client_module))

    assert excinfo.value.reason == "malformed_summary"
    assert expected in str(excinfo.value)


@pytest.mark.parametrize(
    "session_name",
    ["pve-a.example", "lab-cluster", "pve-a", "192.0.2.10"],
    ids=["domain", "cluster-name", "node-name", "ip"],
)
def test_fetch_ceph_sync_accepts_backend_session_names_that_differ_from_netbox(
    monkeypatch: pytest.MonkeyPatch,
    http_client_module,
    session_name: str,
) -> None:
    """proxbox-api names sessions after domain/IP/cluster/node, never the NetBox name."""

    payload = {"items": [_summary_payload("pools", name=session_name)], "raw": None}
    monkeypatch.setattr(http_client_module, "_get_json", lambda *args, **kwargs: payload)

    response = http_client_module.fetch_ceph_sync("pools", scope=_scope(http_client_module))

    assert response.items[0].name == session_name


def test_fetch_ceph_sync_scope_host_match_ignores_case_and_trailing_dot(
    monkeypatch: pytest.MonkeyPatch,
    http_client_module,
) -> None:
    payload = {"items": [{**_summary_payload("pools"), "host": "PVE-A.example."}], "raw": None}
    monkeypatch.setattr(http_client_module, "_get_json", lambda *args, **kwargs: payload)

    response = http_client_module.fetch_ceph_sync("pools", scope=_scope(http_client_module))

    assert response.items[0].host == "PVE-A.example."


def test_fetch_ceph_sync_rejects_summary_for_another_resource(
    monkeypatch: pytest.MonkeyPatch,
    http_client_module,
) -> None:
    payload = {
        "items": [
            _summary_payload("pools", name="pve-a"),
            _summary_payload("osds", name="pve-b"),
        ],
        "raw": None,
    }
    monkeypatch.setattr(
        http_client_module,
        "_get_json",
        lambda *args, **kwargs: payload,
    )

    with pytest.raises(http_client_module.CephSyncPayloadError) as excinfo:
        http_client_module.fetch_ceph_sync("pools", scope=_scope(http_client_module))

    assert excinfo.value.reason == "malformed_summary"
    assert "items[1].resource must match requested resource 'pools'; got 'osds'" in str(
        excinfo.value
    )


@pytest.mark.parametrize(
    ("response", "expected_reason", "error_fragment"),
    [
        (_Response(302, payload=_sync_payload("pools")), "backend_error", "HTTP 302"),
        (
            _Response(200, payload=_sync_payload("osds")),
            "malformed_summary",
            "requested resource 'pools'; got 'osds'",
        ),
    ],
)
def test_ceph_sync_job_rejects_invalid_http_evidence_before_merge(
    monkeypatch: pytest.MonkeyPatch,
    jobs_module,
    http_client_module,
    response: _Response,
    expected_reason: str,
    error_fragment: str,
) -> None:
    _, merge_calls = _configure_isolated_job(monkeypatch, jobs_module)
    _wire_http_client_to_job(monkeypatch, jobs_module, http_client_module)
    monkeypatch.setattr(
        http_client_module.requests,
        "get",
        lambda *args, **kwargs: response,
    )

    runner = _job_runner(jobs_module)
    with pytest.raises(RuntimeError, match="One or more Ceph sync stages failed"):
        runner.run(resources=["pools"], cluster_pk=7)

    assert runner.job.saved_data[-1] is runner.job.data
    saved_response = runner.job.saved_data[-1]["ceph_sync"]["response"]
    stage = saved_response["stages"][0]
    assert stage["resource"] == "pools"
    assert stage["status"] == "failed"
    assert stage["reason"] == expected_reason
    assert error_fragment in stage["error"]
    assert saved_response["branch_disposition"] == {
        "status": "left_open",
        "branch_name": "ceph-sync-101",
        "reason": "ceph_sync_stage_failed",
    }
    assert merge_calls == []


@pytest.mark.parametrize("with_isolation", [False, True])
def test_ceph_sync_job_non_json_200_is_malformed_and_never_merges(
    monkeypatch: pytest.MonkeyPatch,
    jobs_module,
    http_client_module,
    with_isolation: bool,
) -> None:
    merge_calls: list[object] = []
    if with_isolation:
        _, merge_calls = _configure_isolated_job(monkeypatch, jobs_module)
    else:
        monkeypatch.setattr(jobs_module, "branching_enabled_settings", lambda: None)
    _wire_http_client_to_job(monkeypatch, jobs_module, http_client_module)
    monkeypatch.setattr(
        http_client_module.requests,
        "get",
        lambda *args, **kwargs: _Response(200, payload=ValueError("not json")),
    )

    runner = _job_runner(jobs_module)
    with pytest.raises(RuntimeError, match="One or more Ceph sync stages failed"):
        runner.run(resources=["pools"], cluster_pk=7)

    assert runner.job.saved_data[-1] is runner.job.data
    saved_response = runner.job.saved_data[-1]["ceph_sync"]["response"]
    stage = saved_response["stages"][0]
    assert stage["resource"] == "pools"
    assert stage["status"] == "failed"
    assert stage["reason"] == "malformed_summary"
    assert "non-JSON body for ceph/sync/pools" in stage["error"]
    if with_isolation:
        assert saved_response["branch_disposition"] == {
            "status": "left_open",
            "branch_name": "ceph-sync-101",
            "reason": "ceph_sync_stage_failed",
        }
    else:
        assert "branch_disposition" not in saved_response
    assert merge_calls == []


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({}, "items"),
        ({"items": "not-a-list"}, "items"),
        ({"items": ["not-an-object"]}, "items[0]"),
        (
            {"items": [{**_summary_payload("pools"), "fetched": -1}]},
            "items[0].fetched",
        ),
        (
            {"items": [{**_summary_payload("pools"), "errors": "not-a-list"}]},
            "items[0].errors",
        ),
    ],
)
def test_fetch_ceph_sync_rejects_malformed_summary_shape(
    monkeypatch: pytest.MonkeyPatch,
    http_client_module,
    payload: object,
    field: str,
) -> None:
    monkeypatch.setattr(http_client_module, "_get_json", lambda *args, **kwargs: payload)

    with pytest.raises(http_client_module.CephSyncPayloadError) as excinfo:
        http_client_module.fetch_ceph_sync("pools", scope=_scope(http_client_module))

    assert excinfo.value.reason == "malformed_summary"
    assert field in str(excinfo.value)


@pytest.fixture
def branch_lifecycle_module(monkeypatch: pytest.MonkeyPatch):
    settings_holder = SimpleNamespace(
        settings=SimpleNamespace(
            branching_enabled=True,
            branch_name_prefix="review-sync",
            branch_on_conflict="acknowledge",
        )
    )

    models = types.ModuleType("netbox_ceph.models")

    class CephPluginSettings:
        @classmethod
        def get_solo(cls):
            return settings_holder.settings

    models.CephPluginSettings = CephPluginSettings
    monkeypatch.setitem(sys.modules, "netbox_ceph.models", models)

    netbox_proxbox = types.ModuleType("netbox_proxbox")
    netbox_proxbox.__path__ = []
    services = types.ModuleType("netbox_proxbox.services")
    lifecycle = SimpleNamespace(
        is_branching_available=lambda: True,
        get_active_branch_schema_id=lambda: "active-schema",
        create_and_provision_branch=lambda **kwargs: {"created": kwargs},
        branch_has_conflicts=lambda branch: branch == "conflicted",
        merge_branch=lambda **kwargs: (True, f"merged {kwargs['branch']}"),
    )
    services.branch_lifecycle = lifecycle
    monkeypatch.setitem(sys.modules, "netbox_proxbox", netbox_proxbox)
    monkeypatch.setitem(sys.modules, "netbox_proxbox.services", services)

    module = _load_module(
        "tests._netbox_ceph_branch_lifecycle_under_test",
        "netbox_ceph/services/branch_lifecycle.py",
    )
    module._settings_holder = settings_holder
    return module


def test_branching_enabled_settings_reads_ceph_settings(branch_lifecycle_module) -> None:
    assert branch_lifecycle_module.branching_enabled_settings() == {
        "prefix": "review-sync",
        "on_conflict": "acknowledge",
    }

    branch_lifecycle_module._settings_holder.settings.branching_enabled = False
    assert branch_lifecycle_module.branching_enabled_settings() is None


def test_enabled_branching_fails_closed_when_runtime_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    branch_lifecycle_module,
) -> None:
    monkeypatch.setattr(
        branch_lifecycle_module,
        "_proxbox_branch_lifecycle",
        lambda: SimpleNamespace(is_branching_available=lambda: False),
    )

    with pytest.raises(
        branch_lifecycle_module.BranchingUnavailableError,
        match="runtime is unavailable",
    ):
        branch_lifecycle_module.branching_enabled_settings()


def test_unreadable_branching_setting_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    branch_lifecycle_module,
) -> None:
    def fail_settings_read():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        branch_lifecycle_module.CephPluginSettings,
        "get_solo",
        fail_settings_read,
    )

    with pytest.raises(
        branch_lifecycle_module.BranchingUnavailableError,
        match="branching_enabled could not be read.*database unavailable",
    ):
        branch_lifecycle_module.branching_enabled_settings()


def test_branch_lifecycle_delegates_to_proxbox_helpers(branch_lifecycle_module) -> None:
    assert branch_lifecycle_module.is_branching_available() is True
    assert branch_lifecycle_module.get_active_branch_schema_id() == "active-schema"
    assert branch_lifecycle_module.create_and_provision_branch(
        name="ceph-sync-1",
        user=None,
    ) == {"created": {"name": "ceph-sync-1", "user": None, "ready_timeout_seconds": 60}}
    assert branch_lifecycle_module.branch_has_conflicts("conflicted") is True
    assert branch_lifecycle_module.merge_branch(
        branch="ceph-sync-1",
        user=None,
        on_conflict="fail",
    ) == (True, "merged ceph-sync-1")


@pytest.fixture
def api_views_module(monkeypatch: pytest.MonkeyPatch):  # noqa: C901
    rest_framework = types.ModuleType("rest_framework")
    status_mod = types.ModuleType("rest_framework.status")
    status_mod.HTTP_202_ACCEPTED = 202
    status_mod.HTTP_400_BAD_REQUEST = 400
    status_mod.HTTP_403_FORBIDDEN = 403
    status_mod.HTTP_409_CONFLICT = 409
    status_mod.HTTP_502_BAD_GATEWAY = 502
    status_mod.HTTP_503_SERVICE_UNAVAILABLE = 503
    rest_framework.status = status_mod
    monkeypatch.setitem(sys.modules, "rest_framework", rest_framework)
    monkeypatch.setitem(sys.modules, "rest_framework.status", status_mod)

    decorators = types.ModuleType("rest_framework.decorators")

    def action(*, detail, methods, **kwargs):
        def decorator(func):
            func.detail = detail
            func.methods = tuple(methods)
            return func

        return decorator

    decorators.action = action
    monkeypatch.setitem(sys.modules, "rest_framework.decorators", decorators)

    exceptions = types.ModuleType("rest_framework.exceptions")

    class MethodNotAllowed(Exception):
        pass

    class PermissionDenied(Exception):
        pass

    exceptions.MethodNotAllowed = MethodNotAllowed
    exceptions.PermissionDenied = PermissionDenied
    monkeypatch.setitem(sys.modules, "rest_framework.exceptions", exceptions)

    response_mod = types.ModuleType("rest_framework.response")

    class Response:
        def __init__(self, data=None, status=None):
            self.data = data
            self.status_code = status

    response_mod.Response = Response
    monkeypatch.setitem(sys.modules, "rest_framework.response", response_mod)

    netbox = types.ModuleType("netbox")
    netbox.__path__ = []
    netbox_api = types.ModuleType("netbox.api")
    netbox_api.__path__ = []
    authentication = types.ModuleType("netbox.api.authentication")
    netbox_plugins = types.ModuleType("netbox.plugins")
    viewsets = types.ModuleType("netbox.api.viewsets")

    class TokenPermissions:
        def has_permission(self, request, view):
            return True

        def has_object_permission(self, request, view, obj):
            return True

        def _verify_write_permission(self, request):
            return True

    class NetBoxModelViewSet:
        def get_serializer_context(self):
            return {}

    class PluginConfig:
        def ready(self):
            return None

    netbox_plugins.PluginConfig = PluginConfig
    authentication.TokenPermissions = TokenPermissions
    viewsets.NetBoxModelViewSet = NetBoxModelViewSet
    monkeypatch.setitem(sys.modules, "netbox", netbox)
    monkeypatch.setitem(sys.modules, "netbox.api", netbox_api)
    monkeypatch.setitem(sys.modules, "netbox.api.authentication", authentication)
    monkeypatch.setitem(sys.modules, "netbox.plugins", netbox_plugins)
    monkeypatch.setitem(sys.modules, "netbox.api.viewsets", viewsets)

    users = types.ModuleType("users")
    users.__path__ = []
    user_models = types.ModuleType("users.models")

    class Token:
        pass

    user_models.Token = Token
    monkeypatch.setitem(sys.modules, "users", users)
    monkeypatch.setitem(sys.modules, "users.models", user_models)

    class _Manager:
        def all(self):
            return self

        def select_related(self, *args):
            return self

    def model(name: str):
        return type(name, (), {"objects": _Manager()})

    model_names = [
        "CephCluster",
        "CephCrushRule",
        "CephDaemon",
        "CephDriftRecord",
        "CephFilesystem",
        "CephFilesystemDesiredState",
        "CephFlag",
        "CephHealthCheck",
        "CephMetricSnapshot",
        "CephOperation",
        "CephOperationApproval",
        "CephOperationRun",
        "CephOSD",
        "CephPlan",
        "CephPluginSettings",
        "CephPool",
        "CephPoolDesiredState",
        "CephProvider",
        "CephRBDClone",
        "CephRBDImage",
        "CephRBDImageDesiredState",
        "CephRBDSnapshot",
        "CephRBDSnapshotDesiredState",
        "CephRGWBucketDesiredState",
        "CephRGWBucketReflected",
        "CephRGWPlacementTarget",
        "CephRGWRealm",
        "CephRGWRealmDesiredState",
        "CephRGWUserDesiredState",
        "CephRGWUserReflected",
        "CephRGWZone",
        "CephRGWZoneDesiredState",
        "CephRGWZoneGroup",
        "CephValidationResult",
    ]
    models = types.ModuleType("netbox_ceph.models")
    for name in model_names:
        setattr(models, name, model(name))
    monkeypatch.setitem(sys.modules, "netbox_ceph.models", models)

    filtersets = types.ModuleType("netbox_ceph.filtersets")
    serializers = types.ModuleType("netbox_ceph.api.serializers")

    class _Serializer:
        def __init__(self, *args, **kwargs):
            self.data = {"serialized": True}

    for name in model_names:
        setattr(serializers, f"{name}Serializer", _Serializer)
        setattr(filtersets, f"{name}FilterSet", type(f"{name}FilterSet", (), {}))
    monkeypatch.setitem(sys.modules, "netbox_ceph.filtersets", filtersets)
    monkeypatch.setitem(sys.modules, "netbox_ceph.api.serializers", serializers)

    operation_actions = types.ModuleType("netbox_ceph.services.operation_actions")

    class OperationActionError(Exception):
        def __init__(self, message="", kind="backend", run=None):
            super().__init__(message)
            self.message = message
            self.kind = kind
            self.run = run

    operation_actions.OperationActionError = OperationActionError
    operation_actions.approve_and_apply_operation = lambda *args, **kwargs: None
    operation_actions.apply_operation = lambda *args, **kwargs: None
    operation_actions.plan_operation = lambda *args, **kwargs: None
    operation_actions.reconcile_provider = lambda *args, **kwargs: None
    monkeypatch.setitem(
        sys.modules,
        "netbox_ceph.services.operation_actions",
        operation_actions,
    )

    jobs = types.ModuleType("netbox_ceph.jobs")
    jobs.CEPH_SYNC_QUEUE_NAME = "default"
    jobs.enqueue_calls = []

    class CephSyncJob:
        @classmethod
        def enqueue(cls, **kwargs):
            jobs.enqueue_calls.append(kwargs)
            if kwargs.get("resources") == "bad":
                raise ValueError("Cannot enqueue CephSyncJob: bad resource")
            return SimpleNamespace(
                pk=555,
                data={
                    "ceph_sync": {
                        "params": {
                            "cluster_pk": kwargs["cluster_pk"],
                            "resources": ["pools", "osds"],
                        }
                    }
                },
                get_absolute_url=lambda: "/core/jobs/555/",
            )

    jobs.CephSyncJob = CephSyncJob
    monkeypatch.setitem(sys.modules, "netbox_ceph.jobs", jobs)

    module = _load_module(
        "tests._netbox_ceph_api_views_under_test",
        "netbox_ceph/api/views.py",
    )
    module._jobs_stub = jobs
    return module


class _Cluster:
    pk = 7

    def __str__(self):
        return "ceph-a"


def test_cluster_sync_action_enqueues_job_without_instance(api_views_module) -> None:
    viewset = api_views_module.CephClusterViewSet()
    viewset.get_object = lambda: _Cluster()
    request = SimpleNamespace(
        data={"resources": "pools,osds"},
        user=SimpleNamespace(is_authenticated=True, username="operator"),
    )

    response = viewset.sync(request, pk=7)

    assert response.status_code == 202
    assert response.data == {
        "job": 555,
        "cluster": 7,
        "resources": ["pools", "osds"],
        "url": "/core/jobs/555/",
    }
    assert api_views_module._jobs_stub.enqueue_calls == [
        {
            "user": request.user,
            "queue_name": "default",
            "name": "Ceph Sync: ceph-a",
            "cluster_pk": 7,
            "resources": "pools,osds",
        }
    ]
    assert "instance" not in api_views_module._jobs_stub.enqueue_calls[0]
    assert "post" in api_views_module.CephClusterViewSet.http_method_names


def test_cluster_sync_action_returns_400_for_invalid_resources(api_views_module) -> None:
    viewset = api_views_module.CephClusterViewSet()
    viewset.get_object = lambda: _Cluster()
    request = SimpleNamespace(data={"resources": "bad"}, user=None)

    response = viewset.sync(request, pk=7)

    assert response.status_code == 400
    assert response.data == {"detail": "Cannot enqueue CephSyncJob: bad resource"}


def test_cluster_list_post_remains_disabled(api_views_module) -> None:
    with pytest.raises(api_views_module.MethodNotAllowed):
        api_views_module.CephClusterViewSet().create(SimpleNamespace())
