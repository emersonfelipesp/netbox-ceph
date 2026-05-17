# netbox-ceph

`netbox-ceph` is a sibling NetBox plugin for
[`netbox-proxbox`](https://github.com/emersonfelipesp/netbox-proxbox).

Version 0.0.1 is intentionally read-only. It mirrors Proxmox-managed Ceph
inventory through [`proxbox-api`](https://github.com/emersonfelipesp/proxbox-api)
and reuses `netbox-proxbox` backend context, branch lifecycle, endpoint
relationships, and job conventions.

## Out of scope for v0.0.1

- Direct Ceph Dashboard API integration
- Prometheus metric ingestion
- RGW / S3 bucket inventory
- RBD image inventory
- External non-Proxmox Ceph clusters
- All NetBox-to-Ceph write operations
