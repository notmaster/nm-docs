# Trusted control-plane handoff

Agents may create immutable confirmation or authorization requests. They may
not self-approve them.

1. Export the request digest, nonce, exact Spec/configuration hashes, state
   revision, scope, and expiry.
2. Give that record to the administrator through a control-plane capability
   unavailable to workers and agent contexts.
3. Import only a signed confirmation, grant, or revocation whose authenticator
   is configured and whose public-key fingerprint matches project policy.
4. Let the core verify signature, nonce, expiry, request digest, scope, and
   current revision in one transaction.
5. Never paste a private key, shared secret, raw credential, or signature helper
   capability into agent context.

An approval permits the exact action. It does not replace technical gates or
evidence. A revoked in-flight external operation must be fenced and reconciled
before the run can pause or cancel.
