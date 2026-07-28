"""NetBox-gated tests for the Ceph v2 action service and UI wiring.

These need the NetBox app registry (for models/choices and URL registration) but
not a database. They are skipped in the plain-pytest CI job and run in a NetBox
environment (local / plugin smoke). DB-backed behavior is covered by the
proxbox-api contract suite and the pure builder tests.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("netbox")

from django.conf import settings  # noqa: E402

if not settings.configured:
    pytest.skip("Django settings are not configured", allow_module_level=True)

try:
    import django  # noqa: E402

    django.setup()
except Exception as exc:  # noqa: BLE001
    pytest.skip(f"NetBox app registry is not available: {exc}", allow_module_level=True)

from django.core.exceptions import PermissionDenied  # noqa: E402
from django.http import Http404, HttpResponse  # noqa: E402
from django.middleware.csrf import CsrfViewMiddleware  # noqa: E402
from django.test import RequestFactory, override_settings  # noqa: E402
from django.urls import (  # noqa: E402
    NoReverseMatch,
    clear_url_caches,
    include,
    path,
    resolve,
    reverse,
)

from netbox_ceph import views  # noqa: E402
from netbox_ceph.choices import CephOperationStatusChoices, CephOperationTypeChoices  # noqa: E402
from netbox_ceph.services import desired_state_operations, operation_actions  # noqa: E402

_POOL_GENERATE_ROUTE = "plugins:netbox_ceph:cephpooldesiredstate_generate_operation"
urlpatterns = [path("", include("netbox_ceph.urls"))]


def _reverse_plugin_route(route_name: str, *, pk: int = 1) -> str:
    plugin_route_name = route_name.rsplit(":", maxsplit=1)[-1]
    with override_settings(ROOT_URLCONF=__name__):
        clear_url_caches()
        return reverse(f"netbox_ceph:{plugin_route_name}", kwargs={"pk": pk})


def _pool_generate_callback():
    with override_settings(ROOT_URLCONF=__name__):
        url = _reverse_plugin_route(_POOL_GENERATE_ROUTE)
        callback = resolve(url).func
    clear_url_caches()
    return url, callback


def test_operation_payload_shape() -> None:
    provider = SimpleNamespace(kind="proxmox", name="pve-cluster")
    operation = SimpleNamespace(
        pk=1,
        cluster_id=7,
        provider_id=3,
        provider=provider,
        operation_type="reconcile",
        target_kind="pool",
        target_ref="rbd",
        execution_node="pve-a",
        desired={"size": 3},
        is_destructive=False,
        confirmation_required=False,
        confirmed=False,
        source_branch_schema_id="branch-abc",
    )
    payload = operation_actions.operation_payload(operation, endpoint_id=41)
    assert payload["provider_kind"] == "proxmox"
    assert payload["target_kind"] == "pool"
    assert payload["target_ref"] == "rbd"
    assert payload["execution_node"] == "pve-a"
    assert payload["desired_state"]["objects"][0]["node"] == "pve-a"
    assert payload["desired"] == {"size": 3}
    assert payload["source_branch_schema_id"] == "branch-abc"
    assert payload["endpoint_id"] == 41


def test_apply_operation_rejects_unplanned() -> None:
    requester = SimpleNamespace(
        pk=1,
        is_authenticated=True,
        get_username=lambda: "requester",
        has_perm=lambda permission, obj: True,
    )
    approver = SimpleNamespace(
        pk=2,
        is_authenticated=True,
        get_username=lambda: "approver",
        has_perm=lambda permission, obj: True,
    )
    operation = SimpleNamespace(
        status=CephOperationStatusChoices.STATUS_PENDING,
        requested_by=requester,
    )
    with pytest.raises(operation_actions.OperationActionError) as excinfo:
        operation_actions.apply_operation(operation, actor=approver, confirmed=True)
    assert excinfo.value.kind == "invalid"
    assert "planned" in excinfo.value.message


def test_instance_values_for_pool_resolves_without_db() -> None:
    pool = type(
        "CephPoolDesiredState",
        (),
        {},
    )()
    pool.name = "rbd"
    pool.execution_node = "pve-a"
    pool.size = 3
    pool.min_size = 2
    pool.pg_autoscale_mode = "on"
    pool.crush_rule_name = ""
    pool.application = "rbd"
    pool.target_size_ratio = None
    pool.quota_max_bytes = None
    pool.quota_max_objects = None
    pool.compression_mode = "none"
    pool.erasure_code_profile = ""
    pool.parameters = {}

    values = desired_state_operations._instance_values(pool)
    request = desired_state_operations.build_request("CephPoolDesiredState", values)
    assert request["target_kind"] == "pool"
    assert request["target_ref"] == "rbd"
    assert request["desired"]["size"] == 3
    assert "crush_rule" not in request["desired"]  # blank crush rule dropped


def test_reconcile_uses_reconcile_operation_type() -> None:
    # The generated reconcile operation type is non-destructive by contract.
    assert CephOperationTypeChoices.TYPE_RECONCILE == "reconcile"


def test_action_views_are_registered() -> None:
    assert hasattr(views, "CephOperationPlanView")
    assert hasattr(views, "CephOperationApplyView")
    assert hasattr(views, "CephProviderReconcileView")


def test_generate_operation_contract_error_flashes_and_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desired_state = SimpleNamespace(get_absolute_url=lambda: "/desired-state/1/")
    model = SimpleNamespace(objects=SimpleNamespace(all=lambda: object()))
    request = SimpleNamespace(
        user=SimpleNamespace(
            is_authenticated=True,
            get_username=lambda: "requester",
            has_perms=lambda _permissions: True,
        )
    )
    errors: list[str] = []

    monkeypatch.setattr(
        views,
        "get_object_or_404",
        lambda _queryset, **_kwargs: desired_state,
    )
    monkeypatch.setattr(views.messages, "error", lambda _request, message: errors.append(message))
    monkeypatch.setattr(
        views,
        "redirect",
        lambda url: SimpleNamespace(status_code=302, url=url),
    )

    def reject_unsupported_fields(*_args, **_kwargs):
        raise desired_state_operations.DesiredStateContractError(
            "Unsupported pool write field(s): quota_max_bytes."
        )

    monkeypatch.setattr(views, "build_operation", reject_unsupported_fields)
    view = views._GenerateOperationView()
    view.model = model

    response = view.post(request, pk=1)

    assert response.status_code == 302
    assert response.url == "/desired-state/1/"
    assert errors == [
        "Generate operation failed: Unsupported pool write field(s): quota_max_bytes."
    ]


def test_generate_operation_contract_error_preserves_typed_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desired_state = SimpleNamespace()
    request = SimpleNamespace(
        user=SimpleNamespace(
            is_authenticated=True,
            get_username=lambda: "requester",
            has_perms=lambda _permissions: True,
        )
    )

    def reject_unsupported_fields(*_args, **_kwargs):
        raise desired_state_operations.DesiredStateContractError(
            "Unsupported pool write field(s): quota_max_bytes."
        )

    monkeypatch.setattr(views, "build_operation", reject_unsupported_fields)

    with pytest.raises(operation_actions.OperationActionError) as excinfo:
        views._GenerateOperationView().perform(request, desired_state)

    assert excinfo.value.kind == "unsupported"
    assert excinfo.value.reason == "desired_state_contract_unsupported"
    assert excinfo.value.message == "Unsupported pool write field(s): quota_max_bytes."


def test_generate_operation_route_requires_both_permissions_before_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url, callback = _pool_generate_callback()
    checked_permissions: list[tuple[str, ...]] = []

    def has_perms(permissions) -> bool:
        checked_permissions.append(tuple(permissions))
        return False

    request = RequestFactory().post(url)
    request.user = SimpleNamespace(is_authenticated=True, has_perms=has_perms)
    monkeypatch.setattr(
        views,
        "get_object_or_404",
        lambda *_args, **_kwargs: pytest.fail("source lookup occurred before authorization"),
    )

    with pytest.raises(PermissionDenied):
        callback(request, pk=1)

    assert checked_permissions == [
        (
            "netbox_ceph.request_cephoperation",
            "netbox_ceph.apply_cephoperation",
        )
    ]


def test_generate_operation_route_restricts_source_visibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url, callback = _pool_generate_callback()
    restricted_actions: list[str] = []

    class FakeQuerySet:
        def restrict(self, _user, action):
            restricted_actions.append(action)
            return self

    queryset = FakeQuerySet()
    model = SimpleNamespace(objects=SimpleNamespace(all=lambda: queryset))
    monkeypatch.setattr(callback.view_class, "model", model)

    def hidden_source(candidate_queryset, **_kwargs):
        assert candidate_queryset is queryset
        raise Http404

    monkeypatch.setattr(views, "get_object_or_404", hidden_source)
    request = RequestFactory().post(url)
    request.user = SimpleNamespace(
        is_authenticated=True,
        has_perms=lambda _permissions: True,
    )

    with pytest.raises(Http404):
        callback(request, pk=1)

    assert restricted_actions == ["view"]


def test_generate_operation_route_is_post_only() -> None:
    url, callback = _pool_generate_callback()
    request = RequestFactory().get(url)
    request.user = SimpleNamespace(
        is_authenticated=True,
        has_perms=lambda _permissions: True,
    )

    response = callback(request, pk=1)

    assert response.status_code == 405


def test_generate_operation_route_enforces_csrf() -> None:
    url, callback = _pool_generate_callback()
    request = RequestFactory().post(url)
    middleware = CsrfViewMiddleware(lambda _request: HttpResponse())

    response = middleware.process_view(request, callback, (), {"pk": 1})

    assert response is not None
    assert response.status_code == 403


def test_generate_operation_control_matches_required_permissions() -> None:
    template = (
        Path(views.__file__).parent
        / "templates"
        / "netbox_ceph"
        / "inc"
        / "generate_operation_controls.html"
    ).read_text(encoding="utf-8")

    assert (
        "perms.netbox_ceph.request_cephoperation and perms.netbox_ceph.apply_cephoperation"
    ) in template
    assert "perms.netbox_ceph.add_cephoperation" not in template


@pytest.mark.parametrize(
    "route_name",
    [
        "plugins:netbox_ceph:cephoperation_plan",
        "plugins:netbox_ceph:cephoperation_apply",
        "plugins:netbox_ceph:cephprovider_reconcile",
        "plugins:netbox_ceph:cephpooldesiredstate_generate_operation",
        "plugins:netbox_ceph:cephfilesystemdesiredstate_generate_operation",
    ],
)
def test_action_routes_reverse(route_name: str) -> None:
    assert _reverse_plugin_route(route_name)


def test_unsupported_desired_state_has_no_generate_route() -> None:
    with pytest.raises(NoReverseMatch):
        _reverse_plugin_route(
            "plugins:netbox_ceph:cephrgwbucketdesiredstate_generate_operation",
        )
