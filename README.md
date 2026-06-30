# netbox-ceph

`netbox-ceph` is a sibling NetBox plugin for
[`netbox-proxbox`](https://github.com/emersonfelipesp/netbox-proxbox).

Version 0.0.1.post1 is intentionally read-only. It mirrors Proxmox-managed
Ceph inventory through
[`proxbox-api`](https://github.com/emersonfelipesp/proxbox-api) and reuses
`netbox-proxbox` backend context, branch lifecycle, endpoint relationships,
and job conventions. This post release normalizes certification evidence,
packaging metadata, and compatibility documentation without changing runtime
behavior.

Ceph v2 adds the NetBox desired-state and operations foundation alongside the
read-only v1 inventory: provider references, operation requests, generated
plans, validation findings, apply-run audit records, drift records, metric
snapshots, and a feature-detecting proxbox-api orchestrator client.

Desired-state configuration objects (`CephPoolDesiredState`,
`CephFilesystemDesiredState`, `CephRBDImageDesiredState`,
`CephRBDSnapshotDesiredState`, `CephRGWRealmDesiredState`,
`CephRGWZoneDesiredState`, `CephRGWUserDesiredState`, and
`CephRGWBucketDesiredState`) let operators declare NetBox-first pool, CephFS,
RBD, and RGW/S3 intent — size, autoscale, CRUSH rule, application, quotas,
compression, CephFS metadata/data pools, MDS placement, RBD image
layout/features, RBD snapshot protection, RGW topology, S3 users, and buckets —
which a `CephOperation` references to produce a plan and, after validation, an
apply run through the orchestrator.

## Included Models

- Ceph clusters
- Ceph daemons
- Ceph OSDs
- Ceph pools
- Ceph filesystems
- Ceph CRUSH rules
- Ceph flags
- Ceph health checks
- Ceph plugin settings
- Ceph pool desired state (v2)
- Ceph filesystem desired state (v2)
- Ceph RBD image desired state (v2)
- Ceph RBD snapshot desired state (v2)
- Ceph RGW realm desired state (v2)
- Ceph RGW zone desired state (v2)
- Ceph RGW user desired state (v2)
- Ceph RGW bucket desired state (v2)

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
ingestion, RGW/S3 bucket inventory, RBD image inventory, external non-Proxmox
Ceph clusters, and all NetBox-to-Ceph write operations.

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
