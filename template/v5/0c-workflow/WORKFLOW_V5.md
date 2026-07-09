# Workflow V5

Ratified design: `resolutions/RESOLUTION-V5-DESIGN-v1.md`.  
Admin Chinese mirror of this file: `WORKFLOW_V5.zh-CN.md`.

## Maturity status

> **Experimental.** V5 is retained for supervised evaluation and existing
> trials only. Do not use it for unattended `auto`, automatic merge, release,
> deployment, production changes, production credentials, or production data.
> Runner success and built-in checks are diagnostic signals, not independent
> acceptance evidence. The ratified resolution records historical design intent;
> it does not establish that the current implementation meets that intent.

## Core idea

After a **confirmed Spec**, the system implements via **Phase → Task**, with
**disk state** as truth, an experimental **runner**, short **orchestrator**
sessions, and **worker** sessions. Two modes: **staged** and **auto**.

## Directory products

| Path | Role |
| --- | --- |
| `0a-docs/0a-spec/` | Finalized Spec contracts `SPEC-<slug>-V<n>.md` |
| `0a-docs/DECISIONS.md` | Durable decisions |
| `0a-docs/0b-design/prototype/` | Optional prototypes `v1`, `v2`, … |
| `0a-docs/0c-prompts/` | Optional Spec write/review prompts |
| `0b-runtime/INDEX.yaml` | Thin runtime index (mode, phases, locks, pointers) |
| `0b-runtime/tasks/TASK-*.md` | Per-task cards (status, acceptance, context pack) |
| `0b-runtime/issues-ledger.md` | Blocked / skipped / repair-exhausted records |
| `0c-workflow/` | Workflow contracts (English agent source) |
| `0d-scripts/` | verify, check, runner, notify |

## Modes

| Mode | Gate | Merge | Notify |
| --- | --- | --- | --- |
| `staged` | Admin acceptance per Phase | After acceptance → `dev` | Phase done (attention), blockers, all done |
| `auto` | Non-production sandbox trial until hard-stop / authorized skip | No unattended high-impact merge | Progress + attention on stop/skip |

If mode is unspecified at start, the agent/runner **must** present:

1. `staged` — human reviews each Phase before continue  
2. `auto` — trial automation in a disposable, non-production sandbox only

On resume after admin stop, mode may be switched; explain conflicts with
in-flight tasks or unmerged branches first.

Under the current experimental restriction, both modes stop for administrator
control before changing `dev` or another protected ref. The historical auto
design does not grant the current runner that capability.

## Lifecycle

### 0) Finalize Spec

1. Draft anywhere; finalized copy lives under `0a-docs/0a-spec/` with git.
2. Optional helpers: `0a-docs/0c-prompts/write-spec.md`, `review-spec.md`.
3. Admin sets frontmatter `status: confirmed`. Only then execution may start.
4. Validate with project check / CLI status rules (`SPEC_TEMPLATE.md`).

### 1) Bootstrap runtime

1. Orchestrator (or first session) reads confirmed Spec.
2. Writes/updates `0b-runtime/INDEX.yaml` and Task cards under `tasks/`.
3. If mode missing → ask admin (do not invent).
4. `staged`: admin may confirm the split before execution. `auto`: may proceed after valid index+tasks exist.

### 2) Execute

For each Phase in order:

1. Set phase `in_progress` in index.
2. For each Task in the phase:
   - Create work branch from latest `dev` (never commit implementation on `dev`).
   - Orchestrator builds a **minimum context pack** into the task card / worker prompt (`CONTEXT_PACKING.md`).
   - Worker implements, runs task acceptance, self-repairs up to **10** times.
   - On success: update task card and compact report; prepare a candidate and
     stop for administrator-controlled integration to `dev`; after integration,
     sync and evaluate branch cleanup.
   - On repair exhausted without `skip_on_fail`: block + attention.
   - On repair exhausted with `skip_on_fail: true` (auto): ledger + skip + continue.
3. Phase gate: run full `./0d-scripts/verify.sh` (+ phase verify commands).
4. `staged`: notify `phase_awaiting_acceptance`, stop. After accept: ensure merged, mark phase done, next phase.
5. Current experimental `auto`: stop for administrator-controlled integration.
   The historical design would otherwise mark the Phase done and continue.

The remaining lifecycle describes historical design intent; it does not expand
the current V5 runner's authority.

### 3) Complete

- All phases done → `workflow_completed` attention/progress per config.
- Leftover manual items and skips remain in `issues-ledger.md`.
- `workflow_completed` does not authorize or prove release, deployment, or
  production readiness.

## Runner

```bash
python3 0d-scripts/run-workflow.py --agent codex   # or claude / grok
python3 0d-scripts/run-workflow.py --agent codex --mode auto
```

The runner launches short sessions, checks `INDEX.yaml` + task statuses, and
stops on attention conditions. It does not independently revalidate state,
evidence, or Git operations; it does not replace git or invent Spec content.

## Notifications

Events (not raw prose only): see `NOTIFY_EVENTS.md`.

```bash
./0d-scripts/notify-event.sh --event phase_completed --severity progress --message "..."
./0d-scripts/notify-event.sh --event need_review --severity attention --message "..."
```

Feishu is the first channel.

- Secrets: `~/.config/nm-docs/nm-notify-feishu.env` (mode `600`), machine-global.
- Routing: `severity=progress` → progress webhook; `severity=attention` → attention
  webhook; missing split URLs fall back to `FEISHU_WEBHOOK_URL`.
- Project profile lists **env var names** only (`project-profile.yml`); never secrets.
- Quiet vs popup is a Feishu group/notification setting (prefer two groups), not a
  per-message API flag. Card body is built-in; no separate message templates.
- Full setup: `NOTIFY_EVENTS.md` → “Feishu configuration”.

## Self-repair and skip

- Max self-repair attempts per task: **10** (configurable later via index).
- Default cannot skip Phase-blocking or Spec-hard tasks.
- `skip_on_fail: true` only for explicitly optional work.

## Git and deletes

See `BRANCHING.md` and `AGENTS.md`. Summary:

- Base: `dev`. No day-to-day branches from `main`/`master` (hotfix exception).
- No direct implementation commits on `dev`.
- Merge to `dev` before the next unit; clean merged branches carefully.
- Deletes → `.delete-pending/` only.

## Cross-CLI

Contracts are shared. Native subagents are optional. If a CLI lacks subagents,
open a **new session** with the task card path and context pack only
(`AGENT_RECIPES.md`).

## Difference from V4 (informative)

V5 reopens the execution model: index + task cards, hybrid runner/orchestrator/worker,
explicit context packing, event notifications, mode choose/switch, repair=10,
`skip_on_fail`, stricter git/delete rules, EN agent docs with ZH mirrors.
V4 remains available for existing projects.
