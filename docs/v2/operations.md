# Operations And Audit

Ceph v2 operation records provide the audit foundation for a NetBox-only Ceph
control plane.

## Records

- `CephOperation` stores the requested action, desired payload, and exact
  Proxmox `execution_node`.
- `CephPlan` stores the provider-generated preview plus immutable plugin
  endpoint, backend endpoint revision, provider identity/kind, execution-node,
  request, and local-configuration snapshots.
- `CephOperationApproval` stores requester/approver identities, backend plan,
  endpoint, approval, and recovery IDs plus a unique expiring issuance-owner
  lease — never the one-time token or its hash.
- `CephValidationResult` stores plan findings.
- `CephOperationRun` stores apply attempts, backend task references, and the
  copied plan/approval binding snapshots. Its approval relation is one-to-one,
  so one approval cannot authorize two local run rows.
- `CephDriftRecord` stores the latest desired-vs-actual comparison.
- `CephMetricSnapshot` stores the latest metric payload by scope and object.

Plans are append-only. Plans, validations, approvals, and runs are created only
by the service and exposed as read-only API/UI audit surfaces; their state may
advance internally as backend outcomes become known. Only desired state and
operation requests are operator-editable. The operation status and requester
are server-owned.

The control-plane records are distinct from v1 reflected inventory. v1
cluster, daemon, OSD, pool, filesystem, CRUSH rule, flag, and health check
records remain read-only.

## V1 Reflection Sync Failure Semantics

The v1 reflection job treats proxbox-api's HTTP status and its Ceph sync
summaries as separate success conditions. The proxbox-api sync contract returns
HTTP 200. The client accepts only HTTP 2xx responses, then validates the body
against the `CephSyncResponse` envelope and typed `CephSyncSummary` items. Each
summary mirrors the backend's session name, host, resource, non-negative fetched
and written counts, error list, node list, and optional branch schema identifier.
Every summary's `resource` must equal the requested resource; evidence for a
different resource cannot satisfy the requested stage.

A response is not a successful stage when any summary contains an error. The
stage is stored with `status="failed"`, `reason="upstream_errors"`, and the
complete upstream error list. A non-JSON success body, a response that does not
match the typed envelope or summary shape, or a resource mismatch is stored with
`status="failed"` and `reason="malformed_summary"`. The job still calls the
remaining selected resources so that operators can see every clean and failed
stage from a mixed run, but it raises after persisting those results.

No failed run reaches the branch merge step. When branch isolation is active,
the branch remains open for inspection and the saved response includes
`branch_disposition.status="left_open"`, the branch name, and
`branch_disposition.reason="ceph_sync_stage_failed"`. A run whose summaries
are all clean retains the existing merge and conflict-policy behavior.

Every multi-row authority transition locks the operation, plan, approval, and
run in a fixed order and commits atomically. Endpoint/provider routing rows are
re-locked around approval and apply dispatch. A concurrent lease owner, stale
node or configuration digest, unsupported capability, or partial transition
therefore fails closed before it can create new authority.
