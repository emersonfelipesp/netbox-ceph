# CLAUDE.md — netbox-ceph

## Workspace Context

This file lives at `/root/personal-context/nmulticloud-context/netbox-ceph/CLAUDE.md` inside the `personal-context` workspace.
Workspace guidance: `/root/personal-context/CLAUDE.md`.
Per-repo deep-dive: `/root/personal-context/claude-reference/nmulticloud-context.md`.
Submodule layout and cross-repo links: `/root/personal-context/claude-reference/dependency-map.md`.

---

NetBox plugin for netbox-ceph integration with netbox.nmulti.cloud.

## Installation

```bash
pip install -e .
python manage.py migrate
python manage.py collectstatic
```

## Development

- Pre-commit: `python -m compileall . && ruff check . && pytest tests/`
- Type checking: `pyright .`
- Full test suite: `pytest tests/ -v`

## Architecture

See the plugin's code structure:
- `netbox_ceph/` — main plugin package
- `netbox_ceph/models/` — Django ORM models, split by layer: `ceph.py` (v1
  reflected inventory + `CephPluginSettings`), `desired_state.py` (v2 desired
  state), `providers.py`, `operations.py`, `metrics.py` (v2 control plane)
- `netbox_ceph/views.py` — Django views and viewsets (single file)
- `netbox_ceph/api/` — DRF serializers and API endpoints
- `netbox_ceph/templates/` — Django HTML templates
- `netbox_ceph/services/` — sync/orchestrator HTTP clients and response mapping
- `netbox_ceph/migrations/` — Django migrations
- `tests/` — unit and integration tests

## Automatic Staging/Production Deployment

The deploy workflow treats `develop` as staging and `main` as production.
Pushes to `develop` deploy `netbox-ceph` to
`https://staging.netbox.nmulti.cloud`; pushes to `main` deploy to
`https://netbox.nmulti.cloud`.

**Deploy job in `.gitea/workflows/deploy-production.yml`:**
- Triggers on `push: [develop, main]` and `workflow_dispatch` with optional `ref` and optional `environment`.
- Runs on the `prod-deploy` runner, which has access to the NetBox deploy host.
- For staging, runs `/opt/nmulticloud/deploy/bin/deploy-netbox-plugin-staging netbox-ceph "$REF"`.
- For production, runs `/opt/nmulticloud/deploy/bin/deploy-netbox-plugin ceph "$REF"` directly when local, or falls back to `ssh nmc-prod-207 -- deploy-plugin ceph "$REF"` when the script is absent.

**Security hardening:**
- REF is passed via an environment variable, not direct context interpolation.
- A bash `case` statement validates the ref format (version tags, `main`/`develop`,
  7+ char commit SHAs) before use.

**What the deploy helper does** (on the target host, as the runner):
1. Discovers the plugin's live editable source directory from the running
   interpreter (production loads plugins editable from the workspace checkout,
   not `/opt/netbox/netbox/<plugin>`).
2. Refuses to run if that checkout has uncommitted changes (never discards WIP).
3. `git fetch` + checkout the ref (keeping the checkout on its branch) and
   force-refreshes the editable install.
4. **Safety gate:** `manage.py check` — on failure it rolls the source back and
   aborts *without restarting*, so production keeps serving the previous code.
5. `manage.py migrate --no-input` + `collectstatic --no-input`.
6. `systemctl restart netbox.service`, then health-checks the WSGI backend at
   `http://127.0.0.1:8001/api/`; an unhealthy backend rolls back and restarts.

**Monitoring:**
- Watch the `deploy-production.yml` run in Gitea Actions (the `Deploy plugin` job).
- Verify staging: `curl -sS https://staging.netbox.nmulti.cloud/api/plugins/ceph/` → `403`
- Verify production: `curl -sS https://netbox.nmulti.cloud/api/plugins/ceph/` → `403`
  (auth-gated, plugin loaded).

**Manual deployment trigger:**
```bash
# Manual dispatch of the deploy workflow
nms git actions run netbox-ceph .gitea/workflows/deploy-production.yml -r main -f environment=production -f ref=v0.1.0

# Or directly on the production host
/opt/nmulticloud/deploy/bin/deploy-netbox-plugin ceph v0.1.0
```

For comprehensive deploy infrastructure documentation, see `/root/personal-context/nmulticloud-context/CLAUDE.md` section "Automatic Plugin Deployment to Production".

---

# netbox-ceph Architecture Notes

## Ceph v2 Desired-State And Operations Foundation

`netbox-ceph` keeps the v1 reflected inventory models intact and read-only.
`CephPluginSettings`, `CephCluster`, `CephDaemon`, `CephOSD`, `CephPool`,
`CephFilesystem`, `CephCrushRule`, `CephFlag`, `CephHealthCheck`, and the
RGW/RBD reflected models (`CephRGWRealm`, `CephRGWZoneGroup`, `CephRGWZone`,
`CephRGWPlacementTarget`, `CephRGWUserReflected`, `CephRGWBucketReflected`,
`CephRBDImage`, `CephRBDSnapshot`, `CephRBDClone`) continue to mirror
Proxmox-managed Ceph state. See `docs/models.md` for the authoritative,
field-level list.

Ceph v2 adds a separate NetBox control-plane foundation:

- `CephProvider` records backend/provider references and capability metadata.
- `CephOperation` records requested desired-state actions.
- `CephPlan` records provider-generated previews.
- `CephOperationApproval` records token-free independent approval authority.
- `CephValidationResult` records plan findings.
- `CephOperationRun` records apply attempts and backend task references.
- `CephDriftRecord` records desired-vs-actual comparison state.
- `CephMetricSnapshot` records latest metric payloads by scope.

Writable v2 objects are providers, operations, plans, validation results, and
operation runs. Drift records and metric snapshots are read-only API/UI surfaces.

## Ceph v2 Desired-State Configuration Objects

Ceph v2 separates **reflected** inventory (what Proxmox reports) from
**desired** configuration (what an operator wants NetBox to drive). The
reflected models (`CephPool`, `CephFilesystem`, …) stay read-only; the desired
models are the NetBox-first, operator-editable source of intent:

- `CephPoolDesiredState` — desired RADOS pool config: `size`, `min_size`,
  `pg_autoscale_mode`, `crush_rule_name`, `application`, `target_size_ratio`,
  quotas (`quota_max_bytes`, `quota_max_objects`), `compression_mode`,
  `erasure_code_profile`, exact `execution_node`, and a free-form `parameters`
  JSON map. Unique per
  (`cluster`, `name`) via `netbox_ceph_pool_desired_identity`.
- `CephFilesystemDesiredState` — desired CephFS config: `metadata_pool` (FK to a
  `CephPoolDesiredState`), `data_pools` (JSON list), `mds_placement`,
  `standby_count`, `max_mds`, `quota_max_bytes`, exact `execution_node`,
  `pg_num`, `add_storage`, and `parameters`. Unique per
  (`cluster`, `name`) via `netbox_ceph_filesystem_desired_identity`.
- `CephRBDImageDesiredState` — desired RBD image config: `pool_name`, `name`,
  `size_bytes`, `features`, layout (`object_size`, `stripe_unit`,
  `stripe_count`), optional EC `data_pool`, clone parent image/snapshot,
  `metadata`, and `parameters`. Unique per (`cluster`, `pool_name`, `name`) via
  `netbox_ceph_rbd_image_desired_identity`.
- `CephRBDSnapshotDesiredState` — desired RBD snapshot intent: parent `image`,
  `name`, `protected`, and `parameters`. Unique per (`image`, `name`) via
  `netbox_ceph_rbd_snapshot_desired_identity`.
- `CephRGWRealmDesiredState` — desired RGW realm config: `name`, `is_default`,
  and `parameters`. Unique per (`cluster`, `name`) via
  `netbox_ceph_rgw_realm_desired_identity`.
- `CephRGWZoneDesiredState` — desired RGW zone config: optional parent `realm`,
  `zonegroup_name`, `is_master`, `endpoints`, `placement_targets`, and
  `parameters`. Unique per (`cluster`, `name`) via
  `netbox_ceph_rgw_zone_desired_identity`.
- `CephRGWUserDesiredState` — desired RGW/S3 user config: `uid`,
  `display_name`, `email`, `tenant_name`, `suspended`, `max_buckets`,
  quota limits (`quota_max_size_bytes`, `quota_max_objects`),
  `credential_ref`, and `parameters`. Unique per (`cluster`, `uid`) via
  `netbox_ceph_rgw_user_desired_identity`.
- `CephRGWBucketDesiredState` — desired RGW/S3 bucket config: `name`, optional
  owner, `placement_target`, `versioning_enabled`, quota limits
  (`quota_max_size_bytes`, `quota_max_objects`), `lifecycle_policy`, and
  `parameters`. Unique per (`cluster`, `name`) via
  `netbox_ceph_rgw_bucket_desired_identity`.

These desired-state models are writable NetBox objects (full CRUD UI + REST),
but writable intent is not the same as provider capability. Contract
`proxbox-ceph-v2-2026-07` enables **Generate operation** only for pool and
filesystem rows. Pool creation/update accepts only issue #258's typed fields;
filesystem creation accepts only `pg_num` and `add_storage`. Quota,
compression, pool topology/MDS placement, RBD, and RGW/S3 mutations fail closed
until the Proxmox writer implements them. An operator edits supported desired
state, then a `CephOperation` produces an append-only `CephPlan` preview. A
distinct approver creates a token-free `CephOperationApproval` audit row and an
immediate `CephOperationRun` through the orchestrator. Desired-state objects
hold no secrets — provider credentials remain `credential_ref` pointers only.
RGW/S3 users may store only
the opaque `credential_ref`; do not add or expose access keys, secret keys,
passwords, or tokens in NetBox.

REST endpoints: `/api/plugins/ceph/pool-desired-states/` and
`/api/plugins/ceph/filesystem-desired-states/`,
`/api/plugins/ceph/rbd-image-desired-states/`, and
`/api/plugins/ceph/rbd-snapshot-desired-states/`,
`/api/plugins/ceph/rgw-realm-desired-states/`,
`/api/plugins/ceph/rgw-zone-desired-states/`,
`/api/plugins/ceph/rgw-user-desired-states/`, and
`/api/plugins/ceph/rgw-bucket-desired-states/`. UI lives under the
**Desired State** navigation group. See `docs/v2/desired-state.md` for the full
field reference and reconciliation flow.

## Secret-Ref Rule

NetBox must never store actual Ceph provider secrets. `credential_ref` is an
opaque pointer only. Passwords, tokens, access keys, secret keys, and other
credentials live in proxbox-api or its secret store. Payloads logged or stored
through the v2 orchestrator path must pass through `redact_secrets()`.

## Ceph v1 Reflection Sync Dispatch

`CephClusterViewSet.sync` exposes `POST
/api/plugins/ceph/clusters/{id}/sync/` and enqueues `CephSyncJob` with keyword
arguments only: `cluster_pk`, `resources`, `queue_name`, `name`, and `user`.
Do not pass ORM objects through `instance=`. `resources` may be omitted, a
single resource, a comma-separated string, or a list; the job normalizes,
deduplicates, and validates it before enqueueing. v1 HTTP errors store only the
status/path summary in job data, never raw proxbox-api response bodies.

## Orchestrator Feature Detection

`netbox_ceph.services.orchestrator.CephOrchestratorClient` calls proxbox-api
`/ceph/v2/*` routes only after proving exactly one enabled `FastAPIEndpoint`.
It translates the operation's plugin `ProxmoxEndpoint` to the backend database
ID through `netbox_proxbox.views.backend_sync.resolve_backend_endpoint_id`;
plugin PKs are never placed on the wire as backend IDs. Generic 404/501 routes
become `CephOrchestratorUnsupported`, timeouts remain distinct, and structured
backend errors retain only a stable reason plus allowlisted recovery IDs.

Successful bodies are returned intact to the service, while only redacted
copies enter logs. This is required because the approval token is returned once
and must survive long enough for the same-request apply. The service never
stores, serializes, renders, or logs the raw token or token hash.

Unsupported operations fail clearly. Do not add shell command fallbacks or local
Ceph CLI execution paths.

## Orchestrator Response Mapping

proxbox-api (#95, hardened by #258) returns `PlanResponse`/`OperationRun` with `operations`,
`blocked_actions`, `warnings`, `live_state_summary`, `provider_task_refs` (a
**list** of Proxmox UPIDs), and `status` in
`pending`/`running`/`dispatching`/`completed`/`failed`/`blocked`/`cancelled`/
`outcome_unknown`. These field names differ
from the NetBox `CephPlan`/`CephOperationRun` models, so
`netbox_ceph/services/ceph_v2_responses.py` (pure, Django-free, unit-tested in
`tests/test_v2_response_mapping.py`) translates them:

- `map_run_status()` — proxbox status → `CephOperationStatusChoices`
  (`completed`→`succeeded`, `running`/`dispatching`→`applying`,
  `blocked`→`failed`, …).
- `provider_task_ref()` — joins `provider_task_refs` (list) into the singular
  `CephOperationRun.provider_task_ref`, with back-compat for singular keys.
- `plan_fields_from_response()` — derives `intended_changes`/`expected_tasks`/
  `summary`/`is_destructive`/`blast_radius`/`provider_target` from `operations`/
  `blocked_actions`/`warnings`/`live_state_summary`, preferring explicit legacy
  fields when present.

`netbox_ceph/api/views.py` wraps these with the `ChoiceSet` validation. The
structurally complete but secret-redacted backend response is retained in
`CephPlan.raw` / `CephOperationRun.result`.
When proxbox-api response schemas change, update this mapper (and its tests), not
the view handlers.

The #258 write boundary is stricter than the general response mapper. Planning
must return exactly one supported `ProviderOperation` whose `provider`, `kind`,
`target_ref`, explicit top-level `node`, action, and `after_summary` match the
local operation and typed writer field set. Unknown keys, a missing or
different node, blockers, error validations, unsupported actions, or a changed
endpoint/provider/configuration snapshot reject the plan before approval.

## Declarative → Imperative: Operation Actions And The Desired-State Bridge

The declarative desired-state models and the imperative
`CephOperation` → `CephPlan` → `CephOperationRun` engine are wired together by two
service modules, both consumed by the REST API (`netbox_ceph/api/views.py`) and
the NetBox web action views (`netbox_ceph/views.py`) so REST and UI share one
implementation:

- `netbox_ceph/services/operation_actions.py` — owns exact endpoint resolution,
  append-only `plan_operation()`, token-transient
  `approve_and_apply_operation()`, ambiguity recovery, and read-only provider
  `reconcile_provider()`. Failures raise a typed `OperationActionError`
  (`kind` in `invalid`/`unsupported`/`unavailable`/`backend`); the API maps
  `kind` → HTTP status (400/409/503/502), the UI maps it to a flash message. The
  shared response-mapping helpers (`operation_payload`, `refresh_plan`,
  `run_status`, `provider_task_ref`) live here, not in the view layer.
- `netbox_ceph/services/desired_state_operations.py` — turns a desired-state row
  into a `CephOperation`. The payload/target builders (`build_request`, `_clean`,
  the per-kind `*_payload`/`*_ref` functions) are **Django-free** so they unit
  test without a NetBox runtime (`tests/test_desired_state_operations.py`, the
  plain-pytest CI layer). `build_operation(instance)` is the thin Django wrapper.
  Generated operations use `operation_type=reconcile` and `is_destructive=False`:
  the proxbox-api Proxmox adapter `diff()` treats any non-delete action as
  "ensure" and resolves create/update/noop from live state, so a generated
  reconcile is never destructive. The active kind mapping is only pool→`pool`
  and filesystem→`filesystem`; each carries a required exact execution node.
  RBD and RGW/S3 model names raise `DesiredStateContractError` and have no UI
  generation route. The versioned fixture at
  `tests/fixtures/ceph_v2_writer_contract.v1.json` pins field names and aliases
  shared with proxbox-api #258.

### Plan/approval invariants

- A requester needs `request_cephoperation` and `apply_cephoperation`; a
  different actor needs `approve_cephoperation`.
- Direct and desired-state-generated operation requests enforce the same two
  requester permissions and snapshot the authenticated username.
- Every plan stores backend plan/digest/backend endpoint/configuration revision/
  requester/expiry plus the plugin endpoint ID, provider ID and kind, exact
  execution node, local configuration digest, and local request digest. The
  local digest fingerprints endpoint routing and provider configuration without
  persisting credentials. These snapshots are copied to approvals and runs and
  must match before and after every authority reservation and every recovery
  response. Refresh
  appends a new plan and marks older unapplied authority
  stale; validations are never deleted. A ten-minute nonce lease permits safe
  planning crash recovery and rejects stale late responses.
- Approval re-resolves all bindings and the request digest. A unique owner UUID
  plus expiry leases approval issuance; only the lease owner may POST approval
  or finalize its response, and an expired takeover invalidates a late owner.
  The approval-to-run relation is one-to-one at the database layer. Legacy `confirmed`,
  `confirmed_by`, and `confirmed_at` fields remain migration history only.
- Multi-row operation/plan/approval/run transitions acquire a consistent
  `select_for_update()` lock order and commit atomically. Named fault-injection
  checkpoints prove partial status/audit writes roll back together. Routing
  rows remain locked across the irreversible approval and apply POSTs; a
  changed endpoint, provider, node, or local configuration fails closed.
- Apply retries the same token at most once. `approval_replayed` recovers the
  original backend run; unresolved transport ambiguity becomes
  `outcome_unknown`, followed only by safe approval/run GETs.
- `X-Proxbox-Actor` is a delegated assertion. Production writes stay blocked
  until an authenticated gateway strips caller input and injects the verified
  NetBox actor; migrations never enable endpoint writes.
- Plans, validations, approvals, and runs are read-only API/UI audit surfaces.
  Migration `0007` preserves legacy rows, stales old authority, and never
  changes `allow_writes`. PostgreSQL-backed tests exercise the real NetBox
  permission backend, row locks, concurrent reservation, lease takeover, and
  protected audit chain; dependency-only pytest is not sufficient evidence for
  these contracts.

### UI surface

- **Operation detail** (`templates/netbox_ceph/cephoperation.html`): **Plan** and
  **Approve & apply** buttons. The latter is available to an independent
  approver after planning. A destructive warning modal is presentation only and
  does not create authority.
- **Provider detail** (`cephprovider.html`): **Reconcile** button → records a
  provider-scoped operation + run from `/ceph/v2/reconcile`.
- **Supported desired-state detail** (pool and filesystem): **Generate
  operation** button → `build_operation` → redirect to the new operation. RBD
  and RGW/S3 rows remain CRUD-only until writer support exists. The shared partial
  `templates/netbox_ceph/inc/generate_operation_controls.html` resolves the URL
  generically via the `viewname` filter.

Action URLs are registered with `register_model_view` on models already listed in
`urls.py::_MODEL_ROUTES`, so `get_model_urls` auto-includes them — no `urls.py`
change is needed when adding a new action to an already-routed model.
