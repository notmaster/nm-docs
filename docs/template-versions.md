# Template Versions

## Recommended: V3

Use `template/v3` for new projects and workflow updates.

V3 is goal-driven and keeps persistent project facts in files:

- `0a-docs/0a-product/REQUIREMENTS.md`
- `0a-docs/0a-product/ACCEPTANCE.md`
- `0a-docs/0b-design/DESIGN.md`
- `0b-goals/0a-plans/`
- `0b-goals/0b-current/`
- `0b-goals/0c-archive/`

Use `skills/nm-init-project-v3` or `tools/nm-v3/nm_v3.py`.

## Previous: V2

`template/v2` contains the earlier multi-agent collaboration workflow with TODO files, PR review gates, and heavier orchestration rules.

Keep V2 for existing projects that already depend on it. Prefer V3 for new projects unless a project explicitly needs the V2 multi-agent PR workflow.

## Legacy: V1

The `template/temp-*` files are legacy base templates. They are retained for compatibility and reference only.
