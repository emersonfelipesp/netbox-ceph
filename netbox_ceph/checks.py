"""Django system checks for persisted netbox-ceph security invariants."""

from __future__ import annotations

from typing import Any

from django.core.checks import Tags, Warning, register
from django.core.exceptions import ValidationError
from django.db import OperationalError, ProgrammingError

from netbox_ceph.models.providers import CephProvider
from netbox_ceph.validators import validate_credential_reference


def _invalid_provider_ids() -> tuple[object, ...]:
    """Return invalid provider IDs without exposing their stored references."""

    invalid_ids: list[object] = []
    providers = CephProvider.objects.exclude(credential_ref="").values_list("pk", "credential_ref")
    for provider_id, credential_ref in providers.iterator():
        try:
            validate_credential_reference(credential_ref)
        except ValidationError:
            invalid_ids.append(provider_id)
    return tuple(invalid_ids)


@register(Tags.security)
def check_provider_credential_references(
    app_configs: Any = None,
    **kwargs: Any,
) -> list[Warning]:
    """Report existing invalid provider rows without changing them.

    A warning, not an error: a legacy row must not block migrate or startup.
    """

    try:
        invalid_ids = _invalid_provider_ids()
    except (OperationalError, ProgrammingError):
        return []
    return [
        Warning(
            "A CephProvider row contains an invalid credential_ref.",
            hint=(
                "Replace or clear the opaque credential reference for "
                f"CephProvider id={provider_id}. The stored value is not shown."
            ),
            obj=CephProvider,
            id="netbox_ceph.W002",
        )
        for provider_id in invalid_ids
    ]
