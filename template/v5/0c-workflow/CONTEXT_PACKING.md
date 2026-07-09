# Context Packing (NM V5)

## Principle

Worker context is scarce. Pack the **minimum sufficient** set for one Task.
Never attach the entire docs tree “just in case.”

## Orchestrator checklist before dispatch

1. Task goal (from task card)
2. `paths_allow` / `paths_deny`
3. Spec slices (section anchors or criterion IDs), not whole Spec unless tiny
4. Acceptance commands
5. Global prohibitions (branching, `.delete-pending`, secrets)
6. `must_read` file list (small)
7. Dependencies produced by prior tasks (paths + short note in index/handoff)

## Anti-patterns

- Pasting all of `0c-workflow/` into the worker prompt
- Attaching every prior task report in full
- Loading Chinese admin mirrors for execution
- Re-summarizing the whole project history in the orchestrator each turn — read `INDEX.yaml` instead

## Isolating context

Prefer: new session / subagent per Task with only the task card path + listed files.
If the CLI has no subagents, still start a **fresh session** with a short paste:

```text
Implement task card 0b-runtime/tasks/TASK-P01-01.md only.
Follow AGENTS.md. Do not expand scope. Report in the card's Report section.
```
