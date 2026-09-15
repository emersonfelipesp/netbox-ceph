"""Background sync job for netbox-ceph.

``CephSyncJob`` queues onto NetBox's default RQ queue (the same queue
``ProxboxSyncJob`` uses) and calls proxbox-api's read-only ``/ceph/sync/*``
routes. When branching is enabled on ``CephPluginSettings``, the job
provisions a netbox-branching branch around the sync, threads the
branch's ``schema_id`` through to proxbox-api, and merges the branch
back on success.

v1 is reflection-only: there is no Ceph-side write path. Failures leave
the branch open (default policy ``fail``) so an operator can inspect
``ChangeDiff`` conflicts before merging by hand.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from netbox.constants import RQ_QUEUE_DEFAULT
from netbox.jobs import JobRunner

try:
    from netbox.jobs import Job
except ImportError:  # pragma: no cover - test stubs may not export Job
    from typing import Any as _Any

    Job = _Any  # type: ignore[misc,assignment]

from netbox_ceph.services.branch_lifecycle import (
    branching_enabled_settings,
    create_and_provision_branch,
    merge_branch,
)
from netbox_ceph.services.http_client import (
    CEPH_SYNC_RESOURCES,
    CephBackendContext,
    CephBackendError,
    CephSyncPayloadError,
    CephSyncResponse,
    CephSyncScope,
    fetch_ceph_sync,
    resolve_ceph_backend_context,
)

logger = logging.getLogger("netbox_ceph.jobs")

CEPH_SYNC_QUEUE_NAME = RQ_QUEUE_DEFAULT

# Match ProxboxSyncJob's long RQ wall-clock so a slow Ceph cluster does not
# get killed by NetBox's 300s default RQ timeout.
CEPH_SYNC_JOB_TIMEOUT = 7200

DEFAULT_SYNC_RESOURCES: tuple[str, ...] = ("full",)

_BRANCH_SYNC_FAILURE_REASON = "ceph_sync_stage_failed"


class CephSyncScopeError(CephBackendError):
    """The selected Ceph cluster could not be bound to one backend endpoint."""

    reason = "unresolved_cluster_scope"


@dataclass(frozen=True)
class _ResolvedSyncTarget:
    scope: CephSyncScope
    backend_context: CephBackendContext
    proxmox_cluster_pk: int | str
    endpoint_pk: int | str


def _resource_values(resources: object) -> list[object]:
    if resources is None:
        return []
    if isinstance(resources, str):
        return resources.split(",")
    if isinstance(resources, Iterable):
        return list(resources)
    return [resources]


def _normalize_resources(resources: object = None) -> list[str]:
    raw_values = _resource_values(resources)
    if not raw_values:
        return list(DEFAULT_SYNC_RESOURCES)
    normalized: list[str] = []
    for raw in raw_values:
        for candidate in str(raw).split(","):
            value = candidate.strip().lower()
            if not value:
                continue
            if value not in CEPH_SYNC_RESOURCES:
                raise ValueError(
                    f"Unknown Ceph sync resource {value!r}; expected one of {CEPH_SYNC_RESOURCES}"
                )
            if value not in normalized:
                normalized.append(value)
    return normalized or list(DEFAULT_SYNC_RESOURCES)


def _stage_runtime(stage_started: float) -> float:
    return round(time.monotonic() - stage_started, 3)


def _load_cluster_endpoint(cluster_pk: int | str | None) -> tuple[object, object]:
    if cluster_pk is None:
        raise CephSyncScopeError("Ceph sync refused: cluster_pk is required for endpoint scope.")
    from netbox_ceph.models import CephCluster  # noqa: PLC0415

    try:
        cluster = CephCluster.objects.select_related(
            "endpoint",
            "proxmox_cluster__endpoint",
        ).get(pk=cluster_pk)
    except CephCluster.DoesNotExist as exc:
        raise CephSyncScopeError(
            f"Ceph sync refused: no CephCluster exists for cluster_pk={cluster_pk!r}."
        ) from exc
    except Exception:
        raise CephSyncScopeError(
            "Ceph sync refused: the selected Ceph cluster could not be loaded safely."
        ) from None
    proxmox_cluster = getattr(cluster, "proxmox_cluster", None)
    endpoint = getattr(proxmox_cluster, "endpoint", None)
    if proxmox_cluster is None or endpoint is None:
        raise CephSyncScopeError(
            "Ceph sync refused: the selected Ceph cluster has no linked ProxmoxCluster endpoint."
        )
    cluster_endpoint = getattr(cluster, "endpoint", None)
    if getattr(cluster_endpoint, "pk", None) != getattr(endpoint, "pk", None):
        raise CephSyncScopeError(
            "Ceph sync refused: the CephCluster and linked ProxmoxCluster name different "
            "Proxmox endpoints."
        )
    return proxmox_cluster, endpoint


def _backend_sync_helpers() -> tuple[Any, Any]:
    try:
        from netbox_proxbox.views import backend_sync  # noqa: PLC0415
    except Exception:
        raise CephSyncScopeError(
            "Ceph sync refused: this netbox-proxbox installation does not expose "
            "backend endpoint scope helpers."
        ) from None
    resolver = getattr(backend_sync, "resolve_backend_endpoint_id", None)
    name_builder = getattr(backend_sync, "proxmox_backend_name", None)
    if not callable(resolver) or not callable(name_builder):
        raise CephSyncScopeError(
            "Ceph sync refused: this netbox-proxbox installation does not expose "
            "the typed backend endpoint scope contract."
        )
    return resolver, name_builder


def _endpoint_host(endpoint: object) -> str:
    domain = str(getattr(endpoint, "domain", "") or "").strip()
    ip_address = getattr(endpoint, "ip_address", None)
    raw_address = getattr(ip_address, "address", ip_address)
    host = domain or str(raw_address or "").split("/")[0].strip()
    if not host:
        raise CephSyncScopeError(
            "Ceph sync refused: the selected Proxmox endpoint has no usable host."
        )
    return host


def _resolve_sync_target(cluster_pk: int | str | None) -> _ResolvedSyncTarget:
    proxmox_cluster, endpoint = _load_cluster_endpoint(cluster_pk)
    try:
        context = resolve_ceph_backend_context()
    except Exception:
        raise CephSyncScopeError(
            "Ceph sync refused: the proxbox-api request context could not be resolved."
        ) from None
    resolver, name_builder = _backend_sync_helpers()
    try:
        backend_endpoint_id, error = resolver(
            endpoint,
            base_url=context.base_url.rstrip("/"),
            auth_headers=context.headers,
            backend_verify_ssl=context.verify_ssl,
        )
        endpoint_name = str(name_builder(endpoint))
    except Exception:
        raise CephSyncScopeError(
            "Ceph sync refused: the selected Proxmox endpoint mapping could not be resolved."
        ) from None
    if error or isinstance(backend_endpoint_id, bool) or not isinstance(backend_endpoint_id, int):
        raise CephSyncScopeError(
            "Ceph sync refused: the selected Proxmox endpoint is not uniquely registered "
            "in proxbox-api."
        )
    if backend_endpoint_id <= 0:
        raise CephSyncScopeError(
            "Ceph sync refused: proxbox-api returned an invalid backend endpoint id."
        )
    return _ResolvedSyncTarget(
        scope=CephSyncScope(backend_endpoint_id, endpoint_name, _endpoint_host(endpoint)),
        backend_context=context,
        proxmox_cluster_pk=getattr(proxmox_cluster, "pk"),
        endpoint_pk=getattr(endpoint, "pk"),
    )


def _response_stage(
    resource: str,
    response: CephSyncResponse,
    stage_started: float,
) -> tuple[dict[str, Any], bool]:
    errors = response.errors
    stage: dict[str, Any] = {
        "resource": resource,
        "status": "failed" if errors else "ok",
        "runtime_seconds": _stage_runtime(stage_started),
        "response": response.as_payload(),
    }
    if errors:
        stage.update({"reason": "upstream_errors", "errors": errors})
    return stage, bool(errors)


def _exception_reason(exc: Exception) -> str:
    if isinstance(exc, CephSyncPayloadError):
        return exc.reason
    if isinstance(exc, CephBackendError):
        return "backend_error"
    return "invalid_request"


def _exception_stage(resource: str, exc: Exception, stage_started: float) -> dict[str, Any]:
    return {
        "resource": resource,
        "status": "failed",
        "reason": _exception_reason(exc),
        "runtime_seconds": _stage_runtime(stage_started),
        "error": str(exc),
    }


def _run_stage(
    resource: str,
    target: _ResolvedSyncTarget,
    netbox_branch_schema_id: str | None,
    stage_started: float,
    stage_logger: Any,
) -> tuple[dict[str, Any], bool]:
    try:
        response = fetch_ceph_sync(
            resource,
            scope=target.scope,
            netbox_branch_schema_id=netbox_branch_schema_id,
            backend_context=target.backend_context,
        )
    except (CephBackendError, ValueError) as exc:
        stage_logger.error("Ceph sync resource %s failed: %s", resource, exc)
        return _exception_stage(resource, exc, stage_started), True

    stage, stage_failed = _response_stage(resource, response, stage_started)
    if stage_failed:
        stage_logger.error(
            "Ceph sync resource %s reported upstream errors: %s",
            resource,
            "; ".join(response.errors),
        )
    return stage, stage_failed


def _branch_failure_disposition(branch: object) -> dict[str, str]:
    return {
        "status": "left_open",
        "branch_name": str(getattr(branch, "name", "<unknown>")),
        "reason": _BRANCH_SYNC_FAILURE_REASON,
    }


def _record_scope_failure(
    job: object,
    params: dict[str, Any],
    error: CephSyncScopeError,
    run_started: float,
) -> None:
    job.data = {
        "ceph_sync": {
            "params": params,
            "runtime_seconds": round(time.monotonic() - run_started, 3),
            "response": {
                "status": "failed",
                "reason": error.reason,
                "error": str(error),
            },
        }
    }
    job.save(update_fields=["data"])


class CephSyncJob(JobRunner):
    """Trigger a Ceph reflection sync against proxbox-api."""

    class Meta:
        name = "Ceph Sync"

    @classmethod
    def enqueue(cls, **kwargs: object) -> Job:
        """Enqueue with a long ``job_timeout`` so slow Ceph clusters don't get killed."""
        kwargs.setdefault("job_timeout", CEPH_SYNC_JOB_TIMEOUT)
        job_target = kwargs.pop("instance", None)
        if job_target is not None:
            raise ValueError("Cannot enqueue CephSyncJob with instance; use cluster_pk instead.")
        resources_kw = kwargs.pop("resources", None)
        cluster_pk = kwargs.get("cluster_pk")
        try:
            resources = _normalize_resources(resources_kw)
        except ValueError as exc:
            raise ValueError(f"Cannot enqueue CephSyncJob: {exc}") from exc
        kwargs["resources"] = resources

        job = super().enqueue(**kwargs)
        params: dict[str, Any] = {"resources": resources}
        if cluster_pk is not None:
            params["cluster_pk"] = cluster_pk
        job.data = {
            "ceph_sync": {
                "params": params,
            }
        }
        job.save(update_fields=["data"])
        return job

    def _resolve_scope_or_fail(
        self,
        cluster_pk: int | str | None,
        params: dict[str, Any],
        run_started: float,
    ) -> _ResolvedSyncTarget:
        """Bind the job to one backend endpoint, recording a named failure otherwise."""
        try:
            target = _resolve_sync_target(cluster_pk)
        except CephSyncScopeError as exc:
            self.logger.error(str(exc))
            _record_scope_failure(self.job, params, exc, run_started)
            raise
        params.update(
            {
                "proxmox_cluster_pk": target.proxmox_cluster_pk,
                "proxmox_endpoint_pk": target.endpoint_pk,
                "backend_endpoint_id": target.scope.backend_endpoint_id,
            }
        )
        return target

    def run(
        self,
        resources: list[str] | None = None,
        cluster_pk: int | str | None = None,
        **_kwargs: object,
    ) -> None:
        """Run one or more proxbox-api Ceph sync calls."""
        run_started = time.monotonic()
        try:
            normalized_resources = _normalize_resources(resources)
        except ValueError as exc:
            self.logger.error(str(exc))
            raise

        params: dict[str, Any] = {
            "resources": normalized_resources,
            "cluster_pk": cluster_pk,
        }
        target = self._resolve_scope_or_fail(cluster_pk, params, run_started)

        branch = None
        branch_config = branching_enabled_settings()
        if branch_config is not None:
            branch_name = f"{branch_config['prefix']}-{self.job.pk}-{int(run_started)}"
            self.logger.info(
                "NetBox branching enabled — creating branch %r for Ceph sync",
                branch_name,
            )
            try:
                branch = create_and_provision_branch(
                    name=branch_name,
                    user=getattr(self.job, "user", None),
                )
                self.logger.info("Branch %s ready (schema_id=%s)", branch.name, branch.schema_id)
            except Exception as exc:
                self.logger.error(
                    "Failed to create/provision NetBox branch %s: %s",
                    branch_name,
                    exc,
                )
                raise

        netbox_branch_schema_id = str(branch.schema_id) if branch is not None else None

        params["netbox_branch_schema_id"] = netbox_branch_schema_id
        self.job.data = {"ceph_sync": {"params": params}}
        self.job.save(update_fields=["data"])

        stage_results: list[dict[str, Any]] = []
        had_error = False
        for resource in normalized_resources:
            stage_started = time.monotonic()
            self.logger.info("Calling proxbox-api /ceph/sync/%s", resource)
            stage, stage_failed = _run_stage(
                resource,
                target,
                netbox_branch_schema_id,
                stage_started,
                self.logger,
            )
            stage_results.append(stage)
            had_error = had_error or stage_failed

        runtime_seconds = round(time.monotonic() - run_started, 3)
        response_data: dict[str, Any] = {"stages": stage_results}
        if had_error and branch is not None:
            response_data["branch_disposition"] = _branch_failure_disposition(branch)
        self.job.data = {
            "ceph_sync": {
                "params": params,
                "runtime_seconds": runtime_seconds,
                "response": response_data,
            }
        }
        self.job.save(update_fields=["data"])
        self.logger.info(
            "Ceph sync finished in %.3fs (%d stage(s), errors=%s)",
            runtime_seconds,
            len(stage_results),
            had_error,
        )

        if had_error:
            if branch is not None:
                self.logger.warning(
                    "Leaving branch %s open because one or more Ceph stages failed",
                    branch.name,
                )
            raise RuntimeError("One or more Ceph sync stages failed; see job log for details.")

        if branch is not None and branch_config is not None:
            merged, message = merge_branch(
                branch=branch,
                user=getattr(self.job, "user", None),
                on_conflict=branch_config["on_conflict"],
            )
            if merged:
                self.logger.info(message)
            else:
                self.logger.error(message)
                raise RuntimeError(message)


__all__ = (
    "CEPH_SYNC_JOB_TIMEOUT",
    "CEPH_SYNC_QUEUE_NAME",
    "CephSyncScopeError",
    "CephSyncJob",
    "DEFAULT_SYNC_RESOURCES",
)
