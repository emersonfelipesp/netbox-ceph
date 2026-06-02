# Plan And Apply

Ceph v2 operations use a plan-then-apply workflow.

1. Create or update a `CephOperation` with the requested target, operation type,
   and desired payload.
2. POST the operation `plan` action. NetBox calls proxbox-api `/ceph/v2/plan`
   and stores the returned `CephPlan` and validation results.
3. Review the plan and validation output.
4. POST the operation `apply` action only after the operation is planned.

Destructive or confirmation-required operations must have `confirmed=True`
before apply. Apply creates a `CephOperationRun` audit record for every backend
attempt.

If proxbox-api does not expose the v2 route, the run is marked `unsupported` and
the API returns a clear conflict response. No shell fallback exists.
