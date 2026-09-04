"""NetBox Ceph plugin built on top of netbox-proxbox."""

from __future__ import annotations

__version__ = "0.0.1.post1"

from .compat import (
    PLUGIN_MAX_VERSION,
    PLUGIN_MIN_VERSION,
    register_netbox_compatibility_check,
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
        required_plugins = ["netbox_proxbox"]
        queues: list[str] = []

        def ready(self) -> None:
            super().ready()
            register_netbox_compatibility_check(self)
            from . import jobs  # noqa: F401 — registers CephSyncJob via JobRunner metaclass

    config = CephConfig
