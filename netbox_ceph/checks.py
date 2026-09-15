"""Django system checks for persisted netbox-ceph security invariants."""

from __future__ import annotations

from typing import Any

from django.core.checks import Tags, Warning, register
from django.core.exceptions import ValidationError
from django.db import OperationalError, ProgrammingError

from netbox_ceph.models.desired_state import CephRGWUserDesiredState
from netbox_ceph.models.providers import CephProvider
from netbox_ceph.validators import validate_credential_reference


def _invalid_reference_ids(model: type) -> tuple[object, ...]:
    """Return ids of ``model`` rows whose stored credential_ref fails the policy.

    The stored values are never returned or logged.
    """

    invalid_ids: list[object] = []
    rows = model.objects.exclude(credential_ref="").values_list("pk", "credential_ref")
    for row_id, credential_ref in rows.iterator():
        try:
            validate_credential_reference(credential_ref)
        except ValidationError:
            invalid_ids.append(row_id)
    return tuple(invalid_ids)


def _invalid_provider_ids() -> tuple[object, ...]:
    """Return invalid provider IDs without exposing their stored references."""

    return _invalid_reference_ids(CephProvider)


def _credential_reference_warnings(model: type, check_id: str) -> list[Warning]:
    """Build one warning per offending row; silent before the tables exist."""

    try:
        invalid_ids = _invalid_reference_ids(model)
    except (OperationalError, ProgrammingError):
        return []
    return [
        Warning(
            f"A {model.__name__} row contains an invalid credential_ref.",
            hint=(
                "Replace or clear the opaque credential reference for "
                f"{model.__name__} id={row_id}. The stored value is not shown."
            ),
            obj=model,
            id=check_id,
        )
        for row_id in invalid_ids
    ]


@register(Tags.security)
def check_provider_credential_references(
    app_configs: Any = None,
    **kwargs: Any,
) -> list[Warning]:
    """Report existing invalid provider rows without changing them.

    A warning, not an error: a legacy row must not block migrate or startup.
    """

    return _credential_reference_warnings(CephProvider, "netbox_ceph.W002")


@register(Tags.security)
def check_rgw_user_credential_references(
    app_configs: Any = None,
    **kwargs: Any,
) -> list[Warning]:
    """Report RGW/S3 user desired-state rows whose credential_ref fails the policy."""

    return _credential_reference_warnings(CephRGWUserDesiredState, "netbox_ceph.W003")
