# Compatibility Matrix

> `netbox-ceph` extends `netbox-proxbox`. The NetBox version range is inherited
> from the `netbox-proxbox` floor declared below.

| netbox-ceph | netbox-proxbox | NetBox | Python | requests |
|---|---|---|---|---|
| plan-bound approval contract (unreleased) | >=0.0.23.post2,<0.1.0 plus proxbox-api #258 (`proxbox-ceph-v2-2026-07`) | v4.5.8–v4.6.4 (target; remote matrix pending) | ≥3.12 | ≥2.33.0 |
| v0.0.1.post1 | >=0.0.18,<0.1.0 | v4.5.8, v4.5.9, v4.6.0, v4.6.1, v4.6.2, v4.6.3, v4.6.4 | ≥3.12 | ≥2.33.0 |
| v0.0.1 | >=0.0.16.post5 | ≥4.5.8 | ≥3.12 | ≥2.33.0 |

The `0.0.23.post2` floor is reserved for fail-closed backend-key target
adoption in netbox-proxbox. This branch must not be released until that package
exists in the Gitea registry and a clean install at the declared minimum passes
the import and NetBox system-check gates.

The NetBox 4.5.8 matrix leg depends on the pre-existing migration chain using
NetBox 4.5-compatible core migration nodes. Migrations `0002` through `0007`
use the compatible `extras.0134_owner` ancestor; promotion remains blocked
until the full 4.5.8 migration graph is green.

The canonical proxbox-api Ceph write contract must return one 64-hex
`endpoint_config_revision` on Proxmox plans, approvals, approval status, and
runs. Netbox-ceph persists and compares that opaque revision across its local
audit chain; older blank-revision authority is deliberately rejected.

Issue #258 must also preserve exactly one typed `ProviderOperation`, including
its explicit top-level `node`, supported action, and strict `after_summary`.
The consumer fixture `tests/fixtures/ceph_v2_writer_contract.v1.json` pins
contract version `proxbox-ceph-v2-2026-07`. Generated desired-state writes are
limited to pool create/update/noop and filesystem create/noop. RBD/RGW and
filesystem update/delete remain unsupported and must be reported as such; they
must never be filtered, inferred, or silently treated as successful.
