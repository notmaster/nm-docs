# Repository Work Notifications

`nm-docs` uses the dual-channel Feishu notification adapter maintained in the
V5 template for its own long-running AI maintenance work. The root entry points
are stable wrappers; reusing this adapter does not make the repository a V5
runtime or change V5's experimental status.

## Entry Points

Agents must emit structured events through the root event command:

```bash
npm run notify:event -- \
  --event stage_completed \
  --severity progress \
  --title "Repository stage completed" \
  --message "branch=feature/example completed=implementation next=verification risk=none"
```

`./0d-scripts/notify-admin.sh` is an internal compatibility layer used by the
event adapter. Agents should not call it directly or bypass event semantics with
free-form notifications.

## Repository Event Catalog

| Event | Severity | Send when |
| --- | --- | --- |
| `work_started` | `progress` | Preflight is complete and non-trivial work has begun |
| `stage_completed` | `progress` | A meaningful discovery, implementation, or verification stage changed state |
| `work_completed` | `progress` | Requested work and all required local validation are complete |
| `attention_required` | `attention` | An administrator decision, acceptance, or new authorization is required |
| `blocked` | `attention` | Safety, Git state, dependencies, or repeated technical failure prevent safe progress |
| `validation_failed` | `attention` | A required check remains failing when work must stop |
| `notify_test` | selected by caller | The administrator explicitly requests a live delivery test |

Emit exactly one event for each state transition and choose the most specific
event. `work_completed` replaces `stage_completed` for the final stage;
`validation_failed` replaces `blocked` for a required-check failure;
`attention_required` is for a non-error human gate, while `blocked` is for an
unsafe or technical hard stop.

Do not emit periodic heartbeats, one event per shell command, or duplicate events
for unchanged state. A stage report should identify the task or branch and state
what completed, the current status, the next action, and any material risk.

## Configuration And Routing

The adapter reads only the machine-local file:

```text
~/.config/nm-docs/nm-notify-feishu.env
```

The file must have mode `600`. The root repository uses the V5 defaults:

- `FEISHU_WEBHOOK_PROGRESS` and optional `FEISHU_SIGN_SECRET_PROGRESS`
- `FEISHU_WEBHOOK_ATTENTION` and optional `FEISHU_SIGN_SECRET_ATTENTION`
- `FEISHU_WEBHOOK_URL` and `FEISHU_SIGN_SECRET` as single-channel fallbacks

Never put real webhook URLs or signing secrets in the repository, commands,
reports, tests, or notifications. Full Feishu setup and signature behavior remain
documented in
[the V5 notification reference](../template/v5/0c-workflow/NOTIFY_EVENTS.md).

## Validation

Run the isolated local check after changing the root wrappers or the reused V5
adapter:

```bash
npm run notify:check
```

The check uses a temporary home directory, dummy webhook values, a hostile
`.curlrc`, and a fake `curl`. It verifies the repository event catalog, progress
and attention routing, signed payload structure, bounded curl options, unsafe
config rejection, transport failure, and Feishu error handling without network
delivery or access to the real local configuration.

A live `notify_test` sends an external message and should run only when the
administrator explicitly requests delivery validation.

## Boundaries

- Notifications report status; they never grant acceptance or authorization.
- A notification failure must be reported, but does not roll back or invalidate
  already completed engineering work.
- Do not fall back to the system-level `nm-notify-feishu` skill without explicit
  administrator authorization; it uses a different configuration and bypasses
  the repository event entry point.
- Delivery is event-driven. Each attempt disables user curl configuration, uses
  non-argv channels for the webhook URL and payload, uses a 10-second connection
  timeout and a 30-second total timeout, and is not retried automatically. There
  is no periodic heartbeat, crash supervisor, retry queue, deduplication, or
  durable outbox in this integration.
