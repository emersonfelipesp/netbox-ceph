# Plan, Independent Approval, Apply, And Recovery

Ceph v2 uses one fail-closed authority chain. A local boolean, a destructive
confirmation modal, a plugin primary key, or a caller-provided inline plan can
never authorize a Proxmox mutation.

## Required flow

1. Create a `CephOperation` directly or from a supported desired-state row. The
   server records the authenticated requester and requires an exact Proxmox
   `execution_node`; callers cannot set status, requester, or legacy
   confirmation fields. Desired-state generation currently supports only pool
   and filesystem because proxbox-api #258 has no RBD/RGW writer.
2. The requester needs both `netbox_ceph.request_cephoperation` and
   `netbox_ceph.apply_cephoperation`, then invokes **Plan**. NetBox requires
   exactly one enabled `FastAPIEndpoint`, translates the operation's
   `ProxmoxEndpoint` through the canonical `netbox-proxbox` resolver, and sends
   that backend database ID to `POST /ceph/v2/plans`.
3. NetBox accepts exactly one supported provider operation whose provider,
   target, action, explicit node, blockers, and typed payload match issue #258.
   It appends the returned backend plan ID, digest, endpoint ID, opaque
   server-keyed endpoint-configuration revision, requester, expiry, local
   request digest, plugin endpoint ID, provider ID/kind, exact node, local
   configuration digest, redacted response, and validation rows. It
   marks an older unapplied plan stale but never overwrites or deletes its
   evidence. Planning uses a ten-minute nonce lease: a crashed reservation may
   be replaced after expiry, while its late response is rejected by the final
   compare-and-swap check.
4. A different authenticated actor with
   `netbox_ceph.approve_cephoperation` invokes **Approve & apply**. NetBox
   re-resolves the backend endpoint, recomputes the local request digest, checks
   requester permissions, valid/unblocked plan state, and plan expiry. It commits
   a token-free `issuing` reservation with a unique owner UUID and ten-minute
   expiry under database row locks before requesting one backend approval. A
   contender cannot share that owner; expired takeover rotates the UUID and
   makes every late response from the former owner non-authoritative.
5. The raw approval token is held only in the current Python call. NetBox
   re-locks and revalidates the endpoint/provider/node/configuration snapshots,
   finalizes the token-free approval, creates its unique one-to-one run, then
   immediately sends the original requester identity, canonical plan ID, exact
   endpoint ID, endpoint revision, and token to
   `POST /ceph/v2/plans/{id}/apply`.

All multi-row status transitions use one atomic operation/plan/approval/run lock
order. Routing rows remain locked across the irreversible approval and apply
POSTs, and the snapshots are checked again after reservations. A changed local
binding therefore rejects the attempt rather than dispatching with a freshly
resolved target. Named fault-injection tests verify that an exception between
row updates rolls the complete transition back.

The REST endpoint is `POST
/api/plugins/ceph/operations/{id}/approve-and-apply/`. The older `apply` action
is a compatibility alias with the same two-person semantics; `confirmed=true`
is ignored and has no authority.

## Timeout and crash recovery

An apply timeout, connection loss, HTTP 408/5xx response, or malformed success
response is ambiguous, not a known failure. NetBox retries the exact same
plan/token at most once. Because proxbox-api atomically consumes the token, the
retry either performs the first dispatch or returns `approval_replayed` with
the original operation run ID; it cannot authorize a second mutation.

NetBox then reads `GET /ceph/v2/operations/{run_id}`. After two transport
failures it records `outcome_unknown`, queries the safe
`GET /ceph/v2/approvals/{approval_id}` recovery surface, and performs no third
dispatch. If no linked run can be recovered, an operator must inspect/reconcile
state and create a fresh plan. A consumed, expired, lost, or already-issued
approval is never replaced on the same plan.

Approval tokens and hashes do not appear in models, serializers, forms, tables,
logs, exception messages, or recovery responses. Backend errors are reduced to
stable reason codes and a small allowlist of recovery identifiers.

The endpoint-configuration revision returned by proxbox-api is not a secret. It
is an opaque HMAC evidence value and is copied across the local plan, approval,
and run records. Every approval-status and run-recovery response must return the
same canonical 64-hex revision; missing, malformed, changed, or legacy blank
revisions fail closed and require a fresh plan.

The local configuration digest is also non-secret evidence, not authority. It
fingerprints the selected plugin endpoint and provider configuration (including
opaque credential-reference changes) without persisting credentials. The plan,
approval, and run copy the plugin endpoint ID, provider ID/kind, exact node, and
digest so a post-plan routing change cannot be hidden by re-resolution.

`X-Proxbox-Actor` is a delegated identity assertion, not authentication by
itself. Production write enablement remains blocked until the authenticated
gateway strips any caller-supplied value and injects the NetBox-authenticated
actor. Neither this plugin nor proxbox-api enables endpoint writes during
installation or migration.

## Permissions and audit surfaces

| Role | Required permission | Authority |
|---|---|---|
| Requester | `request_cephoperation` and `apply_cephoperation` | Create/refresh the canonical plan and remain the backend apply actor |
| Approver | `approve_cephoperation` | Issue the independent approval and trigger same-request apply; must differ from requester |
| Auditor | model `view_*` permissions | Read plans, validations, approvals, and runs |

Plans, validation results, approval records, and operation runs accept only
GET/HEAD/OPTIONS through the plugin API and use read-only NetBox UI views.
Operation creation, including **Generate operation** from desired state, requires
both requester permissions and captures an immutable username snapshot. Once a
plan or other audit evidence exists, the operation request cannot be edited or
deleted through the API or UI; protected foreign keys preserve the evidence
chain at the database layer.

## UI actions

| Page | Button | Action |
|---|---|---|
| Operation detail | **Plan** | Resolve exact endpoint and append a backend-bound plan |
| Operation detail | **Approve & apply** | Different actor approves and applies while the token remains memory-only |
| Provider detail | **Reconcile** | Read provider state and record a provider-scoped run; no writer or approval is used |
| Pool/CephFS desired-state detail | **Generate operation** | Build a pending, node-bound `CephOperation` from supported declarative intent |

RBD and RGW/S3 desired-state rows remain CRUD/audit surfaces and expose no
generate action until a matching typed writer exists.

## Upgrade and rollback

Migration `0007_ceph_plan_bound_approvals` is additive. It preserves legacy
plans/runs, marks non-applied legacy plans stale, and resets legacy `planning`,
`planned`, `awaiting_confirmation`, and `applying` operations to `pending`.
Nonterminal run rows still block new authority. The migration clears only the
old confirmation boolean and preserves the historical confirming actor/time as
non-authoritative audit evidence. It
also snapshots requester/run usernames, adds endpoint/provider/node/local-config
audit fields and approval issuance leases, and converts the approval/run link to
a database-enforced one-to-one relation. Existing runs without approvals remain
valid historical rows.
Legacy blank revisions are non-authoritative and cannot be approved. The
migration does not enable a Proxmox endpoint or dispatch a provider call.

Roll out proxbox-api's canonical plan/approval contract before this consumer.
Back up the NetBox database, apply the migration, grant the three custom
permissions deliberately, and populate an exact `execution_node` on every
legacy operation or supported pool/CephFS desired-state row before planning it.
Keep `allow_writes=false`, and validate in an approved staging environment. The
actor-header gateway control is also a hard production prerequisite. Rollback
is application rollback plus the normal database restore procedure; do not
reverse-delete audit rows after writes.

## NASA NPR 7150.2D Chapter 4 evidence

This table is scoped to the plan-bound approval feature and does not assert
project-wide compliance.

| Phase / requirement | Status | Evidence | Remaining gap |
|---|---|---|---|
| Requirements — SWE-050, SWE-051, SWE-053, SWE-054, SWE-055, SWE-184 | Partial | tracked inconsistencies plus exact endpoint/revision, two-person, replay, token, and ambiguity requirements in this guide | stakeholder/consumer acceptance and release baseline pending |
| Architecture — SWE-057, SWE-143 | Partial | separate desired-state, canonical backend authority, node/config-bound token-free audit, expiring planning/issuance leases, and read-only recovery boundaries documented here | project classification, production architecture approval, and cross-repository release baseline pending |
| Design — SWE-058 | Partial | append-only plan creation, unique pre-POST approval owner, fixed row-lock order, one approval/one run constraint, protected evidence chain, custom permissions, stable error/recovery types, and fault-injected state-machine tests | independent adversarial review and approved baseline pending |
| Implementation — SWE-060, SWE-061, SWE-062, SWE-063, SWE-135, SWE-136, SWE-186 | Partial | issue worktree implementation, migration, Ruff/compile checks, agent docs | remote CI, review closure, and merged baseline pending |
| Testing — SWE-065, SWE-066, SWE-068, SWE-071, SWE-187, SWE-189, SWE-190, SWE-191, SWE-192, SWE-193, SWE-211 | Partial | dependency-isolated contract/state-machine tests; the local NetBox 4.5.8/PostgreSQL feature suites cover object permissions, exact-one concurrent issuance, expired takeover/late-owner rejection, pending-run blocking, nested-secret rejection, stale binding rejection, transactional fault rollback, and approval/run uniqueness; a provider-owned test imports proxbox-api #258's real `PlanRequest` and `_build_and_persist` route guard; a GitHub migration-capable supported-version job is defined | authoritative from-zero migration matrix, Gitea database-capable safe runner, staging, and green remote CI evidence pending |
| Model/simulation qualification — SWE-070 | N/A | no flight model or simulation is used | not applicable |
| Target validation — SWE-073 | Gap | no live NetBox/Proxmox mutation was authorized | approved staging validation remains required |
| Operations — SWE-075, SWE-077, SWE-194, SWE-195, SWE-196 | Partial | upgrade/rollback, permission, recovery, and compatibility guidance | release notes, package publication, deploy, monitoring, and post-release evidence pending |
