# NM V6 Protocol Reference

English | [简体中文](PROTOCOLS.zh-CN.md)

All contracts are versioned JSON and validated before use. Unknown versions,
unknown fields that affect authority, missing conditional fields, malformed
success results, and stale operation or fencing identifiers fail closed.

## Agent adapter

Adapters expose `probe`, `start`, `poll`, `cancel`, and `collect`. Requests bind
protocol version, Operation, run, Attempt, role, isolated workspace, context
manifest, expected result schema, deadline, fencing token, and allowed
capabilities. Results bind the same Operation and Attempt plus status, session,
candidate commit, changed paths, observations, follow-ups, usage, and adapter
diagnostics.

Provider flags and session behavior stay inside their adapter. Native subagents,
resume, and background tasks are optional optimizations.

## Project actions

Every action declares a non-shell `argv`, repository-relative `cwd`, timeout,
accepted exit codes, environment allowlist, core-injected names, secret
references, result schema, idempotency rule, and—when mutating external
state—observe and reconcile actions. Release, publish, deploy, and rollback are
external mutations. Build is pure and returns an artifact digest.

The core persists an Operation before invocation, injects its ID exactly as
declared, validates `nm-v6/action-result-v1`, then records an observation.
Timeout, process loss, malformed output, `partial`, or `unknown` triggers
observe/reconcile before retry.

## Trusted records

Spec confirmations, staged approvals, auto grants, and revocations are imported
signed records. The verifier trusts configured public keys, not a caller's
identity string or terminal claim. Records bind nonce, request digest, current
revision, Spec/config hashes, exact scope, issue/expiry time, authenticator, and
signature. Replay, scope expansion, expiry, or revision mismatch fails.

## Evidence and gates

Only redacted bytes are retained. Stored byte digests, receipt bindings, and
blob presence are revalidated at transition time. Gate receipts cite exact
prerequisite decisions and evidence. Pre-action gates never imply that an
external effect occurred; result gates independently observe it.
