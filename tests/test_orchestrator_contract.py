"""Dependency-isolated tests for the Ceph v2 orchestrator HTTP contract."""

from __future__ import annotations

import logging
import sys
import traceback
import types
from types import SimpleNamespace

import pytest
import requests


class _EndpointQuery:
    def filter(self, **kwargs):
        return self

    def order_by(self, *args):
        return self

    def values_list(self, *args, **kwargs):
        return [1]


netbox_proxbox = types.ModuleType("netbox_proxbox")
netbox_proxbox.__path__ = []
proxbox_models = types.ModuleType("netbox_proxbox.models")
proxbox_models.FastAPIEndpoint = type(
    "FastAPIEndpoint",
    (),
    {"objects": _EndpointQuery()},
)
proxbox_services = types.ModuleType("netbox_proxbox.services")
proxbox_services.__path__ = []
backend_context = types.ModuleType("netbox_proxbox.services.backend_context")
backend_context.get_fastapi_request_context = lambda endpoint_id=None: None
proxbox_views = types.ModuleType("netbox_proxbox.views")
proxbox_views.__path__ = []
backend_sync = types.ModuleType("netbox_proxbox.views.backend_sync")
backend_sync.resolve_backend_endpoint_id = lambda *args, **kwargs: (41, None)
sys.modules.setdefault("netbox_proxbox", netbox_proxbox)
sys.modules.setdefault("netbox_proxbox.models", proxbox_models)
sys.modules.setdefault("netbox_proxbox.services", proxbox_services)
sys.modules.setdefault("netbox_proxbox.services.backend_context", backend_context)
sys.modules.setdefault("netbox_proxbox.views", proxbox_views)
sys.modules.setdefault("netbox_proxbox.views.backend_sync", backend_sync)

from netbox_ceph.services import orchestrator  # noqa: E402


class _Response:
    def __init__(self, status_code: int, payload: dict | list | None = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


def _context(endpoint_id=None):
    assert endpoint_id == 1
    return SimpleNamespace(
        http_url="https://proxbox-api.example",
        headers={"Authorization": "Bearer opaque"},
        verify_ssl=False,
    )


@pytest.fixture(autouse=True)
def exact_backend(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(orchestrator, "_enabled_fastapi_endpoint_ids", lambda: [1])
    monkeypatch.setattr(orchestrator, "get_fastapi_request_context", _context)


def test_backend_capabilities_use_exact_configured_fastapi_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return _Response(200, {"providers": [{"provider": "proxmox", "apply": False}]})

    monkeypatch.setattr(orchestrator.requests, "request", fake_request)
    payload = orchestrator.CephOrchestratorClient().backend_capabilities(endpoint_id=41)

    assert payload["providers"][0]["apply"] is False
    assert calls[0][0] == "get"
    assert calls[0][1] == "https://proxbox-api.example/ceph/v2/capabilities"
    assert calls[0][2]["headers"] == {"Authorization": "Bearer opaque"}
    assert calls[0][2]["params"] == {"provider": "proxmox", "endpoint_id": 41}
    assert calls[0][2]["verify"] is False


def test_plan_returns_original_body_but_logs_only_redacted_copy(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return _Response(200, {"id": "plan-1", "secret_token": "response-canary"})

    monkeypatch.setattr(orchestrator.requests, "request", fake_request)
    caplog.set_level(logging.DEBUG, logger="netbox_ceph.orchestrator")
    payload = orchestrator.CephOrchestratorClient().plan(
        {"endpoint_id": 41, "desired": {"password": "request-canary"}},
        actor="requester",
    )

    assert calls[0][0] == "post"
    assert calls[0][1] == "https://proxbox-api.example/ceph/v2/plans"
    assert calls[0][2]["headers"]["X-Proxbox-Actor"] == "requester"
    assert calls[0][2]["json"]["desired"]["password"] == "request-canary"
    assert payload["secret_token"] == "response-canary"
    assert "request-canary" not in caplog.text
    assert "response-canary" not in caplog.text


def test_approval_token_is_transient_response_data_and_never_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        orchestrator.requests,
        "request",
        lambda *args, **kwargs: _Response(
            201,
            {"id": "approval-1", "token": "one-time-canary"},
        ),
    )
    caplog.set_level(logging.DEBUG, logger="netbox_ceph.orchestrator")

    payload = orchestrator.CephOrchestratorClient().approve(
        "plan-1",
        endpoint_id=41,
        actor="approver",
    )

    assert payload["token"] == "one-time-canary"
    assert "one-time-canary" not in caplog.text


def test_replay_error_preserves_only_safe_recovery_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approval_id = "8d214f39-a51c-466b-8b6f-ab95f253b8e7"
    operation_run_id = "cf75a2b5-e394-46c6-af55-b97cae765178"
    monkeypatch.setattr(
        orchestrator.requests,
        "request",
        lambda *args, **kwargs: _Response(
            409,
            {
                "detail": {
                    "reason": "approval_replayed",
                    "operation_run_id": operation_run_id,
                    "approval_id": approval_id,
                    "approval_token": "must-not-escape",
                    "detail": "upstream supplied text must not be trusted",
                }
            },
        ),
    )

    with pytest.raises(orchestrator.CephOrchestratorHTTPError) as excinfo:
        orchestrator.CephOrchestratorClient().apply(
            "plan-1",
            endpoint_id=41,
            approval_token="one-time-canary",
            actor="requester",
        )

    assert excinfo.value.status_code == 409
    assert excinfo.value.reason == "approval_replayed"
    assert excinfo.value.recovery == {
        "approval_id": approval_id,
        "operation_run_id": operation_run_id,
    }
    assert "must-not-escape" not in str(excinfo.value)
    assert "upstream supplied" not in str(excinfo.value)


@pytest.mark.parametrize(
    "unsafe_value",
    [
        "../runs/1",
        "/api/ceph/v2/operations/1",
        "not-a-uuid",
        "a" * 4096,
        "Bearer RECOVERY-CANARY",
    ],
)
def test_replay_error_discards_unsafe_recovery_identifiers(
    monkeypatch: pytest.MonkeyPatch,
    unsafe_value: str,
) -> None:
    monkeypatch.setattr(
        orchestrator.requests,
        "request",
        lambda *args, **kwargs: _Response(
            409,
            {
                "detail": {
                    "reason": "approval_replayed",
                    "operation_run_id": unsafe_value,
                    "approval_id": unsafe_value,
                }
            },
        ),
    )

    with pytest.raises(orchestrator.CephOrchestratorHTTPError) as excinfo:
        orchestrator.CephOrchestratorClient().apply(
            "plan-1",
            endpoint_id=41,
            approval_token="one-time-canary",
            actor="requester",
        )

    assert excinfo.value.recovery == {}
    assert unsafe_value not in str(excinfo.value)


@pytest.mark.parametrize("status_code", [404, 501])
def test_missing_route_statuses_raise_unsupported(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    payload = {"detail": "Not Found"} if status_code == 404 else {}
    monkeypatch.setattr(
        orchestrator.requests,
        "request",
        lambda *args, **kwargs: _Response(status_code, payload),
    )

    with pytest.raises(orchestrator.CephOrchestratorUnsupported):
        orchestrator.CephOrchestratorClient().backend_capabilities()


def test_timeout_is_distinct_from_known_backend_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_request(*args, **kwargs):
        raise requests.Timeout("canary-timeout")

    monkeypatch.setattr(orchestrator.requests, "request", fake_request)

    with pytest.raises(orchestrator.CephOrchestratorTimeout) as excinfo:
        orchestrator.CephOrchestratorClient().operation("run-1")
    assert "canary-timeout" not in str(excinfo.value)


def test_multiple_fastapi_endpoints_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator, "_enabled_fastapi_endpoint_ids", lambda: [1, 2])
    with pytest.raises(orchestrator.CephOrchestratorUnavailable, match="multiple"):
        orchestrator.CephOrchestratorClient().backend_capabilities()


def test_plugin_endpoint_is_translated_to_backend_database_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    def resolve(endpoint, **kwargs):
        captured.update(kwargs)
        assert endpoint.pk == 9
        return 41, None

    monkeypatch.setattr(orchestrator, "resolve_proxbox_backend_endpoint_id", resolve)
    endpoint_id = orchestrator.CephOrchestratorClient().resolve_backend_endpoint_id(
        SimpleNamespace(pk=9)
    )

    assert endpoint_id == 41
    assert captured["base_url"] == "https://proxbox-api.example"
    assert captured["auth_headers"] == {"Authorization": "Bearer opaque"}
    assert captured["backend_verify_ssl"] is False


def test_context_factory_exception_is_replaced_by_secret_safe_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canary = "https://root:password@pve.example/?token=CONTEXT-CANARY"

    def fail_context(endpoint_id=None):
        raise RuntimeError(canary)

    monkeypatch.setattr(orchestrator, "get_fastapi_request_context", fail_context)

    try:
        orchestrator.CephOrchestratorClient().backend_capabilities()
    except orchestrator.CephOrchestratorUnavailable as exc:
        rendered = "".join(traceback.format_exception(exc))
    else:  # pragma: no cover - assertion guard
        pytest.fail("context failure did not fail closed")

    assert "CONTEXT-CANARY" not in rendered
    assert "root:password" not in rendered


def test_unexpected_request_exception_is_replaced_by_secret_safe_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_request(*args, **kwargs):
        raise ValueError("password=REQUEST-CANARY")

    monkeypatch.setattr(orchestrator.requests, "request", fail_request)

    with pytest.raises(orchestrator.CephOrchestratorUnavailable) as excinfo:
        orchestrator.CephOrchestratorClient().operation("run-1")

    assert "REQUEST-CANARY" not in "".join(traceback.format_exception(excinfo.value))


@pytest.mark.parametrize("mapped_id", [True, "41", 0, -1])
def test_invalid_backend_endpoint_mapping_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    mapped_id,
) -> None:
    monkeypatch.setattr(
        orchestrator,
        "resolve_proxbox_backend_endpoint_id",
        lambda *args, **kwargs: (mapped_id, None),
    )

    with pytest.raises(orchestrator.CephOrchestratorUnavailable, match="invalid identifier"):
        orchestrator.CephOrchestratorClient().resolve_backend_endpoint_id(SimpleNamespace(pk=9))
