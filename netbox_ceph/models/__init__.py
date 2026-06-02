"""Persisted models for the netbox-ceph plugin."""

from netbox_ceph.models.ceph import (
    CephCluster,
    CephCrushRule,
    CephDaemon,
    CephFilesystem,
    CephFlag,
    CephHealthCheck,
    CephOSD,
    CephPluginSettings,
    CephPool,
)
from netbox_ceph.models.desired_state import (
    CephFilesystemDesiredState,
    CephPoolDesiredState,
    CephRBDImageDesiredState,
    CephRBDSnapshotDesiredState,
)
from netbox_ceph.models.metrics import CephMetricSnapshot
from netbox_ceph.models.operations import (
    CephDriftRecord,
    CephOperation,
    CephOperationRun,
    CephPlan,
    CephValidationResult,
)
from netbox_ceph.models.providers import CephProvider

__all__ = [
    "CephCluster",
    "CephCrushRule",
    "CephDaemon",
    "CephDriftRecord",
    "CephFilesystem",
    "CephFilesystemDesiredState",
    "CephFlag",
    "CephHealthCheck",
    "CephMetricSnapshot",
    "CephOSD",
    "CephOperation",
    "CephOperationRun",
    "CephPlan",
    "CephPluginSettings",
    "CephPool",
    "CephPoolDesiredState",
    "CephProvider",
    "CephRBDImageDesiredState",
    "CephRBDSnapshotDesiredState",
    "CephValidationResult",
]
