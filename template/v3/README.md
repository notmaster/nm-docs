# {{PROJECT_NAME}}

This project uses the NM V3.1 lightweight Goal workflow.

## Start Work

- Small change: create one standalone Goal from
  `0c-workflow/GOAL_TEMPLATE.md`.
- Planned change: optionally create `0a-docs/spec.md`, create a Plan from
  `0c-workflow/PLAN_TEMPLATE.md`, then create Goals just in time.
- Optional project documents are read only when the project-owned block in
  `AGENTS.md` lists them.

Create an optional spec through the deterministic tool:

```bash
python3 /path/to/nm-docs/tools/nm-v3/nm_v3.py create-spec --target . --source-dir /path/to/nm-docs
```

Send the final verified handoff once:

```bash
python3 /path/to/nm-docs/tools/nm-v3/nm_v3.py finish \
  --target . \
  --file 0b-goals/0a-plans/plan-p001-example.md
```

## Commands

```bash
npm install
npm run workflow:check
npm run verify
```

Notification events use strict progress and attention Feishu channels. Setup and
event IDs are documented in `0c-workflow/NOTIFY_EVENTS.md`. Final completion is
always an attention handoff. A live notification test requires explicit
administrator instruction.

## Workflow References

- `AGENTS.md`: durable execution rules and active project references.
- `0c-workflow/WORKFLOW_V3.md`: standalone and planned lifecycle.
- `0c-workflow/BRANCHING.md`: protected and task branch rules.
- `0c-workflow/VERIFY.md`: Goal and full verification boundaries.
- `0c-workflow/SPEC_TEMPLATE.md`: optional spec schema.
- `0c-workflow/PLAN_TEMPLATE.md`: Plan task packet.
- `0c-workflow/GOAL_TEMPLATE.md`: self-contained Goal packet.
- `0c-workflow/NOTIFY_EVENTS.md`: notification contract.
