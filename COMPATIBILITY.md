# Compatibility Matrix

> `netbox-ceph` extends `netbox-proxbox`. The NetBox version range is inherited
> from the `netbox-proxbox` floor declared below.

## NetBox support tiers

`netbox-ceph` declares two NetBox support tiers, defined once in
[`netbox_ceph/compat.py`](netbox_ceph/compat.py) and vendored byte-identically across the
whole Proxbox plugin stack (`netbox-proxbox`, `netbox-ceph`, `netbox-packer`,
`netbox-pbs`, `netbox-pdm`):

| Tier | NetBox range | Constant | Behaviour |
|---|---|---|---|
| **Stable** | `4.5.8` – `4.6.99` | `STABLE_MIN_NETBOX_VERSION` / `STABLE_MAX_NETBOX_VERSION` | Certified and CI-gated. Silent. |
| **Experimental** | `4.7.0` – `4.7.99` | `EXPERIMENTAL_MIN_NETBOX_VERSION` / `EXPERIMENTAL_MAX_NETBOX_VERSION` | Loads and runs normally; warns once via system check `netbox_ceph.W001`. |

`PluginConfig.min_version` is the stable floor; `PluginConfig.max_version` is the
**experimental** ceiling (`4.7.99`). Admitting 4.7 without an opt-in is
deliberate — an operator upgrading NetBox never has to touch plugin
configuration. Experimental support needs no setting, no flag, and no extra
install step.

On a 4.7 install you will see one warning per plugin, from `manage.py check` and
in the startup log:

```
WARNINGS:
?: (netbox_ceph.W001) NetBox Ceph is running on NetBox 4.7.0-beta1, which is
   supported on an experimental basis only. Certified support covers NetBox
   4.5.8 through 4.6.99.
```

It is a warning, never an error, so it cannot block NetBox from starting. Silence
it with Django's stock mechanism in `configuration.py` once the risk is accepted:

```python
SILENCED_SYSTEM_CHECKS = ["netbox_ceph.W001"]
```

NetBox below `4.5.8` and from `4.8` onward is still refused outright by NetBox's
own plugin version gate.

### Upgrading to NetBox 4.7 upgrades the whole plugin stack at once

`PluginConfig.validate()` raises `IncompatiblePluginError` **while
`netbox/settings.py` is still executing**, so a single installed Proxbox-family
plugin whose `max_version` still reads `4.6.99` prevents NetBox from starting at
all — a failed boot, not a disabled plugin.

That makes the Proxbox-family plugins an all-or-nothing set on 4.7. Before moving
a NetBox instance to 4.7, upgrade **every** installed Proxbox-family plugin to a
release carrying the `4.7.99` ceiling. On 4.5.8–4.6.x, mixed versions remain fine
as before.

**Beta version strings.** NetBox's `release.yaml` at tag `v4.7.0-beta1` reads
`version: "4.7.0"` with `designation: "beta1"`, and `netbox/settings.py` passes
`RELEASE.version` — the bare `"4.7.0"` — to `PluginConfig.validate()`. The
`4.7.99` ceiling is sized for that comparison string; `RELEASE.full_version`
(`"4.7.0-beta1"`) is used only for display.

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
