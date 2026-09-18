# NetBox Plugin Certification Evidence

This checklist separates the published `0.0.1.post1` certification target from
current-source evidence. The published artifact is read-only; the current
source adds a separately gated v2 desired-state control plane without changing
the historical package identity.

| Requirement | Evidence |
| --- | --- |
| Open source license | Apache-2.0 in `LICENSE` and `pyproject.toml` |
| Package metadata | PyPI project `netbox-ceph`, project URLs, classifiers, Python `>=3.12` |
| NetBox compatibility | Plugin config preserves the `4.5.8` backward-compatible floor and admits official `v4.7.0` GA; `v4.7.1+` remains outside the tested contract |
| Dependency policy | Requires `netbox-proxbox>=0.0.25.post2,<0.1.0` and communicates with `proxbox-api` over HTTP |
| CI | GitHub Actions run lint, compile, pytest, docs, page coverage, screenshot capture, and release validation |
| Documentation | README, MkDocs site, installation, models, sync, release notes, and support links |
| Current-source surface safety | V1 inventory is read-only; v2 writes require separate requester/approver permissions, canonical plans, immutable execution snapshots, and an explicitly enabled backend endpoint |
| Screenshots | `.github/workflows/docs-screenshots.yml` captures deterministic NetBox v4.6.4 UI screenshots into `docs/assets/screenshots` |
| Icon | NetBox menu uses Material Design Icons class `mdi mdi-database-clock` |
| Maintainer access | Repositories stay under `emersonfelipesp`; NetBox Labs staff can be invited as collaborators when requested |

## Application Summary

- Repository: <https://github.com/emersonfelipesp/netbox-ceph>
- Documentation: <https://emersonfelipesp.github.io/netbox-ceph/>
- PyPI: <https://pypi.org/project/netbox-ceph/>
- Support: <https://github.com/emersonfelipesp/netbox-ceph/issues>
- Certification target release: `0.0.1.post1`
- Verified historical targets: `v4.5.8`, `v4.5.9`, `v4.6.0`, `v4.6.1`,
  `v4.6.2`, `v4.6.3`, and `v4.6.4`. The current compatibility matrix adds
  `v4.6.6` and exact `v4.7.0 GA` source revision
  `5f06007e4c9bacc93ce17c1e645fc1143d60df3d`.

The certification target remains a historical packaged release. It does not
classify current source as globally read-only: v1 inventory remains read-only,
while v2 exposes controlled desired-state operations.
