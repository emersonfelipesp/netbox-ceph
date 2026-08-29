"""NetBox Ceph plugin built on top of netbox-proxbox."""

from __future__ import annotations

__version__ = "0.0.1.post1"

from .compat import (
    APPROVED_EXPERIMENTAL_NETBOX_DESIGNATION,
    APPROVED_EXPERIMENTAL_NETBOX_VERSION,
    PLUGIN_MAX_VERSION,
    PLUGIN_MIN_VERSION,
    register_netbox_compatibility_check,
    validate_held_netbox_release_identity,
)

try:
    from netbox.plugins import PluginConfig
except ModuleNotFoundError as exc:  # pragma: no cover - permits pure-python utility imports
    if exc.name != "netbox":
        raise
    config = None
else:

    class CephConfig(PluginConfig):
        """Plugin metadata for the read-only Ceph inventory package."""

        name = "netbox_ceph"
        verbose_name = "NetBox Ceph"
        description = "Read-only Ceph inventory via netbox-proxbox and proxbox-api"
        version = __version__
        author = "Emerson Felipe"
        author_email = "emersonfelipe.2003@gmail.com"
        base_url = "ceph"
        # Sourced from .compat so the stable and held-beta contracts are
        # declared in one place across the Proxbox plugin stack.
        min_version = PLUGIN_MIN_VERSION
        max_version = PLUGIN_MAX_VERSION
        approved_netbox_version = APPROVED_EXPERIMENTAL_NETBOX_VERSION
        approved_netbox_designation = APPROVED_EXPERIMENTAL_NETBOX_DESIGNATION
        required_plugins = ["netbox_proxbox"]
        queues: list[str] = []

        @classmethod
        def validate(cls, user_config: dict[str, object], netbox_version: str) -> None:
            """Apply stock bounds, then attest the held 4.7 release identity."""
            super().validate(user_config, netbox_version)
            validate_held_netbox_release_identity(cls, netbox_version)

        def ready(self) -> None:
            super().ready()
            register_netbox_compatibility_check(self)
            from . import jobs  # noqa: F401 — registers CephSyncJob via JobRunner metaclass

    config = CephConfig
