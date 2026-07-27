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

Every multi-row authority transition locks the operation, plan, approval, and
run in a fixed order and commits atomically. Endpoint/provider routing rows are
re-locked around approval and apply dispatch. A concurrent lease owner, stale
node or configuration digest, unsupported capability, or partial transition
therefore fails closed before it can create new authority.
