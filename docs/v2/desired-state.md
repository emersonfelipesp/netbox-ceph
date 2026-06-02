# Ceph v2 Desired-State Configuration

Ceph v2 adds NetBox-managed **desired-state** configuration objects. These are
the intended configuration an operator manages from NetBox, and they are kept
strictly separate from the v1 reflected inventory models, which continue to
mirror live Proxmox-managed state read-only.

This increment covers **Pools**, **CephFS filesystems**, and **RBD image/snapshot**
desired state. RGW/S3, CRUSH editing, and daemon desired-state are tracked in
their own follow-up changes.

## Model Split

| Concern | Reflected inventory (v1) | Desired state (v2) |
|---|---|---|
| Pool | `CephPool` (read-only) | `CephPoolDesiredState` (writable) |
| CephFS | `CephFilesystem` (read-only) | `CephFilesystemDesiredState` (writable) |
| RBD image | n/a | `CephRBDImageDesiredState` (writable) |
| RBD snapshot | n/a | `CephRBDSnapshotDesiredState` (writable) |

Reflected models answer "what does the cluster currently report?". Desired-state
models answer "what should the cluster look like?". The reconciliation between
the two is driven by the existing operation engine.

## CephPoolDesiredState

Captures the intended configuration of a Ceph pool:

- Identity: `cluster` + unique `name` (`netbox_ceph_pool_desired_identity`).
- Optional `provider` binding for the controller that should apply it.
- Replication: `size`, `min_size`.
- Placement: `pg_autoscale_mode` (`on` / `warn` / `off`), `crush_rule_name`,
  optional `erasure_code_profile`.
- Usage: `application` (`rbd` / `cephfs` / `rgw` / `other`), `target_size_ratio`,
  `quota_max_bytes`, `quota_max_objects`.
- Data services: `compression_mode` (`none` / `passive` / `aggressive` / `force`).
- `enabled` flag and a free-form `parameters` JSON object for provider-specific
  extensions.

## CephFilesystemDesiredState

Captures the intended configuration of a CephFS filesystem:

- Identity: `cluster` + unique `name` (`netbox_ceph_filesystem_desired_identity`).
- Optional `provider` binding.
- `metadata_pool` references a `CephPoolDesiredState` row; `data_pools` is an
  ordered list of pool names.
- MDS placement: `mds_placement`, `standby_count`, `max_mds`.
- `quota_max_bytes`, `enabled`, and a free-form `parameters` JSON object.

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

## Reconciliation Path

Desired-state objects feed the existing plan/apply engine. An operator (or
automation) creates a `CephOperation` whose `target_kind` is `pool`, `cephfs`,
`rbd_image`, or `rbd_snapshot` and whose `desired` payload carries the serialized
desired-state. The
orchestrator client posts that to proxbox-api `/ceph/v2/plan` and
`/ceph/v2/apply`, producing `CephPlan`, `CephValidationResult`, and
`CephOperationRun` records. No new backend contract is introduced here — only
the NetBox-side ability to express pool/CephFS desired state.

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

## UI

Both models have full CRUD pages under the **Ceph → Desired State** navigation
group, with list, detail, add, edit, and delete views.
