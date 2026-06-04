# Plan And Apply

Ceph v2 operations use a plan-then-apply workflow.

1. Create an operation — either directly (a `CephOperation` with the target,
   operation type, and desired payload) or by clicking **Generate operation** on
   a desired-state row (see [Desired State](desired-state.md)).
2. POST the operation `plan` action (or click **Plan** on the operation page).
   NetBox calls proxbox-api `/ceph/v2/plan` and stores the returned `CephPlan`
   and validation results.
3. Review the plan and validation output.
4. POST the operation `apply` action (or click **Apply**) once the operation is
   planned.

Destructive or confirmation-required operations must have `confirmed=True`
before apply. In the UI these route through a confirmation modal that posts the
confirmation. Apply creates a `CephOperationRun` audit record for every backend
attempt.

If proxbox-api does not expose the v2 route, the run is marked `unsupported` and
the API returns a clear conflict response. No shell fallback exists.

## UI actions

Both layers call the same `netbox_ceph.services.operation_actions` service, so
buttons and REST endpoints behave identically:

| Page | Button | Action |
|------|--------|--------|
| Operation detail | **Plan** | `POST .../operations/{id}/plan/` |
| Operation detail | **Apply** | `POST .../operations/{id}/apply/` (modal posts `confirmed=true` for destructive) |
| Provider detail | **Reconcile** | `POST .../providers/{id}/reconcile/` → records a provider-scoped run from `/ceph/v2/reconcile` |
| Desired-state detail | **Generate operation** | `POST .../{kind}-desired-states/{id}/generate-operation/` → builds a `reconcile` `CephOperation` and opens it |

## Reconcile

`reconcile` pulls live provider state back into NetBox through proxbox-api
`/ceph/v2/reconcile`. It is exposed on `CephProvider` (REST `reconcile` action +
**Reconcile** button) and records an auditable provider-scoped `CephOperation`
and `CephOperationRun`.
