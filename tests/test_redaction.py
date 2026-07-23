"""Pure-python tests for Ceph v2 payload redaction."""

from __future__ import annotations

import pytest

from netbox_ceph.services.redaction import (
    SecretBearingIntentError,
    redact_secrets,
    redact_text,
    validate_secret_free_intent,
)


def test_redact_secrets_masks_secret_like_keys_recursively() -> None:
    payload = {
        "name": "pool-a",
        "password": "hidden",
        "nested": {
            "apiToken": "hidden",
            "public": "visible",
            "items": [{"secret_key": "hidden"}, {"value": "visible"}],
        },
    }

    assert redact_secrets(payload) == {
        "name": "pool-a",
        "password": "***REDACTED***",
        "nested": {
            "apiToken": "***REDACTED***",
            "public": "visible",
            "items": [{"secret_key": "***REDACTED***"}, {"value": "visible"}],
        },
    }


def test_redact_secrets_does_not_mutate_input() -> None:
    payload = {"credential_ref": "vault/path", "data": {"name": "cluster"}}

    redacted = redact_secrets(payload)

    assert redacted["credential_ref"] == "***REDACTED***"
    assert payload["credential_ref"] == "vault/path"


def test_redact_text_masks_credentials_embedded_in_diagnostic_strings() -> None:
    canary = "https://root:password@pve.example/?token=CEPH-CANARY"
    diagnostic = f"failed url={canary} password=SECOND-CANARY Bearer THIRD-CANARY"

    redacted = redact_text(diagnostic)

    assert "CEPH-CANARY" not in redacted
    assert "SECOND-CANARY" not in redacted
    assert "THIRD-CANARY" not in redacted
    assert "https://***REDACTED***@pve.example/" in redacted


@pytest.mark.parametrize(
    "secret_key",
    (
        "password",
        "apiToken",
        "access-key",
        "secret_key",
        "clientSecret",
        "privateKey",
        "authorization",
    ),
)
def test_canonical_intent_rejects_normalized_secret_key_aliases(secret_key: str) -> None:
    with pytest.raises(SecretBearingIntentError):
        validate_secret_free_intent({"outer": [{"nested": {secret_key: "canary"}}]})


def test_canonical_intent_allows_only_a_valid_opaque_credential_reference() -> None:
    validate_secret_free_intent(
        {
            "credentialRef": "vault:rgw/alice-1",
            "monkey_count": 2,
            "keyring_policy": "managed-externally",
        }
    )

    with pytest.raises(SecretBearingIntentError):
        validate_secret_free_intent({"credential_ref": "raw secret with spaces"})
