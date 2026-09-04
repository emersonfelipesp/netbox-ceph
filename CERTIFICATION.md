# NetBox Plugin Certification Evidence

This checklist tracks readiness for the NetBox Plugin Certification Program.

| Requirement | Evidence |
| --- | --- |
| Open source license | Apache-2.0 in `LICENSE` and `pyproject.toml` |
| Package metadata | PyPI project `netbox-ceph`, project URLs, classifiers, Python `>=3.12` |
| NetBox compatibility | Plugin config admits backward-compatible `4.5.8`–`4.7.0`, including official `v4.7.0` GA |
| Dependency policy | Requires `netbox-proxbox>=0.0.25.post1,<0.1.0` and communicates with `proxbox-api` over HTTP |
| CI | GitHub Actions run lint, compile, pytest, docs, page coverage, screenshot capture, and release validation |
| Documentation | README, MkDocs site, installation, models, sync, release notes, and support links |
| Screenshots | `.github/workflows/docs-screenshots.yml` captures deterministic NetBox v4.6.4 UI screenshots into `docs/assets/screenshots` |
| Icon | NetBox menu uses Material Design Icons class `mdi mdi-database-clock` |
| Maintainer access | Repositories stay under `emersonfelipesp`; NetBox Labs staff can be invited as collaborators when requested |

## Application Summary

- Repository: <https://github.com/emersonfelipesp/netbox-ceph>
- Documentation: <https://emersonfelipesp.github.io/netbox-ceph/>
- PyPI: <https://pypi.org/project/netbox-ceph/>
- Support: <https://github.com/emersonfelipesp/netbox-ceph/issues>
- Certification target release: `0.0.1.post1`
- Verified targets: `v4.5.8`, `v4.5.9`, `v4.6.0`, `v4.6.1`, `v4.6.2`,
  `v4.6.3`, `v4.6.4`, `v4.6.6`, and exact `v4.7.0` source revision
  `5f06007e4c9bacc93ce17c1e645fc1143d60df3d`.
- Docker GA evidence uses `netboxcommunity/netbox:v4.7.0-5.1.0@sha256:73a54ff279461170032b59a57a1930929965e3ba15c195af59f4b5f6d39a84a9`.
