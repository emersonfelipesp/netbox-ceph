# netbox-ceph

`netbox-ceph` is a sibling NetBox plugin for
[`netbox-proxbox`](https://github.com/emersonfelipesp/netbox-proxbox).

Version 0.0.1.post1 is intentionally read-only. It mirrors Proxmox-managed Ceph
inventory through [`proxbox-api`](https://github.com/emersonfelipesp/proxbox-api)
and reuses `netbox-proxbox` backend context, branch lifecycle, endpoint
relationships, and job conventions.

## Compatibility

| NetBox | netbox-ceph | netbox-proxbox | Python |
| --- | --- | --- | --- |
| v4.5.8 | v0.0.1.post1 | >=0.0.18,<0.1.0 | 3.12+ |
| v4.5.9 | v0.0.1.post1 | >=0.0.18,<0.1.0 | 3.12+ |
| v4.6.0 | v0.0.1.post1 | >=0.0.18,<0.1.0 | 3.12+ |
| v4.6.1 | v0.0.1.post1 | >=0.0.18,<0.1.0 | 3.12+ |
| v4.6.2 | v0.0.1.post1 | >=0.0.18,<0.1.0 | 3.12+ |
| v4.6.3 | v0.0.1.post1 | >=0.0.18,<0.1.0 | 3.12+ |

## Out of scope for v0.0.1.post1

- Direct Ceph Dashboard API integration
- Prometheus metric ingestion
- RGW / S3 bucket inventory
- RBD image inventory
- External non-Proxmox Ceph clusters
- All NetBox-to-Ceph write operations
