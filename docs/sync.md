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

with the `proxmox_endpoint_ids` query parameter set to exactly one backend
Proxmox endpoint id, and an optional `netbox_branch_schema_id` query parameter
when branching is enabled. The HTTP timeout is `(5.0, 300.0)` seconds (short
connect, long read) to accommodate slow queries on large or degraded clusters.

### Endpoint scope

proxbox-api's `/ceph/sync/*` routes fan out across every configured Proxmox
session unless the request names an endpoint. The job therefore binds each run
to one backend endpoint before its first request:

1. Loads the `CephCluster` named by `cluster_pk` together with its linked
   `ProxmoxCluster` and that cluster's `ProxmoxEndpoint`. The Ceph cluster's own
   `endpoint` must be the same endpoint.
2. Resolves that `ProxmoxEndpoint` to its proxbox-api database id through
   netbox-proxbox's `resolve_backend_endpoint_id()` helper, using the same
   request context as the sync calls.
3. Sends `proxmox_endpoint_ids=<id>` on every `/ceph/sync/<resource>` request
   and records `proxmox_cluster_pk`, `proxmox_endpoint_pk`, and
   `backend_endpoint_id` in the job's `params`.

If the cluster does not exist, has no linked Proxmox cluster or endpoint, names
two different endpoints, or the endpoint is not uniquely registered in
proxbox-api, the job fails with `CephSyncScopeError` before any branch is
created or any request is sent, and stores
`response.reason = "unresolved_cluster_scope"` with the refusal message.

Each accepted response must contain exactly one summary whose `host` matches
the resolved endpoint's domain or IP address (compared case-insensitively,
ignoring a trailing dot); anything else — an aggregate for several endpoints,
a summary for a different endpoint, or an empty list — is rejected as
`malformed_summary` and the stage fails. The summary's `name` is not compared:
proxbox-api names a session after its domain, IP, cluster, or node, never after
the NetBox endpoint name, so the name is only quoted in the refusal message.

Errors from the backend surface as `CephBackendError` and are recorded in the
job log without aborting the whole run — a failure on one resource does not
prevent other resources from syncing. The stored job data records the HTTP
status and route, but never stores raw proxbox-api response bodies.

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
be installed and loaded. This setting establishes a fail-closed isolation
boundary. Before the first backend call or job-data write, the job reads
`CephPluginSettings` and confirms a working branching runtime. If the settings
row cannot be read or `netbox-proxbox` cannot confirm the runtime,
`BranchingUnavailableError` fails the job with an actionable message. The job
writes directly to the main schema only when `branching_enabled` is explicitly
`False`.

## Dispatching a sync

### From NetBox

Enqueue syncs through the cluster REST action below, then follow the queued job
from NetBox's core **Jobs** UI.

### Via the REST API

```http
POST /api/plugins/ceph/clusters/{id}/sync/
Content-Type: application/json
Authorization: Token <token>

{"resources": ["pools", "osds"]}
```

Omit the `resources` key (or pass `["full"]`) to sync all resources.

## Settings and configuration reference

Plugin-wide sync settings live in the singleton `CephPluginSettings` model:

| Field | Default | Description |
|---|---|---|
| `branching_enabled` | `false` | Require branch-per-sync isolation; the job refuses to run if the branching runtime is unavailable |
| `branch_name_prefix` | `ceph-sync` | Prefix for auto-created branch names |
| `branch_on_conflict` | `fail` | What to do when a branch cannot be cleanly merged: `fail` or `acknowledge` |

Edit settings at **Plugins → Ceph → Settings → Edit**.

The wrapper consumes the typed `resolve_branching_decision()` contract from
`netbox-proxbox` 0.0.27 onward. On every supported earlier version, it uses the
published `is_branching_available()` helper and enforces the same fail-closed
rule. This compatibility path does not permit a runtime failure to become an
unisolated sync.
