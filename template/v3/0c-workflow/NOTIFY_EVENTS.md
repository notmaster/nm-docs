# Notification Events

NM V3 emits stable event IDs. Events route to one of two distinct Feishu
channels; free-form callers do not choose a conflicting severity.

## Event Catalog

| Event | Severity | Send when |
| --- | --- | --- |
| `work_started` | `progress` | Git preflight passed and Plan/Goal work began |
| `goal_integrated` | `progress` | A verified Goal was locally integrated into its Plan branch |
| `work_completed` | `attention` | All requested Goal/Plan work and required verification completed; administrator should review the result |
| `decision_required` | `attention` | A product, scope, permission, or authorization decision is required |
| `needs_replan` | `attention` | Material scope, acceptance, dependency, data, or security change occurred |
| `blocked` | `attention` | Safety, environment, dependency, or authority prevents progress |
| `validation_failed` | `attention` | Required verification remains failing when work must stop |
| `git_conflict` | `attention` | A conflict or moved ref prevents safe integration |
| `notify_test` | caller-selected | Administrator explicitly requested a delivery test |

Emit one event per material state transition. Do not send periodic heartbeats,
per-command events, or duplicates for unchanged state.

Final completion is always an attention event. It is a visible handoff to the
administrator, even when no error or additional authorization is required.

Channel routing and card meaning are independent: `work_completed` uses the
attention channel with a green completed card; decisions and replanning use
yellow; blockers, conflicts, and validation failures use red. Attention does
not imply failure.

## Strict Dual-Channel Routing

- `progress` uses `FEISHU_WEBHOOK_PROGRESS` and optional
  `FEISHU_SIGN_SECRET_PROGRESS`.
- `attention` uses `FEISHU_WEBHOOK_ATTENTION` and optional
  `FEISHU_SIGN_SECRET_ATTENTION`.
- Both webhooks are required and must be distinct.
- Attention never falls back to progress or a default webhook.
- Use two Feishu groups (or independently configured bots) when progress should
  be quiet and attention should alert; disturb behavior is a Feishu group setting.

Secrets live only in `~/.config/nm-docs/nm-notify-feishu.env`, mode `600`.
The sender parses an allowlisted `KEY=VALUE` format as data and never sources it
as shell code.

## Delivery

Each transition gets one bounded delivery attempt with a 10-second connection
timeout and 30-second total timeout. There is no automatic retry or background
queue. Record `sent` or `failed` in the Plan/Goal execution record without
recording webhook values. A failed attention event must be prominently reported
before the workflow stops for its original reason.

Final completion uses `nm_v3.py finish`. It validates the standalone Goal or
Plan state, suppresses a duplicate for the same unchanged subject, and records
the attempt in `.nm-template-state.json`.

## Smoke Test

A live smoke test is an external effect and requires explicit administrator
instruction:

```bash
./0d-scripts/notify-event.sh --event notify_test --severity progress \
  --title "[TEST] progress" --message "quiet channel"
./0d-scripts/notify-event.sh --event notify_test --severity attention \
  --title "[TEST] attention" --message "alert channel"
```
