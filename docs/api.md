# REST API

`netbox-ceph` registers a `NetBoxRouter` at `/api/plugins/ceph/`. Every
endpoint supports the standard NetBox REST conventions: JSON responses,
Bearer token auth, `?limit=` / `?offset=` pagination, and `?format=api` for
the browsable API.

## v1 — Reflected inventory endpoints

These endpoints are **read-only** mirrors of Proxmox-managed Ceph state.

| Endpoint | Description |
|---|---|
| `/api/plugins/ceph/settings/` | `CephPluginSettings` singleton |
| `/api/plugins/ceph/clusters/` | Ceph clusters |
| `/api/plugins/ceph/daemons/` | Ceph daemons (MON, MGR, OSD, MDS, RGW) |
| `/api/plugins/ceph/osds/` | OSD map entries |
| `/api/plugins/ceph/pools/` | Pool configuration and usage |
| `/api/plugins/ceph/filesystems/` | CephFS filesystems |
| `/api/plugins/ceph/crush-rules/` | CRUSH rules |
| `/api/plugins/ceph/flags/` | Cluster-wide flags |
| `/api/plugins/ceph/health-checks/` | Health check records |
| `/api/plugins/ceph/rgw-realms/` | RGW realms |
| `/api/plugins/ceph/rgw-zone-groups/` | RGW zone groups |
| `/api/plugins/ceph/rgw-zones/` | RGW zones |
| `/api/plugins/ceph/rgw-placement-targets/` | RGW placement targets |
| `/api/plugins/ceph/rgw-users/` | Reflected RGW users |
| `/api/plugins/ceph/rgw-buckets/` | Reflected S3 buckets |
| `/api/plugins/ceph/rbd-images/` | RBD images |
| `/api/plugins/ceph/rbd-snapshots/` | RBD snapshots |
| `/api/plugins/ceph/rbd-clones/` | RBD clones |

## v2 — Control plane endpoints

Desired-state and operation-request endpoints are writable. Plans, validations,
approvals, runs, drift, and metric records are server-owned read-only audit or
observation surfaces.

The operation serializer requires `execution_node`. Plan, operation-approval,
and operation-run serializers expose `backend_endpoint_config_revision`,
`plugin_endpoint_id`, `provider_id_snapshot`, `provider_kind_snapshot`,
`execution_node`, and `local_config_digest`. These are non-secret evidence
values copied across the audit chain; consumers may correlate them but must not
interpret them as credentials or mutation authority. Approval issuance owner/
expiry fields are read-only crash-recovery metadata.

### Provider and operations

| Endpoint | Description |
|---|---|
| `/api/plugins/ceph/providers/` | `CephProvider` — external controller references |
| `/api/plugins/ceph/operations/` | `CephOperation` — requested actions |
| `/api/plugins/ceph/plans/` | `CephPlan` — provider-generated previews |
| `/api/plugins/ceph/operation-approvals/` | `CephOperationApproval` — token-free two-person approval/recovery audit |
| `/api/plugins/ceph/validation-results/` | `CephValidationResult` — plan findings |
| `/api/plugins/ceph/operation-runs/` | `CephOperationRun` — apply audit records |
| `/api/plugins/ceph/drift-records/` | `CephDriftRecord` — desired vs actual |
| `/api/plugins/ceph/metric-snapshots/` | `CephMetricSnapshot` — metric payloads |

### Desired-state

| Endpoint | Description |
|---|---|
| `/api/plugins/ceph/pool-desired-states/` | Pool desired state |
| `/api/plugins/ceph/filesystem-desired-states/` | CephFS desired state |
| `/api/plugins/ceph/rbd-image-desired-states/` | RBD image desired state |
| `/api/plugins/ceph/rbd-snapshot-desired-states/` | RBD snapshot desired state |
| `/api/plugins/ceph/rgw-realm-desired-states/` | RGW realm desired state |
| `/api/plugins/ceph/rgw-zone-desired-states/` | RGW zone desired state |
| `/api/plugins/ceph/rgw-user-desired-states/` | RGW user desired state |
| `/api/plugins/ceph/rgw-bucket-desired-states/` | S3 bucket desired state |

All eight desired-state resources support CRUD. Only pool and filesystem rows
can currently generate operations through the UI/service contract. RBD/RGW
intent does not imply provider write support. Pool/CephFS generation requires an
exact `execution_node` and rejects fields outside proxbox-api issue #258's typed
writer schema.

## Custom actions

| Endpoint | Method | Description |
|---|---|---|
| `/api/plugins/ceph/clusters/{id}/sync/` | POST | Enqueue a `CephSyncJob` for this cluster |
| `/api/plugins/ceph/providers/{id}/reconcile/` | POST | Trigger a provider-scoped v2 reconcile |
| `/api/plugins/ceph/operations/{id}/plan/` | POST | Run the plan step and store a `CephPlan` |
| `/api/plugins/ceph/operations/{id}/approve-and-apply/` | POST | A distinct approver obtains a one-time backend approval and immediately applies the immutable plan |
| `/api/plugins/ceph/operations/{id}/apply/` | POST | Compatibility alias for the same approve-and-apply flow; legacy `confirmed` input is ignored |

## Example

List all Ceph clusters:

```bash
curl -H "Authorization: Token $NETBOX_TOKEN" \
     https://netbox.example.com/api/plugins/ceph/clusters/?limit=10
```

Trigger a sync of pools and OSDs for cluster 1:

```bash
curl -s -X POST \
     -H "Authorization: Token $NETBOX_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"resources": ["pools", "osds"]}' \
     https://netbox.example.com/api/plugins/ceph/clusters/1/sync/
```
