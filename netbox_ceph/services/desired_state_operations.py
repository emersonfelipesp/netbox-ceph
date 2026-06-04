"""Build ``CephOperation`` requests from declarative desired-state rows.

This is the bridge between the declarative configuration layer (the
``Ceph*DesiredState`` models, NetBox's source of truth for *intended* Ceph
config) and the imperative ``CephOperation`` -> ``CephPlan`` ->
``CephOperationRun`` engine that reconciles intent against a provider through
proxbox-api ``/ceph/v2/*``.

The payload/target shaping functions are intentionally Django-free so they can
be unit tested without a NetBox runtime. ``build_operation`` is the thin Django
wrapper that reads a desired-state instance, resolves its relations to names,
and persists a ``CephOperation`` the existing plan/apply engine consumes.

``operation_type`` defaults to ``reconcile``: the proxbox-api Proxmox adapter
``diff()`` treats any non-delete action as "ensure" and resolves
create/update/noop from live state, so a generated reconcile operation is never
destructive. Desired-state rows never carry secrets; RGW user keys live behind
the opaque ``credential_ref`` that proxbox-api resolves.
"""

from __future__ import annotations

from typing import Any, Callable

# NOTE: keep the module top-level Django-free so the pure payload/target builders
# import without a NetBox runtime (CI runs them as plain pytest). NetBox imports
# live inside ``build_operation``.

# --------------------------------------------------------------------------- #
# Pure payload/target shaping (Django-free)
# --------------------------------------------------------------------------- #


def _clean(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop empty values and fold any ``parameters`` mapping into the result.

    ``None``, ``""``, ``[]`` and ``{}`` are dropped so the generated ``desired``
    payload stays compact and diff-friendly. Meaningful falsey values such as
    ``False`` and ``0`` are preserved. Keys already present win over
    ``parameters`` overrides.
    """

    params = payload.pop("parameters", None)
    result = {key: value for key, value in payload.items() if value not in (None, "", [], {})}
    if isinstance(params, dict):
        for key, value in params.items():
            result.setdefault(str(key), value)
    return result


def _pool_payload(values: dict[str, Any]) -> dict[str, Any]:
    return _clean(
        {
            "name": values.get("name"),
            "size": values.get("size"),
            "min_size": values.get("min_size"),
            "pg_autoscale_mode": values.get("pg_autoscale_mode"),
            "crush_rule": values.get("crush_rule_name"),
            "application": values.get("application"),
            "target_size_ratio": values.get("target_size_ratio"),
            "quota_max_bytes": values.get("quota_max_bytes"),
            "quota_max_objects": values.get("quota_max_objects"),
            "compression_mode": values.get("compression_mode"),
            "erasure_code_profile": values.get("erasure_code_profile"),
            "parameters": values.get("parameters"),
        }
    )


def _filesystem_payload(values: dict[str, Any]) -> dict[str, Any]:
    return _clean(
        {
            "name": values.get("name"),
            "metadata_pool": values.get("metadata_pool_name"),
            "data_pools": values.get("data_pools"),
            "mds_placement": values.get("mds_placement"),
            "standby_count": values.get("standby_count"),
            "max_mds": values.get("max_mds"),
            "quota_max_bytes": values.get("quota_max_bytes"),
            "parameters": values.get("parameters"),
        }
    )


def _rbd_image_payload(values: dict[str, Any]) -> dict[str, Any]:
    return _clean(
        {
            "pool": values.get("pool_name"),
            "name": values.get("name"),
            "size_bytes": values.get("size_bytes"),
            "features": values.get("features"),
            "object_size": values.get("object_size"),
            "stripe_unit": values.get("stripe_unit"),
            "stripe_count": values.get("stripe_count"),
            "data_pool": values.get("data_pool"),
            "metadata": values.get("metadata"),
            "parameters": values.get("parameters"),
        }
    )


def _rbd_snapshot_payload(values: dict[str, Any]) -> dict[str, Any]:
    return _clean(
        {
            "pool": values.get("pool_name"),
            "image": values.get("image_name"),
            "name": values.get("name"),
            "protected": values.get("protected"),
            "parameters": values.get("parameters"),
        }
    )


def _rgw_realm_payload(values: dict[str, Any]) -> dict[str, Any]:
    return _clean(
        {
            "name": values.get("name"),
            "is_default": values.get("is_default"),
            "parameters": values.get("parameters"),
        }
    )


def _rgw_zone_payload(values: dict[str, Any]) -> dict[str, Any]:
    return _clean(
        {
            "name": values.get("name"),
            "realm": values.get("realm_name"),
            "zonegroup": values.get("zonegroup_name"),
            "is_master": values.get("is_master"),
            "endpoints": values.get("endpoints"),
            "placement_targets": values.get("placement_targets"),
            "parameters": values.get("parameters"),
        }
    )


def _rgw_user_payload(values: dict[str, Any]) -> dict[str, Any]:
    return _clean(
        {
            "uid": values.get("uid"),
            "display_name": values.get("display_name"),
            "email": values.get("email"),
            "tenant": values.get("tenant_name"),
            "suspended": values.get("suspended"),
            "max_buckets": values.get("max_buckets"),
            "quota_max_size_bytes": values.get("quota_max_size_bytes"),
            "quota_max_objects": values.get("quota_max_objects"),
            "credential_ref": values.get("credential_ref"),
            "parameters": values.get("parameters"),
        }
    )


def _rgw_bucket_payload(values: dict[str, Any]) -> dict[str, Any]:
    return _clean(
        {
            "name": values.get("name"),
            "owner": values.get("owner_uid"),
            "placement_target": values.get("placement_target"),
            "versioning_enabled": values.get("versioning_enabled"),
            "quota_max_size_bytes": values.get("quota_max_size_bytes"),
            "quota_max_objects": values.get("quota_max_objects"),
            "lifecycle_policy": values.get("lifecycle_policy"),
            "parameters": values.get("parameters"),
        }
    )


def _pool_ref(values: dict[str, Any]) -> str:
    return str(values.get("name") or "")


def _filesystem_ref(values: dict[str, Any]) -> str:
    return str(values.get("name") or "")


def _rbd_image_ref(values: dict[str, Any]) -> str:
    pool = str(values.get("pool_name") or "")
    name = str(values.get("name") or "")
    return f"{pool}/{name}" if pool else name


def _rbd_snapshot_ref(values: dict[str, Any]) -> str:
    pool = str(values.get("pool_name") or "")
    image = str(values.get("image_name") or "")
    name = str(values.get("name") or "")
    base = f"{pool}/{image}" if pool else image
    return f"{base}@{name}" if base else name


def _name_ref(values: dict[str, Any]) -> str:
    return str(values.get("name") or "")


def _uid_ref(values: dict[str, Any]) -> str:
    return str(values.get("uid") or "")


class _Spec:
    """How one desired-state kind maps to a ``CephOperation``."""

    __slots__ = ("target_kind", "ref_fn", "payload_fn")

    def __init__(
        self,
        target_kind: str,
        ref_fn: Callable[[dict[str, Any]], str],
        payload_fn: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        self.target_kind = target_kind
        self.ref_fn = ref_fn
        self.payload_fn = payload_fn


# Keyed by desired-state model class name.
SPECS: dict[str, _Spec] = {
    "CephPoolDesiredState": _Spec("pool", _pool_ref, _pool_payload),
    "CephFilesystemDesiredState": _Spec("filesystem", _filesystem_ref, _filesystem_payload),
    "CephRBDImageDesiredState": _Spec("rbd_image", _rbd_image_ref, _rbd_image_payload),
    "CephRBDSnapshotDesiredState": _Spec("rbd_snapshot", _rbd_snapshot_ref, _rbd_snapshot_payload),
    "CephRGWRealmDesiredState": _Spec("rgw_realm", _name_ref, _rgw_realm_payload),
    "CephRGWZoneDesiredState": _Spec("rgw_zone", _name_ref, _rgw_zone_payload),
    "CephRGWUserDesiredState": _Spec("rgw_user", _uid_ref, _rgw_user_payload),
    "CephRGWBucketDesiredState": _Spec("rgw_bucket", _name_ref, _rgw_bucket_payload),
}


def supported_models() -> tuple[str, ...]:
    """Names of desired-state models that can generate an operation."""

    return tuple(SPECS)


def build_request(model_name: str, values: dict[str, Any]) -> dict[str, Any]:
    """Return ``{target_kind, target_ref, desired}`` for a desired-state kind.

    Pure: ``values`` is a flat mapping of scalar field values (relations already
    resolved to their name/uid). Raises ``KeyError`` for an unknown model.
    """

    spec = SPECS[model_name]
    return {
        "target_kind": spec.target_kind,
        "target_ref": spec.ref_fn(values),
        "desired": spec.payload_fn(values),
    }


# --------------------------------------------------------------------------- #
# Django wrapper
# --------------------------------------------------------------------------- #


def _related_name(obj: Any) -> str | None:
    if obj is None:
        return None
    for attr in ("name", "uid"):
        value = getattr(obj, attr, None)
        if value:
            return str(value)
    return str(obj)


def _instance_values(instance: Any) -> dict[str, Any]:
    """Extract a flat ``values`` mapping from a desired-state instance.

    Resolves the relations the payload/ref functions need (metadata pool, RBD
    parent image, RGW realm, bucket owner) to their identifying name/uid.
    """

    name = type(instance).__name__
    values: dict[str, Any] = {}

    if name == "CephPoolDesiredState":
        values = {
            "name": instance.name,
            "size": instance.size,
            "min_size": instance.min_size,
            "pg_autoscale_mode": instance.pg_autoscale_mode,
            "crush_rule_name": instance.crush_rule_name,
            "application": instance.application,
            "target_size_ratio": instance.target_size_ratio,
            "quota_max_bytes": instance.quota_max_bytes,
            "quota_max_objects": instance.quota_max_objects,
            "compression_mode": instance.compression_mode,
            "erasure_code_profile": instance.erasure_code_profile,
            "parameters": instance.parameters,
        }
    elif name == "CephFilesystemDesiredState":
        values = {
            "name": instance.name,
            "metadata_pool_name": _related_name(instance.metadata_pool),
            "data_pools": instance.data_pools,
            "mds_placement": instance.mds_placement,
            "standby_count": instance.standby_count,
            "max_mds": instance.max_mds,
            "quota_max_bytes": instance.quota_max_bytes,
            "parameters": instance.parameters,
        }
    elif name == "CephRBDImageDesiredState":
        values = {
            "pool_name": instance.pool_name,
            "name": instance.name,
            "size_bytes": instance.size_bytes,
            "features": instance.features,
            "object_size": instance.object_size,
            "stripe_unit": instance.stripe_unit,
            "stripe_count": instance.stripe_count,
            "data_pool": instance.data_pool,
            "metadata": instance.metadata,
            "parameters": instance.parameters,
        }
    elif name == "CephRBDSnapshotDesiredState":
        image = instance.image
        values = {
            "pool_name": getattr(image, "pool_name", None),
            "image_name": getattr(image, "name", None),
            "name": instance.name,
            "protected": instance.protected,
            "parameters": instance.parameters,
        }
    elif name == "CephRGWRealmDesiredState":
        values = {
            "name": instance.name,
            "is_default": instance.is_default,
            "parameters": instance.parameters,
        }
    elif name == "CephRGWZoneDesiredState":
        values = {
            "name": instance.name,
            "realm_name": _related_name(instance.realm),
            "zonegroup_name": instance.zonegroup_name,
            "is_master": instance.is_master,
            "endpoints": instance.endpoints,
            "placement_targets": instance.placement_targets,
            "parameters": instance.parameters,
        }
    elif name == "CephRGWUserDesiredState":
        values = {
            "uid": instance.uid,
            "display_name": instance.display_name,
            "email": instance.email,
            "tenant_name": instance.tenant_name,
            "suspended": instance.suspended,
            "max_buckets": instance.max_buckets,
            "quota_max_size_bytes": instance.quota_max_size_bytes,
            "quota_max_objects": instance.quota_max_objects,
            "credential_ref": instance.credential_ref,
            "parameters": instance.parameters,
        }
    elif name == "CephRGWBucketDesiredState":
        values = {
            "name": instance.name,
            "owner_uid": _related_name(instance.owner),
            "placement_target": instance.placement_target,
            "versioning_enabled": instance.versioning_enabled,
            "quota_max_size_bytes": instance.quota_max_size_bytes,
            "quota_max_objects": instance.quota_max_objects,
            "lifecycle_policy": instance.lifecycle_policy,
            "parameters": instance.parameters,
        }
    else:  # pragma: no cover - guarded by can_generate before call
        raise KeyError(f"{name} is not a supported desired-state model")

    return values


def can_generate(instance: Any) -> bool:
    """Whether the instance's model can generate an operation."""

    return type(instance).__name__ in SPECS


def build_operation(instance: Any, *, requested_by: Any = None) -> Any:
    """Create and persist a ``CephOperation`` from a desired-state instance.

    The generated operation is a non-destructive ``reconcile`` request that the
    existing plan/apply engine can preview and execute.
    """

    from netbox_ceph.choices import CephOperationTypeChoices
    from netbox_ceph.models import CephOperation

    model_name = type(instance).__name__
    request = build_request(model_name, _instance_values(instance))
    operation = CephOperation(
        cluster=instance.cluster,
        provider=instance.provider,
        operation_type=CephOperationTypeChoices.TYPE_RECONCILE,
        target_kind=request["target_kind"],
        target_ref=request["target_ref"],
        desired=request["desired"],
        is_destructive=False,
        confirmation_required=False,
        requested_by=requested_by,
    )
    operation.save()
    return operation
