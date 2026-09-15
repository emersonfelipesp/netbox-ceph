"""Shared Django validators for credential-reference fields."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from netbox_ceph.services.redaction import (
    SecretBearingIntentError,
    validate_credential_ref,
)


def validate_credential_reference(value: object, *, stored: object = None) -> None:
    """Adapt the pure credential-reference policy to Django field validation.

    Pass ``stored`` (the persisted value of the same row) from model ``clean()``
    so an unchanged legacy bare-hex reference is accepted; field and serializer
    validators run without it, so any newly submitted value faces the full policy.
    """

    try:
        validate_credential_ref(value, stored=stored)
    except SecretBearingIntentError as exc:
        raise ValidationError(
            _(str(exc)),
            code="invalid_credential_reference",
        ) from exc


def keep_stored_reference(submitted: object, stored: object) -> str:
    """Return the submitted reference, or the stored one when the field was left blank.

    The form widget never renders the saved value, so an unchanged edit submits an
    empty string; treating that as "keep" prevents every unrelated edit from
    clearing the reference. Clearing is an explicit API write of an empty string.
    """

    value = str(submitted or "")
    if value:
        return value
    return str(stored or "")
