# V5 Lifecycle (skill reference)

> **Experimental.** Use this lifecycle only for supervised evaluation or
> existing trials. The `auto` path is limited to disposable, non-production
> environments without high-impact capability. Built-in success signals are not
> independent acceptance evidence.

1. **Spec confirmed** under `0a-docs/0a-spec/` (`status: confirmed`).
2. **Bootstrap** `0b-runtime/INDEX.yaml` + `tasks/TASK-*.md`.
3. **Mode**: if unspecified, admin chooses `staged` or `auto`.
4. **Execute** Phase → Task with runner/orchestrator/workers.
5. **Task**: branch from `dev` → implement → accept (repair ≤10) → stage a
   candidate and stop for administrator-controlled integration to `dev`.
6. **Phase gate**: full `verify.sh`. staged waits; experimental auto may continue
   only inside its non-production sandbox.
7. **Stop**: hard risk, acceptance, Spec conflict, repair exhausted without `skip_on_fail`.
8. **Skip**: only `skip_on_fail: true` after 10 repairs (auto), ledger entry.
9. **Notify**: events via `notify-event.sh` (Feishu first). Dual channel: progress vs attention webhooks in `~/.config/nm-docs/nm-notify-feishu.env`; see project `0c-workflow/NOTIFY_EVENTS.md`.
10. **Docs**: English agent source; Chinese admin mirrors.

Ratified design: project file `0c-workflow/resolutions/RESOLUTION-V5-DESIGN-v1.md`.
