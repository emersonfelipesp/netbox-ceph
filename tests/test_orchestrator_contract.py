"""Pure-python tests for the Ceph v2 orchestrator HTTP contract."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

requests = pytest.importorskip("requests")
pytest.importorskip("netbox_proxbox.services.backend_context")

from netbox_ceph.services import orchestrator  # noqa: E402


class _Response:
    def __init__(self, status_code: int, payload: dict | list | None = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


def _context():
    return SimpleNamespace(
        http_url="https://proxbox-api.example",
        headers={"Authorization": "Bearer opaque"},
        verify_ssl=False,
    )


def test_backend_capabilities_uses_ceph_v2_route(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return _Response(200, {"capabilities": {"plan": True}})

    monkeypatch.setattr(orchestrator, "get_fastapi_request_context", _context)
    monkeypatch.setattr(orchestrator.requests, "request", fake_request)

    payload = orchestrator.CephOrchestratorClient().backend_capabilities()

    assert payload == {"capabilities": {"plan": True}}
    assert calls[0][0] == "get"
    assert calls[0][1] == "https://proxbox-api.example/ceph/v2/capabilities"
    assert calls[0][2]["headers"] == {"Authorization": "Bearer opaque"}
    assert calls[0][2]["verify"] is False


def test_plan_posts_payload_and_returns_redacted_response(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return _Response(200, {"plan": {"summary": "ok", "secret_token": "hidden"}})

    monkeypatch.setattr(orchestrator, "get_fastapi_request_context", _context)
    monkeypatch.setattr(orchestrator.requests, "request", fake_request)

    payload = orchestrator.CephOrchestratorClient().plan(
        {"target_kind": "pool", "desired": {"password": "hidden"}}
    )

    assert calls[0][0] == "post"
    assert calls[0][1] == "https://proxbox-api.example/ceph/v2/plan"
    assert calls[0][2]["json"] == {"target_kind": "pool", "desired": {"password": "hidden"}}
    assert payload["plan"]["secret_token"] == "***REDACTED***"


@pytest.mark.parametrize("status_code", [404, 501])
def test_unsupported_backend_statuses_raise_unsupported(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    monkeypatch.setattr(orchestrator, "get_fastapi_request_context", _context)
    monkeypatch.setattr(
        orchestrator.requests,
        "request",
        lambda *args, **kwargs: _Response(status_code),
    )

    with pytest.raises(orchestrator.CephOrchestratorUnsupported):
        orchestrator.CephOrchestratorClient().apply({"id": 1})


def test_connection_failure_raises_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request(*args, **kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(orchestrator, "get_fastapi_request_context", _context)
    monkeypatch.setattr(orchestrator.requests, "request", fake_request)

    with pytest.raises(orchestrator.CephOrchestratorUnavailable):
        orchestrator.CephOrchestratorClient().fetch_metrics(scope="cluster")
