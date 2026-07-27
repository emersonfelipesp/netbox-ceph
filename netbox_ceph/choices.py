"""Choice sets for read-only Ceph inventory models."""

from django.utils.translation import gettext_lazy as _
from utilities.choices import ChoiceSet


class CephHealthChoices(ChoiceSet):
    """Ceph cluster/check health states."""

    key = "Ceph.health"

    HEALTH_OK = "HEALTH_OK"
    HEALTH_WARN = "HEALTH_WARN"
    HEALTH_ERR = "HEALTH_ERR"
    HEALTH_UNKNOWN = "unknown"

    CHOICES = [
        (HEALTH_OK, _("OK"), "green"),
        (HEALTH_WARN, _("Warning"), "yellow"),
        (HEALTH_ERR, _("Error"), "red"),
        (HEALTH_UNKNOWN, _("Unknown"), "gray"),
    ]


class CephDaemonTypeChoices(ChoiceSet):
    """Ceph daemon families mirrored in v1."""

    key = "CephDaemon.daemon_type"

    TYPE_MON = "mon"
    TYPE_MGR = "mgr"
    TYPE_MDS = "mds"
    TYPE_OSD = "osd"
    TYPE_UNKNOWN = "unknown"

    CHOICES = [
        (TYPE_MON, _("Monitor"), "blue"),
        (TYPE_MGR, _("Manager"), "purple"),
        (TYPE_MDS, _("Metadata server"), "cyan"),
        (TYPE_OSD, _("OSD"), "orange"),
        (TYPE_UNKNOWN, _("Unknown"), "gray"),
    ]


class CephDaemonStateChoices(ChoiceSet):
    """Common daemon state labels across PVE/Ceph payloads."""

    key = "CephDaemon.state"

    STATE_UNKNOWN = "unknown"
    STATE_ACTIVE = "active"
    STATE_STANDBY = "standby"
    STATE_RUNNING = "running"
    STATE_STOPPED = "stopped"
    STATE_ERROR = "error"

    CHOICES = [
        (STATE_UNKNOWN, _("Unknown"), "gray"),
        (STATE_ACTIVE, _("Active"), "green"),
        (STATE_STANDBY, _("Standby"), "blue"),
        (STATE_RUNNING, _("Running"), "green"),
        (STATE_STOPPED, _("Stopped"), "gray"),
        (STATE_ERROR, _("Error"), "red"),
    ]


class CephProviderKindChoices(ChoiceSet):
    """Backend provider families that can participate in Ceph v2 orchestration."""

    key = "CephProvider.kind"

    KIND_PROXMOX = "proxmox"
    KIND_DASHBOARD = "dashboard"
    KIND_RGW_ADMIN = "rgw_admin"
    KIND_PROMETHEUS = "prometheus"
    KIND_EXTERNAL = "external"

    CHOICES = [
        (KIND_PROXMOX, _("Proxmox"), "blue"),
        (KIND_DASHBOARD, _("Ceph Dashboard"), "purple"),
        (KIND_RGW_ADMIN, _("RGW Admin"), "cyan"),
        (KIND_PROMETHEUS, _("Prometheus"), "green"),
        (KIND_EXTERNAL, _("External"), "gray"),
    ]


class CephProviderStatusChoices(ChoiceSet):
    """Observed reachability/auth state for an orchestration provider."""

    key = "CephProvider.status"

    STATUS_UNKNOWN = "unknown"
    STATUS_OK = "ok"
    STATUS_DEGRADED = "degraded"
    STATUS_UNREACHABLE = "unreachable"
    STATUS_UNAUTHORIZED = "unauthorized"

    CHOICES = [
        (STATUS_UNKNOWN, _("Unknown"), "gray"),
        (STATUS_OK, _("OK"), "green"),
        (STATUS_DEGRADED, _("Degraded"), "yellow"),
        (STATUS_UNREACHABLE, _("Unreachable"), "red"),
        (STATUS_UNAUTHORIZED, _("Unauthorized"), "orange"),
    ]


class CephOperationTypeChoices(ChoiceSet):
    """High-level operation intents tracked by the Ceph v2 control plane."""

    key = "CephOperation.operation_type"

    TYPE_CREATE = "create"
    TYPE_UPDATE = "update"
    TYPE_DELETE = "delete"
    TYPE_APPLY = "apply"
    TYPE_RECONCILE = "reconcile"
    TYPE_CUSTOM = "custom"

    CHOICES = [
        (TYPE_CREATE, _("Create"), "green"),
        (TYPE_UPDATE, _("Update"), "blue"),
        (TYPE_DELETE, _("Delete"), "red"),
        (TYPE_APPLY, _("Apply"), "purple"),
        (TYPE_RECONCILE, _("Reconcile"), "cyan"),
        (TYPE_CUSTOM, _("Custom"), "gray"),
    ]


class CephOperationStatusChoices(ChoiceSet):
    """Lifecycle states for requested and executed Ceph v2 operations."""

    key = "CephOperation.status"

    STATUS_PENDING = "pending"
    STATUS_PLANNING = "planning"
    STATUS_PLANNED = "planned"
    STATUS_AWAITING_CONFIRMATION = "awaiting_confirmation"
    STATUS_APPLYING = "applying"
    STATUS_OUTCOME_UNKNOWN = "outcome_unknown"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"
    STATUS_UNSUPPORTED = "unsupported"

    CHOICES = [
        (STATUS_PENDING, _("Pending"), "gray"),
        (STATUS_PLANNING, _("Planning"), "blue"),
        (STATUS_PLANNED, _("Planned"), "cyan"),
        (STATUS_AWAITING_CONFIRMATION, _("Awaiting confirmation"), "yellow"),
        (STATUS_APPLYING, _("Applying"), "purple"),
        (STATUS_OUTCOME_UNKNOWN, _("Outcome unknown"), "orange"),
        (STATUS_SUCCEEDED, _("Succeeded"), "green"),
        (STATUS_FAILED, _("Failed"), "red"),
        (STATUS_CANCELLED, _("Cancelled"), "gray"),
        (STATUS_UNSUPPORTED, _("Unsupported"), "orange"),
    ]


class CephPlanStatusChoices(ChoiceSet):
    """Validation state for a generated operation plan."""

    key = "CephPlan.status"

    STATUS_DRAFT = "draft"
    STATUS_VALID = "valid"
    STATUS_INVALID = "invalid"
    STATUS_APPLIED = "applied"
    STATUS_STALE = "stale"

    CHOICES = [
        (STATUS_DRAFT, _("Draft"), "gray"),
        (STATUS_VALID, _("Valid"), "green"),
        (STATUS_INVALID, _("Invalid"), "red"),
        (STATUS_APPLIED, _("Applied"), "blue"),
        (STATUS_STALE, _("Stale"), "yellow"),
    ]


class CephApprovalStatusChoices(ChoiceSet):
    """Local audit state for a backend-issued Ceph plan approval."""

    key = "CephOperationApproval.status"

    STATUS_ISSUING = "issuing"
    STATUS_ISSUED = "issued"
    STATUS_APPLYING = "applying"
    STATUS_CONSUMED = "consumed"
    STATUS_OUTCOME_UNKNOWN = "outcome_unknown"
    STATUS_FAILED = "failed"
    STATUS_EXPIRED = "expired"

    CHOICES = [
        (STATUS_ISSUING, _("Issuing"), "blue"),
        (STATUS_ISSUED, _("Issued"), "cyan"),
        (STATUS_APPLYING, _("Applying"), "purple"),
        (STATUS_CONSUMED, _("Consumed"), "green"),
        (STATUS_OUTCOME_UNKNOWN, _("Outcome unknown"), "orange"),
        (STATUS_FAILED, _("Failed"), "red"),
        (STATUS_EXPIRED, _("Expired"), "gray"),
    ]


class CephDriftStatusChoices(ChoiceSet):
    """Comparison state between NetBox desired state and provider state."""

    key = "CephDriftRecord.drift_status"

    STATUS_IN_SYNC = "in_sync"
    STATUS_DRIFTED = "drifted"
    STATUS_MISSING_IN_PROVIDER = "missing_in_provider"
    STATUS_MISSING_IN_NETBOX = "missing_in_netbox"
    STATUS_UNKNOWN = "unknown"

    CHOICES = [
        (STATUS_IN_SYNC, _("In sync"), "green"),
        (STATUS_DRIFTED, _("Drifted"), "yellow"),
        (STATUS_MISSING_IN_PROVIDER, _("Missing in provider"), "orange"),
        (STATUS_MISSING_IN_NETBOX, _("Missing in NetBox"), "red"),
        (STATUS_UNKNOWN, _("Unknown"), "gray"),
    ]


class CephValidationSeverityChoices(ChoiceSet):
    """Severity levels for plan validation findings."""

    key = "CephValidationResult.severity"

    SEVERITY_INFO = "info"
    SEVERITY_WARNING = "warning"
    SEVERITY_ERROR = "error"
    SEVERITY_BLOCKER = "blocker"

    CHOICES = [
        (SEVERITY_INFO, _("Info"), "blue"),
        (SEVERITY_WARNING, _("Warning"), "yellow"),
        (SEVERITY_ERROR, _("Error"), "red"),
        (SEVERITY_BLOCKER, _("Blocker"), "purple"),
    ]


class CephPoolAutoscaleChoices(ChoiceSet):
    """Desired PG autoscale mode for a Ceph pool."""

    key = "CephPoolDesiredState.pg_autoscale_mode"

    MODE_ON = "on"
    MODE_WARN = "warn"
    MODE_OFF = "off"

    CHOICES = [
        (MODE_ON, _("On"), "green"),
        (MODE_WARN, _("Warn"), "yellow"),
        (MODE_OFF, _("Off"), "gray"),
    ]


class CephPoolApplicationChoices(ChoiceSet):
    """Intended application tag for a Ceph pool."""

    key = "CephPoolDesiredState.application"

    APP_RBD = "rbd"
    APP_CEPHFS = "cephfs"
    APP_RGW = "rgw"
    APP_OTHER = "other"

    CHOICES = [
        (APP_RBD, _("RBD"), "blue"),
        (APP_CEPHFS, _("CephFS"), "green"),
        (APP_RGW, _("RGW"), "yellow"),
        (APP_OTHER, _("Other"), "gray"),
    ]


class CephPoolCompressionChoices(ChoiceSet):
    """Desired compression mode for a Ceph pool."""

    key = "CephPoolDesiredState.compression_mode"

    MODE_NONE = "none"
    MODE_PASSIVE = "passive"
    MODE_AGGRESSIVE = "aggressive"
    MODE_FORCE = "force"

    CHOICES = [
        (MODE_NONE, _("None"), "gray"),
        (MODE_PASSIVE, _("Passive"), "blue"),
        (MODE_AGGRESSIVE, _("Aggressive"), "orange"),
        (MODE_FORCE, _("Force"), "red"),
    ]


class CephMetricScopeChoices(ChoiceSet):
    """Metric snapshot target scope."""

    key = "CephMetricSnapshot.scope"

    SCOPE_CLUSTER = "cluster"
    SCOPE_DAEMON = "daemon"
    SCOPE_POOL = "pool"
    SCOPE_OSD = "osd"
    SCOPE_CEPHFS = "cephfs"
    SCOPE_RGW = "rgw"
    SCOPE_RBD = "rbd"

    CHOICES = [
        (SCOPE_CLUSTER, _("Cluster"), "blue"),
        (SCOPE_DAEMON, _("Daemon"), "purple"),
        (SCOPE_POOL, _("Pool"), "cyan"),
        (SCOPE_OSD, _("OSD"), "orange"),
        (SCOPE_CEPHFS, _("CephFS"), "green"),
        (SCOPE_RGW, _("RGW"), "yellow"),
        (SCOPE_RBD, _("RBD"), "gray"),
    ]
