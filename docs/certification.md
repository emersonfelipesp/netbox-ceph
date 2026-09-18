# Certification

The published `netbox-ceph 0.0.1.post1` certification target provides read-only
Proxmox Ceph inventory. Current source adds a separately gated v2 desired-state
control plane; that current-source evidence is recorded below but is not
attributed to the historical packaged artifact.

| Requirement | Evidence |
| --- | --- |
| License | Apache-2.0 in the repository and package metadata |
| Package | Published as `netbox-ceph` on PyPI with source, docs, and issues URLs |
| Compatibility | Backward-compatible NetBox `4.5.8`–`4.6.x` plus official `v4.7.0` GA, with the current matrix at v4.5.8, v4.6.6, and exact source revision `5f06007e4c9bacc93ce17c1e645fc1143d60df3d` |
| Tests | GitHub Actions run lint, compile, pytest, Docker install smoke, page coverage, and release validation |
| Docs | README plus MkDocs installation, models, sync, v2 safety/approval, certification, and release-note pages |
| Current-source write safety | Separate request/apply and independent approval permissions, canonical expiring plans, immutable execution snapshots, one-run reservation, memory-only approval tokens, and fail-closed ambiguity recovery |
| Screenshots | `docs-screenshots.yml` captures NetBox v4.6.4 UI screenshots on release tags or manual dispatch |
| Support | GitHub Issues in `emersonfelipesp/netbox-ceph` |

The application packet for the full plugin family is tracked from
`emersonfelipesp/netbox-proxbox#499`.
