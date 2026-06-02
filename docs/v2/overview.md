# Ceph v2 Overview

Ceph v2 introduces a NetBox desired-state and operations foundation while
leaving the original reflected inventory models read-only. The foundation
stores provider references, operation requests, generated plans, validation
results, apply runs, drift records, and metric snapshots.

This first v2 increment does not define desired-state configuration for pools,
CephFS, RGW, RBD, or other Ceph resources. Those resource-specific models and
workflows belong to later changes.

## Model Split

- v1 inventory models continue to mirror Proxmox-managed Ceph state.
- v2 provider and operation models are writable NetBox control-plane records.
- v2 drift and metric snapshot models are read-only records populated by future
  backend reconciliation and telemetry flows.

## Backend Contract

NetBox calls proxbox-api under `/ceph/v2/*` through a feature-detecting
orchestrator client. If the backend route is missing or explicitly unsupported,
the operation fails as unsupported. The plugin never falls back to shell
commands.
