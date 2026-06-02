"""Views for netbox-ceph.

All inventory models are exposed as read-only object/list views in v1. Only
``CephPluginSettings`` is editable from the UI to toggle branch-aware sync.
"""

from __future__ import annotations

from django.db.models import Count
from django.shortcuts import redirect
from django.views import View
from django.views.generic import TemplateView
from netbox.views import generic
from utilities.views import (
    ContentTypePermissionRequiredMixin,
    ViewTab,
    register_model_view,
)

from netbox_ceph import filtersets, forms, tables
from netbox_ceph.choices import CephDriftStatusChoices
from netbox_ceph.models import (
    CephCluster,
    CephCrushRule,
    CephDaemon,
    CephDriftRecord,
    CephFilesystem,
    CephFilesystemDesiredState,
    CephFlag,
    CephHealthCheck,
    CephMetricSnapshot,
    CephOperation,
    CephOperationRun,
    CephOSD,
    CephPlan,
    CephPluginSettings,
    CephPool,
    CephPoolDesiredState,
    CephProvider,
    CephValidationResult,
)


class CephHomeView(generic.ObjectListView):
    """Plugin home landing redirects to the cluster list for v1."""

    queryset = CephCluster.objects.all()
    table = tables.CephClusterTable
    filterset = filtersets.CephClusterFilterSet
    filterset_form = forms.CephClusterFilterForm
    template_name = "netbox_ceph/home.html"


class CephV2DashboardView(ContentTypePermissionRequiredMixin, TemplateView):
    """Ceph v2 dashboard aggregates rendered from NetBox state only."""

    template_name = "netbox_ceph/ceph_v2_dashboard.html"

    def get_required_permission(self) -> str:
        return "netbox_ceph.view_cephcluster"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "cluster_health": CephCluster.objects.values("health")
                .annotate(count=Count("pk"))
                .order_by("health"),
                "provider_status": CephProvider.objects.values("status")
                .annotate(count=Count("pk"))
                .order_by("status"),
                "recent_operations": CephOperation.objects.select_related(
                    "cluster",
                    "provider",
                    "requested_by",
                ).order_by("-created", "-pk")[:10],
                "drift_count": CephDriftRecord.objects.exclude(
                    drift_status=CephDriftStatusChoices.STATUS_IN_SYNC
                ).count(),
                "latest_metric_snapshots": CephMetricSnapshot.objects.select_related(
                    "cluster",
                    "provider",
                ).order_by("-captured_at", "-created", "-pk")[:10],
            }
        )
        return context


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@register_model_view(CephPluginSettings)
class CephPluginSettingsView(generic.ObjectView):
    queryset = CephPluginSettings.objects.all()


@register_model_view(CephPluginSettings, "edit")
class CephPluginSettingsEditView(generic.ObjectEditView):
    queryset = CephPluginSettings.objects.all()
    form = forms.CephPluginSettingsForm


class SettingsSingletonRedirectView(
    ContentTypePermissionRequiredMixin,
    View,
):
    """UI helper: always edit the singleton settings row.

    Guarded so that the implicit ``get_or_create`` inside ``get_solo`` is not
    reachable to anonymous users when ``LOGIN_REQUIRED=False``, and so that
    only users with ``change_cephpluginsettings`` can land on the editor.
    """

    def get_required_permission(self) -> str:
        return "netbox_ceph.change_cephpluginsettings"

    def get(self, request, *args, **kwargs):
        obj = CephPluginSettings.get_solo()
        return redirect("plugins:netbox_ceph:cephpluginsettings_edit", pk=obj.pk)


settings_singleton_redirect = SettingsSingletonRedirectView.as_view()


# ---------------------------------------------------------------------------
# Cluster
# ---------------------------------------------------------------------------


@register_model_view(CephCluster)
class CephClusterView(generic.ObjectView):
    queryset = CephCluster.objects.select_related("endpoint", "proxmox_cluster")


@register_model_view(CephCluster, "list", path="", detail=False)
class CephClusterListView(generic.ObjectListView):
    queryset = CephCluster.objects.select_related("endpoint", "proxmox_cluster")
    table = tables.CephClusterTable
    filterset = filtersets.CephClusterFilterSet
    filterset_form = forms.CephClusterFilterForm
    actions = {}  # read-only list (no add/edit/delete buttons)


# Tabs on the cluster detail surface
@register_model_view(CephCluster, "daemons", path="daemons")
class CephClusterDaemonsTabView(generic.ObjectChildrenView):
    queryset = CephCluster.objects.all()
    child_model = CephDaemon
    table = tables.CephDaemonTable
    filterset = filtersets.CephDaemonFilterSet
    template_name = "generic/object_children.html"
    actions = {}
    tab = ViewTab(label="Daemons", badge=lambda obj: obj.daemons.count())

    def get_children(self, request, parent):
        return parent.daemons.select_related("endpoint", "proxmox_node")


@register_model_view(CephCluster, "osds", path="osds")
class CephClusterOSDsTabView(generic.ObjectChildrenView):
    queryset = CephCluster.objects.all()
    child_model = CephOSD
    table = tables.CephOSDTable
    filterset = filtersets.CephOSDFilterSet
    template_name = "generic/object_children.html"
    actions = {}
    tab = ViewTab(label="OSDs", badge=lambda obj: obj.osds.count())

    def get_children(self, request, parent):
        return parent.osds.select_related("endpoint", "proxmox_node")


@register_model_view(CephCluster, "pools", path="pools")
class CephClusterPoolsTabView(generic.ObjectChildrenView):
    queryset = CephCluster.objects.all()
    child_model = CephPool
    table = tables.CephPoolTable
    filterset = filtersets.CephPoolFilterSet
    template_name = "generic/object_children.html"
    actions = {}
    tab = ViewTab(label="Pools", badge=lambda obj: obj.pools.count())

    def get_children(self, request, parent):
        return parent.pools.select_related("endpoint")


# ---------------------------------------------------------------------------
# Generic read-only list/detail registrations
# ---------------------------------------------------------------------------


def _register_readonly(model, table_cls, fs_cls, form_cls):
    @register_model_view(model)
    class _View(generic.ObjectView):  # noqa: D401
        queryset = model.objects.all()

    @register_model_view(model, "list", path="", detail=False)
    class _ListView(generic.ObjectListView):  # noqa: D401
        queryset = model.objects.all()
        table = table_cls
        filterset = fs_cls
        filterset_form = form_cls
        actions = {}


def _register_writable(model, table_cls, fs_cls, filter_form_cls, model_form_cls):
    @register_model_view(model)
    class _View(generic.ObjectView):  # noqa: D401
        queryset = model.objects.all()

    @register_model_view(model, "list", path="", detail=False)
    class _ListView(generic.ObjectListView):  # noqa: D401
        queryset = model.objects.all()
        table = table_cls
        filterset = fs_cls
        filterset_form = filter_form_cls

    # Register the same edit view under both ``add`` (list path) and ``edit``
    # (detail path), mirroring NetBox core. The ``add`` registration is what
    # creates the ``<model>_add`` URL name referenced by the navigation
    # buttons; without it, reversing the nav link raises ``NoReverseMatch``
    # and 500s every page that renders the sidebar.
    @register_model_view(model, "add", detail=False)
    @register_model_view(model, "edit")
    class _EditView(generic.ObjectEditView):  # noqa: D401
        queryset = model.objects.all()
        form = model_form_cls

    @register_model_view(model, "delete")
    class _DeleteView(generic.ObjectDeleteView):  # noqa: D401
        queryset = model.objects.all()


_register_readonly(
    CephDaemon, tables.CephDaemonTable, filtersets.CephDaemonFilterSet, forms.CephDaemonFilterForm
)
_register_readonly(
    CephOSD, tables.CephOSDTable, filtersets.CephOSDFilterSet, forms.CephOSDFilterForm
)
_register_readonly(
    CephPool, tables.CephPoolTable, filtersets.CephPoolFilterSet, forms.CephPoolFilterForm
)
_register_readonly(
    CephFilesystem,
    tables.CephFilesystemTable,
    filtersets.CephFilesystemFilterSet,
    forms.CephFilesystemFilterForm,
)
_register_readonly(
    CephCrushRule,
    tables.CephCrushRuleTable,
    filtersets.CephCrushRuleFilterSet,
    forms.CephCrushRuleFilterForm,
)
_register_readonly(
    CephFlag, tables.CephFlagTable, filtersets.CephFlagFilterSet, forms.CephFlagFilterForm
)
_register_readonly(
    CephHealthCheck,
    tables.CephHealthCheckTable,
    filtersets.CephHealthCheckFilterSet,
    forms.CephHealthCheckFilterForm,
)
_register_writable(
    CephProvider,
    tables.CephProviderTable,
    filtersets.CephProviderFilterSet,
    forms.CephProviderFilterForm,
    forms.CephProviderForm,
)
_register_writable(
    CephOperation,
    tables.CephOperationTable,
    filtersets.CephOperationFilterSet,
    forms.CephOperationFilterForm,
    forms.CephOperationForm,
)
_register_writable(
    CephPlan,
    tables.CephPlanTable,
    filtersets.CephPlanFilterSet,
    forms.CephPlanFilterForm,
    forms.CephPlanForm,
)
_register_writable(
    CephValidationResult,
    tables.CephValidationResultTable,
    filtersets.CephValidationResultFilterSet,
    forms.CephValidationResultFilterForm,
    forms.CephValidationResultForm,
)
_register_writable(
    CephOperationRun,
    tables.CephOperationRunTable,
    filtersets.CephOperationRunFilterSet,
    forms.CephOperationRunFilterForm,
    forms.CephOperationRunForm,
)
_register_readonly(
    CephDriftRecord,
    tables.CephDriftRecordTable,
    filtersets.CephDriftRecordFilterSet,
    forms.CephDriftRecordFilterForm,
)
_register_readonly(
    CephMetricSnapshot,
    tables.CephMetricSnapshotTable,
    filtersets.CephMetricSnapshotFilterSet,
    forms.CephMetricSnapshotFilterForm,
)

# Desired-state config models are writable: NetBox is the source of truth.
# _register_writable registers add + edit + delete + list + detail; the `add`
# route is required by the navigation buttons (see views.py header note).
_register_writable(
    CephPoolDesiredState,
    tables.CephPoolDesiredStateTable,
    filtersets.CephPoolDesiredStateFilterSet,
    forms.CephPoolDesiredStateFilterForm,
    forms.CephPoolDesiredStateForm,
)
_register_writable(
    CephFilesystemDesiredState,
    tables.CephFilesystemDesiredStateTable,
    filtersets.CephFilesystemDesiredStateFilterSet,
    forms.CephFilesystemDesiredStateFilterForm,
    forms.CephFilesystemDesiredStateForm,
)
