# Template Versions

## Recommended: V4

Use `template/v4` for new projects and workflow updates.

V4 is spec-driven and keeps the running state in two files:

- `0a-docs/0a-spec/SPEC-<slug>-V<n>.md`: the administrator-owned Spec contract
  (requirements, decisions, phases, acceptance) with YAML frontmatter.
- `0b-goals/ROADMAP.md`: the single runtime state file (phase table, progress,
  handoff notes, manual acceptance backlog).

Each phase runs in a fresh agent session. Execution modes are `staged`
(per-phase administrator acceptance) and `auto` (unattended runner
`0d-scripts/run-goals.py` for Claude Code, Codex, and Grok).

Use `skills/nm-init-project-v4` or `tools/nm-v4/nm_v4.py`. The `update` command
also migrates V3 projects: superseded V3 framework files move to
`.delete-pending/v3-superseded/`, and old requirement documents stay in place
as Spec input material.

## Previous: V3

`template/v3` contains the goal-driven workflow with `REQUIREMENTS.md`,
`ACCEPTANCE.md`, `DESIGN.md`, and Plan/Goal files under `0b-goals/`.

Keep V3 for existing projects that have not migrated yet. Prefer V4 for new
projects. Use `skills/nm-init-project-v3` or `tools/nm-v3/nm_v3.py`.

## Previous: V2

`template/v2` contains the earlier multi-agent collaboration workflow with TODO files, PR review gates, and heavier orchestration rules.

Keep V2 for existing projects that already depend on it.

## Legacy: V1

`template/v1` contains the legacy base template that previously lived as `template/temp-*` files.

V1 is retained for compatibility and reference only. It is almost unused for current work; prefer V4 for new projects unless an existing project explicitly depends on V1.
