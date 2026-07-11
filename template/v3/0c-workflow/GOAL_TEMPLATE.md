---
schema_version: 1
plan_id: p001
goal_id: g001
status: planned
source_type: plan
base_branch: feature/plan-p001-slug
working_branch: task/goal-p001-g001-slug
verification_status: not_run
verification_commit: null
self_review_status: not_run
independent_review_status: not_required
integration_status: not_integrated
integration_commit: null
review:
  independent_reviewer_required: false
---

# Goal: <title>

Planned Goal file name:

```text
goal-p001-g001-<slug>.md
```

Standalone Goal file name and metadata:

```text
goal-g001-<slug>.md
plan_id: null
source_type: administrator_request
base_branch: dev
working_branch: task/goal-g001-<slug>
```

## Objective

State one complete, independently executable outcome.

## Source And Authority

- Administrator request or parent Plan:
- Authorized local work:
- External/protected actions not authorized:

## Context Packet

Include the task-relevant facts needed by a child agent. Do not copy unrelated
documents.

- Project rules: `AGENTS.md`
- Parent Plan: `<path | standalone>`
- Required files and references:
- Relevant decisions and constraints:
- Starting commit/tree:

## Scope

- <required change>

## Out Of Scope

- <explicit exclusion>

## TODO

- [ ] <implementation item>
- [ ] Write or update tests.
- [ ] Run Goal-level verification.
- [ ] Self-review the implementation and test coverage.
- [ ] Return a structured report to the main agent.

## Acceptance Criteria

- <observable outcome>

## Verification

Run only the commands needed for this Goal:

```bash
<command>
```

Do not run full Plan verification here unless this Goal explicitly requires it.

## Review Policy

Default:

```yaml
review:
  independent_reviewer_required: false
```

The implementation child agent writes tests and self-reviews. Change this field
to `true` before execution only when the administrator explicitly requests an
independent Reviewer.

## Stop Conditions

- Required context or acceptance is unclear.
- Scope, acceptance, dependencies, data, permissions, or security materially change.
- The base branch or expected Plan head moved.
- A destructive, external, production, or newly privileged action is needed.
- The repair path is exhausted.

## Child Agent Report

Return:

- summary of changes;
- files changed;
- tests written or updated;
- commands and pass/fail/not-run;
- concise failures and repair count;
- self-review findings and fixes;
- commit/tree SHA when available;
- blockers, assumptions, and remaining risks.

## Main Agent Record

Only the main agent updates status and records:

- Verification:
- Self-review:
- Independent review: `<not_required|pending|pass|changes_requested>`
- Integration strategy/source/target/result SHAs:
- Notification event/result:
- Administrator acceptance: `<pending|accepted|changes_requested>`
- Notes:
