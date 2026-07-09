# Task Card Contract (NM V5)

Path: `0b-runtime/tasks/TASK-<phase>-<nn>.md`  
Example: `TASK-P01-01.md`

## Frontmatter

```yaml
---
id: TASK-P01-01
phase_id: P01
title: Short imperative title
status: pending   # pending | ready | in_progress | verifying | done | skipped | blocked
skip_on_fail: false
branch: ""
repair_attempts: 0
repair_max: 10
acceptance:
  - "./0d-scripts/verify.sh"   # override per task; phase still runs full verify
context:
  paths_allow:
    - "src/foo/"
  paths_deny:
    - "0c-workflow/"
  spec_slices:
    - "Acceptance criteria #1-2"
  must_read:
    - "0a-docs/0a-spec/SPEC-example-V1.md"
  must_not_read_unless_needed:
    - "0a-docs/0b-design/prototype/"
report_format: compact_v1
---
```

## Body

### Goal

One short paragraph: what “done” means for this task only.

### Implementation notes

Only facts the worker needs (APIs, constraints). Prefer pointers over paste.

### Acceptance

Commands or checks (mirror frontmatter). Worker must not mark `done` until these pass.

### Worker report (filled on completion)

```markdown
## Report
- status: done | skipped | blocked
- summary: <= 5 bullets
- files_touched: list
- verify: pass/fail + command
- residual_risks: none | bullets
- delete_pending: paths moved, if any
```

## Compact report to orchestrator

Workers return (and write) only:

1. `status`
2. `summary` (≤5 bullets)
3. `files_touched`
4. `verify` result
5. pointers to ledger rows if skipped/blocked

No full log dumps into the orchestrator session.
