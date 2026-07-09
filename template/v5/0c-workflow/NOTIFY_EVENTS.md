# Notification Events (NM V5)

Producers emit **event IDs**. Channels (Feishu first) map events to webhooks
and disturb settings. Two Feishu groups are a valid **routing config**, not a
required architecture.

## Event catalog

| event_id | severity | Typical use |
| --- | --- | --- |
| `workflow_started` | progress | Mode chosen, run started |
| `mode_selection_required` | attention | Mode unspecified |
| `mode_switch_conflict` | attention | Resume mode switch conflicts with state |
| `phase_started` | progress | Phase entered |
| `phase_completed` | progress | Phase verify passed (auto continues) |
| `phase_awaiting_acceptance` | attention | staged gate |
| `task_completed` | progress | Optional fine-grained progress |
| `task_skipped` | attention | skip_on_fail path used |
| `repair_exhausted` | attention | 10 repairs failed |
| `blocked` | attention | Hard stop / needs admin |
| `need_review` | attention | Spec conflict, product choice |
| `git_conflict` | attention | Unsafe merge |
| `workflow_completed` | attention | All phases done |
| `notify_test` | progress | CLI notify-test |

## Severity

- `progress` — monitoring stream; default non-disturbing channel
- `attention` — admin must see; default disturbing channel

## CLI

```bash
./0d-scripts/notify-event.sh \
  --event phase_awaiting_acceptance \
  --severity attention \
  --title "Phase P01 ready" \
  --message "Accept or request changes."
```

## Feishu config (first channel)

Project may use `~/.config/nm-docs/nm-notify-feishu.env` (see notify scripts).

Optional split:

- `FEISHU_WEBHOOK_PROGRESS` / progress secret
- `FEISHU_WEBHOOK_ATTENTION` / attention secret

If only one webhook exists, both severities use it.

## Future channels

Implement adapters that accept `(event_id, severity, title, message, project)`.
Do not change event producers when adding Slack/email/etc.
