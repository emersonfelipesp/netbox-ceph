# Models

`netbox-ceph` splits its models into two layers:

- **v1 — Reflected inventory** (`netbox_ceph.models.ceph`): read-only objects
  mirrored from Proxmox-managed Ceph state via
  [`proxbox-api`](https://github.com/emersonfelipesp/proxbox-api).
- **v2 — Control plane** (`netbox_ceph.models.{providers,operations,desired_state,metrics}`):
  writable NetBox objects used for desired-state management, operations, and
  audit records.

Every reflected model carries a foreign key to
`netbox_proxbox.ProxmoxEndpoint` so objects are scoped to the Proxmox cluster
they were discovered on.

---

## v1 — Reflected inventory

### CephPluginSettings

Singleton settings row (`get_solo()`). Controls branch lifecycle behaviour for
the Ceph sync job.

| Field | Type | Description |
|---|---|---|
| `branching_enabled` | bool | Require per-sync `netbox-branching` isolation; unavailable branching fails the job before writes |
| `branch_name_prefix` | str | Prefix for auto-created branch names (default `ceph-sync`) |
| `branch_on_conflict` | str | `fail` or `acknowledge` — what to do when a branch merge conflicts |

### CephCluster

Top-level Ceph cluster object.

| Field | Type | Description |
|---|---|---|
| `endpoint` | FK → ProxmoxEndpoint | Proxmox endpoint that hosts the cluster |
| `name` | str | Cluster name |
| `fsid` | str | Ceph cluster FSID (UUID) |
| `health` | str | Aggregate health status (HEALTH_OK / HEALTH_WARN / HEALTH_ERR) |
| `quorum_names` | JSON | List of MON names currently in quorum |
| `status` | JSON | Raw status JSON from the Proxmox API |

Unique constraint: `(endpoint, name)`.

### CephDaemon

Individual Ceph daemon (MON, MGR, OSD, MDS, RGW, etc.).

| Field | Type | Description |
|---|---|---|
| `endpoint` | FK → ProxmoxEndpoint | |
| `daemon_type` | str | Daemon type choice |
| `name` | str | Daemon name |
| `daemon_id` | str | Unique ID within the type |
| `host` | str | Host the daemon runs on |
| `state` | str | Runtime state |
| `version` | str | Ceph software version |
| `metadata` | JSON | Raw daemon metadata |

Unique constraint: `(endpoint, daemon_type, name)`.

### CephOSD

OSD map entry.

| Field | Type | Description |
|---|---|---|
| `endpoint` | FK → ProxmoxEndpoint | |
| `osd_id` | int | Numeric OSD ID |
| `host` | str | Host the OSD runs on |
| `up` | bool | OSD up flag |
| `in_cluster` | bool | OSD in-cluster flag |
| `device_class` | str | Device class (`hdd`, `ssd`, `nvme`, …) |
| `weight` | float | CRUSH weight |
| `used_bytes` | int | Bytes consumed |
| `available_bytes` | int | Bytes free |
| `total_bytes` | int | Total capacity |
| `pgs` | int | Number of placement groups |

Unique constraint: `(endpoint, osd_id)`.

### CephPool

Ceph pool configuration.

| Field | Type | Description |
|---|---|---|
| `endpoint` | FK → ProxmoxEndpoint | |
| `name` | str | Pool name |
| `pool_id` | int | Numeric pool ID |
| `size` | int | Replication size |
| `min_size` | int | Minimum replication size for I/O |
| `pg_num` | int | Placement group count |
| `pg_autoscale_mode` | str | `on`, `warn`, or `off` |
| `crush_rule` | str | CRUSH rule name |
| `application` | str | Pool application tag (`rbd`, `cephfs`, `rgw`) |
| `used_bytes` | int | Bytes consumed |
| `available_bytes` | int | Bytes available |
| `total_bytes` | int | Total capacity |

Unique constraint: `(endpoint, name)`.

### CephFilesystem

CephFS filesystem metadata.

| Field | Type | Description |
|---|---|---|
| `endpoint` | FK → ProxmoxEndpoint | |
| `name` | str | Filesystem name |
| `data_pools` | JSON | List of data pool names |
| `metadata_pool` | FK → CephPool | Metadata pool |
| `standby_count_wanted` | int | Desired standby MDS count |

Unique constraint: `(endpoint, name)`.

### CephCrushRule

CRUSH rule entry.

| Field | Type | Description |
|---|---|---|
| `endpoint` | FK → ProxmoxEndpoint | |
| `name` | str | Rule name |
| `rule_id` | int | Numeric rule ID |
| `rule_type` | str | Rule type |
| `device_class` | str | Device class target |
| `steps` | JSON | Rule step list |
| `raw` | JSON | Full raw rule JSON |

Unique constraint: `(endpoint, name)`.

### CephFlag

Cluster-wide Ceph flag.

| Field | Type | Description |
|---|---|---|
| `endpoint` | FK → ProxmoxEndpoint | |
| `name` | str | Flag name |
| `enabled` | bool | Whether the flag is set |
| `value` | str | Current value |
| `raw` | JSON | Raw flag JSON |

Unique constraint: `(endpoint, name)`.

### CephHealthCheck

Individual health check from the cluster's health detail.

| Field | Type | Description |
|---|---|---|
| `endpoint` | FK → ProxmoxEndpoint | |
| `name` | str | Health check code (e.g. `OSD_DOWN`) |
| `severity` | str | `HEALTH_WARN` or `HEALTH_ERR` |
| `summary` | str | Human-readable summary |
| `detail` | str | Extended detail |
| `source` | str | Source module |
| `first_seen_at` | datetime | First observation time |
| `last_seen_at` | datetime | Most recent observation time |

Unique constraint: `(endpoint, name)`.

### RGW reflected models

The following models mirror RGW (RADOS Gateway / S3) objects from Proxmox:

| Model | Description |
|---|---|
| `CephRGWRealm` | RGW realm |
| `CephRGWZoneGroup` | Zone group within a realm |
| `CephRGWZone` | Zone within a zone group |
| `CephRGWPlacementTarget` | Placement target within a zone |
| `CephRGWUserReflected` | Reflected RGW user (no secrets stored) |
| `CephRGWBucketReflected` | Reflected S3 bucket |

All RGW models carry an `endpoint` FK and are scoped to the cluster they were
discovered on. RGW access keys and secrets are **never stored** in NetBox.

Sync these via the `rgw` sync resource (see [Sync Jobs](sync.md)).

### RBD reflected models

The following models mirror RBD (RADOS Block Device) objects from Proxmox:

| Model | Description |
|---|---|
| `CephRBDImage` | RBD image |
| `CephRBDSnapshot` | RBD snapshot |
| `CephRBDClone` | RBD clone |

Sync these via the `rbd` sync resource (see [Sync Jobs](sync.md)).

---

## v2 — Control plane

The v2 layer adds writable NetBox objects for desired-state management,
operations, and audit records. v1 reflected inventory remains read-only.

### CephProvider

Identifies an external system (Proxmox, Ceph Dashboard, Prometheus, …) that
can plan, apply, or reconcile Ceph state. Stores connection metadata but
**never stores credentials** — `credential_ref` is an opaque pointer to secrets
held by proxbox-api.

`credential_ref` is validated everywhere it can be written. The shared policy
in `netbox_ceph.validators.validate_credential_reference` (backed by
`services.redaction.validate_credential_ref`) accepts only a bounded opaque
pointer — up to 255 characters from `A-Z a-z 0-9 . _ : / @ -`, starting with a
letter or digit, no whitespace — and rejects recognizable credential material
such as AWS access keys, GitHub and GitLab tokens, Slack tokens, JWTs, Stripe or
OpenAI keys, and URLs carrying `user:password@`. Bare 32/40/64-character hex
digests are an *advisory* shape: they are usually leaked digests but can also
be a legitimate opaque id (a dashless UUID), so a newly submitted hex value is
rejected while a stored one that is re-saved unchanged is accepted — an
existing provider whose reference is a bare hex id can still be edited, and
`W002` keeps reporting it until an operator replaces it. The unambiguous token
and URL shapes are rejected even when unchanged. The shape list is a tripwire,
not proof: an unrecognized secret that fits the pointer charset still passes,
so the policy complements, rather than replaces, keeping secrets in the secret
store. The rule is applied by `CephProvider.clean()` (which passes the row's
persisted value as `stored=`), by the `CephProviderForm` field, and by the
`CephProviderSerializer` field; the two field validators run without the stored
value, so any value actually typed or sent faces the full policy — including an
API request that re-sends the same bare-hex value. To leave a legacy hex
reference untouched, omit `credential_ref` from the API payload or leave the
form field blank.

The reference is write-only on every surface: the API serializer never
returns it, the provider table does not list it, and the form renders a
password-style input that never shows the saved value. Leaving the form field
blank keeps the stored reference; clearing it requires an explicit API write
of an empty string.

Existing rows are not rewritten. The Django system check
`netbox_ceph.W002` (`netbox_ceph.checks.check_provider_credential_references`)
reports, as a warning that never blocks `migrate` or startup, the ids of providers whose stored reference fails the policy so an
operator can replace them; it never prints the stored value and stays silent
until the plugin's tables exist.

### CephOperation

Requested control-plane action. Stores the target kind, target reference,
operation type, exact Proxmox execution node, and desired payload. Drives the
plan/apply workflow.

### CephPlan

Provider-generated preview of what a `CephOperation` would do, bound to backend
and plugin endpoints, provider identity/kind, execution node, request digest,
endpoint revision, and a secret-free local-configuration digest.

### CephOperationApproval

Token-free independent-approval audit row. An expiring unique issuance-owner
lease serializes the backend approval POST; no approval token or hash is stored.

### CephValidationResult

Plan-stage findings attached to a `CephPlan`.

### CephOperationRun

Audit record for each backend apply attempt, including task references and
status. The optional historical link is database-enforced one-to-one for every
approval-backed run.

### CephDriftRecord

Latest desired-versus-actual comparison for a cluster or specific object.

### CephMetricSnapshot

Latest metric payload keyed by scope and object (populated by future telemetry
flows).

### Desired-state models

Writable configuration objects that express the intended state of Ceph
resources. See [Desired State](v2/desired-state.md) for the full model
reference.

| Model | Covers |
|---|---|
| `CephPoolDesiredState` | Pool replication, PG policy, quotas |
| `CephFilesystemDesiredState` | CephFS MDS placement and pool mapping |
| `CephRBDImageDesiredState` | RBD image layout, features, clone intent |
| `CephRBDSnapshotDesiredState` | RBD snapshot protection and lifecycle |
| `CephRGWRealmDesiredState` | RGW realm configuration |
| `CephRGWZoneDesiredState` | RGW zone topology |
| `CephRGWUserDesiredState` | RGW user quota and policy (no secrets) |
| `CephRGWBucketDesiredState` | S3 bucket versioning, lifecycle, quota |
