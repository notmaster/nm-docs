# Security review

Review the candidate against `AGENTS.md`, `project.json`, and the confirmed Spec.
Focus on protected refs, trusted-control-plane boundaries, sandbox behavior,
secret injection, external-operation idempotency, evidence redaction, and
rollback. Findings are advisory; only independently executed gates can pass.
