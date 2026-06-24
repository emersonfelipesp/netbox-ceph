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

These endpoints are **writable** NetBox control-plane records.

### Provider and operations

| Endpoint | Description |
|---|---|
| `/api/plugins/ceph/providers/` | `CephProvider` — external controller references |
| `/api/plugins/ceph/operations/` | `CephOperation` — requested actions |
| `/api/plugins/ceph/plans/` | `CephPlan` — provider-generated previews |
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

## Custom actions

| Endpoint | Method | Description |
|---|---|---|
| `/api/plugins/ceph/clusters/{id}/sync/` | POST | Enqueue a `CephSyncJob` for this cluster |
| `/api/plugins/ceph/providers/{id}/reconcile/` | POST | Trigger a provider-scoped v2 reconcile |
| `/api/plugins/ceph/operations/{id}/plan/` | POST | Run the plan step and store a `CephPlan` |
| `/api/plugins/ceph/operations/{id}/apply/` | POST | Apply a planned operation (requires `confirmed=true` for destructive operations) |

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
