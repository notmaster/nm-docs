# Workflow V5

Ratified design: `resolutions/RESOLUTION-V5-DESIGN-v1.md`.  
Admin Chinese mirror of this file: `WORKFLOW_V5.zh-CN.md`.

## Core idea

After a **confirmed Spec**, the system implements via **Phase → Task**, with
**disk state** as truth, a **deterministic runner**, short **orchestrator**
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
| `auto` | Continuous until hard-stop / authorized skip | After verify → merge per branching rules | Progress + attention on stop/skip |

If mode is unspecified at start, the agent/runner **must** present:

1. `staged` — human reviews each Phase before continue  
2. `auto` — unattended until hard-stop or `skip_on_fail` path  

On resume after admin stop, mode may be switched; explain conflicts with
in-flight tasks or unmerged branches first.

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
   - On success: update task card, compact report, merge to `dev`, sync, optional branch cleanup, next task.
   - On repair exhausted without `skip_on_fail`: block + attention.
   - On repair exhausted with `skip_on_fail: true` (auto): ledger + skip + continue.
3. Phase gate: run full `./0d-scripts/verify.sh` (+ phase verify commands).
4. `staged`: notify `phase_awaiting_acceptance`, stop. After accept: ensure merged, mark phase done, next phase.
5. `auto`: mark phase done, progress notify, next phase.

### 3) Complete

- All phases done → `workflow_completed` attention/progress per config.
- Leftover manual items and skips remain in `issues-ledger.md`.

## Runner

```bash
python3 0d-scripts/run-workflow.py --agent codex   # or claude / grok
python3 0d-scripts/run-workflow.py --agent codex --mode auto
```

The runner launches short sessions, checks `INDEX.yaml` + task statuses, and
stops on attention conditions. It does not replace git or invent Spec content.

## Notifications

Events (not raw prose only): see `NOTIFY_EVENTS.md`.

```bash
./0d-scripts/notify-event.sh --event phase_completed --severity progress --message "..."
./0d-scripts/notify-event.sh --event need_review --severity attention --message "..."
```

Feishu is the first channel. Configure separate webhooks for progress vs attention
if desired (e.g. two groups). Future channels plug in without changing producers.

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
