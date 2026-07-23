"""Typed client for the fail-closed proxbox-api Ceph v2 contract."""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

import requests
from netbox_proxbox.models import FastAPIEndpoint
from netbox_proxbox.services.backend_context import get_fastapi_request_context
from netbox_proxbox.views.backend_sync import (
    resolve_backend_endpoint_id as resolve_proxbox_backend_endpoint_id,
)

from netbox_ceph.services.http_client import CephBackendError
from netbox_ceph.services.redaction import redact_secrets

logger = logging.getLogger("netbox_ceph.orchestrator")

_CEPH_V2_HTTP_TIMEOUT: tuple[float, float] = (5.0, 300.0)
_REASON_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_RECOVERY_KEYS = (
    "approval_id",
    "plan_id",
    "operation_run_id",
    "endpoint_id",
)


class CephOrchestratorUnsupported(CephBackendError):
    """Raised when proxbox-api does not expose the requested Ceph v2 route."""


class CephOrchestratorUnavailable(CephBackendError):
    """Raised when the proxbox-api backend cannot be reached safely."""


class CephOrchestratorTimeout(CephOrchestratorUnavailable):
    """A request timed out after it may have reached the backend."""


class CephOrchestratorHTTPError(CephBackendError):
    """Stable structured backend rejection without raw response material."""

    def __init__(
        self,
        *,
        status_code: int,
        reason: str,
        detail: str,
        recovery: dict[str, str | int] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.reason = reason
        self.detail = detail
        self.recovery = recovery or {}


def _request_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _enabled_fastapi_endpoint_ids() -> list[int]:
    """Return at most two enabled endpoint IDs to enforce exact-one selection."""

    return list(
        FastAPIEndpoint.objects.filter(enabled=True).order_by("pk").values_list("pk", flat=True)[:2]
    )


def _safe_reason(value: object) -> str:
    candidate = str(value or "").strip().lower()
    if _REASON_PATTERN.fullmatch(candidate):
        return candidate
    return "backend_request_rejected"


def _safe_recovery_value(key: str, value: object) -> str | int | None:
    """Accept only typed recovery identifiers used by the canonical v2 contract."""

    if key == "endpoint_id":
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
        return None
    if key not in {"approval_id", "plan_id", "operation_run_id"} or not isinstance(value, str):
        return None
    if len(value) > 64:
        return None
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        return None
    return str(parsed)


def _structured_error(response: requests.Response, path: str) -> CephOrchestratorHTTPError:
    """Parse only stable reason/recovery fields; never retain a raw body."""

    reason = "backend_request_rejected"
    recovery: dict[str, str | int] = {}
    try:
        body = response.json()
    except Exception:
        body = None
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict):
        reason = _safe_reason(detail.get("reason"))
        for key in _RECOVERY_KEYS:
            value = _safe_recovery_value(key, detail.get(key))
            if value is not None:
                recovery[key] = value
    message = f"Ceph v2 backend rejected {path} ({reason})."
    return CephOrchestratorHTTPError(
        status_code=response.status_code,
        reason=reason,
        detail=message,
        recovery=recovery,
    )


def _send_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any] | None,
    params: dict[str, Any] | None,
    verify_ssl: bool,
    path: str,
) -> requests.Response:
    try:
        return requests.request(
            method,
            url,
            headers=headers,
            json=payload,
            params=params,
            timeout=_CEPH_V2_HTTP_TIMEOUT,
            verify=verify_ssl,
        )
    except requests.Timeout:
        raise CephOrchestratorTimeout(f"Ceph v2 backend request timed out for {path}.") from None
    except requests.RequestException:
        raise CephOrchestratorUnavailable(
            f"Ceph v2 backend request was unavailable for {path}."
        ) from None
    except Exception:
        raise CephOrchestratorUnavailable(
            f"Ceph v2 backend request could not be constructed for {path}."
        ) from None


def _decode_response(response: requests.Response, path: str) -> dict[str, Any]:
    if response.status_code == 501:
        raise CephOrchestratorUnsupported(
            f"Ceph v2 route {path!r} is unsupported by the configured backend."
        )
    if response.status_code == 404:
        try:
            missing_body = response.json()
        except Exception:
            missing_body = None
        if isinstance(missing_body, dict) and missing_body.get("detail") == "Not Found":
            raise CephOrchestratorUnsupported(
                f"Ceph v2 route {path!r} is unsupported by the configured backend."
            )
    if response.status_code >= 400:
        raise _structured_error(response, path)
    try:
        body = response.json()
    except Exception:
        raise CephBackendError(f"Ceph v2 backend returned non-JSON data for {path}.") from None
    if not isinstance(body, dict):
        raise CephBackendError(f"Ceph v2 backend returned an invalid object shape for {path}.")
    return body


class CephOrchestratorClient:
    """Client for canonical plan, approval, apply, and recovery routes."""

    def _resolve_context(self) -> tuple[str, dict[str, str], bool]:
        try:
            endpoint_ids = _enabled_fastapi_endpoint_ids()
        except Exception:
            raise CephOrchestratorUnavailable(
                "The configured proxbox-api endpoint could not be resolved."
            ) from None
        if not endpoint_ids:
            raise CephOrchestratorUnavailable(
                "Exactly one enabled FastAPI endpoint is required; none is configured."
            )
        if len(endpoint_ids) != 1:
            raise CephOrchestratorUnavailable(
                "Exactly one enabled FastAPI endpoint is required; multiple are configured."
            )
        try:
            context = get_fastapi_request_context(endpoint_id=endpoint_ids[0])
        except Exception:
            raise CephOrchestratorUnavailable(
                "The enabled proxbox-api endpoint context is unavailable."
            ) from None
        if context is None or not context.http_url:
            raise CephOrchestratorUnavailable(
                "The enabled FastAPI endpoint has no usable proxbox-api request context."
            )
        return (
            context.http_url,
            dict(context.headers or {}),
            bool(context.verify_ssl),
        )

    def resolve_backend_endpoint_id(self, endpoint: Any) -> int:
        """Translate a plugin endpoint PK to the canonical proxbox-api database ID."""

        base_url, headers, verify_ssl = self._resolve_context()
        try:
            backend_endpoint_id, error = resolve_proxbox_backend_endpoint_id(
                endpoint,
                base_url=base_url,
                auth_headers=headers,
                backend_verify_ssl=verify_ssl,
            )
        except Exception:
            raise CephOrchestratorUnavailable(
                "The selected Proxmox endpoint mapping could not be resolved."
            ) from None
        if backend_endpoint_id is None:
            logger.warning(
                "Ceph endpoint mapping failed for plugin endpoint %s",
                getattr(endpoint, "pk", None),
            )
            raise CephOrchestratorUnavailable(
                "The selected Proxmox endpoint is not uniquely registered in proxbox-api."
            ) from None
        if error:
            logger.warning(
                "Ceph endpoint mapping returned an inconsistent result for plugin endpoint %s",
                getattr(endpoint, "pk", None),
            )
            raise CephOrchestratorUnavailable(
                "The selected Proxmox endpoint mapping is inconsistent."
            )
        if isinstance(backend_endpoint_id, bool) or not isinstance(backend_endpoint_id, int):
            raise CephOrchestratorUnavailable(
                "The selected Proxmox endpoint mapping returned an invalid identifier."
            )
        if backend_endpoint_id <= 0:
            raise CephOrchestratorUnavailable(
                "The selected Proxmox endpoint mapping returned an invalid identifier."
            )
        return backend_endpoint_id

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        actor: str | None = None,
    ) -> dict[str, Any]:
        base_url, base_headers, verify_ssl = self._resolve_context()
        headers = dict(base_headers)
        if actor:
            headers["X-Proxbox-Actor"] = actor
        url = _request_url(base_url, path)
        logger.debug(
            "Calling proxbox-api %s %s payload=%r params=%r",
            method.upper(),
            path,
            redact_secrets(payload or {}),
            redact_secrets(params or {}),
        )
        response = _send_request(
            method,
            url,
            headers=headers,
            payload=payload,
            params=params,
            verify_ssl=verify_ssl,
            path=path,
        )
        body = _decode_response(response, path)
        logger.debug("proxbox-api %s response=%r", path, redact_secrets(body))
        return body

    def backend_capabilities(self, *, endpoint_id: int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"provider": "proxmox"}
        if endpoint_id is not None:
            params["endpoint_id"] = endpoint_id
        return self._request_json("get", "ceph/v2/capabilities", params=params)

    def plan(self, operation_payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
        return self._request_json(
            "post",
            "ceph/v2/plans",
            payload=operation_payload,
            actor=actor,
        )

    def approve(
        self,
        plan_id: str,
        *,
        endpoint_id: int,
        actor: str,
    ) -> dict[str, Any]:
        return self._request_json(
            "post",
            f"ceph/v2/plans/{plan_id}/approvals",
            payload={"endpoint_id": endpoint_id},
            actor=actor,
        )

    def apply(
        self,
        plan_id: str,
        *,
        endpoint_id: int,
        approval_token: str,
        actor: str,
    ) -> dict[str, Any]:
        return self._request_json(
            "post",
            f"ceph/v2/plans/{plan_id}/apply",
            payload={
                "plan_id": plan_id,
                "endpoint_id": endpoint_id,
                "approval_token": approval_token,
            },
            actor=actor,
        )

    def approval_status(self, approval_id: str) -> dict[str, Any]:
        return self._request_json("get", f"ceph/v2/approvals/{approval_id}")

    def operation(self, operation_id: str) -> dict[str, Any]:
        return self._request_json("get", f"ceph/v2/operations/{operation_id}")

    def reconcile(
        self,
        payload: dict[str, Any] | None = None,
        *,
        actor: str | None = None,
        **params: Any,
    ) -> dict[str, Any]:
        return self._request_json(
            "post",
            "ceph/v2/reconcile",
            payload=payload or {},
            params=params or None,
            actor=actor,
        )

    def fetch_metrics(self, **params: Any) -> dict[str, Any]:
        return self._request_json("get", "ceph/v2/metrics", params=params or None)
