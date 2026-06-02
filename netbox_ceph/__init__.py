"""NetBox Ceph plugin built on top of netbox-proxbox."""

from __future__ import annotations

__version__ = "0.0.1.post1"


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
        min_version = "4.5.8"
        max_version = "4.6.99"
        required_plugins = ["netbox_proxbox"]
        queues: list[str] = []

        def ready(self) -> None:
            super().ready()
            from . import jobs  # noqa: F401 — registers CephSyncJob via JobRunner metaclass

    config = CephConfig
