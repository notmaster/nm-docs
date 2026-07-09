---
doc: RESOLUTION-V5-DESIGN
version: v1
status: ratified
ratified: 2026-07-09
workflow: v5
language: en
admin_mirror: RESOLUTION-V5-DESIGN-v1.zh-CN.md
---

# NM V5 Design Resolution (v1)

This document is the ratified design resolution for the NM V5 workflow.
Update it only through an explicit administrator revision (new version, e.g. v2).
Agents treat this file as durable design intent, not as a runtime state file.

## 1. Problem essence and real goals

### Problem statement

After a Spec is finalized, implement the designed product reliably under limited
agent context and interruptible sessions. The administrator intervenes only when
necessary.

### Desired outcome

- Recoverable staged and auto execution loops
- Auditable runtime state on disk
- Graded, pluggable notifications (Feishu first)
- CLI + Skill install/management for humans, CI, and agents
- Controllable context so agents focus intelligence on the work

### Success criteria

1. A finalized Spec passes structural validation and can drive Phase → Task split.
2. **staged**: after each Phase gate and admin acceptance, merge/sync, then auto-enter the next Phase if any.
3. **auto**: continue without stopping unless a hard-stop condition fires; explicit skippable failures follow skip rules.
4. After any interrupt, resume using disk state only (never conversation memory).
5. Workers meet task-level acceptance (self-repair up to 10 attempts), update the task card, then return; Phase gates run full project verify.
6. Notifications use a stable event model with configurable channels; Feishu ships first.
7. Install UX: CLI is source of truth; Skill is a thin entry; skill packaging aligns with `npx skills add` style distribution.
8. Agent-facing docs are English; Chinese mirrors exist for administrators and stay in sync.

## 2. Constraints and assumptions

### Hard constraints

| Area | Rule |
| --- | --- |
| Deliverable | Template + rules + document contracts + deterministic CLI/runner (not a heavy multi-agent platform product) |
| Orchestration | Runner owns stage progression, gates, notify, resume; short-lived orchestrator sessions make judgments; workers implement |
| Multi-CLI | Claude Code / Codex / GrokBuild: shared contracts, per-CLI adapters and graceful degradation |
| Truth source | Disk state (thin index + per-task cards). Not a long-lived main-agent memory |
| Language | Agent flow/rules/contracts/prompt skeletons → **English**. Admin mirrors → **Simplified Chinese**. Updates must sync. More locales later; no full i18n engine in v5.0 |
| Mode | If mode is unspecified at start → force admin choice (staged / auto with explanations). After stop, resume may switch mode; switching rewrites state files and must explain conflicts with current progress |
| Stop conditions | Hard risk / irreversible ops; acceptance gates; Spec conflict / Spec change required → `attention`. Self-repair cap **10**. Default: cannot skip hard failures. Only tasks/specs with explicit `skip_on_fail: true` may skip after 10 failed repairs in auto, with ledger entry |
| Git | Except hotfix: no day-to-day work branches from `main`/`master`. Integration baseline is **`dev`**. Agents must not commit implementation directly on `dev`. Branch from `dev` → work → merge back to `dev` and sync before next unit → optionally delete merged work branch → new branch for next unit. Merge strategy (merge/squash/ff) is agent judgment |
| Deletes | No physical deletes. Move to `.delete-pending/`, record and report; admin deletes manually |
| Legacy | Keep v1–v4 templates archived; V5 does not simulate V4 filenames |
| Notify | Multi-channel pluggable; Feishu first implementation only |

### Critical assumptions (reopen design if falsified)

- Project exposes a callable verify entry, or task cards override acceptance commands.
- Repo has (or init creates) `dev` as integration branch.
- Admin can choose or switch mode at start/resume.
- Chinese docs are mirrors only; agents must not treat them as execution source.
- Each supported CLI can at least read/write the repo, run commands, and open short task sessions (native subagents optional; degrade to new session + task card).

## 3. Ratified decisions

| ID | Decision |
| --- | --- |
| 1b | Deliverable = template + rules + contracts + deterministic CLI/runner |
| 2c | Hybrid: runner + short orchestrator sessions + workers |
| 3b | Reopen execution model/state contracts; keep “implement after Spec finalization” product position |
| 4b | Cross-CLI contracts unified; adapters per CLI |
| 5d | Full design surface: execution + pluggable notify + Skill/init |
| 6c | Hard risk, acceptance gates, Spec conflicts require stop |
| 7a | Work units: Phase → Task |
| 8b | Truth: thin index + per-task cards |
| 9c | Spec authoring process optional; finalized format + validation mandatory |
| 10c | Skill thin entry + CLI real logic; shared for human/CI/agent |
| 11b | Notify = event enum + per-event channel/disturb routing |
| 12c | Worker: task-level acceptance + self-repair; Phase: full verify |
| 13c | Skip only when `skip_on_fail: true`; else repair exhausted → attention |
| — | Agent docs EN + ZH admin mirror; repair default 10; mode choose/switch; Git and `.delete-pending` rules above |

## 4. Scope

### In scope

- `template/v5`, English agent rules, Chinese admin mirrors
- Spec finalization contract + validation
- Phase/Task state contracts + issues ledger (blocked/skipped)
- CLI: init / update / check / status / notify-test (+ progression helpers as needed)
- staged/auto state machine, mode selection and resume switch
- Orchestrator/worker: minimum context packing, compact report format, done/stop rules
- Notify: event table + channel interface + Feishu adapter
- Skill (e.g. `nm-init-project-v5`) and `npx skills add`-aligned install notes
- Git and `.delete-pending` rules in AGENTS; static checks where feasible
- This resolution document under the V5 workflow tree

### Out of scope

- Production non-Feishu channels (interface + config hooks only)
- Forced unification of native multi-agent APIs across CLIs
- DB/SaaS as state truth; general agent OS / plugin marketplace
- Full multi-language runtime
- Unnecessary V4 filename/process emulation

### Execution defaults

- One work branch per Task (or orchestrator-defined unit), merge to `dev` before the next unit
- Delete only branches already merged into `dev`; never auto-delete `main`, `dev`, `release/*`, `hotfix/*`, unmerged, or in-review branches
- `progress` events non-disturbing by default; `attention` disturbing (configurable)
- Self-repair max attempts: **10**

## 5. Solution outline

1. **Disk state machine** is the only recovery truth; sessions are disposable.
2. **Hybrid orchestration**: runner advances gates/notify; orchestrator session splits Phase/Task, builds minimum context packs, dispatches workers; workers implement → test → self-repair ≤10 → update task card → compact report.
3. **Modes**: unspecified → choose before run; resume may switch; on conflict, explain options first.
4. **Failure**: default after 10 repairs → attention; `skip_on_fail: true` → ledger + continue (auto) + `task_skipped` event.
5. **Context packing**: never dump the whole repo into a worker; pack goal, path bounds, spec slice pointers, acceptance commands, global prohibitions.
6. **Notify**: stable event producers; Feishu is first channel; dual groups are routing config, not architecture.
7. **Skill/CLI**: logic in CLI; skill invokes same commands; distribution follows skills ecosystem habits.
8. **Git / delete**: integrate on `dev`, work on branches, clean merged branches carefully; deletes only via `.delete-pending`.
9. **Docs**: EN = agent source of truth; ZH = administrator mirror.

### Rejected paths (recorded)

- Long-lived main agent that steers by conversation memory alone
- Treating “two Feishu groups” as architecture instead of event severity routing
- Skill-only without deterministic CLI
- Auto mode skipping hard failures without explicit `skip_on_fail`

## 6. Risks and defaults

| Risk | Mitigation |
| --- | --- |
| Uneven subagent support across CLIs | Worker contract + degrade to new session + task card |
| Orchestrator context still grows | Short sessions; read index + current phase summary only |
| EN/ZH drift | Paired updates; check warns missing mirror |
| Merge conflicts on frequent task merges | Conflict → attention; no silent force |
| Wrong branch deletion | Delete only if merged into `dev`; else report |
| `skip_on_fail` abuse | Default false; use only for optional tasks |
| Hot mode switch | Inspect in-flight tasks/unmerged branches; explain before change |

## 7. Acceptance for the V5 product in nm-docs

- [ ] `template/v5` + manifest coherent; `nm_v5.py check` passes
- [ ] Finalized Spec example validates; invalid Spec rejected
- [ ] Index + task cards express mode, progress, blocked/skipped; interrupt/resume documented
- [ ] CLI init/update/check/status/notify-test scriptable
- [ ] Skill installable and calls the same CLI
- [ ] Feishu progress/attention (or equivalent events) sendable; distinct webhooks configurable
- [ ] EN agent rules + ZH mirrors cover repair-10, skip_on_fail, mode choose/switch, Git, `.delete-pending`
- [ ] Prior template versions retained; README recommends V5 when switched

### Runtime “done correctly”

Given a finalized Spec, admin can select mode and the system progresses to merge into `dev` or stops clearly on attention / ledger items.

## 8. Document control

| Field | Value |
| --- | --- |
| Document version | **v1** |
| Status | Ratified 2026-07-09 |
| Next change | Create `RESOLUTION-V5-DESIGN-v2.md` (do not silently rewrite v1 intent without versioning) |
| Admin mirror | `RESOLUTION-V5-DESIGN-v1.zh-CN.md` |
