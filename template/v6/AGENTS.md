# NM V6 Agent Invariants

`AGENTS.md` is the English execution source. `AGENTS.zh-CN.md` is the complete
Simplified Chinese administrator mirror. If they differ, stop and repair both.

- The SQLite database at `.nm/runtime/v6/state.sqlite3` is the only mutable
  workflow authority. Markdown, JSON projections, prompts, notifications,
  conversations, and agent reports are not state.
- Only the deterministic reducer may commit state transitions. Workers return
  versioned proposals or observations and never write the database.
- A hard gate passes only from core-collected or core-verified evidence. Exit
  code zero and agent self-report are advisory.
- Workers never receive protected-ref write authority, remote push credentials,
  release/deploy credentials, trusted signing capabilities, or authoritative
  Git metadata.
- Normal work starts from the exact fetched `origin/dev` on an allowed task
  branch. Stable and `dev` are protected. Hotfixes require explicit trusted
  authorization and start from the exact fetched stable revision.
- Protected/external mutations require both their technical gate and a valid
  staged approval or scoped auto grant. A mode or prompt is not authorization.
- Secrets are named references, injected only into the minimum deterministic
  action, and excluded from prompts, projections, notifications, evidence, and
  ordinary logs.
- Interrupted external operations are observed and reconciled before retry,
  pause, cancellation, or recovery. Unknown state requires attention.
- Project files are never physically deleted by agents; move proposed removals
  to `.delete-pending/` for administrator review.
- Run `npm run workflow:check`, `npm run workflow:test`, and `npm run verify`
  before requesting acceptance. These checks are evidence inputs, not
  administrator acceptance.

Detailed workflow, protocols, and recovery references live under
`0c-workflow/` and load only when the current task or failure class needs them.
