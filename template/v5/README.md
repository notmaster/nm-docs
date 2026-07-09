# {{PROJECT_NAME}}

> **Status: Experimental (V5).** V5 is retained for supervised evaluation and
> existing trials only. Do not use it for unattended `auto`, automatic merge,
> release, deployment, production changes, production credentials, or
> production data. Runner exit success and built-in checks are diagnostic
> signals, not independent acceptance evidence. V6 is the planned replacement
> and is not implemented yet.

NM **V5** experimental workflow project.

- Agent rules (English): `AGENTS.md`
- Admin rules mirror: `AGENTS.zh-CN.md`
- Workflow: `0c-workflow/WORKFLOW_V5.md`
- Design resolution v1: `0c-workflow/resolutions/RESOLUTION-V5-DESIGN-v1.md`

## Supervised trial

1. Write and confirm a Spec under `0a-docs/0a-spec/` (`status: confirmed`).
2. Ask an agent to bootstrap `0b-runtime/INDEX.yaml` and task cards.
3. Use **staged** for a supervised trial. Test **auto** only in a disposable,
   non-production environment with no high-impact capability.
4. Run tasks (manual sessions or `python3 0d-scripts/run-workflow.py --agent <cli>`).

## Scripts

```bash
npm run workflow:check
npm run verify
npm run notify:event -- --event notify_test --severity progress --message "hello"
npm run notify:event -- --event notify_test --severity attention --message "needs eyes"
```

## Feishu (optional)

Machine-global config (not in this repo):

```text
~/.config/nm-docs/nm-notify-feishu.env   # mode 600
```

Progress vs attention can use separate webhooks; see `0c-workflow/NOTIFY_EVENTS.md`.
`0c-workflow/project-profile.yml` only names env vars—never secrets.

## Safety

- Work from `dev` branches; do not commit implementation on `dev` directly.
- Never physically delete files; use `.delete-pending/`.
