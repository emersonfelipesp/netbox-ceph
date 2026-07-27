# netbox-ceph

`netbox-ceph` is a sibling NetBox plugin for
[`netbox-proxbox`](https://github.com/emersonfelipesp/netbox-proxbox).

The reflected v1 inventory is intentionally read-only. It mirrors
Proxmox-managed Ceph inventory through
[`proxbox-api`](https://github.com/emersonfelipesp/proxbox-api) and reuses
`netbox-proxbox` backend context, branch lifecycle, endpoint relationships,
and job conventions. The earlier `0.0.1.post1` release normalized certification
evidence, packaging metadata, and compatibility documentation; the unreleased
plan-bound approval work described below deliberately changes the v2 runtime
authority model.

Ceph v2 adds a separately gated desired-state control plane: immutable
endpoint-and-configuration-revision-bound plans, validation findings,
two-person approval audit records, apply/recovery runs, drift records, metric
snapshots, and a typed proxbox-api client. A raw approval token exists only
between the approval response and the
immediately following apply request; it is never stored, logged, serialized, or
rendered by NetBox.

v1 reflection syncs are dispatched with `POST
/api/plugins/ceph/clusters/{id}/sync/`, which enqueues `CephSyncJob` with a
7200-second timeout. Pass `resources` as a list or comma-separated string such
as `["pools", "osds"]`; omit it to run the default `full` sync. Queued runs are
visible in NetBox's core Jobs UI.

Desired-state configuration objects (`CephPoolDesiredState`,
`CephFilesystemDesiredState`, `CephRBDImageDesiredState`,
`CephRBDSnapshotDesiredState`, `CephRGWRealmDesiredState`,
`CephRGWZoneDesiredState`, `CephRGWUserDesiredState`, and
`CephRGWBucketDesiredState`) let operators declare NetBox-first pool, CephFS,
RBD, and RGW/S3 intent — size, autoscale, CRUSH rule, application, quotas,
compression, CephFS metadata/data pools, MDS placement, RBD image
layout/features, RBD snapshot protection, RGW topology, S3 users, and buckets —
which remain useful as NetBox-owned intent records. The strict
`proxbox-ceph-v2-2026-07` writer currently lets only pool and CephFS rows
generate mutations. Each supported row requires an exact `execution_node`;
pool payloads are limited to the fields accepted by proxbox-api issue #258 and
CephFS creation is limited to `pg_num` and `add_storage`. RBD and RGW/S3 intent
is browsable but deliberately has no **Generate operation** action until its
writer support exists. The requester must have the custom request and apply
permissions. A different actor with the approve permission then performs one
**Approve & apply** action through the orchestrator.

## Included Models

`netbox-ceph` ships v1 reflected inventory (clusters, daemons, OSDs, pools,
filesystems, CRUSH rules, flags, health checks, plugin settings, and
read-only RGW/S3 and RBD reflected inventory), plus v2 desired-state and
control-plane models (providers, operations, plans, token-free approvals,
validation results, operation runs, drift records, metric snapshots). See
[`docs/models.md`](https://emersonfelipesp.github.io/netbox-ceph/models/) for
the full, authoritative model list and field reference.

## Compatibility

See [COMPATIBILITY.md](COMPATIBILITY.md) for the full version compatibility table.

## Installation

```bash
pip install netbox-ceph
```

Then add to `configuration.py`:

```python
PLUGINS = [
    "netbox_proxbox",
    "netbox_ceph",
]
```

Run NetBox migrations as usual:

```bash
python manage.py migrate
```

Out of scope for v1: direct Ceph Dashboard API integration, Prometheus metric
ingestion, external non-Proxmox Ceph clusters, and NetBox-to-Ceph write
operations for reflected inventory (RGW/S3 and RBD objects are read-only
reflected inventory in v1; see [`docs/models.md`](https://emersonfelipesp.github.io/netbox-ceph/models/)).

The v2 write path requires the matching canonical-plan/approval contract from
proxbox-api issue #258. Migration `0007_ceph_plan_bound_approvals` retires
legacy authority, adds endpoint/provider/node/configuration snapshots, creates
expiring approval-issuance leases, and enforces one local run per approval.
Deploy the backend contract first, back up NetBox, migrate, grant the request/
apply/approve permissions deliberately, populate exact execution nodes on
legacy supported intent, and validate the full flow in staging.
Keep all Proxmox endpoint `allow_writes` flags disabled until those gates and
the authenticated actor-header gateway control have completed. No shell or
direct Proxmox API fallback exists.

## Documentation

Full documentation is published at
<https://emersonfelipesp.github.io/netbox-ceph/>.

## Support

Use GitHub Issues for bugs and feature requests:
<https://github.com/emersonfelipesp/netbox-ceph/issues>.

## Certification Status

Certification evidence is tracked in [CERTIFICATION.md](./CERTIFICATION.md).
The repository includes Apache-2.0 licensing, PyPI metadata, compatibility
metadata, GitHub Actions CI, release validation, docs publishing, screenshot
capture, page-coverage workflows for NetBox v4.6.4, and Docker install smoke
coverage for NetBox v4.5.8, v4.5.9, v4.6.0, v4.6.1, v4.6.2, v4.6.3, and v4.6.4.

## License

Apache-2.0
