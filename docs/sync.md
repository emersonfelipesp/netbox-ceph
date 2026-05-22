# Sync Jobs

Ceph sync reuses the `netbox-proxbox` sync job pattern, calling Ceph-aware
endpoints on `proxbox-api`. v0.0.1.post1 is read-only; no writes propagate back to
Ceph.
