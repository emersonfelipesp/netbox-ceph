"""Views for netbox-ceph.

All inventory models are exposed as read-only object/list views in v1. Only
``CephPluginSettings`` is editable from the UI to toggle branch-aware sync.
"""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import TemplateView
from netbox.views import generic
from utilities.permissions import resolve_permission
from utilities.views import (
    ContentTypePermissionRequiredMixin,
    ViewTab,
    register_model_view,
)

from netbox_ceph import filtersets, forms, tables
from netbox_ceph.choices import CephDriftStatusChoices, CephOperationStatusChoices
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
    CephOperationApproval,
    CephOperationRun,
    CephOSD,
    CephPlan,
    CephPluginSettings,
    CephPool,
    CephPoolDesiredState,
    CephProvider,
    CephRBDClone,
    CephRBDImage,
    CephRBDImageDesiredState,
    CephRBDSnapshot,
    CephRBDSnapshotDesiredState,
    CephRGWBucketDesiredState,
    CephRGWBucketReflected,
    CephRGWPlacementTarget,
    CephRGWRealm,
    CephRGWRealmDesiredState,
    CephRGWUserDesiredState,
    CephRGWUserReflected,
    CephRGWZone,
    CephRGWZoneDesiredState,
    CephRGWZoneGroup,
    CephValidationResult,
)
from netbox_ceph.services.desired_state_operations import build_operation
from netbox_ceph.services.operation_actions import (
    OperationActionError,
    approve_and_apply_operation,
    plan_operation,
    reconcile_provider,
)

_OPERATION_GENERATING_DESIRED_STATE_MODELS = (
    CephPoolDesiredState,
    CephFilesystemDesiredState,
)


def _action_user(request):
    user = getattr(request, "user", None)
    return user if user is not None and user.is_authenticated else None


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
_register_readonly(
    CephRGWRealm,
    tables.CephRGWRealmTable,
    filtersets.CephRGWRealmFilterSet,
    forms.CephRGWRealmFilterForm,
)
_register_readonly(
    CephRGWZoneGroup,
    tables.CephRGWZoneGroupTable,
    filtersets.CephRGWZoneGroupFilterSet,
    forms.CephRGWZoneGroupFilterForm,
)
_register_readonly(
    CephRGWZone,
    tables.CephRGWZoneTable,
    filtersets.CephRGWZoneFilterSet,
    forms.CephRGWZoneFilterForm,
)
_register_readonly(
    CephRGWPlacementTarget,
    tables.CephRGWPlacementTargetTable,
    filtersets.CephRGWPlacementTargetFilterSet,
    forms.CephRGWPlacementTargetFilterForm,
)
_register_readonly(
    CephRGWUserReflected,
    tables.CephRGWUserReflectedTable,
    filtersets.CephRGWUserReflectedFilterSet,
    forms.CephRGWUserReflectedFilterForm,
)
_register_readonly(
    CephRGWBucketReflected,
    tables.CephRGWBucketReflectedTable,
    filtersets.CephRGWBucketReflectedFilterSet,
    forms.CephRGWBucketReflectedFilterForm,
)
_register_readonly(
    CephRBDImage,
    tables.CephRBDImageTable,
    filtersets.CephRBDImageFilterSet,
    forms.CephRBDImageFilterForm,
)
_register_readonly(
    CephRBDSnapshot,
    tables.CephRBDSnapshotTable,
    filtersets.CephRBDSnapshotFilterSet,
    forms.CephRBDSnapshotFilterForm,
)
_register_readonly(
    CephRBDClone,
    tables.CephRBDCloneTable,
    filtersets.CephRBDCloneFilterSet,
    forms.CephRBDCloneFilterForm,
)
_register_writable(
    CephProvider,
    tables.CephProviderTable,
    filtersets.CephProviderFilterSet,
    forms.CephProviderFilterForm,
    forms.CephProviderForm,
)


@register_model_view(CephOperation)
class CephOperationView(generic.ObjectView):
    queryset = CephOperation.objects.all()


@register_model_view(CephOperation, "list", path="", detail=False)
class CephOperationListView(generic.ObjectListView):
    queryset = CephOperation.objects.all()
    table = tables.CephOperationTable
    filterset = filtersets.CephOperationFilterSet
    filterset_form = forms.CephOperationFilterForm


@register_model_view(CephOperation, "add", detail=False)
@register_model_view(CephOperation, "edit")
class CephOperationEditView(generic.ObjectEditView):
    queryset = CephOperation.objects.all()
    form = forms.CephOperationForm

    def dispatch(self, request, *args, **kwargs):
        if not kwargs:
            # ObjectEditView validates the saved row against ``self.queryset``
            # inside its transaction. Intersect both custom permission scopes
            # here so request/apply cannot be granted on different clusters.
            self.queryset = (
                CephOperation.objects.restrict(request.user, "request")
                .restrict(request.user, "apply")
                .all()
            )
        return super().dispatch(request, *args, **kwargs)

    def get_required_permission(self) -> str:
        if self._permission_action == "add":
            return "netbox_ceph.request_cephoperation"
        return super().get_required_permission()

    def alter_object(self, obj, request, url_args, url_kwargs):
        if obj.pk is None:
            obj.requested_by = request.user
            obj.requested_by_username = request.user.get_username()
            obj.status = CephOperationStatusChoices.STATUS_PENDING
            obj.confirmed = False
            return obj
        if (
            obj.status != CephOperationStatusChoices.STATUS_PENDING
            or obj.plans.exists()
            or obj.approvals.exists()
            or obj.runs.exists()
        ):
            raise PermissionDenied(
                "Operations become immutable after planning or audit evidence exists."
            )
        return obj


@register_model_view(CephOperation, "delete")
class CephOperationDeleteView(generic.ObjectDeleteView):
    queryset = CephOperation.objects.all()

    def get_object(self, **kwargs):
        obj = super().get_object(**kwargs)
        if (
            obj.status != CephOperationStatusChoices.STATUS_PENDING
            or obj.plans.exists()
            or obj.approvals.exists()
            or obj.runs.exists()
        ):
            raise PermissionDenied("Only untouched pending operation requests may be deleted.")
        return obj


_register_readonly(
    CephPlan,
    tables.CephPlanTable,
    filtersets.CephPlanFilterSet,
    forms.CephPlanFilterForm,
)
_register_readonly(
    CephValidationResult,
    tables.CephValidationResultTable,
    filtersets.CephValidationResultFilterSet,
    forms.CephValidationResultFilterForm,
)
_register_readonly(
    CephOperationApproval,
    tables.CephOperationApprovalTable,
    filtersets.CephOperationApprovalFilterSet,
    forms.CephOperationApprovalFilterForm,
)
_register_readonly(
    CephOperationRun,
    tables.CephOperationRunTable,
    filtersets.CephOperationRunFilterSet,
    forms.CephOperationRunFilterForm,
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
_register_writable(
    CephRBDImageDesiredState,
    tables.CephRBDImageDesiredStateTable,
    filtersets.CephRBDImageDesiredStateFilterSet,
    forms.CephRBDImageDesiredStateFilterForm,
    forms.CephRBDImageDesiredStateForm,
)
_register_writable(
    CephRBDSnapshotDesiredState,
    tables.CephRBDSnapshotDesiredStateTable,
    filtersets.CephRBDSnapshotDesiredStateFilterSet,
    forms.CephRBDSnapshotDesiredStateFilterForm,
    forms.CephRBDSnapshotDesiredStateForm,
)
_register_writable(
    CephRGWRealmDesiredState,
    tables.CephRGWRealmDesiredStateTable,
    filtersets.CephRGWRealmDesiredStateFilterSet,
    forms.CephRGWRealmDesiredStateFilterForm,
    forms.CephRGWRealmDesiredStateForm,
)
_register_writable(
    CephRGWZoneDesiredState,
    tables.CephRGWZoneDesiredStateTable,
    filtersets.CephRGWZoneDesiredStateFilterSet,
    forms.CephRGWZoneDesiredStateFilterForm,
    forms.CephRGWZoneDesiredStateForm,
)
_register_writable(
    CephRGWUserDesiredState,
    tables.CephRGWUserDesiredStateTable,
    filtersets.CephRGWUserDesiredStateFilterSet,
    forms.CephRGWUserDesiredStateFilterForm,
    forms.CephRGWUserDesiredStateForm,
)
_register_writable(
    CephRGWBucketDesiredState,
    tables.CephRGWBucketDesiredStateTable,
    filtersets.CephRGWBucketDesiredStateFilterSet,
    forms.CephRGWBucketDesiredStateFilterForm,
    forms.CephRGWBucketDesiredStateForm,
)


# ---------------------------------------------------------------------------
# Ceph v2 action views (UI buttons -> operation_actions service)
# ---------------------------------------------------------------------------


class _PostActionView(ContentTypePermissionRequiredMixin, View):
    """POST-only UI action that mutates a Ceph object, then redirects back.

    Shares ``netbox_ceph.services.operation_actions`` with the REST API so the
    button and the API endpoint behave identically. ``OperationActionError`` is
    surfaced as a flash message rather than an HTTP error code.
    """

    http_method_names = ["post"]
    model = None
    permission = ""
    action_label = "Action"
    object_permissions: tuple[str, ...] = ()

    def get_required_permission(self) -> str:
        return self.permission

    def perform(self, request, obj) -> tuple[str, str]:
        """Run the action; return (success message, redirect URL)."""

        raise NotImplementedError

    def post(self, request, *args, **kwargs):
        queryset = self.model.objects.all()
        for permission in self.object_permissions:
            action = resolve_permission(permission)[1]
            queryset = queryset.restrict(request.user, action)
        obj = get_object_or_404(queryset, pk=kwargs["pk"])
        try:
            message, redirect_url = self.perform(request, obj)
        except OperationActionError as exc:
            messages.error(request, f"{self.action_label} failed: {exc.message}")
            return redirect(obj.get_absolute_url())
        messages.success(request, message)
        return redirect(redirect_url)


@register_model_view(CephOperation, "plan", path="plan")
class CephOperationPlanView(_PostActionView):
    model = CephOperation
    permission = "netbox_ceph.request_cephoperation"
    additional_permissions = ("netbox_ceph.apply_cephoperation",)
    object_permissions = (
        "netbox_ceph.request_cephoperation",
        "netbox_ceph.apply_cephoperation",
    )
    action_label = "Plan"

    def perform(self, request, obj) -> tuple[str, str]:
        plan_operation(obj, requested_by=_action_user(request))
        return "Plan generated from the configured provider.", obj.get_absolute_url()


@register_model_view(CephOperation, "apply", path="apply")
class CephOperationApplyView(_PostActionView):
    model = CephOperation
    permission = "netbox_ceph.approve_cephoperation"
    object_permissions = ("netbox_ceph.approve_cephoperation",)
    action_label = "Approve and apply"

    def perform(self, request, obj) -> tuple[str, str]:
        run = approve_and_apply_operation(obj, approver=_action_user(request))
        return f"Approval/apply finished with status “{run.status}”.", obj.get_absolute_url()


@register_model_view(CephProvider, "reconcile", path="reconcile")
class CephProviderReconcileView(_PostActionView):
    model = CephProvider
    permission = "netbox_ceph.change_cephprovider"
    object_permissions = ("netbox_ceph.change_cephprovider",)
    action_label = "Reconcile"

    def perform(self, request, obj) -> tuple[str, str]:
        run = reconcile_provider(obj, actor=_action_user(request))
        return f"Reconcile finished with status “{run.status}”.", run.get_absolute_url()


class _GenerateOperationView(_PostActionView):
    """Generate a CephOperation from a desired-state row, then open it."""

    permission = "netbox_ceph.request_cephoperation"
    action_label = "Generate operation"

    def perform(self, request, obj) -> tuple[str, str]:
        if not request.user.has_perms(
            (
                "netbox_ceph.request_cephoperation",
                "netbox_ceph.apply_cephoperation",
            )
        ):
            raise PermissionDenied(
                "Generating a Ceph operation requires request and apply permissions."
            )
        operation = build_operation(obj, requested_by=_action_user(request))
        return "Operation generated from desired state.", operation.get_absolute_url()


for _ds_model in _OPERATION_GENERATING_DESIRED_STATE_MODELS:
    _view_cls = type(
        f"{_ds_model.__name__}GenerateOperationView",
        (_GenerateOperationView,),
        {"model": _ds_model},
    )
    register_model_view(_ds_model, "generate_operation", path="generate-operation")(_view_cls)
