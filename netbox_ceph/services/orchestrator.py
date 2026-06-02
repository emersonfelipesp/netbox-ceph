"""Thin client for proxbox-api Ceph v2 orchestration routes."""

from __future__ import annotations

import logging
from typing import Any

import requests

from netbox_ceph.services.http_client import CephBackendError, get_fastapi_request_context
from netbox_ceph.services.redaction import redact_secrets

logger = logging.getLogger("netbox_ceph.orchestrator")

_CEPH_V2_HTTP_TIMEOUT: tuple[float, float] = (5.0, 300.0)


class CephOrchestratorUnsupported(CephBackendError):
    """Raised when proxbox-api does not expose the requested Ceph v2 route."""


class CephOrchestratorUnavailable(CephBackendError):
    """Raised when the proxbox-api backend cannot be reached."""


def _request_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


class CephOrchestratorClient:
    """Client for future ``/ceph/v2/*`` proxbox-api routes."""

    def _resolve_context(self) -> tuple[str, dict[str, str], bool]:
        context = get_fastapi_request_context()
        if context is None or not context.http_url:
            raise CephOrchestratorUnavailable(
                "No FastAPIEndpoint configured; cannot call proxbox-api /ceph/v2 routes."
            )
        return (
            context.http_url,
            dict(context.headers or {}),
            bool(context.verify_ssl),
        )

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        base_url, headers, verify_ssl = self._resolve_context()
        url = _request_url(base_url, path)
        redacted_payload = redact_secrets(payload or {})
        redacted_params = redact_secrets(params or {})
        logger.debug(
            "Calling proxbox-api %s %s payload=%r params=%r",
            method.upper(),
            path,
            redacted_payload,
            redacted_params,
        )
        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                json=payload,
                params=params,
                timeout=_CEPH_V2_HTTP_TIMEOUT,
                verify=verify_ssl,
            )
        except requests.RequestException as exc:
            raise CephOrchestratorUnavailable(
                f"Ceph v2 backend request failed for {path}: {type(exc).__name__}"
            ) from exc

        if response.status_code in (404, 501):
            raise CephOrchestratorUnsupported(
                f"Ceph v2 route {path!r} is unsupported by the configured backend."
            )
        if response.status_code >= 400:
            raise CephBackendError(
                f"Ceph v2 backend returned HTTP {response.status_code} for {path}."
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise CephBackendError(f"Ceph v2 backend returned non-JSON body for {path}.") from exc

        if not isinstance(body, dict):
            raise CephBackendError(
                f"Ceph v2 backend returned unexpected payload shape for {path} "
                f"(expected object, got {type(body).__name__})."
            )

        redacted_body = redact_secrets(body)
        logger.debug("proxbox-api %s response=%r", path, redacted_body)
        return redacted_body

    def backend_capabilities(self) -> dict[str, Any]:
        return self._request_json("get", "ceph/v2/capabilities")

    def plan(self, operation_payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("post", "ceph/v2/plan", payload=operation_payload)

    def apply(self, operation_payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("post", "ceph/v2/apply", payload=operation_payload)

    def reconcile(self, payload: dict[str, Any] | None = None, **params: Any) -> dict[str, Any]:
        return self._request_json(
            "post",
            "ceph/v2/reconcile",
            payload=payload or {},
            params=params or None,
        )

    def fetch_metrics(self, **params: Any) -> dict[str, Any]:
        return self._request_json("get", "ceph/v2/metrics", params=params or None)
