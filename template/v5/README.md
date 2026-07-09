# {{PROJECT_NAME}}

NM **V5** workflow project.

- Agent rules (English): `AGENTS.md`
- Admin rules mirror: `AGENTS.zh-CN.md`
- Workflow: `0c-workflow/WORKFLOW_V5.md`
- Design resolution v1: `0c-workflow/resolutions/RESOLUTION-V5-DESIGN-v1.md`

## Quick start

1. Write and confirm a Spec under `0a-docs/0a-spec/` (`status: confirmed`).
2. Ask an agent to bootstrap `0b-runtime/INDEX.yaml` and task cards.
3. If mode is unspecified, choose **staged** or **auto**.
4. Run tasks (manual sessions or `python3 0d-scripts/run-workflow.py --agent <cli>`).

## Scripts

```bash
npm run workflow:check
npm run verify
npm run notify:event -- --event notify_test --severity progress --message "hello"
```

## Safety

- Work from `dev` branches; do not commit implementation on `dev` directly.
- Never physically delete files; use `.delete-pending/`.
