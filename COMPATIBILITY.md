# Compatibility Matrix

> `proxbox-api` is a separately deployed backend service. `netbox-ceph`
> communicates with it over HTTP.

## Supported NetBox releases

`netbox-ceph` is an Emerson-owned plugin. Its compatibility contract preserves
the historical NetBox `4.5.8` floor and adds official NetBox `4.7.0` GA.
The declared plugin bounds are `4.5.8` through `4.7.0`.

NetBox 4.7 prereleases remain experimental and are not production support.
NetBox 4.7.1 and later are outside this release's tested contract.

The shared compatibility module is vendored byte-identically across
`netbox-proxbox`, `netbox-ceph`, `netbox-pbs`, and `netbox-pdm`.

## Verification matrix

| Plugin release | NetBox releases | Python | netbox-proxbox | proxbox-api |
|---|---|---|---|---|
| v0.0.1.post1 package | v4.5.8–v4.6.6 and official v4.7.0 GA | ≥3.12 | >=0.0.25.post2,<0.1.0 | v1 reflection routes; the packaged release is read-only |
| current v2 source | v4.5.8–v4.6.6 and official v4.7.0 GA | ≥3.12 | >=0.0.25.post2,<0.1.0 | >=0.0.23 for canonical plan, approval, apply, and recovery routes |

Fail-closed branch isolation is guaranteed on every supported `netbox-proxbox`
version. The typed branching decision contract is consumed automatically from
`netbox-proxbox` 0.0.27 onward; on published earlier releases the wrapper falls
back to `is_branching_available()` and preserves the same fail-closed behavior.
The dependency floor therefore remains on the published `0.0.25.post2` release
and does not require 0.0.27.

The legacy 4.5/4.6 cells remain in CI for backward compatibility. The GA cell
uses the exact NetBox source revision
`5f06007e4c9bacc93ce17c1e645fc1143d60df3d`, and the Docker smoke matrix uses
the pinned official image
`netboxcommunity/netbox:v4.7.0-5.1.0@sha256:73a54ff279461170032b59a57a1930929965e3ba15c195af59f4b5f6d39a84a9`.

## proxbox-api v2 contract

The v1 reflection sync (`/ceph/sync/*`) works against every published
proxbox-api release that serves those routes. The v2 plan → approve → apply flow
additionally needs `POST /ceph/v2/plans/{id}/approvals` and
`GET /ceph/v2/approvals/{id}`, plus an apply route that accepts
`approval_token`. Those routes are pinned from backend commit `4510af90` and
ship in `proxbox-api` 0.0.23. No published release up to and including 0.0.22
serves them. Against an older backend the plugin fails closed at
approval: the orchestrator translates the 404 into
`CephOrchestratorUnsupported` and the operation is left unapproved with a
named backend reason instead of a generic transport error.

The pinned wire contract lives in
`tests/fixtures/proxbox_api_ceph_v2_contract.v1.json` (a reviewed snapshot of
the backend request and response key sets at the recorded commit, digest-pinned
in `netbox_ceph.services.orchestrator.PROXBOX_API_V2_CONTRACT_SHA256`). The
plugin tests prove the client and the snapshot agree; re-deriving the snapshot
from `proxbox_api/ceph/v2_schemas.py` is the review step whenever the backend
commit is bumped. Bump the fixture, the digest, and this section together.

## Upgrade procedure

Install the GA-capable Ceph wheel before upgrading a production NetBox instance.
Run the normal NetBox migration and verify that `netbox_ceph` is registered.
Existing 4.5.8–4.6.x installations retain their supported floor and do not
require a database reset or configuration rewrite.
