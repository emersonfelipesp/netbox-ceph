# netbox-ceph

`netbox-ceph` is a sibling NetBox plugin for
[`netbox-proxbox`](https://github.com/emersonfelipesp/netbox-proxbox).

The v1 surface mirrors Proxmox-managed Ceph inventory read-only through
[`proxbox-api`](https://github.com/emersonfelipesp/proxbox-api) and reuses
`netbox-proxbox` backend context, branch lifecycle, endpoint relationships, and
job conventions. The current v2 surface separately supports controlled
desired-state operations.

V2 mutations require distinct object-scoped requester and approver permissions,
a valid canonical plan, unchanged endpoint/provider/node/configuration
snapshots, a supported backend writer contract, and enabled endpoint write
authority. Installation and migrations never enable writes.

## Compatibility

| NetBox | netbox-ceph | netbox-proxbox | Python |
| --- | --- | --- | --- |
| v4.5.8–v4.6.6 | v0.0.1.post1 | >=0.0.25.post2,<0.1.0 | 3.12+ |
| v4.7.0 GA | v0.0.1.post1 | >=0.0.25.post2,<0.1.0 | 3.12+ |

## Historical v0.0.1.post1 scope

- Direct Ceph Dashboard API integration
- Prometheus metric ingestion
- External non-Proxmox Ceph clusters
- NetBox-to-Ceph write operations for reflected inventory (RGW/S3 and RBD
  objects are read-only reflected inventory in v1 — see [Models](models.md)
  for the full `CephRGW*`/`CephRBD*` model list)

This historical list describes the packaged v0.0.1.post1 v1 surface, not the
later [Ceph v2 control plane](v2/overview.md).
