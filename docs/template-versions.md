# Template Versions

## In Design: V6

V6 is not implemented yet. Its review-ready implementation contract is
`docs/nm-v6-workflow-spec.md`. Do not create `template/v6` until the
administrator confirms that Spec and authorizes implementation.

## Experimental: V5

`template/v5` is retained for supervised trials and repository maintenance. It
is not approved for unattended merge, release, deployment, production
credentials, or production data.

V5 is a hybrid orchestration workflow:

- Confirmed Spec under `0a-docs/0a-spec/`
- Runtime truth: `0b-runtime/INDEX.yaml` + `0b-runtime/tasks/TASK-*.md`
- Runner + short orchestrator sessions + workers with minimum context packs
- Modes: `staged` and `auto` (admin must choose if unspecified)
- Self-repair default 10; `skip_on_fail` only when explicit
- Event notifications (Feishu first); CLI + Skill install
- Agent docs English; Chinese admin mirrors
- Ratified design: `0c-workflow/resolutions/RESOLUTION-V5-DESIGN-v1.md` (document version **v1**)

Tools: `skills/nm-init-project-v5` or `tools/nm-v5/nm_v5.py`.

## Previous: V4

`template/v4` is the prior spec-driven workflow with `ROADMAP.md` and per-phase fresh sessions.

Keep V4 for existing projects that have not migrated. Do not migrate new
projects to V5 merely because it has the highest implemented version number.
Use `skills/nm-init-project-v4` or `tools/nm-v4/nm_v4.py`.

## Previous: V3

`template/v3` contains the goal-driven workflow with `REQUIREMENTS.md`,
`ACCEPTANCE.md`, `DESIGN.md`, and Plan/Goal files under `0b-goals/`.

## Previous: V2

`template/v2` contains the earlier multi-agent collaboration workflow with TODO files, PR review gates, and heavier orchestration rules.

## Legacy: V1

`template/v1` is retained for compatibility and reference only.
