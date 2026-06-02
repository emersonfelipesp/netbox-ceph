"""URL routes for netbox-ceph."""

from __future__ import annotations

from django.urls import include, path
from utilities.urls import get_model_urls

from netbox_ceph import views
from netbox_ceph.sitemap import SitemapView

app_name = "netbox_ceph"

_MODEL_ROUTES = (
    ("cephcluster", "clusters"),
    ("cephdaemon", "daemons"),
    ("cephosd", "osds"),
    ("cephpool", "pools"),
    ("cephfilesystem", "filesystems"),
    ("cephcrushrule", "crush-rules"),
    ("cephflag", "flags"),
    ("cephhealthcheck", "health-checks"),
    ("cephpluginsettings", "settings"),
    ("cephprovider", "providers"),
    ("cephoperation", "operations"),
    ("cephplan", "plans"),
    ("cephvalidationresult", "validation-results"),
    ("cephoperationrun", "operation-runs"),
    ("cephdriftrecord", "drift-records"),
    ("cephmetricsnapshot", "metric-snapshots"),
)

urlpatterns = [
    path("", views.CephHomeView.as_view(), name="home"),
    path("v2/", views.CephV2DashboardView.as_view(), name="ceph_v2_dashboard"),
    path("sitemap.txt", SitemapView.as_view(), name="sitemap"),
    path(
        "settings/edit/",
        views.settings_singleton_redirect,
        name="cephpluginsettings_singleton_edit",
    ),
]

for _model_name, _slug in _MODEL_ROUTES:
    urlpatterns += [
        path(
            f"{_slug}/<int:pk>/",
            include(get_model_urls("netbox_ceph", _model_name)),
        ),
        path(
            f"{_slug}/",
            include(get_model_urls("netbox_ceph", _model_name, detail=False)),
        ),
    ]
