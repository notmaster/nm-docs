# Agent Rules

This file contains the durable NM V3 rules that every agent must follow. Read
`0c-workflow/WORKFLOW_V3.md` only when planning or executing a Plan or Goal.

## Language And Environment

- Use Simplified Chinese for administrator communication and project documents
  unless the administrator requests another language.
- Use ISO 8601 timestamps with the local UTC+8 offset.

## Project Rules

Only references listed in the project-owned block below are active project
context. Do not discover or read `spec.md`, design documents, prototypes,
architecture notes, or other optional documents merely because they exist.
Required references must exist and be non-empty. Missing or empty optional
references are reported and skipped. Update the English and Chinese blocks
together.

<!-- NM-V3-PROJECT-RULES:START -->
```yaml
references:
  required: []
  optional: []
verification:
  goal_commands: []
  full_command: ./0d-scripts/verify.sh
```
<!-- NM-V3-PROJECT-RULES:END -->

## Work Authorization

- Inspection, review, explanation, diagnosis, and status requests are read-only.
- A change request authorizes only scoped edits and normal local verification.
- `Execute Plan <id>` authorizes Goal branches, implementation, Goal-level
  verification, self-review, and local Goal-to-Plan integration in the current
  task. It does not authorize push or protected-branch integration.
- A new task or agent session requires a fresh `Continue Plan <id>` instruction.
  Plan fields record prior intent but do not grant new authority.
- Push, Plan-to-`dev`, `dev`-to-stable, release, deployment, destructive work,
  production access, and remote branch deletion require explicit administrator
  authorization for the exact action.

## Branching

- `main` or `master` is stable; `dev` is integration. They are protected.
- Except for an explicitly classified `hotfix/*`, no file may be modified while
  `main`, `master`, or `dev` is checked out.
- Before ordinary work, require a clean tree, fetch `origin/dev`, confirm local
  `dev` equals `origin/dev`, and create an allowed branch at that exact SHA.
- Allowed ordinary prefixes are `feature/*`, `fix/*`, `docs/*`, `refactor/*`,
  `chore/*`, and `task/*`.
- A planned workflow uses a Plan branch such as `feature/plan-p001-slug`.
  Planned Goal branches use `task/goal-p001-g001-slug` and start from the current
  Plan branch head. A standalone Goal uses `task/goal-g001-slug` from `origin/dev`.
- Goal branches may integrate locally into the Plan branch only after the Goal's
  configured verification and review policy pass.
- Full verification runs once after every Goal is integrated, not after each
  Goal. A failure reopens the affected Goal or moves the Plan to `blocked`.
- Never force-push protected refs. Re-fetch and compare the expected remote SHA
  immediately before an authorized protected integration or push.

## Plan And Goal Workflow

- Plans live in `0b-goals/0a-plans/` and use `plan-p<NNN>-<slug>.md`.
- The active Goal lives in `0b-goals/0b-current/`. Planned Goals use
  `goal-p<NNN>-g<NNN>-<slug>.md`; standalone Goals use
  `goal-g<NNN>-<slug>.md`.
- Keep exactly zero or one active Goal. V3.1 executes Goals serially.
- A small task may use one standalone Goal without a Plan or spec.
- A planned task may use an optional `0a-docs/spec.md`, then a Plan, then Goals
  created just in time.
- The main agent is the only writer of Plan/Goal status and execution records.
  A child agent reads the self-contained Goal, changes code, writes tests,
  self-reviews by default, and returns a structured report.
- When child-agent capability exists, use the platform's general instruction to
  select a suitable available child model from the Goal's difficulty and scope.
  Do not assume a provider-specific adapter or hard-code a model name.
- `independent_reviewer_required: false` is the default. Set it to `true` only
  when the administrator explicitly requests an independent reviewer before the
  Goal starts.
- A material change to scope, acceptance, dependencies, data, or security moves
  the Plan to `needs_replan`, stops later Goals, and emits an attention event.

## Verification And Evidence

- Run each Goal's declared commands before marking it `verified`.
- After all Goals are locally integrated, run the full command declared in the
  project rules before marking the Plan `awaiting_review`.
- Separate automated verification, agent review, and administrator acceptance.
  Agent self-review never substitutes for a required command or administrator
  acceptance.
- Record commands, pass/fail/not-run, concise failure summaries, repair count,
  commit/tree SHAs, and review outcome. Do not store raw logs, secrets,
  credentials, or production data in a Goal.

## Notifications

- Emit only catalogued events through `./0d-scripts/notify-event.sh`.
- `progress` reports meaningful state changes. `attention` reports an
  administrator decision, review gate, material risk, or hard stop.
- Final completion always emits `work_completed` through attention so the
  administrator receives a visible handoff.
- Use `nm_v3.py finish` for the final handoff; it validates state, sends an
  unchanged completed subject once, and records the delivery result.
- Do not send heartbeats, per-command events, or duplicates for unchanged state.
- Attention must never fall back to the progress channel. Notification failure
  does not undo completed work, but it must be reported.
- Notification secrets live only in
  `~/.config/nm-docs/nm-notify-feishu.env` with mode `600`.

## Safety

- Never overwrite, stash, commit, or move uncommitted administrator changes.
- Do not run destructive Git or external operations without explicit authority.
- Move project files pending deletion to `.delete-pending/` and wait for
  administrator confirmation.
- After integration, remove a Worktree only when its agent has stopped and its
  commits are safely integrated. Retain Goal and Plan branches while they still
  carry review, release, backup, dependency, or rollback responsibility.
- Remote deletion always requires a new explicit administrator instruction.
