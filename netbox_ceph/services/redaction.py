"""Secret redaction helpers for Ceph v2 payloads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_SECRET_KEY_PARTS = (
    "secret",
    "password",
    "token",
    "key",
    "access_key",
    "secret_key",
    "credential",
)
_REDACTED = "***REDACTED***"


def _is_secret_key(key: object) -> bool:
    normalized = str(key).lower()
    return any(part in normalized for part in _SECRET_KEY_PARTS)


def redact_secrets(payload: Any) -> Any:
    """Return a copy of ``payload`` with secret-looking mapping values masked."""
    if isinstance(payload, Mapping):
        return {
            key: _REDACTED if _is_secret_key(key) else redact_secrets(value)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [redact_secrets(value) for value in payload]
    if isinstance(payload, tuple):
        return tuple(redact_secrets(value) for value in payload)
    if isinstance(payload, set):
        return {redact_secrets(value) for value in payload}
    return payload
