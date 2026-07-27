# Ceph v2 Desired-State Configuration

Ceph v2 adds NetBox-managed **desired-state** configuration objects. These are
the intended configuration an operator manages from NetBox, and they are kept
strictly separate from the v1 reflected inventory models, which continue to
mirror live Proxmox-managed state read-only.

This increment covers **Pools**, **CephFS filesystems**, **RBD image/snapshot**,
and **RGW/S3 realm/zone/user/bucket** desired state. CRUSH editing and daemon
desired-state are tracked in their own follow-up changes.

## Model Split

| Concern | Reflected inventory (v1) | Desired state (v2) |
|---|---|---|
| Pool | `CephPool` (read-only) | `CephPoolDesiredState` (writable) |
| CephFS | `CephFilesystem` (read-only) | `CephFilesystemDesiredState` (writable) |
| RBD image | n/a | `CephRBDImageDesiredState` (writable) |
| RBD snapshot | n/a | `CephRBDSnapshotDesiredState` (writable) |
| RGW realm | n/a | `CephRGWRealmDesiredState` (writable) |
| RGW zone | n/a | `CephRGWZoneDesiredState` (writable) |
| RGW user | n/a | `CephRGWUserDesiredState` (writable) |
| RGW bucket | n/a | `CephRGWBucketDesiredState` (writable) |

Reflected models answer "what does the cluster currently report?". Desired-state
models answer "what should the cluster look like?". The reconciliation between
the two is driven by the existing operation engine only where the selected
provider advertises a matching typed writer. The current
`proxbox-ceph-v2-2026-07` contract supports pool and CephFS generation; RBD and
RGW/S3 rows are intent/audit records only.

## CephPoolDesiredState

Captures the intended configuration of a Ceph pool:

- Identity: `cluster` + unique `name` (`netbox_ceph_pool_desired_identity`).
- Optional `provider` binding for the controller that should apply it.
- Required `execution_node`, the exact Proxmox node persisted into the plan.
- Replication: `size`, `min_size`.
- Placement: `pg_autoscale_mode` (`on` / `warn` / `off`), `crush_rule_name`,
  optional `erasure_code_profile`.
- Usage: `application` (`rbd` / `cephfs` / `rgw` / `other`), `target_size_ratio`,
  `quota_max_bytes`, `quota_max_objects`.
- Data services: `compression_mode` (`none` / `passive` / `aggressive` / `force`).
- `enabled` flag and a `parameters` JSON object. Operation generation accepts
  only #258 writer keys: `add_storages`, `application`, `crush_rule`,
  `erasure_coding`, `min_size`, `pg_autoscale_mode`, `pg_num`, `pg_num_min`,
  `size`, `target_size`, and `target_size_ratio`. Unknown keys fail closed.
  Quotas and non-`none` compression remain storable but cannot generate a
  Proxmox write yet.

## CephFilesystemDesiredState

Captures the intended configuration of a CephFS filesystem:

- Identity: `cluster` + unique `name` (`netbox_ceph_filesystem_desired_identity`).
- Optional `provider` binding.
- Required `execution_node`, plus writer fields `pg_num` and `add_storage`.
- `metadata_pool` references a `CephPoolDesiredState` row; `data_pools` is an
  ordered list of pool names.
- MDS placement: `mds_placement`, `standby_count`, `max_mds`.
- `quota_max_bytes`, `enabled`, and a free-form `parameters` JSON object.

The current writer supports CephFS create/noop with only `pg_num` and
`add_storage`. Metadata/data-pool mapping, MDS placement/count, quotas, and
unknown parameters remain storable but block operation generation when set.

## CephRBDImageDesiredState

Captures the intended configuration of an RBD image:

- Identity: `cluster` + `pool_name` + unique `name`
  (`netbox_ceph_rbd_image_desired_identity`).
- Optional `provider` binding.
- `pool_name` identifies the RBD pool that contains the image.
- Provisioning and layout: `size_bytes`, `object_size`, `stripe_unit`,
  `stripe_count`, and optional EC `data_pool`.
- `features` is a JSON list of RBD feature flags such as `layering`,
  `exclusive-lock`, `object-map`, `fast-diff`, `deep-flatten`, or `journaling`.
- Clone intent: optional `clone_parent_image` and `clone_parent_snapshot`.
- `metadata` stores image `rbd-meta` key/value pairs.
- `enabled` and a free-form `parameters` JSON object for provider-specific
  extensions.

## CephRBDSnapshotDesiredState

Captures the intended state of an RBD snapshot:

- Identity: `image` + unique `name`
  (`netbox_ceph_rbd_snapshot_desired_identity`).
- Optional `cluster` and `provider` binding alongside the parent `image`.
- `enabled` controls reconciliation for the snapshot.
- `protected` records whether the snapshot should be protected before cloning.
- `parameters` stores provider-specific snapshot options.

## RGW realm/zone/user/bucket desired state

Captures the intended RGW/S3 configuration:

- `CephRGWRealmDesiredState`: identity is `cluster` + unique `name`
  (`netbox_ceph_rgw_realm_desired_identity`). Fields are optional `provider`,
  `enabled`, `is_default`, and `parameters`.
- `CephRGWZoneDesiredState`: identity is `cluster` + unique `name`
  (`netbox_ceph_rgw_zone_desired_identity`). Fields are optional `provider`,
  optional `realm`, `zonegroup_name`, `is_master`, `endpoints`,
  `placement_targets`, `enabled`, and `parameters`.
- `CephRGWUserDesiredState`: identity is `cluster` + unique `uid`
  (`netbox_ceph_rgw_user_desired_identity`). Fields are optional `provider`,
  `display_name`, `email`, `tenant_name`, `suspended`, `max_buckets`,
  `quota_max_size_bytes`, `quota_max_objects`, `credential_ref`, `enabled`, and
  `parameters`.
- `CephRGWBucketDesiredState`: identity is `cluster` + unique `name`
  (`netbox_ceph_rgw_bucket_desired_identity`). Fields are optional `provider`,
  optional `owner`, `placement_target`, `versioning_enabled`,
  `quota_max_size_bytes`, `quota_max_objects`, `lifecycle_policy`, `enabled`,
  and `parameters`.

RGW/S3 access keys are never stored in NetBox. `credential_ref` is the only
credential-related desired-state field, and it is an opaque pointer to keys held
by proxbox-api or its secret store. Do not add `access_key`, `secret_key`,
`password`, or `token` fields to these models or serializers.

## Reconciliation Path

Supported desired-state objects feed the plan/apply engine. An operator (or
automation) creates a node-bound `CephOperation` whose `target_kind` is `pool`
or `filesystem` and whose `desired` payload contains only the exact #258 writer
fields. The orchestrator posts one canonical desired object to proxbox-api
`/ceph/v2/plan` and `/ceph/v2/apply`, producing `CephPlan`,
`CephValidationResult`, `CephOperationApproval`, and `CephOperationRun`
records. RBD/RGW kinds and unsupported pool/CephFS fields are rejected before
planning; there is no generic payload filtering or provider fallback.

Secrets are never stored on desired-state objects. Provider credentials remain
behind the provider's opaque `credential_ref`, and any payload crossing the
orchestrator boundary is redacted.

## REST API

- `GET/POST /api/plugins/ceph/pool-desired-states/`
- `GET/PUT/PATCH/DELETE /api/plugins/ceph/pool-desired-states/{id}/`
- `GET/POST /api/plugins/ceph/filesystem-desired-states/`
- `GET/PUT/PATCH/DELETE /api/plugins/ceph/filesystem-desired-states/{id}/`
- `GET/POST /api/plugins/ceph/rbd-image-desired-states/`
- `GET/PUT/PATCH/DELETE /api/plugins/ceph/rbd-image-desired-states/{id}/`
- `GET/POST /api/plugins/ceph/rbd-snapshot-desired-states/`
- `GET/PUT/PATCH/DELETE /api/plugins/ceph/rbd-snapshot-desired-states/{id}/`
- `GET/POST /api/plugins/ceph/rgw-realm-desired-states/`
- `GET/PUT/PATCH/DELETE /api/plugins/ceph/rgw-realm-desired-states/{id}/`
- `GET/POST /api/plugins/ceph/rgw-zone-desired-states/`
- `GET/PUT/PATCH/DELETE /api/plugins/ceph/rgw-zone-desired-states/{id}/`
- `GET/POST /api/plugins/ceph/rgw-user-desired-states/`
- `GET/PUT/PATCH/DELETE /api/plugins/ceph/rgw-user-desired-states/{id}/`
- `GET/POST /api/plugins/ceph/rgw-bucket-desired-states/`
- `GET/PUT/PATCH/DELETE /api/plugins/ceph/rgw-bucket-desired-states/{id}/`

## UI

All desired-state models have full CRUD pages under the **Ceph -> Desired
State** navigation group, with list, detail, add, edit, and delete views.

## Generate operation (declarative → imperative)

Each supported desired-state detail page has a **Generate operation** button. It
builds a `CephOperation` from the row and opens it, ready to
[plan and apply](plan-apply.md).
No fields are duplicated by hand — the operation's `target_kind`, `target_ref`,
and `desired` payload are derived from the desired-state row by
`netbox_ceph.services.desired_state_operations`:

| Desired-state model | `target_kind` | `target_ref` |
|---|---|---|
| `CephPoolDesiredState` | `pool` | `name` |
| `CephFilesystemDesiredState` | `filesystem` | `name` |

Generated operations use `operation_type=reconcile` and are non-destructive: the
proxbox-api Proxmox adapter resolves create/update/noop from live state, never a
delete. The exact execution node and typed payload are copied into the operation
and later into every authority record. RBD and RGW/S3 pages deliberately expose
no generate route or button until corresponding writer support exists. Their
opaque `credential_ref` values never cross the current mutation boundary.
