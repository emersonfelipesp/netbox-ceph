"""Pure-python tests for Ceph v2 payload redaction."""

from __future__ import annotations

from netbox_ceph.services.redaction import redact_secrets


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
