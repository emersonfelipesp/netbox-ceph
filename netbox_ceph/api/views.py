"""DRF viewsets for the netbox-ceph plugin API.

Inventory resources are read-only. The ``CephOperation`` and ``CephProvider``
viewsets expose write-action endpoints (``plan``/``apply``/``reconcile``) that
delegate to ``netbox_ceph.services.operation_actions`` — the same service the
web action views use, so the REST API and the UI share one implementation.
"""

from __future__ import annotations

from netbox.api.authentication import TokenPermissions
from netbox.api.viewsets import NetBoxModelViewSet
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied
from rest_framework.response import Response
from users.models import Token

from netbox_ceph import filtersets
from netbox_ceph.api import serializers
from netbox_ceph.jobs import CEPH_SYNC_QUEUE_NAME, CephSyncJob
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
from netbox_ceph.services.operation_actions import (
    OperationActionError,
    approve_and_apply_operation,
    plan_operation,
    reconcile_provider,
)

_READ_ONLY_HTTP_METHODS = ("get", "head", "options")
_READ_ONLY_WITH_DETAIL_POST_HTTP_METHODS = ("get", "post", "head", "options")

# OperationActionError.kind -> HTTP status for action endpoints.
_ERROR_STATUS = {
    "invalid": status.HTTP_400_BAD_REQUEST,
    "forbidden": status.HTTP_403_FORBIDDEN,
    "unsupported": status.HTTP_409_CONFLICT,
    "unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
    "backend": status.HTTP_502_BAD_GATEWAY,
}


class CephOperationActionPermissions(TokenPermissions):
    """Map operation actions to the custom two-person permission model."""

    action_permissions = {
        "create": (
            "netbox_ceph.request_cephoperation",
            "netbox_ceph.apply_cephoperation",
        ),
        "plan": (
            "netbox_ceph.request_cephoperation",
            "netbox_ceph.apply_cephoperation",
        ),
        "apply": ("netbox_ceph.approve_cephoperation",),
        "approve_and_apply": ("netbox_ceph.approve_cephoperation",),
    }

    def _custom_permissions(self, view) -> tuple[str, ...] | None:
        return self.action_permissions.get(getattr(view, "action", ""))

    def has_permission(self, request, view):
        permissions = self._custom_permissions(view)
        if permissions is None:
            return super().has_permission(request, view)
        if isinstance(request.auth, Token) and not self._verify_write_permission(request):
            return False
        user = getattr(request, "user", None)
        return bool(user and user.is_authenticated and user.has_perms(permissions))

    def has_object_permission(self, request, view, obj):
        permissions = self._custom_permissions(view)
        if permissions is None:
            return super().has_object_permission(request, view, obj)
        if isinstance(request.auth, Token) and not self._verify_write_permission(request):
            return False
        user = getattr(request, "user", None)
        return bool(user and user.is_authenticated and user.has_perms(permissions, obj))


def _authenticated_user(request):
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return user
    return None


def _request_data_value(request, key: str) -> object | None:
    data = getattr(request, "data", None)
    if hasattr(data, "get"):
        return data.get(key)
    return None


def _action_error_response(viewset, exc: OperationActionError) -> Response:
    """Translate an ``OperationActionError`` into a DRF ``Response``.

    When the failure produced a persisted run (orchestrator errors during
    apply/reconcile) the run is serialized; otherwise a ``detail`` message is
    returned. ``kind`` selects the HTTP status code.
    """

    resp_status = _ERROR_STATUS.get(exc.kind, status.HTTP_502_BAD_GATEWAY)
    detail = {
        "reason": getattr(exc, "reason", "operation_failed"),
        "detail": exc.message,
        **getattr(exc, "recovery", {}),
    }
    payload: dict[str, object] = {"detail": detail}
    if exc.run is not None:
        payload["run"] = serializers.CephOperationRunSerializer(
            exc.run,
            context=viewset.get_serializer_context(),
        ).data
    return Response(payload, status=resp_status)


class CephPluginSettingsViewSet(NetBoxModelViewSet):
    queryset = CephPluginSettings.objects.all()
    serializer_class = serializers.CephPluginSettingsSerializer


class CephClusterViewSet(NetBoxModelViewSet):
    queryset = CephCluster.objects.select_related("endpoint", "proxmox_cluster").all()
    serializer_class = serializers.CephClusterSerializer
    filterset_class = filtersets.CephClusterFilterSet
    http_method_names = _READ_ONLY_WITH_DETAIL_POST_HTTP_METHODS

    def create(self, request, *args, **kwargs):
        raise MethodNotAllowed("POST")

    @action(detail=True, methods=["post"])
    def sync(self, request, pk=None):
        cluster = self.get_object()
        cluster_pk = getattr(cluster, "pk", pk)
        try:
            job = CephSyncJob.enqueue(
                user=_authenticated_user(request),
                queue_name=CEPH_SYNC_QUEUE_NAME,
                name=f"Ceph Sync: {cluster}",
                cluster_pk=cluster_pk,
                resources=_request_data_value(request, "resources"),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        job_data = getattr(job, "data", {})
        params: dict[str, object] = {}
        if isinstance(job_data, dict):
            ceph_sync = job_data.get("ceph_sync", {})
            if isinstance(ceph_sync, dict):
                raw_params = ceph_sync.get("params", {})
                if isinstance(raw_params, dict):
                    params = raw_params

        payload: dict[str, object] = {
            "job": getattr(job, "pk", None),
            "cluster": cluster_pk,
            "resources": params.get("resources", []),
        }
        if hasattr(job, "get_absolute_url"):
            payload["url"] = job.get_absolute_url()
        return Response(payload, status=status.HTTP_202_ACCEPTED)


class CephDaemonViewSet(NetBoxModelViewSet):
    queryset = CephDaemon.objects.select_related("endpoint", "cluster", "proxmox_node").all()
    serializer_class = serializers.CephDaemonSerializer
    filterset_class = filtersets.CephDaemonFilterSet
    http_method_names = _READ_ONLY_HTTP_METHODS


class CephOSDViewSet(NetBoxModelViewSet):
    queryset = CephOSD.objects.select_related("endpoint", "cluster", "proxmox_node").all()
    serializer_class = serializers.CephOSDSerializer
    filterset_class = filtersets.CephOSDFilterSet
    http_method_names = _READ_ONLY_HTTP_METHODS


class CephPoolViewSet(NetBoxModelViewSet):
    queryset = CephPool.objects.select_related("endpoint", "cluster").all()
    serializer_class = serializers.CephPoolSerializer
    filterset_class = filtersets.CephPoolFilterSet
    http_method_names = _READ_ONLY_HTTP_METHODS


class CephFilesystemViewSet(NetBoxModelViewSet):
    queryset = CephFilesystem.objects.select_related("endpoint", "cluster", "metadata_pool").all()
    serializer_class = serializers.CephFilesystemSerializer
    filterset_class = filtersets.CephFilesystemFilterSet
    http_method_names = _READ_ONLY_HTTP_METHODS


class CephCrushRuleViewSet(NetBoxModelViewSet):
    queryset = CephCrushRule.objects.select_related("endpoint", "cluster").all()
    serializer_class = serializers.CephCrushRuleSerializer
    filterset_class = filtersets.CephCrushRuleFilterSet
    http_method_names = _READ_ONLY_HTTP_METHODS


class CephFlagViewSet(NetBoxModelViewSet):
    queryset = CephFlag.objects.select_related("endpoint", "cluster").all()
    serializer_class = serializers.CephFlagSerializer
    filterset_class = filtersets.CephFlagFilterSet
    http_method_names = _READ_ONLY_HTTP_METHODS


class CephHealthCheckViewSet(NetBoxModelViewSet):
    queryset = CephHealthCheck.objects.select_related("endpoint", "cluster").all()
    serializer_class = serializers.CephHealthCheckSerializer
    filterset_class = filtersets.CephHealthCheckFilterSet
    http_method_names = _READ_ONLY_HTTP_METHODS


class CephRGWRealmViewSet(NetBoxModelViewSet):
    queryset = CephRGWRealm.objects.select_related("endpoint", "cluster").all()
    serializer_class = serializers.CephRGWRealmSerializer
    filterset_class = filtersets.CephRGWRealmFilterSet
    http_method_names = _READ_ONLY_HTTP_METHODS


class CephRGWZoneGroupViewSet(NetBoxModelViewSet):
    queryset = CephRGWZoneGroup.objects.select_related("endpoint", "cluster", "realm").all()
    serializer_class = serializers.CephRGWZoneGroupSerializer
    filterset_class = filtersets.CephRGWZoneGroupFilterSet
    http_method_names = _READ_ONLY_HTTP_METHODS


class CephRGWZoneViewSet(NetBoxModelViewSet):
    queryset = CephRGWZone.objects.select_related("endpoint", "cluster", "zonegroup").all()
    serializer_class = serializers.CephRGWZoneSerializer
    filterset_class = filtersets.CephRGWZoneFilterSet
    http_method_names = _READ_ONLY_HTTP_METHODS


class CephRGWPlacementTargetViewSet(NetBoxModelViewSet):
    queryset = CephRGWPlacementTarget.objects.select_related(
        "endpoint",
        "cluster",
        "zonegroup",
        "zone",
    ).all()
    serializer_class = serializers.CephRGWPlacementTargetSerializer
    filterset_class = filtersets.CephRGWPlacementTargetFilterSet
    http_method_names = _READ_ONLY_HTTP_METHODS


class CephRGWUserReflectedViewSet(NetBoxModelViewSet):
    queryset = CephRGWUserReflected.objects.select_related("endpoint", "cluster").all()
    serializer_class = serializers.CephRGWUserReflectedSerializer
    filterset_class = filtersets.CephRGWUserReflectedFilterSet
    http_method_names = _READ_ONLY_HTTP_METHODS


class CephRGWBucketReflectedViewSet(NetBoxModelViewSet):
    queryset = CephRGWBucketReflected.objects.select_related("endpoint", "cluster").all()
    serializer_class = serializers.CephRGWBucketReflectedSerializer
    filterset_class = filtersets.CephRGWBucketReflectedFilterSet
    http_method_names = _READ_ONLY_HTTP_METHODS


class CephRBDImageViewSet(NetBoxModelViewSet):
    queryset = CephRBDImage.objects.select_related("endpoint", "cluster").all()
    serializer_class = serializers.CephRBDImageSerializer
    filterset_class = filtersets.CephRBDImageFilterSet
    http_method_names = _READ_ONLY_HTTP_METHODS


class CephRBDSnapshotViewSet(NetBoxModelViewSet):
    queryset = CephRBDSnapshot.objects.select_related("endpoint", "cluster", "image").all()
    serializer_class = serializers.CephRBDSnapshotSerializer
    filterset_class = filtersets.CephRBDSnapshotFilterSet
    http_method_names = _READ_ONLY_HTTP_METHODS


class CephRBDCloneViewSet(NetBoxModelViewSet):
    queryset = CephRBDClone.objects.select_related(
        "endpoint",
        "cluster",
        "parent_image",
        "parent_snapshot",
    ).all()
    serializer_class = serializers.CephRBDCloneSerializer
    filterset_class = filtersets.CephRBDCloneFilterSet
    http_method_names = _READ_ONLY_HTTP_METHODS


class CephProviderViewSet(NetBoxModelViewSet):
    queryset = CephProvider.objects.select_related("cluster").all()
    serializer_class = serializers.CephProviderSerializer
    filterset_class = filtersets.CephProviderFilterSet

    @action(detail=True, methods=["post"])
    def reconcile(self, request, pk=None):
        provider = self.get_object()
        scope = request.data.get("scope") if isinstance(request.data, dict) else None
        if not isinstance(scope, dict):
            scope = None
        try:
            run = reconcile_provider(
                provider,
                actor=_authenticated_user(request),
                scope=scope,
            )
        except OperationActionError as exc:
            return _action_error_response(self, exc)
        return Response(
            serializers.CephOperationRunSerializer(
                run,
                context=self.get_serializer_context(),
            ).data
        )


class CephOperationViewSet(NetBoxModelViewSet):
    queryset = CephOperation.objects.select_related(
        "cluster",
        "provider",
        "confirmed_by",
        "requested_by",
    ).all()
    serializer_class = serializers.CephOperationSerializer
    filterset_class = filtersets.CephOperationFilterSet
    permission_classes = (CephOperationActionPermissions,)

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        queryset = CephOperation.objects.select_related(
            "cluster",
            "provider",
            "confirmed_by",
            "requested_by",
        ).all()
        user = _authenticated_user(request)
        if self.action in {"create", "plan"}:
            # Intersect both constraints on the same prospective/existing row.
            queryset = queryset.restrict(user, "request").restrict(user, "apply")
        elif self.action in {"apply", "approve_and_apply"}:
            queryset = queryset.restrict(user, "approve")
        self.queryset = queryset

    def perform_create(self, serializer):
        requester = _authenticated_user(self.request)
        if requester is None or not requester.has_perms(
            (
                "netbox_ceph.request_cephoperation",
                "netbox_ceph.apply_cephoperation",
            )
        ):
            raise PermissionDenied(
                "Creating a Ceph operation requires request and apply permissions."
            )
        authority_defaults = {
            "requested_by": requester,
            "requested_by_username": requester.get_username(),
            "status": "pending",
            "confirmed": False,
            "confirmed_by": None,
            "confirmed_at": None,
        }
        validated_data = serializer.validated_data
        if isinstance(validated_data, list):
            for item in validated_data:
                item.update(authority_defaults)
        else:
            validated_data.update(authority_defaults)
        # Preserve NetBox's atomic save + _validate_objects() lifecycle. The
        # queryset was already intersected across request/apply constraints.
        super().perform_create(serializer)

    def perform_update(self, serializer):
        operation = serializer.instance
        if (
            operation.status != "pending"
            or operation.plans.exists()
            or operation.approvals.exists()
            or operation.runs.exists()
        ):
            raise PermissionDenied(
                "Operations become immutable after planning or audit evidence exists."
            )
        serializer.save()

    def perform_destroy(self, instance):
        if (
            instance.status != "pending"
            or instance.plans.exists()
            or instance.approvals.exists()
            or instance.runs.exists()
        ):
            raise PermissionDenied("Only untouched pending operation requests may be deleted.")
        super().perform_destroy(instance)

    @action(detail=True, methods=["post"])
    def plan(self, request, pk=None):
        operation = self.get_object()
        try:
            plan, validations = plan_operation(
                operation,
                requested_by=_authenticated_user(request),
            )
        except OperationActionError as exc:
            return _action_error_response(self, exc)
        return Response(
            {
                "plan": serializers.CephPlanSerializer(
                    plan,
                    context=self.get_serializer_context(),
                ).data,
                "validations": serializers.CephValidationResultSerializer(
                    validations,
                    many=True,
                    context=self.get_serializer_context(),
                ).data,
            }
        )

    @action(detail=True, methods=["post"])
    def apply(self, request, pk=None):
        """Compatibility alias for the token-transient approve-and-apply action."""

        return self._approve_and_apply(request)

    @action(detail=True, methods=["post"], url_path="approve-and-apply")
    def approve_and_apply(self, request, pk=None):
        return self._approve_and_apply(request)

    def _approve_and_apply(self, request):
        operation = self.get_object()
        try:
            run = approve_and_apply_operation(
                operation,
                approver=_authenticated_user(request),
            )
        except OperationActionError as exc:
            return _action_error_response(self, exc)
        return Response(
            serializers.CephOperationRunSerializer(
                run,
                context=self.get_serializer_context(),
            ).data
        )


class CephPlanViewSet(NetBoxModelViewSet):
    queryset = CephPlan.objects.select_related("operation").all()
    serializer_class = serializers.CephPlanSerializer
    filterset_class = filtersets.CephPlanFilterSet
    http_method_names = _READ_ONLY_HTTP_METHODS


class CephOperationApprovalViewSet(NetBoxModelViewSet):
    queryset = CephOperationApproval.objects.select_related(
        "operation",
        "plan",
        "requester",
        "approver",
    ).all()
    serializer_class = serializers.CephOperationApprovalSerializer
    filterset_class = filtersets.CephOperationApprovalFilterSet
    http_method_names = _READ_ONLY_HTTP_METHODS


class CephValidationResultViewSet(NetBoxModelViewSet):
    queryset = CephValidationResult.objects.select_related("plan", "operation").all()
    serializer_class = serializers.CephValidationResultSerializer
    filterset_class = filtersets.CephValidationResultFilterSet
    http_method_names = _READ_ONLY_HTTP_METHODS


class CephOperationRunViewSet(NetBoxModelViewSet):
    queryset = CephOperationRun.objects.select_related(
        "operation",
        "plan",
        "provider",
        "approval",
        "actor",
    ).all()
    serializer_class = serializers.CephOperationRunSerializer
    filterset_class = filtersets.CephOperationRunFilterSet
    http_method_names = _READ_ONLY_HTTP_METHODS


class CephDriftRecordViewSet(NetBoxModelViewSet):
    queryset = CephDriftRecord.objects.select_related("cluster", "provider").all()
    serializer_class = serializers.CephDriftRecordSerializer
    filterset_class = filtersets.CephDriftRecordFilterSet
    http_method_names = _READ_ONLY_HTTP_METHODS


class CephMetricSnapshotViewSet(NetBoxModelViewSet):
    queryset = CephMetricSnapshot.objects.select_related("cluster", "provider").all()
    serializer_class = serializers.CephMetricSnapshotSerializer
    filterset_class = filtersets.CephMetricSnapshotFilterSet
    http_method_names = _READ_ONLY_HTTP_METHODS


# Desired-state config models are fully writable (NetBox is the source of truth).
class CephPoolDesiredStateViewSet(NetBoxModelViewSet):
    queryset = CephPoolDesiredState.objects.select_related("cluster", "provider").all()
    serializer_class = serializers.CephPoolDesiredStateSerializer
    filterset_class = filtersets.CephPoolDesiredStateFilterSet


class CephFilesystemDesiredStateViewSet(NetBoxModelViewSet):
    queryset = CephFilesystemDesiredState.objects.select_related(
        "cluster", "provider", "metadata_pool"
    ).all()
    serializer_class = serializers.CephFilesystemDesiredStateSerializer
    filterset_class = filtersets.CephFilesystemDesiredStateFilterSet


class CephRBDImageDesiredStateViewSet(NetBoxModelViewSet):
    queryset = CephRBDImageDesiredState.objects.select_related(
        "cluster", "provider", "clone_parent_image"
    ).all()
    serializer_class = serializers.CephRBDImageDesiredStateSerializer
    filterset_class = filtersets.CephRBDImageDesiredStateFilterSet


class CephRBDSnapshotDesiredStateViewSet(NetBoxModelViewSet):
    queryset = CephRBDSnapshotDesiredState.objects.select_related(
        "cluster", "provider", "image"
    ).all()
    serializer_class = serializers.CephRBDSnapshotDesiredStateSerializer
    filterset_class = filtersets.CephRBDSnapshotDesiredStateFilterSet


class CephRGWRealmDesiredStateViewSet(NetBoxModelViewSet):
    queryset = CephRGWRealmDesiredState.objects.select_related("cluster", "provider").all()
    serializer_class = serializers.CephRGWRealmDesiredStateSerializer
    filterset_class = filtersets.CephRGWRealmDesiredStateFilterSet


class CephRGWZoneDesiredStateViewSet(NetBoxModelViewSet):
    queryset = CephRGWZoneDesiredState.objects.select_related("cluster", "provider", "realm").all()
    serializer_class = serializers.CephRGWZoneDesiredStateSerializer
    filterset_class = filtersets.CephRGWZoneDesiredStateFilterSet


class CephRGWUserDesiredStateViewSet(NetBoxModelViewSet):
    queryset = CephRGWUserDesiredState.objects.select_related("cluster", "provider").all()
    serializer_class = serializers.CephRGWUserDesiredStateSerializer
    filterset_class = filtersets.CephRGWUserDesiredStateFilterSet


class CephRGWBucketDesiredStateViewSet(NetBoxModelViewSet):
    queryset = CephRGWBucketDesiredState.objects.select_related(
        "cluster", "provider", "owner"
    ).all()
    serializer_class = serializers.CephRGWBucketDesiredStateSerializer
    filterset_class = filtersets.CephRGWBucketDesiredStateFilterSet
