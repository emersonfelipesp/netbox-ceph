# Certification

`netbox-ceph` is prepared for the NetBox Plugin Certification Program as a
read-only companion plugin for Proxmox-managed Ceph inventory.

| Requirement | Evidence |
| --- | --- |
| License | Apache-2.0 in the repository and package metadata |
| Package | Published as `netbox-ceph` on PyPI with source, docs, and issues URLs |
| Compatibility | Stable NetBox `4.5.8`–`4.6.99`, with the current matrix at v4.5.8 and v4.6.6; canonical `v4.7.0-beta2` metadata is held-beta only and tested at exact revision `aa1d49d0f5021a28e6efc2d0364b84c5bcec7137` |
| Tests | GitHub Actions run lint, compile, pytest, Docker install smoke, page coverage, and release validation |
| Docs | README plus MkDocs installation, models, sync, certification, and release-note pages |
| Screenshots | `docs-screenshots.yml` captures NetBox v4.6.4 UI screenshots on release tags or manual dispatch |
| Support | GitHub Issues in `emersonfelipesp/netbox-ceph` |

The application packet for the full plugin family is tracked from
`emersonfelipesp/netbox-proxbox#499`.
