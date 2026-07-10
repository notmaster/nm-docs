# Delivery recovery

Use the persisted Operation ID to invoke the configured observe action, then the
idempotent reconcile action when needed. Reconstruct the source commit/tree,
artifact, tag/release, environment identity, deployed version, and rollback
binding chain. Retry only a confirmed not-started or safely reconciled effect.
Partial or unknown state requires attention or an already authorized rollback.
