# Agent Recipes (NM V5)

Shared contracts; CLI-specific launch lines below. Prefer fresh sessions per Task.

## Mode choice (when index mode is unspecified)

```text
NM V5: INDEX mode is unspecified. Choose execution mode:
1) staged — stop after each Phase for admin acceptance, then merge and continue
2) auto — continue until hard-stop or authorized skip_on_fail
Reply with 1 or 2.
```

## Bootstrap after Spec confirmed

```text
Follow AGENTS.md (NM V5). Spec is confirmed at <SPEC_PATH>.
Create/update 0b-runtime/INDEX.yaml and task cards from the Spec.
If mode is unspecified, ask me to choose staged vs auto. Do not start implementation until mode is set and tasks exist.
```

## Orchestrator: dispatch one task

```text
You are the NM V5 orchestrator for one dispatch only.
Read 0b-runtime/INDEX.yaml and 0b-runtime/tasks/<TASK_ID>.md.
Build/confirm the minimum context pack on the task card.
Start a worker (subagent or instruct a new session) with only that task card.
On worker return: update INDEX, ledger if needed, merge rules per BRANCHING.md, notify-event if required.
Do not implement the task yourself unless worker tooling is unavailable.
```

## Worker

```text
Implement only 0b-runtime/tasks/<TASK_ID>.md.
Follow AGENTS.md. Stay inside paths_allow. Run acceptance; self-repair up to repair_max (10).
Update the task card Report section. Move deletes to .delete-pending/. Compact report only.
```

## staged Phase acceptance

```text
Phase <PHASE_ID> is awaiting acceptance. Summarize Result from INDEX/tasks.
If I accept: merge remaining work to dev if needed, mark phase done, start next phase (or finish).
If I reject: record feedback and reopen tasks.
```

## auto runner

```bash
python3 0d-scripts/run-workflow.py --agent codex --mode auto
python3 0d-scripts/run-workflow.py --agent claude --mode auto
python3 0d-scripts/run-workflow.py --agent grok --mode auto
```

## CLI notes

| CLI | Subagents | Degradation |
| --- | --- | --- |
| Claude Code | Prefer native subagents when available | Else new session + task card path |
| Codex | Prefer separate headless session per task | Same |
| GrokBuild | Prefer new session / subagent if available | Same |

Permissions: prefer non-interactive bypass only when admin authorized for auto; otherwise sandbox/workspace defaults of the CLI.
