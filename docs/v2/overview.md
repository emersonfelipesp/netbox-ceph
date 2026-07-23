# Ceph v2 Overview

Ceph v2 introduces a NetBox desired-state and operations foundation while
leaving the original reflected inventory models read-only. The foundation
stores provider references, operation requests, generated plans, validation
results, apply runs, drift records, and metric snapshots.

The plugin defines desired-state records for pools, CephFS, RBD, and RGW/S3.
Only pool and CephFS currently cross the strict Proxmox mutation boundary; RBD
and RGW/S3 remain writable intent records until typed backend writers exist.

## Model Split

- v1 inventory models continue to mirror Proxmox-managed Ceph state.
- v2 provider, desired-state, and operation-request models are writable NetBox
  control-plane records.
- plans, validations, approvals, and runs are server-owned read-only audit
  records.
- v2 drift and metric snapshot models are read-only records populated by future
  backend reconciliation and telemetry flows.

## Backend Contract

NetBox calls proxbox-api under `/ceph/v2/*` through a feature-detecting
orchestrator client. If the backend route is missing or explicitly unsupported,
the operation fails as unsupported. The plugin never falls back to shell
commands. The `proxbox-ceph-v2-2026-07` contract requires one typed,
node-bound `ProviderOperation`; endpoint/provider/node/configuration snapshots
must remain unchanged from plan through approval and apply.
