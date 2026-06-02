# Ceph v2 Providers

`CephProvider` identifies an external system that can plan, apply, reconcile, or
report Ceph state for a cluster. Provider kinds include Proxmox, Ceph Dashboard,
RGW Admin, Prometheus, external systems, and future backend extensions.

Provider records store:

- Cluster, kind, name, and default/enabled flags.
- Base URL and SSL verification policy.
- Capability and status metadata.
- An opaque `credential_ref`.

## Secret Rule

`credential_ref` is a pointer only. Actual credentials and tokens must live in
proxbox-api or its configured secret store. NetBox must not store provider
passwords, tokens, access keys, or secret material.
