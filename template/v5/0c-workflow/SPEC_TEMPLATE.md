# Spec Template (NM V5)

File name: `0a-docs/0a-spec/SPEC-<slug>-V<n>.md`

Agent source language: **English** (required for execution). Optional admin
translation may live beside it as `SPEC-<slug>-V<n>.zh-CN.md` but is not used
for execution.

## Frontmatter (required)

```yaml
---
spec_id: SPEC-example-V1
title: Example feature
status: draft          # draft | confirmed | final | deprecated
version: 1
workflow: v5
# Optional default only; launch may override. If unset at run start → admin chooses.
execution_mode:        # staged | auto | leave empty
skip_on_fail_default: false
---
```

Execution requires `status: confirmed` or `status: final`.

## Body sections (required)

1. **Problem** — what user/problem this solves (no implementation noise).
2. **Goals** — outcomes.
3. **Non-goals** — explicit out of scope.
4. **Constraints** — hard limits (security, perf, compatibility).
5. **Acceptance criteria** — testable bullets (Phase/Task must map here).
6. **Architecture / design notes** — enough to implement without re-deciding.
7. **Suggested phases** (optional) — orchestrator may refine into Phase → Task.
8. **Risks** — known risks and mitigations.
9. **Open questions** — must be empty or explicitly deferred before confirm.

## Optional task-level flags in Spec

When listing suggested tasks:

```markdown
- [ ] TASK idea: optional docs polish (`skip_on_fail: true`)
```

Hard acceptance items must never be marked `skip_on_fail`.

## Confirm checklist (admin)

- [ ] Acceptance criteria are testable
- [ ] Non-goals clear
- [ ] No unresolved open questions that block implementation
- [ ] `status` set to `confirmed`
