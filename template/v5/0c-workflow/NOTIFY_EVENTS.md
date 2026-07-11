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

| severity | Purpose | Feishu routing |
| --- | --- | --- |
| `progress` | Monitoring stream; usually non-disturbing | Prefer progress webhook |
| `attention` | Admin must see; usually disturbing | Prefer attention webhook |

`notify-event.sh` keeps routing and outcome semantics separate:

- `progress` and `attention` select the configured delivery channel;
- completed workflow events use card level `completed` (green), including when
  they require the attention channel for a visible handoff;
- administrator decisions use `action_required` (yellow);
- skipped work uses `warning` (yellow);
- blockers, conflicts, exhausted repair, and validation failures use `error`
  (red).

Card layout is built-in (title, project, message, optional “next step”). There is
**no per-event message template file** to configure.

## CLI

```bash
./0d-scripts/notify-event.sh \
  --event phase_awaiting_acceptance \
  --severity attention \
  --title "Phase P01 ready" \
  --message "Accept or request changes."

# Dual-channel smoke test
./0d-scripts/notify-event.sh --event notify_test --severity progress \
  --title "[TEST] progress" --message "quiet channel"
./0d-scripts/notify-event.sh --event notify_test --severity attention \
  --title "[TEST] attention" --message "alert channel"

# Or via npm / nm_v5
npm run notify:event -- --event notify_test --severity progress --message "hello"
python3 /path/to/nm-docs/tools/nm-v5/nm_v5.py notify-test --target . --severity attention
```

## Feishu configuration

### What lives where

| Location | Role |
| --- | --- |
| `~/.config/nm-docs/nm-notify-feishu.env` | **Secrets**: webhooks + signing secrets (machine-global, mode `600`) |
| `0c-workflow/project-profile.yml` | **Names only**: which env var names this project uses for progress/attention |
| `0d-scripts/nm-notify-feishu.sh` | Sender: selects channel by `--severity`, signs payload, posts card |

- Do **not** put webhook URLs or secrets in the repo or in `project-profile.yml`.
- One global env file serves **all** NM projects on the machine. New projects do
  not need a new Feishu config unless they need different bots.
- `FEISHU_PROJECT_NAME` is optional display override for the card line `项目：…`.
  Prefer omitting it so each repo uses its git root directory name. Do not list
  every project name in the env file.

### Env file (`~/.config/nm-docs/nm-notify-feishu.env`)

```bash
chmod 600 ~/.config/nm-docs/nm-notify-feishu.env
```

Example:

```bash
# Fallback when a severity-specific webhook is unset
FEISHU_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/xxxx"
FEISHU_SIGN_SECRET="xxxx"

# Dual channel (recommended for quiet progress vs alert attention)
FEISHU_WEBHOOK_PROGRESS="https://open.feishu.cn/open-apis/bot/v2/hook/progress-xxxx"
FEISHU_SIGN_SECRET_PROGRESS="xxxx"

FEISHU_WEBHOOK_ATTENTION="https://open.feishu.cn/open-apis/bot/v2/hook/attention-xxxx"
FEISHU_SIGN_SECRET_ATTENTION="xxxx"

# Optional; omit for multi-project machines
# FEISHU_PROJECT_NAME="my-project"
```

| Variable | Required | Meaning |
| --- | --- | --- |
| `FEISHU_WEBHOOK_URL` | If no split URLs | Default / fallback webhook |
| `FEISHU_SIGN_SECRET` | If bot uses签名校验 and no split secret | Default / fallback signing secret |
| `FEISHU_WEBHOOK_PROGRESS` | Optional | Webhook for `severity=progress` |
| `FEISHU_SIGN_SECRET_PROGRESS` | Optional | Secret for progress bot |
| `FEISHU_WEBHOOK_ATTENTION` | Optional | Webhook for `severity=attention` |
| `FEISHU_SIGN_SECRET_ATTENTION` | Optional | Secret for attention bot |
| `FEISHU_PROJECT_NAME` | Optional | Card project label override |

Routing in `nm-notify-feishu.sh`:

1. Resolve severity from `--severity` (or infer from `--level` on legacy calls).
2. Load progress or attention env vars (names overridable via `project-profile.yml`).
3. If that severity’s webhook is empty → use `FEISHU_WEBHOOK_URL` + `FEISHU_SIGN_SECRET`.
4. If severity webhook is set but secret empty → use `FEISHU_SIGN_SECRET`.

Single-webhook setups: only set `FEISHU_WEBHOOK_URL` (+ secret). Both severities
share one bot; card color still differs by level.

### Signature (签名校验)

When a secret is present, the script sends Feishu custom-bot signature fields:

```text
timestamp = unix seconds
string_to_sign = timestamp + "\n" + secret
sign = base64(HMAC-SHA256(key=string_to_sign, message=""))
```

JSON body includes top-level `timestamp` and `sign`. Enable **签名校验** on the
custom bot and put the same secret in the env file. Common failure: `sign match fail`.

### Delivery safety and bounds

The sender disables user `curl` configuration, passes the card payload through
standard input and the webhook URL through a dedicated file descriptor instead
of process arguments, and limits each attempt to a 10-second connection timeout
and 30-second total timeout. It makes one delivery attempt; notification failure
is reported to the calling workflow without an automatic retry.

### Project profile (`0c-workflow/project-profile.yml`)

Declares channel type and **env variable names** (not values):

```yaml
notify:
  channels:
    - type: feishu
      progress_webhook_env: FEISHU_WEBHOOK_PROGRESS
      attention_webhook_env: FEISHU_WEBHOOK_ATTENTION
      # optional overrides:
      # progress_secret_env: FEISHU_SIGN_SECRET_PROGRESS
      # attention_secret_env: FEISHU_SIGN_SECRET_ATTENTION
```

- Defaults match the names above if keys are omitted.
- Secret env names are derived as `WEBHOOK` → `SIGN_SECRET` when only webhook
  keys are set (e.g. `FEISHU_WEBHOOK_PROGRESS` → `FEISHU_SIGN_SECRET_PROGRESS`).
- Per-project profile does **not** replace the global env; new projects usually
  keep the template defaults and reuse the same machine env.

### Quiet vs popup (disturb)

Feishu custom bots cannot toggle system notification per message. To get
**quiet progress** and **alerting attention**:

1. Prefer **two groups** (or two bots with distinct user notification settings).
2. Mute / non-disturb the progress group; keep notifications on for attention.
3. Point `FEISHU_WEBHOOK_PROGRESS` and `FEISHU_WEBHOOK_ATTENTION` at those bots.

Same-group two bots usually share the group’s mute state—two groups work better.

### Feishu console checklist

1. Group → bots → custom bot → copy Webhook URL.
2. Enable **签名校验**, copy secret.
3. Paste into `~/.config/nm-docs/nm-notify-feishu.env`, `chmod 600`.
4. Run progress and attention smoke tests; confirm messages land in the right group.

### Relation to `nm-notify-feishu` skill

`~/.config/notify-feishu/config.json` is for the **skill** helper
(`~/.agents/skills/nm-notify-feishu/scripts/notify.sh`). NM V5 workflow
notifications use **only** `~/.config/nm-docs/nm-notify-feishu.env` and
`0d-scripts/nm-notify-feishu.sh`. Do not bypass project scripts with the skill
unless the administrator explicitly allows a fallback.

## Future channels

Implement adapters that accept `(event_id, severity, title, message, project)`.
Do not change event producers when adding Slack/email/etc.
