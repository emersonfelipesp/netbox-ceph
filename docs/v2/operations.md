# Operations And Audit

Ceph v2 operation records provide the audit foundation for a NetBox-only Ceph
control plane.

## Records

- `CephOperation` stores the requested action and desired payload.
- `CephPlan` stores the provider-generated preview.
- `CephValidationResult` stores plan findings.
- `CephOperationRun` stores apply attempts and backend task references.
- `CephDriftRecord` stores the latest desired-vs-actual comparison.
- `CephMetricSnapshot` stores the latest metric payload by scope and object.

The writable operation records are distinct from v1 reflected inventory. v1
cluster, daemon, OSD, pool, filesystem, CRUSH rule, flag, and health check
records remain read-only.
