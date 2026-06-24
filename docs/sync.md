# Sync Jobs

`netbox-ceph` synchronises Ceph state from Proxmox into NetBox through a
background RQ job. The job calls Ceph-aware endpoints on
[`proxbox-api`](https://github.com/emersonfelipesp/proxbox-api) and is
intentionally **read-only** — no writes propagate from NetBox back to Ceph.

## CephSyncJob

`netbox_ceph.jobs.CephSyncJob` is a `JobRunner` subclass dispatched to the RQ
`default` queue with a 7200-second timeout.

### Resources

The job accepts a `resources` parameter that controls which Ceph object classes
are synced. Valid values:

| Resource | Objects synced |
|---|---|
| `status` | Cluster health summary |
| `daemons` | MON, MGR, OSD, MDS, and RGW daemon state |
| `osds` | OSD map (capacity, device class, in/up flags) |
| `pools` | Pool configuration and usage |
| `filesystems` | CephFS filesystem and MDS metadata |
| `crush` | CRUSH rules |
| `flags` | Cluster-wide flags |
| `rgw` | Reflected RGW realms, zone groups, zones, placement targets, users, and buckets |
| `rbd` | Reflected RBD images, snapshots, and clones |
| `full` | All of the above (default) |

Pass a single resource name, a comma-separated list, or `full` to sync
everything. Omitting the parameter defaults to `full`.

### HTTP contract

The job resolves the proxbox-api base URL and authentication token via
`netbox_proxbox.services.backend_context.get_fastapi_request_context()` and
calls:

```
GET {proxbox-api}/ceph/sync/{resource}
```

with an optional `netbox_branch_schema_id` query parameter when branching is
enabled. The HTTP timeout is `(5.0, 300.0)` seconds (short connect, long read)
to accommodate fan-out queries on large or degraded clusters.

Errors from the backend surface as `CephBackendError` and are recorded in the
job log without aborting the whole run — a failure on one resource does not
prevent other resources from syncing.

### Branching (optional)

When `CephPluginSettings.branching_enabled` is `True`, each sync job:

1. Creates a fresh `netbox-branching` branch using the configured
   `branch_name_prefix` (default `ceph-sync`).
2. Runs the sync against that branch by passing `netbox_branch_schema_id` to
   proxbox-api.
3. Merges the branch back into `main` on success.
4. Applies the `branch_on_conflict` policy on merge failure:
   - `fail` — leaves the branch open for manual review.
   - `acknowledge` — merges unconditionally.

Branching requires the
[`netbox-branching`](https://github.com/netboxlabs/netbox-branching) plugin to
be installed. Without it, `branching_enabled` has no effect.

## Dispatching a sync

### From the NetBox UI

Navigate to **Plugins → Ceph → Settings** and click **Sync Now**, or open any
`CephCluster` detail page and click **Sync**.

### Via the REST API

```http
POST /api/plugins/ceph/clusters/{id}/sync/
Content-Type: application/json
Authorization: Token <token>

{"resources": ["pools", "osds"]}
```

Omit the `resources` key (or pass `["full"]`) to sync all resources.

## Settings reference

Plugin-wide sync settings live in the singleton `CephPluginSettings` model:

| Field | Default | Description |
|---|---|---|
| `branching_enabled` | `false` | Enable branch-per-sync isolation via `netbox-branching` |
| `branch_name_prefix` | `ceph-sync` | Prefix for auto-created branch names |
| `branch_on_conflict` | `fail` | What to do when a branch cannot be cleanly merged: `fail` or `acknowledge` |

Edit settings at **Plugins → Ceph → Settings → Edit**.
