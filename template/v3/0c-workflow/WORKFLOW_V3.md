# Workflow V3.1

NM V3.1 is a lightweight, Goal-driven workflow. It keeps durable project rules
small, makes project documents opt-in, and separates ordinary local automation
from protected Git operations and administrator acceptance.

## Two Entry Paths

### Standalone Goal

Use for a small change or later maintenance when the administrator did not ask
for a spec or Plan:

```text
administrator request
→ self-contained standalone Goal
→ task branch from exact origin/dev
→ implementation + tests + configured review
→ Goal verification
→ administrator decides whether to integrate dev
```

### Planned Work

Use for multi-Goal or higher-context work:

```text
optional 0a-docs/spec.md
→ Plan + Plan branch from exact origin/dev
→ just-in-time self-contained Goals
→ Goal branches from current Plan head
→ Goal verification + configured review
→ local Goal-to-Plan integration
→ one full verification after all Goals
→ administrator reviews the Plan result
```

An existing `spec.md`, design document, prototype, or architecture document is
not active context unless the project-owned block in `AGENTS.md` lists it.

## Optional Spec

Create `0a-docs/spec.md` only when the administrator requests one. Start from
`0c-workflow/SPEC_TEMPLATE.md`. Its YAML metadata distinguishes:

- `spec_version`: project specification version;
- `workflow_version`: installed NM V3 version;
- authors and reviewers, including provider/product/model for agents;
- reviewer decisions bound to the reviewed spec version;
- administrator acceptance as a record, never as external-action authority.

Changing the Markdown body without changing `spec_version` invalidates workflow
validation. A new spec version invalidates old current-version reviews and
acceptance until they are renewed.

## Plan And Goal State

Plan states:

```text
draft → ready → in_progress → awaiting_review → completed
                   ↘ needs_replan | blocked | cancelled
```

Goal states:

```text
planned → in_progress → reviewing → verified → integrated → archived
                       ↘ blocked | cancelled
```

The main agent owns status and execution-record updates. Child agents return a
structured result; they do not declare their own Goal integrated or complete.
On platforms with child-agent capability, give a general instruction to choose
a suitable available child model from task difficulty. V3.1 does not define a
provider-specific adapter or fixed model mapping.

## Goal Contract

Every Goal is a self-contained task packet with:

- source request and authority boundary;
- objective, required context snapshot, scope, and exclusions;
- exact files/references to read;
- concrete TODO list;
- branch and optional Worktree;
- verification commands and acceptance criteria;
- review policy;
- stop conditions;
- compact execution, verification, review, and integration evidence.

The default review policy is self-review by the implementation child agent:

```yaml
review:
  independent_reviewer_required: false
```

Set it to `true` only when the administrator explicitly requests an independent
reviewer before Goal execution starts.

## Execution And Integration

1. Complete the Git preflight in `BRANCHING.md`.
2. Create the Plan or standalone Goal branch from exact `origin/dev`.
3. For planned work, create one Goal just in time from the current Plan head.
4. Give the child agent the Goal file. It implements, writes tests, runs the
   Goal commands, self-reviews by default, and returns a structured report.
5. The main agent checks the report and diff, records evidence, and locally
   integrates a verified Goal into the Plan branch.
6. Repeat for later Goals. Do not run the full project verification per Goal.
7. After all Goals are integrated, run the full project verification once.
8. If it passes, set the Plan to `awaiting_review` and emit the
   `work_completed` attention event through `nm_v3.py finish`.
9. Only an explicit administrator instruction may integrate/push protected refs.

If the full verification fails, reopen the responsible Goal when identifiable;
otherwise set the Plan to `blocked`. Do not declare the Plan ready.

## Requirement Changes

- A clarification that does not change scope or acceptance may update the active
  Goal and continue after the main agent records the change.
- A material scope, acceptance, dependency, data, permission, or security change
  moves the Plan to `needs_replan`, invalidates affected future work, emits an
  attention event, and stops later Goals.
- An independent new request becomes another Plan or standalone Goal.

## Protected Integration

One administrator instruction may conditionally authorize Plan-to-`dev`, push,
then `dev`-to-stable and push. The agent must still:

1. fetch and compare the expected remote `dev` SHA;
2. integrate the Plan candidate into `dev`;
3. run full verification on the exact `dev` result;
4. push `dev` only if it passes;
5. fetch and compare the expected stable SHA;
6. integrate only the verified `dev` result into stable;
7. verify the stable result and push only if it passes.

Any moved ref, conflict, or failed check stops the sequence and emits attention.

## Notifications

Use the fixed event catalog in `NOTIFY_EVENTS.md`. Progress and attention use
distinct Feishu webhooks. Attention never falls back to progress. Each state
transition gets at most one automatic delivery attempt; failures are recorded
and reported without undoing completed engineering work.

The final completion of a standalone Goal or Plan always emits
`work_completed` through attention so the administrator receives a visible
handoff rather than an ordinary progress update. The `finish` command validates
the subject and records an idempotency key and delivery result in template
state.

## Completion And Cleanup

- Standalone Goal completion reports verification, review, branch, and whether
  administrator acceptance or protected integration remains.
- Plan completion reports every Goal, full verification, unresolved issues, and
  exact candidate commit/tree.
- Remove a Goal Worktree only after its agent stopped and its changes are safely
  integrated. Retain Goal branches until Plan acceptance and `dev` integration.
- Retain the Plan branch while it carries review, release, dependency, backup, or
  rollback responsibility. Remote deletion always needs explicit authority.
