"""Dependency-free migration evidence tests for the Ceph authority cutover."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

MIGRATION_PATH = (
    Path(__file__).parents[1] / "netbox_ceph/migrations/0007_ceph_plan_bound_approvals.py"
)
MIGRATIONS_DIRECTORY = MIGRATION_PATH.parent


def _migration_function():
    module = ast.parse(MIGRATION_PATH.read_text(encoding="utf-8"), filename=str(MIGRATION_PATH))
    function = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "retire_legacy_confirmation_authority"
    )
    namespace: dict[str, object] = {}
    exec(
        compile(ast.Module(body=[function], type_ignores=[]), str(MIGRATION_PATH), "exec"),
        namespace,
    )
    return namespace[function.name]


def test_authority_migration_uses_netbox_458_compatible_extras_ancestor() -> None:
    incompatible_nodes = {
        "0138_customfieldchoiceset_choice_colors",
        "0139_alter_customfieldchoiceset_extra_choices",
    }
    migration_sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(MIGRATIONS_DIRECTORY.glob("0*.py"))
    }

    assert "0134_owner" in migration_sources[MIGRATION_PATH.name]
    assert not {
        (name, node)
        for name, source in migration_sources.items()
        for node in incompatible_nodes
        if node in source
    }


def test_authority_migration_adds_lease_binding_and_one_run_constraints() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")

    for field in (
        "plugin_endpoint_id",
        "provider_id_snapshot",
        "provider_kind_snapshot",
        "execution_node",
        "local_config_digest",
        "issuance_reservation_id",
        "issuance_reservation_expires_at",
    ):
        assert f'"{field}"' in source
    assert "models.UUIDField(blank=True, editable=False, null=True, unique=True)" in source
    assert 'name="approval"' in source
    assert "models.OneToOneField(" in source
    assert 'related_name="run"' in source
    assert "status__in=" in source
    for retired_status in ("planning", "planned", "awaiting_confirmation", "applying"):
        assert f'"{retired_status}"' in source


def _resolve(value, lookup: str):
    for part in lookup.split("__"):
        value = getattr(value, part)
    return value


class _Query:
    def __init__(self, values):
        self.values = list(values)

    def exclude(self, **lookups):
        return _Query(
            value
            for value in self.values
            if not all(_resolve(value, key) == expected for key, expected in lookups.items())
        )

    def filter(self, **lookups):
        def matches(value):
            for lookup, expected in lookups.items():
                if lookup.endswith("__in"):
                    if _resolve(value, lookup.removesuffix("__in")) not in expected:
                        return False
                elif _resolve(value, lookup) != expected:
                    return False
            return True

        return _Query(value for value in self.values if matches(value))

    def select_related(self, *args):
        return self

    def update(self, **values):
        for record in self.values:
            for field, value in values.items():
                setattr(record, field, value)

    def __iter__(self):
        return iter(self.values)


class _Manager(_Query):
    def __init__(self, values):
        super().__init__(values)
        self.bulk_updates = []

    def bulk_update(self, values, fields):
        self.bulk_updates.append((list(values), tuple(fields)))


def test_authority_migration_preserves_legacy_actor_time_and_backfills_snapshots() -> None:
    legacy_time = datetime(2026, 7, 1, tzinfo=UTC)
    user = SimpleNamespace(pk=7, username="legacy-operator")
    operation = SimpleNamespace(
        status="planned",
        confirmed=True,
        confirmed_by=user,
        confirmed_at=legacy_time,
        requested_by=user,
        requested_by_id=user.pk,
        requested_by_username="",
    )
    plan = SimpleNamespace(
        status="valid",
        operation=operation,
        requester_id=None,
        requester_username="",
    )
    run = SimpleNamespace(actor=user, actor_username="")

    models = {
        "CephOperation": SimpleNamespace(objects=_Manager([operation])),
        "CephPlan": SimpleNamespace(objects=_Manager([plan])),
        "CephOperationRun": SimpleNamespace(objects=_Manager([run])),
    }
    apps = SimpleNamespace(get_model=lambda app_label, name: models[name])

    _migration_function()(apps, schema_editor=None)

    assert operation.status == "pending"
    assert operation.confirmed is False
    assert operation.confirmed_by is user
    assert operation.confirmed_at == legacy_time
    assert operation.requested_by_username == "legacy-operator"
    assert plan.status == "stale"
    assert plan.requester_id == user.pk
    assert plan.requester_username == "legacy-operator"
    assert run.actor_username == "legacy-operator"
