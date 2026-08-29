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
| **Stable** | `4.5.8` – `4.6.99` | `STABLE_MIN_NETBOX_VERSION` / `STABLE_MAX_NETBOX_VERSION` | Admitted silently. Directly exercised in CI at v4.5.8 and v4.6.6; the rest of the band is admitted on the strength of those. |
| **Held beta** | canonical `4.7.0-beta2` metadata only | `EXPERIMENTAL_MIN_NETBOX_VERSION` / `EXPERIMENTAL_MAX_NETBOX_VERSION` plus the release-identity guard | Loads and runs normally; warns once via system check `netbox_ceph.W001`. Final 4.7.0 and every other 4.7 identity are rejected. |

`PluginConfig.min_version` is the stable floor; `PluginConfig.max_version` is
the held numeric ceiling (`4.7.0`). Because NetBox passes the bare numeric value
to plugin validation, the shared v3 compatibility contract also reads canonical
release metadata and admits only designation `beta2`. Local release metadata
may add a build label but cannot replace version or designation.

On a 4.7 install you will see one warning per plugin, from `manage.py check` and
in the startup log:

```
WARNINGS:
?: (netbox_ceph.W001) NetBox Ceph is running on NetBox 4.7.0-beta2, which is
   supported on an experimental basis only. Certified support covers NetBox
   4.5.8 through 4.6.99.
```

It is a warning, never an error — it cannot block NetBox from starting.

**To silence it**, set the key in this plugin's `PLUGINS_CONFIG` entry:

```python
PLUGINS_CONFIG = {
    "netbox_ceph": {"silence_netbox_compatibility_warning": True},
}
```

That silences both the system check and the startup log line.

> Django's own `SILENCED_SYSTEM_CHECKS` is honoured too, but **not from
> `configuration.py`** — NetBox's `settings.py` imports an explicit list of
> named settings and that one is not on it, so setting it there has no effect.
> It only applies through NetBox's `local_settings.py` hatch, which upstream
> labels unsupported. Use the `PLUGINS_CONFIG` key above.

NetBox below `4.5.8`, final 4.7.0, unreviewed 4.7 prereleases/minors, and 4.8+
are refused. NetBox's stock numeric gate enforces the outer range; the held-line
identity guard narrows numeric 4.7.0 to canonical beta2 metadata.

> **These tiers describe the *next* release, not the currently published
> package.** Every artifact published before this change declares
> `max_version = "4.6.99"` and will refuse NetBox 4.7 regardless of what this
> table says. `pip install` of an older version therefore still caps at 4.6.99.

### Upgrading to NetBox 4.7 means upgrading the whole plugin stack

A Proxbox-family plugin left at the old `4.6.99` ceiling does **not** stop
NetBox from starting. `netbox/settings.py` catches `IncompatiblePluginError`,
emits a Python `warnings.warn`, and **skips that plugin** — NetBox comes up
without it.

That is easy to miss and worth stating plainly, because the quiet failure is
the dangerous one. `warnings.warn` does not reach the application log in a
normal production deployment, so the visible symptom is not an error but an
*absence*: the plugin's navigation entries, views, REST API routes, and
background jobs are simply gone, and anything that depended on them fails later
and further away. A health probe against NetBox itself still returns 200.

So before moving an instance to beta2, upgrade **every** installed
Proxbox-family plugin to a release carrying compatibility contract v3, and
afterwards verify each one is actually registered rather than trusting that
NetBox started:

```bash
python manage.py shell -c "from django.apps import apps; print([p for p in ('netbox_proxbox','netbox_pbs','netbox_pdm','netbox_ceph','netbox_packer') if apps.is_installed(p)])"
```

On 4.5.8–4.6.x, mixed versions remain fine as before.

### netbox-branching does not support NetBox 4.7 yet

`netboxlabs-netbox-branching` declares `max_version = "4.6.99"` (checked
through 1.0.3), so on NetBox 4.7 **NetBox skips it** — the package stays
importable, but its Django app is absent from `INSTALLED_APPS` and its models
and schemas do not exist.

If you use branch-isolated sync (`branching_enabled = True`), **do not move to
NetBox 4.7 until a 4.7-capable netbox-branching release exists.** The
availability detector here now requires the loaded app rather than an
importable package, so a skipped branching app is correctly reported as
unavailable. A sync configured for branch isolation now fails closed in that
state rather than silently writing against `main`.

Installations that do not use branching are unaffected.

**Beta version strings.** NetBox's `release.yaml` at tag `v4.7.0-beta2` reads
`version: "4.7.0"` with `designation: "beta2"`, and `netbox/settings.py` passes
`RELEASE.version` — the bare `"4.7.0"` — to `PluginConfig.validate()`. The
numeric ceiling therefore remains `4.7.0`; the separate canonical-metadata
guard distinguishes beta2 from GA or another prerelease.

**Current pre-release evidence.** The required real-NetBox/PostgreSQL matrix
runs against exact NetBox `v4.7.0-beta2` commit
`aa1d49d0f5021a28e6efc2d0364b84c5bcec7137`; the 4.5.8 and 4.6.6 cells remain
alongside it as backward-compatibility evidence.

| netbox-ceph | netbox-proxbox | NetBox | Python | requests |
|---|---|---|---|---|
| plan-bound approval contract (unreleased) | >=0.0.23.post2,<0.1.0 plus proxbox-api #258 (`proxbox-ceph-v2-2026-07`) | v4.5.8, v4.6.6, exact v4.7.0-beta2 SHA (matrix) | ≥3.12 | ≥2.33.0 |
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
