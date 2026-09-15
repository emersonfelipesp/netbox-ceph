"""Pin the proxbox-api Ceph v2 wire contract the orchestrator client depends on.

The fixture ``tests/fixtures/proxbox_api_ceph_v2_contract.v1.json`` is derived
from the proxbox-api Pydantic request/response models at a recorded backend
commit. These tests walk every ``CephOrchestratorClient`` method against that
fixture and check the keys ``operation_actions.py`` / ``ceph_v2_responses.py``
read from each response. The fixture is a reviewed snapshot, not a live probe:
these tests prove the plugin agrees with the snapshot, and the pinned digest
makes any snapshot change a visible diff. Verifying the snapshot against the
backend source is a review step when the backend commit is bumped.

The module reuses the dependency-isolated ``netbox_proxbox`` stubs from
``test_orchestrator_contract`` so it runs without Django or NetBox.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

# The sibling module installs the ``netbox_proxbox`` import stubs as a side
# effect; it must run before ``netbox_ceph.services.orchestrator`` is imported.
from tests import test_orchestrator_contract as _isolation  # isort: skip

from netbox_ceph.services import orchestrator  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "proxbox_api_ceph_v2_contract.v1.json"
CONSUMER_SOURCES = (
    REPO_ROOT / "netbox_ceph" / "services" / "operation_actions.py",
    REPO_ROOT / "netbox_ceph" / "services" / "ceph_v2_responses.py",
)
ACTOR = "requester"
_KEY_READ = re.compile(r"""\.get\(\s*["']([a-z_]+)["']""")


def _load_contract() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def contract() -> dict:
    return _load_contract()


@pytest.fixture(scope="module")
def routes(contract: dict) -> dict[str, dict]:
    return {route["client_method"]: route for route in contract["routes"]}


@pytest.fixture(scope="module")
def consumer_source() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in CONSUMER_SOURCES)


@pytest.fixture(autouse=True)
def exact_backend(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(orchestrator, "_enabled_fastapi_endpoint_ids", lambda: [1])
    monkeypatch.setattr(
        orchestrator,
        "get_fastapi_request_context",
        lambda endpoint_id=None: SimpleNamespace(
            http_url="https://proxbox-api.example",
            headers={"Authorization": "Bearer opaque"},
            verify_ssl=True,
        ),
    )


class _Capture:
    """Record one outbound request and answer with a minimal valid body."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return _isolation._Response(200, {"id": "x"})


def _invoke(client: orchestrator.CephOrchestratorClient, name: str) -> None:
    """Call one client method with representative arguments."""
    if name == "backend_capabilities":
        client.backend_capabilities(endpoint_id=41)
    elif name == "plan":
        client.plan({"provider": "proxmox", "endpoint_id": 41}, actor=ACTOR)
    elif name == "approve":
        client.approve("plan-1", endpoint_id=41, actor=ACTOR)
    elif name == "apply":
        client.apply("plan-1", endpoint_id=41, approval_token="t", actor=ACTOR)
    elif name == "approval_status":
        client.approval_status("approval-1", actor=ACTOR)
    elif name == "operation":
        client.operation("run-1")
    elif name == "reconcile":
        client.reconcile({"provider": "proxmox", "endpoint_id": 41, "scope": {}}, actor=ACTOR)
    elif name == "fetch_metrics":
        client.fetch_metrics(provider="proxmox")
    else:  # pragma: no cover - the parametrisation is the fixture itself
        raise AssertionError(f"no invocation recipe for client method {name!r}")


def _path_template(url: str, route: dict) -> str:
    """Turn the concrete URL back into the fixture's ``{param}`` template."""
    relative = url.removeprefix("https://proxbox-api.example/")
    template_parts = route["path"].split("/")
    actual_parts = relative.split("/")
    assert len(template_parts) == len(actual_parts), (route["path"], relative)
    return "/".join(
        template if template.startswith("{") else actual
        for template, actual in zip(template_parts, actual_parts, strict=True)
    )


def test_fixture_digest_is_pinned_in_the_client_module() -> None:
    digest = hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest()
    assert digest == orchestrator.PROXBOX_API_V2_CONTRACT_SHA256
    contract = _load_contract()
    assert contract["contract_version"] == orchestrator.PROXBOX_API_V2_CONTRACT_VERSION
    assert contract["backend"]["commit"] == orchestrator.PROXBOX_API_V2_CONTRACT_BACKEND_COMMIT


def test_every_public_client_method_is_declared_in_the_contract(routes: dict[str, dict]) -> None:
    public = {
        name
        for name, value in vars(orchestrator.CephOrchestratorClient).items()
        if callable(value) and not name.startswith("_") and name != "resolve_backend_endpoint_id"
    }
    assert public == set(routes), (
        "CephOrchestratorClient methods and the contract fixture disagree: "
        f"undeclared={sorted(public - set(routes))} stale={sorted(set(routes) - public)}"
    )


def _assert_actor_header(route: dict, headers: dict, header_name: str) -> None:
    policy = route["actor_header"]
    assert policy in {"required", "optional", "ignored", "none"}, policy
    if policy == "none":
        assert header_name not in headers
    else:
        # Whether the backend enforces, reads, or ignores the header is a
        # backend property recorded in the fixture; the client contract is the
        # same in all three cases: send the actor whenever one is known.
        assert headers[header_name] == ACTOR


def _assert_body_fits_model(route: dict, model: dict, sent: object) -> None:
    assert isinstance(sent, dict)
    assert set(model["required"]) <= set(sent), (
        f"{route['client_method']} omits keys {route['request_model']} requires"
    )
    if model.get("extra") != "allow":
        assert set(sent) <= set(model["properties"]), (
            f"{route['client_method']} sends keys {route['request_model']} does not declare"
        )
    # The representative invocation sends a subset of ``keys_sent``; the
    # fixture's full list is checked against the model separately.
    assert set(sent) <= set(route["keys_sent"])


@pytest.mark.parametrize(
    "route",
    sorted(_load_contract()["routes"], key=lambda r: r["client_method"]),
    ids=lambda r: r["client_method"],
)
def test_client_request_matches_backend_model(
    route: dict,
    contract: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _Capture()
    monkeypatch.setattr(orchestrator.requests, "request", capture)

    _invoke(orchestrator.CephOrchestratorClient(), route["client_method"])

    assert len(capture.calls) == 1
    method, url, kwargs = capture.calls[0]
    assert method.upper() == route["method"]
    assert _path_template(url, route) == route["path"]
    _assert_actor_header(route, kwargs["headers"], contract["actor_header"])

    if "request_model" not in route:
        assert kwargs.get("json") is None
        assert set(kwargs.get("params") or {}) <= set(route.get("query_params", []))
        return
    model = contract["backend"]["models"][route["request_model"]]
    _assert_body_fits_model(route, model, kwargs["json"])


def test_declared_keys_sent_fit_the_backend_request_models(contract: dict) -> None:
    models = contract["backend"]["models"]
    for route in contract["routes"]:
        if "request_model" not in route:
            continue
        model = models[route["request_model"]]
        sent = set(route["keys_sent"])
        assert set(model["required"]) <= sent, route["client_method"]
        if model.get("extra") != "allow":
            assert sent <= set(model["properties"]), route["client_method"]


def test_plugin_reads_are_declared_by_the_backend_response_models(contract: dict) -> None:
    models = contract["backend"]["models"]
    for route in contract["routes"]:
        model = models[route["response_model"]]
        properties = set(model["properties"])
        reads = set(route["plugin_reads"])
        assert reads <= properties, (
            f"{route['client_method']} reads keys {sorted(reads - properties)} that "
            f"{route['response_model']} does not declare"
        )
        legacy = set(route["plugin_reads_legacy"])
        assert not (legacy & properties), (
            f"{route['client_method']}: {sorted(legacy & properties)} are declared by the "
            "backend and must move from plugin_reads_legacy to plugin_reads"
        )
        assert not (legacy & reads)


def test_every_declared_read_exists_in_plugin_source(contract: dict, consumer_source: str) -> None:
    read_in_source = set(_KEY_READ.findall(consumer_source))
    for route in contract["routes"]:
        for key in (*route["plugin_reads"], *route["plugin_reads_legacy"]):
            assert key in read_in_source, (
                f"{route['client_method']} declares a read of {key!r} that no consumer performs"
            )


def test_backend_required_response_keys_cover_the_binding_checks(contract: dict) -> None:
    """The keys the plugin binds on must be ones the backend always returns."""
    models = contract["backend"]["models"]
    always_bound = {
        "approve": {"id", "plan_id", "plan_digest", "token", "expires_at"},
        "approval_status": {"id", "plan_id", "plan_digest", "expires_at"},
        "apply": {"id", "status"},
        "operation": {"id", "status"},
        "plan": {"id", "expires_at"},
    }
    routes = {route["client_method"]: route for route in contract["routes"]}
    for name, keys in always_bound.items():
        required = set(models[routes[name]["response_model"]]["required"])
        assert keys <= required, f"{name}: {sorted(keys - required)} are optional on the backend"
