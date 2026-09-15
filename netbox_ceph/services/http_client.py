"""HTTP client for proxbox-api ``/ceph/*`` read-only endpoints.

The companion ``proxbox-api`` backend exposes Ceph reflection routes as
plain JSON GETs (see ``proxbox_api/ceph/routes.py``):

- ``GET /ceph/status``
- ``GET /ceph/sync/full``
- ``GET /ceph/sync/{status,daemons,osds,pools,filesystems,crush,flags,rgw,rbd}``

Every ``/ceph/sync/*`` route receives exactly one backend
``proxmox_endpoint_ids`` value. The route's ``ProxmoxSessionsDep`` dependency
uses that query parameter to prevent a selected cluster sync from fanning out
across every configured Proxmox session. An optional
``netbox_branch_schema_id`` keeps the request branch-aware.

This module wraps those calls using the FastAPI endpoint context the
``netbox_proxbox`` plugin already resolves via
``services.backend_context.get_fastapi_request_context``. No new
authentication or endpoint resolution lives here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal, cast

import requests
from netbox_proxbox.services.backend_context import get_fastapi_request_context

logger = logging.getLogger("netbox_ceph.http_client")

CephSyncResource = Literal[
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
]

CEPH_SYNC_RESOURCES: tuple[CephSyncResource, ...] = (
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

# Match proxbox-api's tolerant read budget for long sync calls: short connect,
# long read. Ceph queries fan out across nodes and can take a while when
# clusters are large or degraded.
_CEPH_HTTP_TIMEOUT: tuple[float, float] = (5.0, 300.0)


class CephBackendError(RuntimeError):
    """Raised when the proxbox-api Ceph route returns an error or is unreachable."""


class CephSyncPayloadError(CephBackendError):
    """Raised when a successful Ceph sync response violates its response schema."""

    reason = "malformed_summary"


def _payload_error(location: str, expected: str) -> CephSyncPayloadError:
    return CephSyncPayloadError(
        f"Ceph backend returned malformed sync summary: {location} must be {expected}."
    )


def _required_string(payload: dict[str, Any], field_name: str, location: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str):
        raise _payload_error(f"{location}.{field_name}", "a string")
    return value


def _optional_string(payload: dict[str, Any], field_name: str, location: str) -> str | None:
    value = payload.get(field_name)
    if value is not None and not isinstance(value, str):
        raise _payload_error(f"{location}.{field_name}", "a string or null")
    return value


def _non_negative_integer(payload: dict[str, Any], field_name: str, location: str) -> int:
    value = payload.get(field_name, 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _payload_error(f"{location}.{field_name}", "a non-negative integer")
    return value


def _string_list(payload: dict[str, Any], field_name: str, location: str) -> list[str]:
    value = payload.get(field_name, [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise _payload_error(f"{location}.{field_name}", "a list of strings")
    return list(value)


@dataclass
class CephSyncSummary:
    """Validated mirror of proxbox-api's per-session Ceph sync summary."""

    name: str
    resource: CephSyncResource
    host: str | None = None
    fetched: int = 0
    written: int = 0
    errors: list[str] = field(default_factory=list)
    nodes: list[str] = field(default_factory=list)
    netbox_branch_schema_id: str | None = None

    @classmethod
    def from_payload(cls, payload: object, location: str) -> CephSyncSummary:
        if not isinstance(payload, dict):
            raise _payload_error(location, "an object")
        resource = _required_string(payload, "resource", location)
        if resource not in CEPH_SYNC_RESOURCES:
            raise _payload_error(f"{location}.resource", "a known Ceph sync resource")
        return cls(
            name=_required_string(payload, "name", location),
            host=_optional_string(payload, "host", location),
            resource=cast(CephSyncResource, resource),
            fetched=_non_negative_integer(payload, "fetched", location),
            written=_non_negative_integer(payload, "written", location),
            errors=_string_list(payload, "errors", location),
            nodes=_string_list(payload, "nodes", location),
            netbox_branch_schema_id=_optional_string(payload, "netbox_branch_schema_id", location),
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "host": self.host,
            "resource": self.resource,
            "fetched": self.fetched,
            "written": self.written,
            "errors": list(self.errors),
            "nodes": list(self.nodes),
            "netbox_branch_schema_id": self.netbox_branch_schema_id,
        }


@dataclass(frozen=True)
class CephBackendContext:
    """A resolved proxbox-api request context kept stable across one sync run."""

    base_url: str
    headers: dict[str, str] = field(repr=False)
    verify_ssl: bool = True


@dataclass(frozen=True)
class CephSyncScope:
    """The single backend endpoint identity allowed to satisfy a sync stage.

    ``endpoint_name`` is the NetBox-side display name used in refusal messages;
    proxbox-api does not echo it, so scope binding compares ``endpoint_host`` only.
    """

    backend_endpoint_id: int
    endpoint_name: str
    endpoint_host: str


@dataclass
class CephSyncResponse:
    """Validated mirror of proxbox-api's Ceph sync response envelope."""

    items: list[CephSyncSummary]
    raw: dict[str, Any] | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> CephSyncResponse:
        items = payload.get("items")
        if not isinstance(items, list):
            raise _payload_error("items", "a list")
        raw = payload.get("raw")
        if raw is not None and not isinstance(raw, dict):
            raise _payload_error("raw", "an object or null")
        return cls(
            items=[
                CephSyncSummary.from_payload(item, f"items[{index}]")
                for index, item in enumerate(items)
            ],
            raw=dict(raw) if raw is not None else None,
        )

    @property
    def errors(self) -> list[str]:
        return [error for summary in self.items for error in summary.errors]

    def as_payload(self) -> dict[str, Any]:
        return {
            "items": [summary.as_payload() for summary in self.items],
            "raw": dict(self.raw) if self.raw is not None else None,
        }


def _request_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def resolve_ceph_backend_context() -> CephBackendContext:
    """Resolve the proxbox-api context once for endpoint mapping and sync calls."""

    context = get_fastapi_request_context()
    if context is None or not context.http_url:
        raise CephBackendError(
            "No FastAPIEndpoint configured; cannot call proxbox-api /ceph/* routes."
        )
    return CephBackendContext(
        base_url=context.http_url,
        headers=dict(context.headers or {}),
        verify_ssl=bool(context.verify_ssl),
    )


def _response_payload_error(path: str, message: str) -> CephBackendError:
    error_type = CephSyncPayloadError if path.startswith("ceph/sync/") else CephBackendError
    return error_type(message)


def _get_json(
    path: str,
    *,
    params: dict[str, Any] | None = None,
    backend_context: CephBackendContext | None = None,
) -> dict[str, Any]:
    context = backend_context or resolve_ceph_backend_context()
    url = _request_url(context.base_url, path)
    try:
        response = requests.get(
            url,
            headers=context.headers,
            params=params,
            timeout=_CEPH_HTTP_TIMEOUT,
            verify=context.verify_ssl,
        )
    except requests.RequestException as exc:
        raise CephBackendError(f"Ceph backend request failed: {exc}") from exc

    # proxbox-api's sync contract returns HTTP 200; only standard 2xx statuses
    # are eligible for payload validation.
    if not 200 <= response.status_code < 300:
        raise CephBackendError(f"Ceph backend returned HTTP {response.status_code} for {path}.")

    try:
        payload = response.json()
    except ValueError as exc:
        raise _response_payload_error(
            path,
            f"Ceph backend returned non-JSON body for {path}: {exc}",
        ) from exc

    if not isinstance(payload, dict):
        raise _response_payload_error(
            path,
            f"Ceph backend returned unexpected payload shape for {path} "
            f"(expected object, got {type(payload).__name__})",
        )
    return payload


def _normalize_host(value: str | None) -> str:
    return str(value or "").split("/")[0].strip().rstrip(".").lower()


def _validate_resource_binding(response: CephSyncResponse, requested_resource: str) -> None:
    for index, summary in enumerate(response.items):
        if summary.resource != requested_resource:
            raise CephSyncPayloadError(
                "Ceph backend returned malformed sync summary: "
                f"items[{index}].resource must match requested resource "
                f"{requested_resource!r}; got {summary.resource!r}."
            )


def _validate_scope_binding(response: CephSyncResponse, scope: CephSyncScope) -> None:
    if len(response.items) != 1:
        raise CephSyncPayloadError(
            "Ceph backend returned malformed sync summary: items must contain "
            f"exactly one summary for endpoint {scope.endpoint_name!r}; got "
            f"{len(response.items)}."
        )
    # proxbox-api names a session after its domain, IP, cluster, or node — never
    # after the NetBox-side display name — so ``summary.name`` is reported in the
    # refusal for operators but only the host proves the endpoint identity.
    summary = response.items[0]
    if _normalize_host(summary.host) != _normalize_host(scope.endpoint_host):
        raise CephSyncPayloadError(
            "Ceph backend returned malformed sync summary: items[0].host must "
            f"match requested endpoint host {scope.endpoint_host!r}; got {summary.host!r} "
            f"(session {summary.name!r}, endpoint {scope.endpoint_name!r})."
        )


def fetch_ceph_status() -> dict[str, Any]:
    """Return the ``/ceph/status`` reachability/health probe."""
    return _get_json("ceph/status")


def fetch_ceph_sync(
    resource: str,
    *,
    scope: CephSyncScope,
    netbox_branch_schema_id: str | None = None,
    backend_context: CephBackendContext | None = None,
) -> CephSyncResponse:
    """Call ``/ceph/sync/<resource>`` and return its validated response."""
    if resource not in CEPH_SYNC_RESOURCES:
        raise ValueError(
            f"Unknown Ceph sync resource {resource!r}; expected one of {CEPH_SYNC_RESOURCES}"
        )
    if (
        isinstance(scope.backend_endpoint_id, bool)
        or not isinstance(scope.backend_endpoint_id, int)
        or scope.backend_endpoint_id <= 0
    ):
        raise ValueError("Ceph sync requires a positive backend Proxmox endpoint id.")
    params: dict[str, Any] = {
        "proxmox_endpoint_ids": str(scope.backend_endpoint_id),
    }
    if netbox_branch_schema_id:
        params["netbox_branch_schema_id"] = netbox_branch_schema_id
    payload = _get_json(
        f"ceph/sync/{resource}",
        params=params,
        backend_context=backend_context,
    )
    response = CephSyncResponse.from_payload(payload)
    _validate_resource_binding(response, resource)
    _validate_scope_binding(response, scope)
    return response
