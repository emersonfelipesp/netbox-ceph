"""Secret redaction helpers for Ceph v2 payloads."""

from __future__ import annotations

import re
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
_URL_USERINFO_PATTERN = re.compile(r"(?i)(https?://)[^\s/@]+@")
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[^\s,;]+")
_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(password|secret|token|api[_-]?key|access[_-]?key|credential)"
    r"(\s*[:=]\s*)[^\s&,;]+"
)
_CAMEL_BOUNDARY_PATTERN = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_CREDENTIAL_REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,254}$")
_CREDENTIAL_MATERIAL_PATTERNS = (
    re.compile(r"(?i)^https?://[^\s/@]+@"),
    re.compile(r"^(?:AKIA|ASIA)[A-Z0-9]{16}$"),
    re.compile(r"^gh(?:p|o|u|s|r)_[A-Za-z0-9]{20,}$"),
    re.compile(r"^github_pat_[A-Za-z0-9_]{20,}$"),
    re.compile(r"^eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$"),
    re.compile(r"^(?:sk|pk)_(?:live|test)_[A-Za-z0-9]{16,}$"),
    re.compile(r"^sk-(?:(?:proj|svcacct)-)?[A-Za-z0-9_-]{16,}$"),
    re.compile(r"^xox[abeprs]-[A-Za-z0-9-]{10,}$"),
    re.compile(r"^glpat-[A-Za-z0-9_-]{20,}$"),
)
# Shapes that are usually leaked digests but are also plausible opaque pointers
# (a dashless UUID, a content id). They block a *new* value and are reported for
# stored rows, but an unchanged stored value is accepted so a legacy row can
# still be edited.
_ADVISORY_MATERIAL_PATTERNS = (re.compile(r"^(?:[0-9a-f]{32}|[0-9a-f]{40}|[0-9a-f]{64})$"),)
_FORBIDDEN_SECRET_TOKENS = {"password", "passwd", "secret", "token", "credential"}
_FORBIDDEN_FLAT_KEYS = {
    "apikey",
    "accesskey",
    "authorization",
    "bearertoken",
    "clientsecret",
    "encryptionkey",
    "privatekey",
    "secretkey",
    "sessioncookie",
    "signingkey",
}


class SecretBearingIntentError(ValueError):
    """Raised when canonical NetBox intent contains credential material."""


def _normalized_key_parts(key: object) -> tuple[str, tuple[str, ...]]:
    separated = _CAMEL_BOUNDARY_PATTERN.sub("_", str(key))
    parts = tuple(part for part in re.split(r"[^A-Za-z0-9]+", separated.lower()) if part)
    return "".join(parts), parts


def validate_credential_ref(
    value: object,
    *,
    path: str = "credential_ref",
    stored: object = None,
) -> None:
    """Require a bounded opaque pointer and reject recognizable secret values.

    ``stored`` is the value already persisted for the same row. Advisory shapes
    (bare hex digests) are rejected for a new value but accepted when ``value``
    is exactly the stored one, so a legacy row survives unrelated edits; the
    unambiguous token and URL shapes are rejected regardless.
    """
    if value in (None, ""):
        return
    if not _is_opaque_pointer(value):
        raise SecretBearingIntentError(
            f"{path} must be an opaque credential reference, not credential material."
        )
    if value != stored and _matches_any(value, _ADVISORY_MATERIAL_PATTERNS):
        raise SecretBearingIntentError(
            f"{path} looks like a bare secret digest; use an opaque credential reference."
        )


def _matches_any(value: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(value) for pattern in patterns)


def _is_opaque_pointer(value: object) -> bool:
    return (
        isinstance(value, str)
        and _CREDENTIAL_REF_PATTERN.fullmatch(value) is not None
        and not _matches_any(value, _CREDENTIAL_MATERIAL_PATTERNS)
    )


def validate_secret_free_intent(payload: Any, *, path: str = "intent") -> None:
    """Reject secret-bearing keys recursively before canonical intent is stored.

    Key matching normalizes snake_case, kebab-case, and camelCase aliases. The
    sole credential-shaped exception is ``credential_ref``/``credentialRef``,
    whose value must match the bounded opaque-reference grammar.
    """

    if isinstance(payload, Mapping):
        for key, value in payload.items():
            flat_key, parts = _normalized_key_parts(key)
            child_path = f"{path}.{key}"
            if flat_key == "credentialref":
                validate_credential_ref(value, path=child_path)
                continue
            if (
                flat_key in _FORBIDDEN_FLAT_KEYS
                or any(part in _FORBIDDEN_SECRET_TOKENS for part in parts)
                or "key" in parts
            ):
                raise SecretBearingIntentError(
                    f"{child_path} is not permitted in canonical NetBox intent."
                )
            validate_secret_free_intent(value, path=child_path)
        return
    if isinstance(payload, (list, tuple, set, frozenset)):
        for index, value in enumerate(payload):
            validate_secret_free_intent(value, path=f"{path}[{index}]")


def _is_secret_key(key: object) -> bool:
    normalized = str(key).lower()
    return any(part in normalized for part in _SECRET_KEY_PARTS)


def redact_text(value: object) -> str:
    """Mask common credentials embedded in otherwise unstructured text."""

    text = str(value)
    text = _URL_USERINFO_PATTERN.sub(r"\1***REDACTED***@", text)
    text = _BEARER_PATTERN.sub(f"Bearer {_REDACTED}", text)
    return _ASSIGNMENT_PATTERN.sub(rf"\1\2{_REDACTED}", text)


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
    if isinstance(payload, str):
        return redact_text(payload)
    return payload
