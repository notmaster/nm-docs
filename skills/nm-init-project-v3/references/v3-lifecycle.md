# NM V3.1 Lifecycle

## Source Of Truth

- Template: `template/v3/`
- Manifest: `template/v3/manifest.json`
- Deterministic tool: `tools/nm-v3/nm_v3.py`
- Installed-project state: `.nm-template-state.json`
- Workflow version: `3.1.0`

## Entry Paths

```text
small request → standalone Goal → Goal verification/self-review → administrator integration decision
```

```text
optional 0a-docs/spec.md → Plan → just-in-time Goals → local Plan integration
→ one full verification → administrator Plan review
```

Optional documents are inactive unless the project-owned block in `AGENTS.md`
lists them. `spec.md` contains project requirements and acceptance criteria;
there is no separate Requirements or Acceptance document in V3.1.

## Branches

- Plan: `feature/plan-p001-slug` from exact `origin/dev`.
- Planned Goal: `task/goal-p001-g001-slug` from current Plan head.
- Standalone Goal: `task/goal-g001-slug` from exact `origin/dev`.
- Protected integration and push require explicit administrator authorization.

## Review And Verification

- The implementation child agent writes tests and self-reviews by default.
- `independent_reviewer_required: true` is used only when the administrator
  explicitly requests an independent Reviewer before Goal execution.
- Each Goal runs its own commands. Full project verification runs once after all
  Goals are integrated.
- V3.1 executes one active Goal at a time.
- Automated verification, agent review, and administrator acceptance remain
  distinct.

## Notifications

V3.1 uses strict Feishu `progress` and `attention` channels. Attention never
falls back to progress. Producers emit only the fixed event catalog in the
generated project's `0c-workflow/NOTIFY_EVENTS.md`.
Final standalone-Goal or Plan completion emits `work_completed` through
attention as a visible administrator handoff, not ordinary progress. Use the
idempotent `finish` command so an unchanged completed subject is sent once.

## V3 3.0 Migration

Run a dry-run first. Migration:

1. requires clean, current `dev` and creates a task branch at `origin/dev`;
2. builds `0a-docs/spec.md` from the old Requirements and Acceptance content;
3. preserves markerless legacy AGENTS guidance under `.delete-pending` for
   administrator review and installs the new project-owned rules block;
4. moves the old source documents under `.delete-pending/v3-3.1.0-migration/`;
5. updates template state and requires administrator review of the result.
