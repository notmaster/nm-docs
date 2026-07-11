---
schema_version: 1
plan_id: p001
status: draft
source_type: administrator_request
spec_path: null
spec_version: null
plan_branch: feature/plan-p001-slug
full_verification_status: not_run
full_verification_commit: null
administrator_review_status: pending
---

# Plan: <title>

File name:

```text
plan-p001-<slug>.md
```

## Objective

Describe the final Plan outcome.

## Source And Authority

- Administrator request:
- Current-task instruction:
- Authorized local actions:
- Actions still requiring administrator authorization:

## Active Context

List only context required by this Plan. Optional project documents are active
only when `AGENTS.md` lists them.

- Project rules: `AGENTS.md`
- Spec: `<path and version | not used>`
- Other required references:

## Scope

- <required outcome>

## Out Of Scope

- <explicit exclusion>

## Goal List

| Goal | File | Depends On | Summary | Status |
| --- | --- | --- | --- | --- |
| g001 | `goal-p001-g001-<slug>.md` | none | <summary> | planned |

Create one Goal just in time. V3.1 Goals are serial; create the next Goal only
after the previous Goal is integrated.

## Verification Strategy

- Each Goal runs only its declared Goal-level commands.
- After all Goals are integrated, run the project full verification exactly once.
- Full command: `./0d-scripts/verify.sh`

## Requirement Change Rules

- Clarification without scope/acceptance change: update active Goal and continue.
- Material scope, acceptance, dependency, data, permission, or security change:
  set `status: needs_replan`, stop later Goals, and notify attention.
- Independent new request: create another Plan or standalone Goal.

## Stop Conditions

- Unsafe or unknown Git state.
- Required context is missing or contradictory.
- Scope or acceptance materially changes.
- Production credentials/data or irreversible work is needed.
- Verification repair path is exhausted.
- A merge conflict or moved ref cannot be safely reconciled.

## Execution Record

The main agent records state transitions, Goal results, integration SHAs, full
verification, notifications, and unresolved risks. Do not paste raw logs or
secrets.

## Completion

- Integrated Goals:
- Full verification command/result:
- Candidate commit/tree:
- Administrator review: `<pending|accepted|changes_requested>`
- Protected integration/push: `<not_authorized|authorized|completed>`
- Remaining risks:
