"""Disposable PostgreSQL/Redis configuration for real NetBox integration tests."""

from __future__ import annotations

import os
from importlib.util import find_spec

from netbox.configuration_testing import *  # noqa: F403
from netbox.configuration_testing import PLUGINS as BASE_PLUGINS


def _optional_plugin_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().casefold() in {"1", "true", "yes", "on"}


PLUGINS = [*BASE_PLUGINS]
if (
    _optional_plugin_enabled("NETBOX_TEST_ENABLE_BRANCHING")
    and find_spec("netbox_branching") is not None
):
    from netbox_branching.utilities import DynamicSchemaDict

    PLUGINS.append("netbox_branching")
PLUGINS.append("netbox_proxbox")
if _optional_plugin_enabled("NETBOX_TEST_ENABLE_PDM") and find_spec("netbox_pdm") is not None:
    PLUGINS.append("netbox_pdm")
PLUGINS.append("netbox_ceph")

DATABASES["default"]["HOST"] = os.environ.get("NETBOX_TEST_DB_HOST", "127.0.0.1")  # noqa: F405
DATABASES["default"]["PORT"] = int(os.environ.get("NETBOX_TEST_DB_PORT", "5432"))  # noqa: F405
for redis_config in REDIS.values():  # noqa: F405
    redis_config["HOST"] = os.environ.get("NETBOX_TEST_REDIS_HOST", "127.0.0.1")
    redis_config["PORT"] = int(os.environ.get("NETBOX_TEST_REDIS_PORT", "6379"))

if "netbox_branching" in PLUGINS:
    DATABASES = DynamicSchemaDict(DATABASES)  # noqa: F405
    DATABASE_ROUTERS = ["netbox_branching.database.BranchAwareRouter"]
