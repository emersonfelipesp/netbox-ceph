"""Tests for the v1 Ceph reflection sync job and dispatch surface."""

from __future__ import annotations

import importlib.util
import logging
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_module(module_name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
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

    http_client.CephBackendError = CephBackendError
    http_client.fetch_ceph_sync = lambda *args, **kwargs: {}
    monkeypatch.setitem(sys.modules, "netbox_ceph.services.http_client", http_client)

    return _load_module("tests._netbox_ceph_jobs_under_test", "netbox_ceph/jobs.py")


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
    runner.job = SimpleNamespace(
        pk=101,
        user=SimpleNamespace(username="operator"),
        data=None,
        save=lambda update_fields=None: None,
    )
    return runner


def test_ceph_sync_job_run_records_successful_stages(
    monkeypatch: pytest.MonkeyPatch,
    jobs_module,
) -> None:
    calls: list[tuple[str, str | None]] = []

    def fake_fetch(resource, *, netbox_branch_schema_id=None):
        calls.append((resource, netbox_branch_schema_id))
        return {"resource": resource, "ok": True}

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


def test_ceph_sync_job_run_continues_after_stage_error_then_fails(
    monkeypatch: pytest.MonkeyPatch,
    jobs_module,
) -> None:
    calls: list[str] = []

    def fake_fetch(resource, *, netbox_branch_schema_id=None):
        calls.append(resource)
        if resource == "pools":
            raise jobs_module.CephBackendError("backend unavailable")
        return {"resource": resource, "ok": True}

    monkeypatch.setattr(jobs_module, "branching_enabled_settings", lambda: None)
    monkeypatch.setattr(jobs_module, "fetch_ceph_sync", fake_fetch)

    runner = _job_runner(jobs_module)
    with pytest.raises(RuntimeError, match="One or more Ceph sync stages failed"):
        runner.run(resources=["pools", "osds"], cluster_pk=7)

    assert calls == ["pools", "osds"]
    stages = runner.job.data["ceph_sync"]["response"]["stages"]
    assert stages[0]["status"] == "error"
    assert stages[0]["error"] == "backend unavailable"
    assert stages[1]["status"] == "ok"


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

    def fake_fetch(resource, *, netbox_branch_schema_id=None):
        fetch_calls.append((resource, netbox_branch_schema_id))
        return {"ok": True}

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


def test_get_json_strips_raw_error_body(
    monkeypatch: pytest.MonkeyPatch,
    http_client_module,
) -> None:
    monkeypatch.setattr(
        http_client_module.requests,
        "get",
        lambda *args, **kwargs: _Response(
            500,
            text="traceback with admin_key = super-secret",
        ),
    )

    with pytest.raises(http_client_module.CephBackendError) as excinfo:
        http_client_module._get_json("ceph/sync/full")

    message = str(excinfo.value)
    assert message == "Ceph backend returned HTTP 500 for ceph/sync/full."
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
    with pytest.raises(http_client_module.CephBackendError, match="non-JSON body"):
        http_client_module._get_json("ceph/sync/full")

    monkeypatch.setattr(
        http_client_module.requests,
        "get",
        lambda *args, **kwargs: _Response(200, payload=["not", "an", "object"]),
    )
    with pytest.raises(http_client_module.CephBackendError, match="unexpected payload shape"):
        http_client_module._get_json("ceph/sync/full")


def test_fetch_ceph_sync_validates_resource_and_passes_branch_param(
    monkeypatch: pytest.MonkeyPatch,
    http_client_module,
) -> None:
    captured: dict[str, object] = {}

    def fake_get_json(path, *, params=None):
        captured["path"] = path
        captured["params"] = params
        return {"ok": True}

    monkeypatch.setattr(http_client_module, "_get_json", fake_get_json)

    assert http_client_module.fetch_ceph_sync(
        "pools",
        netbox_branch_schema_id="branch-1",
    ) == {"ok": True}
    assert captured == {
        "path": "ceph/sync/pools",
        "params": {"netbox_branch_schema_id": "branch-1"},
    }

    with pytest.raises(ValueError, match="Unknown Ceph sync resource"):
        http_client_module.fetch_ceph_sync("bad-resource")


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
