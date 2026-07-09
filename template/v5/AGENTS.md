# Agent Rules (NM V5)

Hard rules for every run. Full workflow: `0c-workflow/WORKFLOW_V5.md`.
Design resolution (ratified): `0c-workflow/resolutions/RESOLUTION-V5-DESIGN-v1.md`.
Launch recipes: `0c-workflow/AGENT_RECIPES.md`.

**Language:** This English file is the agent execution source. The administrator
mirror is `AGENTS.zh-CN.md`. Do not load Chinese mirrors for execution unless
the administrator explicitly asks for a translation.

## Maturity And Safety Override

- **V5 is experimental.** It is retained for supervised evaluation and existing
  trials only.
- Do not use V5 for unattended `auto`, automatic merge, release, deployment,
  production changes, production credentials, or production data.
- Runner exit success, `workflow:check`, and `verify` are diagnostic signals,
  not independent acceptance evidence or production-readiness gates.
- This current operational restriction governs V5 use. It does not rewrite the
  ratified resolution, which remains a record of historical design intent.

## Language And Environment

- Communicate with the administrator in the language they use (default: Simplified Chinese is fine for chat).
- All workflow rules, task cards, index fields, and agent prompt skeletons are English.
- Default timezone: UTC+8.

## Execution Contract

- Runtime truth is on disk:
  - Index: `0b-runtime/INDEX.yaml`
  - Tasks: `0b-runtime/tasks/TASK-*.md`
  - Issues ledger: `0b-runtime/issues-ledger.md`
  - Confirmed Spec under `0a-docs/0a-spec/`
- Read `AGENTS.md`, the confirmed Spec path from the index, and `INDEX.yaml` before substantial work. Load other docs only when needed.
- Execute only a Spec with frontmatter `status: confirmed` (or `final`).
- Without a confirmed Spec and a runnable index (or an explicit bootstrap to create one), do not start substantial implementation.

## Roles

- **Runner** (`0d-scripts/run-workflow.py`): experimentally advances phases, gates, notifications, and resume checks.
- **Orchestrator session** (short-lived): splits Phase/Task, builds minimum context packs, dispatches workers, updates index.
- **Worker session**: implements one Task, runs acceptance, self-repairs, updates the task card, returns a compact report.
- Do not keep a long-lived “main brain” conversation as the project memory. Persist decisions to disk.

## Execution Modes

- If `mode` in the index is `unspecified` or empty, stop and ask the administrator to choose:
  1. `staged` — human acceptance after each Phase before merge-continue
  2. `auto` — non-production worker trial inside a disposable sandbox
- `staged`: one Phase per orchestrated cycle; after Phase verify, notify `phase_awaiting_acceptance`, stop; merge to `dev` only after acceptance.
- `auto`: only for disposable, non-production trials without high-impact
  capability. After task/phase verify, it may continue within that sandbox. It
  is not authorization to merge, release, deploy, or use production access; it
  must stop before changing `dev` or any other protected ref.
- On resume after admin stop, the administrator may request a mode switch. Update `INDEX.yaml`, explain file/state conflicts first (in-flight tasks, unmerged branches, half-finished phase).

## Stop Conditions (hard)

Stop, set blocked state, and send an `attention` notification when:

- Hard risk: secrets, paid resources, production data, destructive/irreversible ops, unsafe force-push, etc.
- Acceptance gate (staged Phase) waiting for admin
- Conflict with Spec or need to change Spec
- Self-repair exhausted (**10** attempts) on a Task **without** `skip_on_fail: true`
- `dev` merge conflict that cannot be resolved safely

## Skip Rule (auto)

- Default `skip_on_fail: false`.
- Only if the Task (or Spec task entry) sets `skip_on_fail: true` and repairs hit 10: record in `issues-ledger.md`, mark task `skipped`, emit `task_skipped`, continue.
- Never skip Spec hard requirements or Phase-blocking acceptance without that flag.

## Branching

- `dev` is the integration branch. Never develop day-to-day work from `main`/`master` (hotfix only from `main`).
- Do not commit implementation directly on `dev`. Create a work branch from latest `dev`.
- Before the next work unit: request administrator-controlled integration into
  `dev` and sync (merge / squash / ff — agent proposes, administrator controls).
  Then decide whether the safely integrated work branch can be deleted. Then
  create a new branch for the next unit.
- Never auto-delete `main`, `dev`, `release/*`, `hotfix/*`, unmerged branches, or branches still under review/acceptance.
- Details: `0c-workflow/BRANCHING.md`.

## Context Packing

- Orchestrator must not dump the whole project into a worker.
- Pack: task goal, path allow/deny, Spec slice pointers, acceptance commands, global prohibitions, links to only required files.
- Details: `0c-workflow/CONTEXT_PACKING.md`.

## Verification

- Task done: task acceptance commands pass (default may be a subset); worker self-repairs up to 10.
- Phase done: `./0d-scripts/verify.sh` and all Phase-level verify commands pass.
- Details: `0c-workflow/VERIFY.md`.

## Notifications

- Emit workflow **events** via `./0d-scripts/notify-event.sh` (not free-form only).
- Channels are pluggable; Feishu is the first adapter. Progress vs attention routing is configuration.
- Feishu secrets: `~/.config/nm-docs/nm-notify-feishu.env` (mode `600`). Do not commit webhooks or secrets.
- Dual channel: `FEISHU_WEBHOOK_PROGRESS` / `FEISHU_WEBHOOK_ATTENTION` (+ matching `FEISHU_SIGN_SECRET_*`); fallback `FEISHU_WEBHOOK_URL`.
- `0c-workflow/project-profile.yml` declares env **names** only. Setup and signature details: `0c-workflow/NOTIFY_EVENTS.md`.
- Event catalog: `0c-workflow/NOTIFY_EVENTS.md`.
- Notification failure must not be silently treated as success.

## Safety

- Never overwrite uncommitted user changes. No destructive git ops unless explicitly requested.
- **No physical file deletes.** Move paths to `.delete-pending/` and report; administrator deletes manually.
- Prefer the simplest implementation. No unrequested features or opportunistic refactors.
- Every changed line must trace to the current Task/Phase or an explicit administrator request.
