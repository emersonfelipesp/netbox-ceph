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
- `netbox-ceph_plugin/` — main plugin package
- `netbox-ceph_plugin/models/` — Django ORM models
- `netbox-ceph_plugin/views/` — Django views and viewsets
- `netbox-ceph_plugin/api/` — DRF serializers and API endpoints
- `netbox-ceph_plugin/templates/` — Django HTML templates
- `tests/` — unit and integration tests

## Automatic Production Deployment

New commits to `main` automatically deploy to `netbox.nmulti.cloud`.

**Deploy job in `.gitea/workflows/deploy-production.yml`:**
- Triggers on `push: [main]` and `workflow_dispatch` (optional `ref` input).
- Runs on the `prod-deploy` runner, which executes **on the production host**.
- Runs the local deploy script `/opt/nmulticloud/deploy/bin/deploy-netbox-plugin ceph "$REF"`
  directly (mirroring the `deploy-app` pattern used by sibling services); it
  falls back to `ssh nmc-prod-207 -- deploy-plugin ceph "$REF"` only when the
  script is absent (runner not co-located with the target).

**Security hardening:**
- REF is passed via an environment variable, not direct context interpolation.
- A bash `case` statement validates the ref format (version tags, `main`/`develop`,
  7+ char commit SHAs) before use.

**What `deploy-netbox-plugin ceph <ref>` does** (on the prod host, as the runner):
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
- Verify live: `curl -sS https://netbox.nmulti.cloud/api/plugins/ceph/` → `403`
  (auth-gated, plugin loaded).

**Manual deployment trigger:**
```bash
# Manual dispatch of the deploy workflow
nms git actions run netbox-ceph .gitea/workflows/deploy-production.yml -r main -f ref=v0.1.0

# Or directly on the production host
/opt/nmulticloud/deploy/bin/deploy-netbox-plugin ceph v0.1.0
```

For comprehensive deploy infrastructure documentation, see `/root/personal-context/nmulticloud-context/CLAUDE.md` section "Automatic Plugin Deployment to Production".

---

# netbox-ceph Architecture Notes

## Ceph v2 Desired-State And Operations Foundation

`netbox-ceph` keeps the v1 reflected inventory models intact and read-only.
`CephCluster`, `CephDaemon`, `CephOSD`, `CephPool`, `CephFilesystem`,
`CephCrushRule`, `CephFlag`, and `CephHealthCheck` continue to mirror
Proxmox-managed Ceph state.

Ceph v2 adds a separate NetBox control-plane foundation:

- `CephProvider` records backend/provider references and capability metadata.
- `CephOperation` records requested desired-state actions.
- `CephPlan` records provider-generated previews.
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
  `erasure_code_profile`, and a free-form `parameters` JSON map. Unique per
  (`cluster`, `name`) via `netbox_ceph_pool_desired_identity`.
- `CephFilesystemDesiredState` — desired CephFS config: `metadata_pool` (FK to a
  `CephPoolDesiredState`), `data_pools` (JSON list), `mds_placement`,
  `standby_count`, `max_mds`, `quota_max_bytes`, and `parameters`. Unique per
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

These models are writable NetBox objects (full CRUD UI + REST). An operator
edits desired state, then a `CephOperation` references it to produce a
`CephPlan` preview and, after validation, a `CephOperationRun` apply attempt
through the orchestrator. Desired-state objects hold no secrets — provider
credentials remain `credential_ref` pointers only. RGW/S3 users may store only
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

## Orchestrator Feature Detection

`netbox_ceph.services.orchestrator.CephOrchestratorClient` calls proxbox-api
`/ceph/v2/*` routes using the existing `netbox_proxbox` FastAPI request
context. HTTP 404/501 becomes `CephOrchestratorUnsupported`; connection errors
become `CephOrchestratorUnavailable`.

Unsupported operations fail clearly. Do not add shell command fallbacks or local
Ceph CLI execution paths.

## Orchestrator Response Mapping

proxbox-api (#95) returns `PlanResponse`/`OperationRun` with `operations`,
`blocked_actions`, `warnings`, `live_state_summary`, `provider_task_refs` (a
**list** of Proxmox UPIDs), and `status` in
`completed`/`running`/`failed`/`blocked`/`cancelled`. These field names differ
from the NetBox `CephPlan`/`CephOperationRun` models, so
`netbox_ceph/services/ceph_v2_responses.py` (pure, Django-free, unit-tested in
`tests/test_v2_response_mapping.py`) translates them:

- `map_run_status()` — proxbox status → `CephOperationStatusChoices`
  (`completed`→`succeeded`, `running`→`applying`, `blocked`→`failed`, …).
- `provider_task_ref()` — joins `provider_task_refs` (list) into the singular
  `CephOperationRun.provider_task_ref`, with back-compat for singular keys.
- `plan_fields_from_response()` — derives `intended_changes`/`expected_tasks`/
  `summary`/`is_destructive`/`blast_radius`/`provider_target` from `operations`/
  `blocked_actions`/`warnings`/`live_state_summary`, preferring explicit legacy
  fields when present.

`netbox_ceph/api/views.py` wraps these with the `ChoiceSet` validation. The full
backend response is always retained in `CephPlan.raw` / `CephOperationRun.result`.
When proxbox-api response schemas change, update this mapper (and its tests), not
the view handlers.

## Declarative → Imperative: Operation Actions And The Desired-State Bridge

The declarative desired-state models and the imperative
`CephOperation` → `CephPlan` → `CephOperationRun` engine are wired together by two
service modules, both consumed by the REST API (`netbox_ceph/api/views.py`) and
the NetBox web action views (`netbox_ceph/views.py`) so REST and UI share one
implementation:

- `netbox_ceph/services/operation_actions.py` — owns the orchestrator call plus
  persistence/status transitions for `plan_operation()`, `apply_operation()`, and
  provider `reconcile_provider()`. Failures raise a typed `OperationActionError`
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
  reconcile is never destructive. Kind mapping: pool→`pool`,
  filesystem→`filesystem`, rbd_image→`rbd_image` (`pool/name`),
  rbd_snapshot→`rbd_snapshot` (`pool/image@snap`),
  rgw_{realm,zone,user,bucket}→`rgw_*`. RGW users carry only the opaque
  `credential_ref` — never access/secret keys.

### UI surface

- **Operation detail** (`templates/netbox_ceph/cephoperation.html`): **Plan** and
  **Apply** buttons. Apply shows only when the operation is `planned`; destructive
  or confirmation-required operations route through a Bootstrap confirm modal that
  posts `confirmed=true`.
- **Provider detail** (`cephprovider.html`): **Reconcile** button → records a
  provider-scoped operation + run from `/ceph/v2/reconcile`.
- **Desired-state detail** (all 8 models): **Generate operation** button →
  `build_operation` → redirect to the new operation. The shared partial
  `templates/netbox_ceph/inc/generate_operation_controls.html` resolves the URL
  generically via the `viewname` filter.

Action URLs are registered with `register_model_view` on models already listed in
`urls.py::_MODEL_ROUTES`, so `get_model_urls` auto-includes them — no `urls.py`
change is needed when adding a new action to an already-routed model.
