"""Sitemap view for netbox-ceph — serves a plain-text list of all plugin pages."""

from __future__ import annotations

from importlib.metadata import version as _pkg_version

from django.http import HttpRequest, HttpResponse
from django.views import View
from utilities.views import ConditionalLoginRequiredMixin

_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Home",
        [
            ("home", "/plugins/ceph/"),
            ("ceph-v2-dashboard", "/plugins/ceph/v2/"),
            ("sitemap", "/plugins/ceph/sitemap.txt"),
        ],
    ),
    (
        "Clusters",
        [
            ("clusters-list", "/plugins/ceph/clusters/"),
        ],
    ),
    (
        "Daemons",
        [
            ("daemons-list", "/plugins/ceph/daemons/"),
        ],
    ),
    (
        "OSDs",
        [
            ("osds-list", "/plugins/ceph/osds/"),
        ],
    ),
    (
        "Pools",
        [
            ("pools-list", "/plugins/ceph/pools/"),
        ],
    ),
    (
        "Filesystems",
        [
            ("filesystems-list", "/plugins/ceph/filesystems/"),
        ],
    ),
    (
        "CRUSH Rules",
        [
            ("crush-rules-list", "/plugins/ceph/crush-rules/"),
        ],
    ),
    (
        "Flags",
        [
            ("flags-list", "/plugins/ceph/flags/"),
        ],
    ),
    (
        "Health Checks",
        [
            ("health-checks-list", "/plugins/ceph/health-checks/"),
        ],
    ),
    (
        "Ceph v2",
        [
            ("providers-list", "/plugins/ceph/providers/"),
            ("operations-list", "/plugins/ceph/operations/"),
            ("plans-list", "/plugins/ceph/plans/"),
            ("validation-results-list", "/plugins/ceph/validation-results/"),
            ("operation-runs-list", "/plugins/ceph/operation-runs/"),
            ("drift-records-list", "/plugins/ceph/drift-records/"),
            ("metric-snapshots-list", "/plugins/ceph/metric-snapshots/"),
        ],
    ),
    (
        "Desired State",
        [
            ("pool-desired-states-list", "/plugins/ceph/pool-desired-states/"),
            (
                "filesystem-desired-states-list",
                "/plugins/ceph/filesystem-desired-states/",
            ),
        ],
    ),
]

# Detail pages that require a {pk} — excluded from the static sitemap.
# /plugins/ceph/clusters/{pk}/
# /plugins/ceph/daemons/{pk}/
# /plugins/ceph/osds/{pk}/
# /plugins/ceph/pools/{pk}/
# /plugins/ceph/filesystems/{pk}/
# /plugins/ceph/crush-rules/{pk}/
# /plugins/ceph/flags/{pk}/
# /plugins/ceph/health-checks/{pk}/
# /plugins/ceph/settings/{pk}/
# /plugins/ceph/settings/{pk}/edit/
# /plugins/ceph/providers/{pk}/
# /plugins/ceph/operations/{pk}/
# /plugins/ceph/plans/{pk}/
# /plugins/ceph/validation-results/{pk}/
# /plugins/ceph/operation-runs/{pk}/
# /plugins/ceph/drift-records/{pk}/
# /plugins/ceph/metric-snapshots/{pk}/


def _build_sitemap(base: str) -> list[str]:
    lines: list[str] = []
    try:
        version = _pkg_version("netbox-ceph")
        lines.append(f"# netbox-ceph {version} — plugin sitemap")
    except Exception:  # noqa: BLE001
        lines.append("# netbox-ceph — plugin sitemap")
    lines.append(f"# Base: {base}")
    for section, pages in _SECTIONS:
        lines.append("")
        lines.append(f"# {section}")
        for label, path in pages:
            lines.append(f"{base}{path}  # {label}")
    return lines


class SitemapView(ConditionalLoginRequiredMixin, View):
    def get(self, request: HttpRequest) -> HttpResponse:
        base = request.build_absolute_uri("/").rstrip("/")
        body = "\n".join(_build_sitemap(base)) + "\n"
        return HttpResponse(body, content_type="text/plain; charset=utf-8")
