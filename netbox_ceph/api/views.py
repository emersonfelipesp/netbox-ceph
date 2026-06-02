"""DRF viewsets for the netbox-ceph plugin API.

All resources are read-only in v1: HTTP methods are restricted to GET/HEAD/OPTIONS.
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone
from netbox.api.viewsets import NetBoxModelViewSet
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from netbox_ceph import filtersets
from netbox_ceph.api import serializers
from netbox_ceph.choices import (
    CephOperationStatusChoices,
    CephPlanStatusChoices,
    CephValidationSeverityChoices,
)
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
    CephRBDImageDesiredState,
    CephRBDSnapshotDesiredState,
    CephValidationResult,
)
from netbox_ceph.services.http_client import CephBackendError
from netbox_ceph.services.orchestrator import (
    CephOrchestratorClient,
    CephOrchestratorUnavailable,
    CephOrchestratorUnsupported,
)

_READ_ONLY_HTTP_METHODS = ("get", "head", "options")


def _authenticated_user(request):
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return user
    return None


def _operation_payload(operation: CephOperation) -> dict[str, Any]:
    provider = operation.provider
    return {
        "id": operation.pk,
        "cluster_id": operation.cluster_id,
        "provider_id": operation.provider_id,
        "provider_kind": provider.kind if provider is not None else None,
        "provider_name": provider.name if provider is not None else None,
        "operation_type": operation.operation_type,
        "target_kind": operation.target_kind,
        "target_ref": operation.target_ref,
        "desired": operation.desired,
        "is_destructive": operation.is_destructive,
        "confirmation_required": operation.confirmation_required,
        "confirmed": operation.confirmed,
        "source_branch_schema_id": operation.source_branch_schema_id,
    }


def _choice_or_default(value: Any, choices: list[tuple[str, str, str]], default: str) -> str:
    allowed = {choice[0] for choice in choices}
    if value in allowed:
        return str(value)
    return default


def _plan_payload(response: dict[str, Any]) -> dict[str, Any]:
    plan = response.get("plan")
    if isinstance(plan, dict):
        return plan
    return response


def _validation_payloads(response: dict[str, Any], plan_payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = response.get("validations", plan_payload.get("validations", []))
    if not isinstance(candidates, list):
        return []
    return [item for item in candidates if isinstance(item, dict)]


def _latest_plan(operation: CephOperation) -> CephPlan | None:
    return operation.plans.order_by("-generated_at", "-created", "-pk").first()


def _refresh_plan(
    operation: CephOperation,
    response_payload: dict[str, Any],
) -> tuple[CephPlan, list[CephValidationResult]]:
    payload = _plan_payload(response_payload)
    plan = _latest_plan(operation) or CephPlan(operation=operation)
    plan.status = _choice_or_default(
        payload.get("status"),
        CephPlanStatusChoices.CHOICES,
        CephPlanStatusChoices.STATUS_DRAFT,
    )
    plan.summary = str(payload.get("summary", ""))
    plan.intended_changes = payload.get("intended_changes", [])
    plan.provider_target = str(payload.get("provider_target", ""))
    plan.blast_radius = payload.get("blast_radius", {})
    plan.expected_tasks = payload.get("expected_tasks", [])
    plan.rollback_limits = str(payload.get("rollback_limits", ""))
    plan.is_destructive = bool(payload.get("is_destructive", operation.is_destructive))
    plan.generated_at = timezone.now()
    plan.raw = response_payload
    plan.save()

    plan.validations.all().delete()
    validations: list[CephValidationResult] = []
    for item in _validation_payloads(response_payload, payload):
        validation = CephValidationResult.objects.create(
            plan=plan,
            operation=operation,
            severity=_choice_or_default(
                item.get("severity"),
                CephValidationSeverityChoices.CHOICES,
                CephValidationSeverityChoices.SEVERITY_INFO,
            ),
            code=str(item.get("code", "backend")),
            message=str(item.get("message", "")),
            target=str(item.get("target", "")),
        )
        validations.append(validation)
    return plan, validations


def _run_status(value: Any, default: str) -> str:
    if value == "ok":
        return CephOperationStatusChoices.STATUS_SUCCEEDED
    return _choice_or_default(value, CephOperationStatusChoices.CHOICES, default)


class CephPluginSettingsViewSet(NetBoxModelViewSet):
    queryset = CephPluginSettings.objects.all()
    serializer_class = serializers.CephPluginSettingsSerializer


class CephClusterViewSet(NetBoxModelViewSet):
    queryset = CephCluster.objects.select_related("endpoint", "proxmox_cluster").all()
    serializer_class = serializers.CephClusterSerializer
    filterset_class = filtersets.CephClusterFilterSet
    http_method_names = _READ_ONLY_HTTP_METHODS


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


class CephProviderViewSet(NetBoxModelViewSet):
    queryset = CephProvider.objects.select_related("cluster").all()
    serializer_class = serializers.CephProviderSerializer
    filterset_class = filtersets.CephProviderFilterSet


class CephOperationViewSet(NetBoxModelViewSet):
    queryset = CephOperation.objects.select_related(
        "cluster",
        "provider",
        "confirmed_by",
        "requested_by",
    ).all()
    serializer_class = serializers.CephOperationSerializer
    filterset_class = filtersets.CephOperationFilterSet

    @action(detail=True, methods=["post"])
    def plan(self, request, pk=None):
        operation = self.get_object()
        operation.status = CephOperationStatusChoices.STATUS_PLANNING
        if operation.requested_by_id is None:
            operation.requested_by = _authenticated_user(request)
        operation.save(update_fields=("status", "requested_by", "last_updated"))

        orchestrator = CephOrchestratorClient()
        try:
            response_payload = orchestrator.plan(_operation_payload(operation))
        except CephOrchestratorUnsupported as exc:
            operation.status = CephOperationStatusChoices.STATUS_UNSUPPORTED
            operation.save(update_fields=("status", "last_updated"))
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except CephOrchestratorUnavailable as exc:
            operation.status = CephOperationStatusChoices.STATUS_FAILED
            operation.save(update_fields=("status", "last_updated"))
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except CephBackendError as exc:
            operation.status = CephOperationStatusChoices.STATUS_FAILED
            operation.save(update_fields=("status", "last_updated"))
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        plan, validations = _refresh_plan(operation, response_payload)
        operation.status = CephOperationStatusChoices.STATUS_PLANNED
        operation.save(update_fields=("status", "last_updated"))
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
        operation = self.get_object()
        if operation.status != CephOperationStatusChoices.STATUS_PLANNED:
            return Response(
                {"detail": "Operation must be in planned status before apply."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        plan = _latest_plan(operation)
        if plan is None:
            return Response(
                {"detail": "Operation has no generated plan to apply."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = _authenticated_user(request)
        if request.data.get("confirmed") is True and not operation.confirmed:
            operation.confirmed = True
            operation.confirmed_by = user
            operation.confirmed_at = timezone.now()
            operation.save(
                update_fields=("confirmed", "confirmed_by", "confirmed_at", "last_updated")
            )

        if (operation.is_destructive or operation.confirmation_required) and not operation.confirmed:
            return Response(
                {"detail": "Destructive or confirmation-required operations need confirmed=True."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        started_at = timezone.now()
        run = CephOperationRun.objects.create(
            operation=operation,
            plan=plan,
            provider=operation.provider,
            status=CephOperationStatusChoices.STATUS_APPLYING,
            actor=user,
            source_branch_schema_id=operation.source_branch_schema_id,
            started_at=started_at,
        )
        operation.status = CephOperationStatusChoices.STATUS_APPLYING
        operation.save(update_fields=("status", "last_updated"))

        payload = {
            **_operation_payload(operation),
            "plan_id": plan.pk,
            "plan": plan.raw,
        }
        orchestrator = CephOrchestratorClient()
        try:
            response_payload = orchestrator.apply(payload)
        except CephOrchestratorUnsupported as exc:
            run.status = CephOperationStatusChoices.STATUS_UNSUPPORTED
            run.finished_at = timezone.now()
            run.error = str(exc)
            run.save(update_fields=("status", "finished_at", "error", "last_updated"))
            operation.status = CephOperationStatusChoices.STATUS_UNSUPPORTED
            operation.save(update_fields=("status", "last_updated"))
            return Response(
                serializers.CephOperationRunSerializer(
                    run,
                    context=self.get_serializer_context(),
                ).data,
                status=status.HTTP_409_CONFLICT,
            )
        except CephOrchestratorUnavailable as exc:
            run.status = CephOperationStatusChoices.STATUS_FAILED
            run.finished_at = timezone.now()
            run.error = str(exc)
            run.save(update_fields=("status", "finished_at", "error", "last_updated"))
            operation.status = CephOperationStatusChoices.STATUS_FAILED
            operation.save(update_fields=("status", "last_updated"))
            return Response(
                serializers.CephOperationRunSerializer(
                    run,
                    context=self.get_serializer_context(),
                ).data,
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except CephBackendError as exc:
            run.status = CephOperationStatusChoices.STATUS_FAILED
            run.finished_at = timezone.now()
            run.error = str(exc)
            run.save(update_fields=("status", "finished_at", "error", "last_updated"))
            operation.status = CephOperationStatusChoices.STATUS_FAILED
            operation.save(update_fields=("status", "last_updated"))
            return Response(
                serializers.CephOperationRunSerializer(
                    run,
                    context=self.get_serializer_context(),
                ).data,
                status=status.HTTP_502_BAD_GATEWAY,
            )

        run.status = _run_status(
            response_payload.get("status"),
            CephOperationStatusChoices.STATUS_SUCCEEDED,
        )
        run.provider_task_ref = str(
            response_payload.get("provider_task_ref") or response_payload.get("task_ref") or ""
        )
        run.finished_at = timezone.now()
        run.result = response_payload
        warnings = response_payload.get("warnings", [])
        run.warnings = warnings if isinstance(warnings, list) else [str(warnings)]
        run.save(
            update_fields=(
                "status",
                "provider_task_ref",
                "finished_at",
                "result",
                "warnings",
                "last_updated",
            )
        )
        operation.status = run.status
        operation.save(update_fields=("status", "last_updated"))
        if run.status == CephOperationStatusChoices.STATUS_SUCCEEDED:
            plan.status = CephPlanStatusChoices.STATUS_APPLIED
            plan.save(update_fields=("status", "last_updated"))
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


class CephValidationResultViewSet(NetBoxModelViewSet):
    queryset = CephValidationResult.objects.select_related("plan", "operation").all()
    serializer_class = serializers.CephValidationResultSerializer
    filterset_class = filtersets.CephValidationResultFilterSet


class CephOperationRunViewSet(NetBoxModelViewSet):
    queryset = CephOperationRun.objects.select_related(
        "operation",
        "plan",
        "provider",
        "actor",
    ).all()
    serializer_class = serializers.CephOperationRunSerializer
    filterset_class = filtersets.CephOperationRunFilterSet


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
