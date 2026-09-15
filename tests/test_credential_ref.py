"""Behavior tests for the CephProvider credential-reference policy."""

from __future__ import annotations

import ast
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from netbox_ceph.services.redaction import SecretBearingIntentError, validate_credential_ref

ROOT = Path(__file__).resolve().parents[1]

VALID_REFERENCES = (
    "vault://ceph/prod",
    "0123456789abcdef0123456789abcdef-ref",
    "openbao/kv/0123456789abcdef0123456789abcdef",
    "vault:kv/data/ceph@lab",
    "openbao/ceph-prod_01.v2",
    "a" * 255,
)

CREDENTIAL_MATERIAL = (
    pytest.param("AKIAABCDEFGHIJKLMNOP", id="aws-access-key"),
    pytest.param("ghp_" + "a" * 36, id="github-token"),
    pytest.param("github_pat_" + "a" * 40, id="github-fine-grained"),
    pytest.param("eyJhbGciOi.eyJzdWIiOi.abc-def_123", id="jwt"),
    pytest.param("sk_live_" + "a" * 24, id="stripe"),
    pytest.param("sk-proj-" + "a" * 32, id="openai"),
    pytest.param("https://user:hunter2@vault.example/kv", id="basic-auth-url"),
    pytest.param("xoxb-" + "1" * 12 + "-" + "2" * 12 + "-" + "a" * 24, id="slack-bot"),
    pytest.param("xoxp-" + "1" * 12 + "-" + "a" * 24, id="slack-user"),
    pytest.param("glpat-" + "a" * 20, id="gitlab-pat"),
    pytest.param("0123456789abcdef" * 2, id="hex-32"),
    pytest.param("0123456789abcdef" * 2 + "01234567", id="hex-40-shaped-pat"),
    pytest.param("0123456789abcdef" * 4, id="hex-64"),
)

MALFORMED_REFERENCES = (
    pytest.param("vault://ceph prod", id="whitespace"),
    pytest.param(" vault://ceph", id="leading-space"),
    pytest.param("vault://ceph\n", id="newline"),
    pytest.param("-vault", id="leading-dash"),
    pytest.param("a" * 256, id="too-long"),
    pytest.param("a long free text sentence with spaces", id="free-text"),
    pytest.param(12345, id="not-a-string"),
)


@pytest.mark.parametrize("value", VALID_REFERENCES)
def test_policy_accepts_bounded_opaque_references(value: str) -> None:
    validate_credential_ref(value)


@pytest.mark.parametrize("value", (None, ""))
def test_policy_accepts_an_absent_reference(value: object) -> None:
    validate_credential_ref(value)


@pytest.mark.parametrize("value", (*CREDENTIAL_MATERIAL, *MALFORMED_REFERENCES))
def test_policy_rejects_credential_material_and_malformed_references(value: object) -> None:
    with pytest.raises(SecretBearingIntentError, match="credential_ref must be an opaque"):
        validate_credential_ref(value)


def test_policy_error_names_the_field_path_without_echoing_the_value() -> None:
    with pytest.raises(SecretBearingIntentError) as excinfo:
        validate_credential_ref("ghp_" + "b" * 36, path="intent.credentialRef")

    message = str(excinfo.value)
    assert message.startswith("intent.credentialRef must be")
    assert "ghp_" not in message


def _load(module_name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class _ValidationError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.message = message
        self.code = code


@pytest.fixture
def django_stubs(monkeypatch: pytest.MonkeyPatch):
    exceptions = types.ModuleType("django.core.exceptions")
    exceptions.ValidationError = _ValidationError
    translation = types.ModuleType("django.utils.translation")
    translation.gettext_lazy = lambda value: value

    class Warning:
        def __init__(self, msg, *, hint=None, obj=None, id=None):
            self.msg = msg
            self.hint = hint
            self.obj = obj
            self.id = id

    checks = types.ModuleType("django.core.checks")
    checks.Warning = Warning
    checks.Tags = SimpleNamespace(security="security")
    registered: list[object] = []
    checks.register = lambda *tags: lambda func: registered.append(func) or func
    db = types.ModuleType("django.db")

    class OperationalError(Exception):
        pass

    class ProgrammingError(Exception):
        pass

    db.OperationalError = OperationalError
    db.ProgrammingError = ProgrammingError

    for name, module in {
        "django": types.ModuleType("django"),
        "django.core": types.ModuleType("django.core"),
        "django.core.exceptions": exceptions,
        "django.core.checks": checks,
        "django.utils": types.ModuleType("django.utils"),
        "django.utils.translation": translation,
        "django.db": db,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    return SimpleNamespace(registered=registered, OperationalError=OperationalError)


@pytest.fixture
def validators_module(django_stubs):
    return _load("tests._netbox_ceph_validators_under_test", "netbox_ceph/validators.py")


def test_django_validator_translates_policy_errors(validators_module) -> None:
    validators_module.validate_credential_reference("vault://ceph")

    with pytest.raises(_ValidationError) as excinfo:
        validators_module.validate_credential_reference("AKIAABCDEFGHIJKLMNOP")

    assert excinfo.value.code == "invalid_credential_reference"
    assert "opaque credential reference" in str(excinfo.value.message)


def _install_provider_model(monkeypatch: pytest.MonkeyPatch, rows, *, error=None):
    class _Query:
        def exclude(self, **kwargs):
            assert kwargs == {"credential_ref": ""}
            return self

        def values_list(self, *fields):
            assert fields == ("pk", "credential_ref")
            return self

        def iterator(self):
            if error is not None:
                raise error
            return iter(rows)

    providers = types.ModuleType("netbox_ceph.models.providers")
    providers.CephProvider = type("CephProvider", (), {"objects": _Query()})
    monkeypatch.setitem(sys.modules, "netbox_ceph.models.providers", providers)
    monkeypatch.setitem(
        sys.modules,
        "netbox_ceph.validators",
        _load("tests._netbox_ceph_validators_under_test", "netbox_ceph/validators.py"),
    )
    return providers.CephProvider


def test_system_check_reports_offending_rows_without_their_values(
    monkeypatch: pytest.MonkeyPatch, django_stubs
) -> None:
    secret = "ghp_" + "c" * 36
    model = _install_provider_model(
        monkeypatch, [(1, "vault://ceph"), (2, secret), (3, "bad value")]
    )
    checks = _load("tests._netbox_ceph_checks_under_test", "netbox_ceph/checks.py")

    errors = checks.check_provider_credential_references(app_configs=None)

    assert django_stubs.registered == [checks.check_provider_credential_references]
    assert [error.id for error in errors] == ["netbox_ceph.W002", "netbox_ceph.W002"]
    assert [error.obj for error in errors] == [model, model]
    assert "id=2" in errors[0].hint and "id=3" in errors[1].hint
    assert secret not in errors[0].hint and secret not in errors[0].msg
    assert "bad value" not in errors[1].hint


def test_system_check_is_silent_before_migrations_exist(
    monkeypatch: pytest.MonkeyPatch, django_stubs
) -> None:
    _install_provider_model(
        monkeypatch, [], error=django_stubs.OperationalError("relation does not exist")
    )
    checks = _load("tests._netbox_ceph_checks_under_test", "netbox_ceph/checks.py")

    assert checks.check_provider_credential_references() == []


def test_system_check_passes_for_valid_rows(monkeypatch: pytest.MonkeyPatch, django_stubs) -> None:
    _install_provider_model(monkeypatch, [(1, "vault://ceph"), (2, "openbao/ceph")])
    checks = _load("tests._netbox_ceph_checks_under_test", "netbox_ceph/checks.py")

    assert checks.check_provider_credential_references() == []


def _class_source(relative_path: str, class_name: str) -> ast.ClassDef:
    tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    raise AssertionError(f"{class_name} not found in {relative_path}")


def _field_keywords(class_node: ast.ClassDef, field_name: str) -> dict[str, ast.expr]:
    for node in class_node.body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and any(isinstance(t, ast.Name) and t.id == field_name for t in node.targets)
        ):
            return {keyword.arg: keyword.value for keyword in node.value.keywords}
    raise AssertionError(f"{field_name} is not declared on {class_node.name}")


def _validators_of(keywords: dict[str, ast.expr]) -> set[str]:
    validators = keywords["validators"]
    assert isinstance(validators, ast.Tuple | ast.List)
    return {element.id for element in validators.elts if isinstance(element, ast.Name)}


def test_provider_serializer_never_returns_the_reference() -> None:
    keywords = _field_keywords(
        _class_source("netbox_ceph/api/serializers.py", "CephProviderSerializer"),
        "credential_ref",
    )

    assert ast.literal_eval(keywords["write_only"]) is True
    assert ast.literal_eval(keywords["trim_whitespace"]) is False
    assert "validate_credential_reference" in _validators_of(keywords)


def test_provider_form_validates_and_never_renders_the_reference() -> None:
    form = _class_source("netbox_ceph/forms.py", "CephProviderForm")
    keywords = _field_keywords(form, "credential_ref")

    assert "validate_credential_reference" in _validators_of(keywords)
    widget = keywords["widget"]
    assert isinstance(widget, ast.Call) and widget.func.attr == "PasswordInput"
    assert {k.arg: ast.literal_eval(k.value) for k in widget.keywords} == {"render_value": False}
    assert ast.literal_eval(keywords["strip"]) is False
    assert any(
        isinstance(node, ast.FunctionDef) and node.name == "clean_credential_ref"
        for node in form.body
    )


def test_provider_model_clean_applies_the_shared_validator() -> None:
    model = _class_source("netbox_ceph/models/providers.py", "CephProvider")
    clean = next(n for n in model.body if isinstance(n, ast.FunctionDef) and n.name == "clean")
    called = {
        node.func.id
        for node in ast.walk(clean)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "validate_credential_reference" in called


def test_provider_table_does_not_expose_the_reference() -> None:
    table = _class_source("netbox_ceph/tables.py", "CephProviderTable")
    literals = {node.value for node in ast.walk(table) if isinstance(node, ast.Constant)}

    assert "credential_ref" not in literals


def test_form_clean_delegates_to_the_keep_stored_reference_helper() -> None:
    form_class = _class_source("netbox_ceph/forms.py", "CephProviderForm")
    clean = next(
        n
        for n in form_class.body
        if isinstance(n, ast.FunctionDef) and n.name == "clean_credential_ref"
    )
    called = {
        node.func.id
        for node in ast.walk(clean)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "keep_stored_reference" in called


@pytest.mark.parametrize(
    ("submitted", "stored", "expected"),
    [
        ("", "vault://ceph", "vault://ceph"),
        (None, "vault://ceph", "vault://ceph"),
        ("vault://new", "vault://ceph", "vault://new"),
        ("", "", ""),
        ("", None, ""),
    ],
    ids=["blank-keeps", "none-keeps", "replace", "create-blank", "create-none"],
)
def test_keep_stored_reference(
    validators_module, submitted: object, stored: object, expected: str
) -> None:
    assert validators_module.keep_stored_reference(submitted, stored) == expected
